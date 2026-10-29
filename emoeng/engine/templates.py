"""Every file the engine writes when a project is made."""

import re

from .. import const
from . import model as models
from . import scenedoc

GITIGNORE_TEMPLATE = '''# Motion Engine: what a project generates, and never commits
__pycache__/
*.py[cod]

# the game's own slots - progress, not source
saves/

# build output and its caches
dist/
build/
*.spec
.ignored/

# editor scratch and OS noise
*.tmp
Thumbs.db
.DS_Store
'''

README_TEMPLATE = '''# {title}

A Motion Engine project: open this folder in the editor and press F5.

- `scenes/` holds one `.scene` per scene: its kind, the script that
  drives it, and what it places
- `objects/` holds one `.obj3d` (or `.obj2d`) per object: its script or
  node type, its placement and how it looks
- `entities/` holds one `.ent3d` (or `.ent2d`) per scripted thing with
  behaviour - a player, an NPC, an enemy - in the same shape as an
  object document
- `shaders/` holds one `.shader` per look the project wears, each paired
  with the class in `scripts/shaders/` that paints it
- `scripts/scenes/`, `scripts/objects/` and `scripts/entities/` hold that
  code, one class per file; `scripts/` itself holds whatever they share
- `models/` holds `.model3d` meshes and `.model2d` rigs, and is loaded by
  file stem like `textures/` and `audio/` are
- `saves/` is written by the game and is not part of the project
- `project.flig` says what the window is called, how big it starts and
  which scene runs first; `input.map.json` and `assets.json` (when a
  project has them) rebind keys and set import defaults

Made with {engine} {version}.
'''

# sidecar documents: a fresh one, and its purpose
INPUT_MAP_DOC = {
    "format": 1,
    "_help": "action -> binding names: keys ('w'), 'mouse:left', "
             "'wheel:up', 'joy0:button0', 'joy0:axis+1'. Empty means "
             "'use the engine default'.",
    "actions": {},
}
ASSET_MAP_DOC = {
    "format": 1,
    "_help": "how this project's assets are imported",
    "textures": {"filter": "linear", "wrap": "repeat", "mipmaps": True,
                 "tile": 0.0, "sheets": {}},
    "audio": {"gain": 1.0, "gains": {}},
}


# one template per creator entry; the docstring is the lesson
SCENE_TEMPLATE = '''"""Scene: edit me, then press F5 in the editor to play it.

`uses` names what this scene places, by stem: `objects/` holds the inert
ones as `.obj3d`/`.obj2d` and `entities/` the scripted ones as
`.ent3d`/`.ent2d`; the loader checks them on load and `self.spawn("prop",
pos)` resolves the script the document names, from either folder.
The player is one more entity: spawning `fe.Player3D` (or anything that
flags `is_player = True`) hands it the camera - WASD moves, mouse looks,
ESC pauses, all through named bindings the player can rebind. Add verbs
of your own with `actions = {"push": ["mouse:left", "joy0:button0"]}`
and poll `self.input.down("push")`. Extra angles are free: register one
with `self.add_camera(name="...")` (or `some_object.give_camera()`) and
cut to it with `self.set_active_camera("...")`.
`self.place_model` stamps a .model file, `self.add` takes generated
geometry, `self.add_light` throws a warm point light. Override
ground_height for terrain and spawn_point for where the player starts.
A look is a `shaders/` file this project owns: name the stems in `post`
and the frame is washed through them.
"""

import math

import pygame

import emoeng as fe
from emoeng.engine import meshes
from scripts.objects.prop import Prop


class Main(fe.Scene3D):
    name = "main"
    uses = ("prop",)

    clear_color = (0.035, 0.040, 0.060)
    fog_color = (0.045, 0.050, 0.075)
    fog_near = 18.0
    fog_far = 95.0
    ambient = (0.20, 0.21, 0.26)
    sun_dir = (0.4, 0.8, 0.3)
    sun_col = (0.22, 0.20, 0.24)
    # a scene's looks are its own shader files

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
        # the player: an object like any other
        self.player = self.spawn(fe.Player3D, pos=(0.0, 0.0, 9.0),
                                 move_speed=(6.0, 11.0),
                                 world_radius=60.0)
        # a parked wide shot to cut to later

    def update(self, dt):
        super().update(dt)
        self.fire["color"] = (1.0, 0.45 + 0.15 * math.sin(self.t * 9.0),
                              0.18)

    def spawn_point(self):
        return (0.0, 0.0, 9.0), 0.0

    def status(self):
        return [self.name, "emoeng project"]

    def overlay(self, screen):
        # the keymap's own words, so hints never go stale
        fe.ui.text(screen, self.game.fonts["small"],
                   self.game.control_hint(), (14, 12))
'''

OBJECT_TEMPLATE = '''"""Object3D: a prop scenes place, and that can copy itself.

Scene side:

    from scripts.objects.prop import Prop
    self.spawn(Prop, (0.0, 1.2, 0.0))     # or self.spawn("prop", pos)

The document side (objects/prop.object) is what the editor writes when
you drag this prop around, and it may also override `model`, `texture`
and `color`; `spawn(..., look={...})` does the same from code. Both land
in `self.look` before build(), so the lines below read them with a
fallback - that is where a script decides what its document may change.

`clone_attrs` lists what clone() carries over, so
`prop.clone((2, 1.2, 0))` builds a second Prop that knows it is a copy:
is_clone, clone_of, root, depth and lineage all report the relationship.
Objects can also spawn other objects with `self.spawn(...)` in build() or
update(dt).
"""

import math

import emoeng as fe
from emoeng.engine import meshes


class Prop(fe.Object3D):
    name = "prop"
    uses = ()                          # objects this one spawns
    clone_attrs = ("size", "tint")     # what clone() copies from the source

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 size=1.0, tint=(1.0, 0.72, 0.35)):
        super().__init__(scene, pos, yaw, scale)
        self.size = float(size)
        self.tint = tint

    def build(self):
        look = self.look if isinstance(self.look, dict) else {}
        self.col = look.get("color") or self.tint
        texture = look.get("texture")
        model = look.get("model")
        self.shape = None
        if model:
            # a `models/<name>.model`; the texture repaints it whole
            self.model_object(model, tint=self.col, texture=texture)
            return
        self.shape = self.dynamic(self._mesh(),
                                  texture=texture or "grid")

    def _mesh(self):
        return meshes.box(centre=self.pos, size=(0.6,) * 3, col=self.col)

    def update(self, dt):
        super().update(dt)
        if self.shape is None:
            return                     # a model keeps its own place
        bob = 0.18 * math.sin(self.t * 1.8)
        self.shape.update(meshes.box(
            centre=(self.pos[0], self.pos[1] + bob, self.pos[2]),
            size=(0.6,) * 3, col=self.col))
'''

