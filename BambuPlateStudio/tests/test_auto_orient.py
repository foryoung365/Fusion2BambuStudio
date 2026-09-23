import ast,copy,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from BambuPlateStudio.core.auto_orient import extract_rotation,suggest,suggest_many,apply_rotation
from BambuPlateStudio.core.model import Session,new_id
from BambuPlateStudio.core.geometry import face_down,rotate,IDENTITY
from BambuPlateStudio.core.layout import arrange,Bed
from BambuPlateStudio.core.visual_edit import EditHistory
from BambuPlateStudio.tests.test_core import cube


class RotationValidationTests(unittest.TestCase):
    def setUp(self):
        self.s=Session([cube('a'),cube('b',low=(30,5,40),color='#FF0000')])
        self.u=self.s.group(['a','b'],'group');self.rotation=face_down((1,0,0))
        self.parts={}
        for uid,b in self.s.bodies.items():
            self.parts[uid+'.mesh']={'vertices':[tuple(v+10 for v in rotate(self.rotation,p)) for p in b.vertices],
                'triangles':b.triangles,'name':b.name,'unitName':'group','color':b.color,
                'matrix':[list(row)+[0] for row in self.rotation]+[[0,0,0,1]]}

    def extract(self):
        with patch('BambuPlateStudio.core.auto_orient.read',return_value=(self.parts,[['a.mesh','b.mesh']],1,{})):
            return extract_rotation(self.s,'unused')

    def test_whole_group_rotation_verified(self):
        rotation,error=self.extract();self.assertLess(error,.001)
        self.assertEqual(rotation,self.rotation)

    def test_independent_part_translation_rejected(self):
        self.parts['b.mesh']['vertices']=[(p[0]+1,p[1],p[2]) for p in self.parts['b.mesh']['vertices']]
        with self.assertRaisesRegex(ValueError,'相对位置'):self.extract()

    def test_scale_rejected(self):
        self.parts['a.mesh']['matrix'][0][0]*=2
        self.parts['a.mesh']['matrix'][0][2]*=2
        with self.assertRaises(ValueError):self.extract()

    def test_color_change_rejected(self):
        self.parts['b.mesh']['color']='#FFFFFF'
        with self.assertRaisesRegex(ValueError,'颜色'):self.extract()

    def test_split_group_rejected(self):
        with patch('BambuPlateStudio.core.auto_orient.read',return_value=(self.parts,[['a.mesh'],['b.mesh']],1,{})):
            with self.assertRaisesRegex(ValueError,'整体'):extract_rotation(self.s,'unused')

    def test_locked_unit_never_invokes_engine(self):
        self.u.orientation_locked=True
        with patch('BambuPlateStudio.core.auto_orient.run_project') as engine:
            with self.assertRaisesRegex(ValueError,'锁定'):suggest(self.s,self.u.uid,None,'unused')
            engine.assert_not_called()

    def test_legacy_manual_directions_migrate_locked(self):
        self.u.orientation_label='top 面朝下';self.u.rotation=face_down((0,0,1))
        rules=self.s.rules();rules['units'][0].pop('orientation_locked')
        restored=Session(list(self.s.bodies.values()));restored.apply_rules(rules)
        self.assertTrue(restored.units[self.u.uid].orientation_locked)

    def test_group_preserves_member_orientation_lock(self):
        session=Session([cube('x'),cube('y')])
        session.units['x'].orientation_locked=True
        group=session.group(['x','y'],'joined')
        self.assertTrue(group.orientation_locked)


