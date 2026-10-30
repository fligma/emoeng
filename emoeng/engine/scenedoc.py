"""Scene, object and shader documents: `scenes/*.scene`, `objects/*.obj3d`."""

import json
import os
from pathlib import Path

from . import shaders as shadermod

FORMAT = 1

SCENE_EXT = ".scene"
# an object's extension is its dimension
OBJECT3D_EXT = ".obj3d"
OBJECT2D_EXT = ".obj2d"
OBJECT_EXT = ".object"        # the old single spelling, still read
OBJECT_EXTS = (OBJECT3D_EXT, OBJECT2D_EXT, OBJECT_EXT)

# an entity is scripted, with behaviour: health, AI, a will
ENT3D_EXT = ".ent3d"
ENT2D_EXT = ".ent2d"
ENTITY_EXTS = (ENT3D_EXT, ENT2D_EXT)

# the two model kinds: solid mesh, flat cutout rig
MODEL3D_EXT = ".model3d"
MODEL2D_EXT = ".model2d"
MODEL_EXT = ".model"          # the old spelling of MODEL3D_EXT, still read

# a model in `maps/`; it builds its collider
MAP3D_EXT = ".map3d"
MAP2D_EXT = ".map2d"
MAP_EXTS = (MAP3D_EXT, MAP2D_EXT)

# a shader document: mode and knobs plus its class
SHADER_EXT = ".shader"
SHADER_MODES = shadermod.MODES

# scene document kind to the class a scriptless document builds
SCENE_KINDS = {"scene3d": "Scene3D", "scene2d": "Scene2D",
               "sceneui": "SceneUI"}

# every type you can create, in one table
NODE_TYPES = (
    ("object3d", "Object3D", "Objects", "object3d", "3d", "Object3D"),
    ("object2d", "Object2D", "Objects", "object2d", "2d", "Object2D"),
    ("ui", "UIObject", "Objects", "ui", "2d", "UIObject"),
    ("model3d", "Model3D", "Pictures", "object3d", "3d", "Model3D"),
    ("map3d", "Map3D", "Pictures", "object3d", "3d", "Map3D"),
    ("map2d", "Map2D", "Pictures", "object2d", "2d", "Map2D"),
    ("sprite2d", "Sprite2D", "Pictures", "object2d", "2d", "Sprite2D"),
    ("collision3d", "Collision3D", "Physics", "object3d", "3d",
     "Collision3D"),
    ("hitbox3d", "Hitbox3D", "Physics", "object3d", "3d", "Hitbox3D"),
    ("trigger3d", "Trigger3D", "Physics", "object3d", "3d", "Trigger3D"),
    ("collision2d", "Collision2D", "Physics", "object2d", "2d",
     "Collision2D"),
    ("hitbox2d", "Hitbox2D", "Physics", "object2d", "2d", "Hitbox2D"),
    ("trigger2d", "Trigger2D", "Physics", "object2d", "2d", "Trigger2D"),
    ("entity3d", "Entity3D", "Entities", "entity3d", "3d", "Entity3D"),
    ("entity2d", "Entity2D", "Entities", "entity2d", "2d", "Entity2D"),
    ("player3d", "Player3D", "Entities", "entity3d", "3d", "Player3D"),
    ("player2d", "Player2D", "Entities", "entity2d", "2d", "Player2D"),
    ("camera3d", "Camera3D", "Views", "object3d", "3d", None),
    ("camera2d", "Camera2D", "Views", "object2d", "2d", None),
    ("screen3d", "Screen3D", "Views", "object3d", "3d", "Screen3D"),
    ("screen2d", "Screen2D", "Views", "object2d", "2d", "Screen2D"),
    ("light3d", "Light3D", "Lights", "object3d", "3d", "LightNode3D"),
    ("omnilight3d", "OmniLight3D", "Lights", "object3d", "3d",
     "OmniLight3D"),
    ("spotlight3d", "SpotLight3D", "Lights", "object3d", "3d",
     "SpotLight3D"),
    ("directionallight3d", "DirectionalLight3D", "Lights", "object3d",
     "3d", "DirectionalLight3D"),
    ("light2d", "Light2D", "Lights", "object2d", "2d", "LightNode2D"),
    ("pointlight2d", "PointLight2D", "Lights", "object2d", "2d",
     "PointLight2D"),
    ("conelight2d", "ConeLight2D", "Lights", "object2d", "2d",
     "ConeLight2D"),
    ("rectlight2d", "RectLight2D", "Lights", "object2d", "2d",
     "RectLight2D"),
    ("audio3d", "AudioEmitter3D", "Audio", "object3d", "3d",
     "AudioEmitter3D"),
    ("audio2d", "AudioEmitter2D", "Audio", "object2d", "2d",
     "AudioEmitter2D"),
    ("text3d", "Text3D", "Text", "object3d", "3d", "Text3D"),
    ("text2d", "Text2D", "Text", "object2d", "2d", "Text2D"),
    ("particle3d", "Particle3D", "Effects", "object3d", "3d", "Particle3D"),
    ("particle2d", "Particle2D", "Effects", "object2d", "2d", "Particle2D"),
    ("timer3d", "Timer3D", "Utility", "object3d", "3d", "Timer3D"),
    ("timer2d", "Timer2D", "Utility", "object2d", "2d", "Timer2D"),
    ("marker3d", "Marker3D", "Utility", "object3d", "3d", "Marker3D"),
    ("marker2d", "Marker2D", "Utility", "object2d", "2d", "Marker2D"),
)

