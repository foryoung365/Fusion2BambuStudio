import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from BambuPlateStudio.core.bambu import export_native
from BambuPlateStudio.core.profiles import ProfileCatalog,discover

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    exe,roots=discover()
    result=export_native(sys.argv[1],sys.argv[2],ProfileCatalog(roots),exe)
    Path(sys.argv[2]+'.audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
