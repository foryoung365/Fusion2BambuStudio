import ast,copy,time,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock,patch
from BambuPlateStudio.core.auto_place import plate_query,extract_positions,suggest,apply_positions
from BambuPlateStudio.core.model import Session,Plate,Placement,new_id
from BambuPlateStudio.core.layout import arrange,Bed,validate
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
        self.native_plates=1

    def extract(self):
        with patch('BambuPlateStudio.core.auto_place.read',side_effect=[
                (self.original,self.groups,1,{}),(self.arranged,self.groups,self.native_plates,{})]):
            return extract_positions(self.query,'seed','native',Bed(256,256,256))

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

    def test_split_group_members_rejected(self):
        self.native_plates=2
        self.arranged['a.mesh']['plate']=2
        with self.assertRaisesRegex(ValueError,'拆散了不可拆分'):self.extract()

    def test_split_independent_unit_uses_plate_local_coordinates(self):
        query=Session([cube('a'),cube('b')]);query.plates=[Plate(1,'test')]
        query.placements={'a':Placement('a',1,5,5),'b':Placement('b',1,5,5)}
        original={};arranged={}
        for uid,body in query.bodies.items():
            item={'vertices':body.vertices,'triangles':body.triangles,'plate':1,
                  'name':body.name,'unitName':body.name,'color':body.color,'material':'PETG',
                  'matrix':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}
            original[uid+'.mesh']=item
            moved=copy.deepcopy(item);offset=307.2 if uid=='b' else 0.
            moved['vertices']=[(x+offset+4,y-3,z) for x,y,z in body.vertices]
            moved['matrix'][0][3]+=offset+4;moved['matrix'][1][3]-=3
            moved['plate']=2 if uid=='b' else 1
            arranged[uid+'.mesh']=moved
        groups=[['a.mesh'],['b.mesh']]
        with patch('BambuPlateStudio.core.auto_place.read',side_effect=[
                (original,groups,1,{}),(arranged,groups,2,{})]):
            positions,error=extract_positions(query,'seed','native',Bed(256,256,256))
        self.assertEqual(positions['b']['nativePlate'],2)
        self.assertAlmostEqual(positions['b']['x'],9)
        self.assertAlmostEqual(positions['b']['y'],2)
        self.assertLess(error,.001)


class SplitSuggestionTests(unittest.TestCase):
    def test_all_scope_appends_new_plate_without_changing_other_plate(self):
        session=Session([cube('a'),cube('b'),cube('c')])
        session.plates=[Plate(1,'first'),Plate(2,'second')]
        session.placements={'a':Placement('a',1,10,10),'b':Placement('b',1,20,10),
                            'c':Placement('c',2,10,10)}
        catalog=Mock();catalog.resolve.return_value={
            'printable_area':['0x0','256x0','256x256','0x256'],'printable_height':256}
        before=copy.deepcopy(session.rules())
        def native(_session,number,_catalog,_executable):
            return ({'a':{'nativePlate':1,'x':10,'y':10},
                     'b':{'nativePlate':2,'x':10,'y':10}} if number==1 else
                    {'c':{'nativePlate':1,'x':10,'y':10}}),0.
        with patch('BambuPlateStudio.core.auto_place.suggest_plate',side_effect=native):
            proposal=suggest(session,[1,2],catalog,'unused')
        self.assertEqual(session.rules(),before)
        self.assertEqual(proposal['newPlates'][0]['index'],3)
        self.assertEqual(proposal['placements']['b']['plate'],3)
        self.assertEqual(proposal['placements']['c']['plate'],2)
        self.assertEqual(proposal['plates'],[1,2,3])
        self.assertEqual(proposal['errors'],[])
        apply_positions(session,proposal)
        self.assertEqual([plate.index for plate in session.plates],[1,2,3])
        self.assertEqual(session.placements['c'].plate,2)
        self.assertEqual(session.placements['b'].plate,3)
        self.assertEqual(validate(session,Bed(256,256,256))[0],[])

    def test_explicit_bambu_spacing_acceptance_changes_current_gap_only_on_apply(self):
        session=Session([cube('a'),cube('b'),cube('c')]);session.plates=[Plate(1,'first')]
        session.placements={uid:Placement(uid,1,10,10) for uid in session.units}
        session.config['gap']=5
        catalog=Mock();catalog.resolve.return_value={
            'printable_area':['0x0','256x0','256x256','0x256'],'printable_height':256}
        before=copy.deepcopy(session.rules())
        native=({'a':{'nativePlate':1,'x':10,'y':10},
                 'b':{'nativePlate':2,'x':10,'y':10},
                 'c':{'nativePlate':2,'x':32,'y':10}},0.)
        with patch('BambuPlateStudio.core.auto_place.suggest_plate',return_value=native):
            proposal=suggest(session,[1],catalog,'unused')
        self.assertEqual(session.rules(),before)
        self.assertTrue(proposal['errors'])
        self.assertTrue(proposal['canAcceptBambuSpacing'])
        with self.assertRaisesRegex(ValueError,'未应用'):apply_positions(session,proposal)
        self.assertEqual(session.rules(),before)
        apply_positions(session,proposal,True)
        self.assertEqual(session.config['gap'],0)
        self.assertEqual(session.placements['b'].plate,2)
        self.assertEqual(validate(session,Bed(256,256,256))[0],[])

    def test_real_overlap_cannot_be_accepted_as_bambu_spacing(self):
        session=Session([cube('a'),cube('b')]);session.plates=[Plate(1,'first')]
        session.placements={uid:Placement(uid,1,10,10) for uid in session.units}
        session.config['gap']=5
        catalog=Mock();catalog.resolve.return_value={
            'printable_area':['0x0','256x0','256x256','0x256'],'printable_height':256}
        native=({'a':{'nativePlate':1,'x':10,'y':10},
                 'b':{'nativePlate':1,'x':29,'y':10}},0.)
        with patch('BambuPlateStudio.core.auto_place.suggest_plate',return_value=native):
            proposal=suggest(session,[1],catalog,'unused')
        self.assertTrue(proposal['errors'])
        self.assertFalse(proposal['canAcceptBambuSpacing'])
        with self.assertRaisesRegex(ValueError,'未应用'):apply_positions(session,proposal,True)
        self.assertEqual(session.config['gap'],5)


