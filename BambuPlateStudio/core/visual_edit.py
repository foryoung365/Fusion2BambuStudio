"""Atomic visual edits; screen dragging never changes source mesh coordinates."""
import copy
from .model import PrintUnit, Placement
from .layout import footprint, spacing
from .geometry import rectangle_overlap


def merge_onto(session, source_id, target_id):
    if source_id == target_id:
        raise ValueError('不能将模型拖入自身。')
    source, target = session.units[source_id], session.units[target_id]
    members = target.members+source.members
    if len(members) != len(set(members)):
        raise ValueError('打印组包含重复实体。')
    # Target orientation wins; all geometry remains in original assembly coordinates.
    group = PrintUnit(target.uid, target.name if len(target.members)>1 else target.name+' · 整体',
                      members, target.rotation, target.face_token, target.orientation_label,
                      target.orientation_valid)
    session.units[target_id] = group
    del session.units[source_id]
    session.placements.pop(source_id, None)
    return group


class MixedPlateConfirmation(ValueError):
    def __init__(self, session, uid, index):
        message=f'将「{session.units[uid].name}」移入第 {index} 盘后，该盘将包含不同颜色或耗材。是否继续？'
        super().__init__(message)
        self.confirmation={'code':'mixed_plate_confirmation','unit':uid,'plate':index,'message':message}


def check_mixed_transfer(session, uid, index, confirmed=False):
    if index not in {p.index for p in session.plates}:
        raise ValueError('目标打印盘不存在。')
    peers=[p for p in session.placements.values() if p.plate==index and p.unit!=uid]
    mixed=any(session.material_key(session.units[p.unit])!=session.material_key(session.units[uid]) for p in peers)
    if mixed and not session.config.get('allowMixedPlates') and confirmed is not True:
        raise MixedPlateConfirmation(session,uid,index)
    return mixed


def approve_plate(session, index):
    next(p for p in session.plates if p.index==index).allow_mixed=True


def transfer_to_plate(session, uid, index, bed, confirm_mixed=False):
    mixed=check_mixed_transfer(session,uid,index,confirm_mixed)
    unit = session.units[uid]
    peers = [p for p in session.placements.values() if p.plate == index and p.unit != uid]
    old = session.placements.get(uid)
    angle = old.angle if old else 0.
    height = old.z if old else 0.
    _, _, size = unit.geometry(session.bodies, angle)
    if size[2]+height > bed.height+1e-6:
        raise ValueError('模型高度超过打印范围。')
    margin, gap = spacing(session)
    obstacles = [footprint(session,p) for p in peers]+list(bed.exclusions)
    xs = sorted({bed.origin_x+margin, *(r[0]+r[2]+gap for r in obstacles)})
    ys = sorted({bed.origin_y+margin, *(r[1]+r[3]+gap for r in obstacles)})
    candidates = [(old.x,old.y)] if old else []
    candidates += [(x,y) for y in ys for x in xs]
    for x,y in candidates:
        rect = (x,y,size[0],size[1])
        if (x < bed.origin_x+margin-1e-6 or y < bed.origin_y+margin-1e-6 or
            x+size[0] > bed.origin_x+bed.width-margin+1e-6 or y+size[1] > bed.origin_y+bed.depth-margin+1e-6):
            continue
        if any(rectangle_overlap(rect,r,gap) for r in obstacles):
            continue
        result = Placement(uid,index,x,y,angle,height)
        session.placements[uid] = result
        if mixed:approve_plate(session,index)
        return result
    raise ValueError('目标盘空间不足；模型保留在原盘，未改变方向或缩放。')


class EditHistory:
    def __init__(self, limit=30):
        self.limit, self.undo_stack, self.redo_stack = limit, [], []

    def clear(self):
        self.undo_stack.clear(); self.redo_stack.clear()

    def snapshot(self, session):
        return copy.deepcopy(session.rules())

    def commit(self, before, session):
        if before == session.rules():return
        self.undo_stack.append(before)
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()

    def restore(self, session, backwards=True):
        source = self.undo_stack if backwards else self.redo_stack
        target = self.redo_stack if backwards else self.undo_stack
        if not source:raise ValueError('没有可撤销的操作。' if backwards else '没有可重做的操作。')
        current = self.snapshot(session)
        rules = source[-1]
        session.apply_rules(rules)
        source.pop(); target.append(current)
