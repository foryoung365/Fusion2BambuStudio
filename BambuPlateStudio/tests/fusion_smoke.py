"""Run in Fusion on the explicitly opened local, unsaved tissue-box test copy."""
import json
from pathlib import Path
import adsk.core
from BambuPlateStudio import BambuPlateStudio as addon


def run(context):
    controller = addon.controller
    if controller is None:
        raise RuntimeError('Load the add-in before this integration test.')
    doc = adsk.core.Application.get().activeDocument
    assert doc is not None and doc.dataFile is None, 'Use the isolated unsaved test document only'
    if not controller.source:
        controller.scan()
    session = controller.session
    before = {uid: b.fingerprint() for uid, b in session.bodies.items()}
    assert len(before) == 27
    names = {'外框2','外框3','外框4','外框5','外框6','底板框架'}
    ids = [u.uid for u in session.units.values() if u.name in names]
    assert len(ids) == 6
    controller.dispatch('group', {'units': ids, 'name': '顶盖五层与框架（整体）'})
    group = next(u for u in session.units.values() if len(u.members) == 6)
    controller.dispatch('direction', {'unit': group.uid, 'mode': 'top'})
    chest = next(u for u in session.units.values() if u.name == '右胸')
    controller.dispatch('direction', {'unit': chest.uid, 'mode': 'top'})
    controller.dispatch('config', {'enableSupport': True})
    state = controller.dispatch('arrange', {})
    assert not state['errors']
    controller.dispatch('save_rules', {})
    path = Path('I:/3DPrint/BambuPlateStudio/test_artifacts/fusion_paper_petg.3mf')
    report = controller.export_to(str(path))
    assert {uid: b.fingerprint() for uid, b in session.bodies.items()} == before
    assert len(session.units) == 22
    p = adsk.core.Application.get().userInterface.palettes.itemById(addon.PALETTE)
    p.sendInfoToHTML('state', json.dumps(controller.state(True), ensure_ascii=False))
    report['testDocument'] = doc.name
    report['sourceGeometryUnchanged'] = True
    report['guiInspectionImmediate'] = p.sendInfoToHTML('inspect', '{}')
    report['eventLog'] = addon.event_log[-10:]
    (path.parent/'fusion_smoke_result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'path':str(path),'bodies':report['bodies'],'objects':report['objects'],
                      'plates':report['plates'],'warnings':report['warnings'],
                      'sourceGeometryUnchanged':True,'events':addon.event_log[-5:]}))
