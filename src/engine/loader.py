"""Projects: a folder with a manifest, scenes, entities, scripts, models,
textures and audio. The Game and the editor both load everything through
here.

    project.flig      JSON manifest (name, title, start scene, PS2 settings)
    scenes/*.py       one SceneBase subclass per file
    entities/*.py     one Entity subclass per file - the scene's props
    scripts/*.py      shared python modules
    models/*.model    vertex/face meshes
    textures/*.png    uploaded to the renderer under the file's stem
    audio/*.wav|ogg   loaded into the audio bank under the file's stem

Scenes name the entities they place in `uses`, and both scenes and
entities reach each other by file stem: `self.spawn("flame", pos)` inside
any scene or entity resolves `entities/flame.py` through this module.
"""

import importlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from . import model as models
from . import paths
from .entity import Entity, first_entity_class
from .scene import SceneBase, first_scene_class

META_NAME = "project.flig"
KINDS = ("scenes", "entities", "scripts", "models", "textures", "audio")
DEFAULT_PROJECT = "demo"
PACKAGES = ("scenes", "entities", "scripts")

SCENE_TEMPLATE = '''"""Scene: edit me, then press F5 in the editor to play it.

`uses` lists the entities/<name>.py files this scene places; the loader
checks them on load and `self.spawn("prop", pos)` resolves them by stem.
WASD moves, mouse looks, ESC pauses. `self.place_model` stamps a .model
file, `self.add` takes generated geometry, `self.add_light` throws a warm
point light. Override ground_height for terrain and spawn_point for where
the camera starts.
"""

import math

import pygame

import fligengine as fe
from fligengine.engine import meshes
from entities.prop import Prop


class Main(fe.SceneBase):
    name = "main"
    uses = ("prop",)
    camera = "walk"
    move_speed = (6.0, 11.0)
    world_radius = 60.0

    clear_color = (0.035, 0.040, 0.060)
    fog_color = (0.045, 0.050, 0.075)
    fog_near = 18.0
    fog_far = 95.0
    ambient = (0.20, 0.21, 0.26)
    sun_dir = (0.4, 0.8, 0.3)
    sun_col = (0.22, 0.20, 0.24)
    post = ("dither", "vignette")

    def setup(self):
        self.renderer.texture("grid", fe.proctex.grid(128, 8))
        self.renderer.texture("ground", fe.proctex.ground(256))
        self.add(meshes.plane(size=(80, 80), seg=16), texture="ground")
        self.place_model("box", (0.0, 0.0, 0.0), 0.0, 3.0)
        self.add(meshes.box(centre=(0, 0.75, -4), size=(3, 1.5, 1),
                            col=(0.7, 0.6, 0.5)), texture="grid")
        self.prop = self.spawn(Prop, (0.0, 1.8, 0.0))
        self.prop.clone((1.6, 1.2, 0.0))
        self.fire = self.add_light((2.0, 2.4, 2.0), (1.0, 0.55, 0.22))
        self.audio.tone("hum", 70.0, 900, "sine", 0.18)
        self.hum = self.audio.play("hum", 0.5, loops=-1)

    def update(self, dt):
        super().update(dt)
        self.fire["color"] = (1.0, 0.45 + 0.15 * math.sin(self.t * 9.0),
                              0.18)

    def spawn_point(self):
        return (0.0, 0.0, 9.0), 0.0

    def status(self):
        return [self.name, "fligengine project"]

    def overlay(self, screen):
        fe.ui.text(screen, self.game.fonts["small"],
                   "WASD move  mouse look  ESC pause", (14, 12))
'''

ENTITY_TEMPLATE = '''"""Entity: a prop scenes place, and that can copy itself.

Scene side:

    from entities.prop import Prop
    self.spawn(Prop, (0.0, 1.2, 0.0))     # or self.spawn("prop", pos)

`clone_attrs` lists what clone() carries over, so `prop.clone((2, 1.2, 0))`
builds a second Prop that knows it is a copy: is_clone, clone_of, root,
depth and lineage all report the relationship. Entities can also spawn
other entities with `self.spawn(...)` in build() or update(dt).
"""

import math

import fligengine as fe
from fligengine.engine import meshes


class Prop(fe.Entity):
    name = "prop"
    uses = ()                          # entities this one spawns
    clone_attrs = ("size", "tint")     # what clone() copies from the source

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 size=1.0, tint=(1.0, 0.72, 0.35)):
        super().__init__(scene, pos, yaw, scale)
        self.size = float(size)
        self.tint = tint

    def build(self):
        self.mesh = self.dynamic(self._mesh(), texture="grid")

    def _mesh(self):
        return meshes.box(centre=self.pos, size=(0.6,) * 3, col=self.tint)

    def update(self, dt):
        super().update(dt)
        bob = 0.18 * math.sin(self.t * 1.8)
        self.mesh.update(meshes.box(
            centre=(self.pos[0], self.pos[1] + bob, self.pos[2]),
            size=(0.6,) * 3, col=self.tint))
'''