# the same table as a flat list of names
OBJECT_TYPES = tuple((t[0], t[1], t[3]) for t in NODE_TYPES)

# the look fields a document applies before build()
LOOK_KEYS = ("pos", "yaw", "scale", "rot", "size", "model", "map",
             "texture", "color", "showing", "shader", "knobs")

# `object` and `scene` make an entry an instance
INSTANCE_KEYS = ("object", "scene")

SCENE_HELP = ("a scene document: script is what it runs, objects are what "
              "it places, overrides are what the editor moved")
OBJECT_HELP = ("an object document: script is the class, type is the node, "
               "the rest is where it sits and how it looks")
ENTITY_HELP = ("an entity document: a scripted thing with behaviour - a "
               "player, an NPC, an enemy - in the entities folder")
SHADER_HELP = ("a shader document: mode is screen, uv or texture, script is "
               "the class that paints it, knobs are its starting numbers")


def kind_of(path):
    """'scene', 'object', 'entity' or 'shader' for a document path."""
    suffix = Path(path).suffix.lower()
    if suffix == SCENE_EXT:
        return "scene"
    if suffix in ENTITY_EXTS:
        return "entity"
    if suffix in OBJECT_EXTS:
        return "object"
    if suffix == SHADER_EXT:
        return "shader"
    return None


def node_type(kind):
    """The NODE_TYPES row for a type name, or None."""
    for row in NODE_TYPES:
        if row[0] == str(kind or "").lower():
            return row
    return None


def type_family(kind):
    """'3d' or '2d' for a node type."""
    row = node_type(kind)
    return row[4] if row else "3d"


def object_ext(kind):
    """The document extension a node type is stored under."""
    return OBJECT3D_EXT if type_family(kind) == "3d" else OBJECT2D_EXT


def entity_ext(kind):
    """The document extension an entity type is stored under."""
    return ENT3D_EXT if type_family(kind) == "3d" else ENT2D_EXT


def doc_family(kind):
    """'entity' for a scripted thing with behaviour, else 'object'."""
    row = node_type(kind)
    return "entity" if str(row[3] if row else "").startswith("entity") \
        else "object"


def doc_ext(kind):
    """The extension a node type's document is stored under."""
    return entity_ext(kind) if doc_family(kind) == "entity" \
        else object_ext(kind)


def doc_folder(kind):
    """The project folder a node type lives in."""
    return "entities" if doc_family(kind) == "entity" else "objects"


def engine_class(kind):
    """The engine class this type name builds, or None."""
    row = node_type(kind)
    return row[5] if row else None


def node_groups():
    """[(group, [row, ...])] in table order, for Add Node."""
    out = []
    for row in NODE_TYPES:
        if not out or out[-1][0] != row[2]:
            out.append((row[2], []))
        out[-1][1].append(row)
    return out


def doc_path(folder, name, kind, type=None):
    """`<folder>/<name>.scene`, `.obj3d`, `.ent3d`, `.obj2d` or `.shader`."""
    if kind == "scene":
        ext = SCENE_EXT
    elif kind == "shader":
        ext = SHADER_EXT
    elif kind == "entity":
        ext = entity_ext(type)
    else:
        ext = object_ext(type)
    p = Path(name)
    if p.suffix.lower() in \
            (SCENE_EXT, SHADER_EXT) + OBJECT_EXTS + ENTITY_EXTS:
        p = p.with_suffix("")
    if p.is_absolute():
        return p.with_suffix(ext)
    return Path(folder) / f"{p.name}{ext}"


