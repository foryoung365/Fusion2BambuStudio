"""Fusion Python add-in entry point. All scene access stays on Fusion's UI thread."""
import json
import traceback
from pathlib import Path
from urllib.parse import urlparse, unquote
import adsk.core
import adsk.fusion
from .fusion_adapter.bridge import Controller
from .core.geometry import face_down
from .fusion_adapter.native_ui import NativeDialog

COMMAND = 'BambuPlateStudio_Show'
FACE_COMMAND = 'BambuPlateStudio_FaceDown'
PALETTE = 'BambuPlateStudio_Palette'
NATIVE_COMMAND = 'BambuPlateStudio_Native'
handlers = []
controller = None
pending_unit = None
event_log = []
last_view_capture = None
native_dialog = None


def emit_state():
    palette = adsk.core.Application.get().userInterface.palettes.itemById(PALETTE)
    if palette and palette.isValid:
        palette.sendInfoToHTML('state', json.dumps(controller.state(), ensure_ascii=False))


class HtmlHandler(adsk.core.HTMLEventHandler):
    def notify(self, args):
        global last_view_capture
        args = adsk.core.HTMLEventArgs.cast(args)
        if args.action != 'request':
            if args.action == 'palette_refresh':
                palette=adsk.core.Application.get().userInterface.palettes.itemById(PALETTE)
                if palette and palette.isValid and palette.isVisible:
                    palette.isVisible=False
                    palette.isVisible=True
                event_log.append({'action':'palette_refresh','visible':bool(palette and palette.isValid and palette.isVisible)})
                args.returnData='OK'
                return
            if args.action == 'response':
                try:
                    result=json.loads(json.loads(args.data)['data'])
                    if isinstance(result,dict) and isinstance(result.get('image'),str) and result['image'].startswith('data:image/png;base64,') and len(result['image'])<20_000_000:
                        last_view_capture=result
                        event_log.append({'action':'view_capture','mode':result.get('mode')})
                        return
                except (ValueError,KeyError,TypeError):
                    pass
            event_log.append({'action': args.action, 'data': str(args.data)[:4000]})
            return
        try:
            request = json.loads(args.data)
            state = controller.dispatch(request['action'], request.get('data', {}))
            args.returnData = json.dumps({'ok': True, 'state': state}, ensure_ascii=False)
            event_log.append({'action': request['action'], 'ok': True})
        except Exception as exc:
            # UI event boundaries must report errors, not silently swallow them.
            confirmation=getattr(exc,'confirmation',None)
            event_log.append({'action':'confirmation_required',**confirmation} if confirmation else
                             {'action':'error','error':traceback.format_exc()})
            args.returnData = json.dumps({'ok': False, 'error': str(exc),
                                         'confirmation':getattr(exc,'confirmation',None)}, ensure_ascii=False)


class FaceExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            controller.assert_document()
            command = args.firingEvent.sender
            selection = command.commandInputs.itemById('face')
            if selection.selectionCount != 1:
                raise ValueError('请选择一个平面。')
            face = adsk.fusion.BRepFace.cast(selection.selection(0).entity)
            unit = controller.session.units[pending_unit]
            normal = controller.source.normal_for_face(face, unit, controller.session)
            unit.rotation = face_down(normal)
            unit.face_token, unit.orientation_label = face.entityToken, '所选平面朝下'
            unit.orientation_valid = True
            unit.orientation_locked = True
            controller.orientation_preview=None;controller.orientation_snapshot=None
            controller.session.invalidate_layout()
            emit_state()
        except Exception as exc:
            args.executeFailed, args.executeFailedMessage = True, str(exc)
            event_log.append({'action': 'face_error', 'error': traceback.format_exc()})


class FaceCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        selection = args.command.commandInputs.addSelectionInput('face', '贴板面', '请选择当前打印单元上的平面')
        selection.addSelectionFilter('PlanarFaces')
        selection.setSelectionLimits(1, 1)
        handler = FaceExecute()
        args.command.execute.add(handler)
        handlers.append(handler)


class NavigationHandler(adsk.core.NavigationEventHandler):
    def notify(self, args):
        args = adsk.core.NavigationEventArgs.cast(args)
        target = urlparse(args.navigationURL)
        local = (Path(__file__).parent / 'ui').resolve()
        path = Path(unquote(target.path).lstrip('/') if __import__('os').name == 'nt' else unquote(target.path))
        allowed = target.scheme == 'file' and path.resolve().parent == local
        args.preventDefault = not allowed


def choose_face(uid):
    global pending_unit
    if uid not in controller.session.units:
        raise ValueError('打印单元已失效。')
    pending_unit = uid
    adsk.core.Application.get().userInterface.commandDefinitions.itemById(FACE_COMMAND).execute()


def show_palette():
    ui = adsk.core.Application.get().userInterface
    palette = ui.palettes.itemById(PALETTE)
    if not palette:
        url = (Path(__file__).parent / 'ui' / 'index.html').resolve().as_uri()
        palette = ui.palettes.add(PALETTE, 'MF3D打印摆盘助手', url, True, True, True, 1460, 920, True)
        palette.dockingOption = adsk.core.PaletteDockingOptions.PaletteDockOptionsNone
        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateFloating
        palette.setMinimumSize(1020,680)
        handler = HtmlHandler()
        palette.incomingFromHTML.add(handler)
        handlers.append(handler)
        navigation = NavigationHandler()
        palette.navigatingURL.add(navigation)
        handlers.append(navigation)
    palette.isVisible = True
    return palette


class ShowExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        show_palette()


class ShowCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        handler = ShowExecute()
        args.command.execute.add(handler)
        handlers.append(handler)


class NativeCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        global native_dialog
        try:
            args = adsk.core.CommandCreatedEventArgs.cast(args)
            native_dialog = NativeDialog(args.command, controller, handlers)
            event_log.append({'action': 'native_created', 'ok': True})
        except Exception:
            event_log.append({'action': 'native_create_error', 'error': traceback.format_exc()})


def run(context):
    global controller
    ui = adsk.core.Application.get().userInterface
    if controller is None:
        controller = Controller()
    controller.choose_face = choose_face
    for uid, title, handler in ((COMMAND, 'MF3D打印摆盘助手', ShowCreated()),
                                (NATIVE_COMMAND, 'MF3D打印摆盘助手（兼容界面）', NativeCreated()),
                                (FACE_COMMAND, '指定贴板平面', FaceCreated())):
        definition = ui.commandDefinitions.itemById(uid)
        if not definition:
            definition = ui.commandDefinitions.addButtonDefinition(uid, title, title)
            definition.commandCreated.add(handler)
            handlers.append(handler)
    panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
    if panel and not panel.controls.itemById(COMMAND):
        panel.controls.addCommand(ui.commandDefinitions.itemById(COMMAND))
    if not isinstance(context,dict) or context.get('showUI',True):
        workspace=ui.workspaces.itemById('FusionSolidEnvironment')
        if workspace:workspace.activate()
        ui.commandDefinitions.itemById(COMMAND).execute()


def stop(context):
    global controller
    ui = adsk.core.Application.get().userInterface
    if controller:
        controller.clear_preview()
        controller.close()
    palette = ui.palettes.itemById(PALETTE)
    if palette: palette.deleteMe()
    panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
    if panel:
        for uid in (COMMAND, NATIVE_COMMAND):
            control = panel.controls.itemById(uid)
            if control: control.deleteMe()
    for uid in (COMMAND, FACE_COMMAND, NATIVE_COMMAND):
        definition = ui.commandDefinitions.itemById(uid)
        if definition: definition.deleteMe()
    handlers.clear()
    controller = None
