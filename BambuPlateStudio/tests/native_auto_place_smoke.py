"""Opt-in Bambu arrangement and native export test using an isolated 3MF fixture."""
import copy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from BambuPlateStudio.tests.visual_demo_server import load_fixture
from BambuPlateStudio.core.auto_place import suggest,apply_positions
from BambuPlateStudio.core.bambu import export_native
from BambuPlateStudio.core.layout import Bed,validate,process_clearance,auto_brim_reserve
from BambuPlateStudio.core.package3mf import write_project
from BambuPlateStudio.core.profiles import discover,ProfileCatalog

if __name__=='__main__':
    # load_fixture reads the fixture from argv[1]; no Fusion document is touched.
    fixture=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve()
    if not fixture.is_file() or output.exists():raise ValueError('Provide an existing fixture and a fresh output directory.')
    output.mkdir(parents=True)
    session=load_fixture();exe,roots=discover();catalog=ProfileCatalog(roots)
    process=catalog.resolve('process',session.config['process'])
    session.config['printClearance']=process_clearance(process,session.config['enableSupport'])
    session.config['autoBrimReserve']=auto_brim_reserve(process)
    bed=Bed.from_profile(catalog.resolve('machine',session.config['printer']))
    assert not validate(session,bed)[0]
    before=copy.deepcopy(session.rules())
    proposal=suggest(session,[p.index for p in session.plates],catalog,exe)
    assert session.rules()==before and proposal['placements'] and not proposal['errors']
    apply_positions(session,proposal)
    assert not validate(session,bed)[0]
    for uid,original in ((u['uid'],u) for u in before['units']):
        current=session.units[uid]
        assert current.members==original['members'] and current.rotation==tuple(tuple(r) for r in original['rotation'])
    write_project(output/'seed.3mf',session,catalog)
    report=export_native(output/'seed.3mf',output/'auto_placed.3mf',catalog,exe)
    report.update(proposal=proposal,previewDidNotMutate=True,groupsAndDirectionsPreserved=True)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'bodies':report['bodies'],'plates':report['plates'],
                      'moved':proposal['moved'],'skipped':proposal['skipped'],
                      'maxVertexErrorMm':report['maxVertexErrorMm']},ensure_ascii=True))