SCRIPT_TEMPLATE = '''"""Shared helpers for this project.

Import them from a scene with `from scripts import helpers`.
"""


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value
'''


class Project:
    """A fligengine project folder."""

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        meta_path = self.path / META_NAME
        if not meta_path.exists():
            raise FileNotFoundError(f"no {META_NAME} in {self.path}")
        try:
            self.meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"bad {META_NAME}: {exc}") from exc
        self.name = self.meta.get("name") or self.path.name
        self.title = self.meta.get("title") or self.name
        self.size = tuple(self.meta.get("size", [1152, 700]))
        self.render_scale = float(self.meta.get("render_scale", 1.0))
        self.post = tuple(self.meta.get("post", ()))
        self.seed = int(self.meta.get("seed", 7))
        scenes = self.scene_names()
        self.start = self.meta.get("start") or (scenes[0] if scenes else None)
        self._models = {}
        self._textures = {}
        self._entities = {}
        self._script_path_added = False

    # -------------------------------------------------------------- paths
    def dir(self, kind):
        d = self.path / kind
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def scenes_dir(self):
        return self.dir("scenes")

    @property
    def entities_dir(self):
        return self.dir("entities")

    @property
    def scripts_dir(self):
        return self.dir("scripts")

    @property
    def models_dir(self):
        return self.dir("models")

    @property
    def textures_dir(self):
        return self.dir("textures")

    @property
    def audio_dir(self):
        return self.dir("audio")

    @property
    def saves_dir(self):
        return self.dir("saves")

    def files(self, kind):
        d = self.dir(kind)
        return sorted(p for p in d.iterdir() if p.is_file())

    def scene_names(self):
        return [p.stem for p in self.files("scenes") if p.suffix == ".py"]

    def entity_names(self):
        return [p.stem for p in self.files("entities") if p.suffix == ".py"]

    def script_names(self):
        return [p.stem for p in self.files("scripts") if p.suffix == ".py"]

    def model_names(self):
        return [p.stem for p in self.files("models") if p.suffix == ".model"]

    def texture_files(self):
        return [p for p in self.files("textures")
                if p.suffix.lower() in (".png", ".jpg", ".jpeg")]

    def audio_files(self):
        return [p for p in self.files("audio")
                if p.suffix.lower() in (".wav", ".ogg", ".mp3", ".flac")]

    def relative(self, path):
        try:
            return str(Path(path).resolve().relative_to(self.path))
        except ValueError:
            return str(path)

    # ------------------------------------------------------------- models
    def model_path(self, name):
        p = Path(name)
        if p.suffix != ".model":
            p = p.with_suffix(".model")
        return p if p.is_absolute() else self.models_dir / p.name

    def model(self, name):
        """Load and cache a model by stem (fresh copy per caller is not
        needed: scenes only read it)."""
        key = Path(name).stem
        if key in self._models:
            return self._models[key]
        m = models.Model.load(self.model_path(key))
        self._models[key] = m
        return m

    def store_model(self, model, name=None):
        """Save a model into the project and refresh the cache."""
        stem = Path(name or model.name).stem
        path = model.save(self.models_dir / f"{stem}.model")
        self._models[stem] = model
        return path

    def reload_models(self):
        self._models.clear()

    # ----------------------------------------------------------- textures
    def texture(self, name):
        key = Path(name).stem
        if key in self._textures:
            return self._textures[key]
        for ext in (".png", ".jpg", ".jpeg"):
            p = self.textures_dir / f"{key}{ext}"
            if p.exists():
                arr = np.asarray(Image.open(p).convert("RGBA"))
                if arr[..., 3].min() > 250:
                    arr = arr[..., :3]
                arr = np.ascontiguousarray(arr)
                self._textures[key] = arr
                return arr
        return None

    def register_textures(self, renderer, verbose=None):
        """Upload every texture file plus a procedural checker fallback."""
        count = 0
        for p in self.texture_files():
            arr = self.texture(p.stem)
            if arr is not None:
                renderer.texture(p.stem, arr,
                                 rgba=arr.shape[2] == 4, repeat=True)
                count += 1
        if verbose:
            verbose(f"uploaded {count} textures")
        return count

    # ------------------------------------------------------------ scripts
    def _add_import_path(self):
        if str(self.path) not in sys.path:
            sys.path.insert(0, str(self.path))
        if self._script_path_added:
            return
        self._drop_stale_modules()
        self._script_path_added = True

    def _drop_stale_modules(self):
        """Forget scenes/entities/scripts packages belonging to another
        project, so this project's files are imported instead of the ones
        a previously opened project left in sys.modules."""
        for name, module in list(sys.modules.items()):
            if name.split(".")[0] not in PACKAGES:
                continue
            source = getattr(module, "__file__", None)
            if not source:
                continue
            try:
                Path(source).resolve().relative_to(self.path)
            except ValueError:
                sys.modules.pop(name, None)

    # ----------------------------------------------------------- entities
    def entity_path(self, name):
        p = Path(name)
        if p.suffix != ".py":
            p = p.with_suffix(".py")
        return p if p.is_absolute() else self.entities_dir / p.name

    def entity(self, name):
        """Import entities/<name>.py and return its Entity subclass.

        The module is imported as `entities.<name>`, the same name a
        scene gets with `from entities.<name> import X`, so both paths
        hand back the same class.
        """
        key = Path(name).stem
        if key in self._entities:
            return self._entities[key]
        path = self.entity_path(key)
        if not path.exists():
            raise FileNotFoundError(
                f"entity '{key}' not found in {self.entities_dir}")
        self._add_import_path()
        module = importlib.import_module(f"entities.{key}")
        cls = first_entity_class(module, Entity)
        if cls is None:
            raise ValueError(f"entities/{key}.py defines no Entity subclass")
        self._entities[key] = cls
        return cls

    def reload_entities(self):
        """Forget imported entity modules; the next spawn re-imports."""
        self._entities.clear()
        for name in list(sys.modules):
            if name.split(".")[0] == "entities":
                sys.modules.pop(name, None)

    def check_uses(self, cls, seen=None):
        """Entity files a scene (or entity) needs but the project lacks.

        Walks `uses` transitively, so a scene that spawns a bonfire which
        spawns flames reports a missing entities/flame.py too.
        """
        seen = set() if seen is None else seen
        missing = []
        for name in getattr(cls, "uses", ()):
            key = Path(name).stem
            if key in seen:
                continue
            seen.add(key)
            if not self.entity_path(key).exists():
                missing.append(key)
                continue
            try:
                missing.extend(self.check_uses(self.entity(key), seen))
            except (ImportError, ValueError):
                missing.append(key)
        return missing

    def scene(self, name, game):
        """Import scenes/<name>.py fresh and build the scene."""
        path = self.scenes_dir / f"{name}.py"
        if not path.exists():
            raise FileNotFoundError(f"scene '{name}' not found in {path.parent}")
        self._add_import_path()
        mod_name = f"fligscene_{self.name}_{name}".replace("-", "_")
        spec = importlib.util.spec_from_file_location(mod_name, str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        cls = first_scene_class(module, SceneBase)
        if cls is None:
            raise ValueError(f"{path.name} defines no SceneBase subclass")
        missing = self.check_uses(cls)
        if missing:
            names = ", ".join(f"entities/{n}.py" for n in missing)
            raise FileNotFoundError(
                f"scene '{getattr(cls, 'name', name)}' needs {names}")
        game.renderer.reset()
        scene = cls(game)
        scene.setup()
        scene.finish_build()
        return scene

    # ------------------------------------------------------------- assets
    def load_audio(self, audio):
        return audio.load_folder(self.audio_dir)

    def save_meta(self):
        (self.path / META_NAME).write_text(
            json.dumps(self.meta, indent=1), encoding="utf-8")

    def touch(self, kind, name):
        """Make sure a file exists (used by the editor's New buttons)."""
        p = self.dir(kind) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")
        return p

    # ------------------------------------------------------------ factory
    @classmethod
    def default_path(cls):
        """The demo project if it exists, else the first real project."""
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
    def create(cls, path, title=None, start_scene="main"):
        """Scaffold a new project: a playable scene, a spawnable entity and
        a box model."""
        path = Path(path).expanduser().resolve()
        (path / "scenes").mkdir(parents=True, exist_ok=True)
        (path / "entities").mkdir(exist_ok=True)
        (path / "scripts").mkdir(exist_ok=True)
        (path / "models").mkdir(exist_ok=True)
        (path / "textures").mkdir(exist_ok=True)
        (path / "audio").mkdir(exist_ok=True)
        name = path.name
        meta = {
            "name": name,
            "title": title or name.replace("_", " ").title(),
            "start": start_scene,
            "size": [1152, 700],
            "render_scale": 0.75,
            "post": ["dither", "vignette"],
            "seed": 7,
        }
        (path / META_NAME).write_text(json.dumps(meta, indent=1),
                                      encoding="utf-8")
        (path / "scenes" / f"{start_scene}.py").write_text(
            SCENE_TEMPLATE, encoding="utf-8")
        (path / "entities" / "prop.py").write_text(
            ENTITY_TEMPLATE, encoding="utf-8")
        (path / "scripts" / "helpers.py").write_text(
            SCRIPT_TEMPLATE, encoding="utf-8")
        box = models.new_model("box", 1.0, texture="grid", name="box")
        box.save(path / "models" / "box.model")
        return cls(path)
