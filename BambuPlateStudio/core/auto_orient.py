"""Use Bambu's engine as a rotation advisor; never import its modified model."""
import copy
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .bambu import run_project
from .bambu_validation import read,nearest_error
from .geometry import bounds,rotate,validate_rotation,dot,cross,unit as normalize,signed_volume
from .layout import Bed,arrange,process_clearance,spacing,validate
from .model import Session,Body
from .package3mf import write_project


def extract_rotation(query, path):
    parts,groups,plates,_=read(path,orientation=True)
    selected=next(iter(query.units.values()))
    expected=sorted(uid+'.mesh' for uid in selected.members)
    if groups!=[expected] or sorted(parts)!=expected or plates!=1:
        raise ValueError('Bambu 返回的整体或实体对应关系发生变化，已拒绝该朝向。')
    raw=tuple(tuple(row[:3]) for row in parts[expected[0]]['matrix'][:3])
    validate_rotation(raw)
    first=normalize(raw[0]);second=normalize(tuple(raw[1][i]-dot(raw[1],first)*first[i] for i in range(3)))
    rotation=(first,second,cross(first,second));validate_rotation(rotation)
    translation=None
    maximum=0.
    for uid in selected.members:
        body=query.bodies[uid];result=parts[uid+'.mesh']
        if (result['name']!=body.name or result['unitName']!=selected.name or
            result['color'].upper()!=query.effective_color(uid) or len(result['triangles'])!=len(body.triangles)):
            raise ValueError('Bambu 返回的实体名称、颜色或网格发生变化，已拒绝该朝向。')
        candidate=tuple(tuple(row[:3]) for row in result['matrix'][:3]);validate_rotation(candidate)
        if max(abs(candidate[i][j]-rotation[i][j]) for i in range(3) for j in range(3))>1e-5:
            raise ValueError('整体内的实体被分别旋转，已拒绝该朝向。')
        rotated=[rotate(rotation,v) for v in body.vertices]
        a,b=bounds(rotated),bounds(result['vertices'])
        offset=tuple((b[0][i]+b[1][i]-a[0][i]-a[1][i])/2 for i in range(3))
        if translation is None:translation=offset
        if max(abs(offset[i]-translation[i]) for i in range(3))>.001:
            raise ValueError('整体内相对位置发生变化，已拒绝该朝向。')
        transformed=[tuple(v[i]+translation[i] for i in range(3)) for v in rotated]
        error=max(nearest_error(transformed,result['vertices']),nearest_error(result['vertices'],transformed))
        if error>.001:raise ValueError('朝向结果不是原模型的统一刚体旋转，已拒绝。')
        va=signed_volume(body.vertices,body.triangles);vb=signed_volume(result['vertices'],result['triangles'])
        if abs(va-vb)>max(.02,abs(va)*1e-5):raise ValueError('朝向结果的网格体积或面方向发生变化，已拒绝。')
        maximum=max(maximum,error)
    return rotation,maximum


def suggest(session, uid, catalog, executable):
    original=session.units[uid]
    if original.orientation_locked:
        raise ValueError('该打印单元已锁定朝向，请先取消锁定。')
    if not original.orientation_valid:
        raise ValueError('当前贴板面引用失效，请先重新指定方向。')
    # A single temporary mesh prevents the CLI from separately recentering parts.
    # Concatenation preserves every source triangle; this is not a Boolean join.
    vertices=[];triangles=[]
    for member in original.members:
        body=session.bodies[member];offset=len(vertices)
        vertices.extend(body.vertices)
        triangles.extend(tuple(i+offset for i in tri) for tri in body.triangles)
    color=session.effective_color(original.members[0])
    combined=Body('orientation-query',original.name,'orientation-query',color,vertices,triangles,face_colors={color:1.})
    query=Session([combined])
    query.units={uid:copy.deepcopy(original)}
    query.units[uid].members=[combined.uid]
    query.config=copy.deepcopy(session.config)
    query.color_profiles={color:session.color_profiles.get(color,session.config['filament'])}
    bed=Bed.from_profile(catalog.resolve('machine',query.config['printer']))
    query.config['printClearance']=process_clearance(catalog.resolve('process',query.config['process']),query.config['enableSupport'])
    # One isolated print unit is sent; other units and their locks never reach CLI.
    arrange(query,bed)
    with tempfile.TemporaryDirectory(prefix='BPS_orientation_') as directory:
        seed=Path(directory)/'query.3mf'
        write_project(seed,query,catalog)
        native,elapsed=run_project(seed,directory,catalog,executable,orient=True)
        rotation,error=extract_rotation(query,native)
    trial=copy.deepcopy(original);trial.rotation=rotation
    size=trial.geometry(session.bodies)[2];margin,_=spacing(query)
    if size[0]>bed.width-2*margin+1e-6 or size[1]>bed.depth-2*margin+1e-6 or size[2]>bed.height+1e-6:
        raise ValueError('Bambu 推荐朝向超出当前打印区域或安全边距，未应用。')
    placement=session.placements.get(uid)
    previous_rotation,_,previous_size=original.geometry(session.bodies,placement.angle if placement else 0.)
    return {'unit':uid,'name':original.name,'rotation':rotation,'beforeRotation':previous_rotation,
            'beforeSize':previous_size,'afterSize':size,'members':len(original.members),
            'maxVertexErrorMm':error,'elapsedSeconds':elapsed,
            'warning':'这是 Bambu CLI 的几何朝向建议，不保证外观、强度或抗翘曲最优。确认后仅改变本单元朝向；盘内位置可能需要调整。'}


