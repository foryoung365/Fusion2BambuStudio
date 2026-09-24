"""Read installed Bambu presets, resolving inheritance/includes without eval."""
import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path


BEDS = {
    'Supertack Plate': ('低温增稳板 / Cool Plate SuperTack', 'supertack_plate_temp'),
    'Textured PEI Plate': ('纹理 PEI 板', 'textured_plate_temp'),
    'High Temp Plate': ('光面 PEI / 高温板', 'hot_plate_temp'),
    'Engineering Plate': ('工程板', 'eng_plate_temp'),
    'Cool Plate': ('低温板（非 SuperTack）', 'cool_plate_temp'),
}
META = {'name', 'inherits', 'include', 'from', 'type', 'setting_id', 'instantiation',
        'description', 'version', 'filament_id', 'compatible_printers',
        'compatible_printers_condition', 'compatible_prints', 'compatible_prints_condition',
        'renamed_from', 'alias'}


@dataclass
class Profile:
    path: Path
    kind: str
    name: str
    vendor: str
    data: dict


class ProfileCatalog:
    def __init__(self, roots):
        self.records = {}
        self.errors = []
        for root in roots:
            root = Path(root)
            if not root.is_dir():
                continue
            for path in sorted(root.rglob('*.json')):
                if path.parent.name not in ('machine', 'process', 'filament'):
                    continue
                try:
                    data = json.loads(path.read_text(encoding='utf-8-sig'))
                    if isinstance(data, dict) and data.get('name'):
                        self.records[str(path.resolve())] = Profile(path.resolve(), path.parent.name,
                            data['name'], path.parent.parent.name, data)
                except (ValueError, OSError) as exc:
                    self.errors.append(f'{path.name}: {exc}')
        if not self.records:
            raise ValueError('未找到 Bambu Studio 预设，请选择其 resources/profiles 文件夹。')

    def find(self, kind, key, near=None):
        if key in self.records and self.records[key].kind == kind:
            return self.records[key]
        candidates = [p for p in self.records.values() if p.kind == kind and p.name == key]
        if near:
            local = [p for p in candidates if p.path.parent == near.path.parent]
            if local:
                candidates = local
        if len(candidates) != 1:
            raise ValueError(f'预设不存在或名称有歧义：{kind} / {key}')
        return candidates[0]

    def resolve(self, kind, key, stack=(), near=None):
        profile = self.find(kind, key, near)
        path = str(profile.path)
        if path in stack:
            raise ValueError('预设继承出现循环：'+profile.name)
        result = {}
        if profile.data.get('inherits'):
            result.update(self.resolve(kind, profile.data['inherits'], stack+(path,), profile))
        includes = profile.data.get('include', [])
        if not isinstance(includes, list):
            raise ValueError('预设 include 字段格式无效：'+profile.name)
        for include in includes:
            result.update(self.resolve(kind, include, stack+(path,), profile))
        result.update(copy.deepcopy(profile.data))
        result.pop('inherits', None)
        result.pop('include', None)
        return result

    def selectable(self, kind):
        return sorted((p for p in self.records.values() if p.kind == kind and
                       str(p.data.get('instantiation', 'true')).lower() == 'true'),
                      key=lambda p: (p.vendor, p.name))

    def compatible(self, kind, key, machine_name):
        data = self.resolve(kind, key)
        allowed = data.get('compatible_printers', [])
        if allowed:
            return machine_name in allowed
        # Conditions use Bambu's expression language, not Python. Do not eval them.
        if data.get('compatible_printers_condition'):
            return False
        return True

    def options(self, machine_key):
        machine = self.resolve('machine', machine_key)
        name = machine['name']
        def rows(kind):
            out = []
            for p in self.selectable(kind):
                if self.compatible(kind, str(p.path), name):
                    data = self.resolve(kind, str(p.path))
                    out.append({'key': str(p.path), 'name': p.name,
                                'material': (data.get('filament_type') or [''])[0]})
            return out
        return {'processes': rows('process'), 'filaments': rows('filament')}

    def check(self, config, profiles):
        machine = self.resolve('machine', config['printer'])
        process = self.resolve('process', config['process'])
        errors = []
        nozzles = machine.get('nozzle_diameter', [])
        if len(nozzles) != 1:
            errors.append('当前版本只验证了单喷嘴机器，暂不导出双喷嘴配置。')
        if not nozzles or str(nozzles[0]) != str(config['nozzle']):
            errors.append('喷嘴直径与打印机预设不一致。')
        if not self.compatible('process', config['process'], machine['name']):
            errors.append('工艺预设与所选打印机不匹配。')
        if config['bed'] not in BEDS:
            errors.append('未知打印板类型。')
        else:
            key = BEDS[config['bed']][1]
            for profile in set(profiles):
                filament = self.resolve('filament', profile)
                if not self.compatible('filament', profile, machine['name']):
                    errors.append('耗材与打印机不匹配：'+filament['name'])
                for temp_key in (key, key+'_initial_layer'):
                    values = filament.get(temp_key, [])
                    if not values or any(float(v) <= 0 for v in values):
                        errors.append('该耗材预设未提供此打印板的有效温度：'+filament['name'])
                        break
        return errors, machine, process


