"""Swept-box collision helpers for walking around a level."""

import math

# units a body may graze a face before counting outside
GRAZE = 1e-4


def aabb(centre, half):
    return (tuple(float(c) for c in centre), tuple(float(h) for h in half))


def expand(box, amount):
    centre, half = box
    return (centre, tuple(h + amount for h in half))


def contains_point(box, point):
    centre, half = box
    return all(abs(point[i] - centre[i]) <= half[i] for i in range(3))


def overlap(a, b):
    ca, ha = a
    cb, hb = b
    return all(abs(ca[i] - cb[i]) <= ha[i] + hb[i] for i in range(3))


def ray_aabb(origin, direction, box):
    """Entry distance along a unit ray, or None."""
    centre, half = box
    tmin, tmax = 0.0, 1e9
    for i in range(3):
        o = origin[i] - centre[i]
        d = direction[i]
        if abs(d) < 1e-9:
            if abs(o) > half[i]:
                return None
            continue
        t1 = (-half[i] - o) / d
        t2 = (half[i] - o) / d
        if t1 > t2:
            t1, t2 = t2, t1
        tmin = max(tmin, t1)
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    return tmin


def ray_plane(origin, direction, point, normal):
    denom = sum(direction[i] * normal[i] for i in range(3))
    if abs(denom) < 1e-9:
        return None
    t = sum((point[i] - origin[i]) * normal[i] for i in range(3)) / denom
    return t if t >= 0.0 else None


def ray_sphere(origin, direction, centre, radius):
    m = [origin[i] - centre[i] for i in range(3)]
    b = sum(m[i] * direction[i] for i in range(3))
    c = sum(v * v for v in m) - radius * radius
    disc = b * b - c
    if disc < 0.0:
        return None
    t = -b - math.sqrt(disc)
    if t < 0.0:
        t = -b + math.sqrt(disc)
    return t if t >= 0.0 else None


def move_slide(pos, delta, boxes, half=(0.35, 0.9, 0.35)):
    """Move a box-shaped body, stopping at colliders per axis. Returns"""
    pos = [float(c) for c in pos]
    half = tuple(float(h) for h in half)
    hits = [False, False, False]
    for axis in range(3):
        d = float(delta[axis])
        if abs(d) < 1e-9:
            continue
        start = pos[axis]
        want = start + d
        stop = want
        others = [i for i in range(3) if i != axis]
        for centre, bh in boxes:
            # solid only when inside on the two still axes
            if not all(abs(pos[i] - centre[i]) + GRAZE < half[i] + bh[i]
                       for i in others):
                continue
            if d > 0:
                face = centre[axis] - bh[axis] - half[axis]
                if start - GRAZE <= face < stop:
                    stop = face        # nearest blocking face wins
            else:
                face = centre[axis] + bh[axis] + half[axis]
                if start + GRAZE >= face > stop:
                    stop = face
        hits[axis] = stop != want
        pos[axis] = stop
    return pos, tuple(hits)