OBJECT2D_TEMPLATE = '''"""Sprite: a 2D object, one quad of pixels in a 2D scene.

Scene side (2D classes are imported directly, not spawned by stem):

    from scripts.objects.gem import Sprite
    self.spawn(Sprite, (480.0, 260.0), texture="cloth")

`size` is world pixels and `anchor` says which fraction of the box sits
on `pos`. `texture` is a textures/ file stem ("cloth"), a colour
("#203040") or "white"; a sprite sheet is `grid=(cols, rows)` plus
`set_frame(n)` / `animate(fps)` after the spawn.

The document (objects/gem.object) may override `texture` and `color`,
and the editor writes `pos` there when you drag the sprite. They land in
`self.look` before build(), which is why build() below reads them.
"""

import emoeng as fe


class Sprite(fe.Object2D):
    name = "sprite"
    clone_attrs = ("size", "texture", "grid", "anchor")

    def __init__(self, scene, pos=(0.0, 0.0), size=(64.0, 64.0),
                 texture="white", col=(1.0, 1.0, 1.0), rot=0.0,
                 grid=(1, 1), anchor=(0.5, 0.5), tag=None):
        super().__init__(scene, pos=pos, size=size, texture=texture,
                         col=col, rot=rot, grid=grid, anchor=anchor,
                         tag=tag)

    def build(self):
        look = self.look if isinstance(self.look, dict) else {}
        if look.get("texture") or look.get("color"):
            self.set(texture=look.get("texture"), col=look.get("color"))
        super().build()
'''

UI_OBJECT_TEMPLATE = '''"""Widget: a clickable panel in a UI scene.

Scene side (UI classes are imported directly):

    from scripts.objects.button import Widget
    self.spawn(Widget, (640.0, 360.0), text="Play")

A UI scene routes hover, press and click to `handle_event` for you, so a
widget only has to say what its click does: override `on_click`, or hand
`action=` a callable at the spawn. `color`, `hover_color`, `press_color`,
`text_color` and `texture` all take any spelling of a colour ("fog",
"#1b2130", (0.2, 0.3, 0.4)).

The document (objects/button.object) may override `color`; the editor
writes `pos` there when you drag the widget.
"""

import emoeng as fe


class Widget(fe.UIObject):
    name = "widget"
    clone_gap = (0.0, 40.0)

    def __init__(self, scene, pos=(0.0, 0.0), size=(200.0, 44.0),
                 text="Button", color=(0.16, 0.42, 0.78), font_size=18,
                 action=None, tag=None, **kw):
        super().__init__(scene, pos=pos, size=size, text=text, color=color,
                         font_size=font_size, action=action, tag=tag, **kw)

    def build(self):
        look = self.look if isinstance(self.look, dict) else {}
        if look.get("color"):
            self.set(color=look.get("color"))
        super().build()

    def on_click(self):
        # a widget is a button: scene switch, toggle, sound
        pass
'''


PLAYER3D_TEMPLATE = '''"""Player3D: a spawnable first-person entity that owns a camera.

Scene side:

    from scripts.entities.player import Player
    self.player = self.spawn(Player, pos=(0.0, 0.0, 6.0))

The player is Godot-style: it polls the bound actions itself,
integrates its own pos/yaw/pitch and publishes them onto the camera it
drives, so `scene.set_active_camera("...")` can cut to a parked angle
without the player hijacking it. The knobs below are class attributes -
override them here, or set them per instance with
`self.spawn(Player, pos, move_speed=(7.0, 14.0))`.

Third-person is a rig, not a rewrite:

    self.player.give_camera(follow=True, offset=(0.0, 6.0, -10.0))
    self.player.first_person = False
"""

import emoeng as fe


class Player(fe.Player3D):
    name = "player3d"
    move_speed = (6.0, 11.0)           # (walk, run) m/s
    eye_height = 1.7
    movement = "walk"                  # "walk" | "fly"
    world_radius = 60.0                # hard clamp from origin; 0 = off

    def build(self):
        # a visible body for when a chase rig takes over
        pass
'''

PLAYER2D_TEMPLATE = '''"""Player2D: a steered sprite entity that drags the 2D view along.

Scene side (2D classes are imported directly, not spawned by stem):

    from scripts.entities.player import Player
    self.player = self.spawn(Player, (480.0, 270.0),
                             size=(96.0, 24.0), texture="cloth")

Same action vocabulary as the 3D player - arrows/WASD move, `run`
sprints; the ortho camera stays centred on me and the wheel zooms it
(`wheel_zoom = False` to keep it still). `bounds` defaults to the
scene's `world_size`; pass a (w, h) box of your own or 0 to roam free.
"""

import emoeng as fe


class Player(fe.Player2D):
    name = "player2d"
    move_speed = 320.0                 # world pixels per second
    run_multiplier = 1.8
    wheel_zoom = True
    follows_view = True                # keep my camera centred on me
'''

CAMERA3D_TEMPLATE = '''"""Camera3D: an object whose only job is to be a view.

Scene side:

    self.cam = self.spawn("camera")     # by file stem
    self.cam.cut()                      # make it the active view

The object registers a camera on the scene (`scene.add_camera`), keeps
that camera on its own pos/yaw/pitch every frame, and - while `current`
is True - takes the view as soon as it is built. Set `current = False`
to park an angle and cut to it later with `set_active_camera(name)`;
`set_active_camera(None)` hands the view back to the player.

No geometry is built: the eye is the object, and a camera you can see is
a prop wearing a camera (see `Object3D.give_camera`).
"""

import emoeng as fe


class Camera(fe.Object3D):
    name = "camera3d"
    fov = 68.0
    pitch = 0.0                    # radians; positive looks up
    current = True                 # take the view when built
    rig_name = None                # None: the scene names it cam1, cam2...

    def build(self):
        self.rig = self.scene.add_camera(name=self.rig_name, fov=self.fov)
        self.publish()
        if self.current:
            self.cut()

    def publish(self):
        """Push my transform onto the camera; my pos is the eye."""
        cam = self.rig
        cam.eye = [self.pos[0], self.pos[1], self.pos[2]]
        cam.yaw = float(self.yaw)
        cam.pitch = float(self.pitch)
        return cam

    def cut(self):
        """Render through me from now on."""
        return self.scene.set_active_camera(self.rig)

    def update(self, dt):
        super().update(dt)
        self.publish()
'''

CAMERA2D_TEMPLATE = '''"""Camera2D: a view with no picture - it only draws the world.

Scene side:

    self.cam = self.spawn("camera2d")
    self.cam.cut()                  # or self.set_active_camera("cam1")

It builds nothing on purpose: a camera is invisible, so the sprite half
of Object2D is simply never made. `pos` is the point it keeps centred
and `zoom` the ortho zoom (1.0 is 1:1, bigger is closer).

`current = False` registers the angle without taking the view; that is
how a scene keeps a second shot ready and cuts to it on demand.
"""

import emoeng as fe


class Camera(fe.Object2D):
    name = "camera2d"
    zoom = 1.0
    current = True
    rig_name = None

    def build(self):
        # no super().build(): there is no quad to make
        self.rig = self.scene.add_camera(name=self.rig_name,
                                        center=self.pos, zoom=self.zoom)
        if self.current:
            self.cut()

    def cut(self):
        return self.scene.set_active_camera(self.rig)

    def update(self, dt):
        super().update(dt)
        self.rig.set_center(self.pos)
'''

