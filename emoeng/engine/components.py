"""Component nodes: the parts an object is built out of."""

import math

import numpy as np
import pygame

from . import colors, meshes, ui
from . import collision as collmod
from .objects import ModelObject, Object2D, Object3D, UV_KNOBS


def _as_half(value, fallback):
    """A `half` knob as three floats."""
    if value is None:
        return tuple(float(c) for c in fallback)
    if isinstance(value, (int, float)):
        return (float(value),) * 3
    got = [float(c) for c in value]
    if len(got) == 2:
        got = [got[0], got[1], got[0]]
    while len(got) < 3:
        got.append(fallback[len(got)])
    return tuple(got)


def _as_vec(value, count, fallback):
    """A knob as a list of numbers, padded to `count`."""
    if value is None:
        return tuple(float(c) for c in fallback)
    if isinstance(value, (int, float)):
        return (float(value),) + (0.0,) * (count - 1)
    got = [float(c) for c in value][:count]
    while len(got) < count:
        got.append(float(fallback[len(got)]) if len(fallback) > len(got)
                   else 0.0)
    return tuple(got)


class Collider3D(Object3D):
    """A world shape: editor-drawn, mover-readable."""

    kind = "3d"
    name = "collision3d"
    clone_attrs = ("shape", "half", "solid", "group")
    doc_knobs = ("shape", "half", "solid", "group", "offset")

    # a unit cube at the node: visible when unsized
    shape = "box"               # box | sphere | capsule
    half = (0.5, 0.5, 0.5)      # metres from the centre to each face
    solid = True                # False: reports, never stops
    group = ""                  # who this stops; "" = everybody
    # where the shape sits relative to the node's pivot
    offset = (0.0, 0.0, 0.0)

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 tag=None, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag)
        self.set_knobs(knobs)
        self.inside = []        # bodies currently overlapping (hitboxes)

    # -- the shape ----------------------------------------------------------
    def centre(self):
        """The shape's world middle, plus the node offset."""
        k = float(self.scale) or 1.0
        ox, oy, oz = _as_vec(self.offset, 3, (0.0, 0.0, 0.0))
        return [self.pos[0] + k * ox, self.pos[1] + k * oy,
                self.pos[2] + k * oz]

    def box(self):
        """(centre, half) in world metres - what a sweep tests."""
        k = float(self.scale) or 1.0
        h = _as_half(self.half, (0.5, 0.5, 0.5))
        return (self.centre(), tuple(c * k for c in h))

    def radius(self):
        """The one number a round shape needs, in world metres."""
        k = float(self.scale) or 1.0
        h = _as_half(self.half, (0.5, 0.5, 0.5))
        return max(h[0], h[2]) * k

    def contains(self, point):
        """Is a world point inside me?"""
        c, h = self.box()
        x, y, z = (float(point[0]), float(point[1]), float(point[2]))
        if self.shape == "sphere":
            r = self.radius()
            return math.dist((x, y, z), tuple(c)) <= r
        if self.shape == "capsule":
            r = max(h[0], h[2])
            lo = c[1] - h[1] + r
            hi = c[1] + h[1] - r
            dy = max(lo - y, 0.0, y - hi)
            return math.hypot(x - c[0], z - c[2]) ** 2 + dy * dy <= r * r
        return all(abs(v - centre) <= half
                   for v, centre, half in zip((x, y, z), c, h))

    def touches(self, other):
        """Does another body's box overlap mine? `other` is a box()."""
        from .collision import overlap
        c, h = self.box()
        return overlap((c, h), other)

    # -- the editor's picture of me ----------------------------------------
    GIZMO = (0.24, 0.62, 0.94)      # a cool blue: obviously not a prop

    def gizmo(self, col=None):
        """A translucent shape mesh, for the Edit view."""
        c, h = self.box()
        col = col or self.GIZMO
        if self.shape in ("sphere", "capsule"):
            r = max(h[0], h[2])
            return meshes.cylinder(c, r=r, h=2.0 * max(h[1], r), seg=12,
                                   col=col)
        return meshes.box(c, size=(2.0 * h[0], 2.0 * h[1], 2.0 * h[2]),
                          col=col)

    # -- lifecycle ---------------------------------------------------------
    def build(self):
        self.scene.add_collider(self)
        return self

    def dispose(self):
        self.scene.remove_collider(self)
        return super().dispose()

    def set(self, pos=None, yaw=None, scale=None, half=None, shape=None,
            solid=None, group=None, offset=None):
        if half is not None:
            self.half = _as_half(half, self.half)
        if shape is not None:
            self.shape = str(shape)
        if solid is not None:
            self.solid = bool(solid)
        if group is not None:
            self.group = str(group)
        if offset is not None:
            self.offset = _as_vec(offset, 3, (0.0, 0.0, 0.0))
        return super().set(pos=pos, yaw=yaw, scale=scale)

    def __repr__(self):
        where = " ".join(f"{c:g}" for c in self.centre())
        return (f"<{type(self).__name__} {self.shape} ({where}) "
                f"{'solid' if self.solid else 'see-through'}>")


