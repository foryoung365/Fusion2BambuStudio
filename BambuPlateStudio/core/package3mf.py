"""Bambu-compatible unsliced multi-plate 3MF; no geometry repair or shell merging."""
import hashlib
import json
import math
import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from .geometry import encode_3mf, bounds, transform_point
from .layout import Bed, validate, scene_origin, process_clearance, auto_brim_reserve
from .profiles import project_settings

CORE = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
RELS = 'http://schemas.openxmlformats.org/package/2006/relationships'
MODEL_TYPE = 'http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel'
NS = {'c': CORE}


def xml(element):
    # Explicit xmlns on literal, unprefixed tags: do not mutate ET's global namespace map.
    return ET.tostring(element, encoding='utf-8', xml_declaration=True)


def meta(parent, key, value):
    ET.SubElement(parent, 'metadata', key=key, value=str(value))


def slots_for(session):
    keys = sorted({(session.effective_color(uid), session.color_profiles.get(
                   session.effective_color(uid), session.config['filament'])) for uid in session.bodies})
    if any(not re.fullmatch(r'#[0-9A-F]{6}', color) for color, _ in keys):
        raise ValueError('存在无法识别的外观颜色，请明确指定打印颜色。')
    slots = [{'color': color, 'profile': profile} for color, profile in keys]
    body_slots = {uid: 1+keys.index((session.effective_color(uid), session.color_profiles.get(
                  session.effective_color(uid), session.config['filament']))) for uid in session.bodies}
    return slots, body_slots


