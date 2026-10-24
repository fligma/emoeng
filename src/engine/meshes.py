"""Runtime geometry: small builders that emit interleaved-ready vertex
arrays (pos, normal, uv, colour) plus a triangle index list. Props are
assembled here and merged into a handful of big meshes so a whole level
costs a handful of draw calls.

All builders work in world space already (they take a centre + rotation),
so merging is just concatenation. Loaded .model files go through
engine.model, which flattens them into the same MeshData soup.

Copied from the app's src/core/meshes.py so fligengine stays self-contained.
"""

import math

import numpy as np


class MeshData:
    def __init__(self):
        self.pos = []      # (x, y, z)
        self.nrm = []
        self.uv = []
        self.col = []      # rgb 0..1, modulates the texture
        self.idx = []

    @property
    def empty(self):
        return not self.idx

    def vert(self, p, n, uv, col):
        self.pos.append(p)
        self.nrm.append(n)
        self.uv.append(uv)
        self.col.append(col)
        return len(self.pos) - 1

    def tri(self, a, b, c):
        self.idx += [a, b, c]

    def quad(self, a, b, c, d, n, col, uvs=None, flip=False):
        if uvs is None:
            uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
        va = self.vert(a, n, uvs[0], col)
        vb = self.vert(b, n, uvs[1], col)
        vc = self.vert(c, n, uvs[2], col)
        vd = self.vert(d, n, uvs[3], col)
        if flip:
            self.quad_idx(va, vb, vc, vd, reverse=True)
        else:
            self.quad_idx(va, vb, vc, vd)

    def quad_idx(self, a, b, c, d, reverse=False):
        if reverse:
            self.tri(d, c, b)
            self.tri(d, b, a)
        else:
            self.tri(a, b, c)
            self.tri(a, c, d)

    def append(self, other):
        base = len(self.pos)
        self.pos += other.pos
        self.nrm += other.nrm
        self.uv += other.uv
        self.col += other.col
        self.idx += [i + base for i in other.idx]
        return self

    def bounds(self):
        """(min, max) corner tuples; None for an empty mesh."""
        if not self.pos:
            return None
        xs = [p[0] for p in self.pos]
        ys = [p[1] for p in self.pos]
        zs = [p[2] for p in self.pos]
        return ((min(xs), min(ys), min(zs)),
                (max(xs), max(ys), max(zs)))

    def arrays(self):
        return (np.array(self.pos, np.float32),
                np.array(self.nrm, np.float32),
                np.array(self.uv, np.float32),
                np.array(self.col, np.float32),
                np.array(self.idx, np.uint32))


def _rot_y(p, a):
    c, s = math.cos(a), math.sin(a)
    return (c * p[0] + s * p[2], p[1], -s * p[0] + c * p[2])


def _rot_lean(p, lean):
    """Rotate about the Z axis (tips a Y-up shape toward +X)."""
    c, s = math.cos(lean), math.sin(lean)
    return (c * p[0] - s * p[1], s * p[0] + c * p[1], p[2])


def _xf(p, lean, yaw, centre, scale):
    x, y, z = p[0] * scale[0], p[1] * scale[1], p[2] * scale[2]
    x, y, z = _rot_lean((x, y, z), lean)
    x, y, z = _rot_y((x, y, z), yaw)
    return (x + centre[0], y + centre[1], z + centre[2])


