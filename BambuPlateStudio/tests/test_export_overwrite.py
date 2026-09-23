import ast,hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from BambuPlateStudio.core.bambu import export_native


class NativeOverwriteTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.seed=self.root/'seed.3mf'
        with zipfile.ZipFile(self.seed,'w') as archive:
            archive.writestr('Metadata/BambuPlateStudio.json',json.dumps({'warnings':[]}))
        self.target=self.root/'project.3mf'
        self.target.write_bytes(b'original project')
        self.fidelity={'bodies':1,'objects':1,'plates':1,'maxVertexErrorMm':0.}

    def engine(self,seed,job,catalog,executable,timeout=60):
        native=Path(job)/'project.3mf'
        native.write_bytes(b'verified replacement')
        return native,0.1

    def export(self,overwrite=True):
        with patch('BambuPlateStudio.core.bambu.run_project',side_effect=self.engine),\
             patch('BambuPlateStudio.core.bambu.verify',return_value=self.fidelity):
            return export_native(self.seed,self.target,None,None,overwrite=overwrite)

    def test_existing_file_still_requires_explicit_overwrite(self):
        with self.assertRaises(FileExistsError):self.export(overwrite=False)
        self.assertEqual(self.target.read_bytes(),b'original project')

    def test_success_replaces_only_after_verification(self):
        report=self.export()
        self.assertEqual(self.target.read_bytes(),b'verified replacement')
        self.assertEqual(report['sha256'],hashlib.sha256(b'verified replacement').hexdigest())
        self.assertFalse(list(self.root.glob('project.3mf.*.tmp')))

    def test_engine_or_verification_failure_preserves_old_file(self):
        with patch('BambuPlateStudio.core.bambu.run_project',side_effect=RuntimeError('engine failed')):
            with self.assertRaisesRegex(RuntimeError,'engine failed'):
                export_native(self.seed,self.target,None,None,overwrite=True)
        with patch('BambuPlateStudio.core.bambu.run_project',side_effect=self.engine),\
             patch('BambuPlateStudio.core.bambu.verify',side_effect=ValueError('fidelity failed')):
            with self.assertRaisesRegex(ValueError,'fidelity failed'):
                export_native(self.seed,self.target,None,None,overwrite=True)
        self.assertEqual(self.target.read_bytes(),b'original project')

    def test_replace_failure_preserves_old_file_and_removes_staging(self):
        with patch('BambuPlateStudio.core.bambu.os.replace',side_effect=OSError('file in use')):
            with self.assertRaisesRegex(OSError,'file in use'):self.export()
        self.assertEqual(self.target.read_bytes(),b'original project')
        self.assertFalse(list(self.root.glob('project.3mf.*.tmp')))

    def test_copy_failure_preserves_old_file_and_removes_staging(self):
        with patch('BambuPlateStudio.core.bambu.shutil.copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):self.export()
        self.assertEqual(self.target.read_bytes(),b'original project')
        self.assertFalse(list(self.root.glob('project.3mf.*.tmp')))

    def test_file_changed_during_export_is_not_overwritten(self):
        def changed_seed(seed,job,catalog,executable,timeout=60):
            self.target.write_bytes(b'changed by another process')
            return self.engine(seed,job,catalog,executable,timeout)
        with patch('BambuPlateStudio.core.bambu.run_project',side_effect=changed_seed),\
             patch('BambuPlateStudio.core.bambu.verify',return_value=self.fidelity):
            with self.assertRaisesRegex(RuntimeError,'期间发生变化'):
                export_native(self.seed,self.target,None,None,overwrite=True)
        self.assertEqual(self.target.read_bytes(),b'changed by another process')
        self.assertFalse(list(self.root.glob('project.3mf.*.tmp')))


class FusionConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target=Path(self.temporary.name)/'project.3mf'
        self.target.write_bytes(b'original project')
        source=Path(__file__).resolve().parents[1]/'fusion_adapter'/'bridge.py'
        definition=next(node for node in ast.parse(source.read_text(encoding='utf-8')).body
                        if isinstance(node,ast.ClassDef) and node.name=='Controller')
        results=SimpleNamespace(DialogOK='ok',DialogYes='yes')
        adsk=SimpleNamespace(core=SimpleNamespace(DialogResults=results,
            MessageBoxButtonTypes=SimpleNamespace(YesNoButtonType='yes-no'),
            MessageBoxIconTypes=SimpleNamespace(QuestionIconType='question')))
        namespace={'Path':Path,'adsk':adsk}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(source),'exec'),namespace)
        self.controller=namespace['Controller'].__new__(namespace['Controller'])
        self.dialog=SimpleNamespace(title='',filter='',initialFilename='',filename=str(self.target),
                                    showSave=Mock(return_value='ok'))
        self.ui=SimpleNamespace(createFileDialog=Mock(return_value=self.dialog),messageBox=Mock(return_value='yes'))
        self.controller.app=SimpleNamespace(userInterface=self.ui)
        self.controller.assert_document=Mock()
        self.controller.export_to=Mock()
        self.controller.state=Mock(return_value={})
        self.controller.notices=[]

    def test_existing_file_requires_second_yes(self):
        self.controller._dispatch('export',{})
        self.ui.messageBox.assert_called_once()
        self.controller.export_to.assert_called_once_with(str(self.target),overwrite=True)

    def test_no_preserves_old_file_without_export(self):
        self.ui.messageBox.return_value='no'
        self.controller._dispatch('export',{})
        self.controller.export_to.assert_not_called()
        self.assertEqual(self.target.read_bytes(),b'original project')

    def test_new_file_needs_no_overwrite_confirmation(self):
        self.dialog.filename=str(self.target.parent/'new.3mf')
        self.controller._dispatch('export',{})
        self.ui.messageBox.assert_not_called()
        self.controller.export_to.assert_called_once_with(self.dialog.filename,overwrite=False)
