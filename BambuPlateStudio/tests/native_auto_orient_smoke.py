"""Opt-in actual Bambu engine test, including rigid groups and final export."""
import copy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from BambuPlateStudio.tests.test_core import cube
from BambuPlateStudio.core.model import Session
from BambuPlateStudio.core.profiles import discover,ProfileCatalog
from BambuPlateStudio.core.layout import Bed,arrange,process_clearance
from BambuPlateStudio.core.auto_orient import suggest,apply_rotation
from BambuPlateStudio.core.geometry import face_down
from BambuPlateStudio.core.package3mf import write_project
from BambuPlateStudio.core.bambu import export_native

if __name__=='__main__':
    output=Path(sys.argv[1]).resolve();output.mkdir(parents=True,exist_ok=False)
    exe,roots=discover();catalog=ProfileCatalog(roots)
    session=Session([cube('a',size=(10,30,60)),cube('b',color='#FF0000',low=(20,0,20),size=(10,30,20)),cube('locked',color='#FFFFFF')])
    group=session.group(['a','b'],'不可拆整体')
    if '--rotated' in sys.argv[2:]:group.rotation=face_down((0,-1,0))
    session.units['locked'].orientation_locked=True
    session.config['printClearance']=process_clearance(catalog.resolve('process',session.config['process']),False)
    arrange(session,Bed.from_profile(catalog.resolve('machine',session.config['printer'])))
    before=copy.deepcopy(session.rules());proposal=suggest(session,group.uid,catalog,exe)
    if '--rotated' not in sys.argv[2:]:assert proposal['afterSize'][2]<proposal['beforeSize'][2]-1
    assert session.rules()==before,'Query changed preparation rules'
    peer=copy.deepcopy(session.units['locked']);peer_place=copy.deepcopy(session.placements['locked'])
    apply_rotation(session,group.uid,proposal['rotation'])
    assert session.units['locked']==peer and session.placements['locked']==peer_place
    arrange(session,Bed.from_profile(catalog.resolve('machine',session.config['printer'])))
    write_project(output/'seed.3mf',session,catalog)
    report=export_native(output/'seed.3mf',output/'oriented_project.3mf',catalog,exe)
    report.update(proposal=proposal,queryDidNotMutate=True,lockedPeerUnchanged=True,rigidGroupPreserved=True)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
