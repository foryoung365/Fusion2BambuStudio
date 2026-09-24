import hashlib
import json
import math
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import adsk.core
import adsk.fusion
from ..core.geometry import IDENTITY, multiply, rotate, face_down, axis_rotation, cross, unit, dot
from ..core.model import Body, Session, Plate, new_id
from ..core.layout import Bed, arrange, validate, footprint, process_clearance, auto_brim_reserve
from ..core.profiles import ProfileCatalog, discover, profile_roots_for, BEDS
from ..core.package3mf import write_project
from ..core.bambu import export_native
from ..core.inputs import config_change, placement_change, color_hex
from ..core.visual_edit import EditHistory, merge_onto, transfer_to_plate, check_mixed_transfer, approve_plate
from ..core.auto_orient import suggest, suggest_many, apply_rotation
from ..core.auto_place import suggest as suggest_positions, apply_positions

ATTRIBUTE_GROUP = 'BambuPlateStudio'
ATTRIBUTE_NAME = 'printingRules.v1'
AFFINE_IDENTITY = ((1.,0.,0.,0.), (0.,1.,0.,0.), (0.,0.,1.,0.), (0.,0.,0.,1.))


def rows(matrix):
    flat = matrix.asArray()
    return tuple(tuple(flat[r*4+c] for c in range(4)) for r in range(4))


def read_color(appearance):
    if not appearance:
        return ''
    for key in ('metal_f0', 'opaque_albedo', 'layered_diffuse', 'generic_diffuse', 'surface_albedo'):
        value = adsk.core.ColorProperty.cast(appearance.appearanceProperties.itemById(key))
        if value and value.value:
            color = value.value
            return '#%02X%02X%02X' % (color.red, color.green, color.blue)
    return ''


