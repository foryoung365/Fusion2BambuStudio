"""Millimetres throughout. Proper rotations only; never repair or merge meshes."""
import math
from collections import Counter


IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def unit(v):
    n = math.sqrt(dot(v, v))
    if not math.isfinite(n) or n < 1e-12:
        raise ValueError('方向向量无效。')
    return tuple(x/n for x in v)


def multiply(a, b):
    return tuple(tuple(sum(a[r][k]*b[k][c] for k in range(len(b)))
                       for c in range(len(b[0]))) for r in range(len(a)))


def rotate(rotation, point):
    return tuple(dot(row, point) for row in rotation)


def validate_rotation(rotation):
    if len(rotation) != 3 or any(len(row) != 3 for row in rotation):
        raise ValueError('打印方向矩阵必须为 3 × 3。')
    if any(not math.isfinite(v) for row in rotation for v in row):
        raise ValueError('打印方向矩阵含无效数值。')
    if any(abs(dot(rotation[r], rotation[c])-(1 if r == c else 0)) > 1e-7
           for r in range(3) for c in range(3)) or abs(dot(rotation[0], cross(rotation[1], rotation[2]))-1) > 1e-7:
        raise ValueError('打印方向必须是刚体旋转，不能缩放、剪切或镜像。')


def axis_rotation(axis, degrees):
    x, y, z = unit(axis)
    angle = math.radians(degrees)
    c, s, t = math.cos(angle), math.sin(angle), 1-math.cos(angle)
    return ((t*x*x+c, t*x*y-s*z, t*x*z+s*y),
            (t*x*y+s*z, t*y*y+c, t*y*z-s*x),
            (t*x*z-s*y, t*y*z+s*x, t*z*z+c))


def face_down(normal):
    """Map the selected outward face normal to -Z, without reflection."""
    n, target = unit(normal), (0., 0., -1.)
    cosine = max(-1., min(1., dot(n, target)))
    if cosine > 1-1e-10:
        return IDENTITY
    if cosine < -1+1e-10:
        return axis_rotation((1, 0, 0), 180)
    return axis_rotation(cross(n, target), math.degrees(math.acos(cosine)))


def bounds(points):
    points = list(points)
    if not points:
        raise ValueError('网格没有顶点。')
    return (tuple(min(p[i] for p in points) for i in range(3)),
            tuple(max(p[i] for p in points) for i in range(3)))


def transform_point(matrix, point):
    return tuple(dot(matrix[i][:3], point)+matrix[i][3] for i in range(3))


def affine(rotation, translation):
    return tuple(tuple(rotation[i])+tuple([translation[i]]) for i in range(3))+((0., 0., 0., 1.),)


def encode_3mf(matrix):
    return ' '.join(format(matrix[r][c], '.17g') for c in range(4) for r in range(3))


def signed_volume(vertices, triangles):
    center = vertices[0]
    total = 0.
    for indices in triangles:
        a, b, c = [tuple(vertices[j][k]-center[k] for k in range(3)) for j in indices]
        total += dot(a, cross(b, c))/6
    return total


def mesh_issues(vertices, triangles):
    """Report original topology. This function never changes the input arrays."""
    if not vertices or not triangles:
        raise ValueError('网格为空。')
    if any(len(p) != 3 or not all(math.isfinite(x) for x in p) for p in vertices):
        raise ValueError('网格包含无效坐标。')
    # Coordinate welding is for counting only; exported vertices stay untouched.
    keys = [tuple(round(x, 6) for x in v) for v in vertices]
    edges, degenerate = Counter(), 0
    for tri in triangles:
        if len(tri) != 3 or any(not isinstance(i, int) or i < 0 or i >= len(vertices) for i in tri):
            raise ValueError('三角形索引无效。')
        a, b, c = [vertices[i] for i in tri]
        n = cross(tuple(b[i]-a[i] for i in range(3)), tuple(c[i]-a[i] for i in range(3)))
        degenerate += dot(n, n) < 1e-16
        for i, j in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edges[tuple(sorted((keys[i], keys[j])))] += 1
    return {'boundaryEdges': sum(n == 1 for n in edges.values()),
            'nonManifoldEdges': sum(n > 2 for n in edges.values()),
            'degenerateTriangles': degenerate,
            'signedVolumeMm3': signed_volume(vertices, triangles)}


def rectangle_overlap(a, b, gap=0.):
    return (a[0] < b[0]+b[2]+gap-1e-7 and b[0] < a[0]+a[2]+gap-1e-7 and
            a[1] < b[1]+b[3]+gap-1e-7 and b[1] < a[1]+a[3]+gap-1e-7)