def find_doc(folder, name, kind):
    """An existing document's path, trying every extension it may use."""
    stem = Path(str(name)).stem
    if kind == "scene":
        exts = (SCENE_EXT,)
    elif kind == "shader":
        exts = (SHADER_EXT,)
    elif kind == "entity":
        # entities kept an object's extension before the family split
        exts = ENTITY_EXTS + OBJECT_EXTS
    else:
        exts = OBJECT_EXTS
    for ext in exts:
        p = Path(folder) / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


def object_suffix_is_flat(path):
    """Does this document path name the flat half?"""
    return Path(path).suffix.lower() in (OBJECT2D_EXT,)


def entity_suffix_is_flat(path):
    """Does this document path name a flat entity?"""
    return Path(path).suffix.lower() in (ENT2D_EXT,)


def upgrade_ext(path):
    """The extension a legacy document saves under, or None."""
    suffix = Path(path).suffix.lower()
    if suffix == OBJECT_EXT:
        return None            # the caller knows the type; see `object_ext`
    if suffix == MODEL_EXT:
        return MODEL3D_EXT
    return None


def script_field(folder, name, default=None):
    """A document's `script` value: `scripts/objects/torch.py`."""
    if not name:
        return default
    p = Path(str(name).replace("\\", "/"))
    if p.suffix != ".py":
        p = p.with_suffix(".py")
    if p.is_absolute():
        return p.name
    folder = str(folder).replace("\\", "/") if folder else ""
    return f"{folder}/{p.name}" if folder else str(p)


def script_stem(value):
    """The file stem a document's `script` names, or None."""
    if not value:
        return None
    return Path(str(value)).stem or None


def instance_field(value):
    """A document reference normalised to a project-relative path."""
    if not value:
        return None
    return str(value).replace("\\", "/").lstrip("/") or None


def is_instance(entry):
    """Does a placed entry point at another document (an instance)?"""
    return isinstance(entry, dict) and any(entry.get(k) for k in
                                           INSTANCE_KEYS)


def instance_source(entry):
    """The referenced path string, and whether it is a scene."""
    if not isinstance(entry, dict):
        return None, False
    for key in INSTANCE_KEYS:
        value = entry.get(key)
        if value:
            return str(value), key == "scene"
    return None, False


def resolve_instance(project, value):
    """An instance reference as a real path, or None."""
    if project is None or not value:
        return None
    p = Path(str(value).replace("\\", "/"))
    guess = p if p.is_absolute() else project.path / p
    if guess.is_file():
        return guess
    kind = kind_of(guess)
    if kind:
        found = find_doc(guess.parent, guess.stem, kind)
        if found is not None:
            return found
    # no suffix; ask the folder and the reference
    for folder, want in ((getattr(project, "scenes_dir", None), "scene"),
                        (getattr(project, "objects_dir", None), "object"),
                        (getattr(project, "entities_dir", None), "entity")):
        found = find_doc(folder, guess.stem, want) if folder else None
        if found is not None:
            return found
    return None


def type_drawer(kind):
    """The blocks drawer an object document's type belongs to."""
    for name, _label, drawer in OBJECT_TYPES:
        if name == kind:
            return drawer
    return "object3d"


def type_label(kind):
    """The words the editor shows for an object document's type."""
    for name, label, _drawer in OBJECT_TYPES:
        if name == str(kind or "").lower():
            return label
    return "Object3D"


def key(cls_name, index, parent=None):
    """The stable name an object gets: `Torch#0`, `Torch#1`, ..."""
    name = f"{cls_name}#{int(index)}"
    return f"{parent}/{name}" if parent else name


def look(entry):
    """The look fields an entry actually carries."""
    out = {}
    if not isinstance(entry, dict):
        return out
    for field in LOOK_KEYS:
        value = entry.get(field)
        if value is None:
            continue
        if field in ("pos", "color", "size") and \
                isinstance(value, (list, tuple)):
            value = [float(c) for c in value]
        elif field in ("yaw", "scale", "rot") and \
                isinstance(value, (int, float)):
            value = float(value)
        out[field] = value
    return out


