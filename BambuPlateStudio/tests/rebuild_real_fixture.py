"""Replay the real Fusion mesh capture through the current core without touching CAD."""
import json
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from BambuPlateStudio.core.model import Body,PrintUnit,Session
from BambuPlateStudio.core.profiles import ProfileCatalog,discover
from BambuPlateStudio.core.layout import arrange,Bed,process_clearance
from BambuPlateStudio.core.package3mf import write_project,NS


def rebuild(source,output):
    with zipfile.ZipFile(source) as z:
        model=ET.fromstring(z.read('3D/3dmodel.model'))
        config=ET.fromstring(z.read('Metadata/model_settings.config'))
        meta=json.loads(z.read('Metadata/BambuPlateStudio.json'))
        settings=json.loads(z.read('Metadata/project_settings.config'))
    resources={e.get('id'):e for e in model.findall('c:resources/c:object',NS)}
    info={e.get('id'):e for e in config.findall('object')}
    bodies=[]
    for obj in info.values():
        for part in obj.findall('part'):
            values={m.get('key'):m.get('value') for m in part.findall('metadata')}
            uid=Path(values['source_file']).stem
            mesh=resources[part.get('id')].find('c:mesh',NS)
            vertices=[tuple(float(v.get(k)) for k in ('x','y','z')) for v in mesh.findall('c:vertices/c:vertex',NS)]
            triangles=[tuple(int(t.get(k)) for k in ('v1','v2','v3')) for t in mesh.findall('c:triangles/c:triangle',NS)]
            color=meta['slots'][int(values['extruder'])-1]['color']
            body=Body(uid,values['name'],'Real Fusion capture',color,vertices,triangles,face_colors={color:1.})
            body.validate();bodies.append(body)
    session=Session(bodies)
    session.config.update(meta.get('configuration',{}))
    session.config.update(printer=settings['printer_settings_id'],process=settings['print_settings_id'],
                          bed=settings['curr_bed_type'],filament=meta['slots'][0]['profile'],
                          enableSupport=settings['enable_support']=='1')
    session.color_profiles={s['color']:s['profile'] for s in meta['slots']}
    session.units={}
    for item in meta['units']:
        name=next(m.get('value') for m in info[str(item['objectId'])].findall('metadata') if m.get('key')=='name')
        rotation=tuple(tuple(row[:3]) for row in item['matrix'][:3])
        session.units[item['unit']]=PrintUnit(item['unit'],name,item['members'],rotation,orientation_label='已确认的原方向')
    _,roots=discover();catalog=ProfileCatalog(roots)
    process=catalog.resolve('process',session.config['process'])
    session.config['printClearance']=process_clearance(process,session.config['enableSupport'])
    arrange(session,Bed.from_profile(catalog.resolve('machine',session.config['printer'])))
    result=write_project(output,session,catalog)
    assert result['sourceMeshHashes']==meta['sourceMeshHashes'],'Source geometry changed during fixture replay'
    print(json.dumps({'path':str(output),'plates':result['plates'],'clearance':session.config['printClearance'],
                      'allSourceMeshHashesUnchanged':True},ensure_ascii=False))


if __name__=='__main__':rebuild(Path(sys.argv[1]),Path(sys.argv[2]))
