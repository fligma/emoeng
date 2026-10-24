"""Scene authoring API for fligengine projects.

A project looks like this:

    projects/<name>/project.flig
    projects/<name>/scenes/<scene>.py     one SceneBase subclass each
    projects/<name>/entities/<prop>.py    one Entity subclass each
    projects/<name>/scripts/<helper>.py   plain python, imported normally
    projects/<name>/models/<name>.model   vertex/face meshes
    projects/<name>/textures/<name>.png   images uploaded by stem name
    projects/<name>/audio/<name>.wav      sounds loaded by stem name

A scene owns its world: it submits geometry through the shape builders in
engine.meshes, places `.model` files, defines lights, spawns entities and
may draw 2D overlays or claim the status bar. Everything static is merged
into batched GPU meshes; moving props are entities, ModelObjects or
DynamicMeshes.

Entities are declared per scene and placed through the scene API, so the
engine tracks, updates and disposes them:

    class Main(SceneBase):
        uses = ("bonfire", "orb")

        def setup(self):
            self.fire = self.spawn("bonfire", (0.0, 0.0, 0.0))
            self.orb = self.spawn(Orb, (0.0, 1.2, -4.0))
"""

import math

import numpy as np

from . import meshes
from .entity import Entity, ModelObject        # noqa: F401  (re-exported)
from .timers import Timers


