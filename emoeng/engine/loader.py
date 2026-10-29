"""Projects: a folder with a manifest, scenes, objects, scripts, models,"""

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .. import const
from . import components
from . import model as models
from . import objects as objmod
from . import paths, scenedoc, sfx, templates
from . import shaders as shadermod
from .objects import GameObject, Object3D, first_object_class
from .scene import Scene, Scene2D, Scene3D, SceneUI, first_scene_class

# file templates live in `engine.templates`, read through `loader`
OBJECT_PRESETS = templates.OBJECT_PRESETS
SCENE_PRESETS = templates.SCENE_PRESETS
SHADER_PRESETS = templates.SHADER_PRESETS

META_NAME = const.MANIFEST_NAME
KINDS = const.KINDS
DEFAULT_PROJECT = const.DEFAULT_PROJECT
PACKAGES = const.PACKAGES

# project file-format version, written as `format` in the manifest
FORMAT = const.PROJECT_FORMAT
INPUT_NAME = const.INPUT_MAP_NAME
ASSET_NAME = const.ASSET_MAP_NAME

# every manifest section and the flat keys it absorbs
SECTIONS = {
    "window": {"size": "size", "fullscreen": "fullscreen"},
    "render": {"render_scale": "scale", "post": "post",
               "clear_color": "clear_color"},
    "audio": {},
    "save": {"save_slot": "slot", "auto_save_interval": "autosave"},
    "debug": {},
    "input": {"actions": "actions"},
    "defaults": {},
    "assets": {"textures": "textures", "audio": "audio"},
}

# the `defaults` section: one scene attribute each, and the shape it wants
DEFAULT_KINDS = {
    "ambient": "list", "sun_dir": "list", "sun_col": "list",
    "fog_color": "list", "move_speed": "list", "post": "names",
    "camera": "text", "lock_input": "bool", "master": "float",
    "fog_near": "float", "fog_far": "float", "fov": "float",
    "near": "float", "far": "float", "eye_height": "float",
    "world_radius": "float", "gravity": "float", "jump_speed": "float",
}
DEFAULT_ORDER = tuple(DEFAULT_KINDS)


def number_list(value):
    """`"0.2, 0.2, 0.3"` or a list, as floats; None when it cannot read."""
    if value is None:
        return None
    parts = value if isinstance(value, (list, tuple)) else str(value)
    if isinstance(parts, str):
        parts = parts.replace("[", ",").replace("]", ",").split(",")
    out = []
    for part in parts:
        try:
            out.append(float(str(part).strip()))
        except ValueError:
            return None
    return tuple(out) or None


def name_list(value):
    """`"uvscroll, scanlines"` or a list, as a tuple of names."""
    if value is None:
        return ()
    parts = value if isinstance(value, (list, tuple)) \
        else str(value).split(",")
    return tuple(str(part).strip() for part in parts if str(part).strip())


def int_pair(value, default):
    """A size as two ints: `[1152, 700]`, `"1152, 700"`, or `default`."""
    got = number_list(value)
    if not got or len(got) < 2:
        return tuple(default)
    return (int(round(got[0])), int(round(got[1])))


def default_value(key, raw):
    """One `defaults` value, in the shape the scene attribute wants."""
    kind = DEFAULT_KINDS.get(key)
    if kind == "list":
        got = number_list(raw)
        if key == "move_speed" and got and len(got) == 1:
            got = (got[0], got[0] * 2.0)     # (walk, run) wants two
        return got
    if kind == "names":
        return name_list(raw)
    if kind == "bool":
        return bool(raw)
    if kind == "text":
        return str(raw)
    if kind == "float":
        got = number_list(raw)
        return got[0] if got else None
    return None


# keys that stay at top level: identity and entry point
TOP_KEYS = ("format", "name", "title", "start", "seed", "version",
            "description", "author", "icon")


def binding_names(value):
    """A project's binding list, normalised to lower-case strings."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [v.strip() for v in value.replace(";", ",").split(",")]
    else:
        try:
            parts = [str(v).strip() for v in value]
        except TypeError:
            parts = [str(value)]
    return [v.lower() for v in parts if v]


def input_table(mapping):
    """One input map's shape: names to normalised binding lists."""
    return {str(k): binding_names(v) for k, v in (mapping or {}).items()}


def section_meta(raw):
    """A manifest dict with flat keys moved into sections."""
    meta = dict(raw)
    for section, moves in SECTIONS.items():
        block = meta.get(section)
        block = dict(block) if isinstance(block, dict) else {}
        for old, new in moves.items():
            if old in meta:
                block.setdefault(new, meta.pop(old))
        if block:
            meta[section] = block
        else:
            meta.pop(section, None)
    return meta


def meta_get(meta, section, key=None, default=None):
    """Read one value out of a sectioned manifest (see `Project.get`)."""
    if not isinstance(meta, dict):
        return default
    block = meta.get(section)
    if key is None:
        return block if isinstance(block, dict) else default
    if isinstance(block, dict) and key in block:
        return block[key]
    return default


def read_meta(folder):
    """Peek at a project folder's manifest without loading the project."""
    path = Path(folder)
    if path.is_dir():
        path = path / META_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return section_meta(raw) if isinstance(raw, dict) else {}


