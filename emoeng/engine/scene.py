"""Scene authoring API: three kinds of playable screen, one lifecycle."""

import inspect

import numpy as np
import pygame

from . import colors, lights as lightmod
from . import collision as collmod
from . import shaders as shadermod
from . import ui as uimod
from .camera import Camera, Camera2D
from .meshes import MeshData, frame_pin, mesh_anchor, slide_pin
from .objects import (GameObject, Object2D, Object3D, UIObject,
                      ModelObject,             # noqa: F401 (re-exported)
                      answers_to, node_from)
from .timers import Timers


def _slide(data, off):
    """A copy of one MeshData slid by `off` metres."""
    dx, dy, dz = off
    m = MeshData()
    m.pos = [(p[0] + dx, p[1] + dy, p[2] + dz) for p in data.pos]
    m.nrm = list(data.nrm)
    m.uv = list(data.uv)
    m.col = list(data.col)
    m.idx = list(data.idx)
    m.tex = list(data.tex)
    return m


def _uv_look(obj):
    """An object's uv fit, when it carries one."""
    fn = getattr(obj, "uv_look", None)
    return fn() if callable(fn) else None


def _frame_of(obj):
    """Where a metre sheet is pinned on this object, and how it turns."""
    pos = getattr(obj, "pos", None) or ()
    if obj is None or len(list(pos)) < 2:
        return None
    return frame_pin(pos, getattr(obj, "yaw", 0.0))


def _hook_arity(hook):
    """How many arguments a trigger hook takes."""
    try:
        params = list(inspect.signature(hook).parameters.values())
    except (TypeError, ValueError):
        return 2
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return 2
    return sum(1 for p in params
               if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))


def _deliver(hook, name, value):
    """Call a trigger hook with as much of (name, value) as it takes."""
    return hook(name) if _hook_arity(hook) < 2 else hook(name, value)


class Hud:
    """`self.hud`: HUD drawing, screen and font ready."""

    def __init__(self, scene):
        self.scene = scene

    @property
    def screen(self):
        """The window surface, read fresh for resizes."""
        return self.scene.game.screen

    @property
    def area(self):
        """The window minus caption, menu and status bars."""
        return self.scene.game.play_area()

    @property
    def font(self):
        return self.scene.game.fonts["normal"]

    def font_of(self, size="big"):
        """A named font: `small`, `normal`, `big`, `title` or `mono`."""
        return self.scene.game.fonts.get(size) or self.font

    def text(self, s, pos, color=uimod.DEFAULT_TEXT, align="left",
             shadow=uimod.SHADOW, alpha=255):
        return uimod.text(self.screen, self.font, s, pos, color, shadow,
                          align, alpha)

    def panel(self, rect, color=(10, 10, 14), alpha=150, border=None):
        return uimod.panel(self.screen, rect, color, alpha, border)

    def bar(self, rect, frac, **kw):
        return uimod.bar(self.screen, rect, frac, **kw)

    def crosshair(self, centre=None, **kw):
        """A crosshair mid play area, unless told where."""
        return uimod.crosshair(self.screen, centre or self.area.center, **kw)

    def prompt(self, key, label, centre=None, **kw):
        """'[E] pick up' low on the screen unless told where."""
        area = self.area
        return uimod.prompt(self.screen, self.font, key, label,
                            centre or (area.centerx, area.bottom - 92),
                            **kw)

    def hints(self, pairs, pos=None, **kw):
        """A column of 'key  action' rows, bottom left by default."""
        if pos is None:
            area = self.area
            pos = (area.x + 14,
                   area.bottom - self.font.get_height() * len(pairs) - 16)
        return uimod.hints(self.screen, self.font, pairs, pos, **kw)

    def subtitle(self, lines, bottom=None, **kw):
        """Centred captions above the bottom edge, unless given y."""
        area = self.area
        return uimod.subtitle(self.screen, self.font, lines,
                              area.bottom - 16 if bottom is None else bottom,
                              **kw)

    def dim(self, amount=0.55):
        """Darken the frame, for a pause or cutscene card."""
        return uimod.dim(self.screen, amount)

    def __repr__(self):
        return f"<Hud {self.scene.name}>"


