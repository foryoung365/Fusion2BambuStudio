"""Conservative 2D packing of rigid print units, plus authoritative edit validation."""
import math
from dataclasses import dataclass
from .geometry import rectangle_overlap
from .footprint import project_unit,footprints_clearance
from .model import Placement, Plate


@dataclass
class Bed:
    width: float
    depth: float
    height: float
    origin_x: float = 0.
    origin_y: float = 0.
    exclusions: tuple = ()

    @classmethod
    def from_profile(cls, profile):
        def point(text):
            return tuple(float(v) for v in text.lower().split('x'))
        points = [point(p) for p in profile.get('printable_area', [])]
        if len(points) != 4:
            raise ValueError('当前排盘器需要矩形打印区域。')
        xs, ys = sorted(set(p[0] for p in points)), sorted(set(p[1] for p in points))
        if len(xs) != 2 or len(ys) != 2 or set(points) != {(x, y) for x in xs for y in ys}:
            raise ValueError('打印区域不是矩形，不能用其包围盒替代有效打印范围。')
        excluded = [point(p) for p in profile.get('bed_exclude_area', [])]
        exclusions = ()
        if excluded:
            minx, miny = min(p[0] for p in excluded), min(p[1] for p in excluded)
            exclusions = ((minx, miny, max(p[0] for p in excluded)-minx,
                           max(p[1] for p in excluded)-miny),)
        return cls(xs[-1]-xs[0], ys[-1]-ys[0], float(profile['printable_height']),
                   xs[0], ys[0], exclusions)


def footprint(session, placement):
    _, _, size = session.units[placement.unit].geometry(session.bodies, placement.angle)
    return (placement.x, placement.y, size[0], size[1])


def process_clearance(process, supports):
    def number(key, default=0.):
        value=process.get(key, default)
        if isinstance(value,list):value=value[0] if value else default
        return float(value)
    brim_type=process.get('brim_type','auto_brim')
    if isinstance(brim_type,list):brim_type=brim_type[0]
    brim=0. if brim_type in ('auto_brim','no_brim','none',None) else number('brim_width')+number('brim_object_gap')
    support=0.
    if supports:
        support=max(number('support_object_xy_distance'),number('tree_support_branch_diameter')/2,
                    number('tree_support_tip_diameter')/2)
    return max(0.,brim,support)


def auto_brim_reserve(process):
    brim_type=process.get('brim_type','auto_brim')
    if isinstance(brim_type,list):brim_type=brim_type[0] if brim_type else 'auto_brim'
    if brim_type not in ('auto_brim',None):return 0.
    def number(key):
        value=process.get(key,0.)
        return float(value[0] if isinstance(value,list) and value else value)
    return max(0.,number('brim_width')+number('brim_object_gap'))


def spacing(session):
    reserve=float(session.config.get('printClearance',0.))
    gap, margin=float(session.config['gap']),float(session.config['margin'])
    if not all(math.isfinite(v) and v>=0 for v in (reserve,gap,margin)):
        raise ValueError('边距、间距与打印占地预留必须是有限非负数。')
    return margin+reserve,gap+2*reserve