SCREEN3D_TEMPLATE = '''"""Screen3D: a panel in a 3D scene showing another scene.

Scene side:

    self.tv = self.spawn("screen")      # by file stem
    self.tv.show("menu")                # switch what it displays

The scene it shows comes from the document's `showing` (the editor
writes it), from `channel` below, or from `show(name)`. A screen owns a
second renderer, so the nested scene really runs - its script ticks, its
player moves, its post chain applies - and the panel draws the result.

Every knob is here to be turned from this script or from code:

    tv.set_brightness(0.6)         # dim the picture, 0..1
    tv.set_tint("#88bbff")         # pull it cold
    tv.set_shape("round")          # rect | round | circle | soft
    tv.set_audio("emitter", gain=0.8, reach=12.0)    # or "global"
    tv.toggle()                    # off stops the nested scene
    tv.overlay = paint             # overlay(picture, screen) -> None
    tv.send(event)                 # forward input, if takes_input

... and `tv.set_post("scanlines")` names a `screen` shader this project
owns in `shaders/`, which the panel's own picture is washed through.

`audio_mode="emitter"` plays the nested scene's sound from where the
panel hangs, fading out by `reach`; "global" plays it flat.

`refresh` caps the pictures a second the panel paints (0 means every
frame; the nested scene's simulation always keeps running), and
`cull_dist` lets a panel far behind the player rest between looks.

In the editor's Edit mode nothing steps, but the viewport warms one
frame per screen, so the panel shows its picture while you place it.
"""

import emoeng as fe


class Screen(fe.Screen3D):
    name = "screen3d"
    pixels = (320, 180)            # the picture's own resolution
    shape = "rect"
    brightness = 1.0
    tint = (1.0, 1.0, 1.0)
    post = ()
    takes_input = False
    audio_mode = "global"          # "global" | "emitter"
    gain = 1.0
    reach = 20.0                   # metres before an emitter goes quiet
    refresh = 30.0                 # pictures per second; 0 = every frame
    cull_dist = 60.0               # metres past which the picture rests
    channel = None                 # a scene to show with no document

    def __init__(self, scene, pos=(0.0, 2.0, 6.0), yaw=0.0, scale=1.0,
                 size=(3.2, 1.8), glow=False, tag=None, **kw):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, size=size,
                         glow=glow, tag=tag, **kw)

    def build(self):
        super().build()
        if self.showing is None and self.channel:
            self.show(self.channel)
'''

SCREEN2D_TEMPLATE = '''"""Screen2D: a sprite in a 2D or UI scene showing another scene.

Scene side:

    self.tv = self.spawn("screen2d", (480.0, 270.0))
    self.tv.show("menu")

`size` is world pixels and `pixels` is the resolution the picture is
rendered at, so a small panel costs a small frame. The picture is drawn
on the HUD layer by default, which keeps the scene's own lights from
dimming the thing you are looking through; `blend="alpha"` puts it back
inside them.

Same knobs as Screen3D - `show`, `set_brightness`, `set_tint`,
`set_shape`, `set_post`, `set_audio`, `toggle`, `send`, `overlay`,
`refresh`, `cull_dist` - and the scene it shows comes from the
document's `showing` or `channel`.
"""

import emoeng as fe


class Screen(fe.Screen2D):
    name = "screen2d"
    pixels = (320, 180)
    shape = "rect"
    brightness = 1.0
    tint = (1.0, 1.0, 1.0)
    post = ()
    takes_input = False
    audio_mode = "global"
    gain = 1.0
    reach = 20.0
    refresh = 30.0
    cull_dist = 60.0
    channel = None

    def __init__(self, scene, pos=(480.0, 270.0), size=(320.0, 180.0),
                 blend="hud", tag=None, **kw):
        super().__init__(scene, pos=pos, size=size, blend=blend, tag=tag,
                         **kw)

    def build(self):
        super().build()
        if self.showing is None and self.channel:
            self.show(self.channel)
'''

ENTITY3D_TEMPLATE = '''"""Entity3D: an NPC/enemy with AI, health, and hitboxes.

Scene side:

    from scripts.entities.enemy import Enemy
    self.spawn(Enemy, pos=(0.0, 0.0, 0.0), ai_type="aggro")

A document for me lives in `entities/` as `<name>.ent3d`, beside the
players, NPCs and enemies, because I am a scripted thing with behaviour.

The entity has built-in AI types:
- "none": no AI, just sits there
- "follow": follows a target (player or another entity)
- "patrol": patrols between waypoints (set in ai_config)
- "wander": wanders randomly
- "aggro": chases and attacks the player when in range

Health and damage:
- health/max_health: current and maximum health
- take_damage(amount, source): apply damage
- heal(amount): restore health
- on_hit(source): called when damaged
- on_death(source): called when killed

Hitbox:
- hitbox_shape: "box", "sphere", or "capsule"
- hitbox_half: half-extents for box (x, y, z)
- hitbox_radius/hitbox_height: for sphere/capsule

Advanced:
- team: "player", "enemy", "neutral", "friendly"
- aggro_range/deaggro_range: when to chase/lose interest
- attack_range/attack_damage/attack_cooldown: combat settings

The blocks palette reaches all of that through one call per knob -
`set_health`, `set_ai`, `set_team`, `set_aggro_range`, `set_attack`,
`set_move_speed`, `set_hitbox` - each of which returns me, so a script
written by blocks reads back as blocks. `take_damage(n, source)` and
`heal(n)` move the health bar, `is_dead()` and `distance_to(other)` read
it, and `get_node(...)`, `queue_free()` and `connect/emit` work the way
Godot names them.
"""

import math
import emoeng as fe
from emoeng.engine import meshes


class Enemy(fe.Entity3D):
    name = "enemy"
    health = 100.0
    max_health = 100.0
    ai_type = "aggro"
    ai_config = {}
    hitbox_shape = "box"
    hitbox_half = (0.5, 1.0, 0.5)
    team = "enemy"
    aggro_range = 15.0
    deaggro_range = 30.0
    attack_range = 2.0
    attack_damage = 15.0
    attack_cooldown = 1.5
    move_speed = (3.0, 8.0)

    def build(self):
        # A simple box body
        self.add(meshes.box(centre=(0, 1, 0), size=(1.0, 2.0, 1.0),
                            col=(0.8, 0.2, 0.2)), texture="white")

    def on_hit(self, source):
        # Flash red when hit
        pass

    def on_death(self, source):
        # Drop loot, play death effect, etc.
        pass
'''

ENTITY2D_TEMPLATE = '''"""Entity2D: a 2D NPC/enemy with AI, health, and hitboxes.

Scene side (2D classes are imported directly):

    from scripts.entities.enemy2d import Enemy2D
    self.spawn(Enemy2D, (400.0, 300.0), ai_type="aggro")

My document is `entities/<name>.ent2d`.

Same AI types as Entity3D: "none", "follow", "patrol", "wander", "aggro"

Health and damage work the same way.

Hitbox:
- hitbox_shape: "rect" or "circle"
- hitbox_radius: for circle
- hitbox_size: (w, h) for rect

Advanced behavior mirrors Entity3D but in 2D world pixels, and its
setters (`set_health`, `set_ai`, `set_hitbox2d`, ...) are the same calls.
"""

import emoeng as fe


class Enemy2D(fe.Entity2D):
    name = "enemy2d"
    health = 50.0
    max_health = 50.0
    ai_type = "aggro"
    ai_config = {}
    hitbox_shape = "rect"
    hitbox_size = (32.0, 48.0)
    team = "enemy"
    aggro_range = 250.0
    deaggro_range = 500.0
    attack_range = 40.0
    attack_damage = 10.0
    attack_cooldown = 1.0
    move_speed = 80.0

    def build(self):
        look = self.look if isinstance(self.look, dict) else {}
        col = look.get("color") or (0.8, 0.2, 0.2)
        texture = look.get("texture") or "white"
        self.set(texture=texture, col=col)
        super().build()

    def on_hit(self, source):
        pass

    def on_death(self, source):
        pass
'''

SCRIPT_TEMPLATE = '''"""Shared helpers for this project.

Import them from a scene with `from scripts import helpers`.
"""


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value
'''