class PlacementControllerTests(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).resolve().parents[1]/'fusion_adapter/bridge.py'
        definition=next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                        if isinstance(n,ast.ClassDef) and n.name=='Controller')
        self.proposal={'plates':[1],'newPlates':[],
                       'placements':{'a':{'plate':1,'x':100.,'y':100.}},'errors':[],
                       'moved':1,'total':1}
        self.engine=Mock(return_value=copy.deepcopy(self.proposal))
        namespace={'suggest_positions':self.engine,'apply_positions':apply_positions,'new_id':new_id,
                   'ThreadPoolExecutor':ThreadPoolExecutor,'time':time}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(source),'exec'),namespace)
        c=self.c=namespace['Controller'].__new__(namespace['Controller'])
        c.session=Session([cube('a'),cube('b',color='#FF0000')]);c.bed=Bed(256,256,256)
        arrange(c.session,c.bed)
        c.history=EditHistory();c.orientation_preview=None;c.orientation_snapshot=None
        c.arrangement_preview=None;c.arrangement_snapshot=None;c.last_export=None;c.notices=[]
        c.preview_executor=None;c.preview_job=None;c.geometry_revision=1
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

    def test_accept_split_appends_plate_and_undo_restores_original(self):
        c=self.c;before=copy.deepcopy(c.session.rules())
        self.engine.return_value={**self.proposal,'plates':[1,3],
            'newPlates':[{'index':3,'name':'由第 1 盘拆出','allow_mixed':False}],
            'placements':{'a':{'plate':3,'x':100.,'y':100.}}}
        c.dispatch('arrangement_preview',{'scope':'current','plate':1})
        self.assertEqual(c.session.rules(),before)
        c.dispatch('arrangement_apply',{'token':c.arrangement_preview['token']})
        self.assertEqual([plate.index for plate in c.session.plates],[1,2,3])
        self.assertEqual(c.session.placements['a'].plate,3)
        self.assertEqual(c.session.placements['b'].plate,2)
        c.dispatch('undo',{})
        self.assertEqual(c.session.rules(),before)

    def test_invalid_arrangement_is_not_applied(self):
        self.engine.return_value={**self.proposal,'errors':['间距不足']}
        c=self.c;before=copy.deepcopy(c.session.rules())
        c.dispatch('arrangement_preview',{'scope':'current','plate':1})
        with self.assertRaisesRegex(ValueError,'未应用'):
            c.dispatch('arrangement_apply',{'token':c.arrangement_preview['token']})
        self.assertEqual(c.session.rules(),before)

    def test_explicit_spacing_acceptance_and_undo(self):
        c=self.c;c.session.config['gap']=5;before=copy.deepcopy(c.session.rules())
        self.engine.return_value={**self.proposal,'errors':['间距不足'],
                                  'canAcceptBambuSpacing':True}
        c.dispatch('arrangement_preview',{'scope':'current','plate':1})
        c.dispatch('arrangement_apply',{'token':c.arrangement_preview['token'],
                                        'acceptBambuSpacing':True})
        self.assertEqual(c.session.config['gap'],0)
        self.assertEqual(c.session.placements['a'].x,100.)
        c.dispatch('undo',{})
        self.assertEqual(c.session.rules(),before)

    def test_background_preview_returns_immediately_and_polls_result(self):
        c=self.c;before=copy.deepcopy(c.session.rules());gate=Event()
        self.engine.side_effect=lambda *args:(gate.wait(5),copy.deepcopy(self.proposal))[1]
        started=c.dispatch('arrangement_preview',{'scope':'current','plate':1,'background':True})
        token=started['pendingPreview']['token']
        self.assertEqual(c.session.rules(),before)
        self.assertIn('pendingPreview',c.dispatch('preview_status',{'token':token}))
        with self.assertRaisesRegex(ValueError,'正在计算'):
            c.dispatch('arrange',{})
        gate.set()
        result=None
        for _ in range(100):
            result=c.dispatch('preview_status',{'token':token})
            if 'pendingPreview' not in result:break
            time.sleep(.01)
        self.assertIsNotNone(c.arrangement_preview)
        self.assertEqual(c.session.rules(),before)
        c.close()

    def test_background_failure_does_not_change_rules(self):
        c=self.c;before=copy.deepcopy(c.session.rules())
        self.engine.side_effect=RuntimeError('native failed')
        token=c.dispatch('arrangement_preview',{'scope':'current','plate':1,'background':True})['pendingPreview']['token']
        for _ in range(100):
            if c.preview_job['future'].done():break
            time.sleep(.01)
        with self.assertRaisesRegex(RuntimeError,'native failed'):
            c.dispatch('preview_status',{'token':token})
        self.assertIsNone(c.preview_job)
        self.assertEqual(c.session.rules(),before)
        c.close()