class Collision3D(Collider3D):
    """A wall, plinth or crate side: solid to movers."""

    name = "collision3d"
    solid = True


class Hitbox3D(Collider3D):
    """A volume that reports occupants and blocks nobody."""

    name = "hitbox3d"
    solid = False
    doc_knobs = Collider3D.doc_knobs + ("notice", "oneshot")
    notice = ""                  # "" = the player; else a tag/class/"*"
    oneshot = False              # fire once and stop watching

    def watching(self):
        """The live objects my `notice` picks out."""
        if self.oneshot and self.inside:
            return ()
        if not self.notice:
            return tuple(
                [self.scene.player] if self.scene.player else ())
        if self.notice == "*":
            return tuple(o for o in self.scene.objects
                         if o.alive and o is not self)
        wanted = str(self.notice)
        return tuple(o for o in self.scene.objects if o.alive
                     and o is not self and (o.tag == wanted
                                            or type(o).__name__ == wanted))

    def body_of(self, obj):
        """A mover's box, or a guess from body size."""
        box = getattr(obj, "box", None)
        if callable(box) and isinstance(obj, Collider3D):
            return box()
        pos = getattr(obj, "pos", None)
        if pos is None or len(pos) < 3:
            return None
        h = getattr(obj, "body_half", None) or (0.35, 0.9, 0.35)
        return ([float(c) for c in pos], tuple(float(v) for v in h))

    def update(self, dt):
        super().update(dt)
        here = []
        for obj in self.watching():
            body = self.body_of(obj)
            if body is None or not self.touches(body):
                continue
            here.append(obj)
            if obj not in self.inside:
                self.on_enter(obj)
        for obj in self.inside:
            if obj not in here:
                self.on_exit(obj)
        self.inside = here
        return self

    def on_enter(self, other):
        """A body came into me. Override in a script."""
        return other

    def on_exit(self, other):
        """A body left me. Override in a script."""
        return other

    def __repr__(self):
        where = " ".join(f"{c:g}" for c in self.centre())
        return f"<Hitbox3D {self.shape} ({where}) {len(self.inside)} in>"


class Model3D(Object3D):
    """The picture node: one .model3d, hung under whatever moves it."""

    kind = "3d"
    name = "model3d"
    clone_attrs = ("model", "tint", "texture", "blend", "stamp")
    doc_knobs = ("tint", "blend", "stamp", "opacity") + UV_KNOBS

    model = None                 # a models/<name>.model3d stem
    tint = None                  # a colour, or None for the model's own
    texture = None               # one sheet over the whole model
    blend = "opaque"
    stamp = False

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 model=None, tag=None, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag)
        if model is not None:
            self.model = model
        self.obj = None
        self.set_knobs(knobs)

    def model_name(self):
        """Which model to draw: mine or the document's."""
        return self.model or self.look.get("model")

    def build(self):
        name = self.model_name()
        if not name:
            # no picture yet is a half-built branch, not an error
            return self
        if self.stamp:
            self.scene.place_model(name, self.pos, self.yaw, self.scale,
                                   self.tint or self.look.get("color"),
                                   self.opacity, shader=self.shader_pas,
                                   uv=self.uv_look())
            return self
        self.obj = self.model_object(
            name, texture=self.texture or self.look.get("texture"),
            tint=self.tint or self.look.get("color"), blend=self.blend)
        return self

    def update(self, dt):
        super().update(dt)
        if self.obj is None:
            name = self.model_name()
            if name and not self.stamp:
                self.build()          # the editor has since filled it in
            return self
        self.obj.set(self.pos, self.yaw, self.scale)
        self.obj.update(dt)
        return self

    def __repr__(self):
        return f"<Model3D {self.model_name() or '(nothing)'} at " \
               f"{self.tree_path()}>"


