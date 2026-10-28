"""The `.model` format: plain-text vertex/face meshes the engine and the"""

import json
import math
from pathlib import Path

import numpy as np

from . import colors, meshes

FORMAT = "fligmodel"
VERSION = 1

PRIMITIVES = ("box", "wedge", "cylinder", "cone", "plane", "sphere")


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
    """Vertices, uvs and triangles with the editing operations the model"""

    def __init__(self, name="model", verts=None, uvs=None, tris=None,
                 texture="white", color=(1.0, 1.0, 1.0), pivot=(0, 0, 0),
                 tex=None, uv=None, uv2=None, lightmap=None, painted=False,
                 objects=None):
        self.name = name
        self.texture = texture
        self.color = colors.rgb(color, (1.0, 1.0, 1.0))
        self.pivot = tuple(float(c) for c in pivot)
        self.verts = [[float(v) for v in p] for p in (verts or [])]
        self.uvs = [[float(c) for c in p] for p in (uvs or [])]
        self.tris = [[int(i) for i in t] for t in (tris or [])]
        self.tex = [colors.key(t) or None for t in (tex or [])]
        # a second uv channel from the unwrap, for lightmaps
        self.uv2 = [[float(c) for c in p] for p in (uv2 or [])]
        # a baked-light key and whether a painted atlas drives albedo
        self.lightmap = lightmap
        self.painted = bool(painted)
        # named parts, each claiming faces and its own sheet
        self.objects = [dict(o) for o in (objects or [])
                        if isinstance(o, dict)]
        # one whole-model sheet transform: tile, turn, slide
        uv = uv or {}
        self.uv_scale = [float(c) for c in (uv.get("scale") or (1.0, 1.0))]
        self.uv_offset = [float(c) for c in (uv.get("offset") or (0.0, 0.0))]
        self.uv_rot = float(uv.get("rot") or 0.0)
        self.path = None
        self._fix_lengths()
        self.align_objects()

    def uv_identity(self):
        """True when the sheet transform would change nothing."""
        return (abs(self.uv_scale[0] - 1.0) < 1e-6 and
                abs(self.uv_scale[1] - 1.0) < 1e-6 and
                abs(self.uv_offset[0]) < 1e-6 and
                abs(self.uv_offset[1]) < 1e-6 and
                abs(self.uv_rot) < 1e-6)

    # `texture` is canonicalised in, so every caller lands one key
    @property
    def texture(self):
        return self._texture

    @texture.setter
    def texture(self, value):
        self._texture = colors.key(value) or "white"

    def _fix_lengths(self):
        while len(self.uvs) < len(self.verts):
            self.uvs.append([0.0, 0.0])
        del self.uvs[len(self.verts):]
        if self.uv2:      # a second channel is padded only when it exists,
            while len(self.uv2) < len(self.verts):    # so `[]` still means
                self.uv2.append([0.0, 0.0])           # "this model has
            del self.uv2[len(self.verts):]            # no uv2 at all"
        keep = [i for i, t in enumerate(self.tris)
                if len(t) == 3 and all(0 <= j < len(self.verts) for j in t)]
        where = {old: new for new, old in enumerate(keep)}
        self.tris = [self.tris[i] for i in keep]
        self.tex = [(self.tex[i] if i < len(self.tex) else None)
                    for i in keep]
        for o in self.objects:          # a trimmed face list trims the
            got = []                    # object claims along with it
            for f in o.get("faces") or []:
                try:
                    got.append(where[int(f)])
                except (KeyError, TypeError, ValueError):
                    continue
            o["faces"] = got

    def align_tex(self):
        """Pad or trim per-face texture tags to one per face."""
        n = len(self.tris)
        while len(self.tex) < n:
            self.tex.append(None)
        del self.tex[n:]
        self.tex = [colors.key(t) or None for t in self.tex]
        return self.tex

    def align_objects(self):
        """Normalise the object list; every face sits in one."""
        if not self.objects:
            return self.objects
        n = len(self.tris)
        claimed = set()
        out = []
        for src in self.objects:
            faces = []
            for f in src.get("faces") or []:
                try:
                    i = int(f)
                except (TypeError, ValueError):
                    continue
                if 0 <= i < n and i not in claimed:
                    claimed.add(i)
                    faces.append(i)
            name = str(src.get("name") or "").strip() or \
                "object%d" % (len(out) + 1)
            while any(o["name"] == name for o in out):
                name = f"{name}#{len(out) + 1}"
            out.append({"name": name,
                        "faces": sorted(faces),
                        "texture": colors.key(src.get("texture")) or None,
                        "painted": bool(src.get("painted")),
                        "lightmap": src.get("lightmap") or None})
        spare = [f for f in range(n) if f not in claimed]
        if out and spare:
            out[0]["faces"] = sorted(out[0]["faces"] + spare)
        self.objects = out
        return out

    @property
    def has_objects(self):
        """True when the file is carved into named parts."""
        return bool(self.objects)

    def object_names(self):
        return [o["name"] for o in self.objects]

    def object_of_face(self, face):
        """The entry owning one face, or None."""
        for o in self.objects:
            if face in o["faces"]:
                return o
        return None

    def object_verts(self, name):
        """Every vertex index the named object's faces touch."""
        out = set()
        for o in self.objects:
            if o["name"] == str(name):
                for f in o["faces"]:
                    out.update(self.tris[f])
        return out

    def obj_bounds(self, name):
        """(min, max) corners over one object's vertices, or None."""
        idx = self.object_verts(name)
        pts = [self.verts[i] for i in idx if i < len(self.verts)]
        if not pts:
            return None
        lo = tuple(min(p[k] for p in pts) for k in range(3))
        hi = tuple(max(p[k] for p in pts) for k in range(3))
        return (lo, hi)

    def make_object(self, name, faces):
        """Carve faces out into a new named object."""
        name = str(name).strip()
        if not name or name in self.object_names():
            return None
        want = sorted({int(f) for f in faces
                       if isinstance(f, (int, float))
                       and 0 <= int(f) < len(self.tris)})
        if not want:
            return None
        self.align_objects()
        if not self.objects:      # the first split needs the implicit
            seed = self.name if self.name != name else "main"
            self.objects = [{"name": seed,
                             "faces": list(range(len(self.tris))),
                             "texture": None, "painted": False,
                             "lightmap": None}]
        mine = set(want)
        foreign, used = set(), set()
        for i, t in enumerate(self.tris):
            (used if i in mine else foreign).update(t)
        copies = {}
        for v in sorted(used & foreign):
            self.verts.append(list(self.verts[v]))
            self.uvs.append(list(self.uvs[v]))
            if self.uv2:
                self.uv2.append(list(self.uv2[v]))
            copies[v] = len(self.verts) - 1
        for i in mine:
            self.tris[i] = [copies.get(k, k) for k in self.tris[i]]
        for o in self.objects:
            o["faces"] = [f for f in o["faces"] if f not in mine]
        entry = {"name": name, "faces": want, "texture": None,
                 "painted": False, "lightmap": None}
        self.objects.append(entry)
        return entry

    def rename_object(self, old, new):
        """Rename an object; refused when the name is taken."""
        new = str(new).strip()
        if not new or new in self.object_names():
            return False
        for o in self.objects:
            if o["name"] == str(old):
                o["name"] = new
                return True
        return False

    def set_object_texture(self, name, key):
        """Give an object its own sheet; face tags step aside."""
        for o in self.objects:
            if o["name"] == str(name):
                o["texture"] = colors.key(key) or None
                return True
        return False

    def merge_objects(self, names):
        """Fold the named objects into the first one of them."""
        owners = self.align_objects()
        picked = [o for o in owners if o["name"] in
                  {str(n) for n in names}]
        if len(picked) < 2:
            return False
        sel = set()
        for o in picked:
            sel.update(o["faces"])
        drop = []
        for f in sorted(sel):
            for o in picked:
                if f in o["faces"]:
                    continue        # a part is never inside itself
                if self._face_inside(f, [g for g in o["faces"]
                                         if g != f]):
                    drop.append(f)
                    break
        if drop:
            self.delete_faces(sorted(set(drop)))
        primary = next(o for o in self.objects
                       if o["name"] == picked[0]["name"])
        for o in self.objects:
            if o is primary:
                continue
            if o["name"] in {p["name"] for p in picked
                             if p is not primary}:
                primary["faces"] = sorted(
                    set(primary["faces"]) | set(o["faces"]))
                o["faces"] = []
        self.objects = [o for o in self.objects
                        if o["faces"] or o is primary]
        vset = set()
        for f in primary["faces"]:
            vset.update(self.tris[f])
        self._weld_subset(vset, 1e-4)
        refs = set()
        for t in self.tris:
            refs.update(t)
        self.delete_vertices([i for i in range(len(self.verts))
                              if i not in refs])
        self.align_objects()
        return True

    def _face_inside(self, face, shell):
        """True when a face centre sits inside the others."""
        ctr = self.face_centre(face)
        n = self.face_normal(face)
        o = (ctr[0] + n[0] * 1e-3, ctr[1] + n[1] * 1e-3,
             ctr[2] + n[2] * 1e-3)
        hits = 0
        for g in shell:
            a, b, c = (self.verts[i] for i in self.tris[g])
            e1, e2 = _sub(b, a), _sub(c, a)
            p = _cross((0.0, 1.0, 0.0), e2)
            det = _dot(e1, p)
            if abs(det) < 1e-9:
                continue          # ray runs along the triangle's plane
            s = _sub(o, a)
            u = _dot(s, p) / det
            if u < 0.0 or u > 1.0:
                continue
            q = _cross(s, e1)
            v = _dot((0.0, 1.0, 0.0), q) / det
            if v < 0.0 or u + v > 1.0:
                continue
            t = _dot(e2, q) / det
            if t > 1e-7:
                hits += 1
        return hits % 2 == 1

    def _weld_subset(self, indices, eps):
        """Weld coincident vertices within one set only."""
        idx = sorted(i for i in set(indices) if i < len(self.verts))
        if len(idx) < 2:
            return
        uv2 = self._aligned_uv2()
        buckets, remap = {}, list(range(len(self.verts)))
        verts = list(self.verts)
        uvs = list(self.uvs)
        out2 = list(uv2) if uv2 else []
        for i in idx:
            key = tuple(round(c / eps) for c in self.verts[i])
            j = buckets.get(key)
            if j is None:
                buckets[key] = i
                continue
            remap[i] = j
            if self.uvs[j] == [0.0, 0.0] and self.uvs[i] != [0.0, 0.0]:
                uvs[j] = list(self.uvs[i])
                if out2:
                    out2[j] = list(uv2[i])
        if len({remap[i] for i in idx}) == len(idx):
            return                          # nothing sat on top
        tris, tex = [], []
        for t, k in zip(self.tris, self.align_tex()):
            a, b, c = (remap[i] for i in t)
            if len({a, b, c}) == 3:
                tris.append([a, b, c])
                tex.append(k)
        self.tris, self.tex = tris, tex
        used = set()
        for t in self.tris:
            used.update(t)
        where = {}
        nv, nu, n2 = [], [], []
        for i in sorted({remap[i] for i in range(len(verts))
                         if i in used}):
            where[i] = len(nv)
            nv.append(verts[i])
            nu.append(uvs[i])
            if out2:
                n2.append(out2[i])
        self.verts, self.uvs = nv, nu
        if out2:
            self.uv2 = n2
        self.tris = [[where[i] for i in t] for t in self.tris]
        self._sync_claims()

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
            tex=data.get("tex"),
            uv=data.get("uv"),
            uv2=data.get("uv2"),
            lightmap=data.get("lightmap"),
            painted=data.get("painted", False),
            objects=data.get("objects"),
        )

    def to_dict(self):
        d = {
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
        if any(self.align_tex()):        # only write tags that exist
            d["tex"] = list(self.tex)
        if self.objects:                 # named parts, only when carved
            rows = []
            for o in self.objects:
                r = {"name": o["name"], "faces": sorted(o["faces"])}
                if o["texture"]:
                    r["texture"] = o["texture"]
                if o["painted"]:
                    r["painted"] = True
                if o["lightmap"]:
                    r["lightmap"] = o["lightmap"]
                rows.append(r)
            d["objects"] = rows
        if self.uv2:                     # a second channel, when unwrapped
            d["uv2"] = [[round(c, 4) for c in p] for p in self.uv2]
        if self.lightmap:                # a baked-light texture, when set
            d["lightmap"] = self.lightmap
        if self.painted:                 # and only the flag that is on
            d["painted"] = True
        if not self.uv_identity():       # and only a transform that says
            d["uv"] = {                  # something
                "scale": [round(c, 4) for c in self.uv_scale],
                "offset": [round(c, 4) for c in self.uv_offset],
                "rot": round(self.uv_rot, 4),
            }
        return d

    def dumps(self):
        return json.dumps(self.to_dict(), indent=1)

    def save(self, path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.dumps(), encoding="utf-8")
        self.path = str(p)
        self.name = p.stem
        return p

    def meshdata(self, pos=(0, 0, 0), yaw=0.0, scale=(1.0, 1.0, 1.0),
                 tint=None, faces=None):
        """Flatten to render-ready vertices with per-face normals. The"""
        md = meshes.MeshData()
        if not self.tris:
            return md
        if isinstance(scale, (int, float)):
            scale = (float(scale),) * 3
        col = meshes.rgba(tuple(self.color if tint is None
                                else colors.rgb(tint, self.color)))
        verts = np.asarray(self.verts, np.float64)
        tri = np.asarray(self.tris, np.int64)
        if verts.ndim != 2 or verts.shape[1] != 3 or \
                tri.ndim != 2 or tri.shape[1] != 3 or not len(tri):
            return md
        c, s = math.cos(yaw), math.sin(yaw)
        local = verts * np.asarray(scale, np.float64)
        world = np.empty_like(local)
        world[:, 0] = c * local[:, 0] + s * local[:, 2] + float(pos[0])
        world[:, 1] = local[:, 1] + float(pos[1])
        world[:, 2] = -s * local[:, 0] + c * local[:, 2] + float(pos[2])
        # one normal per face, up when the face is degenerate
        n = np.cross(world[tri[:, 1]] - world[tri[:, 0]],
                     world[tri[:, 2]] - world[tri[:, 0]])
        length = np.sqrt((n * n).sum(axis=1))
        flat = length > 1e-9
        n[flat] /= length[flat, None]
        n[~flat] = (0.0, 1.0, 0.0)
        uvs = np.asarray(self.uvs, np.float64)
        if uvs.ndim != 2 or uvs.shape[0] != len(verts):
            uvs = np.zeros((len(verts), 2), np.float64)
        # uv2 ignores the sheet transform; it falls back to albedo
        uv2 = np.asarray(self.uv2, np.float64) if len(self.uv2) else None
        if uv2 is None or uv2.ndim != 2 or uv2.shape[0] != len(verts):
            uv2 = np.asarray(uvs, np.float64)
        if not self.uv_identity():
            # tile about the centre, turn, then slide
            u = (uvs[:, 0] - 0.5) * float(self.uv_scale[0])
            v = (uvs[:, 1] - 0.5) * float(self.uv_scale[1])
            if abs(self.uv_rot) > 1e-6:
                cr, sr = math.cos(self.uv_rot), math.sin(self.uv_rot)
                u, v = cr * u - sr * v, sr * u + cr * v
            uvs = np.stack([u + 0.5 + float(self.uv_offset[0]),
                            v + 0.5 + float(self.uv_offset[1])], axis=1)
        wide = tri.reshape(-1)
        tags = self.align_tex()
        tags = list(tags) + [None] * (len(tri) - len(tags))
        md.pos = world[wide].tolist()
        md.nrm = np.repeat(n, 3, axis=0).tolist()
        if not self.objects:
            # a painted model samples its atlas on uv2
            md.uv = (uv2 if self.painted else uvs)[wide].tolist()
            md.tex = tags[:len(tri)]
        else:
            owners = self.align_objects()
            face_obj = [None] * len(tri)
            for oi, o in enumerate(owners):
                for f in o["faces"]:
                    if 0 <= f < len(face_obj):
                        face_obj[f] = oi
            painted = np.fromiter((face_obj[f] is not None and
                                   owners[face_obj[f]]["painted"]
                                   for f in range(len(tri))),
                                  bool, len(tri))
            flags = np.repeat(painted, 3)
            md.uv = (np.where(flags[:, None], uv2[wide], uvs[wide])
                     if painted.any() else uvs[wide]).tolist()
            md.tex = [(owners[face_obj[f]]["texture"] or tags[f])
                      if face_obj[f] is not None else tags[f]
                      for f in range(len(tri))]
            if any(o["lightmap"] for o in owners):
                # one lightmap key per face; None inherits the model's
                md.lms = [owners[face_obj[f]]["lightmap"]
                          if face_obj[f] is not None else None
                          for f in range(len(tri))]
        md.uv2 = uv2[wide].tolist()
        md.lightmap = self.lightmap
        md.col = [col] * len(wide)
        md.idx = list(range(len(wide)))
        if faces is not None:
            md = self._restrict_md(md, sorted(
                {int(f) for f in faces if 0 <= int(f) < len(tri)}))
        return md

    @staticmethod
    def _restrict_md(md, keep):
        """A mesh pared back to `keep`'s triangles (ascending face"""
        if len(keep) == len(md.idx) // 3:
            return md
        widx = []
        for f in keep:
            widx += [3 * f, 3 * f + 1, 3 * f + 2]
        for name in ("pos", "nrm", "uv", "uv2", "col"):
            rows = getattr(md, name)
            if rows:
                setattr(md, name, [rows[i] for i in widx])
        if md.tex:
            md.tex = [md.tex[f] for f in keep]
        if md.lms:
            md.lms = [md.lms[f] for f in keep]
        md.idx = list(range(len(widx)))
        return md

    def mesh_groups(self, pos=(0, 0, 0), yaw=0.0, scale=(1.0, 1.0, 1.0),
                    tint=None):
        """meshdata() split by surface: [(texture key, MeshData)]."""
        return self.meshdata(pos, yaw, scale, tint).texture_groups(
            self.texture)

    def add_meshdata(self, md):
        """Append generated geometry (meshes builders) as raw triangles."""
        base = len(self.verts)
        self.verts += [list(p) for p in md.pos]
        self.uvs += [list(p) for p in md.uv]
        for i in range(0, len(md.idx), 3):
            self.add_face(md.idx[i] + base, md.idx[i + 1] + base,
                          md.idx[i + 2] + base)
        self.align_tex()
        return self

    def clone(self):
        out = Model(self.name, self.verts, self.uvs, self.tris,
                    self.texture, self.color, self.pivot,
                    tex=list(self.align_tex()),
                    uv2=list(self.uv2), lightmap=self.lightmap,
                    painted=self.painted,
                    objects=[dict(o, faces=list(o["faces"]))
                             for o in self.objects])
        out.uv_scale = list(self.uv_scale)
        out.uv_offset = list(self.uv_offset)
        out.uv_rot = self.uv_rot
        return out

    def snapshot(self):
        return {"verts": [list(v) for v in self.verts],
                "uvs": [list(p) for p in self.uvs],
                "tris": [list(t) for t in self.tris],
                "tex": list(self.align_tex()),
                "texture": self.texture,
                "color": tuple(self.color),
                "uv2": [list(p) for p in self.uv2],
                "lightmap": self.lightmap,
                "painted": self.painted,
                "objects": [dict(o, faces=list(o["faces"]))
                            for o in self.objects],
                "uv": (list(self.uv_scale), list(self.uv_offset),
                       self.uv_rot)}

    def restore(self, snap):
        self.verts = [list(v) for v in snap["verts"]]
        self.uvs = [list(p) for p in snap["uvs"]]
        self.tris = [list(t) for t in snap["tris"]]
        self.tex = list(snap.get("tex") or [])
        self.align_tex()
        self.texture = snap.get("texture", self.texture)
        self.color = tuple(snap.get("color", self.color))
        self.uv2 = [list(p) for p in (snap.get("uv2") or [])]
        self.lightmap = snap.get("lightmap", self.lightmap)
        self.painted = snap.get("painted", self.painted)
        self.objects = [dict(o, faces=list(o["faces"]))
                        for o in (snap.get("objects") or [])]
        uv = snap.get("uv")
        if uv:
            self.uv_scale, self.uv_offset, self.uv_rot = \
                list(uv[0]), list(uv[1]), float(uv[2])

    def faces_using(self, indices):
        s = set(indices)
        return [i for i, t in enumerate(self.tris) if s & set(t)]

    def delete_faces(self, faces):
        drop = set(faces)
        self.align_tex()
        where = {}
        tris, tex = [], []
        for i, (t, k) in enumerate(zip(self.tris, self.tex)):
            if i not in drop:
                where[i] = len(tris)
                tris.append(t)
                tex.append(k)
        self.tris, self.tex = tris, tex
        for o in self.objects:          # claims follow the new indices
            o["faces"] = [where[f] for f in o["faces"] if f in where]

    def _aligned_uv2(self):
        """uv2 rows, one per vertex, or [] when absent."""
        if not self.uv2:
            return []
        pad = [0.0, 0.0]
        return [list(self.uv2[i]) if i < len(self.uv2)
                else list(pad) for i in range(len(self.verts))]

    def delete_vertices(self, indices):
        drop = set(indices)
        if not drop:
            return
        self.align_tex()
        kept, fwhere = [], {}
        for i, (t, k) in enumerate(zip(self.tris, self.tex)):
            if not (drop & set(t)):
                fwhere[i] = len(kept)
                kept.append((t, k))
        self.tris = [t for t, k in kept]
        self.tex = [k for t, k in kept]
        uv2 = self._aligned_uv2()
        remap, verts, uvs, out2 = {}, [], [], []
        for i, (v, uv) in enumerate(zip(self.verts, self.uvs)):
            if i in drop:
                continue
            remap[i] = len(verts)
            verts.append(v)
            uvs.append(uv)
            if uv2:
                out2.append(uv2[i])
        self.verts, self.uvs = verts, uvs
        if uv2:
            self.uv2 = out2
        self.tris = [[remap[i] for i in t] for t in self.tris]
        self._sync_claims(fwhere)

    def _sync_claims(self, remap=None):
        """Put every object's face list back in step with `tris`."""
        if not self.objects:
            return
        if remap is None:
            remap = {i: i for i in range(len(self.tris))}
        for o in self.objects:
            o["faces"] = sorted({remap[f] for f in o["faces"]
                                 if f in remap})

    def add_vertex(self, pos, uv=(0.0, 0.0)):
        self.verts.append([float(c) for c in pos])
        self.uvs.append([float(uv[0]), float(uv[1])])
        return len(self.verts) - 1

    def add_face(self, a, b, c, uvs=None, tex=None):
        if len({a, b, c}) < 3:
            return None
        if uvs is None:
            uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        for k, vi in enumerate((a, b, c)):
            while len(self.uvs) <= vi:
                self.uvs.append([0.0, 0.0])
            if self.uvs[vi] == [0.0, 0.0]:
                self.uvs[vi] = [float(uvs[k][0]), float(uvs[k][1])]
        fid = len(self.tris)
        self.tris.append([a, b, c])
        self.tex.append(tex or None)
        if self.uv2:
            while len(self.uv2) < len(self.tris):   # never split the
                self.uv2.append([0.0, 0.0])         # two parallel lists
        if self.objects:      # a brand new face joins the first part
            self.objects[0]["faces"].append(fid)
        return fid

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

    def face_texture(self, face):
        """The texture key a face actually draws with."""
        tags = self.align_tex()
        tag = tags[face] if 0 <= face < len(tags) else None
        return tag or self.texture

    def set_face_texture(self, face, key):
        """Give a face its own texture: name or colour."""
        tags = self.align_tex()
        if 0 <= face < len(tags):
            tags[face] = colors.key(key) or None
        return self

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
        """Lift a triangle into a prism with three sides."""
        t = list(self.tris[face])
        tag = self.align_tex()[face]
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
            before = len(self.tris)
            self._auto_quad(ids, _sub(mid, centre))
            for i in range(before, len(self.tris)):
                self.tex[i] = tag
                if self.objects:      # the sides wear the source's look
                    self.objects[0]["faces"].append(i)
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
        tris, tex = [], []
        for t, k in zip(self.tris, self.align_tex()):
            a, b, c = (remap[i] for i in t)
            if len({a, b, c}) == 3:
                tris.append([a, b, c])
                tex.append(k)
        self.tris, self.tex = tris, tex
        self._sync_claims()

    def auto_uv(self, faces=None):
        """Planar UV per face, projected along its dominant axis.

        This is a fallback for geometry that arrived with no sheet of its
        own. A primitive unwraps itself per metre, and re-projecting that
        by the model's bounds squeezes every narrow face into a slice of
        the picture - the stretch a round side shows after it. `faces`
        limits the pass to the triangles named, so a part can be
        re-unwrapped without disturbing the parts beside it.
        """
        b = self.bounds() or ((0, 0, 0), (1, 1, 1))
        size = [max(1e-4, b[1][i] - b[0][i]) for i in range(3)]
        if faces is None:
            wanted = range(len(self.tris))
        else:
            wanted = sorted({int(f) for f in faces
                             if 0 <= int(f) < len(self.tris)})
        for fi in wanted:
            t = self.tris[fi]
            pts = [self.verts[i] for i in t]
            n = _normal(pts[0], pts[1], pts[2])
            axis = max(range(3), key=lambda k: abs(n[k]))
            ua, va = [(1, 2), (0, 2), (0, 1)][axis]
            for k, vi in enumerate(t):
                u = (pts[k][ua] - b[0][ua]) / size[ua]
                v = (pts[k][va] - b[0][va]) / size[va]
                self.uvs[vi] = [u, v]

    def _auto_quad(self, ids, hint):
        a, b, c, d = (self.verts[i] for i in ids)
        if _dot(_normal(a, b, c), hint) < 0.0:
            ids = [ids[3], ids[2], ids[1], ids[0]]
        self.tris.append([ids[0], ids[1], ids[2]])
        self.tris.append([ids[0], ids[2], ids[3]])
        self.tex += [None, None]

    def _auto_tri(self, ids, hint):
        a, b, c = (self.verts[i] for i in ids)
        if _dot(_normal(a, b, c), hint) < 0.0:
            ids = [ids[0], ids[2], ids[1]]
        self.tris.append(list(ids))
        self.tex.append(None)

    def append(self, other, offset=(0.0, 0.0, 0.0)):
        """Merge another model's geometry in, offset in model space."""
        base = len(self.verts)
        self.verts += [[v[0] + offset[0], v[1] + offset[1],
                        v[2] + offset[2]] for v in other.verts]
        self.uvs += [list(p) for p in other.uvs]
        blend = other.texture if other.texture != self.texture else None
        for t, k in zip(other.tris, other.align_tex()):
            self.tris.append([i + base for i in t])
            self.tex.append(k or blend)
        if self.objects:      # bolted-in geometry joins the first part
            self.objects[0]["faces"] += list(range(
                len(self.tris) - len(other.tris), len(self.tris)))
        return self

    def add_primitive(self, kind, size=1.0, offset=(0.0, 0.0, 0.0)):
        gen = _PRIMITIVE_FUNCS.get(kind)
        if gen is None:
            raise ValueError(f"unknown primitive '{kind}'")
        other = gen(size)
        other.texture = self.texture    # the new piece wears my texture
        self.append(other, offset)
        return self


def _quad(m, ids, hint, uvs=None):
    a, b, c, d = (m.verts[i] for i in ids)
    if _dot(_normal(a, b, c), hint) < 0.0:
        ids = [ids[3], ids[2], ids[1], ids[0]]
        uvs = list(reversed(uvs)) if uvs else None
    if uvs is None:
        uvs = ((0, 0), (1, 0), (1, 1), (0, 1))
    m.tris.append([ids[0], ids[1], ids[2]])
    m.tris.append([ids[0], ids[2], ids[3]])
    m.tex += [None, None]
    for vi, uv in zip(ids, uvs):
        m.uvs[vi] = [float(uv[0]), float(uv[1])]


def _tri(m, ids, hint, uvs=((0, 0), (1, 0), (1, 1))):
    a, b, c = (m.verts[i] for i in ids)
    if _dot(_normal(a, b, c), hint) < 0.0:
        ids = [ids[0], ids[2], ids[1]]
        uvs = (uvs[0], uvs[2], uvs[1])
    m.tris.append(list(ids))
    m.tex.append(None)
    for vi, uv in zip(ids, uvs):
        m.uvs[vi] = [float(uv[0]), float(uv[1])]


def _panel(m, r, y0, y1, seg, i, span, v0=0.0, v1=1.0):
    """The four corners of barrel panel `i`, new verts with their own u.

    A corner shared with the next panel can hold only one of the two u it
    is drawn at - 1 and 0 across the seam - and whichever panel is written
    last wins, which flattens the first one into a line. Copying costs
    four vertices and saves the picture. Returns (ids, uv) so the caller
    hands the same sheet back to `_quad` instead of its default 0..1.
    """
    u0, u1 = i / seg * span, (i + 1) / seg * span
    out, sheet = [], []
    for a, y, u, v in ((i, y0, u0, v0), (i + 1, y0, u1, v0),
                       (i + 1, y1, u1, v1), (i, y1, u0, v1)):
        turn = 2.0 * math.pi * a / seg
        out.append(m.add_vertex((math.cos(turn) * r, y, math.sin(turn) * r),
                                (u, v)))
        sheet.append((u, v))
    return out, sheet


def _disc(m, r, y, seg, up, middle, unit=1.0):
    """A cap of `seg` triangles with corners of its own, sheet and all.

    The rim is copied rather than shared with the barrel on purpose: a cap
    reusing the side's corners inherits the side's unwrap, which runs down
    the wall and not across the disc, leaving every triangle a line.
    `unit` is the world size one sheet covers, so a cap is drawn at the
    same density as the wall beside it.
    """
    unit = max(1e-6, unit)
    centre = m.add_vertex((0.0, y, 0.0), middle)
    rim = []
    for i in range(seg):
        a = 2.0 * math.pi * i / seg
        rim.append(m.add_vertex((math.cos(a) * r, y, math.sin(a) * r),
                                (middle[0] + math.cos(a) * r / unit,
                                 middle[1] + math.sin(a) * r / unit)))
    for i in range(seg):
        j = (i + 1) % seg
        _tri(m, [rim[i], rim[j], centre], (0, up, 0),
             (m.uvs[rim[i]], m.uvs[rim[j]], middle))
    return m


def _faces(m, corners, faces, sheets=None):
    """Build `faces` over `corners`, copying them so each unwraps alone."""
    for n, (ids, hint) in enumerate(faces):
        made = [m.add_vertex(corners[i]) for i in ids]
        one = None if sheets is None else sheets[n]
        if len(ids) == 3:
            _tri(m, made, hint) if one is None else _tri(m, made, hint, one)
        else:
            _quad(m, made, hint, one)


def box_model(size=1.0, name="box"):
    """Cube with its base on y = 0; a side per face, so all six unwrap.

    Corners are copied per face on purpose. Six sides sharing eight corner
    vertices can only hold one unwrap of each corner, so whichever face is
    written last wins and the rest flatten to a line - the two stretched
    sides an editor shows on a shared-corner box.
    """
    m = Model(name)
    h = float(size)
    x = z = h / 2.0
    c = [(-x, 0, -z), (x, 0, -z), (x, h, -z), (-x, h, -z),
         (-x, 0, z), (x, 0, z), (x, h, z), (-x, h, z)]
    _faces(m, c, (((4, 5, 6, 7), (0, 0, 1)),
                  ((1, 0, 3, 2), (0, 0, -1)),
                  ((5, 1, 2, 6), (1, 0, 0)),
                  ((0, 4, 7, 3), (-1, 0, 0)),
                  ((7, 6, 2, 3), (0, 1, 0)),
                  ((0, 1, 5, 4), (0, -1, 0))))
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
    """Ramp: flat on the ground, rising toward +Z, a face at a time."""
    m = Model(name)
    h = float(size)
    x = z = h / 2.0
    slope = math.hypot(h, h) / h        # the ramp is 2 m long for 1 m down
    c = [(-x, 0, -z), (x, 0, -z), (x, 0, z), (-x, 0, z),
         (x, h, z), (-x, h, z)]
    _faces(m, c, (((0, 1, 2, 3), (0, -1, 0)),      # ground
                  ((0, 1, 4, 5), (0, 0.4, -1)),    # ramp
                  ((2, 3, 5, 4), (0, 0, 1)),       # tall back
                  ((1, 2, 4), (1, 0, 0)),          # +x cheek
                  ((0, 3, 5), (-1, 0, 0))),        # -x cheek
           sheets=(None, ((0, 0), (1, 0), (1, slope), (0, slope)),
                   None, None, None))
    return m


def cylinder_model(size=1.0, seg=12, name="cylinder"):
    """Y-up cylinder, base on y = 0, its sheet square per metre.

    The barrel wraps `2 * pi * r / h` sheets, not one: a single sheet over
    a tall narrow drum squashes the picture round its middle, which is the
    sideways stretch a cylinder shows next to a box. The caps are built
    with `_disc` so their sheet runs across the disc.
    """
    m = Model(name)
    h = float(size)
    r = h * 0.35
    span = 2.0 * math.pi * r / h
    for i in range(seg):
        corners, sheet = _panel(m, r, 0.0, h, seg, i, span)
        _quad(m, corners,
              (math.cos(2 * math.pi * (i + 0.5) / seg), 0,
               math.sin(2 * math.pi * (i + 0.5) / seg)), sheet)
    _disc(m, r, h, seg, 1, (0.5 * span, 0.5), h)
    _disc(m, r, 0.0, seg, -1, (0.5 * span, 0.5), h)
    return m


def cone_model(size=1.0, seg=10, name="cone"):
    """Cone on its base, its sheet measured round the base and up the slant."""
    m = Model(name)
    h = float(size)
    r = h * 0.45
    span = 2.0 * math.pi * r / h
    slant = math.hypot(r, h) / h        # one sheet up the slope, not up y
    for i in range(seg):
        a = 2.0 * math.pi * i / seg
        u0, u1 = i / seg * span, (i + 1) / seg * span
        base, sheet = [], []
        for turn, u in ((a, u0), (a + 2.0 * math.pi / seg, u1)):
            base.append(m.add_vertex((math.cos(turn) * r, 0.0,
                                      math.sin(turn) * r), (u, 0.0)))
            sheet.append((u, 0.0))
        apex = m.add_vertex((0.0, h, 0.0), ((u0 + u1) * 0.5, slant))
        sheet.append(((u0 + u1) * 0.5, slant))
        _tri(m, [base[0], base[1], apex],
             (math.cos(a), 0.25, math.sin(a)), tuple(sheet))
    _disc(m, r, 0.0, seg, -1, (0.5 * span, 0.5), h)
    return m


def sphere_model(size=1.0, seg=12, rings=6, name="sphere"):
    """UV sphere on its base, one sheet round and one pole to pole.

    Each quad carries corners of its own and the poles are triangles, so no
    seam or pole corner has to hold two sheet positions at once - which is
    what used to flatten the sphere's back into a line. A latitude/longitude
    ball cannot be square everywhere: the rings narrow while `u` does not,
    so a picture is widest at the equator, as it is on every globe. Making
    `u` narrow with the ring instead only pinches every seam together.
    """
    m = Model(name)
    r = float(size) / 2.0

    def node(ri, si):
        """Position and sheet coordinate of one node of the grid."""
        phi = math.pi * ri / rings
        turn = 2.0 * math.pi * si / seg
        rad = math.sin(phi) * r
        return ((math.cos(turn) * rad, r - math.cos(phi) * r,
                 math.sin(turn) * rad),
                (si / seg, 1.0 - ri / rings))

    def spot(ri, si):
        pos, uv = node(ri, si)
        return m.add_vertex(pos, uv), uv

    for ri in range(rings):
        for si in range(seg):
            if ri == 0 or ri == rings - 1:
                # a pole row is one triangle: the other corner of the quad
                # would be the same point twice, and the pole takes the
                # middle of the arc it fans over rather than a corner u
                low, top = (1, 0) if ri == 0 else (rings - 1, rings)
                a, au = spot(low, si)
                b, bu = spot(low, si + 1)
                _pos, _uv = node(top, 0)
                tip = ((au[0] + bu[0]) * 0.5, _uv[1])
                c = m.add_vertex(_pos, tip)
                hint = (m.verts[a][0], m.verts[a][1] - r, m.verts[a][2])
                _tri(m, [a, b, c], hint, (au, bu, tip))
                continue
            a, au = spot(ri, si)
            b, bu = spot(ri, si + 1)
            c, cu = spot(ri + 1, si + 1)
            d, du = spot(ri + 1, si)
            hint = (m.verts[a][0], m.verts[a][1] - r, m.verts[a][2])
            _quad(m, [a, b, c, d], hint, (au, bu, cu, du))
    return m


_PRIMITIVE_FUNCS = {
    "box": box_model,
    "plane": plane_model,
    "wedge": wedge_model,
    "cylinder": cylinder_model,
    "cone": cone_model,
    "sphere": sphere_model,
}


def new_model(kind="box", size=1.0, texture="white", name=None, tint=None):
    # `name` must be a keyword: cylinder/cone/sphere take `seg` next
    model = _PRIMITIVE_FUNCS[kind](size, name=name or kind)
    model.texture = texture
    if tint is not None:
        # a coloured prop is the model's own `color`, no sheet
        model.color = colors.rgb(tint, model.color)
    return model


FORMAT2D = "fligmodel2d"
VERSION2D = 1


class Model2D:
    """A flat, riggable 2D model: cutout parts and keyframe tracks."""

    def __init__(self, name="model2d", size=(64.0, 64.0), texture=None,
                 pivot=(0.5, 0.5), parts=None, tracks=None):
        self.name = str(name)
        self.size = [float(size[0]), float(size[1])]
        self.texture = colors.key(texture)
        self.pivot = [float(pivot[0]), float(pivot[1])]
        self.parts = [self._part(p) for p in (parts or [])]
        self.tracks = [dict(t) for t in (tracks or [])]
        self.path = None

    @staticmethod
    def _part(part):
        """Copy a part dict, texture spelled as a key."""
        got = dict(part)
        if "texture" in got:
            got["texture"] = colors.key(got["texture"])
        return got

    def part(self, name):
        """The named part dict, or None."""
        for p in self.parts:
            if p.get("name") == name:
                return p
        return None

    @classmethod
    def load(cls, path):
        p = Path(path)
        model = cls.loads(p.read_text(encoding="utf-8"), p.stem)
        model.path = str(p)
        return model

    @classmethod
    def loads(cls, text, name="model2d"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("model2d file must contain a JSON object")
        return cls(
            name=data.get("name") or name,
            size=data.get("size") or (64.0, 64.0),
            texture=data.get("texture"),
            pivot=data.get("pivot") or (0.5, 0.5),
            parts=data.get("parts") or [],
            tracks=data.get("tracks") or [],
        )

    def to_dict(self):
        return {
            "format": FORMAT2D,
            "version": VERSION2D,
            "name": self.name,
            "size": [round(c, 4) for c in self.size],
            "texture": self.texture,
            "pivot": [round(c, 4) for c in self.pivot],
            "parts": self.parts,
            "tracks": self.tracks,
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


def new_model2d(name=None, size=(64.0, 64.0), texture=None):
    """A blank 2D model: one body part."""
    return Model2D(name=name or "model2d", size=size, texture=texture,
                   parts=[{"name": "body", "texture": texture,
                           "uv": [0.0, 0.0, 1.0, 1.0],
                           "pos": [0.0, 0.0], "rot": 0.0,
                           "scale": [1.0, 1.0], "parent": None}],
                   tracks=[])