class ProposalControllerTests(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).resolve().parents[1]/'fusion_adapter/bridge.py'
        definition=next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef) and n.name=='Controller')
        self.proposal={'unit':'a','rotation':face_down((1,0,0))}
        self.engine=Mock(return_value=copy.deepcopy(self.proposal))
        self.batch={'batch':True,'plates':[1,2],'units':{'a':self.proposal},'placements':{},
                    'skipped':[{'unit':'b','reason':'朝向已锁定'}],'errors':[]}
        self.batch_engine=Mock(return_value=copy.deepcopy(self.batch))
        namespace={'suggest':self.engine,'suggest_many':self.batch_engine,
                   'apply_rotation':apply_rotation,'new_id':new_id,'IDENTITY':IDENTITY,'face_down':face_down}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(source),'exec'),namespace)
        self.c=namespace['Controller'].__new__(namespace['Controller'])
        c=self.c;c.session=Session([cube('a',size=(10,20,30)),cube('b',color='#FF0000')]);c.bed=Bed(256,256,256)
        arrange(c.session,c.bed);c.session.units['b'].orientation_locked=True
        c.history=EditHistory();c.orientation_preview=None;c.orientation_snapshot=None;c.last_export=None;c.notices=[]
        doc=object();c.app=SimpleNamespace(activeDocument=doc);c.source=SimpleNamespace(document=doc)
        c.catalog=None;c.exe='unused';c.update_bed=lambda:None;c.assert_source_current=Mock()
        c.state=lambda include_profiles=False:{'orientationPreview':c.orientation_preview,'notices':c.notices}

    def preview(self):
        self.c.dispatch('orientation_preview',{'unit':'a'})
        return self.c.orientation_preview['token']

    def test_preview_and_cancel_leave_rules_and_history_untouched(self):
        before=copy.deepcopy(self.c.session.rules());token=self.preview()
        self.assertEqual(self.c.session.rules(),before)
        self.c.dispatch('orientation_cancel',{'token':token})
        self.assertEqual(self.c.session.rules(),before);self.assertFalse(self.c.history.undo_stack)
        self.assertIsNone(self.c.orientation_preview)

    def test_confirm_only_changes_selected_unit_and_can_undo(self):
        c=self.c;before=copy.deepcopy(c.session.rules());peer=copy.deepcopy(c.session.placements['b'])
        token=self.preview();c.dispatch('orientation_apply',{'token':token})
        self.assertEqual(c.session.units['a'].rotation,self.proposal['rotation'])
        self.assertEqual(c.session.placements['b'],peer);self.assertTrue(c.session.units['b'].orientation_locked)
        self.assertEqual(len(c.history.undo_stack),1);self.assertIsNone(c.orientation_preview)
        c.dispatch('undo',{});self.assertEqual(c.session.rules(),before)

    def test_wrong_or_stale_token_rejected(self):
        token=self.preview();before=copy.deepcopy(self.c.session.rules())
        with self.assertRaisesRegex(ValueError,'过期'):self.c.dispatch('orientation_apply',{'token':'wrong'})
        self.assertEqual(self.c.session.rules(),before)
        self.c.dispatch('orientation_lock',{'unit':'a','locked':True})
        with self.assertRaisesRegex(ValueError,'过期'):self.c.dispatch('orientation_apply',{'token':token})

    def test_cad_change_after_preview_blocks_apply(self):
        token=self.preview();before=copy.deepcopy(self.c.session.rules())
        self.c.assert_source_current.side_effect=ValueError('源模型已改变')
        with self.assertRaisesRegex(ValueError,'源模型'):self.c.dispatch('orientation_apply',{'token':token})
        self.assertEqual(self.c.session.rules(),before)

    def test_manual_orientation_locks_unit(self):
        self.c.dispatch('direction',{'unit':'a','mode':'top'})
        self.assertTrue(self.c.session.units['a'].orientation_locked)

    def test_all_plate_orientation_is_one_undo_and_keeps_locked_peer(self):
        c=self.c;before=copy.deepcopy(c.session.rules());peer=copy.deepcopy(c.session.units['b'])
        c.dispatch('orientation_preview',{'scope':'all'})
        token=c.orientation_preview['token']
        self.assertEqual(c.session.rules(),before)
        self.assertEqual(self.batch_engine.call_args.args[1:3],(['a','b'],[1,2]))
        c.dispatch('orientation_apply',{'token':token})
        self.assertEqual(c.session.units['a'].rotation,self.proposal['rotation'])
        self.assertEqual(c.session.units['b'],peer)
        self.assertEqual(len(c.history.undo_stack),1)
        c.dispatch('undo',{});self.assertEqual(c.session.rules(),before)

    def test_current_plate_orientation_only_queries_that_plate(self):
        self.c.dispatch('orientation_preview',{'scope':'current','plate':2})
        expected=[uid for uid in self.c.session.units if self.c.session.placements[uid].plate==2]
        self.assertEqual(self.batch_engine.call_args.args[1:3],(expected,[2]))

    def test_empty_batch_cannot_be_applied(self):
        self.batch_engine.return_value={**self.batch,'units':{}}
        c=self.c;before=copy.deepcopy(c.session.rules())
        c.dispatch('orientation_preview',{'scope':'all'})
        with self.assertRaisesRegex(ValueError,'没有需要改变'):
            c.dispatch('orientation_apply',{'token':c.orientation_preview['token']})
        self.assertEqual(c.session.rules(),before)


class BatchSuggestionTests(unittest.TestCase):
    def test_locked_and_unchanged_units_skipped_without_mutation(self):
        session=Session([cube('a'),cube('b',low=(35,0,0)),cube('c',low=(70,0,0))])
        session.units['b'].orientation_locked=True
        arrange(session,Bed(256,256,256));before=copy.deepcopy(session.rules())
        changed={'rotation':face_down((0,0,1)),'beforeRotation':IDENTITY,
                 'elapsedSeconds':0.1,'maxVertexErrorMm':0.}
        unchanged={'rotation':IDENTITY,'beforeRotation':IDENTITY,
                   'elapsedSeconds':0.1,'maxVertexErrorMm':0.}
        catalog=SimpleNamespace(resolve=lambda kind,key:{'printable_area':['0x0','256x0','256x256','0x256'],
                                                         'printable_height':'256'})
        with patch('BambuPlateStudio.core.auto_orient.suggest',side_effect=lambda s,uid,c,e:changed if uid=='a' else unchanged) as engine:
            result=suggest_many(session,['a','b','c'],[1],catalog,'unused')
        self.assertEqual(list(result['units']),['a'])
        self.assertEqual(len(result['skipped']),2)
        self.assertEqual(engine.call_count,2)
        self.assertEqual(session.rules(),before)