SCENE2D_TEMPLATE = '''"""2D scene: sprites on a pixel plane, edit me, F5.

Coordinates are world pixels, origin top-left, x right, y down. The
`world_size` box is the design resolution; the camera scales it to the
window. Sprites are fe.Object2D subclasses, imported here and spawned
with `self.spawn(Sprite, (x, y))`; `texture` is a textures/ file stem
and `grid=(cols, rows)` turns it into a sprite sheet.

The player is one too: `fe.Player2D` steers with the same actions,
keeps the camera centred on itself and wheel-zooms it. Register a
second angle with `self.add_camera(name=...)` and cut between views
with `self.set_active_camera(name)` - or `set_active_camera(None)` to
hand the view back to the player.
"""

import emoeng as fe
from emoeng.engine import meshes


class Main(fe.Scene2D):
    name = "main2d"
    world_size = (960.0, 540.0)
    clear_color = (0.05, 0.06, 0.10)

    def setup(self):
        # a flat backdrop, queued into the static alpha batch
        self.add(meshes.rect2d((480, 270), (960, 540),
                               col=(0.10, 0.16, 0.26)),
               texture="white", blend="alpha")
        self.player = self.spawn(fe.Player2D, (480.0, 450.0),
                                 size=(120.0, 16.0), col=(0.9, 0.9, 1.0))
        # a parked wide shot, ready whenever you cut to it

    def status(self):
        return [self.name, "arrows move the paddle, wheel zooms"]
'''

SCENE_UI_TEMPLATE = '''"""UI scene: widgets on the window, edit me, F5.

The world is the window in pixels. Spawn fe.UIObject widgets (or
subclasses); hover, press and click are routed for you - pass a
callable as `action`, or override `on_click` on a subclass.
"""

import emoeng as fe


class Main(fe.SceneUI):
    name = "menu"
    clear_color = (0.07, 0.08, 0.12)

    def setup(self):
        w, h = self.window_size
        self.title = self.spawn(fe.UIObject, (w / 2.0, h * 0.3),
                                size=(360.0, 64.0), text="hello",
                                color=(0.15, 0.35, 0.65), font_size=32)
        self.quit = self.spawn(fe.UIObject, (w / 2.0, h * 0.55),
                               size=(200.0, 44.0), text="Quit",
                               action=self.game.quit)

    def status(self):
        return [self.name, "click Quit"]
'''

# the editor's New Object entries, in one table
OBJECT_PRESETS = {
    "new_object": ("object3d", OBJECT_TEMPLATE, "prop", "New 3D Object",
                   "Adds scripts/objects/<name>.py and <name>.obj3d - a "
                   "prop a 3D scene spawns"),
    "new_object_2d": ("object2d", OBJECT2D_TEMPLATE, "sprite",
                      "New 2D Object",
                      "Adds scripts/objects/<name>.py and <name>.obj2d - "
                      "a sprite a 2D scene spawns"),
    "new_ui_object": ("ui", UI_OBJECT_TEMPLATE, "button", "New UI Object",
                      "Adds scripts/objects/<name>.py and <name>.obj2d - "
                      "a widget a UI scene places"),
    "new_player_3d": ("player3d", PLAYER3D_TEMPLATE, "player",
                      "New Player 3D",
                      "Adds scripts/entities/<name>.py and <name>.ent3d - "
                      "a Player3D that owns the camera"),
    "new_player_2d": ("player2d", PLAYER2D_TEMPLATE, "player2d",
                      "New Player 2D",
                      "Adds scripts/entities/<name>.py and <name>.ent2d - "
                      "a Player2D a 2D scene drives"),
    "new_entity_3d": ("entity3d", ENTITY3D_TEMPLATE, "enemy",
                      "New Entity 3D",
                      "Adds scripts/entities/<name>.py and <name>.ent3d - "
                      "an Entity3D with AI, health, hitboxes for "
                      "NPCs/enemies"),
    "new_entity_2d": ("entity2d", ENTITY2D_TEMPLATE, "enemy2d",
                      "New Entity 2D",
                      "Adds scripts/entities/<name>.py and <name>.ent2d - "
                      "an Entity2D with AI, health, hitboxes for "
                      "NPCs/enemies"),
    "new_camera_3d": ("camera3d", CAMERA3D_TEMPLATE, "camera",
                      "New Camera 3D",
                      "Adds scripts/objects/<name>.py and <name>.obj3d - "
                      "a view with no body"),
    "new_camera_2d": ("camera2d", CAMERA2D_TEMPLATE, "camera2d",
                      "New Camera 2D",
                      "Adds scripts/objects/<name>.py and <name>.obj2d - "
                      "a 2D view with no sprite"),
    "new_screen_3d": ("screen3d", SCREEN3D_TEMPLATE, "screen",
                      "New Screen 3D",
                      "Adds scripts/objects/<name>.py and <name>.obj3d - "
                      "a panel that shows another scene"),
    "new_screen_2d": ("screen2d", SCREEN2D_TEMPLATE, "screen2d",
                      "New Screen 2D",
                      "Adds scripts/objects/<name>.py and <name>.obj2d - "
                      "a sprite that shows another scene"),
}

# the same for scenes: script plus its `.scene`
SCENE_PRESETS = {
    "new_scene": ("scene3d", SCENE_TEMPLATE, "scene1", "New 3D Scene",
                  "Adds scripts/scenes/<name>.py and <name>.scene - a "
                  "Scene3D world"),
    "new_scene_2d": ("scene2d", SCENE2D_TEMPLATE, "scene2d",
                     "New 2D Scene",
                     "Adds scripts/scenes/<name>.py and <name>.scene - a "
                     "Scene2D sprite screen"),
    "new_scene_ui": ("sceneui", SCENE_UI_TEMPLATE, "menu", "New UI Scene",
                     "Adds scripts/scenes/<name>.py and <name>.scene - a "
                     "SceneUI of widgets"),
}