def apply_rotation(session, uid, rotation):
    selected=session.units[uid]
    if selected.orientation_locked:raise ValueError('该打印单元已锁定，未应用建议。')
    validate_rotation(rotation)
    placement=session.placements.get(uid)
    if placement:
        size=selected.geometry(session.bodies,placement.angle)[2]
        center=(placement.x+size[0]/2,placement.y+size[1]/2)
    selected.rotation=tuple(tuple(row) for row in rotation)
    selected.face_token='';selected.orientation_label='Bambu 自动推荐';selected.orientation_valid=True
    if placement:
        size=selected.geometry(session.bodies)[2]
        placement.x=center[0]-size[0]/2;placement.y=center[1]-size[1]/2
        placement.angle=0.;placement.z=0.


def suggest_many(session,unit_ids,plates,catalog,executable):
    if not unit_ids or len(set(unit_ids))!=len(unit_ids) or any(uid not in session.units for uid in unit_ids):
        raise ValueError('请先选择含打印单元的当前盘或所有盘。')
    started=time.monotonic();changes={};skipped=[];maximum=0.
    eligible=[uid for uid in unit_ids if not session.units[uid].orientation_locked]
    with ThreadPoolExecutor(max_workers=min(2,len(eligible) or 1)) as workers:
        futures={uid:workers.submit(suggest,session,uid,catalog,executable) for uid in eligible}
        for uid in unit_ids:
            unit=session.units[uid]
            if unit.orientation_locked:
                skipped.append({'unit':uid,'name':unit.name,'reason':'朝向已锁定'})
                continue
            try:proposal=futures[uid].result()
            except (ValueError,RuntimeError) as exc:
                skipped.append({'unit':uid,'name':unit.name,'reason':str(exc)})
                continue
            maximum=max(maximum,proposal['maxVertexErrorMm'])
            if max(abs(proposal['rotation'][i][j]-proposal['beforeRotation'][i][j])
                   for i in range(3) for j in range(3))<1e-5:
                skipped.append({'unit':uid,'name':unit.name,'reason':'推荐方向与当前相同'})
                continue
            changes[uid]=proposal
    trial=copy.copy(session)
    trial.units=copy.deepcopy(session.units)
    trial.placements=copy.deepcopy(session.placements)
    for uid,proposal in changes.items():apply_rotation(trial,uid,proposal['rotation'])
    bed=Bed.from_profile(catalog.resolve('machine',session.config['printer']))
    before_errors=set(validate(session,bed)[0]);after_errors,_=validate(trial,bed)
    errors=[error for error in after_errors if error not in before_errors]
    placements={uid:{'x':trial.placements[uid].x,'y':trial.placements[uid].y,
                     'angle':trial.placements[uid].angle,'z':trial.placements[uid].z}
                for uid in changes if uid in trial.placements}
    return {'batch':True,'plates':list(plates),'units':changes,'placements':placements,
            'skipped':skipped,'errors':errors,'moved':len(changes),'total':len(unit_ids),
            'elapsedSeconds':time.monotonic()-started,'maxVertexErrorMm':maximum,
            'warning':'确认后一次应用这些朝向，不换盘、不拆分整体。新朝向可能改变占地；如出现间距或出板错误，请随后使用自动摆位，导出前仍需切片核查。'}
