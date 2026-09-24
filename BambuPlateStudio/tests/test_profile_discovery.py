"""Discovery should work when Bambu Studio is installed outside Program Files."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from BambuPlateStudio.core.profiles import ProfileCatalog, discover


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


if __name__ == '__main__':
    unittest.main()