class Map3D(Object3D):
    """A whole `.map3d`, drawn and collided with for free."""

    kind = "3d"
    name = "map3d"
    clone_attrs = ("map", "tint", "solid", "group")
    doc_knobs = ("solid", "group", "tint") + UV_KNOBS

    map = None                  # a maps/<name>.map3d stem
    tint = None                 # a colour, or None for the map's own
    solid = True                # a map stops you by default
    group = ""                  # who this stops; "" = everybody

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 map=None, tag=None, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag)
        if map is not None:
            self.map = map
        self.obj = None
        self.mesh = None
        self._stamp = None
        self.set_knobs(knobs)

    def map_name(self):
        """Which map to draw: my knob or the document's."""
        return self.map or self.look.get("map")

    def _tint(self):
        return self.tint or self.look.get("color")

    def _world_tris(self, model):
        """The map's world triangles at this node's transform. `meshdata`"""
        md = model.meshdata(self.pos, self.yaw, self.scale, self._tint())
        pts = md.pos
        return [pts[i:i + 3] for i in range(0, len(pts) - 2, 3)]

    def build(self):
        name = self.map_name()
        if not name:
            # no map picked yet is a half-built branch
            return self
        model = self.project.map(name)
        self.obj = ModelObject(self.scene, model, self.pos, self.yaw,
                               self.scale, self._tint(), uv=self.uv_look())
        self.objects.append(self.obj)
        self.mesh = collmod.TriMesh(self._world_tris(model))
        self._stamp = (tuple(self.pos), float(self.yaw), float(self.scale))
        self.scene.add_collider(self)
        return self

    def _rebuild(self):
        """Re-file triangles after a move, so collision follows."""
        name = self.map_name()
        if not name:
            return
        self.mesh = collmod.TriMesh(
            self._world_tris(self.project.map(name)))
        self._stamp = (tuple(self.pos), float(self.yaw), float(self.scale))

    def box(self):
        """The map's overall AABB as (centre, half), for a broadphase."""
        if self.mesh is None or self.mesh.bounds is None:
            return ([float(c) for c in self.pos], (0.0, 0.0, 0.0))
        lo, hi = self.mesh.bounds
        centre = [(a + b) / 2.0 for a, b in zip(lo, hi)]
        half = [(b - a) / 2.0 for a, b in zip(lo, hi)]
        return (centre, tuple(half))

    def contains(self, point):
        """Is a world point enclosed by the map's shell?"""
        return self.mesh is not None and self.mesh.contains(point)

    def set(self, pos=None, yaw=None, scale=None, tint=None, solid=None,
            group=None):
        if tint is not None:
            self.tint = tint
        if solid is not None:
            self.solid = bool(solid)
        if group is not None:
            self.group = str(group)
        moved = pos is not None or yaw is not None or scale is not None
        super().set(pos=pos, yaw=yaw, scale=scale)
        if moved and self.obj is not None:
            self.obj.set(self.pos, self.yaw, self.scale)
            self._rebuild()
        return self

    def update(self, dt):
        super().update(dt)
        if self.obj is None:
            name = self.map_name()
            if name:
                self.build()          # the editor has since filled it in
            return self
        self.obj.set(self.pos, self.yaw, self.scale)
        self.obj.update(dt)
        stamp = (tuple(self.pos), float(self.yaw), float(self.scale))
        if stamp != self._stamp:      # a mover slid the map without set()
            self._rebuild()
        return self

    def dispose(self):
        self.scene.remove_collider(self)
        self.mesh = None
        return super().dispose()

    def __repr__(self):
        return f"<Map3D {self.map_name() or '(nothing)'} at " \
               f"{self.tree_path()}>"


class Sprite2D(Object2D):
    """The flat picture node: a texture or `.model2d` parts."""

    kind = "2d"
    name = "sprite2d"
    clone_attrs = ("model", "playing", "speed")
    doc_knobs = ("playing", "speed", "opacity")

    model = None                 # a models/<name>.model2d stem
    playing = True               # the rig's tracks run on their own
    speed = 1.0                  # and this fast

    def __init__(self, scene, pos=(0.0, 0.0), size=(64.0, 64.0),
                 texture="white", col=(1.0, 1.0, 1.0), rot=0.0,
                 model=None, tag=None, **knobs):
        super().__init__(scene, pos=pos, size=size, texture=texture,
                         col=col, rot=rot, tag=tag)
        if model is not None:
            self.model = model
        self.parts = []           # [(part, ModelObject-ish mesh)]
        self.rig = None
        self.set_knobs(knobs)

    def model_name(self):
        return self.model or self.look.get("model")

    def build(self):
        name = self.model_name()
        if not name:
            return super().build()          # a plain textured quad
        self.rig = self.scene.project.model2d(name)
        # the rig's box wins; parts are cut in sheet pixels
        self.size = (float(self.rig.size[0]), float(self.rig.size[1]))
        self.parts = []
        for part in self.rig.parts:
            uv = tuple(part.get("uv") or (0.0, 0.0, 1.0, 1.0))
            mesh = self.dynamic(
                self._part_quad(part, uv),
                texture=part.get("texture") or self.rig.texture or "white",
                blend=self.blend)
            self.parts.append([part, uv, mesh])
        return self

    def _part_quad(self, part, uv):
        """One rig part posed by its own track."""
        p = _as_vec(part.get("pos"), 2, (0.0, 0.0))
        size = self.size
        c, s = math.cos(self.rot), math.sin(self.rot)
        k = float(size[0] / max(self.rig.size[0], 1.0)) if self.rig else 1.0
        lx, ly = p[0] * k, p[1] * k
        x = self.pos[0] + lx * c - ly * s
        y = self.pos[1] + lx * s + ly * c
        return meshes.quad2d((x, y), size, col=self.col, uv=uv,
                             rot=self.rot + float(part.get("rot") or 0.0),
                             anchor=(0.5, 0.5))

    def track_value(self, part, prop, t):
        """A rig track's value at time `t`, else 0.0."""
        if self.rig is None:
            return 0.0
        for track in self.rig.tracks:
            if track.get("part") != part.get("name") or \
                    track.get("prop") != prop:
                continue
            keys = sorted(track.get("keys") or (), key=lambda k: k[0])
            if not keys:
                return 0.0
            if t <= keys[0][0]:
                return float(keys[0][1])
            for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
                if t <= t1:
                    span = t1 - t0
                    k = 0.0 if span <= 0.0 else (t - t0) / span
                    return float(v0) + (float(v1) - float(v0)) * k
            return float(keys[-1][1])
        return 0.0

    def update(self, dt):
        if self.rig is None:
            return super().update(dt)
        if self.playing:
            self.t += dt * float(self.speed)
            self.timers.update(dt)
        for row in self.parts:
            part, uv, mesh = row
            got = dict(part)
            rot = self.track_value(part, "rot", self.t)
            if rot:
                got["rot"] = float(part.get("rot") or 0.0) + rot
            row[1] = uv
            mesh.update(self._part_quad(got, uv))
        return self

    def __repr__(self):
        what = self.model_name() or self.texture
        return f"<Sprite2D {what} at {self.tree_path()}>"


