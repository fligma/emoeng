"""Seam-aware unwrap onto a model's second uv channel."""

import math


# normals differing more than this cut; a cube's corners cut
SEAM_ANGLE = math.radians(58.0)

# atlas room around each piece, so filtered texels never bleed
MARGIN = 0.004


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 +
                     (a[2] - b[2]) ** 2)


def _norm(a):
    ln = math.sqrt(_dot(a, a))
    return (a[0] / ln, a[1] / ln, a[2] / ln) if ln > 1e-12 else (0.0, 1.0, 0.0)


def _face_normal(verts, tri):
    a, b, c = (verts[i] for i in tri)
    return _norm(_cross(_sub(b, a), _sub(c, a)))


def _perp(v):
    """Any unit vector at right angles to `v`."""
    ax, ay, az = abs(v[0]), abs(v[1]), abs(v[2])
    if ax <= ay and ax <= az:
        ref = (1.0, 0.0, 0.0)
    elif ay <= az:
        ref = (0.0, 1.0, 0.0)
    else:
        ref = (0.0, 0.0, 1.0)
    return _norm(_cross(v, ref))


class _Union:
    """Tiny disjoint-set so faces sharing an uncut edge join."""

    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _edge_faces(tris):
    """Map each undirected edge to the faces that own it."""
    out = {}
    for fi, tri in enumerate(tris):
        for k in range(3):
            a, b = tri[k], tri[(k + 1) % 3]
            out.setdefault((min(a, b), max(a, b)), []).append(fi)
    return out


def _charts(verts, tris, normals):
    """Group faces into charts by joining faces across uncut edges."""
    uf = _Union(len(tris))
    for (_a, _b), fs in _edge_faces(tris).items():
        if len(fs) != 2:
            continue                     # a boundary edge: already a cut
        f0, f1 = fs
        d = max(-1.0, min(1.0, _dot(normals[f0], normals[f1])))
        if math.acos(d) <= SEAM_ANGLE:
            uf.union(f0, f1)             # flat enough to stay one piece
    groups = {}
    for fi in range(len(tris)):
        groups.setdefault(uf.find(fi), []).append(fi)
    return list(groups.values())


def _place_root(verts, tri, normal):
    """Lay one triangle flat: its plane becomes the uv plane."""
    u = _perp(normal)
    v = _norm(_cross(normal, u))
    a = verts[tri[0]]
    out = []
    for i in tri:
        d = _sub(verts[i], a)
        out.append((_dot(d, u), _dot(d, v)))
    return out


def _swing(pu, pv, ru, rv, other):
    """Place a triangle's free corner across the hinge pu-pv."""
    du, dv = pv[0] - pu[0], pv[1] - pu[1]
    d = math.hypot(du, dv)
    if d < 1e-12:
        return ((pu[0] + pv[0]) * 0.5, (pu[1] + pv[1]) * 0.5)
    a = (ru * ru - rv * rv + d * d) / (2.0 * d)
    h = math.sqrt(max(0.0, ru * ru - a * a))
    ux, uy = du / d, dv / d
    bx, by = pu[0] + a * ux, pu[1] + a * uy
    px, py = -uy * h, ux * h
    # which side the parent corner and the candidate sit on
    s = _orient(pu, pv, other)
    s2 = _orient(pu, pv, (bx + px, by + py))
    if (s >= 0) == (s2 >= 0):
        return (bx - px, by - py)        # candidate matched parent: flip
    return (bx + px, by + py)


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _flatten(verts, tris, normals, faces, adj):
    """Swing a chart's faces out about their shared edges."""
    faces = list(faces)
    if len(faces) == 1:
        f = faces[0]
        return [(f, _place_root(verts, tris[f], normals[f]))]
    root = faces[0]
    coord = {}
    rpts = _place_root(verts, tris[root], normals[root])
    for i, c in zip(tris[root], rpts):
        coord[i] = c
    visited = {root: rpts}
    fset = set(faces)
    queue = [root]
    while queue:
        f = queue.pop(0)
        tri = tris[f]
        for k in range(3):
            a, b = tri[k], tri[(k + 1) % 3]
            nb = adj.get((f, min(a, b), max(a, b)))
            if nb is None or nb in visited or nb not in fset:
                continue
            tnb = tris[nb]
            free = next(x for x in tnb if x not in (a, b))
            if free not in coord:
                third = next(x for x in tri if x not in (a, b))
                coord[free] = _swing(coord[a], coord[b],
                                      _dist(verts[a], verts[free]),
                                      _dist(verts[b], verts[free]),
                                      coord[third])
            visited[nb] = [coord[i] for i in tnb]
            queue.append(nb)
    if len(visited) != len(faces):
        return None
    return [(f, visited[f]) for f in faces]


