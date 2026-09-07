"""Tests native GUI state logic, not Fusion rendering or physical user gestures."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def dialog_class():
    source=Path(__file__).resolve().parent.parent/'fusion_adapter'/'native_ui.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    definition=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NativeDialog')
    namespace={}
    exec(compile(ast.Module(body=[definition],type_ignores=[]),str(source),'exec'),namespace)
    return namespace['NativeDialog']


class Items:
    def __init__(self):self.values=[]
    def clear(self):self.values=[]
    def add(self,name,selected):
        self.values.append(SimpleNamespace(name=name,isSelected=selected,index=len(self.values)))
    def item(self,index):return self.values[index]
    @property
    def count(self):return len(self.values)


class Dropdown:
    def __init__(self,name):self.name=name;self.listItems=Items()
    @property
    def selectedItem(self):return next((v for v in self.listItems.values if v.isSelected),None)


class NativeStateTests(unittest.TestCase):
    def setUp(self):
        cls=dialog_class();self.dialog=cls.__new__(cls)
        self.dialog.fields={key:Dropdown(key) for key in ['color','color_filament','process','body']}
        self.dialog.fields['body_hex']=SimpleNamespace(value='')
        self.dialog.choices={}
        self.rows=[{'key':'abs.json','name':'ABS'},{'key':'petg.json','name':'Generic PETG'},
                   {'key':'petg_custom.json','name':'My PETG'}]
        self.dialog.catalog_state={'filaments':self.rows}
        session=SimpleNamespace(config={'filament':'Generic PETG'},color_profiles={'#FF0000':'petg_custom.json'},
                                effective_color=lambda uid:{'a':'#FF0000','b':'#5995DA'}[uid])
        self.dialog.controller=SimpleNamespace(session=session)

    def test_default_does_not_silently_select_abs(self):
        self.dialog.fill('color',[('#5995DA','#5995DA')],'#5995DA')
        self.dialog.sync_color_profile()
        self.assertEqual(self.dialog.selected('color_filament'),'petg.json')

    def test_color_switch_shows_its_actual_override(self):
        self.dialog.fill('color',[('#FF0000','#FF0000')],'#FF0000')
        self.dialog.sync_color_profile()
        self.assertEqual(self.dialog.selected('color_filament'),'petg_custom.json')
        self.dialog.fill('color',[('#5995DA','#5995DA')],'#5995DA')
        self.dialog.sync_color_profile()
        self.assertEqual(self.dialog.selected('color_filament'),'petg.json')

    def test_missing_profile_is_placeholder_not_a_different_preset(self):
        self.dialog.fill_presets('process',self.rows,'Missing preset')
        self.assertEqual(self.dialog.fields['process'].selectedItem.name,'请选择兼容预设')
        with self.assertRaises(ValueError):self.dialog.selected('process')

    def test_body_switch_updates_color_editor(self):
        self.dialog.fill('body',[('a','A'),('b','B')],'b')
        self.dialog.sync_body_color()
        self.assertEqual(self.dialog.fields['body_hex'].value,'#5995DA')
