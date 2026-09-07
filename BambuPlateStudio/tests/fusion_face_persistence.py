"""Validate a selected BRep face across local archive reload using disposable copies."""
import json
import sys
from pathlib import Path
import adsk.core


def run(context):
    app=adsk.core.Application.get();original=app.activeDocument
    root=Path('I:/3DPrint/BambuPlateStudio').resolve()
    addon=next(m for m in list(sys.modules.values()) if getattr(m,'__file__',None)
               and Path(m.__file__).resolve()==root/'BambuPlateStudio.py' and getattr(m,'controller',None))
    addon.controller.assert_document()
    assert app.userInterface.activeCommand=='SelectCommand'
    source=root/'test_artifacts/document_roundtrip_02/paper_box_print_rules.f3d'
    output=root/'test_artifacts/document_roundtrip_03_face'
    output.mkdir(exist_ok=True)
    archive=output/'with_selected_face.f3d'
    assert not archive.exists()
    created=[];report={'passed':False,'originalDocumentModified':False}
    try:
        first=app.importManager.importToNewDocument(app.importManager.createFusionArchiveImportOptions(str(source)))
        assert first and first!=original;created.append(first)
        c=type(addon.controller)();c.scan();c.update_bed()
        bottom=next(u for u in c.session.units.values() if u.name=='底板')
        c.dispatch('viewer_face',{'unit':bottom.uid,'body':bottom.members[0],
                                'triangle':0,'revision':c.geometry_revision})
        selected=c.session.units[bottom.uid]
        expected=json.loads(json.dumps(selected.rotation))
        assert selected.face_token
        c.dispatch('save_rules',{})
        exporter=c.source.design.exportManager
        assert exporter.execute(exporter.createFusionArchiveExportOptions(str(archive)))
        second=app.importManager.importToNewDocument(app.importManager.createFusionArchiveImportOptions(str(archive)))
        assert second and second!=first and second!=original;created.append(second)
        restored=type(c)();restored.scan();restored.update_bed()
        unit=restored.session.units[bottom.uid]
        assert unit.orientation_valid and unit.face_token
        assert json.loads(json.dumps(unit.rotation))==expected
        assert len(restored.source.design.findEntityByToken(unit.face_token))==1
        assert len(restored.session.plates)==8
        report.update(passed=True,faceReferenceResolved=True,orientationUnchanged=True,
                      bodies=len(restored.session.bodies),units=len(restored.session.units),
                      plates=len(restored.session.plates),notices=restored.notices)
    finally:
        for doc in reversed(created):
            if doc.isValid and doc!=original:doc.close(False)
        original.activate();addon.controller.assert_document();addon.emit_state()
        (output/'face_persistence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report))
