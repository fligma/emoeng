"""Objects: what a scene is built from."""

import math

import numpy as np
import pygame

from . import colors, meshes, shaders as shadermod, ui
from .timers import Timers


def _pair(value, default=1.0):
    """A 2-tuple from a number, a pair, or `default`."""
    if isinstance(value, (int, float)):
        return (float(value), float(value))
    got = tuple(float(c) for c in value)[:2]
    return got + (default,) * (2 - len(got))


def _uv_look(obj):
    """An object's uv fit, when it carries one."""
    fn = getattr(obj, "uv_look", None)
    return fn() if callable(fn) else None


UV_KNOBS = ("uv_tile", "uv_scale", "uv_offset", "uv_spin")


class ModelObject:
    """A project model as one dynamic mesh per surface."""

    def __init__(self, scene, model, pos=(0.0, 0.0, 0.0), yaw=0.0,
                 scale=1.0, tint=None, texture=None, blend="opaque",
                 opacity=1.0, shader=None, uv=None):
        self.scene = scene
        self.model = model
        self.pos = [float(c) for c in pos]
        self.yaw = float(yaw)
        self.scale = scale if isinstance(scale, (tuple, list)) \
            else (float(scale),) * 3
        self.tint = colors.rgb(tint) if tint is not None else None
        self.texture = colors.key(texture) if texture else model.texture
        self.blend = blend
        self.opacity = scene.renderer.opacity_of(opacity)
        self.uv = uv            # (tile, scale, offset, spin), or None
        self.surfaces = {}     # face index -> texture key, per instance
        self.dirty = True
        self.meshes = []       # [(texture key, DynamicMesh)]
        self.shader = scene.renderer.shader_pass(shader)
        self._build()
        self.dirty = False

    def uv_pin(self):
        """Where the metre sheet is pinned, and my facing."""
        return meshes.frame_pin(self.pos, self.yaw)

    def _groups(self):
        """(texture key, MeshData) for how this instance looks now."""
        md = self.model.meshdata(self.pos, self.yaw, self.scale, self.tint)
        md.align_tex()
        if self.texture != self.model.texture:
            md.tex = [None] * len(md.tex)    # one sheet paints it all
        for face, key in self.surfaces.items():
            if 0 <= face < len(md.tex):
                md.tex[face] = key
        return md.texture_groups(self.texture)

    def _build(self):
        """(Re)create one GPU mesh per surface."""
        self.dispose()
        pas = self.shader
        # a `texture` look changes the sheet; `uv` is a program
        look = pas if pas is not None and pas.mode == "uv" else None
        bake = pas is not None and pas.mode == "texture"
        self.meshes = []
        for key, md in self._groups():
            sheet = self.scene.renderer.shaded_texture(key, pas) \
                if bake else key
            mesh = self.scene.renderer.new_dynamic(
                md, texture=sheet, blend=self.blend,
                opacity=self.opacity, shader=look, uv=self.uv,
                frame=self.uv_pin)
            # baked models sample their own lightmap, not the live floor
            mesh.lightmap = md.lightmap
            self.meshes.append((key, mesh))

    def set_opacity(self, opacity):
        """Fade every surface of this instance to a new solidity."""
        self.opacity = self.scene.renderer.opacity_of(opacity)
        for _, mesh in self.meshes:
            mesh.set_opacity(self.opacity)
        return self

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

    def set_surface(self, face, key):
        """Retexture one model face on this instance (None = default)."""
        got = colors.key(key) if key else None
        if got:
            self.surfaces[int(face)] = got
        else:
            self.surfaces.pop(int(face), None)
        self.dirty = True
        return self

    def set_uv(self, uv):
        """Re-map this instance's texture; None goes back to the sheet."""
        self.uv = uv
        for _, mesh in self.meshes:
            mesh.set_uv(self.scene.renderer.uv_for(mesh.texture, mesh.blend,
                                                   uv, mesh.anchor))
        return self

    def update(self, dt=0.0):
        if not self.dirty:
            return
        self.dirty = False
        groups = self._groups()
        if len(groups) == len(self.meshes) and \
                all(g[0] == m[0] for g, m in zip(groups, self.meshes)):
            for m, (_, md) in zip(self.meshes, groups):
                m[1].update(md)               # same surfaces: just move
        else:
            self._build()                     # surfaces changed: rebuild

    def dispose(self):
        for _, mesh in self.meshes:
            mesh.dispose()
        self.meshes = []


def answers_to(obj, word):
    """Does that word name me: document id, tag or class?
    A placed node answers to the id its document gave."""
    want = str(word or "").strip()
    if not want:
        return False
    leaf = (getattr(obj, "doc_key", None) or "").rsplit("/", 1)[-1]
    named = (getattr(obj, "placed_id", None) or "").rsplit("/", 1)[-1]
    return want in (leaf, named, getattr(obj, "tag", None),
                    type(obj).__name__)


def node_from(roots, parts):
    """The node a branch names, from whichever root answers.
    None when no root reaches the branch's end."""
    if not parts:
        return None
    for start in roots:
        if not getattr(start, "alive", True) or \
                not answers_to(start, parts[0]):
            continue
        node = start
        for part in parts[1:]:
            node = node.find_child(part)
            if node is None:
                break
        if node is not None:
            return node
    return None


def node_branch(cls):
    """The nodes a class's own document lists, as it was stamped.
    The nearest definer answers, so a subclass never rebuilds
    the branch its parent's document already spoke for."""
    for klass in getattr(cls, "__mro__", ()) or ():
        if "doc_nodes" in klass.__dict__:
            return klass.__dict__["doc_nodes"] or ()
    return ()


