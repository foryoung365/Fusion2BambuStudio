import copy
import unittest
from BambuPlateStudio.core.model import Session,Plate,Placement
from BambuPlateStudio.core.geometry import face_down,transform_point
from BambuPlateStudio.core.visual_edit import EditHistory
from BambuPlateStudio.tests.test_core import cube


class LocalUngroupTests(unittest.TestCase):
    def setUp(self):
        self.s=Session([cube('a'),cube('b',low=(30,0,0)),cube('c'),cube('d')])
        self.g=self.s.group(['a','b'],'to release')
        self.g.rotation=face_down((0,0,1))
        self.g.face_token='face-of-one-member'
        self.s.plates=[Plate(1,allow_mixed=True),Plate(2)]
        self.s.placements={self.g.uid:Placement(self.g.uid,1,11,12,90),
                           'c':Placement('c',1,120,30,90),'d':Placement('d',2,60,70,0)}

    def test_released_members_keep_their_plate_and_exact_transform(self):
        plates=copy.deepcopy(self.s.plates)
        old_matrix=self.g.matrix(self.s.bodies,self.s.placements[self.g.uid])
        untouched={k:copy.deepcopy(v) for k,v in self.s.placements.items() if k!=self.g.uid}
        members=self.s.ungroup(self.g.uid)
        self.assertEqual(members,['a','b'])
        self.assertEqual({uid:self.s.placements[uid] for uid in untouched},untouched)
        self.assertEqual(self.s.plates,plates)
        for uid in members:
            self.assertEqual(self.s.units[uid].rotation,self.g.rotation)
            self.assertEqual(self.s.units[uid].face_token,'')
            self.assertEqual(self.s.placements[uid].plate,1)
            matrix=self.s.units[uid].matrix(self.s.bodies,self.s.placements[uid])
            for vertex in self.s.bodies[uid].vertices:
                for actual,expected in zip(transform_point(matrix,vertex),transform_point(old_matrix,vertex)):
                    self.assertAlmostEqual(actual,expected,places=10)
        self.assertEqual(set(self.s.units),set(self.s.placements))

    def test_unplaced_group_does_not_erase_other_plates(self):
        self.s.placements.pop(self.g.uid)
        before=copy.deepcopy(self.s.placements)
        self.s.ungroup(self.g.uid)
        self.assertEqual(self.s.placements,before)
        self.assertEqual(len(self.s.plates),2)

    def test_undo_redo_preserves_local_scope(self):
        history=EditHistory();before=history.snapshot(self.s)
        self.s.ungroup(self.g.uid);history.commit(before,self.s)
        after=copy.deepcopy(self.s.rules())
        history.restore(self.s);self.assertEqual(self.s.rules(),before)
        history.restore(self.s,False);self.assertEqual(self.s.rules(),after)

    def test_vertical_offsets_do_not_collapse_when_released(self):
        s=Session([cube('a',low=(0,0,80)),cube('b',low=(30,0,0))])
        group=s.group(['a','b'],'stacked');s.plates=[Plate(1)]
        s.placements[group.uid]=Placement(group.uid,1,10,10,90,7)
        old=group.matrix(s.bodies,s.placements[group.uid])
        s.ungroup(group.uid)
        self.assertAlmostEqual(s.placements['a'].z,87)
        self.assertAlmostEqual(s.placements['b'].z,7)
        for uid in ['a','b']:
            matrix=s.units[uid].matrix(s.bodies,s.placements[uid])
            for vertex in s.bodies[uid].vertices:
                for actual,expected in zip(transform_point(matrix,vertex),transform_point(old,vertex)):
                    self.assertAlmostEqual(actual,expected,places=10)

    def test_old_saved_placements_default_to_zero_height(self):
        rules=copy.deepcopy(self.s.rules())
        for p in rules['placements']:p.pop('z')
        restored=Session(list(self.s.bodies.values()));restored.apply_rules(rules)
        self.assertTrue(all(p.z==0 for p in restored.placements.values()))