def _seg_hit(p1, p2, p3, p4):
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    eps = 1e-9
    cross1 = (d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)
    cross2 = (d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps)
    return cross1 and cross2


def _in_tri(p, a, b, c):
    # strictly inside; a corner on an edge is a seam
    d1 = _orient(a, b, p)
    d2 = _orient(b, c, p)
    d3 = _orient(c, a, p)
    return (d1 > 1e-9 and d2 > 1e-9 and d3 > 1e-9) or \
           (d1 < -1e-9 and d2 < -1e-9 and d3 < -1e-9)


def _tri_overlap(t1, t2):
    """Do two flat triangles cover any of the same ground?"""
    for p in t1:
        if _in_tri(p, t2[0], t2[1], t2[2]):
            return True
    for p in t2:
        if _in_tri(p, t1[0], t1[1], t1[2]):
            return True
    edges = [(0, 1), (1, 2), (2, 0)]
    for i, j in edges:
        for m, n in edges:
            if _seg_hit(t1[i], t1[j], t2[m], t2[n]):
                return True
    return False


def _overlaps(flat):
    tris2d = [pp for _f, pp in flat]
    for i in range(len(tris2d)):
        for j in range(i + 1, len(tris2d)):
            if _tri_overlap(tris2d[i], tris2d[j]):
                return True
    return False


def _adjacency(tris, fset):
    """Map (face, edge) to the neighbour across it."""
    adj = {}
    for (a, b), fs in _edge_faces(tris).items():
        if len(fs) != 2:
            continue
        f0, f1 = fs
        if f0 in fset:
            adj[(f0, a, b)] = f1
        if f1 in fset:
            adj[(f1, a, b)] = f0
    return adj


def _chart_bounds(chart):
    xs = [p[0] for _f, pts in chart for p in pts]
    ys = [p[1] for _f, pts in chart for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _pack(charts):
    """Pack charts into a square atlas without leaving a row per face."""
    if not charts:
        return []
    info = []
    for ch in charts:
        x0, y0, x1, y1 = _chart_bounds(ch)
        info.append([ch, x0, y0, max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)])
    info.sort(key=lambda e: (-max(e[3], e[4]), -(e[3] * e[4])))
    span = 1.0 - 2.0 * MARGIN
    target = 1000.0
    gap = 8.0
    widest = max(max(row[3], row[4]) for row in info)

    def place(scale):
        x = y = shelf = 0.0
        out = []
        for ch, x0, y0, w, h in info:
            sw, sh = w * scale, h * scale
            if x and x + sw > target:
                x = 0.0
                y += shelf + gap
                shelf = 0.0
            if sw > target or sh > target or y + sh > target:
                return None
            out.append((ch, x0, y0, w, h, x, y, sw, sh))
            x += sw + gap
            shelf = max(shelf, sh)
        return out

    low, high = 0.0, target / widest
    laid = place(high)
    if laid is None:
        for _ in range(32):
            scale = (low + high) * 0.5
            candidate = place(scale)
            if candidate is None:
                high = scale
            else:
                low = scale
                laid = candidate
    fit = span / target
    out = []
    for (ch, x0, y0, w, h, lx, ly, sw, sh) in laid:
        for (f, pts) in ch:
            out.append((f, pts, x0, y0, w, h,
                        lx * fit, ly * fit, sw * fit, sh * fit))
    return out


