"""Discovery should work when Bambu Studio is installed outside Program Files."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from BambuPlateStudio.core.model import Session
from BambuPlateStudio.core.profiles import ProfileCatalog, discover, profile_roots_for


class _Key:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Registry:
    HKEY_CURRENT_USER = 'HKCU'
    HKEY_LOCAL_MACHINE = 'HKLM'
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x100
    KEY_WOW64_32KEY = 0x200

    def __init__(self, executable):
        self.executable = executable

    def OpenKey(self, root, path, reserved=0, access=0):
        if isinstance(root, _Key):
            path = root.path + '\\' + path
        else:
            path = root + '\\' + path
        if path.endswith('\\Uninstall') or path.endswith('\\BambuStudio'):
            return _Key(path)
        raise FileNotFoundError(path)

    def EnumKey(self, key, index):
        if index == 0:
            return 'BambuStudio'
        raise OSError('end of registry key')

    def QueryValueEx(self, key, name):
        if name == 'DisplayName':
            return 'Bambu Studio', 1
        if name == 'DisplayIcon':
            return f'"{self.executable}",0', 1
        if name == 'InstallLocation':
            return '', 1
        raise FileNotFoundError(name)


@unittest.skipUnless(os.name == 'nt', 'Windows installation discovery')
class DiscoveryTests(unittest.TestCase):
    def test_registry_installation_outside_program_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / 'Other Drive' / 'Bambu Studio' / 'bambu-studio.exe'
            exe.parent.mkdir(parents=True)
            exe.touch()
            machine = exe.parent / 'resources' / 'profiles' / 'BBL' / 'machine'
            machine.mkdir(parents=True)
            (machine / 'test.json').write_text(json.dumps({'name': 'Test printer'}), encoding='utf-8')
            user_machine = root / 'user' / 'BambuStudio' / 'user' / 'BBL' / 'machine'
            user_machine.mkdir(parents=True)
            (user_machine / 'custom.json').write_text(json.dumps({'name': 'Custom printer'}), encoding='utf-8')
            registry = _Registry(exe)
            fake_winreg = types.SimpleNamespace(**{
                name: getattr(registry, name) for name in (
                    'HKEY_CURRENT_USER', 'HKEY_LOCAL_MACHINE', 'KEY_READ',
                    'KEY_WOW64_64KEY', 'KEY_WOW64_32KEY', 'OpenKey', 'EnumKey', 'QueryValueEx')})
            env = {'ProgramFiles': str(root / 'empty'), 'ProgramFiles(x86)': str(root / 'empty'),
                   'LOCALAPPDATA': str(root / 'empty'), 'APPDATA': str(root / 'user')}
            with patch.dict(os.environ, env), patch.dict(sys.modules, {'winreg': fake_winreg}):
                found, roots = discover()
            self.assertEqual(Path(found), exe)
            self.assertIn(str(machine.parent.parent), roots)
            self.assertIn(str(user_machine.parent.parent), roots)
            self.assertEqual(len(ProfileCatalog(roots).selectable('machine')), 2)

    def test_per_user_installation_without_registry_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / 'Programs' / 'Bambu Studio' / 'bambu-studio.exe'
            exe.parent.mkdir(parents=True)
            exe.touch()
            profiles = exe.parent / 'resources' / 'profiles'
            profiles.mkdir(parents=True)
            env = {'ProgramFiles': str(root / 'empty'), 'ProgramFiles(x86)': str(root / 'empty'),
                   'LOCALAPPDATA': str(root), 'APPDATA': str(root / 'no-user-profile')}
            with patch.dict(os.environ, env), patch('BambuPlateStudio.core.profiles._windows_registry_candidates', return_value=[]):
                found, roots = discover()
            self.assertEqual(Path(found), exe)
            self.assertEqual(roots, [str(profiles)])


class PortableProfileTests(unittest.TestCase):
    def test_machine_from_bambu_system_cache_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            exe = base / 'BambuStudio.app' / 'Contents' / 'MacOS' / 'BambuStudio'
            exe.parent.mkdir(parents=True)
            exe.touch()
            bundle = exe.parent.parent / 'resources' / 'profiles'
            old = bundle / 'BBL' / 'machine' / 'Older.json'
            old.parent.mkdir(parents=True)
            old.write_text(json.dumps({'name': 'Older printer'}), encoding='utf-8')
            data_root = (base / 'BambuStudio' if os.name == 'nt' else
                         base / 'Library' / 'Application Support' / 'BambuStudio')
            updated = data_root / 'system' / 'BBL' / 'machine' / 'P2S.json'
            updated.parent.mkdir(parents=True)
            updated.write_text(json.dumps({'name': 'Bambu Lab P2S 0.4 nozzle'}), encoding='utf-8')
            for kind, name in (('process', '0.20mm Standard @BBL P2S'),
                               ('filament', 'Generic PETG @BBL P2S')):
                file = data_root / 'system' / 'BBL' / kind / (name + '.json')
                file.parent.mkdir(parents=True)
                file.write_text(json.dumps({'name': name}), encoding='utf-8')
            home_context = (patch.dict(os.environ, {'APPDATA': str(base)}) if os.name == 'nt'
                            else patch.object(Path, 'home', return_value=base))
            with home_context:
                roots = profile_roots_for(exe)
            self.assertIn(str(updated.parent.parent.parent), roots)
            catalog = ProfileCatalog(roots)
            windows_saved = Session().rules()
            reopened = Session()
            reopened.apply_rules(windows_saved)
            self.assertEqual(reopened.rebind_profiles(catalog), [])
            self.assertEqual(catalog.find('machine', reopened.config['printer']).path, updated.resolve())
            self.assertEqual(reopened.config['printer'], str(updated.resolve()))

    def test_saved_windows_profile_path_resolves_on_mac(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'BambuStudio.app' / 'Contents' / 'resources' / 'profiles'
            machine = root / 'BBL' / 'machine' / 'P2S.json'
            machine.parent.mkdir(parents=True)
            machine.write_text(json.dumps({'name': 'Bambu Lab P2S 0.4 nozzle',
                                           'nozzle_diameter': ['0.4']}), encoding='utf-8')
            for kind, name in (('process', 'Standard'), ('filament', 'Generic PETG')):
                file = root / 'BBL' / kind / (name + '.json')
                file.parent.mkdir(parents=True)
                file.write_text(json.dumps({'name': name}), encoding='utf-8')
            catalog = ProfileCatalog([root])
            saved = Session()
            saved.config['printer'] = r'C:\Program Files\Bambu Studio\resources\profiles\BBL\machine\P2S.json'
            saved.config['process'] = r'C:\Program Files\Bambu Studio\resources\profiles\BBL\process\Standard.json'
            saved.config['filament'] = r'C:\Program Files\Bambu Studio\resources\profiles\BBL\filament\Generic PETG.json'
            saved.color_profiles['#FF0000'] = saved.config['filament']
            restored = Session()
            restored.apply_rules(saved.rules())
            self.assertEqual(catalog.find('machine', restored.config['printer']).path, machine.resolve())
            self.assertEqual(len(catalog.options(restored.config['printer'])['processes']), 1)
            restored.rebind_profiles(catalog)
            for field, kind in (('printer', 'machine'), ('process', 'process'), ('filament', 'filament')):
                self.assertEqual(restored.config[field], str(catalog.find(kind, restored.config[field]).path))
                self.assertNotEqual(restored.config[field], saved.config[field])
            self.assertEqual(restored.color_profiles['#FF0000'], restored.config['filament'])

    def test_old_paths_keep_bundled_and_user_profiles_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            bundled_root = base / 'BambuStudio.app' / 'Contents' / 'resources' / 'profiles'
            user_root = base / 'Library' / 'Application Support' / 'BambuStudio' / 'user'
            for root, marker in ((bundled_root, 'bundled'), (user_root, 'custom')):
                file = root / 'BBL' / 'machine' / 'P2S.json'
                file.parent.mkdir(parents=True)
                file.write_text(json.dumps({'name': 'Same name', 'marker': marker}), encoding='utf-8')
            catalog = ProfileCatalog([bundled_root, user_root])
            bundled = r'C:\Program Files\Bambu Studio\resources\profiles\BBL\machine\P2S.json'
            custom = r'C:\Users\somebody\AppData\Roaming\BambuStudio\user\BBL\machine\P2S.json'
            self.assertEqual(catalog.resolve('machine', bundled)['marker'], 'bundled')
            self.assertEqual(catalog.resolve('machine', custom)['marker'], 'custom')
            with self.assertRaisesRegex(ValueError, '名称有歧义'):
                catalog.find('machine', 'Same name')

    def test_downloaded_system_profile_replaces_same_bundled_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            bundle = base / 'BambuStudio.app' / 'Contents' / 'resources' / 'profiles'
            system = base / 'Library' / 'Application Support' / 'BambuStudio' / 'system'
            for root, revision in ((bundle, 'old'), (system, 'new')):
                file = root / 'BBL' / 'machine' / 'P2S.json'
                file.parent.mkdir(parents=True)
                file.write_text(json.dumps({'name': 'Bambu Lab P2S 0.4 nozzle',
                                            'revision': revision}), encoding='utf-8')
            catalog = ProfileCatalog([bundle, system])
            self.assertEqual(catalog.resolve('machine', Session().config['printer'])['revision'], 'new')
            self.assertEqual(len(catalog.selectable('machine')), 1)

    def test_saved_default_name_prefers_bambu_profile_over_custom_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            bundled = base / 'BambuStudio.app' / 'Contents' / 'resources' / 'profiles'
            user = base / 'Library' / 'Application Support' / 'BambuStudio' / 'user'
            for root, filename in ((bundled, 'P2S.json'), (user, 'Custom P2S.json')):
                file = root / 'BBL' / 'machine' / filename
                file.parent.mkdir(parents=True)
                file.write_text(json.dumps({'name': Session().config['printer']}), encoding='utf-8')
            catalog = ProfileCatalog([bundled, user])
            saved = Session().rules()
            restored = Session()
            restored.apply_rules(saved)
            restored.rebind_profiles(catalog)
            self.assertEqual(Path(restored.config['printer']),
                             (bundled / 'BBL' / 'machine' / 'P2S.json').resolve())


if __name__ == '__main__':
    unittest.main()