class GameObject:
    """Shared tree, clone and lifecycle machinery for every object type."""

    kind = "object"
    name = "object"
    uses = ()                   # extra files this object spawns
    clone_attrs = ()
    clone_gap = (1.2,)
    look_camera = None
    light_layer = None
    doc_knobs = ()              # attributes a document may set and read back
    doc_nodes = ()              # the branch my own document files under me
    doc_name = None             # the document that spoke for me
    opacity = 1.0
    shader = None
    shader_pas = None

    def __init__(self, scene, pos=(0.0, 0.0), tag=None):
        self.scene = scene
        self.game = scene.game
        self.project = scene.project
        self.renderer = scene.renderer
        self.pos = [float(c) for c in pos]
        self.tag = tag or type(self).__name__.lower()
        self.t = 0.0
        self.timers = Timers()
        self.alive = True
        self.parent = None
        self.children = []
        self.clone_of = None
        # what a `.scene` says about my placement and look
        self.look = {}
        self.doc_key = None         # my stable name there: `Torch#0`
        self.placed_id = None       # the `id` a scene document placed me under
        self.clones = []
        self.meshes = []
        self.objects = []
        self.lights = []
        # my transform as the parent sees it; `pos` is world
        self.local_pos = list(self.pos)

    # -- tree tracking ---------------------------------------------------
    def attach(self, parent=None, clone_of=None, tag=None):
        """Link me to whoever spawned or cloned me."""
        if tag:
            self.tag = tag
        if parent is not None:
            self.parent = parent
            parent.children.append(self)
            self.push_local()
        if clone_of is not None:
            self.clone_of = clone_of
            clone_of.clones.append(self)
        return self

    # -- hierarchy -------------------------------------------------------
    def set_knobs(self, knobs):
        """Apply per-instance node settings from a document (typo-safe)."""
        for key, value in (knobs or {}).items():
            if not hasattr(type(self), key):
                raise TypeError(f"{type(self).__name__} has no knob "
                                f"'{key}'")
            setattr(self, key, value)
        return self

    def is_child_of(self, other):
        """Was I placed under them, or under a node?"""
        ent, seen = self.parent, 0
        while ent is not None and seen < 64:
            if ent is other:
                return True
            ent = ent.parent
            seen += 1
        return False

    def descendants(self):
        """Every node under me, my children first and theirs after."""
        out = []
        for child in self.children:
            if not getattr(child, "alive", True) or child in out:
                continue
            out.append(child)
            out.extend(child.descendants())
        return out

    def ancestors(self):
        """Who I sit under, nearest first."""
        out, ent, seen = [], self.parent, 0
        while ent is not None and seen < 64:
            out.append(ent)
            ent = ent.parent
            seen += 1
        return out

    def tree_path(self):
        """My branch as words: `Torch#0/Flame#0`.
        A document key is the branch; hand-built nodes walk parents."""
        if self.doc_key:
            return self.doc_key
        chain = [ent for ent in reversed(self.ancestors())]
        chain.append(self)
        return "/".join(getattr(ent, "doc_key", None)
                       or type(ent).__name__ for ent in chain)

    def world_pos(self):
        """My real world position, parents included."""
        return [float(c) for c in self.pos]

    def child_world(self, local):
        """A child at `local` relative to me, in world."""
        n = len(self.pos)
        local = list(local) + [0.0] * (n - len(local))
        return [float(c) + float(o or 0.0) for c, o in zip(self.pos, local)]

    def child_local(self, world):
        """Inverse of `child_world`: a world point next to me."""
        n = len(self.pos)
        world = list(world) + [0.0] * (n - len(world))
        return [float(w) - float(c) for w, c in zip(world, self.pos)]

    def push_local(self):
        """Record `pos` in my parent's frame after a move."""
        if self.parent is None:
            self.local_pos = [float(c) for c in self.pos]
        else:
            self.local_pos = list(self.parent.child_local(self.pos))[:]
        return self.local_pos

    def follow_parent(self):
        """Put me where my parent is, keeping the offset."""
        p = self.parent
        if p is None:
            return self
        self.pos = p.child_world(self.local_pos)
        return self

    def add_child(self, obj, keep_place=False):
        """File an object under me; it moves with me."""
        if obj is self or obj.is_child_of(self):
            raise ValueError("an object cannot be a node of its own branch")
        if obj.parent is self:
            return obj
        if obj.parent is not None and obj in obj.parent.children:
            obj.parent.children.remove(obj)
        obj.parent = self
        self.children.append(obj)
        if keep_place:
            obj.push_local()
        else:
            obj.local_pos = [float(c) for c in obj.pos]
            obj.follow_parent()
        return obj

    def remove_child(self, obj):
        """Detach a node, returning it to the scene."""
        if obj in self.children:
            self.children.remove(obj)
        if obj.parent is self:
            obj.parent = None
            obj.push_local()
        return obj

    def set_parent(self, parent):
        """Move my branch under another object, or the scene."""
        if parent is not None and (parent is self or parent.is_child_of(self)):
            raise ValueError("an object cannot be a node of its own branch")
        world = [float(c) for c in self.pos]
        if self.parent is not None:
            self.parent.remove_child(self)
        if parent is None:
            self.pos = world
            self.push_local()
            return self
        self.local_pos = world
        parent.add_child(self)
        for child in self.descendants():
            child.follow_parent()
        return self

    # -- tree names, as Godot spells them --------------------------------
    def get_parent(self):
        """Who I sit on, or None at the top."""
        return self.parent

    def get_children(self):
        """My nodes, in the order they were placed."""
        return list(self.children)

    def get_child(self, index):
        """The node at `index`, or None past the end."""
        try:
            return self.children[int(index)]
        except (IndexError, TypeError, ValueError):
            return None

    def get_child_count(self):
        """How many nodes I hold."""
        return len(self.children)

    def get_tree(self):
        """The scene holding me; every node lives in one tree."""
        return self.scene

    def is_inside_tree(self):
        """Am I live in a scene right now?"""
        return bool(self.alive) and \
            any(o is self for o in self.scene.objects)

    def find_child(self, name):
        """My direct node that goes by that name, or None."""
        for child in self.children:
            if answers_to(child, name):
                return child
        return None

    def find_children(self, name):
        """Every direct child that goes by that name:
        its document key, tag or class."""
        return [child for child in self.children
                if answers_to(child, name)]

    def get_node(self, path):
        """The node a branch names below me: `Flame#0/Spark#0`.
        `.` is me, `..` my parent, `/` the whole scene."""
        text = str(path or "").strip().replace("\\", "/")
        if text.startswith("/"):
            return self.scene.get_node(text[1:])
        node = self
        parts = [p for p in text.split("/") if p and p != "."]
        while parts and parts[0] == "..":
            parts.pop(0)
            node = node.parent if node.parent is not None else node
        if not parts:
            return node
        return node_from(node.children, parts)

    # -- the branch, as a script reads it ---------------------------------
    def node(self, name):
        """A node under me, by its document id, tag or class name.
        A name with a `/` walks deeper: `self.node("Flame/Spark")`."""
        text = str(name or "").strip()
        if not text:
            return None
        if "/" in text or "\\" in text:
            return self.get_node(text)
        return self.find_child(text)

    def nodes(self, name=None):
        """My direct nodes, or only the ones answering to `name`."""
        if name is None:
            return list(self.children)
        return self.find_children(name)

    def branch_line(self):
        """One line naming me: my class and the id my document gave."""
        leaf = str(self.placed_id or "").rsplit("/", 1)[-1] or \
            str(self.doc_key or "").rsplit("/", 1)[-1]
        kind = type(self).__name__
        return f"{kind} {leaf}" if leaf else kind

    def branch(self, indent=""):
        """My tree as words: me first, my nodes filed under me."""
        lines = [f"{indent}{self.branch_line()}"]
        for child in self.children:
            if child is self or not getattr(child, "alive", True):
                continue
            lines.append(child.branch(indent + "  "))
        return "\n".join(lines)

    # -- lifetime, as Godot spells it ----------------------------------------
    def queue_free(self):
        """Leave this frame, not now; safe while looping children."""
        self.scene.queue_free(self)
        return self

    def free(self):
        """Leave right now: the Godot name for `despawn()`."""
        return self.despawn()

    @property
    def is_clone(self):
        """True when this instance was made by clone()."""
        return self.clone_of is not None

    @property
    def is_original(self):
        """True when this object was not cloned."""
        return self.clone_of is None

    @property
    def clone_depth(self):
        """Clone hops to the original; 0 means none."""
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
        """Ancestors from root to my source, oldest first."""
        chain = []
        ent = self.clone_of
        while ent is not None and ent not in chain:
            chain.append(ent)
            ent = ent.clone_of
        chain.reverse()
        return tuple(chain)

    # -- spawning / cloning ----------------------------------------------
    def _nudged(self, offset):
        """My position plus a same-length offset (missing parts are 0)."""
        return [c + (o or 0.0) for c, o in zip(self.pos, offset)]

    def spawn(self, obj, pos=None, offset=None, tag=None, **kw):
        """Spawn another object as my child, through the scene API."""
        if pos is None:
            pos = self._nudged(offset or (0.0,) * len(self.pos))
        return self.scene.spawn(obj, pos, parent=self, tag=tag, **kw)

    def clone_kwargs(self):
        """Constructor arguments a clone inherits (see clone_attrs)."""
        return {k: getattr(self, k) for k in self.clone_attrs
                if hasattr(self, k)}

    def clone_extra(self):
        """Type-specific constructor arguments clone() always passes"""
        return {}

    def clone(self, pos=None, tag=None, **overrides):
        """Build a copy of me, kept in the scene."""
        if pos is None:
            pos = self._nudged(self.clone_gap)
        kw = self.clone_kwargs()
        kw.update(self.clone_extra())
        kw.update(overrides)
        # a faded prop's copies are stamped faded, not corrected
        look = dict(kw.pop("look", None) or {})
        if getattr(self, "opacity", 1.0) != 1.0:
            look.setdefault("opacity", self.opacity)
        if getattr(self, "shader", None):
            # a copy wears the look its original was handed
            look.setdefault("shader", self.shader)
        return self.scene.spawn(type(self), pos, clone_of=self, tag=tag,
                                look=look, **kw)

    def despawn(self):
        """Remove me (and my children/clones) from the scene."""
        self.scene.despawn(self)
        return self

    # -- cameras ------------------------------------------------------------
    def give_camera(self, name=None, follow=True, offset=None, damping=0.0,
                    active=True, **kw):
        """Build my own camera and register it on the scene."""
        cam = self.scene.add_camera(name=name, **kw)
        return self.adopt_camera(cam, follow=follow, offset=offset,
                                 damping=damping, active=active)

    def use_camera(self, cam, follow=True, offset=None, damping=0.0,
                   active=True):
        """Drive an existing camera of the scene (name or object)."""
        if isinstance(cam, str):
            found = self.scene.cameras.get(cam)
            if found is None:
                raise KeyError(f"scene has no camera '{cam}'")
            cam = found
        return self.adopt_camera(cam, follow=follow, offset=offset,
                                 damping=damping, active=active)

    def adopt_camera(self, cam, follow=True, offset=None, damping=0.0,
                     active=True):
        """Common half of give_camera()/use_camera()."""
        self.look_camera = cam
        cam.owner = self
        if getattr(cam, "name", None) not in self.scene.cameras:
            self.scene.add_camera(cam)
        if follow and hasattr(cam, "set_follow"):
            off = tuple(offset or (0.0,) * len(self.pos))
            cam.set_follow(self, offset=off, damping=damping)
        if active:
            self.scene.set_active_camera(cam)
        return cam

    # -- shared helpers ---------------------------------------------------
    def set_shader(self, name):
        """Wear a project shader; None clears the look."""
        if name is None:
            self.shader = None
            self.shader_pas = None
            return self
        pas = self.renderer.shader_pass(name)
        if pas is None:
            return self
        if pas.mode == shadermod.POST_MODE:
            shadermod.warn_once(f"{type(self).__name__}: {pas.name} washes a "
                                "whole frame, so an object needs a uv or a "
                                "texture shader")
            return self
        self.shader = pas.name
        self.shader_pas = pas
        return self

    def _look(self, shader=None):
        """The shader I wear, for this draw."""
        return self.shader_pas if shader is None \
            else self.renderer.shader_pass(shader)

    def _wear(self, texture, shader=None):
        """(sheet, look) for one of my meshes."""
        pas = self._look(shader)
        if pas is None:
            return texture, None
        if pas.mode == "texture":
            return self.renderer.shaded_texture(texture, pas), None
        if pas.mode == "uv":
            return texture, pas
        return texture, None

    def dynamic(self, data, texture="white", blend="alpha", shader=None,
                **kw):
        """A mesh I own; dispose() releases it."""
        kw.setdefault("opacity", self.opacity)
        kw.setdefault("uv", _uv_look(self))
        sheet, look = self._wear(texture, shader)
        mesh = self.scene.renderer.new_dynamic(data, texture=sheet,
                                               blend=blend, shader=look,
                                               **kw)
        self.meshes.append(mesh)
        return mesh

    def set_opacity(self, value):
        """Ghost me to a new solidity, 0..1."""
        self.opacity = self.scene.renderer.opacity_of(value)
        for mesh in self.meshes:
            if hasattr(mesh, "set_opacity"):
                mesh.set_opacity(self.opacity)
        for owned in self.objects:
            fade = getattr(owned, "set_opacity", None)
            if callable(fade):
                fade(self.opacity)
        refile = getattr(self.scene, "set_owner_opacity", None)
        if callable(refile):
            refile(self, self.opacity)
        return self

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

    @property
    def hud(self):
        """The scene's HUD helpers: `self.hud.text(...)` from any object."""
        return self.scene.hud

    # -- trigger bus ------------------------------------------------------
    def broadcast(self, name, value=None):
        """Say a trigger fired, on the scene that holds me."""
        return self.scene.broadcast(name, value)

    def listen(self, name, owner=None, method="on_trigger"):
        """Hear one trigger on another object, or on me."""
        return self.scene.listen(name, owner if owner is not None else self,
                                 method)

    def unlisten(self, name, owner=None):
        """Drop one trigger's listener, or all of them."""
        return self.scene.unlisten(name, owner)

    # -- signals ------------------------------------------------------------
    def connect(self, name, fn):
        """Hear a signal: `connect("door", self.on_door)`."""
        return self.scene.connect(name, fn)

    def disconnect(self, name, fn=None):
        """Forget one listener of a signal, or all of them."""
        return self.scene.disconnect(name, fn)

    def emit(self, name, value=None):
        """Fire a signal: the Godot name for `broadcast()`."""
        return self.broadcast(name, value)

    # -- timers -----------------------------------------------------------
    def after(self, delay, func, *args, **kwargs):
        return self.timers.after(delay, func, *args, **kwargs)

    def every(self, delay, func, *args, **kwargs):
        return self.timers.every(delay, func, *args, **kwargs)

    # -- lifecycle ----------------------------------------------------------
    def build(self):
        pass

    def update(self, dt):
        self.t += dt
        self.timers.update(dt)

    def dispose(self):
        """Release everything this object owns."""
        for mesh in self.meshes:
            mesh.dispose()
        self.meshes.clear()
        for obj in self.objects:
            obj.dispose()
        self.objects.clear()
        remove = getattr(self.scene, "remove_light", None)
        for light in self.lights:
            if remove is not None:
                remove(light)
            elif light in self.scene.lights:
                self.scene.lights.remove(light)
        self.lights.clear()
        self.timers.clear()

    def set(self, pos=None):
        if pos is not None:
            self.pos = [float(c) for c in pos]
            self.push_local()
            self.propagate()
        return self

    def propagate(self):
        """After a world move, place my nodes."""
        for child in self.descendants():
            child.follow_parent()
        return self

    def __getattr__(self, name):
        """A direct node by its document id: `self.block.half = ...`.
        Python only asks me this when nothing else answers, so a real
        attribute, method or property always wins."""
        if name.startswith("_"):
            raise AttributeError(name)
        for child in self.__dict__.get("children") or ():
            if answers_to(child, name):
                return child
        raise AttributeError(f"{type(self).__name__} has no attribute "
                             f"'{name}', and no node of that name")

    def __repr__(self):
        where = " ".join(f"{c:g}" for c in self.pos)
        origin = f" clone of {type(self.clone_of).__name__}" \
            if self.is_clone else ""
        under = f" of {type(self.parent).__name__}" \
            if self.parent is not None else ""
        return f"<{type(self).__name__} {self.tag} ({where}){origin}{under}>"