def _charts_of(verts, tris, want):
    """Flatten and pack just `want` faces (indices into `tris`), handing"""
    sub = [tris[f] for f in want]
    normals = [_face_normal(verts, t) for t in sub]
    charts = []
    for faces in _charts(verts, sub, normals):
        flat = _flatten(verts, sub, normals, faces,
                        _adjacency(sub, set(faces)))
        if flat is not None and _overlaps(flat):
            flat = None                  # it crumples: cut every face free
        if flat is None:
            for lf in faces:
                charts.append([(lf, _place_root(verts, sub[lf],
                                                normals[lf]))])
        else:
            charts.append(flat)
    return _pack(charts)


def _corner_uv(pts, i, x0, y0, w, h, ox, oy, ow, oh):
    """One flat corner folded into its packed slot."""
    cx, cy = pts[i]
    nx = (cx - x0) / w if w > 1e-9 else 0.5
    ny = (cy - y0) / h if h > 1e-9 else 0.5
    return [MARGIN + ox + nx * ow, MARGIN + oy + ny * oh]


def _unwrap_subset(model, verts, tris, uvs0, tex0, faces):
    """Unfold only `faces`, appending corners to the model."""
    want = sorted({int(f) for f in faces
                   if isinstance(f, (int, float))
                   and 0 <= int(f) < len(tris)})
    if not want:
        return verts, uvs0, model._aligned_uv2(), tris, tex0
    new_verts = [list(v) for v in verts]
    new_uvs = [list(u) for u in uvs0]
    base2 = model._aligned_uv2()
    new_uv2 = [list(base2[i]) if i < len(base2) else [0.0, 0.0]
               for i in range(len(verts))]
    new_tris = [list(t) for t in tris]
    for (lf, pts, x0, y0, w, h, ox, oy, ow, oh) in \
            _charts_of(verts, tris, want):
        gf = want[lf]
        blk = len(new_verts)
        for i, corner in enumerate(tris[gf]):
            new_verts.append(list(verts[corner]))
            uv = uvs0[corner] if corner < len(uvs0) else [0.0, 0.0]
            new_uvs.append([float(uv[0]), float(uv[1])])
            new_uv2.append(_corner_uv(pts, i, x0, y0, w, h,
                                      ox, oy, ow, oh))
        new_tris[gf] = [blk, blk + 1, blk + 2]
    refs = set()
    for t in new_tris:
        refs.update(t)
    keep = sorted(refs)
    remap = {v: i for i, v in enumerate(keep)}
    new_verts = [new_verts[v] for v in keep]
    new_uvs = [new_uvs[v] for v in keep]
    new_uv2 = [new_uv2[v] for v in keep]
    new_tris = [[remap[v] for v in t] for t in new_tris]
    return new_verts, new_uvs, new_uv2, new_tris, tex0


def split_and_unwrap(model, faces=None):
    """Unwrap the given faces onto a new `uv2` channel."""
    verts = [list(v) for v in model.verts]
    tris = [list(t) for t in model.tris]
    uvs0 = [list(u) for u in model.uvs]
    tex0 = list(model.align_tex())
    if not tris:
        return [], [], [], [], []
    if faces is not None:
        return _unwrap_subset(model, verts, tris, uvs0, tex0, faces)
    new_verts, new_uvs, new_uv2, new_tris, new_tex = [], [], [], [], []
    want = list(range(len(tris)))
    for (lf, pts, x0, y0, w, h, ox, oy, ow, oh) in \
            _charts_of(verts, tris, want):
        f = want[lf]
        base = len(new_verts)
        for i, corner in enumerate(tris[f]):
            new_verts.append(list(verts[corner]))
            uv = uvs0[corner] if corner < len(uvs0) else [0.0, 0.0]
            new_uvs.append([float(uv[0]), float(uv[1])])
            new_uv2.append(_corner_uv(pts, i, x0, y0, w, h,
                                      ox, oy, ow, oh))
        new_tris.append([base, base + 1, base + 2])
        new_tex.append(tex0[f] if f < len(tex0) else None)
    return new_verts, new_uvs, new_uv2, new_tris, new_tex
