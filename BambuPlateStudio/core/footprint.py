"""Exact 2D mesh-footprint spacing for non-rectangular print units."""
import math


def project_unit(session, placement):
    matrix=session.units[placement.unit].matrix(session.bodies,placement)
    result=[]
    for member in session.units[placement.unit].members:
        body=session.bodies[member]
        points=[(sum(matrix[0][i]*v[i] for i in range(3))+matrix[0][3],
                 sum(matrix[1][i]*v[i] for i in range(3))+matrix[1][3]) for v in body.vertices]
        for indices in body.triangles:
            triangle=tuple(points[i] for i in indices)
            xs=[p[0] for p in triangle];ys=[p[1] for p in triangle]
            result.append(((min(xs),min(ys),max(xs),max(ys)),triangle))
    return result


def cross(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def on_segment(p,a,b):
    return (min(a[0],b[0])-1e-9<=p[0]<=max(a[0],b[0])+1e-9 and
            min(a[1],b[1])-1e-9<=p[1]<=max(a[1],b[1])+1e-9)


def segments_intersect(a,b,c,d):
    ab_c,ab_d=cross(a,b,c),cross(a,b,d)
    cd_a,cd_b=cross(c,d,a),cross(c,d,b)
    if (ab_c>1e-9 and ab_d<-1e-9 or ab_c<-1e-9 and ab_d>1e-9) and \
       (cd_a>1e-9 and cd_b<-1e-9 or cd_a<-1e-9 and cd_b>1e-9):return True
    return (abs(ab_c)<=1e-9 and on_segment(c,a,b) or
            abs(ab_d)<=1e-9 and on_segment(d,a,b) or
            abs(cd_a)<=1e-9 and on_segment(a,c,d) or
            abs(cd_b)<=1e-9 and on_segment(b,c,d))


def inside(p,triangle):
    a,b,c=triangle
    if abs(cross(a,b,c))<=1e-9:return False
    values=(cross(a,b,p),cross(b,c,p),cross(c,a,p))
    return min(values)>=-1e-9 or max(values)<=1e-9


def point_segment_sq(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    length=dx*dx+dy*dy
    t=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length)) if length else 0.
    x,y=a[0]+t*dx,a[1]+t*dy
    return (p[0]-x)**2+(p[1]-y)**2


def triangle_distance_sq(first,second):
    if any(inside(p,second) for p in first) or any(inside(p,first) for p in second):return 0.
    edges_a=((first[i],first[(i+1)%3]) for i in range(3))
    edges_b=tuple((second[i],second[(i+1)%3]) for i in range(3))
    minimum=float('inf')
    for a,b in edges_a:
        for c,d in edges_b:
            if segments_intersect(a,b,c,d):return 0.
            minimum=min(minimum,point_segment_sq(a,c,d),point_segment_sq(b,c,d),
                        point_segment_sq(c,a,b),point_segment_sq(d,a,b))
    return minimum


def footprints_clearance(first,second,gap):
    """Return one witnessed sub-gap mesh distance, or None when silhouettes satisfy gap."""
    cell=max(5.,gap)
    bins={}
    for index,(box,_) in enumerate(second):
        x0=math.floor((box[0]-gap)/cell);x1=math.floor((box[2]+gap)/cell)
        y0=math.floor((box[1]-gap)/cell);y1=math.floor((box[3]+gap)/cell)
        for x in range(x0,x1+1):
            for y in range(y0,y1+1):bins.setdefault((x,y),[]).append(index)
    for box,triangle in first:
        candidates=set()
        for x in range(math.floor(box[0]/cell),math.floor(box[2]/cell)+1):
            for y in range(math.floor(box[1]/cell),math.floor(box[3]/cell)+1):
                candidates.update(bins.get((x,y),()))
        for index in candidates:
            other,points=second[index]
            if (box[0]>other[2]+gap or other[0]>box[2]+gap or
                box[1]>other[3]+gap or other[1]>box[3]+gap):continue
            distance_sq=triangle_distance_sq(triangle,points)
            if distance_sq<=1e-18:return 0.
            if gap>1e-3 and distance_sq<(gap-1e-3)**2:return math.sqrt(distance_sq)
    return None


def footprints_near(first,second,gap):
    return footprints_clearance(first,second,gap) is not None
