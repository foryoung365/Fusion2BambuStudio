"""Serializable printing rules kept separate from the source CAD design."""
import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from .geometry import IDENTITY, bounds, rotate, multiply, axis_rotation, affine, mesh_issues, validate_rotation


def new_id():
    return uuid.uuid4().hex


@dataclass
class Body:
    uid: str
    name: str
    component_path: str
    color: str
    vertices: list
    triangles: list
    token: str = ''
    face_colors: dict = field(default_factory=dict)
    issues: dict = field(default_factory=dict)

    def validate(self):
        self.issues = mesh_issues(self.vertices, self.triangles)
        return self.issues

    def fingerprint(self):
        data = json.dumps([self.vertices, self.triangles], separators=(',', ':'))
        return hashlib.sha256(data.encode()).hexdigest()

    def geometry_key(self):
        """Exact geometry, independent of vertex/triangle enumeration order.

        Do not round coordinates or discard multiplicities/winding: real edits,
        reversed faces, duplicate triangles and isolated vertices remain detectable.
        """
        vertices=[tuple(0.0 if value==0 else float(value) for value in p) for p in self.vertices]
        triangles=[]
        for indices in self.triangles:
            p=tuple(vertices[i] for i in indices)
            triangles.append(min(p,p[1:]+p[:1],p[2:]+p[:2]))
        payload=json.dumps([sorted(vertices),sorted(triangles)],separators=(',',':'),allow_nan=False)
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class PrintUnit:
    uid: str
    name: str
    members: list
    rotation: tuple = IDENTITY
    face_token: str = ''
    orientation_label: str = '保持原方向'
    orientation_valid: bool = True

    def geometry(self, bodies, z_angle=0.):
        validate_rotation(self.rotation)
        key = (tuple(tuple(r) for r in self.rotation), z_angle,
               tuple((uid, id(bodies[uid].vertices)) for uid in self.members))
        if getattr(self, '_geometry_key', None) == key:
            return self._geometry_result
        rotation = multiply(axis_rotation((0, 0, 1), z_angle), self.rotation)
        box = bounds(rotate(rotation, p) for uid in self.members for p in bodies[uid].vertices)
        result = rotation, box, tuple(box[1][i]-box[0][i] for i in range(3))
        self._geometry_key, self._geometry_result = key, result
        return result

    def matrix(self, bodies, placement, scene_origin=(0., 0.)):
        rotation, box, _ = self.geometry(bodies, placement.angle)
        return affine(rotation, (placement.x-box[0][0]+scene_origin[0],
                                 placement.y-box[0][1]+scene_origin[1], placement.z-box[0][2]))


@dataclass
class Placement:
    unit: str
    plate: int
    x: float
    y: float
    angle: float = 0.
    z: float = 0.


@dataclass
class Plate:
    index: int
    name: str = ''
    allow_mixed: bool = False


DEFAULT_CONFIG = {
    'printer': 'Bambu Lab P2S 0.4 nozzle', 'nozzle': '0.4',
    'process': '0.20mm Standard @BBL P2S', 'bed': 'Supertack Plate',
    'material': 'PETG', 'filament': 'Generic PETG @BBL P2S',
    'gap': 5., 'margin': 5., 'allowZRotation': True, 'allowMixedPlates': False,
    'includeHidden': False, 'refinement': 'high', 'enableSupport': False,
    'printClearance': 0.,
}