def blank_object(name, kind="object3d", script=None):
    """A fresh object document with only meaningful fields."""
    known = [t[0] for t in OBJECT_TYPES]
    kind = kind if kind in known else "object3d"
    doc = {"format": FORMAT,
           "_help": ENTITY_HELP if doc_family(kind) == "entity"
           else OBJECT_HELP,
           "name": str(name),
           "type": kind}
    if script:
        doc["script"] = str(script)
    if type_family(doc["type"]) == "3d":
        doc.update({"pos": [0.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0})
    else:
        doc["pos"] = [0.0, 0.0]
    doc["nodes"] = []
    return doc


def blank_entity(name, kind="entity3d", script=None):
    """A fresh entity document: an object's shape, entity family."""
    if doc_family(kind) != "entity":
        kind = "entity2d" if type_family(kind) == "2d" else "entity3d"
    return blank_object(name, kind, script)


def blank_shader(name, mode="screen", script=None, knobs=None):
    """A fresh shader document: mode, class and numbers."""
    doc = {"format": FORMAT,
           "_help": SHADER_HELP,
           "name": str(name),
           "mode": mode if mode in SHADER_MODES else "screen"}
    if script:
        doc["script"] = str(script)
    doc["knobs"] = dict(knobs or {})
    return doc


def blank_scene(name, kind="scene3d", script=None):
    """A fresh scene document: no placed objects, nothing overridden."""
    doc = {"format": FORMAT,
           "_help": SCENE_HELP,
           "name": str(name),
           "kind": kind if kind in SCENE_KINDS else "scene3d"}
    if script:
        doc["script"] = str(script)
    doc["objects"] = []
    doc["overrides"] = {}
    return doc


def load(path, kind=None):
    """Read a document, filling in the fields every reader expects."""
    path = Path(path)
    kind = kind or kind_of(path)
    if kind == "shader":
        return _load_shader(path)
    if kind == "scene":
        blank = blank_scene
    elif kind == "entity":
        blank = blank_entity
    else:
        blank = blank_object
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return blank(path.stem)
    if not isinstance(raw, dict):
        return blank(path.stem)
    doc = dict(raw)
    doc.setdefault("format", FORMAT)
    doc.setdefault("name", path.stem)
    if kind == "scene":
        doc.setdefault("kind", "scene3d")
        doc.setdefault("objects", [])
        doc.setdefault("overrides", {})
        if not isinstance(doc["objects"], list):
            doc["objects"] = []
        if not isinstance(doc["overrides"], dict):
            doc["overrides"] = {}
    else:
        # the extension says which half, even without `type`
        if kind == "entity":
            default = "entity2d" if entity_suffix_is_flat(path) else "entity3d"
        else:
            default = "object2d" if object_suffix_is_flat(path) else "object3d"
        doc.setdefault("type", default)
        # an object file owns a branch like a scene does
        if not isinstance(doc.get("nodes"), list):
            doc["nodes"] = []
    return doc


def _load_shader(path):
    """One shader document, with its mode and knobs filled in."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return blank_shader(path.stem)
    if not isinstance(raw, dict):
        return blank_shader(path.stem)
    doc = dict(raw)
    doc.setdefault("format", FORMAT)
    doc.setdefault("name", path.stem)
    mode = str(doc.get("mode") or "screen").lower()
    doc["mode"] = mode if mode in SHADER_MODES else "screen"
    if not isinstance(doc.get("knobs"), dict):
        doc["knobs"] = {}
    return doc


def save(path, doc):
    """Write a document atomically, and hand the path back."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in doc.items() if not str(k).startswith("__")}
    payload["format"] = FORMAT
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def set_override(doc, name, fields):
    """Record moved/looked fields for one object, dropping empty ones."""
    overrides = doc.setdefault("overrides", {})
    entry = {k: v for k, v in fields.items() if v is not None}
    if entry:
        overrides[str(name)] = entry
    else:
        overrides.pop(str(name), None)
    return doc


def roots(doc):
    """The children a document owns: objects or nodes."""
    items = doc.get("objects")
    if isinstance(items, list):
        return items
    if "objects" not in doc and isinstance(doc.get("nodes"), list):
        return doc["nodes"]
    items = []
    doc["objects"] = items
    return items


def branch_of(doc):
    """An object document's own nodes, read without writing anything.
    `roots` files a missing list under `objects`; a branch reader must not."""
    items = (doc or {}).get("nodes")
    return items if isinstance(items, list) else []


def children(entry):
    """A placed entry's own nodes, created on first use."""
    if not isinstance(entry, dict):
        return []
    got = entry.get("children")
    if not isinstance(got, list):
        got = []
        entry["children"] = got
    return got


def walk(doc_or_entry, parent=None, depth=0):
    """Every placed entry, parents before their nodes."""
    items = children(doc_or_entry) if isinstance(doc_or_entry, dict) and \
        doc_or_entry.get("id") else roots(doc_or_entry)
    for entry in items:
        if not isinstance(entry, dict):
            continue
        yield entry, parent, depth
        for row in walk(entry, entry, depth + 1):
            yield row


def placed(doc, name=None):
    """The document's children, or one entry by id."""
    if name is None:
        return roots(doc)
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
    """Append a placed object, replacing one with the same id."""
    if isinstance(parent, str):
        parent = placed(doc, parent)
    items = children(parent) if isinstance(parent, dict) else roots(doc)
    name = entry.get("id")
    for i, old in enumerate(items):
        if isinstance(old, dict) and old.get("id") == name:
            items[i] = entry
            return doc
    items.append(entry)
    return doc


def remove_placed(doc, name):
    """Take a placed object and its branch out."""
    _remove_entry(roots(doc), name)
    overrides = doc.get("overrides") or {}
    for key in list(overrides):
        if key == name or str(key).startswith(f"{name}/"):
            overrides.pop(key, None)
    return doc


def _remove_entry(items, name):
    """Cut one entry by id, at any depth."""
    keep = []
    for entry in items:
        if not isinstance(entry, dict):
            keep.append(entry)
            continue
        if entry.get("id") == name:
            continue
        if entry.get("children"):
            _remove_entry(entry["children"], name)
        if not entry.get("children"):
            entry.pop("children", None)      # keep empty branches unwritten
        keep.append(entry)
    items[:] = keep
    return len(items) != len(keep)


_MISSING = object()


def _same_value(a, b):
    """Do two knob values read the same, numbers included?"""
    if b is _MISSING:
        return False
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(abs(float(x) - float(y)) < 1e-6
                                        for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def knobs_of(obj):
    """The node settings worth writing into a document's `knobs`."""
    out = {}
    for key in getattr(obj, "doc_knobs", ()) or ():
        if not hasattr(obj, key):
            continue
        if key == "shader":
            # `look_of` writes the look; `doc_knobs` only offers the row
            continue
        value = getattr(obj, key)
        if _same_value(value, getattr(type(obj), key, _MISSING)):
            continue                # a document records what it changed
        if isinstance(value, bool):
            pass                    # a switch stays a switch in the file
        elif isinstance(value, (list, tuple)):
            value = [round(float(c), 4) for c in value]
        elif isinstance(value, (int, float)):
            value = round(float(value), 4)
        elif value is not None and not isinstance(value, str):
            value = str(value)
        out[key] = value
    return out


def look_of(obj):
    """Which object state is worth writing to a document."""
    pos = getattr(obj, "pos", ())
    if getattr(obj, "parent", None) is not None and \
            getattr(obj, "local_pos", None) is not None:
        pos = obj.local_pos
    out = {"pos": [round(float(c), 4) for c in pos]}
    if hasattr(obj, "yaw"):
        out["yaw"] = round(float(obj.yaw), 4)
    if hasattr(obj, "scale"):
        out["scale"] = round(float(obj.scale), 4)
    if hasattr(obj, "rot"):
        out["rot"] = round(float(obj.rot), 4)
    if isinstance(getattr(obj, "size", None), tuple) and \
            not hasattr(obj, "half"):
        # `size` is a sprite's box here, never a collision knob
        out["size"] = [round(float(c), 4) for c in obj.size]
    got = getattr(obj, "look", None)
    if isinstance(got, dict):
        for field in ("model", "texture", "color"):
            if field in got:
                out[field] = got[field]
    shader = getattr(obj, "shader", None)
    if shader:
        # the worn look is the answer; the pass is derived
        out["shader"] = str(shader)
    showing = getattr(obj, "showing", None)
    if showing:
        out["showing"] = str(showing)
    knobs = knobs_of(obj)
    if knobs:
        out["knobs"] = knobs
    return out


def describe(obj, extra=None):
    """The look fields a live object carries."""
    out = look_of(obj)
    if extra:
        out.update({k: v for k, v in extra.items() if v is not None})
    return out
