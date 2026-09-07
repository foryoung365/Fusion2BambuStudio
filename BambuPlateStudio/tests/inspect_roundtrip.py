import json
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02',
    'p':'http://schemas.microsoft.com/3dmanufacturing/production/2015/06'}
IDENTITY=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

def transform(text):
    if not text:return IDENTITY
    a=list(map(float,text.split()))
    return [[a[c*3+r] for c in range(4)] for r in range(3)]+[[0,0,0,1]]

def mul(a,b):
    return [[sum(a[r][k]*b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]

def metadata(node):
    return {e.get('key'):e.get('value') for e in node.findall('metadata') if e.get('key')}

def inspect(path):
    with zipfile.ZipFile(path) as archive:
        models={n:ET.fromstring(archive.read(n)) for n in archive.namelist() if n.endswith('.model')}
        resources={(n,o.get('id')):o for n,m in models.items() for o in m.findall('c:resources/c:object',NS)}
        cfg=ET.fromstring(archive.read('Metadata/model_settings.config'))
        names={o.get('id'):metadata(o).get('name') for o in cfg.findall('object')}
        def vertices(file,oid,matrix):
            obj=resources[(file,oid)]
            mesh=obj.find('c:mesh',NS)
            if mesh is not None:
                for v in mesh.findall('c:vertices/c:vertex',NS):
                    p=[float(v.get(c)) for c in ('x','y','z')]+[1]
                    yield [sum(matrix[r][c]*p[c] for c in range(4)) for r in range(3)]
            for c in obj.findall('c:components/c:component',NS):
                target=c.get('{'+NS['p']+'}path',file).lstrip('/')
                yield from vertices(target,c.get('objectid'),mul(matrix,transform(c.get('transform'))))
        result=[]
        for item in models['3D/3dmodel.model'].findall('c:build/c:item',NS):
            oid=item.get('objectid'); points=list(vertices('3D/3dmodel.model',oid,transform(item.get('transform'))))
            result.append({'id':oid,'name':names.get(oid),'bbox':[[min(p[i] for p in points) for i in range(3)],
                           [max(p[i] for p in points) for i in range(3)]]})
        settings=json.loads(archive.read('Metadata/project_settings.config'))
        return {'objects':result,'settings':{k:settings.get(k) for k in ['printer_settings_id','printer_model','printable_area','filament_type','curr_bed_type']},'plates':[{'meta':metadata(p),'instances':[metadata(i) for i in p.findall('model_instance')]} for p in cfg.findall('plate')]}

if __name__=='__main__':
    for name in sys.argv[1:]:
        data=inspect(name)
        print(json.dumps({'file':name,'objects':data['objects'][:2],'settings':data['settings'],'plateCount':len(data['plates'])},ensure_ascii=True))
