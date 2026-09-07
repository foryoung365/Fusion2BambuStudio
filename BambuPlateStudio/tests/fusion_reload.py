"""Development bootstrap. Run only after the prior test dialog has been closed."""
import importlib
import json
import sys
from pathlib import Path
import adsk
import adsk.core


def run(context):
    root=Path('I:/3DPrint/BambuPlateStudio').resolve()
    app=adsk.core.Application.get()
    assert app.userInterface.activeCommand=='SelectCommand','Close the previous dialog first'
    doc=app.activeDocument
    assert doc is not None and doc.dataFile is None,'Use the isolated local test copy'
    old=sys.modules.get('BambuPlateStudio.BambuPlateStudio')
    rules=None
    if old:
        controller=old.controller
        if controller and controller.source and controller.source.document==doc:
            rules=json.loads(json.dumps(controller.session.rules()))
        old.stop(None)
    for name in list(sys.modules):
        if name=='BambuPlateStudio' or name.startswith('BambuPlateStudio.'):
            module=sys.modules[name]
            filename=getattr(module,'__file__',None)
            assert filename and root in Path(filename).resolve().parents,(name,filename)
            del sys.modules[name]
    if str(root.parent) not in sys.path:sys.path.insert(0,str(root.parent))
    importlib.invalidate_caches()
    adsk.autoTerminate(False)
    addon=importlib.import_module('BambuPlateStudio.BambuPlateStudio')
    addon.run({'showUI':False})
    addon.controller.scan()
    if rules:
        aliases=addon.controller.source.aliases_for(rules)
        addon.controller.session.apply_rules(rules,aliases)
    addon.controller.update_bed()
    print(json.dumps({'reloaded':True,'bodies':len(addon.controller.session.bodies),
                      'units':len(addon.controller.session.units),'dialogOpened':False}))
