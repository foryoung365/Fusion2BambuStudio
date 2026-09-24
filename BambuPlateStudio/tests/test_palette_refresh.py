import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


class FakePalette:
    def __init__(self,visible=True):
        self.isValid=True
        self._visible=visible
        self.changes=[]

    @property
    def isVisible(self):return self._visible

    @isVisible.setter
    def isVisible(self,value):
        self.changes.append(value)
        self._visible=value


class PaletteRefreshTests(unittest.TestCase):
    def handler(self,palette):
        source=Path(__file__).resolve().parents[1]/'BambuPlateStudio.py'
        definition=next(item for item in ast.parse(source.read_text(encoding='utf-8')).body
                        if isinstance(item,ast.ClassDef) and item.name=='HtmlHandler')
        app=SimpleNamespace(userInterface=SimpleNamespace(
            palettes=SimpleNamespace(itemById=lambda _id:palette)))
        core=SimpleNamespace(HTMLEventHandler=object,
                             HTMLEventArgs=SimpleNamespace(cast=lambda args:args),
                             Application=SimpleNamespace(get=lambda:app))
        namespace={'adsk':SimpleNamespace(core=core),'PALETTE':'BambuPlateStudio_Palette',
                   'event_log':[]}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(source),'exec'),namespace)
        return namespace['HtmlHandler'](),namespace['event_log']

    def test_visible_palette_is_reshown_after_preview_closes(self):
        palette=FakePalette();handler,log=self.handler(palette)
        args=SimpleNamespace(action='palette_refresh',data='',returnData=None)
        handler.notify(args)
        self.assertEqual(palette.changes,[False,True])
        self.assertTrue(palette.isVisible)
        self.assertEqual(args.returnData,'OK')
        self.assertEqual(log[-1],{'action':'palette_refresh','visible':True})

    def test_user_closed_palette_is_not_reopened(self):
        palette=FakePalette(False);handler,_=self.handler(palette)
        handler.notify(SimpleNamespace(action='palette_refresh',data='',returnData=None))
        self.assertEqual(palette.changes,[])


if __name__=='__main__':unittest.main()