class Object3D(GameObject):
    """A placeable prop inside a 3D scene (the former `Entity`)."""

    kind = "3d"
    name = "object3d"
    clone_gap = (1.2, 0.0, 0.0)
    doc_knobs = ("opacity", "shader") + UV_KNOBS
    uv_tile = 0.0               # metres per texture repeat; 0 = the sheet
    uv_scale = (1.0, 1.0)
    uv_offset = (0.0, 0.0)
    uv_spin = 0.0

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 tag=None, opacity=1.0):
        super().__init__(scene, pos=pos, tag=tag)
        self.yaw = float(yaw)
        self.scale = float(scale)
        self.opacity = float(opacity)
        # the same transform a parent places me by
        self.local_yaw = float(yaw)
        self.local_scale = float(scale)
        self.camera = None          # rig options, set by set_camera()

    # -- hierarchy -------------------------------------------------------
    def _parent_turn(self):
        """(yaw, scale) of my parent's frame, or None."""
        p = self.parent
        if p is None:
            return None
        return (float(getattr(p, "yaw", 0.0) or 0.0),
                float(getattr(p, "scale", 1.0) or 1.0))

    def child_world(self, local):
        """A place next to me, turned to my facing."""
        local = list(local) + [0.0] * (3 - len(local))
        s, c = math.sin(self.yaw), math.cos(self.yaw)
        k = self.scale
        return [self.pos[0] + k * (local[0] * c + local[2] * s),
                self.pos[1] + k * local[1],
                self.pos[2] + k * (local[2] * c - local[0] * s)]

    def child_local(self, world):
        """A world point in my own axes, inverse turn."""
        world = list(world) + [0.0] * (3 - len(world))
        s, c = math.sin(self.yaw), math.cos(self.yaw)
        k = self.scale or 1.0
        wx = world[0] - self.pos[0]
        wy = world[1] - self.pos[1]
        wz = world[2] - self.pos[2]
        return [(wx * c - wz * s) / k, wy / k, (wx * s + wz * c) / k]

    def follow_parent(self):
        p = self._parent_turn()
        if p is None:
            return self
        super().follow_parent()
        self.yaw = p[0] + float(self.local_yaw)
        self.scale = p[1] * float(self.local_scale)
        return self

    def push_local(self):
        super().push_local()
        p = self._parent_turn()
        if p is None:
            self.local_yaw = float(self.yaw)
            self.local_scale = float(self.scale)
        else:
            self.local_yaw = float(self.yaw) - p[0]
            self.local_scale = (float(self.scale) / p[1]) if p[1] else \
                float(self.scale)
        return self.local_pos

    # -- geometry ----------------------------------------------------------
    def uv_pin(self):
        """Where the metre sheet is pinned, and my facing."""
        return meshes.frame_pin(self.pos, self.yaw)

    def uv_look(self):
        """The uv fit my geometry draws with; None when untouched."""
        tile = float(self.uv_tile or 0.0)
        scale = _pair(self.uv_scale, 1.0)
        offset = _pair(self.uv_offset, 0.0)
        spin = float(self.uv_spin or 0.0)
        if not tile and scale == (1.0, 1.0) and offset == (0.0, 0.0) \
                and not spin:
            return None
        return (tile, scale, offset, spin)

    def add(self, data, texture="white", blend="opaque", opacity=None,
            shader=None):
        # `owner=self` keeps this geometry replaceable for live drags
        sheet, look = self._wear(texture, shader)
        if look is not None and not self.scene.live:
            # a uv program runs per vertex: no shared batch
            self.dynamic(data, texture=texture, blend=blend, opacity=opacity,
                         shader=shader)
            return
        self.scene.add(data, texture=sheet, blend=blend, owner=self,
                       opacity=opacity, shader=look, uv=self.uv_look())

    def dynamic(self, data, texture="white", blend="add",
                view_model=False, on_top=False, opacity=None, shader=None):
        """Mesh reshaped every frame. view_model=True makes it a"""
        if opacity is None:
            opacity = self.opacity
        sheet, look = self._wear(texture, shader)
        mesh = self.scene.renderer.new_dynamic(data, texture=sheet,
                                               blend=blend,
                                               view_model=view_model,
                                               on_top=on_top,
                                               opacity=opacity,
                                               shader=look,
                                               uv=self.uv_look(),
                                               frame=self.uv_pin)
        self.meshes.append(mesh)
        return mesh

    def place_model(self, name, pos=None, yaw=None, scale=None, tint=None,
                    opacity=None, shader=None):
        return self.scene.place_model(
            name,
            self.pos if pos is None else pos,
            self.yaw if yaw is None else yaw,
            self.scale if scale is None else scale,
            tint, self.opacity if opacity is None else opacity,
            shader=self._look(shader), uv=self.uv_look())

    def model_object(self, name, pos=None, yaw=None, scale=None, tint=None,
                     texture=None, blend="opaque", opacity=None,
                     shader=None):
        obj = self.scene.model_object(
            name,
            self.pos if pos is None else pos,
            self.yaw if yaw is None else yaw,
            self.scale if scale is None else scale,
            tint, texture, blend,
            self.opacity if opacity is None else opacity,
            shader=self._look(shader), uv=self.uv_look())
        self.objects.append(obj)
        return obj

    def light(self, pos=None, color=(1.0, 0.62, 0.24), shape=None,
              follow=False, offset=None, **kw):
        """A light in the scene that `dispose()` removes again."""
        light = self.scene.add_light(self.pos if pos is None else pos,
                                     color=color, shape=shape,
                                     follow=self if follow else None,
                                     offset=offset, **kw)
        self.lights.append(light)
        return light

    def ground(self, x=None, z=None):
        return self.scene.ground_height(
            self.pos[0] if x is None else x,
            self.pos[2] if z is None else z)

    # -- cloning ------------------------------------------------------------
    def clone_extra(self):
        return {"yaw": self.yaw, "scale": self.scale}

    def set(self, pos=None, yaw=None, scale=None, opacity=None):
        if yaw is not None:
            self.yaw = float(yaw)
        if scale is not None:
            self.scale = float(scale)
        super().set(pos=pos)
        if opacity is not None:
            self.set_opacity(opacity)
        if yaw is not None or scale is not None:
            self.push_local()
            self.propagate()
        return self

    # -- camera rig ---------------------------------------------------------
    def set_camera(self, height=1.7, fov=72.0, near=None, far=None,
                   roll=None, **opts):
        """Ride this object: the eye sits `height` above its ground."""
        self.camera = {"height": height, "fov": fov}
        self.camera.update(opts)
        self.scene.camera_rig = self
        s = self.scene
        s.fov = fov
        if near is not None:
            s.near = float(near)
        if far is not None:
            s.far = float(far)
        if roll is not None:
            s.roll = float(roll)
        return self.camera

    def look(self, yaw, pitch):
        self.yaw, self.pitch = yaw, pitch

    def move(self, wish, run, dt):
        """wish: (x, z) input, sliding along the ground."""
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


