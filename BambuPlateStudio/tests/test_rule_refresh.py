import json
import unittest

from BambuPlateStudio.core.layout import Bed, validate
from BambuPlateStudio.core.model import Session, Plate, Placement
from BambuPlateStudio.core.visual_edit import merge_onto
from BambuPlateStudio.tests.test_core import cube


class RuleRefreshTests(unittest.TestCase):
    def test_dimension_edit_preserves_saved_positions(self):
        original = Session([cube(), cube('b')])
        original.plates = [Plate(1, '原有打印盘')]
        original.placements = {'a': Placement('a', 1, 20, 20, 90),
                               'b': Placement('b', 1, 80, 20)}
        saved = json.loads(json.dumps(original.rules()))
        refreshed = Session([cube(size=(21, 20, 20)), cube('b')])
        notices = refreshed.apply_rules(saved)
        self.assertTrue(notices)
        self.assertEqual(refreshed.placements, original.placements)
        self.assertEqual(refreshed.plates, original.plates)
        self.assertEqual(validate(refreshed, Bed(256, 256, 256))[0], [])

    def test_enlarged_model_keeps_position_but_collision_blocks_export(self):
        original = Session([cube(), cube('b')])
        original.plates = [Plate(1)]
        original.placements = {'a': Placement('a', 1, 20, 20),
                               'b': Placement('b', 1, 80, 20)}
        refreshed = Session([cube(size=(90, 20, 20)), cube('b')])
        refreshed.apply_rules(original.rules())
        self.assertEqual(refreshed.placements, original.placements)
        errors, _ = validate(refreshed, Bed(256, 256, 256))
        self.assertTrue(any('实体轮廓间距' in error for error in errors))

    def test_added_body_is_unplaced_without_removing_existing_layout(self):
        original = Session([cube()])
        original.plates = [Plate(1, '已有盘'), Plate(2, '保留空盘')]
        original.placements = {'a': Placement('a', 1, 30, 40)}
        refreshed = Session([cube(), cube('new')])
        refreshed.apply_rules(original.rules())
        self.assertEqual(refreshed.placements, original.placements)
        self.assertEqual(refreshed.plates, original.plates)
        errors, _ = validate(refreshed, Bed(256, 256, 256))
        self.assertIn('尚有打印单元未排入盘中。', errors)

    def test_enlarged_model_keeps_position_but_new_bounds_are_checked(self):
        original = Session([cube()])
        original.plates = [Plate(1)]
        original.placements = {'a': Placement('a', 1, 200, 20)}
        refreshed = Session([cube(size=(80, 20, 20))])
        refreshed.apply_rules(original.rules())
        self.assertEqual(refreshed.placements, original.placements)
        errors, _ = validate(refreshed, Bed(256, 256, 256))
        self.assertTrue(any('超出打印板实际范围' in error for error in errors))

    def test_changed_entity_id_restores_saved_group_position_via_alias(self):
        original = Session([cube(), cube('b', low=(30, 0, 0))])
        group = original.group(['a', 'b'], '原整体')
        original.plates = [Plate(1)]
        original.placements = {group.uid: Placement(group.uid, 1, 40, 50, 90, 2)}
        refreshed = Session([cube('new-a', size=(21, 20, 20)),
                             cube('b', low=(30, 0, 0))])
        refreshed.apply_rules(original.rules(), {'a': 'new-a'})
        self.assertEqual(refreshed.placements, original.placements)
        self.assertEqual(refreshed.units[group.uid].members, ['new-a', 'b'])
        self.assertEqual(validate(refreshed, Bed(256, 256, 256))[0], [])

    def test_missing_group_member_does_not_transfer_group_placement_to_survivor(self):
        original = Session([cube(), cube('b', low=(30, 0, 0)), cube('c')])
        merge_onto(original, 'b', 'a')  # This group's ID equals a surviving body's ID.
        original.plates = [Plate(1), Plate(2)]
        original.placements = {'a': Placement('a', 1, 20, 20),
                               'c': Placement('c', 2, 40, 50)}
        refreshed = Session([cube(), cube('c')])
        refreshed.apply_rules(original.rules())
        self.assertEqual(refreshed.placements, {'c': original.placements['c']})
        self.assertTrue(refreshed.rule_errors)
        self.assertEqual(refreshed.plates, original.plates)

    def test_changed_color_requires_new_mixed_plate_approval(self):
        original = Session([cube(), cube('b'), cube('c', '#FF0000')])
        original.plates = [Plate(1, allow_mixed=True), Plate(2, allow_mixed=True)]
        original.placements = {'a': Placement('a', 1, 20, 20),
                               'b': Placement('b', 1, 80, 20),
                               'c': Placement('c', 2, 20, 20)}
        refreshed = Session([cube(color='#00FF00'), cube('b'), cube('c', '#FF0000')])
        refreshed.apply_rules(original.rules())
        self.assertEqual(refreshed.placements, original.placements)
        self.assertFalse(refreshed.plates[0].allow_mixed)
        self.assertTrue(refreshed.plates[1].allow_mixed)
        errors, _ = validate(refreshed, Bed(256, 256, 256))
        self.assertTrue(any('第 1 盘包含不同颜色' in error for error in errors))

    def test_color_override_keeps_existing_mixed_plate_approval(self):
        original = Session([cube(), cube('b')])
        original.color_overrides['a'] = '#FF0000'
        original.plates = [Plate(1, allow_mixed=True)]
        original.placements = {'a': Placement('a', 1, 20, 20),
                               'b': Placement('b', 1, 80, 20)}
        refreshed = Session([cube(color='#00FF00'), cube('b')])
        refreshed.apply_rules(original.rules())
        self.assertEqual(refreshed.placements, original.placements)
        self.assertTrue(refreshed.plates[0].allow_mixed)
        self.assertEqual(validate(refreshed, Bed(256, 256, 256))[0], [])


if __name__ == '__main__':
    unittest.main()
