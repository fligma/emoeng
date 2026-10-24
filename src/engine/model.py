"""The `.model` format: plain-text vertex/face meshes the engine and the
model editor share.

A model file is JSON, so it stays diff-able and hand-editable:

    {
      "format": "fligmodel", "version": 1, "name": "crate",
      "texture": "crate", "color": [0.8, 0.8, 0.8],
      "verts": [[x, y, z], ...],
      "uvs":   [[u, v], ...],
      "tris":  [[a, b, c], ...]
    }

Geometry is authored with the base sitting on y = 0 and the pivot at the
origin, so placing a model at ground level is just pos. Rendering flattens
per-triangle normals (faceted PS2 shading) into MeshData; the editor edits
the raw vertices and faces directly.
"""

import json
import math
from pathlib import Path

from . import meshes

FORMAT = "fligmodel"
VERSION = 1

PRIMITIVES = ("box", "wedge", "cylinder", "cone", "plane", "sphere")


# ------------------------------------------------------------------ helpers
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _normal(a, b, c):
    n = _cross(_sub(b, a), _sub(c, a))
    ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
    return (n[0] / ln, n[1] / ln, n[2] / ln) if ln > 1e-9 else (0.0, 1.0, 0.0)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class Model:
    """Vertices, uvs and triangles with the editing operations the model
    tab needs. Every mutation keeps uvs in step with verts."""

    def __init__(self, name="model", verts=None, uvs=None, tris=None,
                 texture="white", color=(1.0, 1.0, 1.0), pivot=(0, 0, 0)):
        self.name = name
        self.texture = texture
        self.color = tuple(float(c) for c in color)
        self.pivot = tuple(float(c) for c in pivot)
        self.verts = [[float(v) for v in p] for p in (verts or [])]
        self.uvs = [[float(c) for c in p] for p in (uvs or [])]
        self.tris = [[int(i) for i in t] for t in (tris or [])]
        self.path = None
        self._fix_lengths()

    def _fix_lengths(self):
        while len(self.uvs) < len(self.verts):
            self.uvs.append([0.0, 0.0])
        del self.uvs[len(self.verts):]
        self.tris = [t for t in self.tris
                     if len(t) == 3 and all(0 <= i < len(self.verts)
                                            for i in t)]

    # --------------------------------------------------------------- facts
    @property
    def tri_count(self):
        return len(self.tris)

    @property
    def empty(self):
        return not self.verts or not self.tris

    def bounds(self):
        if not self.verts:
            return None
        xs = [v[0] for v in self.verts]
        ys = [v[1] for v in self.verts]
        zs = [v[2] for v in self.verts]
        return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))

    def centre(self):
        b = self.bounds()
        if b is None:
            return (0.0, 0.0, 0.0)
        return tuple((b[0][i] + b[1][i]) * 0.5 for i in range(3))

    def radius(self):
        b = self.bounds()
        if b is None:
            return 0.0
        return max(0.01, 0.5 * math.dist(b[0], b[1]))

    # ------------------------------------------------------------- file io
    @classmethod
    def load(cls, path):
        p = Path(path)
        model = cls.loads(p.read_text(encoding="utf-8"), p.stem)
        model.path = str(p)
        return model

    @classmethod
    def loads(cls, text, name="model"):
        data = json.loads(text)
        if isinstance(data, list):                    # bare vertex list
            data = {"verts": data, "tris": []}
        if not isinstance(data, dict):
            raise ValueError("model file must contain a JSON object")
        return cls(
            name=data.get("name") or name,
            verts=data.get("verts") or [],
            uvs=data.get("uvs") or [],
            tris=data.get("tris") or data.get("faces") or [],
            texture=data.get("texture", "white"),
            color=data.get("color", (1.0, 1.0, 1.0)),
            pivot=data.get("pivot", (0.0, 0.0, 0.0)),
        )

    def to_dict(self):
        return {
            "format": FORMAT,
            "version": VERSION,
            "name": self.name,
            "texture": self.texture,
            "color": [round(c, 4) for c in self.color],
            "pivot": [round(c, 4) for c in self.pivot],
            "verts": [[round(c, 4) for c in v] for v in self.verts],
            "uvs": [[round(c, 4) for c in p] for p in self.uvs],
            "tris": [list(t) for t in self.tris],
        }

    def dumps(self):
        return json.dumps(self.to_dict(), indent=1)

    def save(self, path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.dumps(), encoding="utf-8")
        self.path = str(p)
        self.name = p.stem
        return p

    # ------------------------------------------------------------ geometry
    def meshdata(self, pos=(0, 0, 0), yaw=0.0, scale=(1.0, 1.0, 1.0),
                 tint=None):
        """Flatten to render-ready vertices with per-face normals. The
        transform puts the model's base at pos, yawed about +Y."""
        md = meshes.MeshData()
        if not self.tris:
            return md
        if isinstance(scale, (int, float)):
            scale = (float(scale),) * 3
        c, s = math.cos(yaw), math.sin(yaw)
        col = tuple(self.color if tint is None else tint)
        world = []
        for v in self.verts:
            x, y, z = v[0] * scale[0], v[1] * scale[1], v[2] * scale[2]
            world.append((c * x + s * z + pos[0], y + pos[1],
                          -s * x + c * z + pos[2]))
        for t in self.tris:
            a, b, cc = world[t[0]], world[t[1]], world[t[2]]
            n = _normal(a, b, cc)
            for k, vi in enumerate(t):
                uv = self.uvs[vi] if vi < len(self.uvs) else (0.0, 0.0)
                md.vert(world[vi], n, uv, col)
        for i in range(0, len(self.tris) * 3, 3):
            md.tri(i, i + 1, i + 2)
        return md

    def add_meshdata(self, md):
        """Append generated geometry (meshes builders) as raw triangles."""
        base = len(self.verts)
        self.verts += [list(p) for p in md.pos]
        self.uvs += [list(p) for p in md.uv]
        for i in range(0, len(md.idx), 3):
            self.tris.append([md.idx[i] + base, md.idx[i + 1] + base,
                              md.idx[i + 2] + base])
        return self

    # ----------------------------------------------------------- selection
    def clone(self):
        return Model(self.name, self.verts, self.uvs, self.tris,
                     self.texture, self.color, self.pivot)

    def snapshot(self):
        return {"verts": [list(v) for v in self.verts],
                "uvs": [list(p) for p in self.uvs],
                "tris": [list(t) for t in self.tris],
                "texture": self.texture,
                "color": tuple(self.color)}

    def restore(self, snap):
        self.verts = [list(v) for v in snap["verts"]]
        self.uvs = [list(p) for p in snap["uvs"]]
        self.tris = [list(t) for t in snap["tris"]]
        self.texture = snap.get("texture", self.texture)
        self.color = tuple(snap.get("color", self.color))

    def faces_using(self, indices):
        s = set(indices)
        return [i for i, t in enumerate(self.tris) if s & set(t)]

    def delete_faces(self, faces):
        drop = set(faces)
        self.tris = [t for i, t in enumerate(self.tris) if i not in drop]

    def delete_vertices(self, indices):
        drop = set(indices)
        if not drop:
            return
        self.tris = [t for t in self.tris if not (drop & set(t))]
        remap, verts, uvs = {}, [], []
        for i, (v, uv) in enumerate(zip(self.verts, self.uvs)):
            if i in drop:
                continue
            remap[i] = len(verts)
            verts.append(v)
            uvs.append(uv)
        self.verts, self.uvs = verts, uvs
        self.tris = [[remap[i] for i in t] for t in self.tris]

    def add_vertex(self, pos, uv=(0.0, 0.0)):
        self.verts.append([float(c) for c in pos])
        self.uvs.append([float(uv[0]), float(uv[1])])
        return len(self.verts) - 1

    def add_face(self, a, b, c, uvs=None):
        if len({a, b, c}) < 3:
            return None
        if uvs is None:
            uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        for k, vi in enumerate((a, b, c)):
            while len(self.uvs) <= vi:
                self.uvs.append([0.0, 0.0])
            if self.uvs[vi] == [0.0, 0.0]:
                self.uvs[vi] = [float(uvs[k][0]), float(uvs[k][1])]
        self.tris.append([a, b, c])
        return len(self.tris) - 1

    def face_normal(self, face):
        t = self.tris[face]
        return _normal(self.verts[t[0]], self.verts[t[1]],
                       self.verts[t[2]])

    def face_centre(self, face):
        t = self.tris[face]
        return tuple(sum(self.verts[i][k] for i in t) / 3.0 for k in range(3))

    def flip_face(self, face):
        t = self.tris[face]
        t[1], t[2] = t[2], t[1]

    # ------------------------------------------------------------ editing
    def move_verts(self, indices, delta, snap=0.0):
        for i in indices:
            v = self.verts[i]
            v[0] += delta[0]
            v[1] += delta[1]
            v[2] += delta[2]
            if snap > 1e-6:
                v[0] = round(v[0] / snap) * snap
                v[1] = round(v[1] / snap) * snap
                v[2] = round(v[2] / snap) * snap

    def translate(self, delta):
        self.move_verts(range(len(self.verts)), delta)

    def scale(self, factor, origin=(0.0, 0.0, 0.0)):
        if isinstance(factor, (int, float)):
            factor = (factor, factor, factor)
        for v in self.verts:
            for k in range(3):
                v[k] = origin[k] + (v[k] - origin[k]) * factor[k]

    def rotate_y(self, angle, origin=(0.0, 0.0, 0.0)):
        c, s = math.cos(angle), math.sin(angle)
        for v in self.verts:
            x, z = v[0] - origin[0], v[2] - origin[2]
            v[0] = origin[0] + c * x + s * z
            v[2] = origin[2] - s * x + c * z

    def extrude(self, face, dist):
        """Lift a triangle into a prism: new cap + three side faces."""
        t = list(self.tris[face])
        n = self.face_normal(face)
        new = []
        for vi in t:
            v = self.verts[vi]
            new.append(self.add_vertex(
                (v[0] + n[0] * dist, v[1] + n[1] * dist,
                 v[2] + n[2] * dist), self.uvs[vi]))
        centre = self.centre()
        for k in range(3):
            a, b = t[k], t[(k + 1) % 3]
            na, nb = new[k], new[(k + 1) % 3]
            ids = [a, b, nb, na]
            mid = [sum(self.verts[i][j] for i in ids) / 4.0
                   for j in range(3)]
            self._auto_quad(ids, _sub(mid, centre))
        self.tris[face] = new
        return new

    def weld(self, eps=1e-4):
        """Merge vertices that sit on top of each other."""
        buckets = {}
        remap = list(range(len(self.verts)))
        verts, uvs = [], []
        for i, v in enumerate(self.verts):
            key = tuple(round(c / eps) for c in v)
            if key in buckets:
                remap[i] = buckets[key]
                continue
            buckets[key] = len(verts)
            remap[i] = len(verts)
            verts.append(v)
            uvs.append(self.uvs[i])
        self.verts, self.uvs = verts, uvs
        tris = []
        for t in self.tris:
            a, b, c = (remap[i] for i in t)
            if len({a, b, c}) == 3:
                tris.append([a, b, c])
        self.tris = tris

    def auto_uv(self):
        """Planar UV per face, projected along its dominant axis."""
        b = self.bounds() or ((0, 0, 0), (1, 1, 1))
        size = [max(1e-4, b[1][i] - b[0][i]) for i in range(3)]
        for t in self.tris:
            pts = [self.verts[i] for i in t]
            n = _normal(pts[0], pts[1], pts[2])
            axis = max(range(3), key=lambda k: abs(n[k]))
            ua, va = [(1, 2), (0, 2), (0, 1)][axis]
            for k, vi in enumerate(t):
                u = (pts[k][ua] - b[0][ua]) / size[ua]
                v = (pts[k][va] - b[0][va]) / size[va]
                self.uvs[vi] = [u, v]

    # ------------------------------------------------------- face helpers
    def _auto_quad(self, ids, hint):
        a, b, c, d = (self.verts[i] for i in ids)
        if _dot(_normal(a, b, c), hint) < 0.0:
            ids = [ids[3], ids[2], ids[1], ids[0]]
        self.tris.append([ids[0], ids[1], ids[2]])
        self.tris.append([ids[0], ids[2], ids[3]])

    def _auto_tri(self, ids, hint):
        a, b, c = (self.verts[i] for i in ids)
        if _dot(_normal(a, b, c), hint) < 0.0:
            ids = [ids[0], ids[2], ids[1]]
        self.tris.append(list(ids))

    def append(self, other, offset=(0.0, 0.0, 0.0)):
        """Merge another model's geometry in, offset in model space."""
        base = len(self.verts)
        self.verts += [[v[0] + offset[0], v[1] + offset[1],
                        v[2] + offset[2]] for v in other.verts]
        self.uvs += [list(p) for p in other.uvs]
        self.tris += [[i + base for i in t] for t in other.tris]

    # ---------------------------------------------------------- primitives
    def add_primitive(self, kind, size=1.0, offset=(0.0, 0.0, 0.0)):
        gen = _PRIMITIVE_FUNCS.get(kind)
        if gen is None:
            raise ValueError(f"unknown primitive '{kind}'")
        other = gen(size)
        self.append(other, offset)
        return self