class Project:
    """A emoeng project folder."""

    # the manifest shape this class writes
    FORMAT = FORMAT

    # what a hot reload watches: code the player needs
    WATCHED = ("scenes", "objects", "entities", "scripts", "shaders")

    # import defaults, overridable per project in assets.json
    ASSET_DEFAULTS = {
        "textures": {"filter": "linear", "wrap": "repeat",
                     "mipmaps": True, "tile": 0.0, "sheets": {}},
        "audio": {"gain": 1.0, "gains": {}},
    }

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        meta_path = self.path / META_NAME
        if not meta_path.exists():
            raise FileNotFoundError(f"no {META_NAME} in {self.path}")
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"bad {META_NAME}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"bad {META_NAME}: expected an object")
        self.file_format = int(raw.get("format", 1) or 1)
        # old flat files upgrade in memory, saved the new way
        self.legacy = self.file_format < FORMAT
        self.meta = self._sectioned(raw)
        self._models = {}
        self._models2d = {}
        self._maps = {}
        self._textures = {}
        self._objects = {}
        self._shaders = {}
        self._script_path_added = False
        self.apply_meta()
        # documents are renamed on disk, not in memory
        self.migrated = self.upgrade_documents()
        scenes = self.scene_names()
        self.start = self.meta.get("start") or (scenes[0] if scenes else None)

    def apply_meta(self):
        """Read every manifest field back into this project.

        `__init__` calls it once; the Project tab calls it after writing, so
        a value edited in the form reaches the engine without a re-open.
        """
        meta = self.meta
        self.name = meta.get("name") or self.path.name
        self.title = meta.get("title") or self.name
        self.version = str(meta.get("version") or "0.1.0")
        self.description = str(meta.get("description") or "")
        self.seed = int(meta.get("seed", 7))
        self.size = int_pair(self.get("window", "size"), (1152, 700))
        self.fullscreen = bool(self.get("window", "fullscreen", False))
        self.resizable = bool(self.get("window", "resizable", True))
        self.min_size = int_pair(self.get("window", "min_size"), (640, 400))
        self.render_scale = float(self.get("render", "scale", 1.0))
        self.post = self._check_post(tuple(self.get("render", "post", ())))
        # bake `bake`-flagged lights when the scene is entered
        self.bake_on_run = bool(self.get("render", "bake_on_run", False))
        # the lightmap edge, in pixels
        self.bake_size = int(self.get("render", "bake_size", 512) or 512)
        self.save_slot = str(self.get("save", "slot", const.SAVE_SLOT))
        self.auto_save_interval = float(self.get("save", "autosave", 0.0))
        if meta.get("start"):
            self.start = str(meta["start"])
        return self

    def _sectioned(self, raw):
        """This project's manifest, sectioned (see `section_meta`)."""
        return section_meta(raw)

    def get(self, section, key=None, default=None):
        """One manifest value: `get("render", "post")`, or a whole section."""
        return meta_get(self.meta, section, key, default)

    def _check_post(self, names):
        """The manifest's `post` chain, with what this project lacks dropped."""
        out = []
        for value in names:
            key = Path(str(value)).stem
            doc = self.shader_doc(key)
            if doc is None:
                shadermod.report(f"{self.name}: no shader {key!r} to "
                                 "post with", "warn")
                continue
            if doc.get("mode") != shadermod.POST_MODE:
                shadermod.report(f"{self.name}: {key} is a "
                                 f"{doc.get('mode')} shader, so it cannot "
                                 "post with it", "warn")
                continue
            out.append(key)
        return tuple(out)

    def set(self, section, key, value):
        """Write one manifest value in memory; `save_meta()` stores it."""
        block = self.meta.get(section)
        if not isinstance(block, dict):
            block = self.meta[section] = {}
        block[key] = value
        return value

    def _read_sidecar(self, name):
        try:
            data = json.loads((self.path / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_sidecar(self, name, payload):
        """Write a JSON file beside the manifest, atomically."""
        path = self.path / name
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def input_map(self):
        """action -> binding names, as this project declares them."""
        for source in (self._read_sidecar(INPUT_NAME).get("actions"),
                       self.get("input", "actions")):
            if isinstance(source, dict) and source:
                return {str(k): binding_names(v) for k, v in source.items()
                        if not str(k).startswith("_")}
        return {}

    def save_input_map(self, actions):
        """Write the project's keymap sidecar and return its path."""
        payload = dict(templates.INPUT_MAP_DOC)
        payload["actions"] = input_table(actions)
        return self._write_sidecar(INPUT_NAME, payload)

    def trigger_map(self):
        """trigger -> binding names, as this project declares them."""
        for source in (self._read_sidecar(INPUT_NAME).get("triggers"),
                       self.get("input", "triggers")):
            if isinstance(source, dict) and source:
                return {str(k): binding_names(v) for k, v in source.items()
                        if not str(k).startswith("_")}
        return {}

    def input_tuning(self):
        """Numbers a project tunes about its bindings, e.g. the deadzone."""
        for source in (self._read_sidecar(INPUT_NAME).get("tuning"),
                       self.get("input", "tuning")):
            if isinstance(source, dict) and source:
                return {str(k): v for k, v in source.items()
                        if not str(k).startswith("_")}
        return {}

    def save_input_maps(self, actions, triggers, tuning=None):
        """Write both tables into the manifest and store it."""
        self.set("input", "actions", input_table(actions))
        self.set("input", "triggers", input_table(triggers))
        if tuning is not None:
            self.set("input", "tuning", dict(tuning))
        self.save_meta()
        return self.path / META_NAME

    def asset_settings(self):
        """How this project's assets are imported, filled with defaults."""
        out = {kind: dict(opts) for kind, opts in self.ASSET_DEFAULTS.items()}
        # manifest first, sidecar on top: the newer file always wins
        for source in (self.get("assets") or {},
                       self._read_sidecar(ASSET_NAME)):
            if not isinstance(source, dict):
                continue
            for kind, opts in source.items():
                if kind not in out or not isinstance(opts, dict):
                    continue
                out[kind].update({k: v for k, v in opts.items()
                                  if not str(k).startswith("_")})
        return out

    def save_asset_settings(self, settings):
        """Write the import-settings sidecar and return its path."""
        # copy nested blocks; mutating the module constant would leak
        payload = {k: (dict(v) if isinstance(v, dict) else v)
                   for k, v in templates.ASSET_MAP_DOC.items()}
        for kind, opts in (settings or {}).items():
            if kind in payload and isinstance(opts, dict):
                payload[kind].update(opts)
        return self._write_sidecar(ASSET_NAME, payload)

    # scripts live a level down, so scan one folder deeper
    WATCH_NESTED = ("scripts/scenes", "scripts/objects", "scripts/entities",
                    "scripts/shaders")

    def watch_files(self, kind):
        """The files `snapshot()` stamps for one watched folder."""
        out = list(self.files(kind))
        for sub in self.WATCH_NESTED:
            if sub.split("/")[0] == kind:
                out.extend(self.files(sub))
        return out

    def snapshot(self, kinds=None):
        """path -> (mtime, size) for the watched folders."""
        out = {}
        for kind in (self.WATCHED if kinds is None else kinds):
            for p in self.watch_files(kind):
                try:
                    st = p.stat()
                except OSError:
                    continue
                out[str(p)] = (st.st_mtime_ns, st.st_size)
        return out

    def changed_since(self, snap, kinds=None):
        """(changed paths, fresh snapshot) since `snap` was taken."""
        now = self.snapshot(kinds)
        out = [p for p, stamp in now.items() if snap.get(p) != stamp]
        out += [p for p in snap if p not in now]
        return sorted(out), now

    def reload_scripts(self):
        """Forget imported script modules; the next import re-reads them."""
        for name in list(sys.modules):
            if name.split(".")[0] in ("scripts", "objects"):
                parent, _, child = name.rpartition(".")
                sys.modules.pop(name, None)
                if parent:
                    # only the plain import path keeps submodule attributes
                    try:
                        delattr(sys.modules.get(parent), child)
                    except (AttributeError, TypeError):
                        pass
        self._objects.clear()
        self._shaders.clear()
        self._textures.clear()
        self._models.clear()
        self._models2d.clear()
        self._maps.clear()

    def dir(self, kind):
        d = self.path / kind
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def scenes_dir(self):
        return self.dir("scenes")

    @property
    def objects_dir(self):
        return self.dir("objects")

    @property
    def scripts_dir(self):
        return self.dir("scripts")

    @property
    def scene_scripts_dir(self):
        """Where scene code lives: `scripts/scenes`."""
        return self.dir("scripts/scenes")

    @property
    def object_scripts_dir(self):
        """Where object code lives: `scripts/objects`."""
        return self.dir("scripts/objects")

    @property
    def entity_scripts_dir(self):
        """Where entity code lives: `scripts/entities`."""
        return self.dir("scripts/entities")

    @property
    def shader_scripts_dir(self):
        """Where shader code lives: `scripts/shaders`."""
        return self.dir("scripts/shaders")

    @property
    def entities_dir(self):
        return self.dir("entities")

    @property
    def models_dir(self):
        return self.dir("models")

    @property
    def maps_dir(self):
        return self.dir("maps")

    @property
    def textures_dir(self):
        return self.dir("textures")

    @property
    def audio_dir(self):
        return self.dir("audio")

    @property
    def saves_dir(self):
        return self.dir("saves")

    @property
    def shaders_dir(self):
        """The looks this project owns: one `.shader` document each."""
        return self.dir("shaders")

    def files(self, kind):
        d = self.dir(kind)
        return sorted(p for p in d.iterdir() if p.is_file())

    def scene_names(self):
        """The project's scenes: one `scenes/*.scene` each."""
        return self._stems("scenes", (scenedoc.SCENE_EXT,))

    def _stems(self, folder, exts):
        """Each stem under a folder once, sorted, whatever its suffix."""
        out = {}
        for p in self.files(folder):
            if p.suffix.lower() in exts:
                out.setdefault(p.stem, p)
        return sorted(out)

    def object_names(self):
        """The project's objects: one `objects/*.obj3d` or `.obj2d` each."""
        return self._stems("objects", scenedoc.OBJECT_EXTS)

    def entity_names(self):
        """The project's entities: one `entities/*.ent3d` or `.ent2d` each."""
        # the old object spelling still counts, until it is upgraded
        return self._stems("entities",
                           scenedoc.ENTITY_EXTS + scenedoc.OBJECT_EXTS)

    def spawnable_names(self):
        """Everything `spawn(<name>)` can name: objects and entities."""
        return sorted(set(self.object_names()) | set(self.entity_names()))

    def shader_names(self):
        """The project's shaders: one `shaders/*.shader` each."""
        return self._stems("shaders", (scenedoc.SHADER_EXT,))

    def upgrade_documents(self):
        """Rename the one-spelling documents to their dimensioned one."""
        moved = []
        for p in self.files("objects"):
            if p.suffix.lower() != scenedoc.OBJECT_EXT:
                continue
            doc = scenedoc.load(p, "object")
            want = p.with_suffix(scenedoc.object_ext(doc.get("type")))
            if want.exists():
                continue
            try:
                p.rename(want)
            except OSError:
                continue
            moved.append(want)
        for p in self.files("entities"):
            # an entity kept an object's extension before the family split
            if p.suffix.lower() not in scenedoc.OBJECT_EXTS:
                continue
            doc = scenedoc.load(p, "entity")
            want = p.with_suffix(scenedoc.entity_ext(doc.get("type")))
            if want.exists():
                continue
            try:
                p.rename(want)
            except OSError:
                continue
            moved.append(want)
        for p in self.files("models"):
            if p.suffix.lower() != scenedoc.MODEL_EXT:
                continue
            want = p.with_suffix(scenedoc.MODEL3D_EXT)
            if want.exists():
                continue
            try:
                p.rename(want)
            except OSError:
                continue
            moved.append(want)
        if moved:
            self.reload_models()
        return moved

    def strays(self, folder):
        """Python files in a document folder, which nothing loads."""
        return [p for p in self.files(folder) if p.suffix.lower() == ".py"]

    def script_names(self):
        return [p.stem for p in self.files("scripts") if p.suffix == ".py"]

    def model_names(self):
        """The solid models: `models/*.model3d`, old `.model` included."""
        return self._stems("models", (scenedoc.MODEL3D_EXT,
                                      scenedoc.MODEL_EXT))

    def model2d_names(self):
        return [p.stem for p in self.files("models")
                if p.suffix == ".model2d"]

    def map_names(self):
        """The maps this project carries: one `maps/<stem>.map3d` each."""
        return self._stems("maps", (scenedoc.MAP3D_EXT,
                                    scenedoc.MODEL3D_EXT))

    def texture_files(self):
        return [p for p in self.files("textures")
                if p.suffix.lower() in (".png", ".jpg", ".jpeg")]

    def audio_files(self):
        return [p for p in self.files("audio")
                if p.suffix.lower() in (".wav", ".ogg", ".mp3", ".flac")]

    def sfx_files(self):
        """Sound projects: the editable source of some of those files."""
        return [p for p in self.files("audio")
                if p.suffix.lower() == sfx.SFX_EXT]

    def relative(self, path):
        try:
            return str(Path(path).resolve().relative_to(self.path))
        except ValueError:
            return str(path)

    def scene_doc(self, name):
        """A scene's document, or None when script-only."""
        path = scenedoc.find_doc(self.scenes_dir, name, "scene")
        return scenedoc.load(path, "scene") if path else None

    def save_scene_doc(self, name, doc):
        """Write a scene document (creating scenes/<name>.scene)."""
        path = scenedoc.doc_path(self.scenes_dir, name, "scene")
        return scenedoc.save(path, doc)

    def object_doc(self, name):
        """An object's document, or None when script-only."""
        path = scenedoc.find_doc(self.objects_dir, name, "object")
        return scenedoc.load(path, "object") if path else None

    def save_object_doc(self, name, doc):
        """Write an object document under the extension its type means."""
        path = scenedoc.doc_path(self.objects_dir, name, "object",
                                 type=(doc or {}).get("type"))
        made = scenedoc.save(path, doc)
        # a renamed document leaves the old-spelling file behind; delete it
        old = scenedoc.find_doc(self.objects_dir, name, "object")
        if old is not None and old != path and \
                old.suffix.lower() == scenedoc.OBJECT_EXT:
            try:
                old.unlink()
            except OSError:
                pass
        return made

    def entity_doc(self, name):
        """An entity's document, or None when script-only."""
        path = scenedoc.find_doc(self.entities_dir, name, "entity")
        return scenedoc.load(path, "entity") if path else None

    def save_entity_doc(self, name, doc):
        """Write an entity document under the extension its type means."""
        path = scenedoc.doc_path(self.entities_dir, name, "entity",
                                 type=(doc or {}).get("type"))
        made = scenedoc.save(path, doc)
        # an entity re-spelled from `.obj3d` leaves the old file behind
        for ext in scenedoc.OBJECT_EXTS:
            stale = path.with_suffix(ext)
            if stale == path or not stale.is_file():
                continue
            try:
                stale.unlink()
            except OSError:
                pass
        return made

    def shader_doc(self, name):
        """A shader's document, or None when missing."""
        path = scenedoc.find_doc(self.shaders_dir, name, "shader")
        return scenedoc.load(path, "shader") if path else None

    def save_shader_doc(self, name, doc):
        """Write a shader document (creating shaders/<name>.shader)."""
        path = scenedoc.doc_path(self.shaders_dir, name, "shader")
        return scenedoc.save(path, doc)

    def shader_script(self, name):
        """The `.py` a shader runs, or None."""
        key = Path(str(name)).stem
        doc = self.shader_doc(key)
        path = self.script_path(doc.get("script") if doc else None)
        if path is not None:
            return path
        guess = self.shader_scripts_dir / f"{key}.py"
        return guess if guess.is_file() else None

    def shader_file(self, name):
        """(document, script path) for a shader name."""
        key = Path(str(name)).stem
        return self.shader_doc(key), self.shader_script(key)

    def shader_class(self, name):
        """Import a shader's script and return its `Shader` subclass."""
        key = Path(str(name)).stem
        cached = self._shaders.get(key)
        if cached is not None:
            return cached
        doc, path = self.shader_file(key)
        if path is None:
            return None
        self._add_import_path()
        try:
            module = importlib.import_module(
                f"scripts.shaders.{path.stem}")
        except (ImportError, SyntaxError, ValueError):
            shadermod.report(f"scripts/shaders/{path.stem}.py will not "
                             "import", "error")
            return None
        # a class defined here wins over an imported one
        cls = first_object_class(module, shadermod.Shader)
        if cls is None:
            shadermod.report(f"scripts/shaders/{path.stem}.py defines no "
                             "Shader subclass", "error")
            return None
        over = {}
        knobs = {**(getattr(cls, "knobs", None) or {}),
                 **((doc or {}).get("knobs") or {})}
        if knobs != (getattr(cls, "knobs", None) or {}):
            over["knobs"] = knobs
        mode = (doc or {}).get("mode")
        if mode and mode != getattr(cls, "mode", None):
            over["mode"] = mode
        if over:
            cls = type(cls.__name__, (cls,), over)
        self._shaders[key] = cls
        return cls

    def load_shaders(self):
        """stem -> class, for every shader document this project has."""
        out = {}
        for stem in self.shader_names():
            cls = self.shader_class(stem)
            if cls is not None:
                out[stem] = cls
        return out

    def script_path(self, value):
        """A document's `script` field as a file path, or None."""
        if not value:
            return None
        p = Path(str(value).replace("\\", "/"))
        if p.suffix != ".py":
            p = p.with_suffix(".py")
        if p.is_absolute():
            return p if p.is_file() else None
        for guess in (self.path / p, self.scripts_dir / p,
                      self.scene_scripts_dir / p.name,
                      self.object_scripts_dir / p.name,
                      self.entity_scripts_dir / p.name,
                      self.shader_scripts_dir / p.name):
            if guess.is_file():
                return guess
        return None

    def scene_script(self, name):
        """The `.py` a scene runs, or None."""
        doc = self.scene_doc(name)
        path = self.script_path(doc.get("script") if doc else None)
        if path is not None:
            return path
        guess = self.scene_scripts_dir / f"{name}.py"
        return guess if guess.is_file() else None

    def model_path(self, name):
        """Where a solid model lives, preferring the `.model3d` spelling."""
        stem = Path(str(name)).stem
        for ext in (scenedoc.MODEL3D_EXT, scenedoc.MODEL_EXT):
            p = self.models_dir / f"{stem}{ext}"
            if p.is_file():
                return p
        return self.models_dir / f"{stem}{scenedoc.MODEL3D_EXT}"

    def model(self, name):
        """Load and cache a model by stem."""
        key = Path(name).stem
        if key in self._models:
            return self._models[key]
        m = models.Model.load(self.model_path(key))
        self._models[key] = m
        return m

    def store_model(self, model, name=None):
        """Save a model into the project and refresh the cache."""
        stem = Path(name or model.name).stem
        path = model.save(self.models_dir
                          / f"{stem}{scenedoc.MODEL3D_EXT}")
        self._models[stem] = model
        return path

    def reload_models(self):
        self._models.clear()
        self._models2d.clear()
        self._maps.clear()

    def map_path(self, name):
        """Where a map lives, preferring the `.map3d` spelling."""
        stem = Path(str(name)).stem
        for ext in (scenedoc.MAP3D_EXT, scenedoc.MODEL3D_EXT):
            p = self.maps_dir / f"{stem}{ext}"
            if p.is_file():
                return p
        return self.maps_dir / f"{stem}{scenedoc.MAP3D_EXT}"

    def map(self, name):
        """Load and cache a map by stem."""
        key = Path(name).stem
        if key in self._maps:
            return self._maps[key]
        m = models.Model.load(self.map_path(key))
        self._maps[key] = m
        return m

    def store_map(self, model, name=None):
        """Save a map into the project and refresh the cache."""
        stem = Path(name or model.name).stem
        path = model.save(self.maps_dir
                          / f"{stem}{scenedoc.MAP3D_EXT}")
        self._maps[stem] = model
        return path

    def model2d_path(self, name):
        p = Path(name)
        if p.suffix != ".model2d":
            p = p.with_suffix(".model2d")
        return p if p.is_absolute() else self.models_dir / p.name

    def model2d(self, name):
        """Load and cache a .model2d document by stem."""
        key = Path(name).stem
        if key in self._models2d:
            return self._models2d[key]
        m = models.Model2D.load(self.model2d_path(key))
        self._models2d[key] = m
        return m

    def store_model2d(self, model, name=None):
        """Save a 2D model document and refresh the cache."""
        stem = Path(name or model.name).stem
        path = model.save(self.models_dir / f"{stem}.model2d")
        self._models2d[stem] = model
        return path

    def store_texture(self, name, surface, renderer=None):
        """Write a painted sheet to `textures/<stem>.png` and cache it."""
        stem = Path(str(name).replace("\\", "/")).stem
        arr = np.ascontiguousarray(np.asarray(surface, np.uint8))
        if arr.ndim != 3 or arr.shape[2] not in (3, 4):
            raise ValueError("surface must be an (H, W, 3/4) uint8 array")
        mode = "RGBA" if arr.shape[2] == 4 else "RGB"
        path = self.textures_dir / f"{stem}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(arr, mode).save(path)
        self._textures[stem] = arr
        if renderer is not None:
            per = self.texture_settings(stem)
            renderer.texture(stem, arr,
                             rgba=arr.shape[2] == 4,
                             repeat=str(per.get("wrap", "repeat")) ==
                             "repeat",
                             filter=str(per.get("filter", "linear")),
                             mipmaps=bool(per.get("mipmaps", True)),
                             tile=float(per.get("tile", 0.0) or 0.0))
        return path

    def texture(self, name):
        key = Path(name).stem
        if key in self._textures:
            return self._textures[key]
        for ext in (".png", ".jpg", ".jpeg"):
            p = self.textures_dir / f"{key}{ext}"
            if p.exists():
                # close files promptly: an open PIL handle locks the PNG
                with Image.open(p) as im:
                    arr = np.asarray(im.convert("RGBA"))
                if arr[..., 3].min() > 250:
                    arr = arr[..., :3]
                arr = np.ascontiguousarray(arr)
                self._textures[key] = arr
                return arr
        return None

    def register_textures(self, renderer, verbose=None):
        """Upload every texture file, filtered the way the project asks."""
        opts = self.asset_settings()["textures"]
        sheets = opts.get("sheets") or {}
        count = 0
        for p in self.texture_files():
            arr = self.texture(p.stem)
            if arr is not None:
                per = dict(opts)
                named = sheets.get(p.stem)
                if isinstance(named, dict):
                    per.update({k: v for k, v in named.items()
                                if not str(k).startswith("_")})
                renderer.texture(p.stem, arr,
                                 rgba=arr.shape[2] == 4,
                                 repeat=str(per.get("wrap", "repeat")) ==
                                 "repeat",
                                 filter=str(per.get("filter", "linear")),
                                 mipmaps=bool(per.get("mipmaps", True)),
                                 tile=float(per.get("tile", 0.0) or 0.0))
                count += 1
        if verbose:
            verbose(f"uploaded {count} textures")
        return count

    def texture_settings(self, name):
        """The effective import settings for one sheet, by stem."""
        opts = self.asset_settings()["textures"]
        out = {k: v for k, v in opts.items() if k != "sheets"}
        named = (opts.get("sheets") or {}).get(Path(str(name).replace(
            "\\", "/")).stem)
        if isinstance(named, dict):
            out.update({k: v for k, v in named.items()
                        if not str(k).startswith("_")})
        return out

    def sheet_overrides(self, name):
        """Only what this project files about one sheet, globals aside.

        A built-in sheet reads this: the shared defaults would drown its own
        settings, and a sheet with no file behind it has nothing to inherit.
        """
        sheets = self.asset_settings()["textures"].get("sheets") or {}
        entry = sheets.get(Path(str(name).replace("\\", "/")).stem)
        if not isinstance(entry, dict):
            return {}
        return {k: v for k, v in entry.items() if not str(k).startswith("_")}

    def set_texture_settings(self, name, keep_all=False, **opts):
        """File one sheet's import settings and write the sidecar.

        A value matching the shared default is normally dropped, since a
        file reads it anyway; `keep_all` files it regardless, which a
        built-in sheet needs because it inherits nothing.
        """
        stem = Path(str(name).replace("\\", "/")).stem
        settings = self.asset_settings()
        textures = settings["textures"]
        sheets = dict(textures.get("sheets") or {})
        entry = dict(sheets.get(stem) or {})
        entry.update({k: v for k, v in opts.items() if v is not None})
        globals_ = {k: v for k, v in textures.items() if k != "sheets"}
        if not keep_all:
            entry = {k: v for k, v in entry.items()
                     if globals_.get(k) != v}
        if entry:
            sheets[stem] = entry
        else:
            sheets.pop(stem, None)
        textures["sheets"] = sheets
        return self.save_asset_settings(settings)

    def load_audio(self, audio):
        """Fill the bank, with this project's import gains applied."""
        opts = self.asset_settings()["audio"]
        out = audio.load_folder(self.audio_dir,
                                gain=float(opts.get("gain", 1.0)))
        gains = opts.get("gains") or {}
        if isinstance(gains, dict):
            for key, value in gains.items():
                try:
                    audio.set_gain(str(Path(str(key)).stem), float(value))
                except (TypeError, ValueError):
                    continue
        return out

    def _add_import_path(self):
        if str(self.path) not in sys.path:
            sys.path.insert(0, str(self.path))
        if self._script_path_added:
            return
        self._drop_stale_modules()
        self._script_path_added = True

    def _drop_stale_modules(self):
        """Forget scenes/objects/scripts packages belonging to another"""
        for name, module in list(sys.modules.items()):
            if name.split(".")[0] not in PACKAGES:
                continue
            sources = [getattr(module, "__file__", None)]
            sources += [str(p) for p in getattr(module, "__path", ()) or ()]
            sources = [s for s in sources if s]
            if not sources:
                sys.modules.pop(name, None)
                continue
            inside = False
            for source in sources:
                try:
                    Path(source).resolve().relative_to(self.path)
                except ValueError:
                    continue
                inside = True
                break
            if not inside:
                sys.modules.pop(name, None)

    def object_path(self, name):
        """Where an object's script sits, whether or not it exists."""
        p = Path(str(name).replace("\\", "/"))
        if p.suffix != ".py":
            p = p.with_suffix(".py")
        if p.is_absolute():
            return p
        if len(p.parts) > 1:
            return self.path / p
        return self.object_scripts_dir / p.name

    def entity_path(self, name):
        """Where an entity's script sits, whether or not it exists."""
        p = Path(str(name).replace("\\", "/"))
        if p.suffix != ".py":
            p = p.with_suffix(".py")
        if p.is_absolute():
            return p
        if len(p.parts) > 1:
            return self.path / p
        return self.entity_scripts_dir / p.name

    def node_class(self, type_name, base=GameObject):
        """An engine node class from a document's `type`, or None."""
        name = scenedoc.engine_class(type_name)
        if not name:
            return None
        cls = getattr(components, name, None) or \
            getattr(objmod, name, None)
        if cls is None or not (isinstance(cls, type) and
                               issubclass(cls, base)):
            return None
        return cls

    def module_name(self, path, package):
        """The dotted import name of a project script's path.

        A document may name its script anywhere in the project, so the
        import follows the file rather than the folder it was guessed from.
        """
        name = Path(path).stem
        try:
            rel = Path(path).resolve().relative_to(self.path)
        except ValueError:
            return f"{package}.{name}"
        parts = list(rel.parts)
        if not parts:
            return f"{package}.{name}"
        parts[-1] = name
        return ".".join(parts)

    def _spawn_class(self, key, base, doc, path, package, where, folder):
        """Resolve one spawnable: its script's class, or its node type."""
        cache = f"{package}:{key}"
        cached = self._objects.get(cache)
        if cached is not None and cached[1] is base:
            return cached[0]
        if path is None:
            cls = self.node_class((doc or {}).get("type"), base)
            if cls is None:
                raise FileNotFoundError(
                    f"{where} '{key}' not found in {folder}")
            if doc is not None:
                # the placement rides a subclass of its own
                cls = type(cls.__name__, (cls,),
                           {"look_defaults": scenedoc.look(doc)})
            self._objects[cache] = (cls, base)
            return cls
        self._add_import_path()
        module = importlib.import_module(self.module_name(path, package))
        cls = first_object_class(module, base)
        if cls is None:
            raise ValueError(
                f"{self.relative(path)} defines no {base.__name__} subclass")
        if doc is not None:
            cls.look_defaults = scenedoc.look(doc)
        self._objects[cache] = (cls, base)
        return cls

    def object(self, name, base=GameObject):
        """Import an object's script and return its GameObject subclass."""
        key = Path(name).stem
        doc, path = self.object_file(key)
        return self._spawn_class(key, base, doc, path, "scripts.objects",
                                 "object", self.object_scripts_dir)

    def entity(self, name, base=GameObject):
        """Import an entity's script and return its GameObject subclass."""
        key = Path(name).stem
        doc, path = self.entity_file(key)
        return self._spawn_class(key, base, doc, path, "scripts.entities",
                                 "entity", self.entity_scripts_dir)

    def entity_file(self, name):
        """(document, script path) for an entity name."""
        key = Path(name).stem
        doc = self.entity_doc(key)
        path = self.script_path(doc.get("script") if doc else None)
        if path is not None:
            return doc, path
        guess = self.entity_scripts_dir / f"{key}.py"
        return doc, (guess if guess.is_file() else None)

    def spawnable_file(self, name):
        """(document, script path) for a name in either folder."""
        key = Path(name).stem
        doc, path = self.entity_file(key)
        if doc is not None or path is not None:
            return doc, path
        return self.object_file(key)

    def spawnable(self, name, base=GameObject):
        """The class a `spawn(<name>)` or a `uses` entry means.

        An entity document wins: a scripted thing lives in `entities/`
        whatever its node type is called, and only the entity route reads
        `scripts/entities/`.
        """
        key = Path(name).stem
        doc, path = self.entity_file(key)
        if doc is not None or path is not None:
            return self.entity(key, base)
        return self.object(key, base)

    def object_file(self, name):
        """(document, script path) for an object name."""
        key = Path(name).stem
        doc = self.object_doc(key)
        path = self.script_path(doc.get("script") if doc else None)
        if path is not None:
            return doc, path
        guess = self.object_scripts_dir / f"{key}.py"
        return doc, (guess if guess.is_file() else None)

    def reload_objects(self):
        """Forget imported object modules; the next spawn re-imports."""
        self._objects.clear()
        for name in list(sys.modules):
            if name.split(".")[0] == "objects" or \
                    name.startswith("scripts.objects") or \
                    name.startswith("scripts.entities"):
                sys.modules.pop(name, None)

    def check_uses(self, cls, seen=None, base=GameObject):
        """Scripts a scene needs but the project lacks, in either folder."""
        seen = set() if seen is None else seen
        missing = []
        for name in getattr(cls, "uses", ()):
            key = Path(name).stem
            if key in seen:
                continue
            seen.add(key)
            _doc, path = self.spawnable_file(key)
            if path is None:
                if self.node_class((_doc or {}).get("type"), base):
                    # a document naming an engine node needs no script
                    continue
                missing.append(key)
                continue
            try:
                missing.extend(self.check_uses(self.spawnable(key, base),
                                               seen, base))
            except (ImportError, ValueError):
                missing.append(key)
        return missing

    def scene(self, name, game, plan=None):
        """Build a scene: the script's objects, then the document's."""
        doc = self.scene_doc(name)
        path = self.scene_script(name)
        if path is None and doc is None:
            raise FileNotFoundError(
                f"scene '{name}' not found in {self.scenes_dir}")
        if path is not None:
            cls = self._scene_class(path)
        else:
            cls = self._doc_scene_class(doc)
        game.renderer.reset()
        scene = cls(game)
        scene.doc = doc
        scene.plan = dict((doc or {}).get("overrides") or {})
        if plan:
            scene.plan.update(plan)
        self._apply_defaults(scene)
        scene.setup()
        if doc is not None:
            self._place_maps(scene, doc)
            self._place_objects(scene, doc)
        scene.finish_build()
        if self.bake_on_run:
            scene.bake_lights(size=self.bake_size)
        return scene

    def _apply_defaults(self, scene):
        """The manifest's `defaults`, onto a fresh scene before `setup()`."""
        raw = self.get("defaults")
        if not isinstance(raw, dict):
            return scene
        for key in DEFAULT_ORDER:
            if key not in raw or not hasattr(scene, key):
                continue
            value = default_value(key, raw[key])
            if value is not None:
                setattr(scene, key, value)
        return scene

    def _place_maps(self, scene, doc):
        """Spawn a `Map3D` for each name in `maps`."""
        for entry in doc.get("maps") or ():
            row = entry if isinstance(entry, dict) else {"map": entry}
            stem = str(row.get("map") or "").strip()
            if not stem:
                continue
            knobs = {"map": stem}
            for key in ("tint", "group", "solid"):
                if key in row:
                    knobs[key] = row[key]
            how = {"knobs": knobs}
            for key in ("pos", "yaw", "scale"):
                if key in row:
                    how[key] = row[key]
            scene.spawn(components.Map3D, look=how)

    def bake_for_build(self, plan, scenes=None, size=None):
        """Freeze baked lights into PNGs, hidden from the bundle."""
        size = size or self.bake_size
        staged = Path(plan.staged) if plan is not None and \
            getattr(plan, "staged", None) else None
        if staged is None or not staged.is_dir():
            return ["no staged project to bake into"]
        from .renderer import Renderer
        from .game import register_builtin_textures
        renderer = Renderer(64, 64, render_scale=1.0)
        renderer.project = self
        register_builtin_textures(renderer, self)
        self.register_textures(renderer)
        stub = _BakeGame(self, renderer)
        report = []
        names = list(scenes or self.scene_names())
        made = {}
        maps = {}
        try:
            for name in names:
                try:
                    scene = self.scene(name, stub)
                except Exception as exc:                 # noqa: BLE001
                    report.append(f"scene '{name}' skipped: {exc}")
                    continue
                if not scene.bake_lights(size=size):
                    continue
                for _host, inst in scene._bake_targets():
                    model = getattr(inst, "model", None)
                    if model is None:
                        continue
                    rows = []
                    if getattr(model, "has_objects", False):
                        for obj in model.objects:
                            k = obj.get("lightmap")
                            if isinstance(k, str) and k.endswith("@lm"):
                                rows.append((f"{model.name}-{obj['name']}",
                                             model.name, obj["name"], k))
                    k = getattr(model, "lightmap", None)
                    if isinstance(k, str) and k.endswith("@lm"):
                        rows.append((model.name, model.name, None, k))
                    for png, mname, oname, key in rows:
                        if key in maps:
                            continue
                        maps[key] = renderer.read_texture_rgb(key)
                        made[png] = (mname, oname, key)
        finally:
            try:
                renderer.dispose()
            except Exception:                            # noqa: BLE001
                pass
        if not made:
            return ["no bake-mode light found in this project"]
        tex_dir = staged / "textures"
        tex_dir.mkdir(parents=True, exist_ok=True)
        for png, (mname, oname, key) in sorted(made.items()):
            arr = maps.get(key)
            if arr is None:
                continue
            png_path = tex_dir / f"{png}-lm.png"
            try:
                Image.fromarray(arr, "RGB").save(png_path)
            except OSError as exc:
                report.append(f"cannot write {png_path.name}: {exc}")
                continue
            report.append(f"lightmap {png}-lm.png "
                          f"({arr.shape[1]}x{arr.shape[0]})")
            self._patch_stage_model(staged, mname, oname, f"{png}-lm")
        for name in names:
            dropped = self._strip_stage_scene(staged, name)
            if dropped:
                report.append(f"stripped {dropped} bake light(s) "
                              f"from scene '{name}'")
        return report

    @staticmethod
    def _patch_stage_model(staged, model_name, obj_name, lightmap_key):
        """Point a staged model at its baked lightmap."""
        exts = (scenedoc.MODEL3D_EXT, scenedoc.MODEL_EXT,
                scenedoc.MAP3D_EXT)
        for folder in (staged / "models", staged / "maps"):
            for ext in exts:
                path = folder / f"{model_name}{ext}"
                if not path.is_file():
                    continue
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return False
                if not isinstance(doc, dict):
                    return False
                if obj_name is None:
                    doc["lightmap"] = lightmap_key
                else:
                    hit = False
                    for obj in doc.get("objects") or []:
                        if obj.get("name") == obj_name:
                            obj["lightmap"] = lightmap_key
                            hit = True
                    if not hit:
                        return False
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
                os.replace(tmp, path)
                return True
        return False

    @staticmethod
    def _strip_stage_scene(staged, scene_name):
        """Drop every bake-mode light entry from one staged scene doc."""
        for path in (staged / "scenes").glob(f"{scene_name}"
                                             f"{scenedoc.SCENE_EXT}"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return 0
            if not isinstance(doc, dict):
                return 0
            hits = _drop_bake_lights(doc.get("objects") or [])
            if not hits:
                return 0
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            os.replace(tmp, path)
            return hits
        return 0

    def _scene_class(self, path):
        """Import a scene script fresh and hand back its class."""
        self._add_import_path()
        mod_name = f"emoscene_{self.name}_{path.stem}".replace("-", "_")
        spec = importlib.util.spec_from_file_location(mod_name, str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        cls = first_scene_class(module, Scene)
        if cls is None:
            raise ValueError(f"{path.name} defines no Scene subclass")
        missing = self.check_uses(cls, base=getattr(cls, "object_base",
                                                   Object3D))
        if missing:
            names = ", ".join(f"scripts/objects/{n}.py" for n in missing)
            raise FileNotFoundError(
                f"scene '{getattr(cls, 'name', path.stem)}' needs {names}")
        return cls

    def _doc_scene_class(self, doc):
        """A scene class for a document with no script."""
        bases = {"scene3d": Scene3D, "scene2d": Scene2D, "sceneui": SceneUI}
        kind = str(doc.get("kind") or "scene3d").lower()
        base = bases.get(kind, Scene3D)
        name = str(doc.get("name") or "scene")
        return type(name.title().replace(" ", "") or "DocScene", (base,),
                    {"name": name})

    def _place_objects(self, scene, doc):
        """Spawn the objects a document places, parents before their nodes."""
        made = {}
        for entry, parent_entry, _depth in scenedoc.walk(doc):
            if not isinstance(entry, dict):
                continue
            parent = made.get(str(parent_entry.get("id"))) \
                if isinstance(parent_entry, dict) else None
            inst = self._place_one(scene, entry, parent, made,
                                   str(entry.get("id")))
            if inst is not None:
                made[str(entry.get("id"))] = inst
        # a node is only useful once its parent has settled
        scene.sync_tree()
        return scene

    def _place_one(self, scene, entry, parent, made, this_id):
        """Build one placed entry, following an instance to its source."""
        what, how, source = self._entry_build(scene, entry)
        if what is None:
            return None
        how = dict(how)
        how.update(scene.plan.get(this_id) or {})
        pos = how.pop("pos", None)
        if pos is not None and parent is not None:
            # a node's `pos` is parent-relative; convert to world first
            pos = parent.child_world(pos)
        inst = scene.spawn(what, pos=pos, parent=parent, look=how)
        inst.placed_id = this_id
        made[this_id] = inst
        if source is not None:
            # names the instance's children so prefab copies never collide
            for child, child_parent, _d in scenedoc.walk(source):
                if not isinstance(child, dict):
                    continue
                pid = str(child_parent.get("id")) if \
                    isinstance(child_parent, dict) else None
                real_parent = made.get(f"{this_id}/{pid}") \
                    if pid else inst
                cid = f"{this_id}/{child.get('id')}"
                self._place_one(scene, child, real_parent, made, cid)
        return inst

    def _entry_build(self, scene, entry):
        """Resolve an entry to (class, look, source_doc_or_None)."""
        base = getattr(scene, "object_base", GameObject)
        if not scenedoc.is_instance(entry):
            target = scenedoc.script_stem(entry.get("script"))
            what = target or self.node_class(entry.get("type"), base)
            return what, scenedoc.look(entry), None
        value, is_scene = scenedoc.instance_source(entry)
        path = scenedoc.resolve_instance(self, value)
        if path is None:
            return None, {}, None
        src = scenedoc.load(path, "scene" if is_scene else "object")
        if is_scene:
            kind = str(src.get("kind") or "scene3d").lower()
            flat = "2d" if kind in ("scene2d", "sceneui") else "3d"
            what = self.node_class("object2d" if flat == "2d"
                                   else "object3d", base)
            return what, scenedoc.look(entry), src
        target = scenedoc.script_stem(src.get("script"))
        what = target or self.node_class(src.get("type"), base)
        how = scenedoc.look(src)
        how.update(scenedoc.look(entry))
        return what, how, src

    def save_meta(self):
        """Write the manifest in the current sectioned shape, atomically."""
        self.meta["format"] = FORMAT
        self.file_format = FORMAT
        self.legacy = False
        path = self.path / META_NAME
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.meta, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def ensure_templates(self, gitignore=True, readme=True):
        """Write the folder's boilerplate docs, never overwriting them."""
        made = []
        for flag, name, text in (
                (gitignore, const.GITIGNORE_NAME,
                 templates.GITIGNORE_TEMPLATE),
                (readme, const.README_NAME,
                 templates.README_TEMPLATE.format(
                     title=self.title, engine=const.TITLE,
                     version=const.VERSION))):
            if not flag:
                continue
            path = self.path / name
            if path.exists():
                continue
            try:
                path.write_text(text, encoding="utf-8")
            except OSError:
                continue
            made.append(path)
        return made

    def touch(self, kind, name):
        """Make sure a file exists, for New buttons."""
        p = self.dir(kind) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")
        return p

    @classmethod
    def default_path(cls):
        """The demo project if present, else the first."""
        root = paths.projects_dir()
        preferred = root / DEFAULT_PROJECT
        if (preferred / META_NAME).exists():
            return preferred
        if root.is_dir():
            for folder in sorted(root.iterdir()):
                if (folder / META_NAME).exists():
                    return folder
        raise FileNotFoundError(f"no projects in {root}")

    @classmethod
    def create(cls, path, title=None, start_scene=None,
               template=templates.DEFAULT_TEMPLATE):
        """Scaffold a new project from a starter template."""
        path = Path(path).expanduser().resolve()
        for folder in ("scenes", "objects", "entities", "shaders", "models",
                       "maps", "textures", "audio", "scripts/scenes",
                       "scripts/objects", "scripts/entities",
                       "scripts/shaders"):
            (path / folder).mkdir(parents=True, exist_ok=True)
        name = path.name
        stem = str(start_scene or templates.spec(template)["start"])
        meta = templates.manifest(
            template, name,
            title or name.replace("_", " ").title(), stem)
        (path / META_NAME).write_text(json.dumps(meta, indent=1),
                                     encoding="utf-8")
        scripts, documents, model_stems, map_stems = \
            templates.layout(template, stem)
        scripts.setdefault("scripts/helpers.py", templates.SCRIPT_TEMPLATE)
        # a new project ships no look; `shaders/` starts empty
        for rel, text in scripts.items():
            file = path / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text, encoding="utf-8")
        for rel, doc in documents.items():
            scenedoc.save(path / rel, doc)
        for model_stem in model_stems:
            made = templates.make_model(model_stem)
            if made is not None:
                made.save(path / "models"
                          / f"{model_stem}{scenedoc.MODEL3D_EXT}")
        for map_stem in map_stems:
            made = templates.make_map(map_stem)
            if made is not None:
                made.save(path / "maps"
                          / f"{map_stem}{scenedoc.MAP3D_EXT}")
        project = cls(path)
        project.ensure_templates()
        return project


# node types the bake pass strips; scripted lights stay live
LIGHT_NODE_TYPES = frozenset((
    "light3d", "omnilight3d", "spotlight3d", "directionallight3d",
    "light2d", "pointlight2d", "conelight2d", "rectlight2d",
))


def _drop_bake_lights(items):
    """Recursively delete every bake-flagged light entry from a list."""
    if not isinstance(items, list):
        return 0
    hits = 0
    keep = []
    for entry in items:
        if not isinstance(entry, dict):
            keep.append(entry)
            continue
        kids = entry.get("children")
        if isinstance(kids, list):
            hits += _drop_bake_lights(kids)
        kind = str(entry.get("type") or "").lower()
        knob = entry.get("knobs") or {}
        if kind in LIGHT_NODE_TYPES and bool(knob.get("bake", False)):
            hits += 1
            continue
        keep.append(entry)
    items[:] = keep
    return hits


class _Silent:
    """A stand-in whose every attribute read is another silent sink."""

    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _silent_noop

    def __call__(self, *args, **kwargs):
        return None


def _silent_noop(*args, **kwargs):
    return None


class _BakeScreen:
    """Just enough of a pygame Surface for `get_size()` to work."""

    def __init__(self, size=(64, 64)):
        self._size = tuple(int(v) for v in size)

    def get_size(self):
        return self._size


class _BakeGame:
    """A throwaway game host for `Project.scene(name, game)`."""

    scene = None

    def __init__(self, project, renderer):
        from .camera import Camera
        self.project = project
        self.renderer = renderer
        self.audio = _Silent(master=1.0, gains={})
        self.input = _Silent(grabbed=False, mouse_rel=(0, 0),
                             mouse_pos=(0, 0))
        self.fonts = {}
        self.save = _Silent(slot="bake", data={})
        self.screen = _BakeScreen()
        self.camera = Camera(eye=(0.0, 2.0, 8.0))
        self.time = 0.0
        self.last_dt = 1 / 60.0
        self.fps = 0.0
        self.state = "play"
        self.paused = False
        self.running = True
        self.next_scene = None

    @property
    def eye(self):
        return self.camera.eye

    def set_player(self, pos, yaw=None, pitch=None):
        return None

    def load_scene(self, name=None):
        return None

    def play_scene(self, name, fade=0.35):
        return None

    def push_scene(self, name, fade=0.35):
        return None

    def pop_scene(self, fade=0.35):
        return None

    def restart_scene(self):
        return None

    def quit(self):
        self.running = False

    def control_hint(self):
        return ""

    def play_area(self):
        import pygame
        return pygame.Rect(0, 0, 64, 64)