# the stock looks, as files a project owns
SHADERS = {
    "invert": (
        "screen",
        {"amount": 1.0},
        '''"""push the frame towards its own negative"""

import emoeng as fe


class Invert(fe.Shader):
    name = "invert"
    mode = "screen"
    knobs = {"amount": 1.0}

    def frag(self, g):
        amount = g.clamp(self.amount, 0.0, 1.0)
        g.out = g.mix(g.color, 1.0 - g.color, amount)
'''),
    "grey": (
        "screen",
        {},
        '''"""drop the colour out of the frame and keep the light"""

import emoeng as fe


class Grey(fe.Shader):
    name = "grey"
    mode = "screen"
    knobs = {}

    def frag(self, g):
        tone = g.grey(g.color)
        g.out = g.vec3(tone, tone, tone)
'''),
    "posterize": (
        "screen",
        {"steps": 4.0, "grain": 0.5},
        '''"""few levels of colour, scattered by a per-pixel dither"""

import emoeng as fe


class Posterize(fe.Shader):
    name = "posterize"
    mode = "screen"
    knobs = {"steps": 4.0, "grain": 0.5}

    def frag(self, g):
        level = g.max(self.steps, 2.0)
        grain = g.noise(g.pixel, 1.0) - 0.5
        tone = g.clamp(g.color + grain * self.grain / level, 0.0, 1.0)
        g.out = g.floor(tone * level) / (level - 1.0)
'''),
    "vignette": (
        "screen",
        {"amount": 0.55, "soft": 0.6},
        '''"""wash the frame towards black out at its edges"""

import emoeng as fe


class Vignette(fe.Shader):
    name = "vignette"
    mode = "screen"
    knobs = {"amount": 0.55, "soft": 0.6}

    def frag(self, g):
        ring = g.length(g.uv - 0.5)
        shade = g.smoothstep(self.soft, 1.0, ring * 2.0)
        dark = g.mix(1.0, 1.0 - self.amount, g.clamp(shade, 0.0, 1.0))
        g.out = g.color * dark
'''),
    "scanlines": (
        "screen",
        {"amount": 0.35, "lines": 90.0},
        '''"""darken every other row, the way a tube monitor did"""

import emoeng as fe


class Scanlines(fe.Shader):
    name = "scanlines"
    mode = "screen"
    knobs = {"amount": 0.35, "lines": 90.0}

    def frag(self, g):
        row = g.dot(g.pixel, g.vec2(0.0, 1.0))
        high = g.dot(g.size, g.vec2(0.0, 1.0))
        band = g.fract(row * self.lines / g.max(high, 1.0))
        dim = g.mix(1.0, 1.0 - self.amount, g.step(0.5, band))
        g.out = g.color * dim
'''),
    "filmgrain": (
        "screen",
        {"amount": 0.12, "dots": 600.0},
        '''"""speckle the frame with its own per-pixel hash"""

import emoeng as fe


class FilmGrain(fe.Shader):
    name = "filmgrain"
    mode = "screen"
    knobs = {"amount": 0.12, "dots": 600.0}

    def frag(self, g):
        speck = g.noise(g.uv * self.dots + g.seed, 1.0)
        g.out = g.clamp(g.color + (speck - 0.5) * self.amount,
                        0.0, 1.0)
'''),
    "ripple": (
        "screen",
        {"amount": 0.012, "speed": 1.6, "scale": 22.0},
        '''"""bend the frame in rings that travel out from its centre"""

import emoeng as fe


class Ripple(fe.Shader):
    name = "ripple"
    mode = "screen"
    knobs = {"amount": 0.012, "speed": 1.6, "scale": 22.0}

    def frag(self, g):
        ring = g.length(g.uv - 0.5)
        wave = g.sin(ring * self.scale - g.time * self.speed)
        g.out = g.tex(g.uv + wave * self.amount)
'''),
    "uvscroll": (
        "uv",
        {"speed": 0.35, "tilt": 0.0},
        '''"""slide a mesh's own sheet across it, forwards and sideways"""

import emoeng as fe


class UvScroll(fe.Shader):
    name = "uvscroll"
    mode = "uv"
    knobs = {"speed": 0.35, "tilt": 0.0}

    def frag(self, g):
        moved = g.wmuv(g.uv, g.vec2(self.speed, self.tilt), 1.0)
        g.out = g.tex(moved)
'''),
    "tintpulse": (
        "uv",
        {"amount": 0.5, "speed": 1.2},
        '''"""breathe a cycling hue over a mesh, on no clock but its own"""

import emoeng as fe


class TintPulse(fe.Shader):
    name = "tintpulse"
    mode = "uv"
    knobs = {"amount": 0.5, "speed": 1.2}

    def frag(self, g):
        beat = 0.5 + 0.5 * g.sin(g.time * self.speed)
        glow = g.hue(g.fract(g.time * self.speed * 0.1))
        g.out = g.mix(g.color, glow,
                      g.clamp(self.amount * beat, 0.0, 1.0))
'''),
    "brushed": (
        "texture",
        {"amount": 0.3, "lines": 40.0},
        '''"""stripe a sheet once, so the look is in the picture itself"""

import emoeng as fe


class Brushed(fe.Shader):
    name = "brushed"
    mode = "texture"
    knobs = {"amount": 0.3, "lines": 40.0}

    def frag(self, g):
        row = g.dot(g.pixel, g.vec2(0.0, 1.0))
        band = g.noise(g.vec2(0.0, row), self.lines)
        g.out = g.clamp(g.color * (1.0 + (band - 0.5) * self.amount),
                        0.0, 1.0)
'''),
}

# what New Shader offers, in chooser order
SHADER_PRESETS = {
    "invert": ("screen", "invert", "Invert",
               "Push the frame towards its own negative"),
    "grey": ("screen", "grey", "Grey",
             "Drop the colour and keep the light"),
    "posterize": ("screen", "posterize", "Posterize",
                  "Few levels of colour, dithered per pixel"),
    "vignette": ("screen", "vignette", "Vignette",
                 "Wash the frame to black at its edges"),
    "scanlines": ("screen", "scanlines", "Scanlines",
                  "Darken every other row, like a tube monitor"),
    "filmgrain": ("screen", "filmgrain", "Film Grain",
                  "Speckle the frame with moving noise"),
    "ripple": ("screen", "ripple", "Ripple",
               "Bend the frame in rings from its centre"),
    "uvscroll": ("uv", "uvscroll", "UV Scroll",
                 "Slide this mesh's own sheet across it"),
    "tintpulse": ("uv", "tintpulse", "Tint Pulse",
                  "Breathe a cycling hue over this mesh"),
    "brushed": ("texture", "brushed", "Brushed",
                "Stripe the sheet once and keep the result"),
}


def shader_class_name(stem):
    """The class name a shader script should carry."""
    parts = [w for w in re.split(r"[^0-9a-zA-Z]+", str(stem)) if w]
    out = "".join(w[:1].upper() + w[1:] for w in parts)
    return out if out.isidentifier() and out[:1].isalpha() else "Custom"


def shader_source(key, stem):
    """A stock shader's whole script, renamed for a new stem."""
    row = SHADERS.get(str(key))
    if row is None:
        return ""
    name = str(stem)
    source = re.sub(r"^class \w+\(", f"class {shader_class_name(name)}(",
                    row[2], count=1, flags=re.MULTILINE)
    return re.sub(r'^(\s*)name = "[^"]*"', rf'\1name = "{name}"',
                  source, count=1, flags=re.MULTILINE)


# file-free assets, so a fresh folder has something to place
MODELS = {
    "box": ("box", 1.0, None),
    "crate": ("box", 1.0, "#8a5a2c"),
    "pillar": ("cylinder", 1.0, "#9a9ea6"),
    "wedge": ("wedge", 1.0, "#4c6f9a"),
    "orb": ("sphere", 0.8, "#d8b26a"),
    "sprite": ("plane", 1.0, None),
}

# named colours a scene or document may say
PALETTE = {
    "ink": "#101420",
    "slate": "#1b2130",
    "steel": "#6f7f93",
    "stone": "#96948e",
    "sand": "#d6be8c",
    "rust": "#94502c",
    "moss": "#60964c",
    "water": "#3c7ad6",
    "sky": "#88bbff",
    "fire": "#ff8c28",
    "gold": "#e2b450",
    "bone": "#e8e4d8",
    "plum": "#9650be",
    "mint": "#46c8d2",
}


def make_model(stem):
    """One stock model, built from `MODELS` and ready to save."""
    row = MODELS.get(str(stem))
    if row is None:
        return None
    kind, size, tint = row
    return models.new_model(kind, size, name=stem, tint=tint)


# file-free maps, so a new project has one to open in the map editor.
# Each row is (floor across, wall up); a wall is a box of that same size.
MAPS = {
    "room": (8.0, 3.0),
}


