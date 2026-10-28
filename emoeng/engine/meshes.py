"""Runtime geometry: builders that emit interleaved-ready vertex"""

import math

import numpy as np

from . import colors


def rgba(col):
    """A vertex colour as (r, g, b, a)."""
    if isinstance(col, str):
        col = colors.rgb(col, (1.0, 1.0, 1.0))
    col = tuple(float(c) for c in col)
    if len(col) >= 4:
        return col[:4]
    if len(col) == 3:
        return col + (1.0,)
    return tuple(col) + (1.0,) * (4 - len(col))


def _reuv(data, uv):
    """A twin of `data` sharing its geometry but carrying new uv."""
    out = MeshData()
    out.pos, out.nrm, out.col, out.idx, out.tex = (data.pos, data.nrm,
                                                   data.col, data.idx,
                                                   data.tex)
    out.uv2, out.lightmap = data.uv2, data.lightmap
    out.lms = data.lms
    out.uv = uv
    return out


def _wraps(nrm):
    """True when the sides turn all the way round, so a box map smears."""
    nrm = np.asarray(nrm, np.float64)
    sides = nrm[np.abs(nrm[:, 1]) < 0.7] if len(nrm) else nrm
    if len(sides) < 12:
        return False
    turn = np.arctan2(sides[:, 2], sides[:, 0])
    return len(np.unique(np.round(turn / (math.pi / 12)))) >= 8


def mesh_anchor(data):
    """The point a metre sheet should be pinned to for this mesh."""
    if not data.pos:
        return None
    pos = np.asarray(data.pos, np.float64)
    return tuple((pos.min(axis=0) + pos.max(axis=0)) * 0.5)


def _turn(vec, angle):
    """Points or normals spun about Y, the way a body spins its surface."""
    vec = np.asarray(vec, np.float64)
    if not len(vec) or abs(angle) < 1e-9:
        return vec
    c, s = math.cos(angle), math.sin(angle)
    out = vec.copy()
    x, z = vec[:, 0], vec[:, 2]
    out[:, 0] = c * x + s * z
    out[:, 2] = -s * x + c * z
    return out


def _unpin(anchor):
    """An anchor as ((x, y, z), yaw): a sheet's zero and its turn."""
    row = list(anchor or ())
    yaw = float(row[3]) if len(row) > 3 else 0.0
    return (row[0], row[1], row[2]), yaw


def frame_pin(pos, yaw=0.0):
    """A body's sheet pin: where it stands and which way it faces."""
    point = [float(c) for c in pos][:3]
    while len(point) < 3:
        point.append(0.0)
    return tuple(point) + (float(yaw or 0.0),)


def slide_pin(pin, off):
    """A sheet pin moved with its body; its turn is kept."""
    point, yaw = _unpin(pin)
    step = list(off) + [0.0] * (3 - len(off))
    return tuple(point[k] + float(step[k]) for k in range(3)) + (yaw,)


def tile_world(data, metres, anchor=None):
    """Re-unwrap a mesh so its sheet repeats every `metres`.

    `anchor` is the metre zero of the sheet, optionally its turn: `(x, y,
    z, yaw)`. Left unset it is the mesh's own middle, which is right for
    one still mesh and wrong for a moving one - a fresh middle per pose
    slides the picture under the geometry. A caller that reshapes or
    drags a mesh keeps the pin it first had, and a body that turns
    measures its sheet in its own axes, so the picture rides the surface
    instead of swimming across it.
    """
    metres = float(metres or 0.0)
    if metres <= 0.0 or not data.pos:
        return data
    pos = np.asarray(data.pos, np.float64)
    nrm = np.asarray(data.nrm, np.float64)
    if anchor is None:
        anchor = mesh_anchor(data)
    point, yaw = _unpin(anchor)
    pos = pos - np.asarray(point, np.float64)
    if yaw:
        # undo the body's turn about its own pin: the unwrap is written in
        # the body's axes, so a turning body carries its picture round
        pos = _turn(pos, -yaw)
        nrm = _turn(nrm, -yaw)
    round_side = _wraps(nrm)     # read on the signed normals: which way
    nrm = np.abs(nrm)            # each face looks, and how far round they go
    ax, ay, az = nrm[:, 0], nrm[:, 1], nrm[:, 2]
    flat = (ay >= ax) & (ay >= az)      # a floor or a lid: across XZ
    wide = (~flat) & (ax >= az)         # a side face: across YZ
    u = np.where(flat, pos[:, 0], np.where(wide, pos[:, 2], pos[:, 0]))
    v = np.where(flat, pos[:, 2], pos[:, 1])
    if round_side:
        # a round side keeps its own seam: run u along the arc it covers
        side = np.abs(nrm[:, 1]) < 0.7
        arc = np.asarray(data.uv, np.float64)[:, 0] * 2.0 * math.pi * \
            np.hypot(pos[:, 0], pos[:, 2])
        u = np.where(side, arc, u)
    return _reuv(data, (np.stack([u, v], axis=1) / metres).tolist())