def validate(session, bed):
    errors, warnings = list(session.rule_errors), []
    try:
        margin,gap=spacing(session)
    except ValueError as exc:
        return [str(exc)],[]
    if not all(math.isfinite(v) and v >= 0 for v in (margin, gap)):
        return ['边距与零件间距必须是有限非负数。'], []
    indices = [p.index for p in session.plates]
    if sorted(indices) != list(range(1, len(indices)+1)):
        errors.append('盘号需要从 1 开始连续且唯一。')
    if set(session.placements) != set(session.units):
        errors.append('尚有打印单元未排入盘中。')
    grouped = [b for u in session.units.values() for b in u.members]
    if sorted(grouped) != sorted(session.bodies):
        errors.append('打印组未完整且唯一地覆盖全部实体。')
    by_plate = {}
    projections={}
    auto_brim_edges=auto_brim_pairs=0
    auto_brim=float(session.config.get('autoBrimReserve',0.))
    for placement in session.placements.values():
        if placement.unit not in session.units or placement.plate not in indices:
            errors.append('盘位引用无效。')
            continue
        if not all(math.isfinite(x) for x in (placement.x, placement.y, placement.angle, placement.z)):
            errors.append('盘位包含无效数值。')
            continue
        unit = session.units[placement.unit]
        if not unit.orientation_valid:
            errors.append('贴板面引用已失效，请重新指定：'+unit.name)
        rotation, box, size = unit.geometry(session.bodies, placement.angle)
        rect = footprint(session, placement)
        if (rect[0] < bed.origin_x-1e-6 or rect[1] < bed.origin_y-1e-6 or
            rect[0]+rect[2] > bed.origin_x+bed.width+1e-6 or
            rect[1]+rect[3] > bed.origin_y+bed.depth+1e-6):
            errors.append('超出打印板实际范围：'+unit.name)
        elif (rect[0] < bed.origin_x+margin-1e-6 or rect[1] < bed.origin_y+margin-1e-6 or
            rect[0]+rect[2] > bed.origin_x+bed.width-margin+1e-6 or
            rect[1]+rect[3] > bed.origin_y+bed.depth-margin+1e-6):
            errors.append('未满足设置的板边距或明确启用的裙边预留：'+unit.name)
        if size[2]+placement.z > bed.height+1e-6 or placement.z < -1e-6:
            errors.append('超出打印高度：'+unit.name)
        if auto_brim and (rect[0] < bed.origin_x+margin+auto_brim-1e-6 or
            rect[1] < bed.origin_y+margin+auto_brim-1e-6 or
            rect[0]+rect[2] > bed.origin_x+bed.width-margin-auto_brim+1e-6 or
            rect[1]+rect[3] > bed.origin_y+bed.depth-margin-auto_brim+1e-6):
            auto_brim_edges+=1
        if any(rectangle_overlap(rect, exclusion, gap) for exclusion in bed.exclusions):
            errors.append('进入打印板禁用区：'+unit.name)
        peers = by_plate.setdefault(placement.plate, [])
        for other in peers:
            other_rect=footprint(session,other)
            box_close=rectangle_overlap(rect,other_rect,gap)
            distance=None
            if box_close:
                for candidate in (placement,other):
                    if candidate.unit not in projections:
                        projections[candidate.unit]=project_unit(session,candidate)
                distance=footprints_clearance(projections[placement.unit],projections[other.unit],gap)
            if distance is not None:
                errors.append(f'检测到实体轮廓间距约 {distance:.2f} mm，小于设置的 {gap:g} mm：'+unit.name+' / '+session.units[other.unit].name)
            elif auto_brim and rectangle_overlap(rect,other_rect,gap+2*auto_brim):
                auto_brim_pairs+=1
        peers.append(placement)
        for member in unit.members:
            body = session.bodies[member]
            if len(body.face_colors) > 1 and member not in session.color_overrides:
                errors.append('实体含多种面颜色，请明确选择整件打印颜色：'+body.name)
            low_z = min(sum(rotation[2][i]*v[i] for i in range(3)) for v in body.vertices)-box[0][2]+placement.z
            if low_z > 0.05:
                warnings.append(f'整体中的 {body.name} 离板 {low_z:.2f} mm，请核查支撑或贴板方向。')
            if any(body.issues.get(k, 0) for k in ('boundaryEdges', 'nonManifoldEdges', 'degenerateTriangles')):
                warnings.append('保留原网格异常，未自动修复：'+body.name)
    for number, placements in by_plate.items():
        keys = {session.material_key(session.units[p.unit]) for p in placements}
        approved=next((p.allow_mixed for p in session.plates if p.index==number),False)
        if len(keys) > 1 and not session.config.get('allowMixedPlates') and not approved:
            errors.append(f'第 {number} 盘包含不同颜色/耗材单元；请分盘或明确允许混色。')
        elif len(keys)>1:
            warnings.append(f'第 {number} 盘为已确认的手动混色盘，请核查换料方式与耗材兼容性。')
        if any(len(key) > 1 for key in keys):
            warnings.append(f'第 {number} 盘含多色不可拆分整体，需多材料切换，不能拆到不同盘。')
    if auto_brim_edges or auto_brim_pairs:
        warnings.append(f'自动裙边若实际生成，{auto_brim_edges} 件模型靠近预留边界、{auto_brim_pairs} 对模型可能需要额外空间；这不是实体碰撞，请切片确认。')
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