def _tri_normal(a, b, c):
    n = _cross(_sub(b, a), _sub(c, a))
    ln = math.sqrt(sum(v * v for v in n))
    return (n[0] / ln, n[1] / ln, n[2] / ln) if ln > 1e-9 else None


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class TriMesh:
    """World-space triangles a body can walk among."""

    def __init__(self, tris, cell=4.0):
        self.tris = [[tuple(float(v) for v in p) for p in t]
                     for t in tris]
        self.normals = [(_tri_normal(*t) or (0.0, 1.0, 0.0))
                        for t in self.tris]
        self.cell = max(0.5, float(cell))
        self.grid = {}
        lo, hi = None, None
        for i, t in enumerate(self.tris):
            xs = [p[0] for p in t]
            ys = [p[1] for p in t]
            zs = [p[2] for p in t]
            box = ((min(xs), min(ys), min(zs)),
                   (max(xs), max(ys), max(zs)))
            lo = box[0] if lo is None else tuple(
                min(a, b) for a, b in zip(lo, box[0]))
            hi = box[1] if hi is None else tuple(
                max(a, b) for a, b in zip(hi, box[1]))
            c = self._cell(box[0])
            d = self._cell(box[1])
            for ix in range(c[0], d[0] + 1):
                for iy in range(c[1], d[1] + 1):
                    for iz in range(c[2], d[2] + 1):
                        self.grid.setdefault((ix, iy, iz),
                                             []).append(i)
        self.bounds = (lo, hi) if lo is not None else None

    def _cell(self, p):
        return tuple(int(math.floor(v / self.cell)) for v in p)

    def tris_near(self, box):
        """The triangles whose own bounds touch a `(centre, half)` box."""
        if not self.tris:
            return []
        centre, half = box
        lo = [centre[i] - half[i] for i in range(3)]
        hi = [centre[i] + half[i] for i in range(3)]
        c = self._cell(lo)
        d = self._cell(hi)
        seen, out = set(), []
        for ix in range(c[0], d[0] + 1):
            for iy in range(c[1], d[1] + 1):
                for iz in range(c[2], d[2] + 1):
                    for i in self.grid.get((ix, iy, iz), ()):
                        if i in seen:
                            continue
                        seen.add(i)
                        tlo, thi = self._tri_bounds(i)
                        if all(tlo[k] <= hi[k] + GRAZE and
                               thi[k] >= lo[k] - GRAZE for k in range(3)):
                            out.append(i)
        return out

    def _tri_bounds(self, i):
        t = self.tris[i]
        return ([min(p[k] for p in t) for k in range(3)],
                [max(p[k] for p in t) for k in range(3)])

    def tri_bounds(self, i):
        """The (lo, hi) corner bounds of one triangle, by index."""
        return self._tri_bounds(i)

    def contains(self, point):
        """Even-odd ray parity: a straight-up line from the point counts"""
        hits = 0
        for i in self.tris_near(((point[0], point[1] + 32.0, point[2]),
                                 (32.0, 32.0, 32.0))):
            if _ray_tri(point, (0.0, 1.0, 0.0), self.tris[i]) > 0.0:
                hits += 1
        return hits % 2 == 1


def _ray_tri(origin, rd, tri):
    """Distance along a ray to a triangle, -1.0 on miss."""
    a, b, c = tri
    e1, e2 = _sub(b, a), _sub(c, a)
    p = _cross(rd, e2)
    det = _dot(e1, p)
    if abs(det) < 1e-9:
        return -1.0
    s = _sub(origin, a)
    u = _dot(s, p) / det
    if u < 0.0 or u > 1.0:
        return -1.0
    q = _cross(s, e1)
    v = _dot(rd, q) / det
    if v < 0.0 or u + v > 1.0:
        return -1.0
    t = _dot(e2, q) / det
    return t if t > 1e-7 else -1.0


def _tri_bounds(tri):
    return ([min(p[k] for p in tri) for k in range(3)],
            [max(p[k] for p in tri) for k in range(3)])


def _block_along_axis(tri, nrm, centre, half, delta, axis):
    """Travel allowed along one axis before hitting a triangle."""
    mid = [(tri[0][k] + tri[1][k] + tri[2][k]) / 3.0 for k in range(3)]
    side = _dot(_sub(centre, mid), nrm)
    if abs(_dot(delta, nrm)) <= GRAZE:
        return None        # grazed parallel: slid on, as ever
    tlo, thi = _tri_bounds(tri)
    for i in (0, 1, 2):    # solid only while genuinely inside the span
        if i == axis:
            continue
        if not (tlo[i] - half[i] - GRAZE < centre[i] <
                thi[i] + half[i] + GRAZE):
            return None
    rad = sum(abs(nrm[k]) * half[k] for k in range(3))
    # the plane, aimed into the move rather than away
    if side < 0.0:
        nrm = tuple(-v for v in nrm)
        side = -side
    dist = side - rad      # to the face plane, from the body's skin
    if dist < -1e-3:
        return 0.0         # already through the plane
    moving = _dot(delta, nrm)          # negative: moving into the face
    if moving >= -GRAZE:
        return None
    frac = dist / -moving
    return frac if frac <= 1.0 + GRAZE else None


