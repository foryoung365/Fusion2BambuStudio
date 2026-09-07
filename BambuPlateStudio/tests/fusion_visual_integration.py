"""Run against the isolated Fusion document; exercises the production controller.

This is a real Fusion API integration test, not a claim of mouse-driven GUI QA.
"""
import json
import sys
from pathlib import Path
import adsk.core
from BambuPlateStudio.core.geometry import face_down


def normalized(value):
    return json.loads(json.dumps(value))


def run(context):
    app=adsk.core.Application.get()
    assert app.userInterface.activeCommand=='SelectCommand'
    doc=app.activeDocument
    assert doc is not None and doc.dataFile is None, 'Use the isolated local test copy'
    entry=Path('I:/3DPrint/BambuPlateStudio/BambuPlateStudio.py').resolve()
    candidates=[m for m in list(sys.modules.values())
                if getattr(m,'__file__',None) and Path(m.__file__).resolve()==entry
                and getattr(m,'controller',None) is not None]
    assert len(candidates)==1, 'Exactly one active add-in entry is required'
    addon=candidates[0]
    registered=app.scripts.itemByPath(str(entry.parent))
    managed=bool(registered and registered.isRunning)
    suffix='02_managed' if managed else '01'
    output=entry.parent/'test_artifacts'/('fusion_visual_integration_'+suffix)
    output.mkdir(parents=True,exist_ok=True)
    destination=output/'paper_box_P2S_PETG_SuperTack.3mf'
    assert not destination.exists(),'Never overwrite an earlier test artifact'
    c=addon.controller
    if not c.source:
        c.dispatch('scan',{})
    c.assert_document()
    initial=normalized(c.session.rules())
    before={uid:b.fingerprint() for uid,b in c.session.bodies.items()}
    checks={}
    try:
        assert len(before)==27 and len(c.session.units)==22, ('counts',len(before),len(c.session.units))
        groups=[u for u in c.session.units.values() if len(u.members)==6]
        assert len(groups)==1, ('group count',len(groups))
        expected_names={'外框2','外框3','外框4','外框5','外框6','底板框架'}
        actual_names={c.session.bodies[b].name for b in groups[0].members}
        assert actual_names==expected_names, ('group names',actual_names,expected_names)
        chest=next(u for u in c.session.units.values() if u.name=='右胸')
        top=normalized(face_down((0,0,1)))
        assert normalized(chest.rotation)==top, ('right chest direction',chest.rotation,top)
        assert normalized(groups[0].rotation)==top, ('rigid group direction',groups[0].rotation,top)
        checks['requiredRigidGroupAndTopDownDirections']=True

        # Repacking derives process space; no part is reoriented except around bed Z.
        c.dispatch('arrange',{})
        assert c.session.config['printClearance']>5
        assert not c.state()['errors']
        baseline=normalized(c.session.rules())
        checks['actualProcessClearanceMm']=c.session.config['printClearance']
        wind=[u.uid for u in c.session.units.values() if u.name=='金色风口']
        assert len(wind)==2
        c.dispatch('group_drop',{'source':wind[0],'target':wind[1]})
        assert len(c.session.units)==21
        assert len(c.session.units[wind[1]].members)==2
        c.dispatch('undo',{})
        assert normalized(c.session.rules())==baseline, ('group undo changed fields',[k for k in baseline if normalized(c.session.rules())[k]!=baseline[k]])
        checks['groupDropAndUndo']=True

        bottom=next(u for u in c.session.units.values() if u.name=='底板')
        c.dispatch('viewer_face',{'unit':bottom.uid,'body':bottom.members[0],
                                'triangle':0,'revision':c.geometry_revision})
        assert c.session.units[bottom.uid].face_token
        c.dispatch('undo',{})
        assert normalized(c.session.rules())==baseline, ('face undo changed fields',[k for k in baseline if normalized(c.session.rules())[k]!=baseline[k]])
        checks['realViewerFaceAndUndo']=True

        rigid=next(u for u in c.session.units.values() if len(u.members)==6)
        c.dispatch('add_plate',{})
        target=c.session.plates[-1].index
        c.dispatch('transfer_plate',{'unit':rigid.uid,'plate':target})
        assert c.session.placements[rigid.uid].plate==target
        assert len(c.session.units[rigid.uid].members)==6
        c.dispatch('undo',{})
        c.dispatch('undo',{})
        assert normalized(c.session.rules())==baseline, ('transfer undo changed fields',[k for k in baseline if normalized(c.session.rules())[k]!=baseline[k]])
        checks['WholeSixBodyGroupTransferAndUndo']=True

        c.dispatch('save_rules',{})
        fresh=type(c)()
        fresh.scan();fresh.update_bed()
        assert normalized(fresh.session.rules())==baseline, ('rule restore changed fields',[k for k in baseline if normalized(fresh.session.rules())[k]!=baseline[k]])
        assert not fresh.state()['errors']
        checks['NewControllerRestoresSavedRules']=True

        report=c.export_to(str(destination))
        assert report['nativeBambuReadWritePassed']
        after=type(c.source)(doc).scan(c.session.config['includeHidden'],c.session.config['refinement'])
        assert {b.uid:b.fingerprint() for b in after}==before
        report.update(checks=checks,sourceGeometryUnchanged=True,document=doc.name,
                      configuration=dict(c.session.config),mouseGuiTest=False,
                      managedAddin=managed,entryModule=addon.__name__)
        (output/'integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        addon.emit_state()
        print(json.dumps(report,ensure_ascii=False))
    except Exception as exc:
        c.session.apply_rules(initial)
        c.update_bed()
        addon.emit_state()
        raise RuntimeError('Integration checks reached: '+repr(checks)+'; failure: '+repr(exc)) from exc
