"""Read-only comparison of source and reopened local archive tessellations."""
import json
import sys
from pathlib import Path
import adsk.core
from BambuPlateStudio.core.geometry import bounds,signed_volume
from BambuPlateStudio.core.bambu_validation import nearest_error


def run(context):
    app=adsk.core.Application.get();doc=app.activeDocument
    root=Path('I:/3DPrint/BambuPlateStudio').resolve()
    addon=next(m for m in list(sys.modules.values()) if getattr(m,'__file__',None)
               and Path(m.__file__).resolve()==root/'BambuPlateStudio.py' and getattr(m,'controller',None))
    c=addon.controller;c.assert_document();old=c.session
    imported=None;report=[]
    try:
        imported=app.importManager.importToNewDocument(app.importManager.createFusionArchiveImportOptions(
            str(root/'test_artifacts/document_roundtrip_01/paper_box_print_rules.f3d')))
        source=type(c.source)(imported)
        bodies={b.uid:b for b in source.scan(old.config['includeHidden'],old.config['refinement'])}
        aliases=source.aliases_for(old.rules())
        for uid,a in old.bodies.items():
            b=bodies[aliases[uid]]
            def vertex_set(body):return sorted(tuple(round(v,6) for v in p) for p in body.vertices)
            def triangles(body):
                result=[]
                for tri in body.triangles:
                    p=tuple(tuple(round(v,6) for v in body.vertices[i]) for i in tri)
                    result.append(min(p,p[1:]+p[:1],p[2:]+p[:2]))
                return sorted(result)
            same_vertices=vertex_set(a)==vertex_set(b)
            report.append({'name':a.name,'fingerprintEqual':a.fingerprint()==b.fingerprint(),
                'vertexCounts':[len(a.vertices),len(b.vertices)],'triangleCounts':[len(a.triangles),len(b.triangles)],
                'canonicalVerticesEqual':same_vertices,'canonicalTrianglesEqual':triangles(a)==triangles(b),
                'nearestVertexErrorMm':max(nearest_error(a.vertices,b.vertices),nearest_error(b.vertices,a.vertices)),
                'bounds':[bounds(a.vertices),bounds(b.vertices)],'colorEqual':a.color==b.color,
                'faceColorsEqual':a.face_colors==b.face_colors,
                'faceAreas':[a.face_colors,b.face_colors],
                'volumes':[signed_volume(a.vertices,a.triangles),signed_volume(b.vertices,b.triangles)]})
    finally:
        if imported and imported.isValid and imported!=doc:imported.close(False)
        doc.activate()
    path=root/'test_artifacts/document_roundtrip_01/diagnosis.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in row.items() if k not in ('bounds','faceAreas','volumes')} for row in report],ensure_ascii=False))