class SceneBase:
    """One playable (or cutscene) world chunk.

    Override the knobs to steer the camera/chrome, and the hooks:
      setup()          build geometry + spawn entities (called once per
                       load; batches are compiled right after you return)
      update(dt)       per frame; entity updates run automatically
      handle_event(e)  consume a pygame event (return True) or None
      overlay(screen)  2D passes drawn over the 3D frame
      status()         status-bar panel strings while playing
      ground_height(x, z) terrain under the player
      spawn_point()    ((x, y, z), yaw) where the player materialises

Declare the entity files this scene uses in `uses`; they are checked
against the project when the scene loads, and `self.spawn("name", pos)`
resolves them by file stem.

Every scene also gets `self.timers` (after/every) and `self.save` (the
project's JSON save slot); both die with the scene.
    """

    name = "scene"
    uses = ()                       # entities/<name>.py this scene spawns

    # camera / movement knobs (read by the game loop)
    camera = "walk"                 # "walk" glues to the ground, "fly" is free
    move_speed = (6.0, 12.0)        # (walk, run) m/s
    eye_height = 2.0                # above ground in walk mode
    world_radius = 128.0            # hard camera clamp from origin; 0 = off
                                    # (levels that contain the player, like a
                                    # gallery of rooms, set 0 and manage it)
    fov = 68.0                      # vertical field of view, degrees

    # lighting / atmosphere defaults the renderer uploads every frame
    clear_color = (0.02, 0.02, 0.03)
    fog_color = (0.06, 0.06, 0.09)
    fog_near = 40.0
    fog_far = 220.0
    ambient = (0.22, 0.22, 0.26)
    sun_dir = (0.35, 0.75, 0.5)     # normalised by the renderer
    sun_col = (0.22, 0.20, 0.18)

    # optional screen passes, e.g. ("dither", "scanlines", "vignette")
    post = ()

    def __init__(self, game, seed=7):
        self.game = game
        self.project = game.project
        self.renderer = game.renderer
        self.audio = game.audio
        self.input = game.input
        self.rng = np.random.default_rng(seed)
        self.entities = []
        self.lights = []            # dicts: {"pos": xyz, "color": rgb}
        self.camera_rig = None      # entity that claimed set_camera()
        self.lock_input = False     # freezes the player (cutscenes etc.)
        self.t = 0.0                # seconds since setup(), advanced here
        self.timers = Timers()
        self.save = game.save

    # -- world construction
    def setup(self):
        pass

    def add(self, data, texture="white", blend="opaque"):
        """Queue batched static geometry (merged per texture+blend)."""
        self.renderer.add(data, texture=texture, blend=blend)

    def spawn(self, ent, pos=(0.0, 0.0, 0.0), parent=None, clone_of=None,
              tag=None, **kw):
        """Create an entity, attach it to the scene and build it.

        `ent` is an Entity subclass, or the stem of an entities/<name>.py
        file. `parent`, `clone_of` and `tag` are the bookkeeping the
        engine fills in when an entity spawns or clones another one.
        """
        cls = self.entity_class(ent)
        inst = cls(self, pos=pos, **kw)
        inst.attach(parent=parent, clone_of=clone_of, tag=tag)
        self.entities.append(inst)
        try:
            inst.build()
        except Exception:
            self.entities.remove(inst)
            inst.alive = False
            inst.dispose()
            raise
        return inst

    def despawn(self, ent):
        """Take an entity - and everything it spawned or cloned - out."""
        if ent is None or not getattr(ent, "alive", False):
            return False
        for child in list(ent.children) + list(ent.clones):
            self.despawn(child)
        ent.alive = False
        ent.dispose()
        if ent in self.entities:
            self.entities.remove(ent)
        return True

    def entity_class(self, ent):
        """Resolve a class or an entities/<name> file to its class."""
        if isinstance(ent, str):
            return self.project.entity(ent)
        if not (isinstance(ent, type) and issubclass(ent, Entity)):
            raise TypeError(f"{ent!r} is not an Entity class or file name")
        return ent

    def entities_of(self, ent):
        """Every live entity of one class (or entities/<name> file)."""
        cls = self.entity_class(ent)
        return [e for e in self.entities if isinstance(e, cls) and e.alive]

    def by_tag(self, tag):
        """The first live entity with that tag, or None."""
        for ent in self.entities:
            if ent.alive and ent.tag == tag:
                return ent
        return None

    def model(self, name):
        """Load (cached) a model from the project's models folder."""
        return self.project.model(name)

    def place_model(self, name, pos, yaw=0.0, scale=1.0, tint=None):
        """Stamp a .model into the static batch at a world position."""
        m = self.model(name)
        self.add(m.meshdata(pos, yaw, scale, tint),
                 texture=m.texture)
        return m

    def model_object(self, name, pos, yaw=0.0, scale=1.0, tint=None,
                     texture=None, blend="opaque"):
        """A movable model instance (dynamic mesh)."""
        return ModelObject(self, self.model(name), pos, yaw, scale, tint,
                           texture, blend)

    def add_light(self, pos, color):
        light = {"pos": tuple(float(c) for c in pos),
                 "color": tuple(float(c) for c in color)}
        self.lights.append(light)
        return light

    def finish_build(self):
        self.renderer.build()

    # -- timers / flow
    def after(self, delay, func, *args, **kwargs):
        """Call func once, delay seconds from now."""
        return self.timers.after(delay, func, *args, **kwargs)

    def every(self, delay, func, *args, **kwargs):
        """Call func every delay seconds until the scene ends."""
        return self.timers.every(delay, func, *args, **kwargs)

    def play_scene(self, name, fade=0.35):
        """Fade out, load another scene from the project, fade back in."""
        self.game.play_scene(name, fade=fade)

    # -- per-frame
    def update(self, dt):
        self.t += dt
        self.timers.update(dt)
        for ent in list(self.entities):
            if ent.alive:
                ent.update(dt)

    def handle_event(self, e):
        return False

    def overlay(self, screen):
        pass

    # -- world queries
    def ground_height(self, x, z):
        return 0.0

    def spawn_point(self):
        return (0.0, 0.0, 0.0), 0.0

    def on_enter(self):
        """Called every time play mode (re)starts this scene; drops the
        player (and the camera rig, if one claimed the camera) onto the
        spawn point looking where the scene wants."""
        pos, yaw = self.spawn_point()
        self.game.set_player(pos, yaw)
        rig = self.camera_rig
        if rig is not None:
            rig.pos = [pos[0], self.ground_height(pos[0], pos[2]), pos[2]]
            rig.yaw, rig.pitch = yaw, 0.0

    def on_exit(self):
        self.timers.clear()

    def status(self):
        return [self.name]

    # -- player shortcuts
    @property
    def player(self):
        """Live camera position [x, y, z]; mutate via game.set_player."""
        return self.game.eye


def first_scene_class(module, base=SceneBase):
    """The SceneBase subclass a scenes/<name>.py file defines.

    A class defined in this very file wins over any scene class the file
    happened to import.
    """
    fallback = None
    for obj in vars(module).values():
        if not (isinstance(obj, type) and issubclass(obj, base)) \
                or obj is base:
            continue
        if obj.__module__ == module.__name__:
            return obj
        if fallback is None:
            fallback = obj
    return fallback
