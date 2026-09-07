"""Verify a confirmed manual mixed plate survives actual Bambu serialization."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from BambuPlateStudio.core.model import Session
from BambuPlateStudio.core.layout import arrange,Bed,process_clearance
from BambuPlateStudio.core.visual_edit import transfer_to_plate
from BambuPlateStudio.core.profiles import discover,ProfileCatalog
from BambuPlateStudio.core.package3mf import write_project
from BambuPlateStudio.core.bambu import export_native
from BambuPlateStudio.tests.test_core import cube


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]/'test_artifacts/mixed_confirmation_01'
    root.mkdir(exist_ok=True)
    exe,roots=discover();catalog=ProfileCatalog(roots)
    session=Session([cube('a'),cube('b',color='#FF0000')])
    session.config['printClearance']=process_clearance(catalog.resolve('process',session.config['process']),False)
    bed=Bed.from_profile(catalog.resolve('machine',session.config['printer']))
    arrange(session,bed)
    transfer_to_plate(session,'a',session.placements['b'].plate,bed,True)
    write_project(root/'seed.3mf',session,catalog)
    result=export_native(root/'seed.3mf',root/'manual_mixed.3mf',catalog,exe)
    result['manualMixedPlate']=session.placements['a'].plate
    result['globalMixedModeEnabled']=session.config['allowMixedPlates']
    (root/'native_export.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
