import copy
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from BambuPlateStudio.core.geometry import face_down, rotate, dot, cross, transform_point
from BambuPlateStudio.core.model import Body, Session, Placement, Plate, PrintUnit
from BambuPlateStudio.core.layout import Bed, arrange, validate, process_clearance
from BambuPlateStudio.core.package3mf import write_project, inspect_project, CORE
from BambuPlateStudio.core.profiles import ProfileCatalog, discover, project_settings


def cube(uid='a', color='#040531', low=(0, 0, 0), size=(20, 20, 20)):
    x, y, z = low
    w, d, h = size
    vertices = [(x,y,z), (x+w,y,z), (x+w,y+d,z), (x,y+d,z),
                (x,y,z+h), (x+w,y,z+h), (x+w,y+d,z+h), (x,y+d,z+h)]
    triangles = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
                 (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    body = Body(uid, '零件 '+uid, '组件:1', color, vertices, triangles,
                face_colors={color: 1.})
    body.validate()
    return body


def flat_rectangles(uid,rectangles):
    vertices,triangles=[],[]
    for x,y,width,height in rectangles:
        start=len(vertices)
        vertices.extend(((x,y,0),(x+width,y,0),(x+width,y+height,0),(x,y+height,0)))
        triangles.extend(((start,start+1,start+2),(start,start+2,start+3)))
    body=Body(uid,'零件 '+uid,'组件:1','#040531',vertices,triangles,face_colors={'#040531':1.})
    body.validate()
    return body


class GeometryTests(unittest.TestCase):
    def test_face_down_all_axes(self):
        for normal in [(0,0,1), (0,0,-1), (1,0,0), (0,-1,0), (1,2,3)]:
            r = face_down(normal)
            actual = rotate(r, normal)
            self.assertAlmostEqual(actual[0], 0)
            self.assertAlmostEqual(actual[1], 0)
            self.assertLess(actual[2], 0)
            self.assertAlmostEqual(dot(r[0], cross(r[1], r[2])), 1.)

    def test_rigid_group_not_individually_grounded(self):
        session = Session([cube('lid', low=(0,0,80), size=(10,10,20)),
                           cube('frame', low=(20,0,-4), size=(10,10,104))])
        group = session.group(list(session.units), '顶盖与框架')
        group.rotation = face_down((0,0,1))
        arrange(session, Bed(256,256,256))
        placement = session.placements[group.uid]
        matrix = group.matrix(session.bodies, placement)
        self.assertAlmostEqual(transform_point(matrix, (0,0,100))[2], 0.)
        self.assertAlmostEqual(transform_point(matrix, (0,0,80))[2], 20.)
        self.assertAlmostEqual(transform_point(matrix, (20,0,-4))[2], 104.)

    def test_colors_split_and_manual_collision_blocked(self):
        session = Session([cube(), cube('b'), cube('c', '#FF0000')])
        bed = Bed(60,60,50)
        arrange(session, bed)
        self.assertEqual(len(session.plates), 2)
        session.placements['b'] = copy.copy(session.placements['a'])
        session.placements['b'].unit = 'b'
        self.assertTrue(any('间距' in e for e in validate(session, bed)[0]))

    def test_concave_footprint_uses_real_mesh_spacing(self):
        frame=flat_rectangles('frame',[(0,0,2,20),(18,0,2,20),(2,0,16,2)])
        inner=flat_rectangles('inner',[(0,0,10,10)])
        session=Session([frame,inner]);session.plates=[Plate(1,'test')]
        session.placements={'frame':Placement('frame',1,10,10),'inner':Placement('inner',1,15,15)}
        session.config['gap']=2
        self.assertEqual(validate(session,Bed(100,100,50))[0],[])
        session.config['gap']=4
        self.assertTrue(any('间距' in error for error in validate(session,Bed(100,100,50))[0]))
        session.config['gap']=2;session.placements['inner'].x=11
        self.assertTrue(any('间距' in error for error in validate(session,Bed(100,100,50))[0]))

    def test_spacing_tolerates_sub_micron_mesh_rounding(self):
        session=Session([flat_rectangles('a',[(0,0,10,10)]),flat_rectangles('b',[(0,0,10,10)])])
        session.plates=[Plate(1,'test')]
        session.placements={'a':Placement('a',1,10,10),'b':Placement('b',1,21.99998,10)}
        session.config['gap']=2
        self.assertEqual(validate(session,Bed(100,100,50))[0],[])
        session.placements['b'].x=21.98
        self.assertTrue(any('间距' in error for error in validate(session,Bed(100,100,50))[0]))

    def test_default_has_no_extra_gap_but_rejects_real_overlap(self):
        session=Session([flat_rectangles('a',[(0,0,10,10)]),flat_rectangles('b',[(0,0,10,10)])])
        session.plates=[Plate(1,'test')]
        session.placements={'a':Placement('a',1,10,10),'b':Placement('b',1,20.5,10)}
        self.assertEqual(session.config['gap'],0)
        self.assertEqual(validate(session,Bed(100,100,50))[0],[])
        session.placements['b'].x=19.5
        self.assertTrue(any('间距' in error for error in validate(session,Bed(100,100,50))[0]))

    def test_oversize_never_scaled(self):
        session = Session([cube(size=(300,300,20))])
        original = copy.deepcopy(session.bodies['a'].vertices)
        with self.assertRaises(ValueError):
            arrange(session, Bed(256,256,256))
        self.assertEqual(original, session.bodies['a'].vertices)

    def test_rules_restore_and_geometry_change_preserves_group_layout(self):
        session = Session([cube(), cube('b', low=(30,0,0))])
        session.config['gap']=5
        session.group(list(session.units), '原位组')
        arrange(session, Bed(256,256,256))
        rules = json.loads(json.dumps(session.rules()))
        restored = Session([cube(), cube('b', low=(30,0,0))])
        self.assertEqual(restored.apply_rules(rules), [])
        self.assertEqual(restored.config['gap'],5)
        self.assertEqual(len(restored.units), 1)
        self.assertEqual(len(restored.placements), 1)
        changed = Session([cube(size=(21,20,20)), cube('b', low=(30,0,0))])
        self.assertTrue(changed.apply_rules(rules))
        self.assertEqual(changed.placements, session.placements)
        self.assertEqual(changed.units, session.units)
        self.assertEqual(validate(changed, Bed(256,256,256))[0], [])

    def test_mixed_face_colors_require_decision(self):
        body = cube()
        body.face_colors['#FF0000'] = 1.
        session = Session([body])
        with self.assertRaisesRegex(ValueError, '多种面颜色'):
            arrange(session, Bed(256,256,256))
        session.color_overrides['a'] = '#FF0000'
        arrange(session, Bed(256,256,256))

    def test_duplicate_group_request_is_atomic(self):
        session=Session([cube(),cube('b')])
        with self.assertRaises(ValueError):session.group(['a','a'],'错误分组')
        self.assertEqual(set(session.units),{'a','b'})

    def test_rules_cannot_scale_or_reflect_geometry(self):
        session=Session([cube()]);rules=session.rules()
        rules['units'][0]['rotation']=((2,0,0),(0,1,0),(0,0,1))
        with self.assertRaises(ValueError):session.apply_rules(rules)
        rules['units'][0]['rotation']=((-1,0,0),(0,1,0),(0,0,1))
        with self.assertRaises(ValueError):session.apply_rules(rules)

    def test_color_change_preserves_saved_layout(self):
        session=Session([cube()]);arrange(session,Bed(256,256,256))
        changed=Session([cube(color='#FF0000')])
        self.assertTrue(changed.apply_rules(session.rules()))
        self.assertEqual(changed.placements,session.placements)
        self.assertEqual(changed.effective_color('a'),'#FF0000')
        self.assertEqual(validate(changed,Bed(256,256,256))[0],[])

    def test_clearance_is_reserved_around_each_print_unit(self):
        session=Session([cube(),cube('b')])
        session.config['printClearance']=5.1
        arrange(session,Bed(256,256,256))
        for placement in session.placements.values():
            self.assertGreaterEqual(placement.x,10.1-1e-7)
            self.assertGreaterEqual(placement.y,10.1-1e-7)
        self.assertFalse(validate(session,Bed(256,256,256))[0])

    def test_auto_brim_is_warning_not_false_collision(self):
        session=Session([cube('a',size=(53.37,36.47,10)),cube('b',size=(40.31,11.82,10))])
        session.config['gap']=5
        session.config['autoBrimReserve']=5.1
        session.plates=[Plate(1,'test')]
        session.placements={'a':Placement('a',1,10.1,10.1),
                            'b':Placement('b',1,10.1,58.2912)}
        errors,warnings=validate(session,Bed(256,256,256))
        self.assertEqual(errors,[])
        self.assertTrue(any('自动裙边' in warning for warning in warnings))

    def test_actual_bed_exit_is_distinguished_from_margin(self):
        session=Session([cube()]);session.plates=[Plate(1,'test')]
        session.placements={'a':Placement('a',1,-0.1,10)}
        self.assertTrue(any('实际范围' in error for error in validate(session,Bed(256,256,256))[0]))
        session.placements['a'].x=2
        self.assertTrue(any('板边距' in error for error in validate(session,Bed(256,256,256))[0]))

    def test_lost_face_reference_blocks_arrangement(self):
        session=Session([cube()]);session.units['a'].orientation_valid=False
        with self.assertRaisesRegex(ValueError,'引用已失效'):arrange(session,Bed(256,256,256))

    def test_missing_group_member_never_silently_splits(self):
        original=Session([cube(),cube('b')]);original.group(['a','b'],'不可拆组')
        changed=Session([cube()]);changed.apply_rules(original.rules())
        self.assertTrue(changed.rule_errors)
        with self.assertRaisesRegex(ValueError,'不能自动拆散'):arrange(changed,Bed(256,256,256))
        reopened=Session([cube()]);reopened.apply_rules(changed.rules())
        with self.assertRaisesRegex(ValueError,'不能自动拆散'):arrange(reopened,Bed(256,256,256))
        changed.reset_units();arrange(changed,Bed(256,256,256))


class InstalledProfilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe, roots = discover()
        if not roots:
            raise unittest.SkipTest('本机未安装 Bambu Studio；需要在集成测试环境执行。')
        cls.catalog = ProfileCatalog(roots)

    def test_petg_defaults_are_real_profiles(self):
        session = Session([cube()])
        errors, machine, process = self.catalog.check(session.config, [session.config['filament']])
        self.assertEqual(errors, [])
        self.assertEqual(Bed.from_profile(machine).width, 256)
        filament = self.catalog.resolve('filament', session.config['filament'])
        self.assertIn('PETG', filament['filament_type'])
        self.assertTrue(all(float(v) > 200 for v in filament['nozzle_temperature']))

    def test_refreshed_layout_exports_current_geometry_and_rejects_collision(self):
        original=Session([cube(),cube('b')]);original.plates=[Plate(1)]
        original.placements={'a':Placement('a',1,60,90),'b':Placement('b',1,150,90)}
        changed=Session([cube(size=(21,20,20)),cube('b')])
        changed.apply_rules(original.rules())
        with tempfile.TemporaryDirectory() as directory:
            safe=Path(directory)/'updated.3mf'
            write_project(safe,changed,self.catalog)
            with zipfile.ZipFile(safe) as archive:
                model=ET.fromstring(archive.read('3D/3dmodel.model'))
                vertices=model.find('c:resources/c:object/c:mesh/c:vertices',{'c':CORE})
                self.assertEqual(max(float(v.attrib['x']) for v in vertices),21)
            colliding=Session([cube(size=(110,20,20)),cube('b')])
            colliding.apply_rules(original.rules())
            rejected=Path(directory)/'collision.3mf'
            with self.assertRaisesRegex(ValueError,'实体轮廓间距'):
                write_project(rejected,colliding,self.catalog)
            self.assertFalse(rejected.exists())
        self.assertEqual(changed.placements,original.placements)
        self.assertEqual(colliding.placements,original.placements)

    def test_export_group_and_namespace_regression(self):
        session = Session([cube(), cube('b', low=(30,0,0)), cube('c', '#E8AD23')])
        group = session.group(['a', 'b'], '整体')
        group.rotation = face_down((0,0,1))
        bed = Bed.from_profile(self.catalog.resolve('machine', session.config['printer']))
        session.config['printClearance'] = process_clearance(
            self.catalog.resolve('process',session.config['process']),session.config['enableSupport'])
        arrange(session, bed)
        ET.register_namespace('', CORE)  # Must not poison relationship XML serialization.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'test.3mf'
            result = write_project(path, session, self.catalog)
            self.assertEqual(result['objects'], 2)
            self.assertEqual(inspect_project(path), {'bodies':3,'objects':2,'plates':2,'colors':2,'hasGcode':False})
            with zipfile.ZipFile(path) as archive:
                settings = json.loads(archive.read('Metadata/project_settings.config'))
                self.assertEqual(settings['filament_type'], ['PETG','PETG'])
                self.assertEqual(len(settings['machine_max_speed_x']), 6)
                self.assertEqual(settings['enable_prime_tower'],'0')
                self.assertIn(b'<Relationship ', archive.read('_rels/.rels'))
            with self.assertRaises(FileExistsError):
                write_project(path, session, self.catalog)

    def test_auto_brim_inside_bed_is_warning_not_export_blocker(self):
        session=Session([cube()])
        arrange(session,Bed.from_profile(self.catalog.resolve('machine',session.config['printer'])))
        # Reproduce the legacy corner layout; centered positions may already be safe.
        session.placements['a'].x=session.placements['a'].y=session.config['margin']
        original=copy.deepcopy(session.placements)
        self.assertEqual(session.config['printClearance'],0)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'auto_brim.3mf'
            report=write_project(path,session,self.catalog)
            self.assertTrue(path.exists())
            self.assertTrue(any('自动裙边' in warning for warning in report['warnings']))
        self.assertEqual(session.placements,original)
        self.assertEqual(session.config['printClearance'],0)
        self.assertGreater(session.config['autoBrimReserve'],0)

    def test_arrangement_scratch_seed_only_waives_xy_errors(self):
        session=Session([cube('a'),cube('b')]);session.plates=[Plate(1,'test')]
        session.placements={'a':Placement('a',1,10,10),'b':Placement('b',1,15,15)}
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            with self.assertRaisesRegex(ValueError,'间距'):
                write_project(output/'final.3mf',session,self.catalog)
            self.assertFalse((output/'final.3mf').exists())
            write_project(output/'scratch.3mf',session,self.catalog,allow_unarranged=True)
            self.assertTrue((output/'scratch.3mf').exists())
            session.color_overrides['b']='#FF0000'
            with self.assertRaisesRegex(ValueError,'不同颜色'):
                write_project(output/'mixed.3mf',session,self.catalog,allow_unarranged=True)

    def test_native_export_rejects_non_3mf_filename_before_launch(self):
        from BambuPlateStudio.core.bambu import export_native
        with self.assertRaisesRegex(ValueError,'.3mf'):
            export_native('unused.3mf','wrong.stl',self.catalog,self.exe)

    def test_fidelity_rejects_changed_unicode_body_names(self):
        from BambuPlateStudio.core.bambu_validation import verify
        session=Session([cube()])
        session.config['printClearance']=process_clearance(
            self.catalog.resolve('process',session.config['process']),session.config['enableSupport'])
        arrange(session,Bed.from_profile(self.catalog.resolve('machine',session.config['printer'])))
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.3mf';changed=Path(directory)/'changed.3mf'
            write_project(source,session,self.catalog)
            with zipfile.ZipFile(source) as a,zipfile.ZipFile(changed,'x') as b:
                for item in a.infolist():
                    data=a.read(item.filename)
                    if item.filename=='Metadata/model_settings.config':
                        root=ET.fromstring(data)
                        name=next(m for m in root.findall('object/part/metadata') if m.get('key')=='name')
                        name.set('value','被错误改名')
                        data=ET.tostring(root,encoding='utf-8')
                    b.writestr(item,data)
            with self.assertRaisesRegex(AssertionError,'name changed'):verify(source,changed)


if __name__ == '__main__':
    unittest.main()
