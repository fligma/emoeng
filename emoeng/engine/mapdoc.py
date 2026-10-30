"""Map documents: `maps/<name>.map3d` and `.map2d`, one level per file.

A map keeps a model's geometry keys untouched - verts, uvs, tris, tex,
named parts - and adds what a level needs: the nodes it places, where a
player starts, and how its faces stop a body. An old `.map3d` that has
only geometry still loads: it simply places nothing.
"""

import json
import os
from pathlib import Path

from . import model as modelmod
from . import scenedoc

MAP3D_EXT = ".map3d"
MAP2D_EXT = ".map2d"
MAP_EXTS = (MAP3D_EXT, MAP2D_EXT)
KINDS = ("map3d", "map2d")

FORMAT = "fligmap"
VERSION = 2

# how a map's own faces stop a moving body
COLLISIONS = ("mesh", "boxes", "none")

MAP_HELP = ("a map document: verts, uvs and tris are the level's parts, "
            "nodes are what it places, spawn is where a player starts")

# the geometry half, spelled exactly as a model file spells it
GEOMETRY_KEYS = ("texture", "color", "pivot", "verts", "uvs", "tris", "tex",
                 "uv2", "lightmap", "painted", "objects", "uv")
# what a map adds to that
MAP_KEYS = ("kind", "nodes", "spawn", "spawn_yaw", "collision", "overrides")


def kind_of(path):
    """'map3d' or 'map2d' for a document path, or None."""
    suffix = Path(path).suffix.lower()
    if suffix == MAP3D_EXT:
        return "map3d"
    if suffix == MAP2D_EXT:
        return "map2d"
    return None


def ext_of(kind):
    """The extension one map kind is filed under."""
    return MAP2D_EXT if str(kind).lower() in ("2d", "map2d") else MAP3D_EXT


def kind_name(kind):
    """'map3d' or 'map2d' from any spelling of the kind."""
    return "map2d" if str(kind).lower() in ("2d", "map2d") else "map3d"


def blank(name, kind="map3d"):
    """A fresh map document: no geometry, nothing placed."""
    return {"format": FORMAT,
            "version": VERSION,
            "kind": kind_name(kind),
            "_help": MAP_HELP,
            "name": str(name),
            "texture": "white",
            "color": [1.0, 1.0, 1.0],
            "pivot": [0.0, 0.0, 0.0],
            "verts": [],
            "uvs": [],
            "tris": [],
            "objects": [],
            "nodes": [],
            "collision": "mesh"}


def load(path, kind=None):
    """Read a map document, filling in the fields every reader expects."""
    path = Path(path)
    kind = kind_name(kind or kind_of(path) or "map3d")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    if not isinstance(raw, dict):
        return blank(path.stem, kind)
    doc = dict(raw)
    doc["kind"] = kind_name(doc.get("kind") or kind)
    doc["name"] = str(doc.get("name") or path.stem)
    doc["format"] = FORMAT
    doc["version"] = VERSION
    doc.setdefault("_help", MAP_HELP)
    if not isinstance(doc.get("nodes"), list):
        doc["nodes"] = []
    if not isinstance(doc.get("overrides"), dict):
        doc["overrides"] = {}
    if str(doc.get("collision") or "") not in COLLISIONS:
        doc["collision"] = "mesh"
    return doc


def save(path, doc):
    """Write a map document atomically, and hand the path back."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in doc.items() if not str(k).startswith("__")}
    payload["format"] = FORMAT
    payload["version"] = VERSION
    payload["kind"] = kind_name(payload.get("kind"))
    payload.setdefault("nodes", [])
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def collision_of(doc, kind=None):
    """How a map's own faces stop a body, settled for its kind.

    A flat level has no triangles to sweep, so `"mesh"` on a
    `.map2d` means one rectangle per part, as it always did.
    """
    got = str((doc or {}).get("collision") or "")
    if got not in COLLISIONS:
        got = "mesh"
    if got == "mesh" and kind_name(kind or (doc or {}).get("kind")) == "map2d":
        return "boxes"
    return got


def geometry(doc):
    """The geometry half of a map document, as a model file would read it."""
    return {k: doc.get(k) for k in GEOMETRY_KEYS if k in doc}


def model_of(doc, name=None):
    """The map's carved mesh, loaded as an engine Model."""
    part = geometry(doc)
    return modelmod.Model(
        name=name or str(doc.get("name") or "map"),
        verts=part.get("verts") or [],
        uvs=part.get("uvs") or [],
        tris=part.get("tris") or [],
        texture=part.get("texture", "white"),
        color=part.get("color", (1.0, 1.0, 1.0)),
        pivot=part.get("pivot", (0.0, 0.0, 0.0)),
        tex=part.get("tex"),
        uv=part.get("uv"),
        uv2=part.get("uv2"),
        lightmap=part.get("lightmap"),
        painted=part.get("painted", False),
        objects=part.get("objects"),
    )


