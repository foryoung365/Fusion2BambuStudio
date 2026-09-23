import json
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


class UiEntrypointTests(unittest.TestCase):
    def test_five_actions_have_unambiguous_labels(self):
        html=(ROOT/'ui'/'index.html').read_text(encoding='utf-8')
        for uid,label in [('autoPlaceAll','所有盘自动摆放'),('autoOrientAll','所有盘自动朝向'),
                          ('autoPlaceCurrent','整盘自动摆放'),('autoOrientCurrent','整盘自动朝向'),
                          ('autoOrient','自动朝向')]:
            self.assertIn(f'id="{uid}">{label}</button>',html)
        self.assertNotIn('id="arrangementScope"',html)
        self.assertNotIn('id="orientationScope"',html)

    def test_display_name_and_small_version_match_manifest(self):
        manifest=json.loads((ROOT/'BambuPlateStudio.manifest').read_text(encoding='utf-8'))
        html=(ROOT/'ui'/'index.html').read_text(encoding='utf-8')
        entry=(ROOT/'BambuPlateStudio.py').read_text(encoding='utf-8')
        self.assertIn(f'<small class="brand-version">v{manifest["version"]}</small>',html)
        self.assertIn('<title>MF3D打印摆盘助手</title>',html)
        self.assertIn("ui.palettes.add(PALETTE, 'MF3D打印摆盘助手'",entry)
