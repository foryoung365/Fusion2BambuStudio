import ast
import copy
import json
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from BambuPlateStudio.core.inputs import color_hex
from BambuPlateStudio.core.layout import Bed, arrange, footprint, validate
from BambuPlateStudio.core.model import Plate, Session
from BambuPlateStudio.core.visual_edit import EditHistory, transfer_to_plate
from BambuPlateStudio.tests.test_core import cube


class DominantColorTests(unittest.TestCase):
    def mixed_body(self):
        body = cube('mixed', color='#000000')
        body.face_colors = {'#000000': 1., '#FF0000': 9.}
        return body

    def test_auto_color_arrangement_uses_dominant_face_color_and_warns(self):
        body = self.mixed_body()
        session = Session([body, cube('red', color='#FF0000')])
        before = copy.deepcopy(body)

        warnings = arrange(session, Bed(256, 256, 256))

        self.assertEqual(len(session.plates), 1)
        self.assertEqual(set(session.placements), set(session.units))
        self.assertEqual(session.effective_color('mixed'), '#FF0000')
        self.assertEqual(validate(session, Bed(256, 256, 256))[0], [])
        self.assertTrue(any(body.name in warning and '#FF0000' in warning
                            for warning in warnings))
        self.assertEqual(body, before)
        self.assertEqual(session.color_overrides, {})

    def test_largest_total_face_area_wins_and_other_colors_still_split(self):
        session = Session([self.mixed_body(), cube('red', color='#FF0000'),
                           cube('black', color='#000000')])
        arrange(session, Bed(256, 256, 256))
        self.assertEqual(len(session.plates), 2)
        self.assertEqual(session.placements['mixed'].plate, session.placements['red'].plate)
        self.assertNotEqual(session.placements['mixed'].plate, session.placements['black'].plate)

    def test_manual_color_wins_and_resolves_only_that_body_warning(self):
        body = self.mixed_body()
        session = Session([body, cube('green', color='#00FF00')])
        session.color_overrides['mixed'] = '#00ff00'
        warnings = arrange(session, Bed(256, 256, 256))
        self.assertEqual(len(session.plates), 1)
        self.assertEqual(session.effective_color('mixed'), '#00FF00')
        self.assertFalse(any(body.name in warning for warning in warnings))

    def test_equal_areas_are_stable_and_meshes_fall_back_to_body_color(self):
        body = self.mixed_body()
        body.face_colors = {'#ff0000': 2., '#000000': 2.}
        session = Session([body])
        self.assertEqual(session.effective_color('mixed'), '#000000')
        body.color = '#FFFFFF'
        first = session.effective_color('mixed')
        self.assertEqual(first, '#000000')
        body.face_colors = dict(reversed(list(body.face_colors.items())))
        self.assertEqual(session.effective_color('mixed'), first)
        body.face_colors = {}
        self.assertEqual(session.effective_color('mixed'), '#FFFFFF')

    def test_warning_survives_rule_roundtrip_and_manual_plate_transfer(self):
        original = Session([self.mixed_body()])
        bed = Bed(256, 256, 256)
        arrange(original, bed)
        restored = Session([self.mixed_body()])
        restored.apply_rules(json.loads(json.dumps(original.rules())))
        restored.plates.append(Plate(2))
        transfer_to_plate(restored, 'mixed', 2, bed)
        errors, warnings = validate(restored, bed)
        self.assertEqual(errors, [])
        self.assertTrue(any('第 2 盘' in w and restored.bodies['mixed'].name in w
                            for w in warnings))
        self.assertEqual(restored.color_overrides, {})

    def test_changed_dominant_face_color_resets_affected_mixed_plate_approval(self):
        original = Session([self.mixed_body()])
        arrange(original, Bed(256, 256, 256))
        original.plates[0].allow_mixed = True
        changed = self.mixed_body()
        changed.face_colors = {'#000000': 9., '#FF0000': 1.}
        restored = Session([changed])
        restored.apply_rules(original.rules())
        self.assertEqual(restored.placements, original.placements)
        self.assertEqual(restored.effective_color('mixed'), '#000000')
        self.assertFalse(restored.plates[0].allow_mixed)


class ColorEditingControllerTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1]/'fusion_adapter/bridge.py'
        definition = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                          if isinstance(n, ast.ClassDef) and n.name == 'Controller')
        namespace = {'color_hex': color_hex, 'asdict': asdict,
                     'footprint': footprint, 'validate': validate}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), 'exec'), namespace)
        c = self.controller = namespace['Controller'].__new__(namespace['Controller'])
        body = cube('mixed')
        body.face_colors['#FF0000'] = 9.
        c.session = Session([body])
        c.bed = Bed(256, 256, 256)
        arrange(c.session, c.bed)
        c.history = EditHistory()
        c.geometry_revision = 1
        c.orientation_preview = c.orientation_snapshot = None
        c.arrangement_preview = c.arrangement_snapshot = None
        c.preview_job = None
        c.notices = []
        c.last_export = None
        c.exe = ''
        doc = SimpleNamespace(name='多面颜色测试')
        c.app = SimpleNamespace(activeDocument=doc)
        c.source = SimpleNamespace(document=doc)
        c.update_bed = lambda: None
        c.profile_state = lambda: {}

    def test_override_preserves_positions_and_can_be_undone(self):
        c = self.controller
        before = copy.deepcopy(c.session.rules())
        updated = c.dispatch('body_color', {'body': 'mixed', 'color': '#00FF00'})
        self.assertEqual(c.session.placements['mixed'].plate, 1)
        self.assertEqual([asdict(p) for p in c.session.placements.values()], before['placements'])
        self.assertTrue(updated['units'][0]['members'][0]['colorOverridden'])
        self.assertFalse(any('多种面颜色' in w for w in updated['warnings']))
        c.dispatch('undo', {})
        self.assertEqual(c.session.rules(), before)
        self.assertTrue(any('多种面颜色' in w for w in c.state()['warnings']))

    def test_state_exposes_primary_color_and_unconfirmed_source(self):
        state = self.controller.state()
        member = state['units'][0]['members'][0]
        self.assertEqual(member['color'], '#FF0000')
        self.assertTrue(member['mixedFaces'])
        self.assertFalse(member['colorOverridden'])
        self.assertTrue(any(member['name'] in w for w in state['warnings']))


if __name__ == '__main__':
    unittest.main()
