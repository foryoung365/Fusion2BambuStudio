"""Two-phase capture of the add-in's own WebGL canvas via its normal HTML bridge.

Run once to request the next view; run again to save a completed response and
request the following view. No OS screenshot, injected input or CAD edit.
"""
import base64
import json
import sys
from pathlib import Path
import adsk.core


def run(context):
    entry=Path('I:/3DPrint/BambuPlateStudio/BambuPlateStudio.py').resolve()
    addons=[m for m in list(sys.modules.values()) if getattr(m,'__file__',None)
            and Path(m.__file__).resolve()==entry and getattr(m,'controller',None)]
    assert len(addons)==1
    addon=addons[0]
    palette=adsk.core.Application.get().userInterface.palettes.itemById(addon.PALETTE)
    assert palette and palette.isVisible
    output=entry.parent/'test_artifacts'/'fusion_visual_integration_02_managed'
    capture=getattr(addon,'last_view_capture',None)
    if capture:
        name='fusion_'+capture['mode']
        path=output/(name+'.png')
        if not path.exists():
            result=dict(capture)
            raw=base64.b64decode(result.pop('image').split(',',1)[1],validate=True)
            assert raw.startswith(b'\x89PNG\r\n\x1a\n')
            with path.open('xb') as f:f.write(raw)
            (output/(name+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    jobs=[('group',{}),('layout',{'plate':4}),('face',{'unit':next(
        u.uid for u in addon.controller.session.units.values() if u.name=='右胸')})]
    pending=[(mode,options) for mode,options in jobs if not (output/('fusion_'+mode+'.png')).exists()]
    if pending:
        mode,options=pending[0]
        palette.sendInfoToHTML('capture_view',json.dumps(dict(options,mode=mode)))
    print(json.dumps({'remaining':[m for m,_ in pending],'saved':[m for m,_ in jobs
        if (output/('fusion_'+m+'.png')).exists()],'events':addon.event_log[-2:]}))