class Session:
    def __init__(self, bodies=()):
        self.bodies = {b.uid: b for b in bodies}
        self.units = {b.uid: PrintUnit(b.uid, b.name, [b.uid]) for b in bodies}
        self.placements = {}
        self.plates = []
        self.config = dict(DEFAULT_CONFIG)
        self.color_profiles = {}
        self.color_overrides = {}
        self.rule_errors = []

    def reset_units(self):
        self.units={uid:PrintUnit(uid,body.name,[uid]) for uid,body in self.bodies.items()}
        self.rule_errors=[]
        self.invalidate_layout()

    def effective_color(self, uid):
        return self.color_overrides.get(uid, self.bodies[uid].color).upper()

    def material_key(self, unit):
        return tuple(sorted({(self.effective_color(uid), self.color_profiles.get(
            self.effective_color(uid), self.config['filament'])) for uid in unit.members}))

    def group(self, unit_ids, name):
        if len(set(unit_ids)) != len(unit_ids):
            raise ValueError('同一打印单元不能重复加入整体。')
        selected = [self.units[i] for i in unit_ids]
        if len(selected) < 2:
            raise ValueError('请至少选择两个打印单元。')
        if any(u.rotation != IDENTITY for u in selected):
            raise ValueError('请先将所选单元恢复原方向，再按原装配关系组合。')
        group = PrintUnit(new_id(), name.strip() or '整体打印组',
                          [uid for u in selected for uid in u.members])
        for u in selected:
            del self.units[u.uid]
        self.units[group.uid] = group
        self.invalidate_layout()
        return group

    def ungroup(self, uid):
        if len(self.units[uid].members) < 2:
            raise ValueError('当前单元不是多实体整体，无需解除。')
        unit = self.units[uid]
        placement = self.placements.get(uid)
        box = unit.geometry(self.bodies,placement.angle)[1] if placement else None
        released, placements = {}, {}
        for member in unit.members:
            body = self.bodies[member]
            child = PrintUnit(member, body.name, [member], unit.rotation,
                              orientation_label='继承已解除整体的方向',
                              orientation_valid=unit.orientation_valid)
            released[member] = child
            if placement:
                child_box=child.geometry(self.bodies,placement.angle)[1]
                placements[member]=Placement(member,placement.plate,
                    placement.x+child_box[0][0]-box[0][0],
                    placement.y+child_box[0][1]-box[0][1],placement.angle,
                    placement.z+child_box[0][2]-box[0][2])
        self.units.pop(uid)
        self.placements.pop(uid, None)
        self.units.update(released)
        self.placements.update(placements)
        if placement and len(self.material_key(unit))>1:
            next(p for p in self.plates if p.index==placement.plate).allow_mixed=True
        return list(unit.members)

    def invalidate_layout(self):
        self.placements, self.plates = {}, []

    def rules(self):
        return {'version': 1, 'config': self.config, 'colorProfiles': self.color_profiles,
                'colorOverrides': self.color_overrides,
                'ruleErrors': list(self.rule_errors),
                'sources': [{'uid': b.uid, 'token': b.token, 'path': b.component_path,
                             'name': b.name, 'fingerprint': b.fingerprint(),
                             'geometryKey': b.geometry_key(),
                             'color': b.color, 'faceColors': b.face_colors} for b in self.bodies.values()],
                'units': [asdict(u) for u in self.units.values()],
                'placements': [asdict(p) for p in self.placements.values()],
                'plates': [asdict(p) for p in self.plates]}

    def apply_rules(self, rules, aliases=None):
        if rules.get('version') != 1:
            raise ValueError('保存的规则版本不受支持。')
        aliases = aliases or {}
        remap = lambda uid: aliases.get(uid, uid)
        self.config.update(rules.get('config', {}))
        self.color_profiles = dict(rules.get('colorProfiles', {}))
        self.color_overrides = {remap(k): v for k, v in rules.get('colorOverrides', {}).items()
                                if remap(k) in self.bodies}
        kept, claimed, notices = {}, set(), []
        self.rule_errors=list(rules.get('ruleErrors',[]))
        for data in rules.get('units', []):
            members = [remap(m) for m in data['members']]
            if not members or len(set(members)) != len(members):
                raise ValueError('保存的打印组含空成员或重复成员。')
            validate_rotation(data['rotation'])
            if any(m not in self.bodies or m in claimed for m in members):
                notices.append('部分实体已改变，未恢复打印组：'+data['name'])
                self.rule_errors.append('打印组引用失效，必须确认重建，不能自动拆散：'+data['name'])
                continue
            kept[data['uid']] = PrintUnit(data['uid'], data['name'], members,
                                         tuple(tuple(r) for r in data['rotation']),
                                         data.get('face_token', ''), data.get('orientation_label', ''),
                                         data.get('orientation_valid',True))
            claimed.update(members)
        for uid, body in self.bodies.items():
            if uid not in claimed:
                kept[uid] = PrintUnit(uid, body.name, [uid])
        self.units = kept
        unchanged = len(rules.get('sources', [])) == len(self.bodies) and all(
            remap(s['uid']) in self.bodies and (
                self.bodies[remap(s['uid'])].fingerprint() == s['fingerprint'] or
                (s.get('geometryKey') and self.bodies[remap(s['uid'])].geometry_key() == s['geometryKey']))
            and self.bodies[remap(s['uid'])].color == s.get('color', self.bodies[remap(s['uid'])].color)
            and self.bodies[remap(s['uid'])].face_colors == s.get('faceColors', self.bodies[remap(s['uid'])].face_colors)
            for s in rules.get('sources', []))
        self.invalidate_layout()
        if unchanged and not notices:
            self.plates = [Plate(**p) for p in rules.get('plates', [])]
            self.placements = {p['unit']: Placement(**p) for p in rules.get('placements', [])
                               if p['unit'] in self.units}
        else:
            notices.append('源几何或颜色发生变化，请重新检查贴板方向并排盘。')
        return notices