def make_map(stem):
    """One stock map: a floor and two walls, each its own object.

    A map is drawn and lit one object at a time, so the starter is split
    that way rather than being one merged shell.
    """
    row = MAPS.get(str(stem))
    if row is None:
        return None
    wide, high = float(row[0]), float(row[1])
    m = models.Model(str(stem))
    m.texture = "ground"
    parts = []
    m.append(models.plane_model(wide))
    parts.append(("floor", list(range(len(m.tris)))))
    for name, off in (("wall_w", (-(wide - high) / 2.0, 0.0, 0.0)),
                      ("wall_n", (0.0, 0.0, -(wide - high) / 2.0))):
        before = len(m.tris)
        m.append(models.box_model(high), offset=off)
        parts.append((name, list(range(before, len(m.tris)))))
    m.objects = [{"name": name, "faces": faces, "texture": None,
                  "painted": False, "lightmap": None}
                 for name, faces in parts]
    m.align_objects()
    return m


# the three starting scenes and the objects they place
START3D_SCENE = '''"""Main: a floor, one prop and a first-person player.

This is a starting point, not a level. The floor is one sheet the engine
paints, the prop is `objects/prop.obj3d` - which this scene's document
places, so the Project View shows it under the scene - and the player
walks and looks with the bound actions, which a player can rebind.

The player starts at +Z facing back down the floor (`yaw=math.pi`), so
the prop and the fire are in front of the camera on the first frame;
`spawn_point()` is what play mode and the editor's Edit view both obey.

F5 plays it. Drag the prop in Edit mode and the collision box its own
document files under it moves along, because it was placed as its child.

Add a game from here: `self.spawn(...)` more objects, `self.add_light`
a lamp, `self.add(meshes...)` walls, `self.place_model(...)` a mesh from
`models/`, or a look of your own in `shaders/` named in `post`.
"""

import math

import emoeng as fe
from emoeng.engine import meshes


class Main(fe.Scene3D):
    name = "main"
    uses = ("prop",)

    clear_color = (0.05, 0.06, 0.09)
    fog_color = (0.06, 0.07, 0.11)
    fog_near = 24.0
    fog_far = 120.0
    ambient = (0.34, 0.35, 0.40)
    sun_dir = (0.4, 0.9, 0.3)
    sun_col = (0.50, 0.48, 0.46)

    def setup(self):
        # `grid` is built in; a new project has a floor
        self.renderer.texture("grid", fe.proctex.grid(128, 8))
        self.add(meshes.plane(size=(40, 40), seg=8), texture="grid")
        self.add_light((0.0, 2.6, -4.0), "fire", radius=9.0)
        self.player = self.spawn(fe.Player3D, pos=(0.0, 0.0, 6.0),
                                 yaw=math.pi, move_speed=(5.0, 9.0),
                                 world_radius=19.0)

    def spawn_point(self):
        return (0.0, 0.0, 6.0), math.pi

    def status(self):
        return [self.name, "emoeng project"]

    def overlay(self, screen):
        # the keymap's own words, so hints never go stale
        fe.ui.text(screen, self.game.fonts["small"],
                   self.game.control_hint(), (14, 12))
'''

START3D_PROP = '''"""Prop: the box a scene places, and the shape you walk into.

Its document (objects/prop.obj3d) files a Collision3D under it, so one
placement brings a picture and a shape along together, and dragging the
prop drags both. `self.look` is what the document said about where this
one sits and how it looks; reading it in build() is how a script honours
that, because geometry is stamped once and cannot be moved afterwards.
"""

import emoeng as fe
from emoeng.engine import meshes


class Prop(fe.Object3D):
    name = "prop"
    uses = ()
    clone_attrs = ("tint",)

    tint = (0.72, 0.55, 0.32)          # the colour of the box's faces

    def build(self):
        look = self.look if isinstance(self.look, dict) else {}
        # the base sits on the ground; lift the box halfway
        centre = (self.pos[0], self.pos[1] + 0.5, self.pos[2])
        self.add(meshes.box(centre=centre, size=(1.0, 1.0, 1.0),
                            col=look.get("color") or self.tint),
                 texture=look.get("texture") or "grid")
'''

# the prop's branch: a solid box on the same ground
_PROP3D_NODES = (
    {"id": "Collision3D#0",
     "type": "collision3d",
     "pos": [0.0, 0.5, 0.0],
     "knobs": {"shape": "box", "half": [0.55, 0.55, 0.55]}},
)

START2D_SCENE = '''"""Main: a flat arena, one sprite, one steered player.

World pixels: origin top-left, x right, y down. `world_size` is the
design resolution the camera scales to the window. The player steers
with arrows or WASD (`run` sprints), keeps the view centred on itself
and wheel-zooms it; the sprite is placed by this scene's document, which
files its Collision2D under it.

Add a game from here: `self.spawn(Sprite, (x, y))` more flat objects,
`self.add(meshes.rect2d(...), blend="alpha")` backdrops, a second angle
with `self.add_camera(name=...)` and `self.set_active_camera(name)`.
"""

import emoeng as fe
from emoeng.engine import meshes


class Main(fe.Scene2D):
    name = "main"
    uses = ("sprite",)

    world_size = (960.0, 540.0)
    clear_color = (0.05, 0.06, 0.10)

    def setup(self):
        # a flat backdrop, queued into the static alpha batch
        self.add(meshes.rect2d((480, 270), (960, 540),
                               col=(0.10, 0.14, 0.22)),
                 texture="white", blend="alpha")
        self.player = self.spawn(fe.Player2D, (480.0, 450.0),
                                 size=(96.0, 20.0), col=(0.9, 0.9, 1.0))

    def status(self):
        return [self.name, "arrows or WASD move, wheel zooms"]
'''

START2D_SPRITE = '''"""Sprite: a flat thing a scene places, with a rect.

Its document (objects/sprite.obj2d) files a Collision2D under it, so it
is something the player can bump into as soon as it is placed. `texture`
takes a textures/ stem, "white" or any spelling of a colour - this one
says a colour and so needs no file at all.
"""

import emoeng as fe


class Sprite(fe.Object2D):
    name = "sprite"
    clone_attrs = ("size", "texture", "grid", "anchor")

    def build(self):
        look = self.look if isinstance(self.look, dict) else {}
        if look.get("texture") or look.get("color"):
            self.set(texture=look.get("texture"), col=look.get("color"))
        else:
            self.set(texture="#d8b26a")
        super().build()
'''

# the sprite's branch: the box it draws, as a wall
_SPRITE2D_NODES = (
    {"id": "Collision2D#0",
     "type": "collision2d",
     "pos": [0.0, 0.0],
     "size": [48.0, 48.0]},
)

MENU_SCENE = '''"""Menu: widgets on the window, and a button that ends the run.

A UI scene's world is the window in pixels and its camera does not move.
Hover, press and click are routed to the widget that owns them, so a
button only has to say what its click does: hand `action=` a callable, or
subclass `fe.UIObject` and override `on_click`.

This is the shape of a title screen. Point `Play` at a scene once you
have one - `self.play_scene("main")` - and name this folder's `start`
`menu` to open on it instead of on a world.
"""

import emoeng as fe


class Menu(fe.SceneUI):
    name = "menu"
    clear_color = (0.07, 0.08, 0.12)

    def setup(self):
        w, h = self.window_size
        self.title = self.spawn(fe.UIObject, (w / 2.0, h * 0.30),
                                size=(360.0, 64.0), text="hello",
                                color=(0.15, 0.35, 0.65), font_size=32)
        self.quit = self.spawn(fe.UIObject, (w / 2.0, h * 0.55),
                               size=(200.0, 44.0), text="Quit",
                               action=self.game.quit)

    def status(self):
        return [self.name, "click Quit"]
'''