def move_slide_mesh(pos, delta, boxes, meshes, half=(0.35, 0.9, 0.35)):
    """Mesh twin of `move_slide`: same per-axis sweep."""
    pos = [float(c) for c in pos]
    half = tuple(float(h) for h in half)
    hits = [False, False, False]
    for axis in (0, 2, 1):
        d = float(delta[axis])
        if abs(d) < 1e-9:
            continue
        start = pos[axis]
        want = start + d
        stop = want
        others = [i for i in range(3) if i != axis]
        for centre, bh in boxes:
            # the plain box rule, exactly as `move_slide` applies it
            if not all(abs(pos[i] - centre[i]) + GRAZE < half[i] + bh[i]
                       for i in others):
                continue
            if d > 0:
                face = centre[axis] - bh[axis] - half[axis]
                if start - GRAZE <= face < stop:
                    stop = face
            else:
                face = centre[axis] + bh[axis] + half[axis]
                if start + GRAZE >= face > stop:
                    stop = face
        path = [float(c) for c in pos]
        path[axis] = want
        pad = [half[k] + abs(delta[k]) for k in range(3)]
        if axis != 1:
            # a step-up: stand where that face will hold the body
            for mesh in meshes:
                for i in mesh.tris_near((path, pad)):
                    nrm = mesh.normals[i]
                    if abs(_dot(delta, nrm)) <= GRAZE:
                        continue
                    tlo, thi = mesh.tri_bounds(i)
                    if not all(tlo[k] - half[k] - GRAZE < pos[k] <
                               thi[k] + half[k] + GRAZE
                               for k in others):
                        continue
                    mid = [(mesh.tris[i][0][k] + mesh.tris[i][1][k] +
                            mesh.tris[i][2][k]) / 3.0 for k in range(3)]
                    at = [float(c) for c in pos]
                    at[axis] = want
                    side = _dot(_sub(at, mid), nrm)
                    if side < 0.0:
                        nrm = tuple(-v for v in nrm)
                    rad = sum(abs(nrm[k]) * half[k] for k in range(3))
                    if nrm[1] < 0.35 or abs(nrm[1]) < 1e-6:
                        continue        # a wall, not a slope
                    # the centre height that rests the skin on the plane
                    rest = mid[1] + (rad - _dot(_sub(at, mid), nrm)
                                     + (at[1] - mid[1]) * nrm[1]) / nrm[1]
                    if pos[1] < rest < pos[1] + half[1] + 0.6 and \
                            rest > pos[1]:
                        pos[1] = max(pos[1], rest)
        for mesh in meshes:
            for i in mesh.tris_near((path, pad)):
                if axis != 1 and abs(mesh.normals[i][1]) >= 0.35:
                    # walkable floors never block a sideways step; only walls stop
                    continue
                frac = _block_along_axis(mesh.tris[i], mesh.normals[i],
                                         pos, half, delta, axis)
                if frac is None:
                    continue
                face = start + d * frac
                if d > 0 and face < stop - GRAZE or \
                        d < 0 and face > stop + GRAZE:
                    stop = face
        hits[axis] = stop != want
        pos[axis] = stop
    return pos, tuple(hits)


def sphere_push(pos, radius, boxes):
    """Cheap depenetration for a sphere against axis-aligned boxes."""
    pos = list(pos)
    for centre, half in boxes:
        nearest = [max(centre[i] - half[i], min(pos[i], centre[i] + half[i]))
                   for i in range(3)]
        d = [pos[i] - nearest[i] for i in range(3)]
        dist = math.sqrt(sum(v * v for v in d))
        if dist < radius:
            if dist < 1e-6:
                pos[1] = centre[1] + half[1] + radius
                continue
            push = (radius - dist)
            for i in range(3):
                pos[i] += d[i] / dist * push
    return pos