def box(centre=(0, 0, 0), size=(1, 1, 1), yaw=0.0, col=(1, 1, 1),
        uv=(1, 1), lean=0.0):
    """Axis-aligned-ish cuboid; faces wound counter-clockwise seen from
    outside, so the renderer can cull backfaces."""
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    v = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
         (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    v = [_xf(p, lean, yaw, centre, (1, 1, 1)) for p in v]
    m = MeshData()
    uvs = ((0, 0), (uv[0], 0), (uv[0], uv[1]), (0, uv[1]))
    faces = [((4, 5, 6, 7), (0, 0, 1)),    # +z
             ((1, 0, 3, 2), (0, 0, -1)),   # -z
             ((5, 1, 2, 6), (1, 0, 0)),    # +x
             ((0, 4, 7, 3), (-1, 0, 0)),   # -x
             ((7, 6, 2, 3), (0, 1, 0)),    # +y
             ((0, 1, 5, 4), (0, -1, 0))]   # -y
    for (a, b, c, d), n in faces:
        m.quad(v[a], v[b], v[c], v[d], n, col, uvs)
    return m


def cylinder(centre=(0, 0, 0), r=0.5, h=1.0, seg=10, col=(1, 1, 1),
             yaw=0.0, lean=0.0, capped=True, uv=(1, 1), taper=1.0):
    """Y-up cylinder centred on `centre`; taper < 1 makes a cone-ish trunk.
    `lean` tips the whole shape sideways before yaw, so lying logs are
    cylinder(lean=pi/2)."""
    m = MeshData()
    lo, hi = -h / 2, h / 2
    r_lo, r_hi = r, r * taper
    ring_lo, ring_hi = [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        ca, sa = math.cos(a), math.sin(a)
        ring_lo.append(_xf((ca * r_lo, lo, sa * r_lo), lean, yaw, centre,
                           (1, 1, 1)))
        ring_hi.append(_xf((ca * r_hi, hi, sa * r_hi), lean, yaw, centre,
                           (1, 1, 1)))
        nrm = _rot_y((ca, 0, sa), 0)
        nrm = _rot_lean(nrm, lean)
        nrm = _rot_y(nrm, yaw)
        if i:
            a0, a1 = ring_lo[i - 1], ring_lo[i]
            b0, b1 = ring_hi[i - 1], ring_hi[i]
            u0, u1 = uv[0] * (i - 1) / seg, uv[0] * i / seg
            # wound a0 -> b0 -> b1 -> a1 so the face normal points away
            # from the axis (the renderer culls what winds clockwise)
            m.quad(a0, b0, b1, a1, nrm, col,
                   ((u0, 0), (u0, uv[1]), (u1, uv[1]), (u1, 0)))
    if seg > 1:
        a0, a1 = ring_lo[-1], ring_lo[0]
        b0, b1 = ring_hi[-1], ring_hi[0]
        nrm = _rot_y(_rot_lean((math.cos(0), 0, math.sin(0)), lean), yaw)
        m.quad(a0, b0, b1, a1, col=col, n=nrm,
               uvs=((uv[0], 0), (uv[0], uv[1]), (0, uv[1]), (0, 0)))
    if capped:
        top_c = _xf((0, hi, 0), lean, yaw, centre, (1, 1, 1))
        n_top = _rot_y(_rot_lean((0, 1, 0), lean), yaw)
        for i in range(seg):
            j = (i + 1) % seg
            ua = 2 * math.pi * i / seg
            ub = 2 * math.pi * j / seg
            m.tri(m.vert(ring_hi[i], n_top,
                         (0.5 + 0.5 * math.cos(ua), 0.5 + 0.5 * math.sin(ua)),
                         col),
                  m.vert(top_c, n_top, (0.5, 0.5), col),
                  m.vert(ring_hi[j], n_top,
                         (0.5 + 0.5 * math.cos(ub),
                          0.5 + 0.5 * math.sin(ub)), col))
    return m


def cone(centre=(0, 0, 0), r=1.0, h=1.5, seg=9, col=(1, 1, 1), yaw=0.0,
         uv=(1, 1)):
    """Pyramid-ish canopy tier: base ring at centre.y, apex above it."""
    return cylinder(centre=centre, r=r, h=h, seg=seg, col=col, yaw=yaw,
                    capped=True, uv=uv, taper=0.02)


def plane(centre=(0, 0, 0), size=(50, 50), seg=32, height_fn=lambda x, z: 0.0,
          color_fn=lambda x, z, h: (1, 1, 1), uv_scale=8.0):
    """XZ grid deformed by height_fn; normals from finite differences."""
    m = MeshData()
    w, d = size[0], size[1]
    nx, nz = seg + 1, seg + 1
    grid = []
    for iz in range(nz):
        row = []
        for ix in range(nx):
            x = centre[0] - w / 2 + w * ix / seg
            z = centre[2] - d / 2 + d * iz / seg
            y = centre[1] + height_fn(x, z)
            e = 0.6
            hx = height_fn(x + e, z) - height_fn(x - e, z)
            hz = height_fn(x, z + e) - height_fn(x, z - e)
            nl = math.sqrt(hx * hx + 1.0 + hz * hz)
            n = (hx / nl, 1.0 / nl, hz / nl)
            row.append(m.vert((x, y, z), n,
                              ((x - centre[0]) / w * uv_scale + 0.5,
                               (z - centre[2]) / d * uv_scale + 0.5),
                              color_fn(x, z, y - centre[1])))
        grid.append(row)
    for iz in range(seg):
        for ix in range(seg):
            a = grid[iz][ix]
            b = grid[iz][ix + 1]
            c = grid[iz + 1][ix + 1]
            d0 = grid[iz + 1][ix]
            # counter-clockwise seen from above, matching the +Y normals
            m.tri(a, d0, b)
            m.tri(b, d0, c)
    return m


def tile_plane(centre=(0, 0, 0), size=(50, 50), seg=32,
               height_fn=lambda x, z: 0.0,
               color_fn=lambda x, z, h: (1, 1, 1),
               tile_fn=lambda ix, iz: (0, 0), cols=8, rows=16):
    """XZ grid of independent quads, each sampling one cell of a
    cols x rows sprite sheet: tile_fn(ix, iz) picks the (column, row)
    from the top-left of the sheet. Per-quad vertices let every tile
    carry its own colour and UV window - one draw call, whole-terrain
    texture variation. Half-texel inset keeps neighbouring tiles from
    bleeding across the seams."""
    m = MeshData()
    w, d = size[0], size[1]
    sx, sz = w / seg, d / seg
    eu = 0.5 / (cols * 64.0)                 # half texel in sheet space
    ev = 0.5 / (rows * 64.0)
    x00 = centre[0] - w / 2
    z00 = centre[2] - d / 2
    for iz in range(seg):
        for ix in range(seg):
            x0, z0 = x00 + ix * sx, z00 + iz * sz
            cx, cz = x0 + sx / 2, z0 + sz / 2
            p00 = (x0, centre[1] + height_fn(x0, z0), z0)
            p10 = (x0 + sx, centre[1] + height_fn(x0 + sx, z0), z0)
            p11 = (x0 + sx, centre[1] + height_fn(x0 + sx, z0 + sz), z0 + sz)
            p01 = (x0, centre[1] + height_fn(x0, z0 + sz), z0 + sz)
            e1 = (p10[0] - p00[0], p10[1] - p00[1], p10[2] - p00[2])
            e2 = (p01[0] - p00[0], p01[1] - p00[1], p01[2] - p00[2])
            # e2 x e1 points up for a flat XZ grid
            n = (e2[1] * e1[2] - e2[2] * e1[1],
                 e2[2] * e1[0] - e2[0] * e1[2],
                 e2[0] * e1[1] - e2[1] * e1[0])
            nl = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
            n = tuple(v / nl for v in n)
            col = color_fn(cx, cz, (p00[1] + p11[1]) / 2 - centre[1])
            tc, tr = tile_fn(ix, iz)
            u0 = (tc + eu) / cols
            u1 = (tc + 1.0 - eu) / cols
            # sheet row 0 is at the top of the file; the renderer flips
            # textures on upload, so count rows down from v = 1
            v1 = 1.0 - (tr + ev) / rows
            v0 = 1.0 - (tr + 1.0 - ev) / rows
            m.quad(p00, p01, p11, p10, n, col,
                   ((u0, v0), (u0, v1), (u1, v1), (u1, v0)))
    return m


def face_auto(md, pts, col, uvs=None, outward=None):
    """Add a 3- or 4-point polygon, computing the normal from the winding
    and re-orienting it to face away from `outward` (a reference point,
    usually the enclosing object's centre), so callers need not think
    about vertex order."""
    a, b, c = pts[0], pts[1], pts[2]
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
         u[0] * v[1] - u[1] * v[0])
    ln = math.sqrt(sum(x * x for x in n)) or 1.0
    n = tuple(x / ln for x in n)
    if outward is not None:
        mx = sum(p[0] for p in pts) / len(pts) - outward[0]
        my = sum(p[1] for p in pts) / len(pts) - outward[1]
        mz = sum(p[2] for p in pts) / len(pts) - outward[2]
        if n[0] * mx + n[1] * my + n[2] * mz < 0:
            pts = list(reversed(pts))
            n = tuple(-x for x in n)
    if len(pts) == 3:
        uvs = uvs or ((0, 0), (1, 0), (1, 1))
        va = md.vert(pts[0], n, uvs[0], col)
        vb = md.vert(pts[1], n, uvs[1], col)
        vc = md.vert(pts[2], n, uvs[2], col)
        md.tri(va, vb, vc)
    else:
        if uvs is None:
            uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
        md.quad(pts[0], pts[1], pts[2], pts[3], n, col, uvs)


def billboards(centre, w, h, count=3, col=(1, 1, 1)):
    """Crossed camera-facing quads for flames / glows (yaw-only fake)."""
    m = MeshData()
    uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
    for i in range(count):
        yaw = math.pi * i / count
        pts = [
            _xf((-w / 2, -h / 2, 0), 0, yaw, centre, (1, 1, 1)),
            _xf((w / 2, -h / 2, 0), 0, yaw, centre, (1, 1, 1)),
            _xf((w / 2, h / 2, 0), 0, yaw, centre, (1, 1, 1)),
            _xf((-w / 2, h / 2, 0), 0, yaw, centre, (1, 1, 1)),
        ]
        # double-sided: two windings, normals ignored in the add pass
        for flip in (False, True):
            a, b, c, d = pts
            va = m.vert(b if flip else a, (0, 0, 1), uvs[1 if flip else 0],
                        col)
            vb = m.vert(a if flip else b, (0, 0, 1), uvs[0 if flip else 1],
                        col)
            vc = m.vert(d if flip else c, (0, 0, 1), uvs[3 if flip else 2],
                        col)
            vd = m.vert(c if flip else d, (0, 0, 1), uvs[2 if flip else 3],
                        col)
            m.tri(va, vb, vc)
            m.tri(va, vc, vd)
    return m