class Collision2D(Object2D):
    """A pixel-world rect a mover cannot pass."""

    kind = "2d"
    name = "collision2d"
    clone_attrs = ("solid", "group")
    doc_knobs = ("solid", "group")

    solid = True
    group = ""

    def __init__(self, scene, pos=(0.0, 0.0), size=(64.0, 64.0),
                 texture="#4c8fd6", col=(1.0, 1.0, 1.0), rot=0.0, tag=None,
                 **knobs):
        # flat colliders keep a quad; the Edit view shows it
        super().__init__(scene, pos=pos, size=size, texture=texture,
                         col=col, rot=rot, tag=tag)
        self.inside = []        # bodies currently overlapping (hitboxes)
        self.set_knobs(knobs)

    def build(self):
        self.scene.add_collider(self)
        return self

    def dispose(self):
        self.scene.remove_collider(self)
        return super().dispose()

    def touches(self, other):
        """Does `other`, an (x, y, w, h) rect, overlap me?"""
        from .collision import rects_overlap
        return rects_overlap(self.rect(), other)

    def __repr__(self):
        x, y, w, h = self.rect()
        return f"<Collision2D ({x:g} {y:g} {w:g} {h:g})>"


class Hitbox2D(Collision2D):
    """A flat trigger area: reports occupants, stops nothing."""

    name = "hitbox2d"
    solid = False
    doc_knobs = Collision2D.doc_knobs + ("notice", "oneshot")
    notice = ""
    oneshot = False

    def watching(self):
        if self.oneshot and self.inside:
            return ()
        if not self.notice:
            return tuple(
                [self.scene.player] if self.scene.player else ())
        if self.notice == "*":
            return tuple(o for o in self.scene.objects
                         if o.alive and o is not self)
        wanted = str(self.notice)
        return tuple(o for o in self.scene.objects if o.alive
                     and o is not self and (o.tag == wanted
                                            or type(o).__name__ == wanted))

    def body_of(self, obj):
        box = getattr(obj, "rect", None)
        return box() if callable(box) else None

    def update(self, dt):
        super().update(dt)
        here = []
        for obj in self.watching():
            body = self.body_of(obj)
            if body is None or not self.touches(body):
                continue
            here.append(obj)
            if obj not in self.inside:
                self.on_enter(obj)
        for obj in self.inside:
            if obj not in here:
                self.on_exit(obj)
        self.inside = here
        return self

    def on_enter(self, other):
        return other

    def on_exit(self, other):
        return other


class LightNode3D(Object3D):
    """A light you can hang on anything."""

    kind = "3d"
    name = "light3d"
    clone_attrs = ("shape", "color", "radius", "energy", "angle", "inner",
                   "layer", "glow", "flicker", "pulse", "enabled", "bake")
    doc_knobs = clone_attrs

    shape = "point"
    color = "torch"
    radius = 8.0
    energy = 1.0
    angle = None                 # a spot's cone, degrees
    inner = None                 # how much of it is full brightness
    layer = 0
    glow = 0.0
    flicker = 0.0
    pulse = 0.0
    enabled = True
    bake = False                 # freeze into a lightmap instead of lighting

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 color=None, shape=None, tag=None, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag)
        if color is not None:
            self.color = color
        if shape is not None:
            self.shape = shape
        self.beam = None
        self.set_knobs(knobs)

    def build(self):
        kw = {}
        for key in ("radius", "energy", "layer", "glow", "flicker",
                    "pulse", "bake"):
            kw[key] = getattr(self, key)
        for key in ("angle", "inner"):
            if getattr(self, key) is not None:
                kw[key] = getattr(self, key)
        self.beam = self.scene.add_light(self.pos, color=self.color,
                                         shape=self.shape, follow=self,
                                         **kw)
        self.beam.enabled = bool(self.enabled)
        self.lights.append(self.beam)
        return self

    def __repr__(self):
        return f"<Light3D {self.shape} {self.color} at {self.tree_path()}>"