def ground_clamp(pos, height_fn, eye_height):
    """Keep a walking camera gliding over terrain."""
    y = height_fn(pos[0], pos[2]) + eye_height
    return [pos[0], y, pos[2]]


def _rect(box):
    """A `(x, y, w, h)` rect as four floats."""
    if hasattr(box, "w") and hasattr(box, "h"):
        return float(box.x), float(box.y), float(box.w), float(box.h)
    return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))


def rects_overlap(a, b):
    """Do two rects cover the same pixel?"""
    ax, ay, aw, ah = _rect(a)
    bx, by, bw, bh = _rect(b)
    return (ax < bx + bw and bx < ax + aw
            and ay < by + bh and by < ay + ah)


def move_slide2d(pos, delta, rects, radius=0.0):
    """Move a disc in a pixel world, stopping per axis."""
    pos = [float(pos[0]), float(pos[1])]
    r = float(radius)
    hits = [False, False]
    for axis in range(2):
        d = float(delta[axis])
        if abs(d) < 1e-9:
            continue
        start = pos[axis]
        want = start + d
        stop = want
        other = 1 - axis
        for box in rects:
            rx, ry, rw, rh = _rect(box)
            span = (rx, ry)[other]
            size = (rw, rh)[other]
            near = (rx, ry)[axis]
            thick = (rw, rh)[axis]
            # solid only while overlapping on the still axis
            if not (span - r - GRAZE < pos[other] < span + size + r + GRAZE):
                continue
            if d > 0:
                face = near - r
                if start - GRAZE <= face < stop:
                    stop = face        # nearest blocking face wins
            else:
                face = near + thick + r
                if start + GRAZE >= face > stop:
                    stop = face
        hits[axis] = stop != want
        pos[axis] = stop
    return pos, tuple(hits)


def _push_one(pos, r, box):
    """Smallest move freeing a disc from a rect, or None."""
    rx, ry, rw, rh = _rect(box)
    if not (rx - r <= pos[0] <= rx + rw + r and
            ry - r <= pos[1] <= ry + rh + r):
        return None
    near = (max(rx, min(pos[0], rx + rw)), max(ry, min(pos[1], ry + rh)))
    dx, dy = pos[0] - near[0], pos[1] - near[1]
    dist = math.hypot(dx, dy)
    if dist > 1e-6:
        return None if dist >= r else (r - dist, dx / dist, dy / dist)
    return min(((pos[0] - rx) + r, -1.0, 0.0),
               ((rx + rw - pos[0]) + r, 1.0, 0.0),
               ((pos[1] - ry) + r, 0.0, -1.0),
               ((ry + rh - pos[1]) + r, 0.0, 1.0))


def _clear(pos, r, rects):
    """Does a disc at `pos` miss every rect?"""
    return all(_push_one(pos, r, box) is None for box in rects)


def _escapes(pos, r, rects):
    """Every exit from the rects containing the centre."""
    out = []
    for box in rects:
        rx, ry, rw, rh = _rect(box)
        if not (rx <= pos[0] < rx + rw and ry <= pos[1] < ry + rh):
            continue
        out.extend([[rx - r, pos[1]], [rx + rw + r, pos[1]],
                    [pos[0], ry - r], [pos[0], ry + rh + r]])
    out.sort(key=lambda p: math.hypot(p[0] - pos[0], p[1] - pos[1]))
    return out


def disc_push(pos, radius, rects):
    """Push a disc out of every rect it overlaps."""
    pos = [float(pos[0]), float(pos[1])]
    r = float(radius)
    for _pass in range(8):
        best = None
        for box in rects:
            got = _push_one(pos, r, box)
            if got is not None and (best is None or got[0] < best[0]):
                best = got
        if best is None:
            break
        step = [pos[0] + best[1] * best[0], pos[1] + best[2] * best[0]]
        if not _clear(step, r, rects):
            for cand in _escapes(pos, r, rects):
                if _clear(cand, r, rects):
                    step = cand
                    break
        pos = list(step)
    return pos
