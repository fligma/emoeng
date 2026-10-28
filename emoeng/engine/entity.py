"""Entities: the props a scene is built from."""

import math

from .timers import Timers


class ModelObject:
    """A project model drawn as a movable dynamic mesh."""

    def __init__(self, scene, model, pos=(0.0, 0.0, 0.0), yaw=0.0,
                 scale=1.0, tint=None, texture=None, blend="opaque"):
        self.scene = scene
        self.model = model
        self.pos = [float(c) for c in pos]
        self.yaw = float(yaw)
        self.scale = scale if isinstance(scale, (tuple, list)) \
            else (float(scale),) * 3
        self.tint = tint
        self.texture = texture or model.texture
        self.blend = blend
        self.dirty = True
        self.mesh = scene.renderer.new_dynamic(
            model.meshdata(self.pos, self.yaw, self.scale, self.tint),
            texture=self.texture, blend=blend)
        self.dirty = False

    def set(self, pos=None, yaw=None, scale=None):
        if pos is not None:
            self.pos = [float(c) for c in pos]
        if yaw is not None:
            self.yaw = float(yaw)
        if scale is not None:
            self.scale = scale if isinstance(scale, (tuple, list)) \
                else (float(scale),) * 3
        self.dirty = True
        return self

    def update(self, dt=0.0):
        if self.dirty and self.mesh is not None:
            self.mesh.update(self.model.meshdata(
                self.pos, self.yaw, self.scale, self.tint))
            self.dirty = False

    def dispose(self):
        if self.mesh is not None:
            self.mesh.dispose()
            self.mesh = None