# -------------------------------------------------------------- primitives
def _quad(m, ids, hint, uvs=None):
    a, b, c, d = (m.verts[i] for i in ids)
    if _dot(_normal(a, b, c), hint) < 0.0:
        ids = [ids[3], ids[2], ids[1], ids[0]]
        uvs = list(reversed(uvs)) if uvs else None
    if uvs is None:
        uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
    m.tris.append([ids[0], ids[1], ids[2]])
    m.tris.append([ids[0], ids[2], ids[3]])
    for vi, uv in zip(ids, uvs):
        m.uvs[vi] = [float(uv[0]), float(uv[1])]


def _tri(m, ids, hint, uvs=((0, 0), (1, 0), (1, 1))):
    a, b, c = (m.verts[i] for i in ids)
    if _dot(_normal(a, b, c), hint) < 0.0:
        ids = [ids[0], ids[2], ids[1]]
        uvs = (uvs[0], uvs[2], uvs[1])
    m.tris.append(list(ids))
    for vi, uv in zip(ids, uvs):
        m.uvs[vi] = [float(uv[0]), float(uv[1])]


def _ring(m, r, y, seg, top=False):
    out = []
    for i in range(seg):
        a = 2.0 * math.pi * i / seg
        out.append(m.add_vertex((math.cos(a) * r, y, math.sin(a) * r),
                                (i / seg, 1.0 if top else 0.0)))
    return out


