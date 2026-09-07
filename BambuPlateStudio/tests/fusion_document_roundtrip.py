"""Persist rules in a local F3D and reopen an isolated copy; leave the source open."""
import json
import sys
from pathlib import Path
import adsk.core


def run(context):
    app=adsk.core.Application.get()
    assert app.userInterface.activeCommand=='SelectCommand'
    source_doc=app.activeDocument
    assert source_doc and source_doc.dataFile is None,'Use the isolated local test document'
    root=Path('I:/3DPrint/BambuPlateStudio').resolve()
    addons=[m for m in list(sys.modules.values()) if getattr(m,'__file__',None)
            and Path(m.__file__).resolve()==root/'BambuPlateStudio.py' and getattr(m,'controller',None)]
    assert len(addons)==1
    addon=addons[0];c=addon.controller;c.assert_document()
    output=root/'test_artifacts'/'document_roundtrip_02'
    output.mkdir(exist_ok=True)
    archive=output/'paper_box_print_rules.f3d'
    assert not archive.exists(),'Never overwrite a prior archive'
    c.dispatch('save_rules',{})
    baseline=json.loads(json.dumps(c.session.rules()))
    before={b.uid:b.fingerprint() for b in c.session.bodies.values()}
    geometry={b.uid:b.geometry_key() for b in c.session.bodies.values()}
    exporter=c.source.design.exportManager
    assert exporter.execute(exporter.createFusionArchiveExportOptions(str(archive)))
    assert archive.exists() and archive.stat().st_size>0
    imported=None
    report={'archive':str(archive),'sourceDocumentLeftOpen':True,'passed':False}
    try:
        imported=app.importManager.importToNewDocument(
            app.importManager.createFusionArchiveImportOptions(str(archive)))
        assert imported and imported!=source_doc
        restored=type(c)()
        restored.scan();restored.update_bed()
        aliases=restored.source.aliases_for(baseline)
        remap=lambda uid:aliases.get(uid,uid)
        report.update(bodies=len(restored.session.bodies),units=len(restored.session.units),
                      plates=len(restored.session.plates),resolvedAliases=len(aliases),
                      notices=restored.notices,errors=restored.state()['errors'])
        assert len(restored.session.bodies)==len(before),report
        assert {remap(uid):h for uid,h in geometry.items()}=={
            b.uid:b.geometry_key() for b in restored.session.bodies.values()},'Reopened geometry differs'
        report['exactOrderIndependentGeometryEqual']=True
        expected_units=[dict(u,members=[remap(uid) for uid in u['members']]) for u in baseline['units']]
        actual=json.loads(json.dumps(restored.session.rules()))
        assert actual['units']==expected_units,('units',actual['units'],expected_units)
        assert actual['placements']==baseline['placements'],'Saved positions did not restore'
        assert actual['plates']==baseline['plates'],'Saved plate tree did not restore'
        assert actual['config']==baseline['config'],'Saved print configuration did not restore'
        assert actual['colorProfiles']==baseline['colorProfiles'],'Saved materials did not restore'
        assert not report['errors'],report
        report['passed']=True
    finally:
        # Only close the transient document created by this test, never source_doc.
        if imported and imported.isValid and imported!=source_doc:
            imported.close(False)
        source_doc.activate()
        c.assert_document()
        current=type(c.source)(source_doc).scan(c.session.config['includeHidden'],c.session.config['refinement'])
        report['sourceGeometryUnchanged']={b.uid:b.fingerprint() for b in current}==before
        (output/'roundtrip.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        addon.emit_state()
    assert report['sourceGeometryUnchanged']
    print(json.dumps(report,ensure_ascii=False))