class Entity:
    """A placeable prop inside a scene."""

    name = "entity"
    uses = ()                   # entities/<name>.py files this one spawns
    clone_attrs = ()            # attributes clone() copies from the source

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 tag=None):
        self.scene = scene
        self.game = scene.game
        self.project = scene.project
        self.renderer = scene.renderer
        self.pos = [float(c) for c in pos]
        self.yaw = float(yaw)
        self.scale = float(scale)
        self.tag = tag or type(self).__name__.lower()
        self.t = 0.0
        self.timers = Timers()
        self.camera = None
        self.alive = True
        self.parent = None          # entity that spawned me through the api
        self.clone_of = None        # entity I was cloned from
        self.children = []          # entities I spawned
        self.clones = []            # clones made from me
        self.meshes = []            # DynamicMesh objects I own
        self.objects = []           # ModelObject instances I own
        self.lights = []            # light dicts I added

    # -- entity tracking -------------------------------------------------
    def attach(self, parent=None, clone_of=None, tag=None):
        """Link me to whoever spawned or cloned me."""
        if tag:
            self.tag = tag
        if parent is not None:
            self.parent = parent
            parent.children.append(self)
        if clone_of is not None:
            self.clone_of = clone_of
            clone_of.clones.append(self)
        return self

    @property
    def is_clone(self):
        """True when this instance was made by clone()."""
        return self.clone_of is not None

    @property
    def is_original(self):
        """True when this entity was not cloned."""
        return self.clone_of is None

    @property
    def clone_depth(self):
        """Clone hops between me and the original; 0 means none."""
        return 0 if self.clone_of is None else self.clone_of.clone_depth + 1

    @property
    def root(self):
        """The original this lineage started with."""
        ent = self
        seen = 0
        while ent.clone_of is not None and ent.clone_of is not ent:
            ent = ent.clone_of
            seen += 1
            if seen > 64:               # guard against a hand-made cycle
                break
        return ent

    @property
    def lineage(self):
        """Ancestors from root to my direct source, oldest first."""
        chain = []
        ent = self.clone_of
        while ent is not None and ent not in chain:
            chain.append(ent)
            ent = ent.clone_of
        chain.reverse()
        return tuple(chain)

    # -- spawning / cloning ----------------------------------------------
    def spawn(self, ent, pos=None, offset=(0.0, 0.0, 0.0), tag=None, **kw):
        """Spawn another entity as my child, through the scene API."""
        if pos is None:
            pos = (self.pos[0] + offset[0], self.pos[1] + offset[1],
                   self.pos[2] + offset[2])
        return self.scene.spawn(ent, pos, parent=self, tag=tag, **kw)

    def clone_kwargs(self):
        """Constructor arguments a clone inherits (see clone_attrs)."""
        return {k: getattr(self, k) for k in self.clone_attrs
                if hasattr(self, k)}

    def clone(self, pos=None, yaw=None, tag=None, **overrides):
        """Build a copy of me, kept in the scene."""
        if pos is None:
            pos = (self.pos[0] + 1.2, self.pos[1], self.pos[2])
        kw = self.clone_kwargs()
        kw.update(overrides)
        return self.scene.spawn(type(self), pos,
                                yaw=self.yaw if yaw is None else yaw,
                                clone_of=self, tag=tag, **kw)

    def despawn(self):
        """Remove me (and my children/clones) from the scene."""
        self.scene.despawn(self)
        return self

    # -- geometry helpers
    def add(self, data, texture="white", blend="opaque"):
        self.scene.add(data, texture=texture, blend=blend)

    def dynamic(self, data, texture="white", blend="add",
                view_model=False, on_top=False):
        """Small mesh reshaped every frame. view_model=True makes it a"""
        mesh = self.scene.renderer.new_dynamic(data, texture=texture,
                                               blend=blend,
                                               view_model=view_model,
                                               on_top=on_top)
        self.meshes.append(mesh)
        return mesh

    def place_model(self, name, pos=None, yaw=None, scale=None, tint=None):
        return self.scene.place_model(
            name,
            self.pos if pos is None else pos,
            self.yaw if yaw is None else yaw,
            self.scale if scale is None else scale,
            tint)

    def model_object(self, name, pos=None, yaw=None, scale=None, tint=None):
        obj = self.scene.model_object(
            name,
            self.pos if pos is None else pos,
            self.yaw if yaw is None else yaw,
            self.scale if scale is None else scale,
            tint)
        self.objects.append(obj)
        return obj

    def light(self, pos=None, color=(1.0, 0.62, 0.24)):
        """Point light that dispose() removes again."""
        light = self.scene.add_light(self.pos if pos is None else pos, color)
        self.lights.append(light)
        return light

    def ground(self, x=None, z=None):
        return self.scene.ground_height(
            self.pos[0] if x is None else x,
            self.pos[2] if z is None else z)

    @property
    def rng(self):
        return self.scene.rng

    @property
    def audio(self):
        return self.scene.audio

    @property
    def input(self):
        return self.scene.input

    @property
    def save(self):
        return self.scene.save

    # -- timers ----------------------------------------------------------
    def after(self, delay, func, *args, **kwargs):
        return self.timers.after(delay, func, *args, **kwargs)

    def every(self, delay, func, *args, **kwargs):
        return self.timers.every(delay, func, *args, **kwargs)

    # -- lifecycle -------------------------------------------------------
    def build(self):
        pass

    def update(self, dt):
        self.t += dt
        self.timers.update(dt)

    def dispose(self):
        """Release everything this entity owns."""
        for mesh in self.meshes:
            mesh.dispose()
        self.meshes.clear()
        for obj in self.objects:
            obj.dispose()
        self.objects.clear()
        for light in self.lights:
            if light in self.scene.lights:
                self.scene.lights.remove(light)
        self.lights.clear()
        self.timers.clear()

    def set(self, pos=None, yaw=None, scale=None):
        if pos is not None:
            self.pos = [float(c) for c in pos]
        if yaw is not None:
            self.yaw = float(yaw)
        if scale is not None:
            self.scale = float(scale)
        return self

    # -- camera rig -------------------------------------------------------
    def set_camera(self, height=1.7, fov=72.0, **opts):
        self.camera = {"height": height, "fov": fov}
        self.camera.update(opts)
        self.scene.camera_rig = self
        self.scene.fov = fov

    def look(self, yaw, pitch):
        self.yaw, self.pitch = yaw, pitch

    def move(self, wish, run, dt):
        """wish: (x, z) world-axis input, sliding along ground."""
        s = self.scene
        speed = s.move_speed[1] if run else s.move_speed[0]
        wx, wz = wish
        length = math.hypot(wx, wz)
        if length > 1.0:
            wx, wz = wx / length, wz / length
        self.pos[0] += wx * speed * dt
        self.pos[2] += wz * speed * dt
        r = math.hypot(self.pos[0], self.pos[2])
        if s.world_radius and r > s.world_radius:
            k = s.world_radius / r
            self.pos[0] *= k
            self.pos[2] *= k
        self.pos[1] = self.ground()

    def eye(self):
        c = self.camera or {}
        return [self.pos[0], self.ground() + c.get("height", 1.7),
                self.pos[2]]

    def __repr__(self):
        where = " ".join(f"{c:g}" for c in self.pos)
        origin = f" clone of {type(self.clone_of).__name__}" \
            if self.is_clone else ""
        return f"<{type(self).__name__} {self.tag} ({where}){origin}>"


def first_entity_class(module, base=Entity):
    """The Entity subclass an entities/<name>.py file defines."""
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
