import copy
import unittest
from BambuPlateStudio.core.layout import Bed,arrange,footprint,validate
from BambuPlateStudio.core.model import Session
from BambuPlateStudio.tests.test_core import cube


class CenterArrangeTests(unittest.TestCase):
    def center(self,s,bed,plate):
        rects=[footprint(s,p) for p in s.placements.values() if p.plate==plate]
        return ((min(r[0] for r in rects)+max(r[0]+r[2] for r in rects))/2,
                (min(r[1] for r in rects)+max(r[1]+r[3] for r in rects))/2)

    def test_single_unit_starts_at_bed_center(self):
        s=Session([cube(size=(30,10,20))]);bed=Bed(256,256,256)
        arrange(s,bed)
        self.assertEqual(self.center(s,bed,1),(128,128))
        self.assertEqual(s.placements['a'].angle,0)

    def test_centered_cluster_expands_without_unnecessary_extra_plate(self):
        s=Session([cube('a',size=(100,180,10)),cube('b',size=(100,180,10))]);bed=Bed(230,230,230)
        before={uid:b.fingerprint() for uid,b in s.bodies.items()}
        arrange(s,bed)
        self.assertEqual(len(s.plates),1)
        self.assertEqual(self.center(s,bed,1),(115,115))
        self.assertFalse(validate(s,bed)[0])
        self.assertEqual({uid:b.fingerprint() for uid,b in s.bodies.items()},before)

    def test_multiple_colors_each_cluster_centered(self):
        s=Session([cube('a'),cube('b'),cube('c',color='#FF0000'),cube('d',color='#FFFFFF')])
        bed=Bed(256,256,256);s.config['allowMixedPlates']=True
        arrange(s,bed)
        self.assertEqual(len(s.plates),3)
        for p in s.plates:self.assertEqual(self.center(s,bed,p.index),(128,128))
        self.assertFalse(validate(s,bed)[0])

    def test_nonzero_bed_origin(self):
        s=Session([cube()]);bed=Bed(100,120,100,100,200)
        arrange(s,bed)
        self.assertEqual(self.center(s,bed,1),(150,260))

    def test_blocked_center_uses_nearest_safe_region(self):
        s=Session([cube()]);bed=Bed(100,100,100,exclusions=((45,45,10,10),))
        arrange(s,bed)
        self.assertFalse(validate(s,bed)[0])
        cx,cy=self.center(s,bed,1)
        self.assertAlmostEqual((cx-50)**2+(cy-50)**2,225)

    def test_validation_failure_does_not_replace_existing_layout(self):
        s=Session([cube()]);bed=Bed(100,100,100);arrange(s,bed)
        before=copy.deepcopy(s.placements)
        s.bodies['untracked']=cube('untracked')
        with self.assertRaisesRegex(ValueError,'完整且唯一'):arrange(s,bed)
        self.assertEqual(s.placements,before)