class LightNode2D(Sprite2D):
    """The 2D twin: a light under the same node rules."""

    kind = "2d"
    name = "light2d"
    clone_attrs = ("shape", "color", "radius", "energy", "angle", "cast",
                   "outer", "enabled", "bake")
    doc_knobs = clone_attrs

    shape = "radial"
    color = "torch"
    radius = 180.0
    energy = 1.0
    angle = None
    cast = True                  # walls in scene.blockers hide what is out
    outer = None
    enabled = True
    bake = False

    def __init__(self, scene, pos=(0.0, 0.0), size=(64.0, 64.0),
                 color=None, shape=None, tag=None, **knobs):
        super().__init__(scene, pos=pos, size=size, tag=tag)
        if color is not None:
            self.color = color
        if shape is not None:
            self.shape = shape
        self.beam = None
        self.set_knobs(knobs)

    def build(self):
        kw = {"radius": float(self.radius), "energy": float(self.energy),
              "cast": bool(self.cast)}
        for key in ("angle", "outer"):
            if getattr(self, key) is not None:
                kw[key] = getattr(self, key)
        self.beam = self.scene.add_light(self.pos, color=self.color,
                                         shape=self.shape, follow=self,
                                         **kw)
        self.beam.enabled = bool(self.enabled)
        self.lights.append(self.beam)
        return self

    def update(self, dt):
        self.t += dt
        self.timers.update(dt)
        return self

    def __repr__(self):
        return f"<Light2D {self.shape} {self.color} at {self.tree_path()}>"


# fixed-shape lights: the type is the preset
def _knobs_without(cls, drop):
    """A light class's knobs, minus the preset-spelled names."""
    return tuple(k for k in cls.doc_knobs if k not in drop)


class OmniLight3D(LightNode3D):
    """A 3D light shining everywhere from one point."""

    name = "omnilight3d"
    shape = "point"
    doc_knobs = _knobs_without(LightNode3D, ("shape",))
    clone_attrs = tuple(k for k in LightNode3D.clone_attrs if k != "shape")


class SpotLight3D(LightNode3D):
    """A 3D cone of light from one point."""

    name = "spotlight3d"
    shape = "spot"
    angle = 45.0
    doc_knobs = _knobs_without(LightNode3D, ("shape",))
    clone_attrs = tuple(k for k in LightNode3D.clone_attrs if k != "shape")


class DirectionalLight3D(LightNode3D):
    """The sun: one direction, no position, lights the whole world."""

    name = "directionallight3d"
    shape = "sun"
    doc_knobs = _knobs_without(LightNode3D, ("shape", "radius", "angle",
                                             "inner", "glow"))
    clone_attrs = tuple(k for k in LightNode3D.clone_attrs
                        if k not in ("shape", "radius", "angle", "inner",
                                     "glow"))


class PointLight2D(LightNode2D):
    """A 2D light that fades out evenly in every direction."""

    name = "pointlight2d"
    shape = "radial"
    doc_knobs = _knobs_without(LightNode2D, ("shape",))
    clone_attrs = tuple(k for k in LightNode2D.clone_attrs if k != "shape")


class ConeLight2D(LightNode2D):
    """A 2D cone from the node, turned by `rot`."""

    name = "conelight2d"
    shape = "cone"
    angle = 76.0
    doc_knobs = _knobs_without(LightNode2D, ("shape",))
    clone_attrs = tuple(k for k in LightNode2D.clone_attrs if k != "shape")


class RectLight2D(LightNode2D):
    """A 2D shaft of light with straight sides."""

    name = "rectlight2d"
    shape = "rect"
    doc_knobs = _knobs_without(LightNode2D, ("shape",))
    clone_attrs = tuple(k for k in LightNode2D.clone_attrs if k != "shape")


_text_seq = 0


def paint_text(owner, text, color, font_name, font_size):
    """Render words onto a new RGBA texture."""
    global _text_seq
    _text_seq += 1
    key = f"node_text_{id(owner)}_{_text_seq}"
    rgb = colors.rgb(color, (1.0, 1.0, 1.0))
    byte_col = tuple(round(c * 255) for c in rgb)
    font = ui.load_font(str(font_name), max(1, int(font_size)))
    label = font.render(str(text), True, byte_col)
    w, h = label.get_size()
    canvas = pygame.Surface((max(w, 1), max(h, 1)), pygame.SRCALPHA)
    canvas.fill(byte_col + (0,))
    canvas.blit(label, (0, 0))
    arr = np.dstack((
        np.transpose(pygame.surfarray.array3d(canvas), (1, 0, 2)),
        np.transpose(pygame.surfarray.array_alpha(canvas)),
    )).astype(np.uint8)
    owner.renderer.texture(key, arr, rgba=True, repeat=False,
                           filter="nearest", mipmaps=False)
    return key, float(w), float(h)


