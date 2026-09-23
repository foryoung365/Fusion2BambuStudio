"""Ask Bambu to arrange one existing plate at a time; import positions only."""
import copy
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .bambu import run_project
from .bambu_validation import read,nearest_error
from .geometry import bounds,signed_volume
from .layout import Bed,validate
from .model import Session,Plate
from .package3mf import write_project


class PlateOverflow(ValueError):
    pass


def plate_query(session, number):
    selected=[u for u in session.units.values() if u.uid in session.placements and
              session.placements[u.uid].plate==number]
    if not selected:raise ValueError(f'第 {number} 盘没有可摆放的模型。')
    bodies=[copy.copy(session.bodies[member]) for unit in selected for member in unit.members]
    query=Session(bodies)
    query.units={unit.uid:copy.deepcopy(unit) for unit in selected}
    query.placements={unit.uid:copy.deepcopy(session.placements[unit.uid]) for unit in selected}
    for placement in query.placements.values():placement.plate=1
    plate=next(p for p in session.plates if p.index==number)
    query.plates=[Plate(1,plate.name,plate.allow_mixed)]
    query.config=copy.deepcopy(session.config)
    query.color_profiles=copy.deepcopy(session.color_profiles)
    query.color_overrides={uid:session.color_overrides[uid] for uid in query.bodies if uid in session.color_overrides}
    return query


def extract_positions(query,seed,native):
    original,original_groups,original_plates,_=read(seed,orientation=True)
    arranged,groups,plates,_=read(native,orientation=True)
    expected=sorted(sorted(member+'.mesh' for member in unit.members) for unit in query.units.values())
    if original_plates!=1 or groups!=expected or original_groups!=expected or original.keys()!=arranged.keys():
        raise ValueError('Bambu 改变了打印组或实体，已拒绝摆位结果。')
    if plates!=1 or any(item['plate']!=1 for item in arranged.values()):
        raise PlateOverflow('Bambu 建议拆到更多打印盘，原盘位已保留。')
    positions={};maximum=0.
    for unit in query.units.values():
        displacement=None
        for member in unit.members:
            key=member+'.mesh';before=original[key];after=arranged[key]
            if (before['plate']!=1 or after['plate']!=1 or
                (before['name'],before['unitName'],before['color'],before['material'])!=
                (after['name'],after['unitName'],after['color'],after['material']) or
                len(before['triangles'])!=len(after['triangles'])):
                raise ValueError('Bambu 改变了实体、颜色或打印盘，已拒绝摆位结果。')
            if max(abs(before['matrix'][i][j]-after['matrix'][i][j]) for i in range(3) for j in range(3))>1e-5:
                raise ValueError('Bambu 改变了模型朝向，已拒绝摆位结果。')
            first,last=bounds(before['vertices']),bounds(after['vertices'])
            delta=tuple((last[0][i]+last[1][i]-first[0][i]-first[1][i])/2 for i in range(3))
            if abs(delta[2])>.001 or (displacement is not None and
                max(abs(delta[i]-displacement[i]) for i in range(3))>.001):
                raise ValueError('Bambu 改变了贴板高度或组内相对位置，已拒绝摆位结果。')
            translated=[tuple(v[i]+delta[i] for i in range(3)) for v in before['vertices']]
            error=max(nearest_error(translated,after['vertices']),nearest_error(after['vertices'],translated))
            volume_before=signed_volume(before['vertices'],before['triangles'])
            volume_after=signed_volume(after['vertices'],after['triangles'])
            if error>.001 or abs(volume_before-volume_after)>max(.02,abs(volume_before)*1e-5):
                raise ValueError('Bambu 改变了源网格，已拒绝摆位结果。')
            displacement=delta;maximum=max(maximum,error)
        old=query.placements[unit.uid]
        positions[unit.uid]={'x':old.x+displacement[0],'y':old.y+displacement[1]}
    return positions,maximum


def suggest_plate(session,number,catalog,executable):
    query=plate_query(session,number)
    with tempfile.TemporaryDirectory(prefix='BPS_arrange_') as directory:
        seed=Path(directory)/'query.3mf'
        write_project(seed,query,catalog,allow_unarranged=True)
        native,_=run_project(seed,directory,catalog,executable,arrange=True)
        return extract_positions(query,seed,native)


def suggest(session,numbers,catalog,executable):
    if session.rule_errors:raise ValueError('\n'.join(session.rule_errors))
    if not session.plates or set(session.placements)!=set(session.units):
        raise ValueError('请先将所有打印单元分盘，再使用 Bambu 自动摆位。')
    available={p.index for p in session.plates}
    if not numbers or len(set(numbers))!=len(numbers) or any(n not in available for n in numbers):
        raise ValueError('自动摆位的打印盘无效。')
    started=time.monotonic();proposals={};skipped=[];maximum=0.
    with ThreadPoolExecutor(max_workers=min(2,len(numbers))) as workers:
        futures={number:workers.submit(suggest_plate,session,number,catalog,executable) for number in numbers}
        for number in numbers:
            try:positions,error=futures[number].result()
            except PlateOverflow as exc:
                if len(numbers)==1:raise ValueError(f'第 {number} 盘：{exc}') from exc
                skipped.append({'plate':number,'reason':str(exc)})
                continue
            proposals.update(positions);maximum=max(maximum,error)
    trial=copy.copy(session)
    trial.units={uid:copy.copy(unit) for uid,unit in session.units.items()}
    trial.placements=copy.deepcopy(session.placements)
    for uid,position in proposals.items():
        trial.placements[uid].x=position['x'];trial.placements[uid].y=position['y']
    bed=Bed.from_profile(catalog.resolve('machine',session.config['printer']))
    errors,warnings=validate(trial,bed)
    if not proposals:errors.append('Bambu 未能在保留原盘号的条件下重新摆放任何打印盘。')
    moved=sum(abs(session.placements[uid].x-p['x'])>.001 or
              abs(session.placements[uid].y-p['y'])>.001 for uid,p in proposals.items())
    return {'plates':list(numbers),'placements':proposals,'skipped':skipped,'moved':moved,'total':len(proposals),
            'errors':errors,'warnings':warnings,'elapsedSeconds':time.monotonic()-started,'maxVertexErrorMm':maximum,
            'warning':'仅建议盘内 X/Y 位置；不换盘、不转向、不拆分整体。若未满足当前间距或板边距，不能确认应用。'}


def apply_positions(session,proposal):
    if proposal['errors']:raise ValueError('建议摆位不满足当前设置的安全间距或板边距，未应用。')
    for uid,position in proposal['placements'].items():
        session.placements[uid].x=position['x'];session.placements[uid].y=position['y']
