"""Check native Bambu roundtrip fidelity, not merely successful ZIP/XML parsing."""
import itertools
import json
import math
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from .geometry import signed_volume
from .profiles import BEDS
NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02',
    'p':'http://schemas.microsoft.com/3dmanufacturing/production/2015/06'}
IDENTITY=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

def metadata(node):
    return {e.get('key'):e.get('value') for e in node.findall('metadata') if e.get('key')}

def transform(text):
    if not text:return IDENTITY
    values=list(map(float,text.split()))
    if len(values)!=12:raise ValueError('Invalid 3MF transform')
    return [[values[c*3+r] for c in range(4)] for r in range(3)]+[[0,0,0,1]]

def mul(a,b):
    return [[sum(a[r][k]*b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]



def read(path):
    with zipfile.ZipFile(path) as z:
        models={n:ET.fromstring(z.read(n)) for n in z.namelist() if n.endswith('.model')}
        config=ET.fromstring(z.read('Metadata/model_settings.config'))
        settings=json.loads(z.read('Metadata/project_settings.config'))
    resources={(name,o.get('id')):o for name,m in models.items() for o in m.findall('c:resources/c:object',NS)}
    configs={o.get('id'):o for o in config.findall('object')}
    object_plates={metadata(i)['object_id']:n+1 for n,p in enumerate(config.findall('plate')) for i in p.findall('model_instance')}
    parts,groups={},[]
    def walk(file,oid,matrix):
        obj=resources[(file,oid)]
        mesh=obj.find('c:mesh',NS)
        if mesh is not None:yield oid,mesh,matrix
        for c in obj.findall('c:components/c:component',NS):
            yield from walk(c.get('{'+NS['p']+'}path',file).lstrip('/'),c.get('objectid'),mul(matrix,transform(c.get('transform'))))
    for item in models['3D/3dmodel.model'].findall('c:build/c:item',NS):
        oid=item.get('objectid');obj=configs[oid]
        pinfo={p.get('id'):metadata(p) for p in obj.findall('part')}
        members=[]
        for mid,mesh,matrix in walk('3D/3dmodel.model',oid,transform(item.get('transform'))):
            info=pinfo[mid];key=info['source_file'];members.append(key)
            vertices=[]
            for v in mesh.findall('c:vertices/c:vertex',NS):
                point=[float(v.get(k)) for k in ('x','y','z')]+[1.]
                vertices.append(tuple(sum(matrix[r][c]*point[c] for c in range(4)) for r in range(3)))
            triangles=[tuple(int(t.get(k)) for k in ('v1','v2','v3')) for t in mesh.findall('c:triangles/c:triangle',NS)]
            slot=int(info.get('extruder',metadata(obj).get('extruder','1')))-1
            assert key not in parts,'Source body duplicated in project'
            parts[key]={'vertices':vertices,'triangles':triangles,'plate':object_plates[oid],
                        'name':info.get('name'),'unitName':metadata(obj).get('name'),
                        'color':settings['filament_colour'][slot],
                        'material':settings['filament_type'][slot]}
        groups.append(sorted(members))
    return parts,sorted(groups),len(config.findall('plate')),settings


def nearest_error(first,second,tolerance=.001):
    cells={}
    for point in second:
        key=tuple(math.floor(v/tolerance) for v in point)
        cells.setdefault(key,[]).append(point)
    maximum=0.
    for point in set(first):
        key=tuple(math.floor(v/tolerance) for v in point)
        best=float('inf')
        for offset in itertools.product((-1,0,1),repeat=3):
            for target in cells.get(tuple(key[i]+offset[i] for i in range(3)),[]):
                distance=sum((point[i]-target[i])**2 for i in range(3))**.5
                if distance<best:best=distance
        maximum=max(maximum,best)
    return maximum


def verify(source,output,report_path=None):
    a,groups_a,plates_a,settings_a=read(source)
    b,groups_b,plates_b,settings_b=read(output)
    assert a.keys()==b.keys(),'Body correspondence changed'
    assert groups_a==groups_b,'Print-in-place grouping changed'
    assert plates_a==plates_b,'Plate count changed'
    for key in ['printer_model','printable_area','nozzle_diameter','curr_bed_type','filament_colour','filament_type']:
        assert settings_a[key]==settings_b[key],key
    def numeric(value):
        if isinstance(value,list):return [numeric(v) for v in value]
        if isinstance(value,(int,float)):return float(value)
        try:return float(value)
        except (ValueError,TypeError):return value
    bed_key=BEDS[settings_a['curr_bed_type']][1]
    for key in ['layer_height','enable_support','enable_prime_tower','nozzle_temperature',
                'nozzle_temperature_initial_layer',bed_key,bed_key+'_initial_layer']:
        if key in settings_a:
            assert numeric(settings_a[key])==numeric(settings_b.get(key)),('setting changed',key)
    rows=[]
    for key in a:
        x,y=a[key],b[key]
        assert (x['name'],x['unitName'])==(y['name'],y['unitName']),(key,'name changed')
        assert (x['plate'],x['color'],x['material'])==(y['plate'],y['color'],y['material']),key
        error=max(nearest_error(x['vertices'],y['vertices']),nearest_error(y['vertices'],x['vertices']))
        assert error<.001,(key,error)
        assert len(x['triangles'])==len(y['triangles']),(key,'triangle count')
        va=signed_volume(x['vertices'],x['triangles']);vb=signed_volume(y['vertices'],y['triangles'])
        assert abs(va-vb)<max(.02,abs(va)*1e-5),(key,'oriented volume',va,vb)
        rows.append({'body':key,'maxVertexErrorMm':error,'orientedVolumeBeforeMm3':va,
                     'orientedVolumeAfterMm3':vb,'plate':x['plate'],'color':x['color']})
    result={'passed':True,'bodies':len(a),'objects':len(groups_a),'plates':plates_a,
            'maxVertexErrorMm':max(r['maxVertexErrorMm'] for r in rows),'rows':rows}
    if report_path:
        Path(report_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