FLY3D_SCENE = '''"""Sky: a free-flying player among crates that float.

`movement="fly"` is the whole difference from the walking starter: WASD
goes where you look, `up` climbs and `down` sinks, and no ground glues you
down - only the floor at y = 0 catches you. The crates are `prop`
placements, and each one carries the collision box its document files, so
flying into one stops you instead of passing through.

The crates are at -Z and the player starts at +Z turned toward them
(`yaw=math.pi`), so flying forward weaves between all three.

Add a game from here: rings to fly through, a wider sky (`world_radius`),
a look of your own in `shaders/` named in `post`.
"""

import math

import emoeng as fe
from emoeng.engine import meshes


class Main(fe.Scene3D):
    name = "main"
    uses = ("prop",)

    clear_color = (0.09, 0.12, 0.20)
    fog_color = (0.10, 0.13, 0.22)
    fog_near = 30.0
    fog_far = 140.0
    ambient = (0.42, 0.46, 0.58)
    sun_dir = (0.5, 0.8, -0.3)
    sun_col = (0.55, 0.55, 0.60)

    def setup(self):
        # a floor far below, so "up" has something to mean
        self.renderer.texture("grid", fe.proctex.grid(128, 8))
        self.add(meshes.plane(size=(90, 90), seg=8), texture="grid")
        self.add_light((0.0, 7.0, -9.0), (0.55, 0.70, 1.0), radius=20.0)
        self.player = self.spawn(fe.Player3D, pos=(0.0, 4.0, 10.0),
                                 yaw=math.pi, movement="fly",
                                 move_speed=(8.0, 18.0), world_radius=34.0)

    def spawn_point(self):
        return (0.0, 4.0, 10.0), math.pi

    def status(self):
        return [self.name, "fly: WASD, space up, q down"]

    def overlay(self, screen):
        fe.ui.text(screen, self.game.fonts["small"],
                   self.game.control_hint(), (14, 12))
'''

PLATFORMER2D_SCENE = '''"""Main: ledges, gravity and a jump, written out so you can change them.

The engine does not integrate gravity - a scene says how falling works.
`LEDGES` is the solid world as plain rects, the player is a `Player2D`
with its own steering switched off, and `step()` is the whole physics: one
sideways sweep, one downward sweep, and `collision.move_slide2d` stopping
each of them at a ledge.

Space jumps, but only from the ground. `GRAVITY` pulls harder when it is
bigger and `JUMP` lifts higher; a jump clears about 113 px here, and each
step of the staircase is only 64 px above the one before.

The camera is held still on the whole level (`follows_view=False`), so
the layout reads as one screen; drop that knob from the spawn and the
view follows the player instead.
"""

import emoeng as fe
from emoeng.engine import collision, meshes


# the solid world: left, top, width, height, in world pixels
LEDGES = (
    (0.0, 500.0, 960.0, 40.0),     # the ground: everything stands on it
    (120.0, 436.0, 180.0, 16.0),   # the staircase, 64 px a step
    (340.0, 372.0, 180.0, 16.0),
    (560.0, 308.0, 180.0, 16.0),
    (780.0, 244.0, 170.0, 16.0),   # the top step
)

# a gold square over the top step: scenery, and nothing to collide with
GOAL = (865.0, 200.0, 26.0, 26.0)


class Main(fe.Scene2D):
    name = "main"

    world_size = (960.0, 540.0)
    clear_color = (0.05, 0.06, 0.10)

    speed = 250.0            # pixels per second, walking
    GRAVITY = 1800.0         # downward pull, pixels per second squared
    JUMP = 640.0             # upward kick when the jump starts
    RADIUS = 13.0            # how round the player is to a ledge

    def setup(self):
        tones = ((0.24, 0.30, 0.44), (0.30, 0.37, 0.52))
        for i, (x, y, w, h) in enumerate(LEDGES):
            self.add(meshes.rect2d((x + w / 2.0, y + h / 2.0), (w, h),
                                   col=tones[i % 2]),
                     texture="white", blend="alpha")
        x, y, w, h = GOAL
        self.add(meshes.rect2d((x, y), (w, h), col=(0.95, 0.78, 0.35)),
                 texture="white", blend="alpha")
        # standing on the ground row, which its radius puts at y 487
        self.player = self.spawn(fe.Player2D, (60.0, 487.0),
                                 size=(26.0, 26.0), col=(0.95, 0.85, 0.55),
                                 follows_view=False)
        # the scene steers, so the player does not steer itself
        self.player.lock_input = True
        self.vy = 0.0
        self.grounded = True

    def update(self, dt):
        super().update(dt)
        self.step(dt)

    def step(self, dt):
        """One frame of walking and falling, each axis swept separately."""
        body = self.player
        right = self.input.axis("right", "left")
        run = self.input.down("run")
        speed = self.speed * (1.8 if run else 1.0)
        if right:
            body.pos, _hits = collision.move_slide2d(
                body.pos, [right * speed * dt, 0.0], LEDGES, self.RADIUS)
        self.vy += self.GRAVITY * dt
        body.pos, hits = collision.move_slide2d(
            body.pos, [0.0, self.vy * dt], LEDGES, self.RADIUS)
        landed = bool(hits[1]) and self.vy > 0.0
        if hits[1]:
            self.vy = 0.0      # a ledge, above or below: stop there
        self.grounded = landed
        if landed and self.input.pressed("up"):
            self.vy = -self.JUMP
            self.grounded = False

    def status(self):
        return [self.name, "arrows or WASD move, space jumps"]

    def overlay(self, screen):
        where = "on a ledge" if self.grounded else "in the air"
        fe.ui.text(screen, self.game.fonts["small"], where, (14, 12))
'''

EMPTY3D_SCENE = '''"""Main: an empty 3D scene, a player, and nothing to look at.

A blank page with the camera already in it. The player walks on the
ground plane at y = 0 whether or not anything is drawn there, so the
first thing worth adding is a floor:

    self.renderer.texture("grid", fe.proctex.grid(128, 8))
    self.add(meshes.plane(size=(40, 40), seg=8), texture="grid")

Props come from the Project View (a document brings its collision box
with it) or from `self.spawn(...)` here; `self.add_light(...)` for a lamp.
"""

import emoeng as fe


class Main(fe.Scene3D):
    name = "main"
    uses = ()

    clear_color = (0.04, 0.05, 0.08)

    def setup(self):
        self.player = self.spawn(fe.Player3D, pos=(0.0, 0.0, 0.0),
                                 move_speed=(5.0, 10.0), world_radius=0.0)

    def status(self):
        return [self.name, "empty scene: add geometry in setup()"]
'''

EMPTY2D_SCENE = '''"""Main: an empty 2D scene with a steered player.

`world_size` is the design resolution: the camera fits it to the window
and the player drags the view along as it walks. Arrows or WASD move,
wheel zooms. Pictures come from `self.add(meshes.rect2d(...),
blend="alpha")` or from sprite documents this scene places - a
`Collision2D` under one is what turns it into a wall.
"""

import emoeng as fe


class Main(fe.Scene2D):
    name = "main"

    world_size = (960.0, 540.0)
    clear_color = (0.05, 0.06, 0.10)

    def setup(self):
        self.player = self.spawn(fe.Player2D, (480.0, 270.0))

    def status(self):
        return [self.name, "arrows or WASD move, wheel zooms"]
'''