def uv_fit(data, tile=0.0, scale=(1.0, 1.0), offset=(0.0, 0.0),
           spin=0.0, anchor=None):
    """Tile a mesh by the metre, then scale, turn and slide its uv."""
    metres = float(tile or 0.0)
    if metres > 0.0:
        data = tile_world(data, metres, anchor)
    sx, sy = float(scale[0]), float(scale[1])
    ox, oy = float(offset[0]), float(offset[1])
    turn = float(spin or 0.0)
    still = (abs(sx - 1.0) < 1e-6 and abs(sy - 1.0) < 1e-6
             and abs(ox) < 1e-6 and abs(oy) < 1e-6 and abs(turn) < 1e-6)
    if still or not data.uv:
        return data
    uv = np.asarray(data.uv, np.float64)
    if turn:
        # tiled sheets turn about the origin, so repeats stay lined up
        mid = (np.zeros(2) if metres > 0.0
               else (uv.min(axis=0) + uv.max(axis=0)) * 0.5)
        c, s = math.cos(turn), math.sin(turn)
        d = uv - mid
        uv = np.stack([d[:, 0] * c - d[:, 1] * s,
                       d[:, 0] * s + d[:, 1] * c], axis=1) + mid
    return _reuv(data, (uv * np.array([sx, sy]) +
                        np.array([ox, oy])).tolist())