class Object2D(GameObject):
    """A sprite quad in a 2D scene."""

    kind = "2d"
    name = "sprite"
    clone_gap = (32.0, 0.0)
    clone_attrs = ("size", "texture", "grid", "anchor")
    doc_knobs = ("opacity", "shader")

    def __init__(self, scene, pos=(0.0, 0.0), size=(64.0, 64.0),
                 texture="white", col=(1.0, 1.0, 1.0), rot=0.0,
                 anchor=(0.5, 0.5), grid=(1, 1), frame=0, uv=None,
                 flip=False, tag=None, blend="alpha", opacity=1.0):
        super().__init__(scene, pos=pos, tag=tag)
        self.opacity = float(opacity)
        self.size = (float(size[0]), float(size[1]))
        self.texture = colors.key(texture)
        self.col = colors.rgb(col, (1.0, 1.0, 1.0))
        self.rot = float(rot)              # radians, about the anchor
        self.anchor = (float(anchor[0]), float(anchor[1]))
        self.grid = (int(grid[0]), int(grid[1]))
        self.frame = int(frame)
        self.uv = None if uv is None else tuple(float(u) for u in uv)
        self.flip = bool(flip)
        self.blend = blend
        self.dirty = False
        self.mesh = None
        # animation: `frames` cycle at `anim_fps`
        self.anim_frames = None
        self.anim_fps = 0.0
        self._anim_t = 0.0
        # my spin as my parent places me by
        self.local_rot = float(rot)

    # -- hierarchy -------------------------------------------------------
    def _parent_turn(self):
        """The spin of my parent's frame, or None."""
        p = self.parent
        if p is None:
            return None
        return (float(getattr(p, "rot", 0.0) or 0.0),)

    def child_world(self, local):
        """A place next to me, turned like my sprite."""
        local = list(local) + [0.0] * (2 - len(local))
        c, s = math.cos(self.rot), math.sin(self.rot)
        return [self.pos[0] + local[0] * c - local[1] * s,
                self.pos[1] + local[0] * s + local[1] * c]

    def child_local(self, world):
        """A world point in my own turned axes."""
        world = list(world) + [0.0] * (2 - len(world))
        c, s = math.cos(self.rot), math.sin(self.rot)
        wx = world[0] - self.pos[0]
        wy = world[1] - self.pos[1]
        return [wx * c + wy * s, -wx * s + wy * c]

    def follow_parent(self):
        turn = self._parent_turn()
        if turn is None:
            return self
        super().follow_parent()
        self.rot = turn[0] + float(self.local_rot)
        self.dirty = True
        return self

    def push_local(self):
        super().push_local()
        turn = self._parent_turn()
        self.local_rot = float(self.rot) if turn is None \
            else float(self.rot) - turn[0]
        return self.local_pos

    # -- quad ----------------------------------------------------------------
    def cell_uv(self):
        """The (u0, v0, u1, v1) window currently shown."""
        if self.uv is not None:
            return self.uv
        cols, rows = self.grid
        col = self.frame % cols
        row = (self.frame // cols) % max(rows, 1)
        u0, v0, u1, v1 = meshes.sprite_uv(col, row, cols, rows)
        if self.flip:
            u0, u1 = u1, u0
        return (u0, v0, u1, v1)

    def quad(self):
        return meshes.quad2d(self.pos, self.size, col=self.col,
                             uv=self.cell_uv(), rot=self.rot,
                             anchor=self.anchor)

    def build(self):
        self.mesh = self.dynamic(self.quad(), texture=self.texture,
                                 blend=self.blend)
        self.dirty = False

    def _sync(self):
        if self.dirty and self.mesh is not None:
            sheet, _look = self._wear(self.texture)
            if self.mesh.texture != sheet:
                # a sprite can change sheet or go flat mid-game
                self.mesh.texture = sheet
            self.mesh.update(self.quad())
            self.dirty = False

    # -- mutating ------------------------------------------------------------
    def set(self, pos=None, size=None, col=None, rot=None, texture=None,
            anchor=None, uv=None, flip=None, opacity=None):
        changed = False
        moved = False
        if pos is not None:
            self.pos = [float(c) for c in pos]
            changed = moved = True
        if size is not None:
            self.size = (float(size[0]), float(size[1]))
            changed = True
        if col is not None:
            self.col = colors.rgb(col, self.col)
            changed = True
        if rot is not None:
            self.rot = float(rot)
            changed = True
        if texture is not None and colors.key(texture) != self.texture:
            self.texture = colors.key(texture)
            changed = True
        if anchor is not None:
            self.anchor = (float(anchor[0]), float(anchor[1]))
            changed = True
        if uv is not None:
            self.uv = tuple(float(u) for u in uv)
            changed = True
        if flip is not None:
            self.flip = bool(flip)
            changed = True
        self.dirty = self.dirty or changed
        if moved:
            self.push_local()
            self.propagate()
        if opacity is not None:
            self.set_opacity(opacity)
        return self

    def moved(self):
        """Glue my branch on after a direct `pos` change."""
        self.dirty = True
        self.push_local()
        self.propagate()
        return self

    def move(self, dx=0.0, dy=0.0):
        self.pos[0] += float(dx)
        self.pos[1] += float(dy)
        return self.moved()

    def move_to(self, x=None, y=None):
        if x is not None:
            self.pos[0] = float(x)
        if y is not None:
            self.pos[1] = float(y)
        return self.moved()

    def set_frame(self, index):
        self.frame = int(index)
        self.dirty = True
        return self

    def animate(self, fps=8.0, frames=None):
        """Cycle sprite-sheet cells: `frames` are cell indices (default:"""
        self.anim_fps = float(fps)
        cols, rows = self.grid
        self.anim_frames = list(frames) if frames is not None \
            else list(range(cols * rows))
        self._anim_t = 0.0
        if self.anim_fps <= 0.0 or not self.anim_frames:
            self.anim_fps = 0.0
        return self

    # -- lighting -------------------------------------------------------------
    def light(self, pos=None, color="torch", shape="radial", radius=None,
              follow=False, offset=None, **kw):
        """A 2D light that `dispose()` removes again."""
        if radius is None:
            radius = round(math.hypot(self.size[0], self.size[1]))
        light = self.scene.add_light(self.pos if pos is None else pos,
                                     color=color, shape=shape, radius=radius,
                                     follow=self if follow else None,
                                     offset=offset, **kw)
        self.lights.append(light)
        return light

    # -- picking -------------------------------------------------------------
    def rect(self):
        """The axis-aligned box of the unrotated quad, world pixels."""
        w, h = self.size
        ax, ay = self.anchor
        return (self.pos[0] - ax * w, self.pos[1] - ay * h, w, h)

    def contains(self, point):
        x, y, w, h = self.rect()
        return x <= point[0] <= x + w and y <= point[1] <= y + h

    # -- frame ----------------------------------------------------------------
    def update(self, dt):
        super().update(dt)
        if self.anim_fps > 0.0 and self.anim_frames:
            self._anim_t += dt
            step = 1.0 / self.anim_fps
            while self._anim_t >= step:
                self._anim_t -= step
                idx = self.anim_frames.index(
                    self.frame, 0) if self.frame in self.anim_frames else -1
                self.frame = self.anim_frames[(idx + 1) %
                                              len(self.anim_frames)]
                self.dirty = True
        self._sync()

    def clone_extra(self):
        return {"rot": self.rot, "uv": self.uv, "flip": self.flip,
                "col": self.col, "frame": self.frame}


class UIObject(Object2D):
    """A clickable UI panel: one flat quad."""

    kind = "ui"
    name = "widget"
    clone_gap = (0.0, 40.0)
    clone_attrs = ("size", "text", "color", "font_size", "anchor")

    _tex_seq = 0

    def __init__(self, scene, pos=(0.0, 0.0), size=(160.0, 40.0),
                 text="", color=(0.16, 0.42, 0.78), hover_color=None,
                 press_color=None, text_color=(1.0, 1.0, 1.0),
                 font_size=18, font_name="tahoma", texture="white",
                 anchor=(0.5, 0.5), enabled=True, action=None, tag=None,
                 blend="hud", **kw):
        base = colors.rgb(color, (0.16, 0.42, 0.78))
        super().__init__(scene, pos=pos, size=size, texture=texture,
                         col=base, anchor=anchor, tag=tag, blend=blend,
                         **kw)
        self.color = base
        self.hover_color = None if hover_color is None \
            else colors.rgb(hover_color)
        self.press_color = None if press_color is None \
            else colors.rgb(press_color)
        self.text_color = colors.rgb(text_color, (1.0, 1.0, 1.0))
        self.text = str(text or "")
        self.font_size = int(font_size)
        self.font_name = font_name
        self.enabled = bool(enabled)
        self.action = action
        self.hovered = False
        self.pressed = False
        self._text_mesh = None
        self._text_key = None
        self._text_size = (0.0, 0.0)

    # -- look -----------------------------------------------------------------
    def build(self):
        super().build()
        if self.text:
            self._rebuild_text()

    def dispose(self):
        if self._text_mesh is not None:
            self._text_mesh.dispose()
            self._text_mesh = None
        self._release_text()
        super().dispose()

    def _release_text(self):
        if self._text_key is not None:
            tex = self.renderer.textures.pop(self._text_key, None)
            if tex is not None:
                tex.release()
            self._text_key = None

    def _text_texture(self):
        """Render self.text to an RGBA texture; returns (key, w_px, h_px)."""
        UIObject._tex_seq += 1
        key = f"ui_text_{id(self)}_{UIObject._tex_seq}"
        font = ui.load_font(self.font_name, self.font_size)
        label = font.render(self.text, True,
                            tuple(round(c * 255) for c in self.text_color))
        w, h = label.get_size()
        canvas = pygame.Surface((max(w, 1), max(h, 1)), pygame.SRCALPHA)
        # fill with zero alpha so RGB survives the fade
        canvas.fill(tuple(round(c * 255) for c in self.text_color) + (0,))
        canvas.blit(label, (0, 0))
        rgb = np.transpose(pygame.surfarray.array3d(canvas), (1, 0, 2))
        alpha = np.transpose(pygame.surfarray.array_alpha(canvas))
        arr = np.dstack((rgb, alpha)).astype(np.uint8)
        self.renderer.texture(key, arr, rgba=True, repeat=False,
                              filter="nearest", mipmaps=False)
        return key, float(w), float(h)

    def _text_quad(self):
        """The label quad, welded to the panel's anchor and rotation."""
        return meshes.quad2d(self.pos, self._text_size,
                             col=(1.0, 1.0, 1.0), rot=self.rot,
                             anchor=self.anchor, uv=(0.0, 0.0, 1.0, 1.0))

    def _rebuild_text(self):
        if not self.text:
            if self._text_mesh is not None:
                self._text_mesh.dispose()
                self._text_mesh = None
            self._release_text()
            return
        if self._text_key is not None:
            self._release_text()
        key, w, h = self._text_texture()
        self._text_key = key
        self._text_size = (w, h)
        if self._text_mesh is None:
            self._text_mesh = self.dynamic(self._text_quad(), texture=key,
                                           blend=self.blend)
        else:
            # re-point the mesh; a released key draws white
            self._text_mesh.texture = key
            self._text_mesh.update(self._text_quad())

    def set_text(self, text):
        self.text = str(text or "")
        self._rebuild_text()
        return self

    def set(self, pos=None, size=None, col=None, rot=None, texture=None,
            anchor=None, uv=None, flip=None, text=None, color=None,
            enabled=None, opacity=None):
        if color is not None:
            self.color = colors.rgb(color, self.color)
            if not (self.hovered or self.pressed):
                self.col = self.color
                self.dirty = True
        super().set(pos=pos, size=size, col=col if color is None else None,
                    rot=rot, texture=texture, anchor=anchor, uv=uv,
                    flip=flip, opacity=opacity)
        if text is not None:
            self.set_text(text)
        if enabled is not None:
            self.enabled = bool(enabled)
        return self

    def clone_extra(self):
        """The 2D defaults minus `col`: `color` (in clone_attrs) already"""
        kw = super().clone_extra()
        kw.pop("col", None)
        return kw

    def _state_color(self):
        if self.pressed and self.press_color is not None:
            return self.press_color
        if self.hovered and self.hover_color is not None:
            return self.hover_color
        return self.color

    def _apply_state(self):
        col = self._state_color()
        if col != self.col:
            self.col = col
            self.dirty = True
            self._sync()

    # -- interaction ----------------------------------------------------------
    def click(self):
        """Fire the click callbacks (also fine to call from code)."""
        if self.action is not None:
            self.action()
        self.on_click()
        return self

    def on_click(self):
        pass

    def on_hover(self):
        pass

    def on_leave(self):
        pass

    def handle_event(self, e, world_pos):
        """Called by the scene with a mouse event."""
        inside = self.enabled and self.contains(world_pos)
        if e.type == pygame.MOUSEMOTION:
            if inside and not self.hovered:
                self.hovered = True
                self._apply_state()
                self.on_hover()
            elif self.hovered and not inside:
                self.hovered = False
                self.pressed = False
                self._apply_state()
                self.on_leave()
            return False
        if not inside:
            if self.pressed:
                self.pressed = False
                self._apply_state()
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.pressed = True
            self._apply_state()
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            was = self.pressed
            self.pressed = False
            self._apply_state()
            if was:
                self.click()
            return True
        return False

    def update(self, dt):
        moved = self.dirty          # before _sync() clears it
        super().update(dt)
        if moved and self._text_mesh is not None:
            # the panel moved: weld the picture without re-rendering
            self._text_mesh.update(self._text_quad())


class _EntityHitbox:
    """A collider over an entity's live transform and hitbox."""

    solid = False
    group = "entity"

    def __init__(self, owner):
        self.owner = owner

    @property
    def alive(self):
        return self.owner.alive

    def box(self):
        entity = self.owner
        if entity.hitbox_shape == "sphere":
            half = (entity.hitbox_radius,) * 3
        elif entity.hitbox_shape == "capsule":
            half = (entity.hitbox_radius, entity.hitbox_height / 2.0,
                    entity.hitbox_radius)
        else:
            half = entity.hitbox_half
        scale = abs(float(entity.scale))
        return tuple(entity.pos), tuple(float(value) * scale for value in half)

    def rect(self):
        entity = self.owner
        if entity.hitbox_shape == "circle":
            width = height = float(entity.hitbox_radius) * 2.0
        else:
            width, height = entity.hitbox_size
        return (entity.pos[0] - width / 2.0,
                entity.pos[1] - height / 2.0,
                width, height)


class EntityBehaviour:
    """Health, AI and attack: what 3D and 2D entities share.
    Each world answers `_plane()`, `_moved()` and `_hitbox_shape()`."""

    # Health
    health = 100.0
    max_health = 100.0
    invulnerable_time = 0.0

    ai_type = "none"          # "none", "follow", "patrol", "wander", "aggro"
    ai_config = {}
    ai_state = "idle"
    ai_target = None
    ai_timer = 0.0

    # Behaviour
    team = "neutral"          # "player", "enemy", "neutral", "friendly"
    attack_damage = 10.0
    attack_cooldown = 1.0
    attack_timer = 0.0

    # The same ideas, in each world's own units
    hitbox_shapes = ()
    ai_arrive = 0.5
    wander_range = (2.0, 8.0)
    run_ratio = 1.5               # chase speed when only one is set

    # -- what each world answers ------------------------------------------
    def _plane(self):
        """The two axes of `pos` I walk on."""
        return (0, 1)

    def _facing(self, dx, dy):
        """Turn to face a move along my plane."""

    def _moved(self):
        """Announce a direct change of `pos`."""

    def _flat(self):
        """True when nothing below me turns or rises with me."""
        return True

    def _hitbox_shape(self, shape):
        """The shape my collider takes for a name."""
        return str(shape)

    # -- setup ------------------------------------------------------------
    def _own_state(self):
        """Hand me my own copy of anything my class holds:
        a shared `ai_config` would let two enemies steer each other."""
        for name in ("ai_config", "hitbox_half", "hitbox_size",
                     "move_speed"):
            value = getattr(self, name, None)
            if isinstance(value, dict):
                setattr(self, name, dict(value))
            elif isinstance(value, (list, tuple)):
                setattr(self, name, type(value)(value))

    def _entity_init(self):
        """The `__init__` half both worlds share, run after theirs."""
        self._own_state()
        self.health = float(self.max_health)
        self._hitbox = None
        self._setup_hitbox()

    def _setup_hitbox(self):
        """File my collider when my shape is a real one."""
        if self.hitbox_shape in self.hitbox_shapes:
            self._hitbox = _EntityHitbox(self)
            self.scene.add_collider(self._hitbox)

    def _rebuild_hitbox(self):
        """Move my collider to a new shape."""
        if getattr(self, "_hitbox", None) is not None:
            self.scene.remove_collider(self._hitbox)
            self._hitbox = None
        self._setup_hitbox()
        return self

    def dispose(self):
        if getattr(self, "_hitbox", None) is not None:
            self.scene.remove_collider(self._hitbox)
            self._hitbox = None
        return super().dispose()

    # -- health -----------------------------------------------------------
    def take_damage(self, amount, source=None):
        """Apply damage to this entity."""
        if self.invulnerable_time > 0 or self.health <= 0:
            return False
        self.health = max(0.0, self.health - float(amount))
        self.invulnerable_time = 0.2  # brief invulnerability
        if self.health <= 0:
            self.die(source)
        else:
            self.on_hit(source)
        return True

    def heal(self, amount):
        """Heal this entity."""
        self.health = min(self.max_health, self.health + float(amount))
        return self

    def kill(self, source=None):
        """Out of health at once: death runs, then I go."""
        if self.health <= 0.0:
            return self
        self.health = 0.0
        self.die(source)
        return self

    def die(self, source=None):
        """Called when health reaches 0."""
        self.on_death(source)
        self.alive = False
        self.dispose()

    def on_hit(self, source):
        """Hook called when damaged but not killed."""
        flash = getattr(self, "flash_hit", None)
        if callable(flash):
            flash()                 # a body that can flash it red, briefly

    def on_death(self, source):
        """Hook called when killed."""

    def is_dead(self):
        """Have I run out of health?"""
        return self.health <= 0

    def distance_to(self, other):
        """How far away another object stands, measured on my plane."""
        ix, iy = self._plane()
        pos = list(getattr(other, "pos", None) or ()) + [0.0, 0.0]
        if self._flat():
            return math.hypot(float(pos[ix]) - self.pos[ix],
                              float(pos[iy]) - self.pos[iy])
        return math.sqrt((float(pos[0]) - self.pos[0]) ** 2 +
                         (float(pos[1]) - self.pos[1]) ** 2 +
                         (float(pos[2]) - self.pos[2]) ** 2)

    # -- one-call setters, what a block lowers to
    def set_health(self, value):
        """Damage I can still take, never past my maximum.
        Zero kills me, as losing my last health does."""
        was = self.health
        self.health = max(0.0, min(float(self.max_health), float(value)))
        if self.health <= 0.0 and was > 0.0:
            self.die()
        return self

    def set_max_health(self, value):
        """My full health; current health is kept or trimmed."""
        self.max_health = max(1.0, float(value))
        self.health = min(self.health, self.max_health)
        return self

    def set_team(self, name):
        """Whose side I am on: `player`, `enemy`, `neutral` or `friendly`."""
        self.team = str(name)
        return self

    def set_ai(self, ai_type, config=None):
        """My behaviour: `none`, `follow`, `patrol` or `wander`.
        `config` carries its `waypoints` or `wander_interval`."""
        self.ai_type = str(ai_type)
        if config is not None:
            self.ai_config = dict(config)
        self.ai_state = "idle"
        self.ai_timer = 0.0
        return self

    def set_ai_target(self, target):
        """Who I follow, chase or attack; nobody until told."""
        self.ai_target = target
        return self

    def set_aggro_range(self, distance, deaggro=None):
        """How far off I notice, and when I lose interest."""
        self.aggro_range = float(distance)
        self.deaggro_range = self.aggro_range * 2.0 if deaggro is None \
            else float(deaggro)
        return self

    def set_attack(self, range=None, damage=None, cooldown=None):
        """My reach, my damage, and seconds between swings."""
        if range is not None:
            self.attack_range = float(range)
        if damage is not None:
            self.attack_damage = float(damage)
        if cooldown is not None:
            self.attack_cooldown = max(0.0, float(cooldown))
        return self

    def set_move_speed(self, walk, run=None):
        """Walk and chase speed; a single number
        runs at `run_ratio` times it."""
        speed = float(walk)
        if isinstance(self.move_speed, (list, tuple)):
            self.move_speed = (speed, speed * self.run_ratio
                               if run is None else float(run))
        else:
            self.move_speed = speed
        return self

    def set_hitbox(self, shape, half=None, radius=None, height=None):
        """My 3D collider: a `box`, `sphere` or `capsule`."""
        self.hitbox_shape = self._hitbox_shape(shape)
        if half is not None:
            self.hitbox_half = tuple(float(c) for c in half)
        if radius is not None:
            self.hitbox_radius = float(radius)
        if height is not None:
            self.hitbox_height = float(height)
        return self._rebuild_hitbox()

    def set_hitbox2d(self, shape, size=None, radius=None):
        """My flat collider: a `rect` (width, height) or a `circle`."""
        self.hitbox_shape = self._hitbox_shape(shape)
        if size is not None:
            self.hitbox_size = tuple(float(c) for c in size)
        if radius is not None:
            self.hitbox_radius = float(radius)
        return self._rebuild_hitbox()

    # -- speeds -----------------------------------------------------------
    def _walk_speed(self):
        """My cruising speed, in the world's units per second."""
        speed = self.move_speed
        if isinstance(speed, (list, tuple)):
            return float(speed[0])
        return float(speed)

    def _run_speed(self):
        """Chase speed: a pair's second number, or a step up."""
        speed = self.move_speed
        if isinstance(speed, (list, tuple)):
            return float(speed[1]) if len(speed) > 1 else float(speed[0])
        return float(speed) * self.run_ratio

    # -- movement ---------------------------------------------------------
    def _delta_to(self, pos):
        """My plane's (dx, dy) toward a world position."""
        ix, iy = self._plane()
        where = list(pos) + [0.0] * (max(ix, iy) + 1)
        return (float(where[ix]) - self.pos[ix],
                float(where[iy]) - self.pos[iy])

    def _step(self, dx, dy, speed, dt):
        """Slide along my plane, turning to face the delta."""
        length = math.hypot(dx, dy)
        if length <= 0.0:
            return False
        ix, iy = self._plane()
        self.pos[ix] += dx / length * speed * dt
        self.pos[iy] += dy / length * speed * dt
        self._facing(dx, dy)
        self._moved()
        return True

    def _scattered(self, angle, distance):
        """A spot `distance` along my plane, turned by `angle`."""
        ix, iy = self._plane()
        return (self.pos[ix] + math.cos(angle) * distance,
                self.pos[iy] + math.sin(angle) * distance)

    def _plane_delta(self, pair):
        """`(dx, dy)` on my plane, from a plane-space pair."""
        ix, iy = self._plane()
        where = list(pair) + [0.0, 0.0]
        return (float(where[0]) - self.pos[ix],
                float(where[1]) - self.pos[iy])

    # -- behaviour --------------------------------------------------------
    def update(self, dt):
        super().update(dt)
        if self.invulnerable_time > 0:
            self.invulnerable_time -= dt
        self._update_ai(dt)
        self._update_attack(dt)

    def _update_ai(self, dt):
        """Step through whatever `ai_type` says I should be doing."""
        if self.ai_type == "none" or self.health <= 0:
            return
        self.ai_timer += dt
        walk = {"follow": self._ai_follow, "patrol": self._ai_patrol,
                "wander": self._ai_wander, "aggro": self._ai_aggro}
        step = walk.get(self.ai_type)
        if step is not None:
            step(dt)

    def _who(self):
        """Who I am after; the player when nobody was named."""
        target = self.ai_target
        if target is None:
            target = getattr(self.scene, "player", None)
            self.ai_target = target
        if target is None or getattr(target, "pos", None) is None:
            return None
        return target

    def _ai_follow(self, dt):
        """Keep within reach of whoever I follow."""
        target = self._who()
        if target is None:
            return
        dx, dy = self._delta_to(target.pos)
        if math.hypot(dx, dy) > self.attack_range:
            self._step(dx, dy, self._walk_speed(), dt)

    def _ai_patrol(self, dt):
        """Walk a list of `waypoints`, one after the other, forever."""
        waypoints = self.ai_config.get("waypoints") or ()
        if not waypoints:
            return
        current = int(self.ai_config.get("current_waypoint", 0)) % \
            len(waypoints)
        dx, dy = self._delta_to(waypoints[current])
        if math.hypot(dx, dy) < self.ai_arrive:
            self.ai_config["current_waypoint"] = (current + 1) % \
                len(waypoints)
        else:
            self._step(dx, dy, self._walk_speed(), dt)

    def _ai_wander(self, dt):
        """Amble to a new nearby spot every few seconds."""
        if self.ai_timer > self.ai_config.get("wander_interval", 3.0):
            self.ai_timer = 0.0
            angle = self.rng.uniform(0, 2 * math.pi)
            distance = self.rng.uniform(*self.wander_range)
            self.ai_config["wander_target"] = self._scattered(angle, distance)
        target = self.ai_config.get("wander_target")
        if not target:
            return
        dx, dy = self._plane_delta(target)
        if math.hypot(dx, dy) < self.ai_arrive:
            self.ai_config["wander_target"] = None
        else:
            self._step(dx, dy, self._walk_speed(), dt)

    def _ai_aggro(self, dt):
        """Chase the player, hitting once within reach."""
        player = getattr(self.scene, "player", None)
        if player is None or getattr(player, "pos", None) is None:
            return
        dx, dy = self._delta_to(player.pos)
        dist = math.hypot(dx, dy)
        if self.ai_state == "idle":
            if dist <= self.aggro_range:
                self.ai_state = "chase"
                self.ai_target = player
        elif self.ai_state == "chase":
            if dist > self.deaggro_range:
                self.ai_state = "idle"
                self.ai_target = None
            elif dist <= self.attack_range:
                self.ai_state = "attack"
            else:
                self._step(dx, dy, self._run_speed(), dt)
        elif self.ai_state == "attack":
            if dist > self.attack_range:
                self.ai_state = "chase"
            else:
                self._try_attack(dt)

    def _update_attack(self, dt):
        """Cool down between swings."""
        if self.attack_timer > 0:
            self.attack_timer -= dt

    def _try_attack(self, dt):
        """One hit per cooldown, however long I stay within reach."""
        if self.attack_timer <= 0:
            self.attack_timer = self.attack_cooldown
            self._perform_attack()

    def _perform_attack(self):
        """Override in subclass to implement actual attack."""
        hit = getattr(self.ai_target, "take_damage", None)
        if callable(hit):
            hit(self.attack_damage, self)


class Entity3D(EntityBehaviour, Object3D):
    """3D entities (NPCs, enemies) with AI, health and hitboxes."""

    kind = "3d"
    name = "entity3d"
    clone_gap = (2.0, 0.0, 0.0)
    clone_attrs = ("health", "max_health", "ai_type", "ai_config",
                   "hitbox_shape", "hitbox_half")
    doc_knobs = ("opacity", "shader", "health", "max_health", "ai_type",
                 "ai_config", "hitbox_shape", "hitbox_half") + UV_KNOBS

    # Hitbox
    hitbox_shape = "box"      # "box", "sphere", "capsule"
    hitbox_shapes = ("box", "sphere", "capsule")
    hitbox_half = (0.5, 1.0, 0.5)  # box, or sphere/capsule radius,
    hitbox_radius = 0.5       # hitbox_height: capsule
    hitbox_height = 2.0

    # Distances, in metres
    aggro_range = 10.0
    deaggro_range = 20.0
    attack_range = 1.5
    move_speed = (3.0, 6.0)   # (walk, run)

    # Walking numbers, in a world you can sprint across
    ai_arrive = 0.5
    wander_range = (2.0, 8.0)
    run_ratio = 2.0

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 tag=None, opacity=1.0, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag,
                         opacity=opacity)
        self.set_knobs(knobs)
        self._entity_init()

    # -- my world ---------------------------------------------------------
    def _plane(self):
        """I cross the floor: x and z, not height."""
        return (0, 2)

    def _facing(self, dx, dy):
        """Turn my yaw toward a move, second value is depth."""
        self.yaw = math.atan2(dx, dy)

    def _moved(self):
        """Re-place the nodes I carry."""
        self.push_local()
        self.propagate()

    def _flat(self):
        """On the ground: what I hold swings as I turn."""
        return abs(float(self.pos[1])) < 1e-6