def box_model(size=1.0, name="box"):
    """Cube with its base on y = 0."""
    m = Model(name)
    h = float(size)
    x = z = h / 2.0
    v = [m.add_vertex((-x, 0, -z)), m.add_vertex((x, 0, -z)),
         m.add_vertex((x, h, -z)), m.add_vertex((-x, h, -z)),
         m.add_vertex((-x, 0, z)), m.add_vertex((x, 0, z)),
         m.add_vertex((x, h, z)), m.add_vertex((-x, h, z))]
    _quad(m, [v[4], v[5], v[6], v[7]], (0, 0, 1))
    _quad(m, [v[1], v[0], v[3], v[2]], (0, 0, -1))
    _quad(m, [v[5], v[1], v[2], v[6]], (1, 0, 0))
    _quad(m, [v[0], v[4], v[7], v[3]], (-1, 0, 0))
    _quad(m, [v[7], v[6], v[2], v[3]], (0, 1, 0))
    _quad(m, [v[0], v[1], v[5], v[4]], (0, -1, 0))
    return m


def plane_model(size=2.0, name="plane"):
    m = Model(name)
    h = float(size) / 2.0
    v = [m.add_vertex((-h, 0, -h), (0, 0)),
         m.add_vertex((h, 0, -h), (1, 0)),
         m.add_vertex((h, 0, h), (1, 1)),
         m.add_vertex((-h, 0, h), (0, 1))]
    _quad(m, [v[0], v[3], v[2], v[1]], (0, 1, 0))
    return m


