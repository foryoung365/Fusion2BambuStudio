import ast,copy,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from BambuPlateStudio.core.auto_place import plate_query,extract_positions,apply_positions,PlateOverflow
from BambuPlateStudio.core.model import Session,new_id
from BambuPlateStudio.core.layout import arrange,Bed
from BambuPlateStudio.core.visual_edit import EditHistory
from BambuPlateStudio.tests.test_core import cube


class PlacementExtractionTests(unittest.TestCase):
    def setUp(self):
        self.session=Session([cube('a'),cube('b',low=(30,10,0))])
        self.group=self.session.group(['a','b'],'whole')
        arrange(self.session,Bed(256,256,256))
        self.query=plate_query(self.session,1)
        self.original={};self.arranged={}
        for uid,body in self.query.bodies.items():
            key=uid+'.mesh'
            item={'vertices':body.vertices,'triangles':body.triangles,'plate':1,
                  'name':body.name,'unitName':'whole','color':body.color,'material':'PETG',
                  'matrix':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}
            self.original[key]=item
            moved=copy.deepcopy(item)
            moved['vertices']=[(p[0]+4,p[1]-3,p[2]) for p in body.vertices]
            moved['matrix'][0][3]+=4;moved['matrix'][1][3]-=3
            self.arranged[key]=moved
        self.groups=[['a.mesh','b.mesh']]

    def extract(self):
        with patch('BambuPlateStudio.core.auto_place.read',side_effect=[
                (self.original,self.groups,1,{}),(self.arranged,self.groups,1,{})]):
            return extract_positions(self.query,'seed','native')

    def test_rigid_group_translation_only(self):
        positions,error=self.extract()
        old=self.query.placements[self.group.uid]
        self.assertAlmostEqual(positions[self.group.uid]['x'],old.x+4)
        self.assertAlmostEqual(positions[self.group.uid]['y'],old.y-3)
        self.assertLess(error,.001)

    def test_group_member_recenter_rejected(self):
        self.arranged['b.mesh']['vertices']=[(p[0]+1,p[1],p[2]) for p in self.arranged['b.mesh']['vertices']]
        with self.assertRaisesRegex(ValueError,'组内相对位置'):self.extract()

    def test_orientation_change_rejected(self):
        self.arranged['a.mesh']['matrix'][0][0]=0
        with self.assertRaisesRegex(ValueError,'朝向'):self.extract()

    def test_plate_change_rejected(self):
        self.arranged['a.mesh']['plate']=2
        with self.assertRaisesRegex(PlateOverflow,'更多打印盘'):self.extract()


class PlacementControllerTests(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).resolve().parents[1]/'fusion_adapter/bridge.py'
        definition=next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                        if isinstance(n,ast.ClassDef) and n.name=='Controller')
        self.proposal={'plates':[1],'placements':{'a':{'x':100.,'y':100.}},'errors':[],
                       'moved':1,'total':1}
        self.engine=Mock(return_value=copy.deepcopy(self.proposal))
        namespace={'suggest_positions':self.engine,'apply_positions':apply_positions,'new_id':new_id}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(source),'exec'),namespace)
        c=self.c=namespace['Controller'].__new__(namespace['Controller'])
        c.session=Session([cube('a'),cube('b',color='#FF0000')]);c.bed=Bed(256,256,256)
        arrange(c.session,c.bed)
        c.history=EditHistory();c.orientation_preview=None;c.orientation_snapshot=None
        c.arrangement_preview=None;c.arrangement_snapshot=None;c.last_export=None;c.notices=[]
        doc=object();c.app=SimpleNamespace(activeDocument=doc);c.source=SimpleNamespace(document=doc)
        c.catalog=None;c.exe='unused';c.assert_source_current=Mock();c.update_bed=Mock()
        c.state=lambda include_profiles=False:{'arrangementPreview':c.arrangement_preview,'notices':c.notices}

    def test_preview_cancel_and_apply_undo(self):
        c=self.c;before=copy.deepcopy(c.session.rules());other=copy.deepcopy(c.session.placements['b'])
        c.dispatch('arrangement_preview',{'scope':'current','plate':1})
        token=c.arrangement_preview['token']
        self.assertEqual(c.session.rules(),before)
        c.dispatch('arrangement_cancel',{'token':token})
        self.assertEqual(c.session.rules(),before)
        c.dispatch('arrangement_preview',{'scope':'current','plate':1})
        c.dispatch('arrangement_apply',{'token':c.arrangement_preview['token']})
        self.assertEqual(c.session.placements['a'].x,100.)
        self.assertEqual(c.session.placements['b'],other)
        c.dispatch('undo',{})
        self.assertEqual(c.session.rules(),before)

    def test_all_scope_uses_existing_plates_and_stale_token_fails(self):
        c=self.c;c.dispatch('arrangement_preview',{'scope':'all'})
        self.engine.assert_called_once()
        self.assertEqual(self.engine.call_args.args[1],[1,2])
        token=c.arrangement_preview['token']
        c.dispatch('orientation_lock',{'unit':'a','locked':True})
        with self.assertRaisesRegex(ValueError,'过期'):
            c.dispatch('arrangement_apply',{'token':token})

    def test_invalid_arrangement_is_not_applied(self):
        self.engine.return_value={**self.proposal,'errors':['间距不足']}
        c=self.c;before=copy.deepcopy(c.session.rules())
        c.dispatch('arrangement_preview',{'scope':'current','plate':1})
        with self.assertRaisesRegex(ValueError,'未应用'):
            c.dispatch('arrangement_apply',{'token':c.arrangement_preview['token']})
        self.assertEqual(c.session.rules(),before)