# every starting point, in the order the dialog lists: `group` is the
# caption the picker puts above a run of starters
PROJECTS = {
    "game3d": {
        "title": "Game 3D",
        "group": "3D",
        "hint": "a first-person world: a floor, one prop, a player",
        "size": [1152, 700],
        "scale": 0.75,
        "start": "main",
        "scenes": (("main", "scene3d", START3D_SCENE,
                    (("prop", [0.0, 0.0, -4.0]),)),),
        "objects": (("prop", "object3d", START3D_PROP, _PROP3D_NODES),),
        "models": ("box", "crate", "pillar"),
        "maps": ("room",),
    },
    "fly3d": {
        "title": "Fly 3D",
        "group": "3D",
        "hint": "a free-flying camera among floating crates",
        "size": [1152, 700],
        "scale": 0.75,
        "start": "main",
        "scenes": (("main", "scene3d", FLY3D_SCENE,
                    (("prop", [0.0, 2.0, 2.0]),
                     ("prop", [4.5, 6.0, -4.0]),
                     ("prop", [-5.0, 10.0, -9.0]))),),
        "objects": (("prop", "object3d", START3D_PROP, _PROP3D_NODES),),
        "models": ("box", "crate"),
        "maps": (),
    },
    "game2d": {
        "title": "Game 2D",
        "group": "2D",
        "hint": "a flat arena: a backdrop, one sprite, a steered player",
        "size": [960, 540],
        "scale": 1.0,
        "start": "main",
        "scenes": (("main", "scene2d", START2D_SCENE,
                    (("sprite", [480.0, 200.0]),)),),
        "objects": (("sprite", "object2d", START2D_SPRITE,
                     _SPRITE2D_NODES),),
        "models": ("sprite",),
        "maps": (),
    },
    "platformer": {
        "title": "Platformer 2D",
        "group": "2D",
        "hint": "ledges, gravity and a jump, all in the scene script",
        "size": [960, 540],
        "scale": 1.0,
        "start": "main",
        "scenes": (("main", "scene2d", PLATFORMER2D_SCENE, ()),),
        "objects": (),
        "models": ("sprite",),
        "maps": (),
    },
    "menu": {
        "title": "Menu",
        "group": "UI",
        "hint": "widgets on the window: a title and a button that quits",
        "size": [900, 560],
        "scale": 1.0,
        "start": "menu",
        "scenes": (("menu", "sceneui", MENU_SCENE, ()),),
        "objects": (),
        "models": (),
        "maps": (),
    },
    "empty3d": {
        "title": "Empty 3D",
        "group": "Empty",
        "hint": "a clear colour and a player: build the world yourself",
        "size": [1152, 700],
        "scale": 0.75,
        "start": "main",
        "scenes": (("main", "scene3d", EMPTY3D_SCENE, ()),),
        "objects": (),
        "models": (),
        "maps": (),
    },
    "empty2d": {
        "title": "Empty 2D",
        "group": "Empty",
        "hint": "a flat world with a steered player and no pictures",
        "size": [960, 540],
        "scale": 1.0,
        "start": "main",
        "scenes": (("main", "scene2d", EMPTY2D_SCENE, ()),),
        "objects": (),
        "models": ("sprite",),
        "maps": (),
    },
}

TEMPLATE_ORDER = ("game3d", "fly3d", "game2d", "platformer", "menu",
                  "empty3d", "empty2d")
DEFAULT_TEMPLATE = "game3d"


def spec(key):
    """One template's entry; unknown names get the default."""
    return PROJECTS.get(str(key) or DEFAULT_TEMPLATE,
                        PROJECTS[DEFAULT_TEMPLATE])


# what a 3D scene already starts with, so the Project tab has rows to show:
# every `defaults` key, set to the value the engine itself holds, so a new
# project looks exactly as it did before the manifest said anything
SEED_DEFAULTS = {
    "ambient": [0.22, 0.22, 0.26], "sun_dir": [0.35, 0.75, 0.5],
    "sun_col": [0.22, 0.20, 0.18], "fog_color": [0.06, 0.06, 0.09],
    "move_speed": [6.0, 12.0], "post": [], "camera": "walk",
    "lock_input": False, "master": 1.0, "fog_near": 40.0,
    "fog_far": 220.0, "fov": 68.0, "near": 0.05, "far": 800.0,
    "eye_height": 2.0, "world_radius": 128.0,
    # the engine's walk camera is glued to the ground, so these stay off
    # until a scene wants falling: they are here to be switched on
    "gravity": 0.0, "jump_speed": 0.0,
}


def template_names():
    """The template keys, in chooser order."""
    return TEMPLATE_ORDER


def manifest(key, name, title=None, start=None):
    """The manifest dict `Project.create` writes for one template."""
    named = str(key or DEFAULT_TEMPLATE)
    got = spec(named)
    # the row the manager files it under, without reading its scenes back
    named = named if named in PROJECTS else DEFAULT_TEMPLATE
    three_d = any(kind == "scene3d" for _n, kind, _s, _p in got["scenes"])
    return {
        "format": const.PROJECT_FORMAT,
        "name": str(name),
        "template": named,
        "title": str(title or got["title"]),
        "start": str(start or got["start"]),
        "version": "0.1.0",
        "description": str(got["hint"]),
        "seed": 7,
        "window": {"size": list(got["size"]), "fullscreen": False,
                   "resizable": True, "min_size": [800, 480]},
        "render": {"scale": float(got["scale"]), "post": [],
                   "bake_on_run": False, "bake_size": 512,
                   "vsync": True, "fps_cap": 60},
        "audio": {"master": 0.8, "music_volume": 0.6, "music": ""},
        "save": {"slot": const.SAVE_SLOT, "autosave": 0.0,
                 "auto_load": False},
        "debug": {"show_fps": True, "show_help": False, "overlay": True},
        "input": {"actions": {}, "triggers": {}},
        "defaults": dict(SEED_DEFAULTS) if three_d else {},
    }


def layout(key, start=None):
    """What a template writes for `Project.create`."""
    got = spec(key)
    stem = str(start or got["start"])
    # the folder and suffix are read off the template's own document types,
    # so an entity is written into `entities/` and a prop into `objects/`
    where = {name: (scenedoc.doc_folder(kind), scenedoc.doc_ext(kind))
             for name, kind, _src, _nodes in got["objects"]}

    def document_ref(ref):
        """`objects/prop.obj3d` or `entities/guard.ent3d`, by its type."""
        folder, ext = where.get(ref) or ("objects", "")
        return f"{folder}/{ref}{ext}"

    scripts, documents = {}, {}
    for name, kind, source, places in got["scenes"]:
        file = stem if name == got["start"] else name
        scripts[f"scripts/scenes/{file}.py"] = source
        doc = scenedoc.blank_scene(
            file, kind, scenedoc.script_field("scripts/scenes",
                                              f"{file}.py"))
        doc["objects"] = [{"id": ref, "object": document_ref(ref),
                           "pos": list(place)} for ref, place in places]
        documents[f"scenes/{file}.scene"] = doc
    for name, kind, source, nodes in got["objects"]:
        entity = scenedoc.doc_family(kind) == "entity"
        folder = "scripts/entities" if entity else "scripts/objects"
        scripts[f"{folder}/{name}.py"] = source
        blank = scenedoc.blank_entity if entity else scenedoc.blank_object
        doc = blank(name, kind, scenedoc.script_field(folder, f"{name}.py"))
        doc["nodes"] = [dict(node) for node in nodes]
        documents[f"{scenedoc.doc_folder(kind)}/{name}"
                  f"{scenedoc.doc_ext(kind)}"] = doc
    return scripts, documents, tuple(got["models"]), \
        tuple(got.get("maps") or ())
