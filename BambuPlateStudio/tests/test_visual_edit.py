import copy
import unittest
from BambuPlateStudio.core.model import Session,Plate,Placement
from BambuPlateStudio.core.geometry import face_down
from BambuPlateStudio.core.layout import Bed,arrange
from BambuPlateStudio.core.visual_edit import EditHistory,merge_onto,transfer_to_plate
from BambuPlateStudio.tests.test_core import cube


class VisualEditTests(unittest.TestCase):
    def test_drag_group_adopts_target_direction_preserves_original_vertices(self):
        s=Session([cube('a',low=(0,0,80)),cube('b',low=(30,0,-4),size=(20,20,104))])
        s.units['b'].rotation=face_down((0,0,1));s.units['b'].face_token='target-face'
        before={k:b.fingerprint() for k,b in s.bodies.items()}
        group=merge_onto(s,'a','b')
        self.assertEqual(group.members,['b','a'])
        self.assertEqual(group.rotation,face_down((0,0,1)))
        self.assertEqual(group.face_token,'target-face')
        self.assertEqual(before,{k:b.fingerprint() for k,b in s.bodies.items()})

    def test_group_does_not_erase_unrelated_plates_or_positions(self):
        s=Session([cube('a'),cube('b'),cube('c')]);s.plates=[Plate(1),Plate(2)]
        s.placements={k:Placement(k,1 if k!='c' else 2,i*30,0) for i,k in enumerate(['a','b','c'])}
        untouched=copy.deepcopy(s.placements['c'])
        merge_onto(s,'a','b')
        self.assertEqual(s.placements['c'],untouched);self.assertEqual(len(s.plates),2)
        self.assertNotIn('a',s.placements)

    def test_tree_transfer_moves_whole_group(self):
        s=Session([cube('a'),cube('b',low=(30,0,0))]);g=merge_onto(s,'a','b')
        arrange(s,Bed(256,256,256));s.plates.append(Plate(2))
        rotation=g.rotation
        result=transfer_to_plate(s,g.uid,2,Bed(256,256,256))
        self.assertEqual(result.plate,2);self.assertEqual(g.members,['b','a']);self.assertEqual(g.rotation,rotation)

    def test_no_room_does_not_change_existing_placement(self):
        s=Session([cube('a',size=(40,40,20)),cube('b',size=(40,40,20))])
        s.plates=[Plate(1),Plate(2)];s.placements={'a':Placement('a',1,5,5),'b':Placement('b',2,5,5)}
        old=copy.deepcopy(s.placements)
        with self.assertRaises(ValueError):transfer_to_plate(s,'a',2,Bed(50,50,50))
        self.assertEqual(s.placements,old)

    def test_different_color_transfer_requires_explicit_mixed_mode(self):
        s=Session([cube('a'),cube('b',color='#FF0000')]);arrange(s,Bed(256,256,256))
        target=s.placements['b'].plate;old=copy.deepcopy(s.placements['a'])
        with self.assertRaises(ValueError):transfer_to_plate(s,'a',target,Bed(256,256,256))
        self.assertEqual(s.placements['a'],old)

    def test_undo_redo_restores_group_and_all_plate_state(self):
        s=Session([cube('a'),cube('b')]);arrange(s,Bed(256,256,256))
        history=EditHistory();before=history.snapshot(s)
        merge_onto(s,'a','b');history.commit(before,s)
        self.assertEqual(len(s.units),1)
        history.restore(s);self.assertEqual(s.rules(),before)
        history.restore(s,False);self.assertEqual(len(s.units),1)