def release_text(owner, key):
    """Drop a painted-words texture again; hands back None to store."""
    if key is None:
        return None
    tex = owner.renderer.textures.pop(key, None)
    if tex is not None:
        tex.release()
    return None


class Text3D(Object3D):
    """Words standing in the 3D world."""

    kind = "3d"
    name = "text3d"
    doc_knobs = ("text", "color", "font_name", "font_size", "height",
                 "billboard", "blend", "opacity")
    clone_attrs = ("text", "color", "font_name", "font_size", "height",
                   "billboard")

    text = ""
    color = (1.0, 1.0, 1.0)      # the words' own colour
    font_name = "tahoma"
    font_size = 48
    height = 0.5                 # metres, capital to baseline as it comes
    billboard = True
    blend = "alpha"

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 text=None, color=None, height=None, tag=None, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag)
        if text is not None:
            self.text = str(text)
        if color is not None:
            self.color = colors.rgb(color, self.color)
        if height is not None:
            self.height = float(height)
        self._key = None
        self._size = (0.0, 0.0)  # the picture in metres, after `height`
        self._at = None          # last transform drawn; see update()
        self.mesh = None
        self.set_knobs(knobs)

    def build(self):
        if not self.text:
            return self                # empty words draw nothing
        if self._key is None:
            self._repaint()
        self.mesh = self.dynamic(self._quad(), texture=self._key,
                                 blend=self.blend)
        return self

    def _repaint(self):
        """A fresh picture for the current words; returns its key."""
        self._key = release_text(self, self._key)
        self._key, w, h = paint_text(self, self.text, self.color,
                                     self.font_name, self.font_size)
        k = max(0.001, float(self.height)) / max(h, 1.0)
        self._size = (w * k, float(self.height))
        return self._key

    def _face(self):
        """The yaw that turns the words toward the camera."""
        if not self.billboard:
            return self.yaw
        cam = getattr(self.scene, "view", None)
        if cam is None:
            return self.yaw
        look = cam.view_yaw() if hasattr(cam, "view_yaw") else cam.yaw
        return look + math.pi

    def _quad(self):
        """The words' geometry right where the node stands now."""
        k = float(self.scale) or 1.0
        w, h = self._size[0] * k, self._size[1] * k
        yaw = self._face()
        m = meshes.MeshData()
        c, s = math.cos(yaw), math.sin(yaw)
        corners = ((-w / 2.0, -h / 2.0), (w / 2.0, -h / 2.0),
                   (w / 2.0, h / 2.0), (-w / 2.0, h / 2.0))
        uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        pts = [(self.pos[0] + lx * c, self.pos[1] + ly,
                self.pos[2] - lx * s) for lx, ly in corners]
        # one winding only; the alpha pass neither depth-tests nor culls
        vs = [m.vert(pts[i], (s, 0.0, c), uvs[i], (1.0, 1.0, 1.0))
              for i in range(4)]
        m.tri(vs[0], vs[1], vs[2])
        m.tri(vs[0], vs[2], vs[3])
        return m

    def set_text(self, text):
        """Say something else: repaint, and the mesh follows."""
        self.text = str(text or "")
        if not self.text:
            if self.mesh is not None:
                self.mesh.dispose()
                self.mesh = None
            self._key = release_text(self, self._key)
            return self
        if self.mesh is None:
            return self.build()
        self._repaint()
        self.mesh.texture = self._key
        self.mesh.update(self._quad())
        return self

    def update(self, dt):
        super().update(dt)
        if self.mesh is None:
            return self
        at = (tuple(round(c, 4) for c in self.pos), round(self.yaw, 4),
              round(self.scale, 4), round(self._face(), 4))
        if at != self._at:
            # moved or turned since the last draw: re-stand the words
            self._at = at
            self.mesh.update(self._quad())
        return self

    def dispose(self):
        self._key = release_text(self, self._key)
        return super().dispose()


