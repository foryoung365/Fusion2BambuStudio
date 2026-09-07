import copy
import unittest
from BambuPlateStudio.core.model import Session,Plate,Placement
from BambuPlateStudio.core.layout import arrange,Bed,validate
from BambuPlateStudio.core.visual_edit import transfer_to_plate,MixedPlateConfirmation,EditHistory
from BambuPlateStudio.tests.test_core import cube


class MixedTransferTests(unittest.TestCase):
    def setUp(self):
        self.s=Session([cube('a'),cube('b',color='#FF0000'),cube('c',color='#FFFFFF')])
        self.bed=Bed(256,256,256);arrange(self.s,self.bed)
        self.target=self.s.placements['b'].plate

    def test_initial_attempt_is_read_only_and_requires_confirmation(self):
        before=copy.deepcopy(self.s.rules())
        with self.assertRaises(MixedPlateConfirmation) as ctx:
            transfer_to_plate(self.s,'a',self.target,self.bed)
        self.assertEqual(ctx.exception.confirmation['code'],'mixed_plate_confirmation')
        self.assertEqual(self.s.rules(),before)

    def test_confirmation_only_moves_requested_unit_and_approves_target(self):
        before=copy.deepcopy(self.s.placements)
        transfer_to_plate(self.s,'a',self.target,self.bed,True)
        self.assertEqual(self.s.placements['a'].plate,self.target)
        self.assertEqual(self.s.placements['b'],before['b'])
        self.assertEqual(self.s.placements['c'],before['c'])
        self.assertEqual([p.index for p in self.s.plates if p.allow_mixed],[self.target])
        self.assertFalse(self.s.config['allowMixedPlates'])
        self.assertFalse(validate(self.s,self.bed)[0])
        with self.assertRaises(MixedPlateConfirmation):
            transfer_to_plate(self.s,'c',self.target,self.bed)

    def test_confirmed_no_space_is_still_atomic(self):
        s=Session([cube('a',size=(40,40,10)),cube('b',color='#FF0000',size=(40,40,10))])
        s.plates=[Plate(1),Plate(2)];s.placements={'a':Placement('a',1,5,5),'b':Placement('b',2,5,5)}
        before=copy.deepcopy(s.rules())
        with self.assertRaisesRegex(ValueError,'空间不足'):transfer_to_plate(s,'a',2,Bed(50,50,50),True)
        self.assertEqual(s.rules(),before)

    def test_consent_persists_and_undo_redo_restores_it(self):
        h=EditHistory();before=h.snapshot(self.s)
        transfer_to_plate(self.s,'a',self.target,self.bed,True);h.commit(before,self.s)
        restored=Session(list(self.s.bodies.values()));restored.apply_rules(self.s.rules())
        self.assertFalse(validate(restored,self.bed)[0])
        h.restore(self.s);self.assertEqual(self.s.rules(),before)
        h.restore(self.s,False);self.assertFalse(validate(self.s,self.bed)[0])
        self.assertTrue(next(p for p in self.s.plates if p.index==self.target).allow_mixed)

    def test_auto_arrange_still_separates_colors_and_resets_manual_approval(self):
        transfer_to_plate(self.s,'a',self.target,self.bed,True)
        arrange(self.s,self.bed)
        self.assertEqual(len({p.plate for p in self.s.placements.values()}),3)
        self.assertFalse(any(p.allow_mixed for p in self.s.plates))