def write_project(path, session, catalog, allow_unarranged=False):
    path = Path(path).resolve()
    if path.suffix.lower() != '.3mf':
        raise ValueError('输出文件必须使用 .3mf 扩展名。')
    if path.exists():
        raise FileExistsError('为避免覆盖已有项目，请选择新的文件名：'+str(path))
    slots, body_slots = slots_for(session)
    settings = project_settings(catalog, session.config, slots)
    # Seed export must also protect direct callers restoring an old zero-clearance layout.
    process=catalog.resolve('process', session.config['process'])
    session.config['printClearance'] = process_clearance(process, session.config['enableSupport'])
    session.config['autoBrimReserve'] = auto_brim_reserve(process)
    bed = Bed.from_profile(catalog.resolve('machine', session.config['printer']))
    errors, warnings = validate(session, bed)
    # A scratch input for Bambu --arrange may start with bad XY positions;
    # final exports still enforce every validation error.
    xy_errors=('超出打印板实际范围：','未满足设置的板边距或明确启用的裙边预留：',
               '进入打印板禁用区：','包围矩形未满足设置的实体间距：')
    blocking=[error for error in errors if not (allow_unarranged and error.startswith(xy_errors))]
    if blocking:
        raise ValueError('\n'.join(blocking))
    if not session.plates:
        raise ValueError('没有已排布的打印盘。')
    plate_slots = {p.index: set() for p in session.plates}
    for uid, placement in session.placements.items():
        plate_slots[placement.plate].update(body_slots[m] for m in session.units[uid].members)
    if all(len(s) <= 1 for s in plate_slots.values()):
        # Seven colors across seven single-material plates do not need a wipe tower.
        settings['enable_prime_tower'] = '0'

    model = ET.Element('model', {'xmlns': CORE, 'unit': 'millimeter', 'xml:lang': 'zh-CN'})
    ET.SubElement(model, 'metadata', name='Application').text = 'BambuPlateStudio 0.1.11'
    ET.SubElement(model, 'metadata', name='BambuStudio:3mfVersion').text = '1'
    resources, build = ET.SubElement(model, 'resources'), ET.SubElement(model, 'build')
    model_config = ET.Element('config')
    resource_ids, next_id = {}, 1
    for uid, body in session.bodies.items():
        body.validate()
        resource_ids[uid] = next_id
        obj = ET.SubElement(resources, 'object', id=str(next_id), type='model', name=body.name)
        mesh = ET.SubElement(obj, 'mesh')
        vertices, triangles = ET.SubElement(mesh, 'vertices'), ET.SubElement(mesh, 'triangles')
        for vertex in body.vertices:
            ET.SubElement(vertices, 'vertex', **dict(zip(('x', 'y', 'z'), (format(v, '.17g') for v in vertex))))
        for a, b, c in body.triangles:
            ET.SubElement(triangles, 'triangle', v1=str(a), v2=str(b), v3=str(c))
        next_id += 1

    unit_ids, audit = {}, []
    for uid, unit in session.units.items():
        unit_ids[uid] = next_id
        obj = ET.SubElement(resources, 'object', id=str(next_id), type='model', name=unit.name)
        components = ET.SubElement(obj, 'components')
        config_obj = ET.SubElement(model_config, 'object', id=str(next_id))
        meta(config_obj, 'name', unit.name)
        meta(config_obj, 'extruder', body_slots[unit.members[0]])
        ET.SubElement(config_obj, 'metadata', face_count=str(sum(len(session.bodies[m].triangles) for m in unit.members)))
        for member in unit.members:
            body = session.bodies[member]
            ET.SubElement(components, 'component', objectid=str(resource_ids[member]))
            part = ET.SubElement(config_obj, 'part', id=str(resource_ids[member]), subtype='normal_part')
            meta(part, 'name', body.name)
            meta(part, 'extruder', body_slots[member])
            meta(part, 'source_file', member+'.mesh')
            meta(part, 'source_object_id', 0)
            meta(part, 'source_volume_id', 0)
            ET.SubElement(part, 'mesh_stat', face_count=str(len(body.triangles)), edges_fixed='0',
                          degenerate_facets='0', facets_removed='0', facets_reversed='0', backwards_edges='0')
        placement = session.placements[uid]
        origin = scene_origin(placement.plate, len(session.plates), bed)
        matrix = unit.matrix(session.bodies, placement, origin)
        ET.SubElement(build, 'item', objectid=str(next_id), transform=encode_3mf(matrix), printable='1')
        audit.append({'unit': uid, 'objectId': next_id, 'members': unit.members, 'plate': placement.plate,
                      'sceneOriginMm': origin, 'matrix': matrix,
                      'bboxSceneMm': bounds(transform_point(matrix, p) for m in unit.members
                                             for p in session.bodies[m].vertices)})
        next_id += 1
    for plate in session.plates:
        p = ET.SubElement(model_config, 'plate')
        meta(p, 'plater_id', plate.index)
        meta(p, 'plater_name', plate.name or f'第 {plate.index} 盘')
        meta(p, 'locked', 'false')
        for placement in session.placements.values():
            if placement.plate == plate.index:
                instance = ET.SubElement(p, 'model_instance')
                meta(instance, 'object_id', unit_ids[placement.unit])
                meta(instance, 'instance_id', 0)
                meta(instance, 'identify_id', unit_ids[placement.unit])
    relationships = ET.Element('Relationships', xmlns=RELS)
    ET.SubElement(relationships, 'Relationship', Target='/3D/3dmodel.model', Id='rel-1', Type=MODEL_TYPE)
    types = ET.Element('Types', xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    for extension, kind in (('rels', 'application/vnd.openxmlformats-package.relationships+xml'),
                            ('model', 'application/vnd.ms-package.3dmanufacturing-3dmodel+xml'),
                            ('config', 'application/octet-stream'), ('json', 'application/json')):
        ET.SubElement(types, 'Default', Extension=extension, ContentType=kind)
    report = {'schema': 1, 'bodies': len(session.bodies), 'objects': len(session.units),
              'plates': len(session.plates), 'slots': slots, 'units': audit, 'warnings': warnings,
              'sourceMeshHashes': {uid: b.fingerprint() for uid, b in session.bodies.items()},
              'configuration': dict(session.config),
              'status': 'structurally_valid_not_yet_slicer_tested', 'sliced': False}
    contents = {'[Content_Types].xml': xml(types), '_rels/.rels': xml(relationships),
                '3D/3dmodel.model': xml(model), 'Metadata/model_settings.config': xml(model_config),
                'Metadata/project_settings.config': json.dumps(settings, ensure_ascii=False, indent=2).encode(),
                'Metadata/BambuPlateStudio.json': json.dumps(report, ensure_ascii=False, indent=2).encode()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.stem+'.', suffix='.tmp', delete=False) as stream:
            temp = Path(stream.name)
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        verification = inspect_project(temp)
        assert verification['bodies'] == len(session.bodies) and verification['objects'] == len(session.units)
        # Exclusive final creation, then copy; a concurrent file must never be overwritten.
        with path.open('xb') as destination, temp.open('rb') as source:
            while chunk := source.read(1024*1024):
                destination.write(chunk)
        report['path'] = str(path)
        report['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        return report
    finally:
        if temp and temp.exists():
            temp.unlink()  # Exact temporary file created by this invocation only.


def inspect_project(path):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError('3MF 压缩包校验失败。')
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('3MF 包含重复文件名。')
        rel = archive.read('_rels/.rels')
        if b'<Relationship ' not in rel or b'ns0:' in rel:
            raise ValueError('入口引用必须使用 Bambu 可识别的未加前缀标签。')
        for child in ET.fromstring(rel):
            if child.attrib['Target'].lstrip('/') not in names:
                raise ValueError('3MF 包含悬空入口引用。')
        root = ET.fromstring(archive.read('3D/3dmodel.model'))
        if root.attrib.get('unit') != 'millimeter':
            raise ValueError('3MF 单位不是毫米。')
        resources = {o.attrib['id']: o for o in root.findall('c:resources/c:object', NS)}
        mesh_count = sum(o.find('c:mesh', NS) is not None for o in resources.values())
        build = root.findall('c:build/c:item', NS)
        for item in build:
            obj = resources[item.attrib['objectid']]
            for component in obj.findall('c:components/c:component', NS):
                if component.attrib['objectid'] not in resources:
                    raise ValueError('打印对象引用了不存在的网格。')
            if any(not math.isfinite(float(v)) for v in item.get('transform', '').split()):
                raise ValueError('变换含非有限数值。')
        config = ET.fromstring(archive.read('Metadata/model_settings.config'))
        assigned = []
        for plate in config.findall('plate'):
            assigned += [m.get('value') for i in plate.findall('model_instance')
                         for m in i.findall('metadata') if m.get('key') == 'object_id']
        if sorted(assigned) != sorted(i.get('objectid') for i in build):
            raise ValueError('对象未唯一地分配到打印盘。')
        settings = json.loads(archive.read('Metadata/project_settings.config'))
        n = len(settings['filament_colour'])
        if len(settings['filament_settings_id']) != n:
            raise ValueError('耗材颜色与预设槽数不一致。')
        for part in config.findall('object/part'):
            slot = next(int(m.get('value')) for m in part.findall('metadata') if m.get('key') == 'extruder')
            if not 1 <= slot <= n:
                raise ValueError('实体耗材槽超出范围。')
        return {'bodies': mesh_count, 'objects': len(build), 'plates': len(config.findall('plate')),
                'colors': n, 'hasGcode': any(name.endswith('.gcode') for name in names)}
