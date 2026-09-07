"""Three-phase development reload preserving unsaved printing edits and undo history."""
import json
import sys
import importlib
from pathlib import Path
import adsk.core


def run(context):
    root=Path('I:/3DPrint/BambuPlateStudio').resolve()
    version=json.loads((root/'BambuPlateStudio.manifest').read_text(encoding='utf-8'))['version']
    path=root/'test_artifacts'/('reload_'+version+'.json')
    app=adsk.core.Application.get()
    assert app.userInterface.activeCommand=='SelectCommand'
    script=app.scripts.itemByPath(str(root))
    if context=='save':
        addon=next(m for m in list(sys.modules.values()) if getattr(m,'__file__',None)
                   and Path(m.__file__).resolve()==root/'BambuPlateStudio.py' and getattr(m,'controller',None))
        c=addon.controller;c.assert_document()
        data={'rules':c.session.rules(),'undo':c.history.undo_stack,'redo':c.history.redo_stack,
              'rootToken':c.source.design.rootComponent.entityToken,'exe':c.exe,
              'profileRoots':sorted({str(p.path.parent.parent) for p in c.catalog.records.values()}),
              'lastExport':c.last_export}
        with path.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False)
        assert script.stop()
        print(json.dumps({'saved':True,'undoEntries':len(data['undo'])}))
    elif context=='start':
        assert not script.isRunning
        for name,module in list(sys.modules.items()):
            filename=getattr(module,'__file__',None)
            if filename and root in Path(filename).resolve().parents:del sys.modules[name]
        importlib.invalidate_caches()
        print(json.dumps({'startRequested':script.run()}))
    elif context=='restore':
        assert script.isRunning
        addon=next(m for m in list(sys.modules.values()) if getattr(m,'__file__',None)
                   and Path(m.__file__).resolve()==root/'BambuPlateStudio.py' and getattr(m,'controller',None))
        data=json.loads(path.read_text(encoding='utf-8'));c=addon.controller
        c.scan()
        resolved=c.source.design.findEntityByToken(data['rootToken'])
        aliases=c.source.aliases_for(data['rules'])
        same_root=any(e==c.source.design.rootComponent for e in resolved)
        if not same_root:
            # Some Fusion builds do not resolve the root component's own token.
            # Require its unchanged token AND all original body references/geometry.
            same_root=c.source.design.rootComponent.entityToken==data['rootToken'] and len(aliases)==len(data['rules']['sources']) and all(
                aliases[s['uid']] in c.session.bodies and c.session.bodies[aliases[s['uid']]].geometry_key()==s.get('geometryKey')
                for s in data['rules']['sources'])
        assert same_root,'The active document changed'
        c.exe=data['exe'];c.catalog=type(c.catalog)(data['profileRoots'])
        c.session.apply_rules(data['rules'],aliases);c.update_bed()
        c.history.undo_stack=data['undo'];c.history.redo_stack=data['redo'];c.last_export=data['lastExport']
        current=json.loads(json.dumps(c.session.rules()))
        expected_placements=[dict(p,z=p.get('z',0.)) for p in data['rules']['placements']]
        assert current['placements']==expected_placements,'Placement preservation failed'
        assert current['units']==data['rules']['units'],'Group or direction preservation failed'
        assert current['config']==data['rules']['config'],'Config preservation failed'
        c.notices=['插件已更新，当前打印组、盘位、方向及撤销/重做记录已恢复。']
        addon.emit_state()
        print(json.dumps({'restored':True,'units':len(c.session.units),'plates':len(c.session.plates),
                          'undoEntries':len(c.history.undo_stack),'errors':c.state()['errors']}))
    else:raise ValueError('Specify save, start or restore')