def wedge_model(size=1.0, name="wedge"):
    """Ramp: flat on the ground, rising toward +Z (PS2 corridor staple)."""
    m = Model(name)
    h = float(size)
    x = z = h / 2.0
    v = [m.add_vertex((-x, 0, -z)), m.add_vertex((x, 0, -z)),
         m.add_vertex((x, 0, z)), m.add_vertex((-x, 0, z)),
         m.add_vertex((x, h, z)), m.add_vertex((-x, h, z))]
    _quad(m, [v[0], v[1], v[2], v[3]], (0, -1, 0))     # ground
    _quad(m, [v[3], v[2], v[4], v[5]], (0, 0.4, 1))    # ramp
    _quad(m, [v[2], v[3], v[5], v[4]], (0, 0, 1))      # tall back
    _tri(m, [v[1], v[2], v[4]], (1, 0, 0))             # +x cheek
    _tri(m, [v[0], v[3], v[5]], (-1, 0, 0))            # -x cheek
    return m


def cylinder_model(size=1.0, seg=12, name="cylinder"):
    """Y-up cylinder, base on y = 0."""
    m = Model(name)
    h = float(size)
    r = h * 0.35
    lo = _ring(m, r, 0.0, seg)
    hi = _ring(m, r, h, seg, top=True)
    for i in range(seg):
        j = (i + 1) % seg
        u0, u1 = i / seg, (i + 1) / seg
        _quad(m, [lo[i], lo[j], hi[j], hi[i]],
              (math.cos(2 * math.pi * (i + 0.5) / seg), 0,
               math.sin(2 * math.pi * (i + 0.5) / seg)),
              ((u0, 0), (u1, 0), (u1, 1), (u0, 1)))
    c_top = m.add_vertex((0.0, h, 0.0), (0.5, 0.5))
    c_bot = m.add_vertex((0.0, 0.0, 0.0), (0.5, 0.5))
    for i in range(seg):
        j = (i + 1) % seg
        a = 2 * math.pi * i / seg
        b = 2 * math.pi * j / seg
        _tri(m, [hi[i], hi[j], c_top], (0, 1, 0),
             ((0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)),
              (0.5 + 0.5 * math.cos(b), 0.5 + 0.5 * math.sin(b)), (0.5, 0.5)))
        _tri(m, [lo[j], lo[i], c_bot], (0, -1, 0),
             ((0.5 + 0.5 * math.cos(b), 0.5 + 0.5 * math.sin(b)),
              (0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)), (0.5, 0.5)))
    return m


