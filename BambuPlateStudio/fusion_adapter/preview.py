"""Transient mesh preview in Fusion's viewport, separate from original B-Rep bodies."""
import adsk.core
import adsk.fusion
from ..core.geometry import transform_point
from ..core.layout import scene_origin


def effect(hex_color):
    values=[int(hex_color[i:i+2],16) for i in (1,3,5)]
    return adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(*values,255))


def draw(controller, plate_index=None):
    controller.assert_document()
    if not controller.session.placements:
        raise ValueError('请先完成排盘。')
    controller.clear_preview()
    session,bed=controller.session,controller.bed
    group=controller.source.design.rootComponent.customGraphicsGroups.add()
    controller.preview_group=group
    shift=400.  # Millimetres away from the original assembly; not a model transform.
    selected=[p for p in session.plates if plate_index is None or p.index==plate_index]
    if not selected:
        raise ValueError('指定打印盘不存在。')
    for n,plate in enumerate(selected):
        origin=scene_origin(n+1,len(selected),bed)
        x,y=origin[0]+shift+bed.origin_x,origin[1]+bed.origin_y
        corners=[(x,y,-.1),(x+bed.width,y,-.1),(x+bed.width,y+bed.depth,-.1),(x,y+bed.depth,-.1)]
        coords=adsk.fusion.CustomGraphicsCoordinates.create([v/10 for p in corners for v in p])
        platform=group.addMesh(coords,[0,1,2,0,2,3],[],[])
        platform.color=effect('#DCE8E2');platform.isSelectable=False
        border=group.addLines(coords,[0,1,2,3,0],True)
        border.color=effect('#557A67');border.isSelectable=False
        for uid,placement in session.placements.items():
            if placement.plate!=plate.index:continue
            unit=session.units[uid]
            matrix=unit.matrix(session.bodies,placement,(origin[0]+shift,origin[1]))
            for member in unit.members:
                body=session.bodies[member]
                vertices=[transform_point(matrix,v) for v in body.vertices]
                coords=adsk.fusion.CustomGraphicsCoordinates.create([value/10 for point in vertices for value in point])
                mesh=group.addMesh(coords,[i for triangle in body.triangles for i in triangle],[],[])
                mesh.color=effect(session.effective_color(member));mesh.isSelectable=False
    controller.app.activeViewport.fit()
    return {'previewPlates':[p.index for p in selected],'sourceGeometryModified':False}