class Entity2D(EntityBehaviour, Object2D):
    """2D entities (NPCs, enemies) with AI, health and hitboxes."""

    kind = "2d"
    name = "entity2d"
    clone_gap = (64.0, 0.0)
    clone_attrs = ("health", "max_health", "ai_type", "ai_config",
                   "hitbox_shape", "hitbox_radius")
    doc_knobs = ("opacity", "shader", "health", "max_health", "ai_type",
                 "ai_config", "hitbox_shape", "hitbox_radius")

    # Hitbox
    hitbox_shape = "rect"     # "rect", "circle"
    hitbox_shapes = ("rect", "circle")
    hitbox_radius = 24.0      # for circle
    hitbox_size = (48.0, 48.0)  # for rect

    # Distances, in pixels
    aggro_range = 200.0
    deaggro_range = 400.0
    attack_range = 32.0
    move_speed = 100.0        # pixels per second

    # Walking numbers, in a world measured in pixels
    ai_arrive = 10.0
    wander_range = (50.0, 200.0)
    run_ratio = 1.5

    def __init__(self, scene, pos=(0.0, 0.0), size=(64.0, 64.0),
                 texture="white", col=(1.0, 1.0, 1.0), rot=0.0,
                 anchor=(0.5, 0.5), grid=(1, 1), frame=0, uv=None,
                 flip=False, tag=None, blend="alpha", opacity=1.0, **knobs):
        super().__init__(scene, pos=pos, size=size, texture=texture, col=col,
                         rot=rot, anchor=anchor, grid=grid, frame=frame, uv=uv,
                         flip=flip, tag=tag, blend=blend, opacity=opacity)
        self.set_knobs(knobs)
        self._entity_init()

    # -- my world ---------------------------------------------------------
    def _plane(self):
        """I cross the screen: x and y, like a sprite."""
        return (0, 1)

    def _facing(self, dx, dy):
        """Turn my rotation toward a move."""
        self.rot = math.atan2(dy, dx)

    def _moved(self):
        """Redraw where I stand, and re-place the nodes I carry."""
        self.moved()

    def _hitbox_shape(self, shape):
        """A circle is round; anything else is my box."""
        return "circle" if str(shape) == "circle" else "rect"


def first_object_class(module, base=GameObject):
    """The object subclass a project file defines."""
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
