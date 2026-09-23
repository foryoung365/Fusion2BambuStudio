"""Run only on the explicitly imported local tissue-box test copy."""
import json,sys
from pathlib import Path
import adsk.core


def run(context):
    root=Path('I:/3DPrint/BambuPlateStudio').resolve()
    app=adsk.core.Application.get();doc=app.activeDocument
    assert doc and doc.dataFile is None and app.userInterface.activeCommand=='SelectCommand'
    addon=next(m for m in list(sys.modules.values()) if getattr(m,'__file__',None)
               and Path(m.__file__).resolve()==root/'BambuPlateStudio.py' and getattr(m,'controller',None))
    c=addon.controller;c.dispatch('scan',{})
    original=json.loads(json.dumps(c.session.rules()))
    group=next(u for u in c.session.units.values() if len(u.members)==6)
    assert group.orientation_locked,'Legacy manual orientation was not protected'
    c.dispatch('orientation_lock',{'unit':group.uid,'locked':False})
    unlocked=json.loads(json.dumps(c.session.rules()))
    report={}
    try:
        c.dispatch('orientation_preview',{'unit':group.uid})
        preview=c.orientation_preview
        assert preview['members']==6
        assert json.loads(json.dumps(c.session.rules()))==unlocked
        c.dispatch('orientation_cancel',{'token':preview['token']})
        assert json.loads(json.dumps(c.session.rules()))==unlocked
        c.dispatch('orientation_preview',{'unit':group.uid})
        preview=c.orientation_preview
        c.dispatch('orientation_apply',{'token':preview['token']})
        assert c.session.units[group.uid].rotation==preview['rotation']
        assert c.session.units[group.uid].members==group.members
        c.dispatch('undo',{});assert json.loads(json.dumps(c.session.rules()))==unlocked
        c.dispatch('undo',{});assert json.loads(json.dumps(c.session.rules()))==original
        fresh=type(c.source)(doc).scan(c.session.config['includeHidden'],c.session.config['refinement'])
        assert {b.uid:b.geometry_key() for b in fresh}=={uid:b.geometry_key() for uid,b in c.session.bodies.items()}
        report={'passed':True,'sixBodyGroupVerified':True,'legacyManualLockVerified':True,
                'previewAndCancelNonMutating':True,'confirmedApplyAndUndo':True,'sourceCadUnchanged':True,
                'beforeSize':preview['beforeSize'],'afterSize':preview['afterSize'],'maxVertexErrorMm':preview['maxVertexErrorMm']}
    finally:
        c.session.apply_rules(original);c.update_bed();c.orientation_preview=None;c.orientation_snapshot=None
        c.history.clear();addon.emit_state()
    output=Path('I:/3DPrint/Fusion2BambuStudio/BambuPlateStudio/test_artifacts/auto_orient_fusion.json')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report))