class Text2D(Object2D):
    """Words drawn as a sprite in a flat world."""

    kind = "2d"
    name = "text2d"
    doc_knobs = ("text", "color", "font_name", "font_size", "opacity")
    clone_attrs = ("text", "color", "font_name", "font_size")

    text = ""
    color = (1.0, 1.0, 1.0)
    font_name = "tahoma"
    font_size = 24

    def __init__(self, scene, pos=(0.0, 0.0), text=None, color=None,
                 font_name=None, font_size=None, tag=None, blend="hud",
                 **knobs):
        super().__init__(scene, pos=pos, size=(8.0, 8.0), texture="white",
                         col=(1.0, 1.0, 1.0), tag=tag, blend=blend)
        if text is not None:
            self.text = str(text)
        if color is not None:
            self.color = colors.rgb(color, self.color)
        if font_name is not None:
            self.font_name = str(font_name)
        if font_size is not None:
            self.font_size = int(font_size)
        self._key = None
        self.set_knobs(knobs)

    def build(self):
        if not self.text:
            return self                # empty words draw nothing
        self._paint()
        return super().build()

    def _paint(self):
        """A fresh picture for the current words; returns its key."""
        self._key = release_text(self, self._key)
        self._key, w, h = paint_text(self, self.text, self.color,
                                     self.font_name, self.font_size)
        self.texture = self._key
        self.size = (w, h)
        self.dirty = True
        return self._key

    def set_text(self, text):
        """Say something else: repaint, and the quad follows."""
        self.text = str(text or "")
        if self.mesh is None:
            if self.text:
                self.build()
            return self
        if not self.text:
            self.mesh.dispose()
            self.mesh = None
            self._key = release_text(self, self._key)
            return self
        key = self._paint()
        self.mesh.texture = key
        self.mesh.update(self.quad())
        self.dirty = False
        return self

    def dispose(self):
        self._key = release_text(self, self._key)
        return super().dispose()


class _Emitter:
    """Shared behaviour of the two audio emitters."""

    doc_knobs = ("sound", "gain", "reach", "loop", "autoplay")
    clone_attrs = doc_knobs

    sound = ""
    gain = 1.0
    reach = 12.0
    loop = False
    autoplay = False

    def _emitter_init(self):
        self._ch = None            # the live mixer channel, if any
        self._base = 0.0           # the volume play() was asked for
        self._key_played = ""
        self._started = False

    def listener(self):
        """The point ear distances measure from, or None."""
        return getattr(self.game, "eye", None)

    def gain_at(self):
        """How loud the sound is right now, distance and all."""
        g = max(0.0, float(self.gain))
        ear = self.listener()
        if ear is None:
            return g
        n = min(len(ear), len(self.pos))
        d = math.dist([float(c) for c in ear[:n]],
                      [float(c) for c in self.pos[:n]])
        return g * max(0.0, 1.0 - d / max(1.0, float(self.reach)))

    def _loud(self):
        """The channel volume the mixer should hold right now."""
        vol = self._base * self.gain_at()
        vol *= self.audio.gain(self._key_played) * self.audio.master
        return max(0.0, min(1.0, vol))

    def play(self, sound=None, gain=None):
        """Start the sound (or `sound`); returns the channel or None."""
        key = str(self.sound if sound is None else sound or "")
        if not key:
            return None
        self.stop()
        self._key_played = key
        self._base = max(0.0, float(self.gain if gain is None else gain))
        self._started = True
        # Audio.play already folds per-sound gain and master in
        self._ch = self.audio.play(key, volume=self._base * self.gain_at(),
                                   loops=-1 if self.loop else 0)
        return self._ch

    def stop(self):
        """Silence the emitter, now and until the next play()."""
        if self._ch is not None:
            try:
                self._ch.stop()
            except Exception:
                pass
            self._ch = None
        self._started = False
        return self

    def build(self):
        super().build()
        if self.autoplay and self.sound:
            self.play()
        return self

    def update(self, dt):
        super().update(dt)
        if not (self.loop and self._started):
            return self
        loud = self._loud()
        if self._ch is None:
            # silent out of reach; the loop restarts when audible
            if loud > 0.0:
                self._ch = self.audio.play(self._key_played,
                                           volume=self._base *
                                           self.gain_at(), loops=-1)
            return self
        if loud <= 0.0:
            try:
                self._ch.stop()
            except Exception:
                pass
            self._ch = None
            return self
        if not self._ch.get_busy():
            self._ch = None
            return self
        try:
            self._ch.set_volume(loud)
        except Exception:
            pass
        return self

    def dispose(self):
        self.stop()
        return super().dispose()


class AudioEmitter3D(_Emitter, Object3D):
    """A sound placed at a point in the 3D world."""

    kind = "3d"
    name = "audioemitter3d"

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 tag=None, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag)
        self._emitter_init()
        self.set_knobs(knobs)


class AudioEmitter2D(_Emitter, Object2D):
    """A sound placed in a flat world, with no picture."""

    kind = "2d"
    name = "audioemitter2d"

    def __init__(self, scene, pos=(0.0, 0.0), tag=None, **knobs):
        super().__init__(scene, pos=pos, size=(8.0, 8.0), tag=tag)
        self._emitter_init()
        self.set_knobs(knobs)

    def build(self):
        # deliberately not Object2D.build: an emitter owns no quad
        if self.autoplay and self.sound:
            self.play()
        return self