class FusionSource:
    def __init__(self, document):
        self.document = document
        self.design = adsk.fusion.Design.cast(document.products.itemByProductType('DesignProductType'))
        if not self.design:
            raise ValueError('当前文档不是 Fusion 设计。')
        self.entities = {}

    def scan(self, include_hidden=False, refinement='high'):
        self.entities = {}
        result = []

        def body(native, occurrence, world):
            proxy = native.createForAssemblyContext(occurrence) if occurrence else native
            if not include_hidden and not proxy.isVisible:
                return
            if adsk.fusion.BRepBody.cast(native):
                if not native.isSolid:
                    return
                calculator = native.meshManager.createMeshCalculator()
                quality = (adsk.fusion.TriangleMeshQualityOptions.HighQualityTriangleMesh if refinement == 'high'
                           else adsk.fusion.TriangleMeshQualityOptions.NormalQualityTriangleMesh)
                calculator.setQuality(quality)
                mesh = calculator.calculate()
            else:
                mesh = native.mesh
            if not mesh:
                raise ValueError('无法网格化：'+native.name)
            token = proxy.entityToken
            path = occurrence.fullPathName if occurrence else self.design.rootComponent.name
            uid = hashlib.sha256((path+'\n'+token).encode()).hexdigest()[:24]
            numbers, indices = mesh.nodeCoordinatesAsDouble, mesh.nodeIndices
            vertices = [tuple(10*(sum(world[r][c]*numbers[i+c] for c in range(3))+world[r][3])
                              for r in range(3)) for i in range(0, len(numbers), 3)]
            triangles = [tuple(int(v) for v in indices[i:i+3]) for i in range(0, len(indices), 3)]
            face_colors = {}
            if adsk.fusion.BRepBody.cast(proxy):
                for face in proxy.faces:
                    color = read_color(face.appearance)
                    face_colors[color] = face_colors.get(color, 0)+face.area*100
            color = read_color(proxy.appearance)
            record = Body(uid, native.name, path, color, vertices, triangles, token, face_colors)
            record.validate()
            result.append(record)
            self.entities[uid] = {'proxy': proxy, 'native': native, 'occurrence': occurrence, 'world': world}

        def component(comp, occurrence, world):
            for native in comp.bRepBodies:
                body(native, occurrence, world)
            for native in comp.meshBodies:
                body(native, occurrence, world)
            for native_occ in comp.occurrences:
                proxy = native_occ.createForAssemblyContext(occurrence) if occurrence else native_occ
                if not include_hidden and not proxy.isVisible:
                    continue
                component(native_occ.component, proxy, multiply(world, rows(native_occ.transform2)))

        component(self.design.rootComponent, None, AFFINE_IDENTITY)
        if not result:
            raise ValueError('当前范围中没有可打印的实体或网格。请检查可见性。')
        return result

    def aliases_for(self, rules):
        aliases = {}
        # Resolve Fusion's saved entity tokens rather than assuming token strings are permanent.
        for old in rules.get('sources', []):
            resolved = self.design.findEntityByToken(old['token']) if old.get('token') else []
            for entity in resolved:
                for uid, item in self.entities.items():
                    if entity == item['proxy'] or entity.entityToken == item['proxy'].entityToken:
                        aliases[old['uid']] = uid
        return aliases

    def normal_for_face(self, face, unit, session):
        body = face.body
        context = body.assemblyContext
        path = context.fullPathName if context else self.design.rootComponent.name
        native_body = body.nativeObject or body
        matches = [uid for uid in unit.members if session.bodies[uid].component_path == path and
                   self.entities[uid]['native'].entityToken == native_body.entityToken]
        if len(matches) != 1:
            raise ValueError('请选择当前打印单元中实体的平面。')
        native_face = face.nativeObject or face
        plane = adsk.core.Plane.cast(native_face.geometry)
        if not plane:
            raise ValueError('请选择平面，曲面不能唯一确定贴板方向。')
        normal = plane.normal.asArray()
        if native_face.isParamReversed:
            normal = [-v for v in normal]
        world = self.entities[matches[0]]['world']
        return rotate(tuple(row[:3] for row in world[:3]), normal)

    def face_for_triangle(self, body_uid, triangle_index, session):
        record = session.bodies[body_uid]
        if type(triangle_index) is not int or not 0 <= triangle_index < len(record.triangles):
            raise ValueError('选面数据已经失效，请重新读取模型。')
        source = self.entities[body_uid]
        native = source['native']
        if not adsk.fusion.BRepBody.cast(native):
            raise ValueError('当前模型为网格；请使用方向选项，或先转换为实体后点选平面。')
        points = [record.vertices[i] for i in record.triangles[triangle_index]]
        unit_vector = unit(cross(tuple(points[1][i]-points[0][i] for i in range(3)),
                                         tuple(points[2][i]-points[0][i] for i in range(3))))
        center = [sum(p[i] for p in points)/30 for i in range(3)]  # world cm
        world = source['world']
        offset = [center[i]-world[i][3] for i in range(3)]
        local = [sum(world[r][c]*offset[r] for r in range(3)) for c in range(3)]
        point = adsk.core.Point3D.create(*local)
        for face in native.faces:
            plane = adsk.core.Plane.cast(face.geometry)
            if not plane:continue
            n = plane.normal.asArray()
            if face.isParamReversed:n = [-v for v in n]
            outward = rotate(tuple(row[:3] for row in world[:3]), n)
            if dot(unit_vector,outward) < 1-1e-5:continue
            distance = abs(dot(plane.normal.asArray(), [local[i]-plane.origin.asArray()[i] for i in range(3)]))
            if distance > 1e-4:continue
            success, parameter = face.evaluator.getParameterAtPoint(point)
            if success and face.evaluator.isParameterOnFace(parameter):
                return face.createForAssemblyContext(source['occurrence']) if source['occurrence'] else face
        raise ValueError('此处不是可识别的平面，请旋转视图后选择平面区域。')