def cone_model(size=1.0, seg=10, name="cone"):
    m = Model(name)
    h = float(size)
    r = h * 0.45
    lo = _ring(m, r, 0.0, seg)
    apex = m.add_vertex((0.0, h, 0.0), (0.5, 1.0))
    for i in range(seg):
        j = (i + 1) % seg
        a = 2 * math.pi * i / seg
        _tri(m, [lo[i], lo[j], apex],
             (math.cos(a), 0.25, math.sin(a)),
             ((0.0, 0.0), (1.0, 0.0), (0.5, 1.0)))
    c_bot = m.add_vertex((0.0, 0.0, 0.0), (0.5, 0.5))
    for i in range(seg):
        j = (i + 1) % seg
        _tri(m, [lo[j], lo[i], c_bot], (0, -1, 0))
    return m


def sphere_model(size=1.0, seg=12, rings=6, name="sphere"):
    """UV sphere with its base on y = 0."""
    m = Model(name)
    r = float(size) / 2.0
    grid = []
    for ri in range(rings + 1):
        phi = math.pi * ri / rings
        y = r - math.cos(phi) * r
        rad = math.sin(phi) * r
        row = []
        for si in range(seg):
            a = 2 * math.pi * si / seg
            row.append(m.add_vertex((math.cos(a) * rad, y,
                                     math.sin(a) * rad),
                                    (si / seg, 1.0 - ri / rings)))
        grid.append(row)
    for ri in range(rings):
        for si in range(seg):
            sj = (si + 1) % seg
            a = grid[ri][si]
            b = grid[ri][sj]
            c = grid[ri + 1][sj]
            d = grid[ri + 1][si]
            hint = (m.verts[a][0], m.verts[a][1] - r, m.verts[a][2])
            _quad(m, [a, b, c, d], hint)
    m.weld(1e-4)
    return m


_PRIMITIVE_FUNCS = {
    "box": box_model,
    "plane": plane_model,
    "wedge": wedge_model,
    "cylinder": cylinder_model,
    "cone": cone_model,
    "sphere": sphere_model,
}


def new_model(kind="box", size=1.0, texture="white", name=None):
    model = _PRIMITIVE_FUNCS[kind](size, name or kind)
    model.texture = texture
    model.auto_uv()
    return model
