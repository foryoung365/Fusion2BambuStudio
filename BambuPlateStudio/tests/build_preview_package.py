"""Package only portable add-in source; never include user models or test outputs."""
import hashlib
import json
import zipfile
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'BambuPlateStudio.manifest').read_text(encoding='utf-8'))
    names=['BambuPlateStudio.py','BambuPlateStudio.manifest','__init__.py',
           'README.md','GUIDE_CN.md','ACCEPTANCE_STATUS.md']
    files=[root/name for name in names]
    for directory,suffixes in [('core',{'.py'}),('fusion_adapter',{'.py'}),('ui',{'.html','.js','.css'})]:
        files+=sorted(p for p in (root/directory).rglob('*') if p.is_file() and p.suffix in suffixes
                      and '__pycache__' not in p.parts)
    assert all(p.is_file() and root in p.resolve().parents for p in files)
    assert len({p.relative_to(root).as_posix() for p in files})==len(files)
    for p in files:
        if p.suffix=='.py':compile(p.read_text(encoding='utf-8'),str(p),'exec')
    rows=[{'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
          for p in files]
    report={'version':manifest['version'],'releaseType':'development_preview',
            'files':rows,'containsUserModels':False,'requiresMCP':False}
    output=root/'releases'/('BambuPlateStudio-'+manifest['version']+'-visual-preview.zip')
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in files:archive.write(p,'BambuPlateStudio/'+p.relative_to(root).as_posix())
        archive.writestr('BambuPlateStudio/BUILD_REPORT.json',json.dumps(report,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for row in rows:
            assert hashlib.sha256(archive.read('BambuPlateStudio/'+row['path'])).hexdigest()==row['sha256']
    result={'path':str(output),'files':len(files),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'verified':True,'releaseType':'development_preview'}
    output.with_suffix('.audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