def profile_roots_for(executable):
    exe=Path(executable)
    try:
        if not exe.is_file():return []
        roots=[str(p) for p in (exe.parent/'resources'/'profiles',
                               exe.parent.parent/'resources'/'profiles',
                               exe.parent.parent/'Resources'/'profiles') if p.is_dir()]
    except OSError:
        return []
    if not roots:return []
    user=(Path(os.environ.get('APPDATA',''))/'BambuStudio'/'user' if os.name=='nt'
          else Path.home()/'Library'/'Application Support'/'BambuStudio'/'user')
    try:
        if user.is_dir():roots.append(str(user))
    except OSError:
        pass  # An inaccessible user profile must not hide the bundled presets.
    return roots


def _windows_registry_candidates():
    """Read installer locations; Bambu Studio may be installed on any drive."""
    try:
        import winreg
    except ImportError:
        return []

    def value(key, name):
        try:
            return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return ''

    def icon_path(icon):
        # Windows DisplayIcon commonly ends in an icon index such as `,0`.
        icon = str(icon).strip()
        if ',' in icon and icon.rsplit(',', 1)[1].strip().lstrip('-').isdigit():
            icon = icon.rsplit(',', 1)[0]
        return icon.strip().strip('"')

    candidates = []
    app_path = r'Software\Microsoft\Windows\CurrentVersion\App Paths\bambu-studio.exe'
    uninstall = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            access = winreg.KEY_READ | view
            try:
                with winreg.OpenKey(hive, app_path, 0, access) as key:
                    path = icon_path(value(key, ''))
                    if path:
                        candidates.append(Path(path))
            except OSError:
                pass
            try:
                with winreg.OpenKey(hive, uninstall, 0, access) as base:
                    index = 0
                    while True:
                        try:
                            name = winreg.EnumKey(base, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(base, name, 0, access) as key:
                                display = str(value(key, 'DisplayName')).casefold().replace(' ', '')
                                if not display.startswith('bambustudio'):
                                    continue
                                location = value(key, 'InstallLocation')
                                if location:
                                    candidates.append(Path(str(location).strip('"'))/'bambu-studio.exe')
                                icon = icon_path(value(key, 'DisplayIcon'))
                                if icon:
                                    candidates.append(Path(icon))
                        except OSError:
                            continue
            except OSError:
                pass
    return candidates


def discover():
    candidates = []
    if os.name == 'nt':
        candidates.extend(_windows_registry_candidates())
    search_roots = [os.environ.get('ProgramFiles', ''), os.environ.get('ProgramFiles(x86)', ''),
                    'D:/Program Files', 'C:/Program Files']
    if os.environ.get('LOCALAPPDATA'):
        search_roots.append(str(Path(os.environ['LOCALAPPDATA'])/'Programs'))
    for root in search_roots:
        if root:
            candidates.append(Path(root)/'Bambu Studio'/'bambu-studio.exe')
    if os.name != 'nt':
        candidates += [Path('/Applications/BambuStudio.app/Contents/MacOS/BambuStudio')]
    seen = set()
    for exe in candidates:
        key = os.path.normcase(str(exe))
        if key in seen:continue
        seen.add(key)
        roots=profile_roots_for(exe)
        if roots:return str(exe),roots
    return '', []


def project_settings(catalog, config, slots):
    """Keep machine/process vectors intact; concatenate filament vectors per slot."""
    errors, machine, process = catalog.check(config, [s['profile'] for s in slots])
    if errors:
        raise ValueError('\n'.join(errors))
    settings = {k: copy.deepcopy(v) for data in (machine, process) for k, v in data.items() if k not in META}
    filaments = [catalog.resolve('filament', slot['profile']) for slot in slots]
    keys = set().union(*(set(f)-META for f in filaments))
    for key in keys:
        if any(key not in f for f in filaments):
            raise ValueError('所选耗材预设的参数结构不一致：'+key)
        values = [f[key] for f in filaments]
        if all(isinstance(v, list) for v in values):
            sizes = {len(v) for v in values}
            if len(sizes) != 1:
                raise ValueError('所选耗材的喷嘴变体参数长度不一致：'+key)
            settings[key] = [item for value in values for item in value]
        elif all(v == values[0] for v in values):
            settings[key] = copy.deepcopy(values[0])
        else:
            raise ValueError('无法无损合并耗材标量参数：'+key)
    settings.update({'printer_settings_id': machine['name'], 'print_settings_id': process['name'],
                     'curr_bed_type': config['bed'], 'filament_colour': [s['color'] for s in slots],
                     'default_filament_colour': [s['color'] for s in slots],
                     'filament_settings_id': [f['name'] for f in filaments],
                     'filament_ids': [f.get('filament_id', '') for f in filaments]})
    if 'filament_self_index' in settings:
        stride = len(filaments[0]['filament_self_index'])
        settings['filament_self_index'] = [str(i+1) for i in range(len(slots)) for _ in range(stride)]
    settings['enable_support'] = '1' if config.get('enableSupport') else '0'
    return settings