class MeshData:
    def __init__(self):
        self.pos = []      # (x, y, z)
        self.nrm = []
        self.uv = []
        self.uv2 = []      # a second uv per corner, for the lightmap and a
                           # painted atlas; empty means "reuse `uv`"
        self.col = []      # rgba 0..1, modulates the texture; a string is
                           # parsed as a colour spelling ("#rrggbb", "gold")
        self.idx = []
        self.tex = []      # one texture key per triangle, None = default
        self.lms = []      # one lightmap key per triangle, parallel to
                           # None inherits `lightmap`; an empty list inherits everywhere
        self.lightmap = None    # a baked-light texture key, or None

    @property
    def empty(self):
        return not self.idx

    def vert(self, p, n, uv, col, uv2=None):
        self.pos.append(p)
        self.nrm.append(n)
        self.uv.append(uv)
        if self.uv2 or uv2 is not None:
            # keep uv2 parallel to pos; new corners default to albedo
            self.uv2.append(uv2 if uv2 is not None else uv)
        self.col.append(rgba(col))
        return len(self.pos) - 1

    def tri(self, a, b, c, tex=None):
        self.idx += [a, b, c]
        self.tex.append(tex)

    def quad(self, a, b, c, d, n, col, uvs=None, flip=False, tex=None):
        if uvs is None:
            uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
        va = self.vert(a, n, uvs[0], col)
        vb = self.vert(b, n, uvs[1], col)
        vc = self.vert(c, n, uvs[2], col)
        vd = self.vert(d, n, uvs[3], col)
        if flip:
            self.quad_idx(va, vb, vc, vd, reverse=True, tex=tex)
        else:
            self.quad_idx(va, vb, vc, vd, tex=tex)

    def quad_idx(self, a, b, c, d, reverse=False, tex=None):
        if reverse:
            self.tri(d, c, b, tex)
            self.tri(d, b, a, tex)
        else:
            self.tri(a, b, c, tex)
            self.tri(a, c, d, tex)

    def align_tex(self):
        """Pad or trim per-face texture tags to the face count."""
        n = len(self.idx) // 3
        while len(self.tex) < n:
            self.tex.append(None)
        del self.tex[n:]
        return self

    def align_lms(self):
        """Trim per-face lightmap keys to the face count."""
        del self.lms[len(self.idx) // 3:]
        return self

    def texture_groups(self, default="white"):
        """Split into [(texture key, MeshData)], one piece per surface."""
        self.align_tex()
        eff = [lm or self.lightmap for lm in self.lms] + \
            [self.lightmap] * (len(self.idx) // 3 - len(self.lms))
        keys = set(zip(self.tex, eff))
        if len(keys) <= 1:
            key = next(iter(keys), (None, None))
            piece = MeshData()
            piece.pos, piece.nrm = self.pos, self.nrm
            piece.uv, piece.col = self.uv, self.col
            piece.uv2, piece.lightmap = self.uv2, key[1]
            piece.idx = self.idx
            return [(key[0] or default, piece)]
        keys, buckets, remaps = [], {}, []
        for k in range(len(self.idx) // 3):
            key = (self.tex[k] or default, eff[k])
            if key not in buckets:
                keys.append(key)
                buckets[key] = MeshData()
                remaps.append({})
            m, remap = buckets[key], remaps[keys.index(key)]
            m.lightmap = key[1]
            trio = []
            for vi in self.idx[3 * k:3 * k + 3]:
                if vi not in remap:
                    remap[vi] = m.vert(self.pos[vi], self.nrm[vi],
                                       self.uv[vi], self.col[vi],
                                       uv2=(self.uv2[vi]
                                            if vi < len(self.uv2)
                                            else None))
                trio.append(remap[vi])
            m.tri(trio[0], trio[1], trio[2], key[0] if key[0] != default
                  else None)
        return [(key[0], buckets[key]) for key in keys]

    def append(self, other):
        base = len(self.pos)
        # a merged uv2 borrows the albedo uv where missing
        mine = self.uv2 if len(self.uv2) == len(self.pos) else list(self.uv)
        theirs = (other.uv2 if len(other.uv2) == len(other.pos)
                  else list(other.uv))
        self.uv2 = mine + theirs if (self.uv2 or other.uv2) else []
        self.pos += other.pos
        self.nrm += other.nrm
        self.uv += other.uv
        self.col += other.col
        self.idx += [i + base for i in other.idx]
        self.align_tex()
        n = len(self.idx) // 3
        mine = list(self.lms) + [None] * (n - len(self.lms))
        self.tex += list(other.align_tex().tex)
        self.lms = mine + [lm or other.lightmap for lm in
                           list(other.align_lms().lms) +
                           [None] * (len(other.idx) // 3 -
                                     len(other.lms))]
        if self.lightmap is None:
            self.lightmap = other.lightmap
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
    """Rotate about Z, tipping a Y-up shape toward +X."""
    c, s = math.cos(lean), math.sin(lean)
    return (c * p[0] - s * p[1], s * p[0] + c * p[1], p[2])


def _xf(p, lean, yaw, centre, scale):
    x, y, z = p[0] * scale[0], p[1] * scale[1], p[2] * scale[2]
    x, y, z = _rot_lean((x, y, z), lean)
    x, y, z = _rot_y((x, y, z), yaw)
    return (x + centre[0], y + centre[1], z + centre[2])


def box(centre=(0, 0, 0), size=(1, 1, 1), yaw=0.0, col=(1, 1, 1),
        uv=(1, 1), lean=0.0):
    """Axis-aligned-ish cuboid; faces wound counter-clockwise seen from"""
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
        # the face normal is written in the body's axes, so it turns too -
        # a lit box that did not turn its normals would shade as it lay
        m.quad(v[a], v[b], v[c], v[d], _rot_y(_rot_lean(n, lean), yaw),
               col, uvs)
    return m


def cylinder(centre=(0, 0, 0), r=0.5, h=1.0, seg=10, col=(1, 1, 1),
             yaw=0.0, lean=0.0, capped=True, uv=(1, 1), taper=1.0):
    """A Y-up cylinder; taper below 1 narrows it."""
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
            # wound a0, b0, b1, a1 so the normal points out
            m.quad(a0, b0, b1, a1, nrm, col,
                   ((u0, 0), (u0, uv[1]), (u1, uv[1]), (u1, 0)))
    if seg > 1:
        a0, a1 = ring_lo[-1], ring_lo[0]
        b0, b1 = ring_hi[-1], ring_hi[0]
        nrm = _rot_y(_rot_lean((math.cos(0), 0, math.sin(0)), lean), yaw)
        # the closing quad runs on to u = uv[0], never back to 0: a repeat
        # sheet would otherwise squeeze a whole tile into one segment
        u_lo = uv[0] * (seg - 1) / seg
        m.quad(a0, b0, b1, a1, col=col, n=nrm,
               uvs=((u_lo, 0), (u_lo, uv[1]), (uv[0], uv[1]), (uv[0], 0)))
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
    """XZ grid of quads, each sampling one sheet cell."""
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
            # row 0 is top; count down from v = 1
            v1 = 1.0 - (tr + ev) / rows
            v0 = 1.0 - (tr + 1.0 - ev) / rows
            m.quad(p00, p01, p11, p10, n, col,
                   ((u0, v0), (u0, v1), (u1, v1), (u1, v0)))
    return m


def face_auto(md, pts, col, uvs=None, outward=None):
    """Add a 3- or 4-point polygon, normal from winding."""
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


def sprite_uv(col, row, cols, rows, pad=0.0):
    """(u0, v0, u1, v1) of one sheet cell."""
    e = float(pad)
    u0 = (col + e) / cols
    u1 = (col + 1.0 - e) / cols
    v0 = (row + e) / rows
    v1 = (row + 1.0 - e) / rows
    return (u0, v0, u1, v1)


def quad2d(pos, size, col=(1, 1, 1), uv=(0.0, 0.0, 1.0, 1.0), rot=0.0,
           layer=0.0, anchor=(0.5, 0.5)):
    """A screen-space quad for the 2D / UI pass."""
    w, h = float(size[0]), float(size[1])
    ax, ay = float(anchor[0]), float(anchor[1])
    # corners relative to the anchor, before rotation
    lx = (-ax * w, (1.0 - ax) * w)
    ly = (-ay * h, (1.0 - ay) * h)
    u0, v0, u1, v1 = uv
    tu0, tu1 = u0, u1
    tv0, tv1 = 1.0 - v0, 1.0 - v1          # image top -> texture v = 1
    pts = [(lx[0], ly[0], (tu0, tv0)),     # top-left
           (lx[1], ly[0], (tu1, tv0)),     # top-right
           (lx[1], ly[1], (tu1, tv1)),     # bottom-right
           (lx[0], ly[1], (tu0, tv1))]     # bottom-left
    if rot:
        c, s = math.cos(rot), math.sin(rot)
        pts = [(x * c - y * s, x * s + y * c, t) for x, y, t in pts]
    m = MeshData()
    n = (0.0, 0.0, 1.0)
    verts = [m.vert((px[0] + pos[0], px[1] + pos[1], layer), n, px[2], col)
             for px in pts]
    m.quad_idx(*verts)
    return m


def rect2d(pos, size, col=(1, 1, 1), rot=0.0, layer=0.0, anchor=(0.5, 0.5)):
    """A flat untextured quad: panels, fills, colour bars."""
    return quad2d(pos, size, col=col, uv=(0.0, 0.0, 1.0, 1.0), rot=rot,
                  layer=layer, anchor=anchor)


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