class Controller:
    def __init__(self):
        self.app = adsk.core.Application.get()
        self.session = Session()
        self.source = None
        self.exe, roots = discover()
        self.catalog = ProfileCatalog(roots) if roots else None
        self.notices, self.last_export = [], None
        self.choose_face = None
        self.on_update = None
        self.bed = None
        self.preview_group = None
        self.history = EditHistory()
        self.geometry_revision = 0
        self.orientation_preview = None
        self.orientation_snapshot = None
        self.arrangement_preview = None
        self.arrangement_snapshot = None
        self.preview_executor = None
        self.preview_job = None

    def clear_preview(self):
        if self.preview_group and self.preview_group.isValid:
            self.preview_group.deleteMe()
        self.preview_group=None

    def show_preview(self,plate=None):
        from .preview import draw
        return draw(self,plate)

    def assert_document(self):
        if not self.source or self.app.activeDocument != self.source.document:
            raise ValueError('当前文档已切换，请重新读取模型。')

    def scan(self):
        if not self.app.activeDocument:
            raise ValueError('请先打开需要导出的 Fusion 设计。')
        self.clear_preview()
        self.orientation_preview = None
        self.orientation_snapshot = None
        self.arrangement_preview = None
        self.arrangement_snapshot = None
        config = dict(self.session.config)
        memory_rules = (self.session.rules() if self.source and self.source.document == self.app.activeDocument
                        and self.session.bodies and not self.session.rule_errors else None)
        source = FusionSource(self.app.activeDocument)
        bodies = source.scan(config['includeHidden'], config['refinement'])
        session = Session(bodies)
        session.config.update(config)
        self.notices = []
        saved = source.design.attributes.itemByName(ATTRIBUTE_GROUP, ATTRIBUTE_NAME)
        if memory_rules or saved:
            rules = memory_rules or json.loads(saved.value)
            self.notices = session.apply_rules(rules, source.aliases_for(rules))
        self.source, self.session = source, session
        for unit in session.units.values():
            if not unit.face_token:continue
            try:
                resolved=source.design.findEntityByToken(unit.face_token)
                if len(resolved)!=1:raise ValueError('平面引用不再唯一')
                face=adsk.fusion.BRepFace.cast(resolved[0])
                if not face:raise ValueError('引用不再指向平面')
                normal=source.normal_for_face(face,unit,session)
                unit.rotation=face_down(normal);unit.orientation_valid=True
            except (ValueError,RuntimeError):
                unit.orientation_valid=False
                unit.orientation_label='贴板面引用失效，需要重新指定'
                self.notices.append('请重新指定贴板面：'+unit.name)
        self.last_export = None
        self.geometry_revision += 1
        self.history.clear()

    def viewport_data(self):
        self.assert_document()
        return {'revision':self.geometry_revision, 'bodies':[
            {'uid':b.uid,'vertices':b.vertices,'triangles':b.triangles}
            for b in self.session.bodies.values()]}

    def profile_state(self):
        if not self.catalog:
            return {'machines': [], 'processes': [], 'filaments': [], 'beds': {k:v[0] for k,v in BEDS.items()}, 'error': '未找到 Bambu Studio。'}
        machines = []
        for p in self.catalog.selectable('machine'):
            data = self.catalog.resolve('machine', str(p.path))
            if len(data.get('nozzle_diameter', [])) == 1:
                machines.append({'key': str(p.path), 'name': p.name, 'model': data.get('printer_model', p.name),
                                 'nozzle': data['nozzle_diameter'][0]})
        try:
            options = self.catalog.options(self.session.config['printer'])
            return dict(options, machines=machines, beds={k: v[0] for k, v in BEDS.items()})
        except ValueError as exc:
            return {'machines': machines, 'processes': [], 'filaments': [], 'beds': {k:v[0] for k,v in BEDS.items()}, 'error': str(exc)}

    def update_bed(self):
        if not self.catalog:
            raise ValueError('请指定本机 Bambu Studio 预设文件夹。')
        machine = self.catalog.resolve('machine', self.session.config['printer'])
        self.bed = Bed.from_profile(machine)
        process = self.catalog.resolve('process', self.session.config['process'])
        # Stored rules from older versions are not authoritative for process space.
        self.session.config['printClearance'] = process_clearance(process, self.session.config['enableSupport'])
        self.session.config['autoBrimReserve'] = auto_brim_reserve(process)

    def state(self, include_profiles=False):
        units = []
        for unit in self.session.units.values():
            _, _, size = unit.geometry(self.session.bodies)
            placement = self.session.placements.get(unit.uid)
            members = [{'uid': uid, 'name': self.session.bodies[uid].name,
                        'path': self.session.bodies[uid].component_path,
                        'color': self.session.effective_color(uid),
                        'mixedFaces': len(self.session.bodies[uid].face_colors) > 1,
                        'issues': self.session.bodies[uid].issues} for uid in unit.members]
            units.append({'uid': unit.uid, 'name': unit.name, 'members': members, 'size': size,
                          'rotation':unit.rotation,
                          'orientationLocked':unit.orientation_locked,
                          'direction': unit.orientation_label,
                          'placement': asdict(placement) if placement else None,
                          'rect': footprint(self.session, placement) if placement else None})
        errors, warnings = list(self.session.rule_errors), []
        if self.bed and self.session.placements:
            errors, warnings = validate(self.session, self.bed)
        result = {'document': self.source.document.name if self.source else '',
                  'config': self.session.config, 'units': units, 'plates': [asdict(p) for p in self.session.plates],
                  'bed': asdict(self.bed) if self.bed else None, 'errors': errors,
                  'warnings': warnings, 'notices': self.notices, 'lastExport': self.last_export,
                  'colorProfiles': self.session.color_profiles, 'exe': self.exe}
        result.update(geometryRevision=self.geometry_revision,canUndo=bool(self.history.undo_stack),
                      canRedo=bool(self.history.redo_stack),orientationPreview=self.orientation_preview,
                      arrangementPreview=self.arrangement_preview,
                      pendingPreview=self.pending_preview())
        if include_profiles:
            result['profiles'] = self.profile_state()
        return result

    def assert_source_current(self):
        self.assert_document()
        # Refuse stale geometry or colors; do not export an out-of-date captured model.
        fresh_source = FusionSource(self.app.activeDocument)
        fresh = fresh_source.scan(self.session.config['includeHidden'], self.session.config['refinement'])
        current = {b.uid: b for b in fresh}
        if set(current) != set(self.session.bodies) or any(
            current[uid].geometry_key() != body.geometry_key() or current[uid].color != body.color or
            current[uid].face_colors != body.face_colors for uid, body in self.session.bodies.items()):
            raise ValueError('源模型或颜色已改变，请重新读取并排盘后导出。')

    def pending_preview(self):
        job=getattr(self,'preview_job',None)
        if not job:return None
        return {'token':job['token'],'kind':job['kind'],'scope':job['scope'],
                'total':job['total'],'elapsedSeconds':time.monotonic()-job['started']}

    def start_preview(self,action,data):
        self.assert_document()
        if self.preview_job:raise ValueError('已有朝向或摆位建议正在计算，请等待完成。')
        scope=data.get('scope','unit' if action=='orientation_preview' else None)
        session=self.session
        if action=='orientation_preview':
            if scope=='unit':
                uid=data['unit']
                if uid not in session.units:raise ValueError('所选打印单元已失效。')
                work=suggest;arguments=(session,uid,self.catalog,self.exe);total=1
            elif scope in ('current','all'):
                if scope=='current':
                    number=data.get('plate')
                    if type(number) is not int or not any(p.index==number for p in session.plates):
                        raise ValueError('请选择有效的当前打印盘。')
                    plates=[number]
                else:plates=[p.index for p in session.plates if any(x.plate==p.index for x in session.placements.values())]
                selected=[uid for uid in session.units if uid in session.placements and session.placements[uid].plate in plates]
                if not selected:raise ValueError('所选范围没有已分盘的打印单元。')
                work=suggest_many;arguments=(session,selected,plates,self.catalog,self.exe);total=len(selected)
            else:raise ValueError('请选择所选件、当前盘或所有盘。')
        elif action=='arrangement_preview':
            if scope=='current':
                number=data.get('plate')
                if type(number) is not int or not any(p.index==number for p in session.plates):
                    raise ValueError('请选择有效的当前打印盘。')
                plates=[number]
            elif scope=='all':plates=[p.index for p in session.plates if any(x.plate==p.index for x in session.placements.values())]
            else:raise ValueError('请选择当前盘或所有盘。')
            if not plates:raise ValueError('没有可摆放的打印盘。')
            work=suggest_positions;arguments=(session,plates,self.catalog,self.exe);total=len(plates)
        else:raise ValueError('未知的预览类型。')
        snapshot=self.history.snapshot(session)
        if self.preview_executor is None:self.preview_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='MF3D_preview')
        self.orientation_preview=None;self.orientation_snapshot=None
        self.arrangement_preview=None;self.arrangement_snapshot=None
        token=new_id()
        future=self.preview_executor.submit(work,*arguments)
        self.preview_job={'token':token,'kind':action,'scope':scope,'total':total,
                          'started':time.monotonic(),'future':future,'session':session,
                          'snapshot':snapshot,'document':self.app.activeDocument,
                          'revision':self.geometry_revision}
        return {'pendingPreview':self.pending_preview()}

    def preview_status(self,data):
        job=self.preview_job
        if not job or data.get('token')!=job['token']:raise ValueError('预览计算已失效，请重新请求。')
        if self.app.activeDocument!=job['document']:
            self.preview_job=None
            raise ValueError('当前文档已切换，已丢弃朝向或摆位建议。')
        if not job['future'].done():return {'pendingPreview':self.pending_preview()}
        self.preview_job=None
        proposal=job['future'].result()
        if self.session is not job['session'] or self.geometry_revision!=job['revision'] or self.session.rules()!=job['snapshot']:
            raise ValueError('模型或打印规则已改变，已丢弃过期建议。')
        self.assert_source_current()
        proposal['token']=job['token'];proposal['scope']=job['scope']
        if job['kind']=='orientation_preview':
            self.orientation_preview=proposal;self.orientation_snapshot=job['snapshot']
            self.notices=['朝向建议已生成，尚未修改任何打印单元。请预览后确认。']
        else:
            self.arrangement_preview=proposal;self.arrangement_snapshot=job['snapshot']
            self.notices=['Bambu 分盘与摆位建议已生成，尚未修改盘位。请预览后确认。']
        return self.state()

    def close(self):
        if self.preview_executor:self.preview_executor.shutdown(wait=False,cancel_futures=True)
        self.preview_executor=None;self.preview_job=None

    def export_to(self, path, overwrite=False):
        self.assert_source_current()
        self.update_bed()
        with tempfile.TemporaryDirectory(prefix='BambuPlateStudio_seed_') as temporary:
            seed=Path(temporary)/'seed.3mf'
            write_project(seed, self.session, self.catalog)
            self.last_export=export_native(seed,path,self.catalog,self.exe,overwrite=overwrite)
        return self.last_export

    def dispatch(self, action, data):
        if action=='preview_status':return self.preview_status(data)
        if action in ('orientation_preview','arrangement_preview') and data.get('background') is True:
            return self.start_preview(action,data)
        if getattr(self,'preview_job',None) and action not in ('bootstrap','viewport_data'):
            raise ValueError('正在计算朝向或摆位建议，请等待完成。')
        if action == 'viewport_data':return self.viewport_data()
        if action in ('undo','redo'):
            self.assert_document()
            self.history.restore(self.session,action=='undo')
            self.update_bed();self.last_export=None;self.notices=[]
            self.orientation_preview=None;self.orientation_snapshot=None
            self.arrangement_preview=None;self.arrangement_snapshot=None
            return self.state(True)
        edits={'group','ungroup','group_drop','rename_unit','direction','viewer_face','body_color','color_profile',
               'arrange','move','transfer_plate','add_plate','delete_plate','config','reset_units',
               'orientation_lock','orientation_apply','arrangement_apply'}
        before=self.history.snapshot(self.session) if action in edits and self.session.bodies else None
        previous_bed=self.bed
        try:
            result=self._dispatch(action,data)
        except Exception:
            if before is not None:
                self.session.apply_rules(before)
                self.bed=previous_bed
            raise
        if before is not None:
            self.history.commit(before,self.session);self.last_export=None
            self.orientation_preview=None;self.orientation_snapshot=None
            self.arrangement_preview=None;self.arrangement_snapshot=None
            result.update(canUndo=bool(self.history.undo_stack),canRedo=bool(self.history.redo_stack),
                          lastExport=None,orientationPreview=None,arrangementPreview=None)
        return result

    def _dispatch(self, action, data):
        if action == 'bootstrap':
            return self.state(True)
        if action == 'installation':
            exe=Path(data['executable']).expanduser().resolve()
            if exe.name.lower() not in ('bambu-studio.exe','bambustudio','bambu-studio'):
                raise ValueError('请选择 Bambu Studio 的可执行程序。')
            roots=profile_roots_for(exe)
            if not roots:raise ValueError('程序不存在，或相邻位置没有 Bambu 预设资源目录。')
            catalog=ProfileCatalog(roots)
            self.exe,self.catalog=str(exe),catalog
            self.history.clear();self.last_export=None
            self.orientation_preview=None;self.orientation_snapshot=None
            self.arrangement_preview=None;self.arrangement_snapshot=None
            self.session.invalidate_layout()
            self.notices=['已切换本次会话使用的 Bambu 安装位置，请重新核对预设。']
            return self.state(True)
        if action == 'scan':
            self.scan()
            self.update_bed()
        elif action == 'config':
            candidate=config_change(self.session.config,data)
            if not self.catalog:raise ValueError('请先指定 Bambu 预设目录。')
            bed=Bed.from_profile(self.catalog.resolve('machine',candidate['printer']))
            self.catalog.find('process',candidate['process'])
            filament=self.catalog.resolve('filament',candidate['filament'])
            candidate['material']=(filament.get('filament_type') or [candidate['material']])[0]
            self.session.config,self.bed=candidate,bed
            self.update_bed()
            if set(data) != {'allowMixedPlates'}:
                self.session.invalidate_layout()
            return self.state(True)
        elif action == 'profile_root':
            existing=sorted({str(p.path.parent.parent) for p in self.catalog.records.values()}) if self.catalog else []
            self.catalog = ProfileCatalog(existing+[data['path']])
            self.history.clear();self.last_export=None
            self.orientation_preview=None;self.orientation_snapshot=None
            self.arrangement_preview=None;self.arrangement_snapshot=None
            return self.state(True)
        else:
            self.assert_document()
            if action == 'orientation_preview':
                self.orientation_preview=None;self.orientation_snapshot=None
                self.arrangement_preview=None;self.arrangement_snapshot=None
                self.assert_source_current()
                scope=data.get('scope','unit')
                if scope=='unit':
                    proposal=suggest(self.session,data['unit'],self.catalog,self.exe)
                elif scope in ('current','all'):
                    if scope=='current':
                        number=data.get('plate')
                        if type(number) is not int or not any(p.index==number for p in self.session.plates):
                            raise ValueError('请选择有效的当前打印盘。')
                        plates=[number]
                    else:plates=[p.index for p in self.session.plates if any(x.plate==p.index for x in self.session.placements.values())]
                    selected=[uid for uid in self.session.units if uid in self.session.placements and
                              self.session.placements[uid].plate in plates]
                    proposal=suggest_many(self.session,selected,plates,self.catalog,self.exe)
                    proposal['scope']=scope
                else:raise ValueError('请选择所选件、当前盘或所有盘。')
                proposal['token']=new_id()
                self.orientation_preview=proposal
                self.orientation_snapshot=self.history.snapshot(self.session)
                self.notices=['朝向建议已生成，尚未修改任何打印单元。请预览后确认。']
            elif action == 'orientation_cancel':
                if self.orientation_preview and data.get('token')==self.orientation_preview['token']:
                    self.orientation_preview=None;self.orientation_snapshot=None
                self.notices=['已取消朝向建议，原方向和盘位未改变。']
            elif action == 'orientation_apply':
                preview=self.orientation_preview
                if not preview or data.get('token')!=preview['token'] or self.session.rules()!=self.orientation_snapshot:
                    raise ValueError('朝向建议已过期，请重新生成；未修改模型。')
                self.assert_source_current()
                if preview.get('batch'):
                    if not preview['units']:raise ValueError('没有需要改变的朝向，未应用。')
                    for uid,proposal in preview['units'].items():apply_rotation(self.session,uid,proposal['rotation'])
                    self.notices=[f"已一次应用 {len(preview['units'])} 个打印单元的推荐朝向；盘号和整体不变。请检查占地并按需自动摆位，可撤销。"]
                else:
                    apply_rotation(self.session,preview['unit'],preview['rotation'])
                    self.notices=['已应用 Bambu 推荐朝向，仅改变所选打印单元。请检查占地与支撑；如有冲突，可手动移位或重新排盘。可撤销。']
            elif action == 'orientation_lock':
                if type(data['locked']) is not bool:raise ValueError('锁定状态必须是开关值。')
                self.session.units[data['unit']].orientation_locked=data['locked']
            elif action == 'arrangement_preview':
                self.orientation_preview=None;self.orientation_snapshot=None
                self.arrangement_preview=None;self.arrangement_snapshot=None
                self.assert_source_current()
                scope=data.get('scope')
                if scope=='current':
                    number=data.get('plate')
                    if type(number) is not int:raise ValueError('请选择有效的当前打印盘。')
                    numbers=[number]
                elif scope=='all':
                    numbers=[p.index for p in self.session.plates if any(x.plate==p.index for x in self.session.placements.values())]
                else:raise ValueError('请选择当前盘或所有盘。')
                proposal=suggest_positions(self.session,numbers,self.catalog,self.exe)
                proposal['token']=new_id();proposal['scope']=scope
                self.arrangement_preview=proposal
                self.arrangement_snapshot=self.history.snapshot(self.session)
                self.notices=['Bambu 分盘与摆位建议已生成，尚未修改盘位。请预览后确认。']
            elif action == 'arrangement_cancel':
                if self.arrangement_preview and data.get('token')==self.arrangement_preview['token']:
                    self.arrangement_preview=None;self.arrangement_snapshot=None
                self.notices=['已取消摆位建议，原盘位未改变。']
            elif action == 'arrangement_apply':
                proposal=self.arrangement_preview
                if not proposal or data.get('token')!=proposal['token'] or self.session.rules()!=self.arrangement_snapshot:
                    raise ValueError('摆位建议已过期，请重新生成；未修改盘位。')
                self.assert_source_current()
                accepted_spacing=bool(proposal['errors'] and data.get('acceptBambuSpacing') is True)
                apply_positions(self.session,proposal,accepted_spacing)
                added=len(proposal.get('newPlates',[]))
                self.notices=[f'已应用 Bambu 建议，新增 {added} 个打印盘并调整盘位；整体和方向不变，可撤销。' if added else
                              '已应用 Bambu 摆位建议，仅调整所选打印盘内的 X/Y 位置；可撤销。']
                if accepted_spacing:self.notices.append('当前文档的件间距已按确认选择改为 0 mm；请切片核查实际裙边和支撑。')
            elif action == 'group':
                self.session.group(data['units'], data.get('name', '整体打印组'))
            elif action == 'group_drop':
                group=merge_onto(self.session,data['source'],data['target'])
                self.notices=['已组成整体：'+group.name+'。保持原装配关系，采用目标组的方向；可撤销。']
            elif action == 'rename_unit':
                name=data['name'].strip()
                if not name or len(name)>120:raise ValueError('名称需为 1–120 个字符。')
                self.session.units[data['unit']].name=name
            elif action == 'transfer_plate':
                self.update_bed()
                transfer_to_plate(self.session,data['unit'],data['plate'],self.bed,data.get('confirmMixed') is True)
                self.notices=[f"已将「{self.session.units[data['unit']].name}」移至第 {data['plate']} 盘。其他盘位和组内相对位置未改变。"]
            elif action == 'viewer_face':
                if data.get('revision') != self.geometry_revision:raise ValueError('视图已过期，请刷新模型。')
                selected=self.session.units[data['unit']]
                if data['body'] not in selected.members:raise ValueError('所选面不属于该打印单元。')
                face=self.source.face_for_triangle(data['body'],data['triangle'],self.session)
                normal=self.source.normal_for_face(face,selected,self.session)
                selected.rotation=face_down(normal)
                selected.face_token=face.entityToken;selected.orientation_label='视图中所选平面朝下'
                selected.orientation_valid=True
                selected.orientation_locked=True
                if selected.uid in self.session.placements:self.session.placements[selected.uid].z=0.
                self.notices=['已按所选平面贴板。请检查新的占地；可撤销。']
            elif action == 'ungroup':
                members=self.session.ungroup(data['unit'])
                placed=all(uid in self.session.placements for uid in members)
                self.notices=[f'已解除整体，{len(members)} 个成员仍留在原盘并保持原位置和方向；如有独立模型占地重叠，请手动检查。其他模型未改变。' if placed else
                              f'已解除未分盘的整体，{len(members)} 个成员仍未分盘；其他模型未改变。']
            elif action == 'direction':
                unit = self.session.units[data['unit']]
                normal = {'top': (0,0,1), 'bottom': (0,0,-1), 'front': (0,-1,0),
                          'back': (0,1,0), 'left': (-1,0,0), 'right': (1,0,0)}
                mode = data['mode']
                if mode == 'keep':return self.state()
                unit.rotation = IDENTITY if mode == 'original' else face_down(normal[mode])
                unit.orientation_label = '保持原方向' if mode == 'original' else mode+' 面朝下'
                unit.face_token = ''
                unit.orientation_valid=True
                unit.orientation_locked=True
                self.session.invalidate_layout()
            elif action == 'pick_face':
                if not self.choose_face:
                    raise ValueError('贴板面命令未初始化。')
                self.choose_face(data['unit'])
            elif action == 'highlight':
                self.app.userInterface.activeSelections.clear()
                for uid in self.session.units[data['unit']].members:
                    self.app.userInterface.activeSelections.add(self.source.entities[uid]['proxy'])
            elif action == 'color_profile':
                self.catalog.find('filament', data['profile'])
                self.session.color_profiles[data['color']] = data['profile']
                self.session.invalidate_layout()
            elif action == 'body_color':
                if data['body'] not in self.session.bodies:raise ValueError('实体引用已失效。')
                self.session.color_overrides[data['body']] = color_hex(data['color'])
                self.session.invalidate_layout()
            elif action == 'arrange':
                self.update_bed()
                profiles = [self.session.color_profiles.get(self.session.effective_color(uid),
                            self.session.config['filament']) for uid in self.session.bodies]
                errors, _, process = self.catalog.check(self.session.config, profiles)
                if errors:
                    raise ValueError('\n'.join(errors))
                self.session.config['printClearance']=process_clearance(process,self.session.config['enableSupport'])
                self.notices = arrange(self.session, self.bed)
                self.notices.insert(0,'已从盘中央优先布局，围绕中央扩展；禁用区域与安全间距仍受检查。')
                self.notices.insert(0,f"已为裙边/支撑额外预留 {self.session.config['printClearance']:.2f} mm。仍须进行实际切片碰撞检查。")
            elif action == 'move':
                p = self.session.placements[data['unit']]
                values=placement_change(data,{plate.index for plate in self.session.plates})
                mixed=check_mixed_transfer(self.session,data['unit'],values[0],data.get('confirmMixed') is True) if values[0]!=p.plate else False
                p.plate,p.x,p.y,p.angle=values
                if mixed:approve_plate(self.session,p.plate)
            elif action == 'add_plate':
                self.session.plates.append(Plate(len(self.session.plates)+1, '手动盘'))
            elif action == 'delete_plate':
                index = int(data['plate'])
                if any(p.plate == index for p in self.session.placements.values()):
                    raise ValueError('只能删除空盘；请先移动其中的打印单元。')
                self.session.plates = [p for p in self.session.plates if p.index != index]
                for p in self.session.plates:
                    if p.index > index: p.index -= 1
                for p in self.session.placements.values():
                    if p.plate > index: p.plate -= 1
            elif action == 'save_rules':
                if self.session.rule_errors:raise ValueError('请先处理失效的打印组引用，不能覆盖保存为已确认规则。')
                self.source.design.attributes.add(ATTRIBUTE_GROUP, ATTRIBUTE_NAME, json.dumps(self.session.rules()))
                self.notices = ['规则已写入文档属性；请自行保存 Fusion 文档以持久保留。原几何未修改。']
            elif action == 'reset_units':
                self.session.reset_units()
                self.notices=['已重建打印单元列表，请重新指定不可拆分整体与方向。原设计未修改。']
            elif action == 'export':
                dialog = self.app.userInterface.createFileDialog()
                dialog.title = '导出 Bambu Studio 多盘项目'
                dialog.filter = '3MF Project (*.3mf)'
                dialog.initialFilename = 'BambuPlateStudio.3mf'
                if dialog.showSave() == adsk.core.DialogResults.DialogOK:
                    target=Path(dialog.filename)
                    overwrite=target.exists()
                    if overwrite:
                        answer=self.app.userInterface.messageBox(
                            f'文件已存在：\n{target}\n\n确认覆盖吗？旧文件会在新 3MF 完成并通过校验后才被替换。',
                            '确认覆盖 3MF',adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                            adsk.core.MessageBoxIconTypes.QuestionIconType)
                        if answer != adsk.core.DialogResults.DialogYes:
                            self.notices=['已取消覆盖，原文件未改变。']
                            return self.state()
                    self.export_to(dialog.filename,overwrite=overwrite)
            else:
                raise ValueError('未知操作：'+action)
        return self.state()