def centered_shift(rects, bed, margin, gap):
    """Translate a compact cluster nearest the bed center, respecting fixed exclusions."""
    left=min(r[0] for r in rects);bottom=min(r[1] for r in rects)
    right=max(r[0]+r[2] for r in rects);top=max(r[1]+r[3] for r in rects)
    low_x=bed.origin_x+margin-left;high_x=bed.origin_x+bed.width-margin-right
    low_y=bed.origin_y+margin-bottom;high_y=bed.origin_y+bed.depth-margin-top
    if low_x>high_x+1e-7 or low_y>high_y+1e-7:return None
    dx=bed.origin_x+bed.width/2-(left+right)/2
    dy=bed.origin_y+bed.depth/2-(bottom+top)/2
    def allowed(x,y):
        if not low_x-1e-7<=x<=high_x+1e-7 or not low_y-1e-7<=y<=high_y+1e-7:return False
        return not any(rectangle_overlap((r[0]+x,r[1]+y,r[2],r[3]),e,gap)
                       for r in rects for e in bed.exclusions)
    if allowed(dx,dy):return dx,dy,0.
    xs={max(low_x,min(high_x,dx)),low_x,high_x}
    ys={max(low_y,min(high_y,dy)),low_y,high_y}
    for r in rects:
        for e in bed.exclusions:
            xs.update((e[0]-gap-r[0]-r[2],e[0]+e[2]+gap-r[0]))
            ys.update((e[1]-gap-r[1]-r[3],e[1]+e[3]+gap-r[1]))
    choices=[(((x-dx)/bed.width)**2+((y-dy)/bed.depth)**2,x,y)
             for x in xs for y in ys if allowed(x,y)]
    if not choices:return None
    error,x,y=min(choices)
    return x,y,error


def arrange(session, bed):
    if session.rule_errors:raise ValueError('\n'.join(session.rule_errors))
    margin,gap=spacing(session)
    if not all(math.isfinite(v) and v >= 0 for v in (margin, gap)):
        raise ValueError('边距与间距必须是非负数。')
    placements, plates, buckets = {}, [], {}
    units = sorted(session.units.values(), key=lambda u: (-u.geometry(session.bodies)[2][0]*
                    u.geometry(session.bodies)[2][1], u.name, u.uid))
    for unit in units:
        if not unit.orientation_valid:
            raise ValueError('贴板面引用已失效，请重新指定：'+unit.name)
        key = session.material_key(unit)
        candidates = buckets.setdefault(key, [])
        angles = (0., 90.) if session.config.get('allowZRotation') else (0.,)
        best = None
        # Start at the center, then grow around already centered print units.
        # Recenter the provisional cluster while it grows so a centered first
        # object does not unnecessarily split a physically packable plate.
        for plate in candidates+[len(plates)+1]:
            peers = [p for p in placements.values() if p.plate == plate]
            obstacles = [footprint(session, p) for p in peers]
            for angle in angles:
                _, _, size = unit.geometry(session.bodies, angle)
                if size[2] > bed.height+1e-6:
                    continue
                w,h=size[:2]
                xs={bed.origin_x+(bed.width-w)/2}
                ys={bed.origin_y+(bed.depth-h)/2}
                for x,y,width,height in obstacles:
                    xs.update((x-w-gap,x+width+gap,x,x+width-w,x+(width-w)/2))
                    ys.update((y-h-gap,y+height+gap,y,y+height-h,y+(height-h)/2))
                for y in sorted(ys):
                    for x in sorted(xs):
                        rect = (x, y, w, h)
                        if any(rectangle_overlap(rect, obstacle, gap) for obstacle in obstacles):
                            continue
                        rects=obstacles+[rect]
                        shift=centered_shift(rects,bed,margin,gap)
                        if shift is None:continue
                        dx,dy,center_error=shift
                        span_x=max(r[0]+r[2] for r in rects)-min(r[0] for r in rects)
                        span_y=max(r[1]+r[3] for r in rects)-min(r[1] for r in rects)
                        radial=sum(((r[0]+r[2]/2+dx-bed.origin_x-bed.width/2)/bed.width)**2+
                                   ((r[1]+r[3]/2+dy-bed.origin_y-bed.depth/2)/bed.depth)**2 for r in rects)
                        score = (plate not in candidates,plate,center_error,
                                 max(span_x/bed.width,span_y/bed.depth),span_x*span_y,radial,angle,y,x)
                        if best is None or score < best[0]:
                            best = (score, Placement(unit.uid,plate,x+dx,y+dy,angle),dx,dy)
            if best and plate in candidates:
                break
        if best is None:
            raise ValueError('无法放入所选打印板，未缩放或拆分：'+unit.name)
        placement = best[1]
        if placement.plate > len(plates):
            plates.append(Plate(placement.plate, ', '.join(c for c, _ in key)))
            candidates.append(placement.plate)
        for uid,p in list(placements.items()):
            if p.plate==placement.plate:
                placements[uid]=Placement(uid,p.plate,p.x+best[2],p.y+best[3],p.angle,p.z)
        placements[unit.uid] = placement
    previous=session.placements,session.plates
    session.placements, session.plates = placements, plates
    errors, warnings = validate(session, bed)
    if errors:
        session.placements,session.plates=previous
        raise ValueError('\n'.join(errors))
    return warnings


def scene_origin(index, count, bed):
    columns = math.ceil(math.sqrt(count))
    return ((index-1) % columns*bed.width*1.2, -((index-1)//columns)*bed.depth*1.2)