class Scene:
    """The shared shell: objects, timers, events, one render entry."""

    kind = "scene"
    name = "scene"
    object_base = GameObject      # what self.spawn() accepts
    uses = ()                     # object files this scene places
    actions = {}                  # action -> bindings, bound on load
    controls = ()                 # extra actions the help panel lists

    clear_color = (0.02, 0.02, 0.03)
    post = ()                     # the frame's own shader chain: names of
                                  # `screen` looks in the project's shaders/
    viewport = None               # None = the whole window, or a rect
                                  # (x, y, w, h) in pixels / 0..1 floats
    camera_class = None           # what add_camera() builds (per kind)

    # lighting the renderer uploads: `ambient2d` and `blockers`
    ambient = (0.22, 0.22, 0.26)
    ambient2d = (0.10, 0.10, 0.12)
    sun_dir = (0.35, 0.75, 0.5)     # normalised by the renderer
    sun_col = (0.22, 0.20, 0.18)
    blockers = None               # rects / segments / objects / a callable
    master = 1.0                  # scene-wide dimmer: set_master(0) is black

    # movement numbers a script may read: the engine's walk-mode player is
    # glued to the ground, so these only mean something to a scene that
    # implements falling (`self.gravity` down, `self.jump_speed` up)
    gravity = 0.0
    jump_speed = 0.0

    def __init__(self, game, seed=7):
        self.game = game
        self.project = game.project
        self.renderer = game.renderer
        self.audio = game.audio
        self.input = game.input
        self.rng = np.random.default_rng(seed)
        self.objects = []
        self.lights = []            # Light3D / Light2D (or old-style dicts)
        self.sun = None             # the one directional light, if any
        self.player = None          # the attached player object (any kind)
        self.camera_rig = None      # Scene3D: object that claimed set_camera()
        self.lock_input = False     # freezes the player (cutscenes etc.)
        self.cameras = {}           # name -> Camera/Camera2D add_camera made
        self.active = None          # name of the rendering camera; None =
                                    # the scene's default view
        self.t = 0.0                # seconds since setup(), advanced here
        self.timers = Timers()
        self.save = game.save
        self._hud = None            # built on first use, see `hud`
        # `.scene` placement: `plan` by stable name, `doc` whole
        self.plan = {}
        self.doc = None
        self.placed = {}            # class name -> how many spawn() built
        # live-drag bookkeeping: meshes, queued geometry, sequence numbers
        self.live = False
        self._rec = None            # the object whose build is recording
        self.live_add = {}
        self.live_pos = {}
        self.live_seq = {}
        self.live_anchor = {}         # ident -> where its sheet is pinned
        # every Collision/Hitbox node, in spawn order
        self.colliders = []
        # trigger bus: name -> [(owner, method)] waiting for a broadcast
        self.listeners = {}
        # objects `queue_free()` marked, taken out when the frame ends
        self._freeing = []

    @property
    def hud(self):
        """HUD helpers bound to this scene's screen and font (`scene.Hud`)."""
        if self._hud is None:
            self._hud = Hud(self)
        return self._hud

    def setup(self):
        pass

    def add(self, data, texture="white", blend="opaque", owner=None,
            opacity=None, shader=None, uv=None):
        """Queue batched static geometry (merged per texture+blend)."""
        host = self._rec if self._rec is not None else owner
        fit = uv if uv is not None else _uv_look(self._rec or owner)
        pin = _frame_of(host) or mesh_anchor(data)
        claim = None
        if self.kind == "3d" and self.live and self._rec is not None:
            # record this build's geometry, drawn under the current sequence
            obj = self._rec
            ident = id(obj)
            self.live_anchor.setdefault(ident, pin)
            got = self._opacity_of(opacity, obj)
            self.live_add.setdefault(ident, []).append(
                (data, texture, blend, got, shader, fit))
            self.live_pos[ident] = list(getattr(obj, "pos", (0, 0, 0)))[:3]
            seq = self.live_seq.setdefault(ident, 0)
            claim = (ident, seq, len(self.live_add[ident]) - 1)
        elif self.kind == "3d" and self.live and owner is not None \
                and id(owner) in self.live_add:
            # a late `add` claims a fresh mesh, dropping the old
            ident = id(owner)
            seq = self.live_seq[ident] = self.live_seq.get(ident, 0) + 1
            self.live_anchor.setdefault(ident, pin)
            got = self._opacity_of(opacity, owner)
            self.live_add[ident] = [(data, texture, blend, got, shader, fit)]
            self.live_pos[ident] = list(getattr(owner, "pos",
                                                (0, 0, 0)))[:3]
            self.renderer.drop_live(ident, seq - 1)
            self.renderer.add(data, texture=texture, blend=blend,
                              claim=(ident, seq, 0), opacity=got,
                              shader=shader, uv=fit,
                              anchor=self.live_anchor[ident])
            return
        self.renderer.add(data, texture=texture, blend=blend, claim=claim,
                          opacity=self._opacity_of(opacity, owner),
                          shader=shader, uv=fit, anchor=pin)

    @staticmethod
    def _opacity_of(opacity, owner=None):
        """An explicit opacity, or the one the drawing object carries."""
        if opacity is None:
            opacity = getattr(owner, "opacity", None)
        return 1.0 if opacity is None else opacity

    def dynamic(self, data, texture="white", blend="alpha", **kw):
        """A mesh the scene refills every frame instead of batching."""
        return self.renderer.new_dynamic(data, texture=texture,
                                         blend=blend, **kw)

    def set_post(self, *names):
        """The shader chain this scene's frame runs through, by name."""
        self.post = tuple(names)
        return self.post

    def set_shader_knob(self, name, knob, value):
        """Retune a knob of a shader this scene draws."""
        find = getattr(self.project, "shader_class", None)
        cls = find(str(name)) if find is not None else None
        pas = shadermod.make_pass(cls) if cls is not None else None
        return pas.set(knob, value) if pas is not None else None

    def object_class(self, obj):
        """Resolve a class or a project name to its class.

        A name is looked for in `entities/` first, then `objects/`, so a
        script may say `spawn("enemy")` without caring which folder the
        behaviour lives in.
        """
        if isinstance(obj, str):
            cls = self.project.spawnable(obj, self.object_base)
        else:
            cls = obj
        if not (isinstance(cls, type) and issubclass(cls, self.object_base)):
            raise TypeError(f"{obj!r} is not a {self.object_base.__name__} "
                            "class or an objects/entities name")
        return cls

    def spawn(self, obj, pos=None, parent=None, clone_of=None, tag=None,
              look=None, **kw):
        """Create an object, attach and build it."""
        cls = self.object_class(obj)
        name = cls.__name__
        index = self.placed.get(name, 0)
        self.placed[name] = index + 1
        index_key = f"{name}#{index}"
        moved = self.plan.get(index_key) or {}
        # document beats class defaults; an explicit `look` beats both
        how = dict(getattr(cls, "look_defaults", None) or {})
        how.update(moved)
        if look:
            how.update(look)
        spot = how.pop("pos", None)
        if spot is not None and (pos is None or "pos" in moved or
                                 "pos" in (look or {})):
            # an object's document is a default; a caller's place wins
            pos = spot
        inst = cls(self, pos=self.default_pos() if pos is None else pos,
                   **kw)
        # yaw/scale and rot/size are copied, not guessed
        if "yaw" in how and hasattr(inst, "yaw"):
            inst.yaw = float(how["yaw"])
        if "scale" in how and hasattr(inst, "scale"):
            inst.scale = float(how["scale"])
        if "rot" in how and hasattr(inst, "rot"):
            inst.rot = float(how["rot"])
        if "size" in how and hasattr(inst, "size"):
            inst.size = tuple(float(c) for c in how["size"])
        if "opacity" in how and hasattr(inst, "opacity"):
            # fade before build(), the only moment it is honoured
            inst.opacity = float(how["opacity"])
        # node knobs land before the geometry is made
        knobs = how.pop("knobs", None)
        if knobs:
            inst.set_knobs(knobs)
        if how.get("shader") is not None:
            # a look is decided before build() too
            inst.set_shader(how["shader"])
        inst.look = how
        inst.doc_key = index_key if parent is None or not parent.doc_key \
            else f"{parent.doc_key}/{index_key}"
        inst.attach(parent=parent, clone_of=clone_of, tag=tag)
        self.objects.append(inst)
        try:
            self._rec = inst
            inst.build()
        except Exception:
            self.objects.remove(inst)
            inst.alive = False
            inst.dispose()
            raise
        finally:
            self._rec = None
        self._post_spawn(inst, cls)
        return inst

    def default_pos(self):
        return (0.0, 0.0)

    def _post_spawn(self, inst, cls):
        """Hook for scene kinds: adopt the first player object."""
        if getattr(cls, "is_player", False) and self.player is None:
            self.attach_player(inst)

    def attach_player(self, ent, **kw):
        """Make an object this scene's player."""
        self.player = ent
        if hasattr(ent, "lock_input"):
            ent.lock_input = bool(self.lock_input)
        return ent

    def relive(self, obj):
        """Redraw a live object's recorded geometry where it now stands."""
        ident = id(obj)
        items = list(self.live_add.get(ident) or ())
        if not items:
            return 0
        was = self.live_pos.get(ident) or [0.0, 0.0, 0.0]
        now = list(getattr(obj, "pos", (0, 0, 0)))[:3]
        off = [now[k] - was[k] for k in range(3)]
        slid = any(abs(c) > 1e-6 for c in off)
        seq = self.live_seq[ident] = self.live_seq.get(ident, 0) + 1
        if ident not in self.live_anchor:
            # a drag that starts without a recorded build pins itself now
            self.live_anchor[ident] = _frame_of(obj) or mesh_anchor(
                items[0][0])
        # the pin travels with the body, so its sheet rides it and does not
        # swim underneath; the stored pin stays at the build place, since
        # every relive slides the build geometry by the whole distance
        pin = slide_pin(self.live_anchor[ident], off) if slid \
            else self.live_anchor[ident]
        self.renderer.drop_live(ident, seq - 1)
        for index, (data, texture, blend, opacity, shader, uv) in \
                enumerate(items):
            self.renderer.add(_slide(data, off) if slid else data,
                              texture=texture, blend=blend, opacity=opacity,
                              claim=(ident, seq, index), shader=shader,
                              uv=uv, anchor=pin)
        return len(items)

    def set_owner_opacity(self, obj, opacity):
        """Re-file a live object's recorded geometry at a new opacity."""
        items = self.live_add.get(id(obj))
        if not items:
            return 0
        self.live_add[id(obj)] = [(data, texture, blend, opacity, shader, uv)
                                  for (data, texture, blend, _o, shader, uv)
                                  in items]
        return self.relive(obj)

    def despawn(self, obj):
        """Take an object, and its offspring, out."""
        if obj is None or not getattr(obj, "alive", False):
            return False
        for child in list(obj.children) + list(obj.clones):
            self.despawn(child)
        obj.alive = False
        obj.dispose()
        ident = id(obj)
        if ident in self.live_add or ident in self.live_seq:
            self.renderer.drop_live(ident, self.live_seq.get(ident))
            self.live_add.pop(ident, None)
            self.live_pos.pop(ident, None)
            self.live_seq.pop(ident, None)
            self.live_anchor.pop(ident, None)
        if obj in self.objects:
            self.objects.remove(obj)
        if obj in self.colliders:
            self.colliders.remove(obj)
        # drop the parent link, or a dead node lives on
        parent = obj.parent
        if parent is not None and obj in parent.children:
            parent.children.remove(obj)
        obj.parent = None
        if obj is self.player:
            self.player = None
        if obj is self.camera_rig:
            self.camera_rig = None
        # cameras the object made leave with it; the default stays
        for name, cam in list(self.cameras.items()):
            if getattr(cam, "owner", None) is obj:
                del self.cameras[name]
                if self.active == name:
                    self.active = None
        if getattr(obj, "look_camera", None) is not None:
            obj.look_camera = None
        return True

    def objects_of(self, obj):
        """Every live object of one class (or an objects/entities name)."""
        cls = self.object_class(obj)
        return [o for o in self.objects
                if isinstance(o, cls) and o.alive]

    def queue_free(self, obj):
        """Mark an object to leave when this frame's update ends.

        Removal in the middle of a loop over `get_children()` would skip a
        node, so the request waits its turn; `despawn()` still means now.
        """
        if obj is not None and getattr(obj, "alive", False) and \
                not any(o is obj for o in self._freeing):
            self._freeing.append(obj)
        return obj

    def _drain_free(self):
        """Remove everything `queue_free()` marked; runs after the objects."""
        while self._freeing:
            self.despawn(self._freeing.pop(0))
        return self

    def get_node(self, path):
        """A live object by branch: `get_node("Torch#0/Flame#0")`.

        A word is a node's document name, its tag or its class. Top-level
        names are looked for among the scene's roots first, so a script need
        not spell the whole branch to reach a node it knows the name of.
        `"."` is the scene itself.
        """
        text = str(path or "").strip().replace("\\", "/")
        parts = [p for p in text.split("/") if p and p != "."]
        if not parts or parts[0] == "..":
            return self
        roots = [o for o in self.objects if o.alive and o.parent is None]
        return node_from(roots, parts) or node_from(self.objects, parts)

    def find_by_name(self, name):
        """The first live object that goes by that name, or None."""
        for obj in self.objects:
            if obj.alive and answers_to(obj, name):
                return obj
        return None

    def by_tag(self, tag):
        """The first live object with that tag, or None."""
        for obj in self.objects:
            if obj.alive and obj.tag == tag:
                return obj
        return None

    def add_collider(self, node):
        """File a Collision/Hitbox node for movers and triggers."""
        if node not in self.colliders:
            self.colliders.append(node)
        return node

    def remove_collider(self, node):
        """Take a node out of the list; safe if absent."""
        if node in self.colliders:
            self.colliders.remove(node)
        return node

    def colliders_of(self, group="", solid=None):
        """The nodes a mover should reckon with."""
        out = []
        for node in self.colliders:
            if not getattr(node, "alive", True):
                continue
            if solid is not None and bool(node.solid) != bool(solid):
                continue
            got = getattr(node, "group", "") or ""
            if got and got != (group or ""):
                continue
            out.append(node)
        return out

    def collider_boxes(self, group="", solid=True):
        """Every solid 3D shape as a `(centre, half)` box."""
        return [node.box() for node in self.colliders_of(group, solid)
                if hasattr(node, "box")]

    def collider_rects(self, group="", solid=True):
        """Solid 2D shapes as (x, y, w, h) rects."""
        return [node.rect() for node in self.colliders_of(group, solid)
                if hasattr(node, "rect")]

    def move_body(self, pos, delta, half=(0.35, 0.9, 0.35), group=""):
        """Sweep a box body through the scene, per axis."""
        nodes = self.colliders_of(group, True)
        boxes = [node.box() for node in nodes
                 if hasattr(node, "box") and not hasattr(node, "mesh")]
        meshes = [node.mesh for node in nodes
                  if getattr(node, "mesh", None) is not None]
        if not boxes and not meshes:
            return ([float(p) + float(d) for p, d in zip(pos, delta)],
                    (False, False, False))
        if meshes:
            return collmod.move_slide_mesh(pos, delta, boxes, meshes, half)
        return collmod.move_slide(pos, delta, boxes, half)

    def move_body2d(self, pos, delta, radius=0.0, group=""):
        """The 2D twin of `move_body`, sweeping against solid rects."""
        rects = self.collider_rects(group=group)
        if not rects:
            return ([float(p) + float(d) for p, d in zip(pos, delta)],
                    (False, False))
        return collmod.move_slide2d(pos, delta, rects, radius)

    def hits_at(self, point, group=""):
        """Every trigger node covering a point, 3D or 2D."""
        out = []
        for node in self.colliders_of(group, solid=False):
            test = getattr(node, "contains", None)
            if test is not None and test(point):
                out.append(node)
        return out

    def model(self, name):
        """Load (cached) a model from the project's models folder."""
        return self.project.model(name)

    def place_model(self, name, pos, yaw=0.0, scale=1.0, tint=None,
                    opacity=None, shader=None, uv=None):
        """Stamp a `.model` into the static batch."""
        m = self.model(name)
        for tex, md in m.mesh_groups(pos, yaw, scale, tint):
            self.add(md, texture=self._bake_shader(shader, tex),
                     opacity=opacity, uv=uv)
        return m

    def _bake_shader(self, shader, sheet):
        """The sheet through a `texture` look, or plain."""
        if shader is None:
            return sheet
        pas = self.renderer.shader_pass(shader)
        if pas is None:
            return sheet
        if pas.mode == "screen":
            shadermod.warn_once(f"{pas.name}: a scene look, so it cannot be "
                                "baked into one object's sheet")
            return sheet
        if pas.mode == "uv":
            shadermod.warn_once(f"{pas.name}: needs a mesh of its own, so "
                                "it is baked into the sheet instead")
            pas = shadermod.make_pass(shadermod.as_mode(pas.cls, "texture"))
            if pas is None:
                return sheet
        return self.renderer.shaded_texture(sheet, pas)

    def model_object(self, name, pos, yaw=0.0, scale=1.0, tint=None,
                     texture=None, blend="opaque", opacity=1.0,
                     shader=None, uv=None):
        """A movable model instance (dynamic mesh)."""
        return ModelObject(self, self.model(name), pos, yaw, scale, tint,
                           texture, blend, opacity, shader, uv)

    def add_light(self, pos=None, color=None, shape=None, **kw):
        """Put a light in the scene; hand it back."""
        if isinstance(pos, lightmod.Light):
            return self._add_existing(pos, color, shape, kw)
        if isinstance(pos, dict):
            return self._add_existing(
                lightmod.Light.from_dict(dict(pos), self), color, shape, kw)
        dims = kw.pop("dims", None)
        if dims is None:
            if pos is not None:
                dims = 2 if len(pos) <= 2 else 3
            else:
                low = str(shape or "").lower()
                flat, solid = (low in lightmod.SHAPES_2D,
                               low in lightmod.SHAPES_3D)
                # a shared light name follows the scene; unique names decide
                dims = (2 if flat else 3) if flat != solid else \
                    (2 if self.kind in ("2d", "ui") else 3)
        cls = lightmod.Light2D if dims == 2 else lightmod.Light3D
        if color is not None:
            kw["color"] = color
        if shape is not None:
            kw["shape"] = shape
        light = cls(self, pos=pos, **kw)
        self.lights.append(light)
        return light

    def _add_existing(self, light, color=None, shape=None, kw=None):
        """Adopt a light made elsewhere: a copy here, keywords applied."""
        kw = dict(kw or {})
        pos = kw.pop("pos", None)
        tag = kw.pop("tag", None)
        kw.pop("dims", None)
        if color is not None:
            kw["color"] = color
        if shape is not None:
            kw["shape"] = shape
        if light.scene is self and light in self.lights \
                and not kw and pos is None and tag is None:
            return light        # already ours, unchanged: nothing to do
        got = light.copy(self, pos=pos, tag=tag)
        if kw:
            got.set(**kw)
        return got

    def copy_light(self, light, pos=None, tag=None, **kw):
        """A second copy of one of the scene's lights."""
        return self._add_existing(light, kw=dict(kw, pos=pos, tag=tag))

    def add_preset(self, name, pos=None, dim=None, tag=None, **kw):
        """A ready-made light: "campfire", "streetlamp", "siren", "pool"."""
        light = lightmod.preset(name, self, pos=pos, dim=dim, tag=tag, **kw)
        self.lights.append(light)
        return light

    def remove_light(self, light):
        """Remove a light; True when it was there."""
        found = light
        if isinstance(light, str):
            found = next((L for L in self.lights if L.tag == light), None)
        if found is None:
            return False
        if found in self.lights:
            self.lights.remove(found)
        elif found is not self.sun:
            return False
        if found is self.sun:
            self.sun = None
        if hasattr(found, "dispose"):
            found.dispose()
        return True

    def clear_lights(self):
        """Switch every light off and drop it."""
        for light in list(self.lights) + ([self.sun] if self.sun else []):
            if hasattr(light, "dispose"):
                light.dispose()
        self.lights = []
        self.sun = None
        return self

    def _lit(self):
        """The light list, old dict entries swapped for lights."""
        for i, entry in enumerate(self.lights):
            if not isinstance(entry, lightmod.Light):
                self.lights[i] = lightmod.coerce(entry, self)
        return self.lights

    def lights_near(self, pos, radius=None):
        """The lights around a point, nearest first."""
        got = []
        for light in self._lit():
            dist = light.distance_to(pos)
            span = light.radius if radius is None else float(radius)
            if span <= 0.0 or dist <= span:
                got.append((dist, light))
        got.sort(key=lambda item: item[0])
        return [light for _dist, light in got]

    def luminance(self, pos=None):
        """How bright one spot is, added up from every light."""
        if pos is None:
            pos = getattr(self.player, "pos", (0.0, 0.0, 0.0))
        amb = self.ambient2d if self.kind in ("2d", "ui") else self.ambient
        return lightmod.luminance_at(pos, self._lit(),
                                     ambient=float(np.mean(amb)) * self.master)

    def light_count(self):
        """How many lights the scene holds and shines."""
        shining = len([L for L in self._lit()
                       if L.enabled and L.level() > 0.0])
        return {"lights": len(self.lights), "shining": shining,
                "sun": 1 if self.sun is not None else 0}

    def set_ambient(self, color, level=1.0):
        """The light always on, in both worlds."""
        got = colors.rgb(color, None)
        if got is None:
            raise TypeError(f"{color!r} is not a colour")
        k = float(level)
        self.ambient = tuple(c * k for c in got)
        self.ambient2d = tuple(c * k for c in got)
        return self.ambient

    def set_master(self, value=1.0):
        """Dim all scene lighting, including ambient."""
        got = lightmod.set_master(value, self)
        if self.sun is not None:
            self.sync_sun()          # the sun's colour carries the dimmer
        return got

    def set_sun(self, dir=None, color=None, energy=None, hour=None, **kw):
        """The scene's one directional light, made on the first call."""
        if self.sun is None:
            self.sun = lightmod.Light3D(
                self, shape="sun", pos=(0.0, 0.0, 0.0),
                dir=tuple(dir if dir is not None else self.sun_dir),
                color=color if color is not None else "white",
                energy=1.0 if energy is None else energy, **kw)
        else:
            self.sun.set(dir=dir, color=color, energy=energy, **kw)
        if hour is not None:
            self.sun.set_time(hour)
        self.sync_sun()
        return self.sun

    def sync_sun(self):
        """Copy the sun light onto the uniforms the renderer reads."""
        sun = self.sun
        if sun is None:
            return None
        self.sun_dir = list(sun.dir)
        self.sun_col = tuple(sun.tint())
        return self.sun_dir

    def finish_build(self):
        self.renderer.build()

    def bake_lights(self, size=None):
        """Freeze the scene's bake-mode lights into each model's lightmap."""
        bake = [L for L in self.lights
                if getattr(L, "bake", False)
                and not isinstance(L, lightmod.Light2D)]
        if not bake:
            return 0
        master = self.master if self.master is not None else 1.0
        ambient = tuple(c * master for c in self.ambient)
        done = {}
        tried = set()
        for host, inst in self._bake_targets():
            model = getattr(inst, "model", None)
            if model is None or not len(getattr(model, "uv2", ())) \
                    or not len(model.tris):
                continue
            place = (getattr(inst, "pos", (0, 0, 0)),
                     getattr(inst, "yaw", 0.0),
                     getattr(inst, "scale", 1.0),
                     getattr(inst, "tint", None))
            if model.has_objects:
                # one map per object: each part bakes separately
                for obj in model.align_objects():
                    if not obj["faces"]:
                        continue
                    slot = f"{model.name}-{obj['name']}"
                    if slot in tried:
                        continue
                    tried.add(slot)
                    md = model.meshdata(*place, faces=obj["faces"])
                    done[slot] = (model, obj["name"],
                                  self.renderer.bake_lightmap(
                                      slot, md, ambient, bake, size=size))
                continue
            if model.name in tried:
                continue
            tried.add(model.name)
            md = model.meshdata(*place)
            done[model.name] = (model, None,
                                self.renderer.bake_lightmap(
                                    model.name, md, ambient, bake,
                                    size=size))
        for slot, (model, oname, key) in done.items():
            if key is None:
                continue
            if oname is None:
                model.lightmap = key
            else:
                for obj in model.objects:
                    if obj["name"] == oname:
                        obj["lightmap"] = key
            for _host, inst in self._bake_targets():
                if getattr(inst, "model", None) is model and \
                        hasattr(inst, "_build"):
                    inst._build()
        return len(done)

    def _bake_targets(self):
        """Every scene object and the ModelObject instances it owns."""
        for host in self.objects:
            if getattr(host, "obj", None) is not None \
                    and hasattr(host.obj, "model"):
                yield host, host.obj
            for inst in getattr(host, "objects", ()) or ():
                if hasattr(inst, "model"):
                    yield host, inst
            direct = getattr(host, "model", None)
            if hasattr(direct, "uv2") and hasattr(direct, "tris"):
                yield host, host

    def after(self, delay, func, *args, **kwargs):
        """Call func once, delay seconds from now."""
        return self.timers.after(delay, func, *args, **kwargs)

    def every(self, delay, func, *args, **kwargs):
        """Call func every delay seconds until the scene ends."""
        return self.timers.every(delay, func, *args, **kwargs)

    def play_scene(self, name, fade=0.35):
        """Fade out, load another scene, fade in."""
        self.game.play_scene(name, fade=fade)

    def push_scene(self, name, fade=0.35):
        """Stack another scene over this one; pop_scene() comes back."""
        self.game.push_scene(name, fade=fade)

    def pop_scene(self, fade=0.35):
        """Leave the top scene and return to the one underneath."""
        self.game.pop_scene(fade=fade)

    def update(self, dt):
        if self.is_current():
            # only the scene the game runs hears the keyboard
            for name in self.input.fired_triggers():
                self.broadcast(name)
        self.t += dt
        self.timers.update(dt)
        for obj in list(self.objects):
            if obj.alive:
                obj.update(dt)
        # a node `queue_free()`d mid-frame leaves only now, once the loop
        # that asked for it has finished
        self._drain_free()
        # nodes are re-derived from their parents after moves
        self.sync_tree()
        for light in list(self._lit()):
            light.update(dt)
        if self.sun is not None:
            self.sun.update(dt)
            self.sync_sun()
        # every registered camera ticks, so parked angles keep easing
        for cam in self.cameras.values():
            cam.update(dt)

    def sync_tree(self):
        """Move every node to wherever its parent has got to."""
        for obj in self.objects:
            if obj.alive and obj.parent is not None:
                obj.follow_parent()
        return self

    def handle_event(self, e):
        return False

    def render(self, camera=None):
        """Draw one frame; the game blits the Surface."""
        return self.renderer.render(self.view or camera, self)

    def overlay(self, screen):
        pass

    def on_enter(self):
        """Called every time play mode (re)starts this scene."""

    def on_exit(self):
        self.timers.clear()
        self._freeing = []

    def on_save(self, save):
        """Called with the project's SaveStore before it is written."""

    def on_load(self, save):
        """Called with the store after a slot loads."""

    def on_trigger(self, name, value=None):
        """Called when a trigger is broadcast; the scene's own hook."""

    def is_current(self):
        """True when the game runs this scene, not a picture inside one."""
        return getattr(self.game, "scene", None) is self

    def broadcast(self, name, value=None):
        """Say a trigger fired: me, my listeners, every object with a hook."""
        name = str(name)
        self.on_trigger(name, value)
        for owner, method in list(self.listeners.get(name, ())):
            # a `connect()` listener is the callable; a `listen()` one owns it
            hook = owner if method is None else getattr(owner, method, None)
            if hook is not None:
                _deliver(hook, name, value)
        for obj in list(self.objects):
            if obj.alive and hasattr(obj, "on_trigger"):
                _deliver(obj.on_trigger, name, value)
        return name

    def listen(self, name, owner, method="on_trigger"):
        """Have `owner` hear a trigger broadcast; the pair back.

        `method` is the name of the hook to call on `owner`, or None when
        `owner` is the callable itself -- what `connect()` asks for.
        """
        name = str(name)
        row = self.listeners.setdefault(name, [])
        pair = (owner, None if method is None else str(method))
        if pair not in row:
            row.append(pair)
        return pair

    def unlisten(self, name, owner=None):
        """Forget one listener of a trigger, or every listener of it."""
        name = str(name)
        if owner is None:
            return self.listeners.pop(name, [])
        # `!=` as well as identity, so a bound method lets itself go
        row = [pair for pair in self.listeners.get(name, ())
               if pair[0] is not owner and pair[0] != owner]
        if self.listeners.get(name) is None:
            return []
        self.listeners[name] = row
        return row

    # -- signals, as Godot spells them ------------------------------------
    def connect(self, name, fn, method=None):
        """Hear a signal: `connect("door", self.on_door)`.

        An object and the name of its hook work too, and mean the same as
        the older `listen("door", obj, "on_door")`.
        """
        if method is None and not callable(fn):
            raise TypeError("a signal listener is a callable, or an object "
                            "and the name of its hook")
        return self.listen(name, fn, method)

    def disconnect(self, name, fn=None):
        """Forget one listener of a signal, or every listener of it."""
        return self.unlisten(name, fn)

    def emit(self, name, value=None):
        """Fire a signal: the Godot name for `broadcast()`."""
        return self.broadcast(name, value)

    def status(self):
        return [self.name]

    def add_camera(self, camera=None, name=None, **kw):
        """Register another view for this scene and hand it back."""
        if camera is None:
            if self.camera_class is None:
                raise TypeError(f"{type(self).__name__} has no camera class")
            cam = self.camera_class(**kw)
        else:
            cam = camera
        name = name or getattr(cam, "name", None) or \
            f"cam{len(self.cameras) + 1}"
        cam.name = str(name)
        self.cameras[cam.name] = cam
        return cam

    def set_active_camera(self, cam=None):
        """Swap the angle the scene renders through."""
        if cam is None:
            self.active = None
            return None
        if isinstance(cam, str):
            if cam not in self.cameras:
                raise KeyError(
                    f"no camera '{cam}' in scene '{self.name}'; have: "
                    f"{', '.join(self.cameras) or 'none'}")
            self.active = cam
            return self.cameras[cam]
        if not any(cam is c for c in self.cameras.values()):
            self.add_camera(cam)
        self.active = cam.name
        return cam

    @property
    def active_camera(self):
        """The registered camera rendering the scene, or None."""
        return self.cameras.get(self.active) if self.active else None

    @property
    def view(self):
        """Active camera first; otherwise the game's own camera."""
        return self.active_camera or getattr(self.game, "camera", None)

    def bind(self, action, *bindings):
        """Bind an action to tokens, exactly like `input.map.json` does."""
        self.input.bind(action, *bindings)
        return action


