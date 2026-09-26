import copy
import unittest
from BambuPlateStudio.core.model import Session
from BambuPlateStudio.core.layout import arrange,Bed,validate
from BambuPlateStudio.tests.test_core import cube


def reordered(body):
    b=copy.deepcopy(body)
    order=list(reversed(range(len(b.vertices))))
    mapping={old:new for new,old in enumerate(order)}
    b.vertices=[b.vertices[i] for i in order]
    b.triangles=[tuple(mapping[i] for i in (tri[1],tri[2],tri[0])) for tri in reversed(b.triangles)]
    return b


class GeometryIdentityTests(unittest.TestCase):
    def test_order_independent_but_raw_hash_kept(self):
        a=cube();b=reordered(a)
        self.assertNotEqual(a.fingerprint(),b.fingerprint())
        self.assertEqual(a.geometry_key(),b.geometry_key())

    def test_reordered_mesh_restores_saved_plates(self):
        original=Session([cube()]);arrange(original,Bed(256,256,256))
        saved=original.rules();restored=Session([reordered(original.bodies['a'])])
        self.assertEqual(restored.apply_rules(saved),[])
        self.assertEqual(restored.placements,original.placements)
        self.assertEqual(restored.plates,original.plates)

    def test_real_changes_including_submicron_remain_detected(self):
        original=cube();key=original.geometry_key()
        moved=copy.deepcopy(original)
        moved.vertices[0]=(-0.00000001,0,0)
        self.assertNotEqual(moved.geometry_key(),key)
        reversed_face=copy.deepcopy(original)
        a,b,c=reversed_face.triangles[0];reversed_face.triangles[0]=(a,c,b)
        self.assertNotEqual(reversed_face.geometry_key(),key)
        duplicate=copy.deepcopy(original);duplicate.triangles.append(duplicate.triangles[0])
        self.assertNotEqual(duplicate.geometry_key(),key)
        isolated=copy.deepcopy(original);isolated.vertices.append((100,100,100))
        self.assertNotEqual(isolated.geometry_key(),key)

    def test_legacy_rules_keep_positions_with_change_notice(self):
        original=Session([cube()]);arrange(original,Bed(256,256,256))
        saved=original.rules()
        for source in saved['sources']:source.pop('geometryKey')
        equal=Session([cube()]);self.assertEqual(equal.apply_rules(saved),[])
        changed_order=Session([reordered(original.bodies['a'])])
        self.assertTrue(changed_order.apply_rules(saved))
        self.assertEqual(changed_order.placements,original.placements)
        self.assertEqual(validate(changed_order,Bed(256,256,256))[0],[])