def with_model(doc, model):
    """A map document's geometry half rewritten from a live Model."""
    out = dict(doc)
    part = model.to_dict()
    part.pop("format", None)
    part.pop("version", None)
    out.update(part)
    out["format"] = FORMAT
    out["version"] = VERSION
    out["kind"] = kind_name(out.get("kind"))
    out["_help"] = MAP_HELP
    out.setdefault("nodes", [])
    return out


def nodes(doc):
    """The entries a map places, created on first use."""
    got = doc.get("nodes")
    if not isinstance(got, list):
        got = []
        doc["nodes"] = got
    return got


def parts(doc):
    """The map's named parts, or one implicit whole for an uncarved file."""
    got = geometry(doc).get("objects")
    return got if isinstance(got, list) else []


def part_names(doc):
    """The part names a map can be re-dressed by."""
    return [str(p.get("name")) for p in parts(doc) if p.get("name")]


def part_faces(doc, name):
    """The face indices one named part owns."""
    for part in parts(doc):
        if part.get("name") == str(name):
            return list(part.get("faces") or ())
    return []


def spawn_of(doc):
    """A map's player start as ((x, y, z), yaw), or (None, 0.0)."""
    raw = doc.get("spawn")
    if not isinstance(raw, (list, tuple)) or not raw:
        return None, 0.0
    try:
        pos = [float(c) for c in raw]
    except (TypeError, ValueError):
        return None, 0.0
    if len(pos) == 2:
        pos.append(0.0)
    try:
        yaw = float(doc.get("spawn_yaw") or 0.0)
    except (TypeError, ValueError):
        yaw = 0.0
    return tuple(pos[:3]), yaw


def set_spawn(doc, pos=None, yaw=0.0):
    """Record where a player starts, or clear it."""
    if pos is None:
        doc.pop("spawn", None)
        doc.pop("spawn_yaw", None)
        return doc
    doc["spawn"] = [round(float(c), 4) for c in pos]
    doc["spawn_yaw"] = round(float(yaw or 0.0), 4)
    return doc


def walk(doc):
    """Every placed entry, parents before their nodes."""
    def rows(items, parent, depth):
        for entry in items:
            if not isinstance(entry, dict):
                continue
            yield entry, parent, depth
            kids = entry.get("children")
            if isinstance(kids, list):
                for row in rows(kids, entry, depth + 1):
                    yield row
    return rows(nodes(doc), None, 0)


def placed(doc, name):
    """One placed entry by id, or None."""
    for entry, _parent, _depth in walk(doc):
        if entry.get("id") == name:
            return entry
    return None


def parent_of(doc, name):
    """The entry a node is filed under, or None."""
    for entry, parent, _depth in walk(doc):
        if entry.get("id") == name:
            return parent
    return None


def add_placed(doc, entry, parent=None):
    """Append a placed entry, replacing one with the same id."""
    items = scenedoc.children(parent) if isinstance(parent, dict) \
        else nodes(doc)
    name = entry.get("id")
    for i, old in enumerate(items):
        if isinstance(old, dict) and old.get("id") == name:
            items[i] = entry
            return doc
    items.append(entry)
    return doc


def remove_placed(doc, name):
    """Take a placed entry and its branch out."""
    _cut(nodes(doc), name)
    return doc


def _cut(items, name):
    """Drop one entry by id at any depth."""
    keep = []
    for entry in items:
        if not isinstance(entry, dict):
            keep.append(entry)
            continue
        if entry.get("id") == name:
            continue
        kids = entry.get("children")
        if isinstance(kids, list):
            _cut(kids, name)
            if not kids:
                entry.pop("children", None)
        keep.append(entry)
    items[:] = keep


def describe(doc):
    """A one-line account of what a map carries."""
    count = len(parts(doc))
    return f"{doc.get('kind', 'map3d')} '{doc.get('name')}' " \
           f"{count} part(s), {len(nodes(doc))} node(s)"