class Scene3D(Scene):
    """One playable (or cutscene) 3D world chunk."""

    kind = "3d"
    name = "scene"
    object_base = Object3D
    camera_class = Camera           # add_camera() builds perspective rigs
    uses = ()                       # objects/<name>.py this scene spawns

    # camera knobs used when no Player is spawned
    camera = "walk"                 # "walk" glues to the ground, "fly" is free
    move_speed = (6.0, 12.0)        # (walk, run) m/s
    eye_height = 2.0                # above ground in walk mode
    world_radius = 128.0            # hard camera clamp from origin; 0 = off
                                    # levels set 0 and manage the player themselves
    fov = 68.0                      # vertical field of view, degrees
    near = 0.05                     # frustum, in world units
    far = 800.0                     # anything past this is not drawn
    roll = 0.0                      # horizon tilt in radians (Dutch angle)

    # lighting defaults the renderer uploads every frame
    fog_color = (0.06, 0.06, 0.09)
    fog_near = 40.0
    fog_far = 220.0

    def default_pos(self):
        return (0.0, 0.0, 0.0)

    def handle_event(self, e):
        """Land an aimed click on a screen panel."""
        if e.type not in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                          pygame.MOUSEMOTION):
            return False
        button = getattr(e, "button", 0)
        if button in (4, 5, 6):           # a wheel notch is not a click
            return False
        screens = [o for o in self.objects
                   if getattr(o, "pickable", None) is not None
                   and o.pickable() and o.alive]
        if not screens:
            return False
        cam = self.view
        if cam is None:
            return False
        size = self.game.screen.get_size()
        if getattr(self.input, "grabbed", False):
            pos = (size[0] // 2, size[1] // 2)
        else:
            pos = getattr(e, "pos", None)
            if pos is None:
                return False
        try:
            origin, direction = cam.ray(size, pos)
        except np.linalg.LinAlgError:
            return False
        best = None
        for s in screens:
            normal = np.asarray(s.panel_normal(), np.float64)
            denom = float(np.dot(direction, normal))
            if denom > -1e-6:             # parallel, or the back of it
                continue
            t = float(np.dot(np.asarray(s.pos, np.float64)
                             - origin, normal)) / denom
            if t <= 0.0 or (best is not None and t >= best[0]):
                continue
            local = s.panel_uv(origin + direction * t)
            if local is not None:
                best = (t, s, local)
        if best is None:
            return False
        _t, screen, local = best
        data = dict(e.dict)
        data["pos"] = (int(local[0]), int(local[1]))
        if e.type == pygame.MOUSEMOTION:
            data["rel"] = (0, 0)
        handled = screen.send(pygame.event.Event(e.type, data))
        if handled and button and e.type in (pygame.MOUSEBUTTONDOWN,
                                             pygame.MOUSEBUTTONUP):
            # a click the picture took must not fire the action
            self.input.consume(button)
        return handled

    def ground_height(self, x, z):
        return 0.0

    def spawn_point(self):
        return (0.0, 0.0, 0.0), 0.0

    def attach_player(self, ent, pos=None, yaw=None, pitch=None):
        """Hand the camera to an object you created."""
        self.player = ent
        ent.lock_input = bool(self.lock_input)
        self.game.set_player(pos if pos is not None else ent.pos,
                             yaw if yaw is not None
                             else getattr(ent, "yaw", 0.0),
                             pitch if pitch is not None
                             else getattr(ent, "pitch", 0.0))
        return ent

    def on_enter(self):
        """Called every time play mode (re)starts this scene."""
        pos, yaw = self.spawn_point()
        if self.player is not None:
            self.attach_player(self.player, pos, yaw, 0.0)
        else:
            self.game.set_player(pos, yaw)
        rig = self.camera_rig
        if rig is not None and rig is not self.player:
            rig.pos = [pos[0], self.ground_height(pos[0], pos[2]), pos[2]]
            rig.yaw, rig.pitch = yaw, 0.0

    @property
    def eye(self):
        """Live camera position [x, y, z]."""
        if self.player is not None:
            return self.player.pos
        return self.game.eye

    def shake(self, amount=1.0, duration=0.35, freq=None, scale=None,
              roll=None):
        """Rattle the camera; `self.shake(0.3, 0.2)` is a footstep."""
        if self.active_camera is not None:
            return self.active_camera.shake(amount, duration, freq, scale,
                                            roll)
        fn = getattr(self.game, "shake", None)
        if fn is None:
            view = self.view
            return view.shake(amount, duration, freq, scale, roll) \
                if view is not None else 0.0
        return fn(amount, duration, freq, scale, roll)

    def look_at(self, target, damping=None, offset=None):
        """Aim the camera at a point, eased by `damping`."""
        view = self.view
        if view is None:
            return None
        if damping:
            view.damping = float(damping)
        return view.look_at_point(target, dt=getattr(self.game, "last_dt",
                                                     0.0),
                                  damping=damping, offset=offset)

    def follow(self, target, offset=None, damping=None):
        """Chase a point (or object) with a damped camera."""
        view = self.view
        if view is None:
            return None
        return view.set_follow(target, offset, damping)


class Scene2D(Scene):
    """A flat pixel world rendered through an orthographic camera."""

    kind = "2d"
    name = "scene2d"
    object_base = Object2D
    camera_class = Camera2D         # add_camera() builds ortho rigs

    world_size = (960.0, 540.0)     # design pixels; None = window pixels
    scale_mode = "fit"              # "fit" letterboxes, "expand" crops

    clear_color = (0.0, 0.0, 0.0)
    ambient = (1.0, 1.0, 1.0)       # the lit pass is never used here, but
    sun_col = (0.0, 0.0, 0.0)       # keep uniforms harmless if it is
    fog_near = 1.0e6                # fog is a 3D shader term; switch it off
    fog_far = 2.0e6

    def __init__(self, game, seed=7):
        super().__init__(game, seed=seed)
        w, h = game.screen.get_size()
        self.view2d = Camera2D(size=(w, h))
        # the default rig is a registered camera too
        self.view2d.name = "default"
        self.cameras["default"] = self.view2d
        self._center_default = None

    def _cams2d(self):
        """view2d plus every registered Camera2D, default rig first."""
        cams = [self.view2d]
        for cam in self.cameras.values():
            if isinstance(cam, Camera2D) and cam is not self.view2d:
                cams.append(cam)
        return cams

    def sync_view(self):
        """Match the ortho rigs to the window every frame (resize-proof)."""
        w, h = self.game.screen.get_size()
        dw, dh = self.world_size if self.world_size else (w, h)
        for cam in self._cams2d():
            cam.resize((w, h))
            if cam is self.view2d and self.world_size and cam.autofit:
                if self.scale_mode == "expand":
                    zoom = max(w / dw, h / dh)
                else:
                    zoom = min(w / dw, h / dh)
                cam.zoom = zoom
            if cam.center is None:
                cam.set_center((dw / 2.0, dh / 2.0))
        return self.view2d

    @property
    def view(self):
        """Active registered camera, else the scene's own ortho rig."""
        return self.active_camera or self.view2d

    def to_world(self, screen_pixel):
        """Window mouse position -> world pixel under the camera."""
        view = self.view
        if hasattr(view, "to_world"):
            return view.to_world(screen_pixel)
        return self.view2d.to_world(screen_pixel)

    def render(self, camera=None):
        self.sync_view()
        return self.renderer.render(self.view, self)

    def handle_event(self, e):
        return self.route_mouse(e)

    def route_mouse(self, e):
        """Feed mouse events to the objects above them."""
        if e.type not in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN,
                          pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL):
            return False
        # a wheel carries no position; read the pointer lazily
        pos = getattr(e, "pos", None)
        if pos is None:
            pos = pygame.mouse.get_pos()
        pos = self.to_world(pos)
        widgets = [o for o in self.objects if o.alive
                   and hasattr(o, "handle_event")]
        if e.type == pygame.MOUSEMOTION or e.type == pygame.MOUSEWHEEL:
            for obj in reversed(widgets):
                obj.handle_event(e, pos)
            return False
        for obj in reversed(widgets):
            if obj.handle_event(e, pos):
                return True
        return False


class SceneUI(Scene2D):
    """A screen of widgets: menus, HUDs, inventory grids, dialog."""

    kind = "ui"
    name = "menu"
    object_base = UIObject

    world_size = None               # the window is the world

    def default_pos(self):
        return (0.0, 0.0)

    @property
    def window_size(self):
        """Current window pixel size, for right/bottom anchoring."""
        return self.game.screen.get_size()

    def handle_event(self, e):
        return self.route_mouse(e)


def first_scene_class(module, base=Scene):
    """The Scene subclass a scenes/<name>.py file defines."""
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