class _Timer:
    """Shared heartbeat of Timer3D and Timer2D."""

    doc_knobs = ("interval", "repeat", "autostart", "fn")
    clone_attrs = doc_knobs

    interval = 1.0
    repeat = False
    autostart = True
    fn = "on_timeout"

    def _timer_init(self):
        self._left = max(0.0, float(self.interval))
        self.running = False

    def start(self):
        """Begin counting again from a fresh interval."""
        self._left = max(0.0, float(self.interval))
        self.running = True
        return self

    def stop(self):
        """Stop counting; a later start() begins from the top again."""
        self.running = False
        return self

    def on_timeout(self):
        """The node's hook: override it in a script."""
        return self

    def _fire(self):
        self.on_timeout()
        name = str(self.fn or "").strip()
        if not name or name == "on_timeout":
            return self
        for target in (self, self.scene,
                       getattr(self.scene, "player", None)):
            func = getattr(target, name, None) if target is not None \
                else None
            if callable(func):
                func()
                break
        return self

    def _timer_update(self, dt):
        if not self.running:
            return self
        self._left -= dt
        if self._left > 0.0:
            return self
        if self.repeat:
            self._left += max(0.001, float(self.interval))
        else:
            self.running = False
        self._fire()
        return self

    def build(self):
        super().build()
        if self.autostart:
            self.start()
        return self

    def update(self, dt):
        super().update(dt)
        return self._timer_update(dt)


class Timer3D(_Timer, Object3D):
    """A countdown sitting at a place in the 3D world."""

    kind = "3d"
    name = "timer3d"

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 tag=None, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag)
        self._timer_init()
        self.set_knobs(knobs)


class Timer2D(_Timer, Object2D):
    """A countdown in the flat world; same rules as Timer3D."""

    kind = "2d"
    name = "timer2d"

    def __init__(self, scene, pos=(0.0, 0.0), tag=None, **knobs):
        super().__init__(scene, pos=pos, size=(8.0, 8.0), tag=tag)
        self._timer_init()
        self.set_knobs(knobs)

    def build(self):
        # not Object2D.build: a timer owns no quad
        if self.autostart:
            self.start()
        return self


class _TriggerBus:
    """Knobs that let a volume broadcast a trigger with no script."""

    enter = ""                   # the trigger a body arriving fires
    exit = ""                    # ... and one leaving

    def tell(self, name, other):
        """Broadcast a named trigger, with the body as its value."""
        if name:
            self.scene.broadcast(str(name), other)
        return name


class Trigger3D(_TriggerBus, Hitbox3D):
    """A volume that reports who walked in, and broadcasts to the scene."""

    kind = "3d"
    name = "trigger3d"
    clone_attrs = Collider3D.clone_attrs + ("enter", "exit")
    doc_knobs = Hitbox3D.doc_knobs + ("enter", "exit")

    def on_enter(self, other):
        self.tell(self.enter, other)
        return other

    def on_exit(self, other):
        self.tell(self.exit, other)
        return other


class Trigger2D(_TriggerBus, Hitbox2D):
    """The flat twin: a rectangle that reports and broadcasts."""

    kind = "2d"
    name = "trigger2d"
    clone_attrs = Collision2D.clone_attrs + ("enter", "exit")
    doc_knobs = Hitbox2D.doc_knobs + ("enter", "exit")

    def on_enter(self, other):
        self.tell(self.enter, other)
        return other

    def on_exit(self, other):
        self.tell(self.exit, other)
        return other


class Marker3D(Collider3D):
    """A named place only: solid off, no physics."""

    kind = "3d"
    name = "marker3d"
    solid = False
    half = (0.25, 0.25, 0.25)


class Marker2D(Collision2D):
    """The 2D twin: a small named, invisible rect."""

    kind = "2d"
    name = "marker2d"
    solid = False

    def __init__(self, scene, pos=(0.0, 0.0), size=(16.0, 16.0), tag=None,
                 **knobs):
        super().__init__(scene, pos=pos, size=size, tag=tag, **knobs)


# engine classes a document can name with `type` alone
ENGINE_NODES = {
    "Model3D": Model3D,
    "Sprite2D": Sprite2D,
    "Collision3D": Collision3D,
    "Hitbox3D": Hitbox3D,
    "Collision2D": Collision2D,
    "Hitbox2D": Hitbox2D,
    "LightNode3D": LightNode3D,
    "LightNode2D": LightNode2D,
    "OmniLight3D": OmniLight3D,
    "SpotLight3D": SpotLight3D,
    "DirectionalLight3D": DirectionalLight3D,
    "PointLight2D": PointLight2D,
    "ConeLight2D": ConeLight2D,
    "RectLight2D": RectLight2D,
    "AudioEmitter3D": AudioEmitter3D,
    "AudioEmitter2D": AudioEmitter2D,
    "Text3D": Text3D,
    "Text2D": Text2D,
    "Timer3D": Timer3D,
    "Timer2D": Timer2D,
    "Trigger3D": Trigger3D,
    "Trigger2D": Trigger2D,
    "Marker3D": Marker3D,
    "Marker2D": Marker2D,
    "Object3D": Object3D,
    "Object2D": Object2D,
}
