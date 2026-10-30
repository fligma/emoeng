# Scenes

A scene is one playable screen. It lives in `scripts/scenes/<stem>.py`, defines
exactly one `Scene` subclass, and owns the objects, timers, geometry and camera
of that screen. Three kinds exist; they share one lifecycle and one API.

| Class | `kind` | Object base | Camera | World units |
| --- | --- | --- | --- | --- |
| `fe.Scene3D` | `'3d'` | `Object3D` | `Camera` (perspective) | metres, y up |
| `fe.Scene2D` | `'2d'` | `Object2D` | `Camera2D` (orthographic) | world pixels, origin top-left |
| `fe.SceneUI` | `'ui'` | `UIObject` | `Camera2D` | window pixels |

`Scene` is the shared shell and is never used directly.

## Lifecycle

| Order | Hook | Called |
| --- | --- | --- |
| 1 | `__init__(game, seed=7)` | By `Project.scene()`; sets up subsystem handles |
| 2 | `setup()` | Once, before the first frame - build the world here |
| - | `on_map_loaded(level)` / `on_map_unloaded(level)` | Around each `load_map()` / `change_map()` / `unload_map()`; a declared map is built before `setup()`, so the first `on_map_loaded` comes first ([Maps](maps.md)) |
| 3 | `finish_build()` | Merges queued geometry into GPU batches (`renderer.build()`) |
| 4 | `on_enter()` | Every time play (re)starts this scene |
| 5 | `update(dt)` | Every frame, unless paused |
| 6 | `handle_event(e)` | Every pygame event not consumed by the game |
| 7 | `render(camera=None)` | Every frame; returns the `Surface` the game blits |
| 8 | `overlay(screen)` | Every frame, after the render, straight onto the window |
| 9 | `status()` | When the status bar redraws |
| 10 | `on_save(save)` / `on_load(save)` | Around a slot write / read |
| 11 | `on_exit()` | When the scene is left; clears timers by default |

## Shared attributes

Set these as class attributes on your subclass.

| Attribute | Default | Meaning |
| --- | --- | --- |
| `name` | per kind | Scene name; `game.load_scene(name)` and the caption use it |
| `uses` | `()` | Object stems this scene spawns, checked at load |
| `actions` | `{}` | `{action: [binding, ...]}` this scene adds to the keymap |
| `controls` | `()` | Extra action names to list in the F1 help panel |
| `map_name` | `None` | The `maps/` stem this scene opens on; the level is loaded before `setup()` and `self.map_name` follows the live one ([Maps](maps.md)) |
| `clear_color` | `(0.02, 0.02, 0.03)` | Linear RGB background, or any colour spelling |
| `post` | `()` | Names of the scene's `screen` shader chain; empty falls back to the project's ([Shaders](shaders.md)) |
| `viewport` | `None` | `(x, y, w, h)` - pixels or 0..1 - to limit the view |
| `object_base` | `GameObject` | What `spawn()` accepts |
| `camera_class` | `None` | Camera type `add_camera()` builds |
| `ambient` | `(0.22, 0.22, 0.26)` | The 3D shader floor - how dark the dark is |
| `ambient2d` | `(0.10, 0.10, 0.12)` | How bright a 2D scene's unlit corner is |
| `sun_dir` / `sun_col` | `(0.35, 0.75, 0.5)` / `(0.22, 0.20, 0.18)` | The directional light's uniforms |
| `blockers` | `None` | What occludes a `Light2D`: rects, segments, objects or a callable |
| `master` | `1.0` | Scene-wide dimmer; `set_master(0)` is black |

## Shared instance state

Set in `Scene.__init__`, readable from any hook.

| Attribute | Value |
| --- | --- |
| `self.game` | The `Game` |
| `self.project` | `game.project` |
| `self.renderer`, `self.audio`, `self.input`, `self.save` | The subsystems, so a scene writes `self.audio.play("pickup")` |
| `self.rng` | `np.random.default_rng(seed)` - seeded from the project, so a seed replays a map |
| `self.objects` | Live object list |
| `self.lights` | The `Light3D` / `Light2D` in the scene; an old-style `{"pos":, "color":}` dict is adopted as a real light the first time it is read |
| `self.sun` | The one directional light, or `None` (`set_sun()` makes it) |
| `self.player` | The object that claimed the view, or `None` |
| `self.map` | The live `MapLevel`, or `None`; `load_map` / `change_map` / `unload_map` swap it ([Maps](maps.md)) |
| `self.camera_rig` | The object that called `set_camera()` |
| `self.cameras` | `{name: Camera}` registered extra views |
| `self.active` | Name of the rendering camera; `None` = the scene's default view |
| `self.lock_input` | Freezes the player (cutscenes) |
| `self.t` | Seconds since `setup()` |
| `self.timers` | The scene's `Timers` |
| `self.hud` | The `Hud` facade: `ui` calls with the screen and font filled in, laid out inside `hud.area` ([UI and HUD](ui-and-hud.md)) |

## Building the world

| Method | Signature | Notes |
| --- | --- | --- |
| `add` | `add(data, texture='white', blend='opaque')` | Queue generated geometry into the static batch, merged per texture + blend |
| `dynamic` | `dynamic(data, texture='white', blend='alpha', **kw)` | A live mesh you refill every frame, for geometry that never holds still. The renderer disposes it when the scene unloads |
| `model` | `model(name)` | Cached `Model` from `models/<name>.model3d` |
| `place_model` | `place_model(name, pos, yaw=0.0, scale=1.0, tint=None)` | Stamp a `.model3d` into the static batch, one piece per tagged surface |
| `model_object` | `model_object(name, pos, yaw=0.0, scale=1.0, tint=None, texture=None, blend='opaque')` | A movable `ModelObject` |
| `add_light` | `add_light(pos=None, color=None, shape=None, **kw)` | Any light, 3D or 2D; returns the `Light` to move, aim, animate or remove. Also adopts an existing `Light` or a `to_dict()` mapping |
| `add_preset` | `add_preset(name, pos=None, dim=None, tag=None, **kw)` | One of the ready-made lights (`"campfire"`, `"doorway"`, `"siren"`) |
| `copy_light` | `copy_light(light, pos=None, tag=None, **kw)` | A second copy of one of the scene's lights |
| `remove_light` | `remove_light(light_or_tag)` | Take it out for good; True when it was there |
| `clear_lights` | | Drop every light, for a level rebuild |
| `finish_build` | | Merge everything queued (the loader calls it for you) |

Blend values are `'opaque'`, `'alpha'`, `'add'` and - for 2D lights - `'light'`;
`'hud'` draws after the light mask, so widgets stay readable. Shapes pick the
class: `point`, `spot`, `sun`, `tube` are 3D, `radial`, `cone`, `rect`, `strip`,
`ring`, `poly`, `world` are 2D, and where a name lives in both worlds the
scene's kind decides (`dims=2` / `dims=3` forces it). Lights tick with the
scene and need nothing further - [Lighting](lighting.md) is the whole API.

```python
self.set_ambient("night", 0.06)
self.torch = self.add_light(shape="spot", angle=48, radius=26, glow=0.6,
                           follow=self.player, align=True, local=True,
                           aim=(0, -12), priority=9)
self.add_preset("campfire", (4.0, 0.9, -3.0))
```

## Objects

| Method | Signature | Notes |
| --- | --- | --- |
| `spawn` | `spawn(obj, pos=None, parent=None, clone_of=None, tag=None, look=None, **kw)` | `obj` is a class or an object name (its `.obj3d` / `.obj2d` document or `scripts/objects/<stem>.py`); extra kwargs go to the constructor and `look` is placement from a document |
| `object_class` | `object_class(obj)` | Resolve a stem or class to a class, checked against `object_base` |
| `despawn` | `despawn(obj)` | Remove it and everything it spawned or cloned; its owned cameras go too |
| `objects_of` | `objects_of(obj)` | Every live instance of a class or file |
| `by_tag` | `by_tag(tag)` | First live object with that tag |
| `default_pos` | | Where a spawn with `pos=None` lands |
| `attach_player` | `attach_player(ent, **kw)` | Called for you when a spawned class has `is_player = True` |

`spawn()` constructs, attaches, appends, then calls `build()`. If `build()`
raises, the object is removed, marked dead and disposed, so a broken prop cannot
sit half-built in the scene.

Placement arrives as `self.look`, merged from the class's `look_defaults`, the
scene's document and the `look=` keyword - in that order, and before `build()`
runs. Each instance also gets a stable `doc_key` (`Torch#0`, a node's
`Torch#0/Flame#0`) and, when a document placed it, a `placed_id`. See *Scene
documents* below.

### Nodes and shapes

`spawn(..., parent=obj)` files the new object as that object's node: it keeps
the world position you passed, works out the offset from the parent, and rides
it from then on. `obj.spawn(...)` is the same call with the parent already set.

| Method | Signature | Notes |
| --- | --- | --- |
| `colliders` | attribute | The live list of filed shape nodes |
| `add_collider` / `remove_collider` | `(node)` | A `Collision3D` / `Hitbox3D` / `Collision2D` / `Hitbox2D` calls these itself, in `build()` and `dispose()` |
| `colliders_of` | `colliders_of(group="", solid=None)` | The shapes a mover reckons with; `""` on a shape stops everybody, `solid=None` asks for every one, triggers included |
| `collider_boxes` / `collider_rects` | `(group="", solid=True)` | Those nodes as `(centre, half)` boxes or `(x, y, w, h)` rects |
| `move_body` | `move_body(pos, delta, half=(0.35, 0.9, 0.35), group="")` | Sweep a 3D body through them; returns `(new_pos, hits)` |
| `move_body2d` | `move_body2d(pos, delta, radius=0.0, group="")` | The flat twin |
| `hits_at` | `hits_at(point, group="")` | Every trigger covering a world point or pixel |
| `sync_tree` | | Put every node where its parent has got to - run at the end of `update()`, and by the editor after a drag |

A `Player3D`'s move already goes through `move_body`, so the shapes a document
places are what holds the player up. [Collision](collision.md) is the whole
sweeping API and [Objects](objects.md) the nodes themselves.

## Cameras

| Method | Signature | Notes |
| --- | --- | --- |
| `add_camera` | `add_camera(camera=None, name=None, **kw)` | Adopt a rig or build one from `camera_class(**kw)`; names default to `cam1`, `cam2` |
| `set_active_camera` | `set_active_camera(cam=None)` | Cut by name or object; `None` returns to the default view |
| `active_camera` | property | The registered rendering camera, or `None` |
| `view` | property | Active camera, else the scene's (or game's) own rig - what `render()` uses |
| `bind` | `bind(action, *bindings)` | Add a binding for this scene, exactly like `input.map.json` |

Every registered camera ticks each frame, not only the active one, so a parked
angle keeps its shake dying out and its follow easing while you are elsewhere.

## Scheduling and flow

| Method | Signature | Notes |
| --- | --- | --- |
| `after` | `after(delay, func, *args, **kwargs)` | One-shot; returns a `Timer` you can `cancel()` |
| `every` | `every(delay, func, *args, **kwargs)` | Repeating until the scene ends |
| `play_scene` | `play_scene(name, fade=0.35)` | Fade through black into another scene |
| `push_scene` | `push_scene(name, fade=0.35)` | Stack one over this one |
| `pop_scene` | `pop_scene(fade=0.35)` | Back to the scene underneath |

## Scene3D

3D-specific class attributes, all overridable per scene or per object:

| Attribute | Default | Meaning |
| --- | --- | --- |
| `camera` | `'walk'` | Movement style: `'walk'` or `'fly'` |
| `move_speed` | `(6.0, 12.0)` | Walk and run, metres per second |
| `eye_height` | `2.0` | Camera above the ground while walking |
| `world_radius` | `128.0` | Hard clamp from origin; `0` disables it |
| `fov` / `near` / `far` | `68.0` / `0.05` / `800.0` | Frustum |
| `roll` | `0.0` | Horizon tilt, radians |
| `fog_color` | `(0.06, 0.06, 0.09)` | Fog and background tint |
| `fog_near` / `fog_far` | `40.0` / `220.0` | Fog start and full distance |

`ambient`, `sun_dir` and `sun_col` are inherited from `Scene` (see Shared
attributes); `set_ambient(...)` and `set_sun(...)` are the ways to move them
without spelling tuples.

| Member | Notes |
| --- | --- |
| `ground_height(x, z)` | Override for terrain; used to keep the camera on the floor |
| `spawn_point()` | `((x, y, z), yaw)` where the player starts - the live map's `spawn` when there is one, else the origin |
| `attach_player(ent, pos=None, yaw=None, pitch=None)` | Hand the camera to an object |
| `eye` | Live camera position; with a Player this reads the player |
| `shake(amount=1.0, duration=0.35, freq=None, scale=None, roll=None)` | Rattle the view |
| `look_at(target, damping=None, offset=None)` | Aim at a world point |
| `follow(target, offset=None, damping=None)` | Chase a point or object |

```python
class Grove(fe.Scene3D):
    name = "grove"
    uses = ("firefly",)
    fog_near, fog_far = 6.0, 40.0
    ambient = (0.10, 0.12, 0.16)

    def setup(self):
        self.renderer.texture("bark", fe.proctex.bark(64))
        self.place_model("trunk", (4.0, 0.0, -6.0), scale=2.0)
        self.add(fe.meshes.plane(size=(60, 60), seg=24,
                                 height_fn=self.hill), texture="ground")
        self.player = self.spawn(fe.Player3D, pos=(0.0, 0.0, 9.0))
        self.spawn("firefly", (0.0, 1.4, 4.0))
        self.finish_build()

    def hill(self, x, z):
        return 0.6 * (x * 0.05) ** 2 + 0.4 * (z * 0.05) ** 2

    def ground_height(self, x, z):
        return self.hill(x, z)

    def update(self, dt):
        super().update(dt)
        if self.input.pressed("use"):
            self.player.look_at(self.by_tag("firefly"))
```

## Scene2D

| Attribute / member | Default | Meaning |
| --- | --- | --- |
| `world_size` | `(960.0, 540.0)` | Design resolution box in world pixels |
| `scale_mode` | `'fit'` | How the box maps onto the window |
| `clear_color` | `(0, 0, 0)` | |
| `ambient` / `sun_col` | `(1, 1, 1)` / `(0, 0, 0)` | Flat lighting: sprites keep their own colour |
| `fog_near` / `fog_far` | very large | Fog effectively disabled |
| `lights_near(pos, radius=None)` / `luminance(pos=None)` / `light_count()` | | The gameplay questions to ask about the light in a 2D world |
| `sync_view()` | | Match the ortho rigs to the window; called every frame, resize-proof |
| `to_world(screen_pixel)` | | Window mouse position to world pixel |
| `route_mouse(e)` | | Feed mouse events to the objects above them, topmost first |
| `_cams2d()` | | The default rig plus every registered `Camera2D` |
| `spawn_point()` | | `((x, y, z), yaw)` - the live map's spawn in world pixels, else the middle of `world_size`; a flat caller takes `start[:2]` |

```python
class Play(fe.Scene2D):
    name = "play2d"
    world_size = (960.0, 540.0)

    def setup(self):
        self.add(fe.meshes.rect2d((480, 270), (960, 540),
                                  col=(0.10, 0.16, 0.26)),
                 texture="white", blend="alpha")
        self.player = self.spawn(fe.Player2D, (480.0, 450.0),
                                 size=(120.0, 16.0), col=(0.9, 0.9, 1.0))
        self.add_camera(name="wide", center=(480.0, 270.0), zoom=0.5)
```

A flat scene can skip the backdrop entirely and name a level instead -
`map_name = "arena"` loads `maps/arena.map2d` before `setup()` and draws it
behind every sprite the scene spawns, its floor and its border bands being
parts of one file rather than calls in code ([Maps](maps.md)).

## SceneUI

A `Scene2D` whose world is the window: `world_size = None`, so nothing is
scaled and coordinates are window pixels.

| Member | Notes |
| --- | --- |
| `default_pos()` | Widgets land at the top-left unless placed |
| `window_size` | Current window pixels, for right/bottom anchoring |
| `handle_event(e)` | Routes mouse events into `UIObject.handle_event` |

```python
class Menu(fe.SceneUI):
    name = "menu"
    clear_color = (0.07, 0.08, 0.12)

    def setup(self):
        w, h = self.window_size
        self.title = self.spawn(fe.UIObject, (w / 2.0, h * 0.3),
                                size=(360.0, 64.0), text="hello",
                                color=(0.15, 0.35, 0.65), font_size=32)
        self.play = self.spawn(fe.UIObject, (w / 2.0, h * 0.55),
                               size=(200.0, 44.0), text="Play",
                               action=lambda: self.play_scene("main"))
        self.quit = self.spawn(fe.UIObject, (w / 2.0, h * 0.70),
                               size=(200.0, 44.0), text="Quit",
                               action=self.game.quit)
```

## Stacking a menu over the world

```python
# in the 3D scene
def setup(self):
    self.bind("menu", "tab")

def update(self, dt):
    super().update(dt)
    if self.input.pressed("menu"):
        self.push_scene("menu")        # pauses nothing; the world keeps running

# in the menu scene
def on_click_resume(self):
    self.pop_scene()                   # back to the world, still built
```

`pop_scene()` rebuilds the scene underneath, so a HUD that must survive a menu
should be drawn in `overlay()` rather than pushed as its own scene.

## `handle_event` and `overlay`

```python
class Main(fe.Scene3D):
    def handle_event(self, e):
        if e.type == pygame.KEYDOWN and e.key == pygame.K_g:
            self.shake(1.4, 0.5)
            return True                # consumed
        return False

    def overlay(self, screen):
        fe.ui.text(screen, self.game.fonts["small"],
                   self.game.control_hint(), (14, 12))
        fe.ui.bar(screen, (14, 40, 180, 12), self.hp / 100.0)
```

Return `True` from `handle_event` when your scene took the event. `overlay`
draws on the window surface after the 3D/2D frame and after post passes, so it
stays crisp at any render scale. See [UI and HUD](ui-and-hud.md).

## Scene documents (`scenes/*.scene`)

A scene is two files that sit side by side, one in each half of the project:
the script (`scripts/scenes/camp.py`) says what the scene is and what it does,
and the document (`scenes/camp.scene`) says what is placed, where and how it
looks. The runtime only reads documents; the editor writes them as you drag
things.

```json
{
 "format": 1,
 "name": "camp",
 "kind": "scene3d",
 "script": "scripts/scenes/camp.py",
 "objects": [
  {"id": "torch#0", "script": "scripts/objects/torch.py",
   "pos": [1.0, 0.0, 2.0], "yaw": 0.0, "scale": 1.0,
   "model": "brazier", "texture": "rust", "color": [1.0, 0.9, 0.8]},
  {"id": "crate#0", "type": "object3d", "pos": [-3.0, 0.0, 1.5],
   "children": [
    {"id": "crate#0/Model3D#0", "type": "model3d",
     "pos": [0.0, 0.45, 0.0], "model": "crate"},
    {"id": "crate#0/Collision3D#0", "type": "collision3d",
     "pos": [0.0, 0.45, 0.0],
     "knobs": {"shape": "box", "half": [0.45, 0.45, 0.45]}}
   ]},
  {"id": "visitor", "type": "player3d", "pos": [0.0, 0.0, 7.4],
   "yaw": 3.1416}
 ],
 "overrides": {"Walker#0": {"pos": [0.0, 1.7, 4.0]}}
}
```

Add `"map": "hall"` to name the level this scene opens on.

| Field | Holds |
| --- | --- |
| `kind` | `scene3d`, `scene2d` or `sceneui` - the class built when there is no script |
| `script` | The project-relative `.py` the scene runs; optional |
| `map` | The `maps/` stem whose level this scene opens on, loaded before `setup()`; `scene.change_map(...)` swaps it mid play ([Maps](maps.md)) |
| `maps` | Stems in `maps/` to walk around - `"keep"`, or `{"map": "keep", "pos":, "yaw":, "scale":}`; the older placement route, each entry spawning its own `Map3D` node after `setup()` |
| `objects` | A tree: the top-level entries the document places, in spawn order, each with an `id` |
| `children` | An entry's own nodes, filed under it - a Model3D, a Collision3D, a lamp |
| `object` / `scene` | Make an entry an *instance*: it names another object or scene document, carries only a place (and per-instance overrides), and grafts that document's own branch under the placement |
| `type` | The node an entry is, when there is no script to say so - see [Objects](objects.md) |
| `knobs` | What that node owns beyond a transform, set before `build()` |
| `overrides` | Fields for objects the *script* spawned, keyed `Walker#0` |

`Project.scene(name, game, plan=None)` builds in one order: the document's
`map` (or the class's `map_name`) is loaded, then the script's `setup()`, then
`_place_maps()` and `_place_objects()` for the document's `maps` and `objects`,
then `finish_build()`. A document with no script still
builds - it gets the base class for its `kind`, with that kind's camera,
lighting and input. A project with no documents at all runs exactly as it
always did.

Because the declared level goes down first, `setup()` can read the world it is
standing in - `self.spawn_point()`, `self.map.parts()` - and `on_map_loaded`
fires before `setup()` on that first load, so a hook there has to guard against
state that does not exist yet. [Maps](maps.md) walks the whole swap.

Every spawn merges placement the same way and hands it to the object as
`self.look` before `build()` runs:

1. the class's own `look_defaults` (set from its `.obj3d` / `.obj2d` file, or
   from the object document the entry points at);
2. the scene document - the placed entry's fields, and `overrides` for the key;
3. an explicit `look=` keyword on the spawn call.

```python
class Torch(fe.Object3D):
    def build(self):
        model = self.look.get("model") or "brazier"
        sheet = self.look.get("texture") or "rust"
        self.body = self.model_object(model, self.pos, texture=sheet)
```

A key is the class name plus how many of that class `spawn()` has already built
- `Walker#0` is the first `Walker` the script spawns. That is a property of the
script rather than of the frame, so the same script names the same objects every
build, and an override survives a reload without the script being rewritten.
Every instance carries its key as `doc_key`, and `placed_id` when the document
placed it; the whole document is on `scene.doc` and its `overrides` on
`scene.plan`.

Only these fields are read (`scenedoc.LOOK_KEYS`): `pos`, `yaw`, `scale`, `rot`,
`size`, `model`, `texture`, `color`, `showing`, `shader`, `knobs`. A missing
field means "leave the object's own value alone", which is not the same as `0`.

A parent is placed before its nodes, and a node's `pos` is the offset from the
parent it is filed under, turned by that parent's `yaw` (or `rot` when flat) -
the same words `child_world()` speaks. `sync_tree()` runs once the last entry is
in, so the branch is right on the first frame.

| Helper | Does |
| --- | --- |
| `scenedoc.load(path, kind=None)` | Read a document, filling in every field a reader expects |
| `scenedoc.save(path, doc)` | Write one atomically (`.tmp`, then `os.replace`) |
| `scenedoc.blank_scene(name, kind, script)` / `blank_object(name, kind, script)` | A fresh document; the object's own `type` picks its `pos` shape |
| `scenedoc.roots(doc)` / `children(entry)` | The `objects` list / one entry's own nodes, made on first use |
| `scenedoc.walk(doc_or_entry)` | Every entry as `(entry, parent, depth)`, parents first - one pass rebuilds or draws the tree |
| `scenedoc.placed(doc, id=None)`, `parent_of`, `add_placed(doc, entry, parent=None)`, `remove_placed` | Find, file and cut entries, at any depth |
| `scenedoc.look(entry)` | Just the look fields an entry carries |
| `scenedoc.look_of(obj)` / `describe(obj, extra=None)` | The transform, look and `knobs` of a live object, written back as its parent sees it |
| `scenedoc.knobs_of(obj)` | Only the attributes the object put in `doc_knobs` |
| `scenedoc.set_override(doc, key, fields)` | Record a moved object; empty fields drop the entry |
| `scenedoc.key(cls_name, index, parent=None)` | `"Torch#0"`, or `"Torch#0/Flame#0"` for a node |
| `scenedoc.NODE_TYPES`, `node_type`, `type_label`, `type_drawer`, `node_groups` | The createable node types and what the editor calls them |
| `scenedoc.object_ext(type)`, `type_family`, `engine_class` | Which extension and which engine class a type means |
| `scenedoc.doc_path`, `find_doc`, `upgrade_ext`, `kind_of` | Where a document lives, in either its new or its old spelling |
| `scenedoc.script_field(folder, name)` / `script_stem(value)` | The `script` value, and the stem back out of it |

The `Project` side is one line each: `scene_doc(name)` (read fresh, so the next
build sees what the viewer just wrote), `save_scene_doc(name, doc)`,
`object_doc(name)` and `save_object_doc(name, doc)` - which writes under the
extension the document's own `type` means and clears away an old `.object` the
rename left behind. `object_file(name)` hands back the `(document, script)`
pair, `node_class(type, base)` the engine class a bare `type` names, and
`upgrade_documents()` renames a legacy `.object` / `.model` file the moment the
project opens.

## Screens: a scene inside a scene

`fe.Screen3D` and `fe.Screen2D` show another scene of the same project, the way
a monitor shows a camera feed. A screen owns a second `Renderer` at its own
resolution, builds the other scene through a stand-in host, and every frame
steps it, renders it, runs its post chain and hands the pixels to the outer
renderer as the texture the panel draws.

```python
class Booth(fe.Scene3D):
    def setup(self):
        self.feed = self.spawn(fe.Screen3D, (0.0, 2.0, 6.0),
                               size=(4.0, 2.25), name="menu",
                               brightness=0.8, audio=0.7,
                               audio_mode="emitter", reach=12.0, tag="feed")
        self.feed.overlay = self.stamp

    def stamp(self, picture, screen):
        fe.ui.text(picture, self.game.fonts["small"], "LIVE", (14, 12))

class Kiosk(fe.Scene2D):
    def setup(self):
        self.panel = self.spawn(fe.Screen2D, (320.0, 180.0),
                                size=(240.0, 135.0), pixels=(96, 54),
                                name="menu", shape="round")
```

`name=` is the scene to show; a document's word for the same thing is
`"showing"`, which `_ready()` honours because `look` is filled in after the
constructor has run. `None` leaves the picture blank until the screen's script
calls `show(name)`.

| Keyword | Default | Meaning |
| --- | --- | --- |
| `name` / `showing` | `None` | Which scene of the project to display |
| `pixels` | `(320, 180)` | The nested frame's own resolution |
| `shape` | `"rect"` | Alpha mask: `rect`, `round`, `circle`, `soft` (`screen.SHAPES`) |
| `brightness` | `1.0` | Multiplier on the picture |
| `tint` | `(1, 1, 1)` | Colour multiplied into the picture, any `fe.colors` spelling |
| `post` | `()` | Passes for the nested frame; empty falls back to the nested scene's own |
| `audio` | `1.0` | Gain for whatever the nested scene plays |
| `audio_mode` | `"global"` | `global` is flat, `emitter` fades with distance (`screen.AUDIO_MODES`) |
| `reach` | `20.0` | Metres before an emitter falls silent |
| `input` | `False` | Whether a camera ray and a click reach the nested scene; also what `send()` obeys - see [Pointing at a panel](#pointing-at-a-panel) |
| `overlay` | `None` | `overlay(picture, screen)` drawn on the nested frame after post |

```python
Screen3D(scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0, size=(3.2, 1.8),
         glow=False, depth=0.06, tag=None, opacity=1.0, **kw)
Screen2D(scene, pos=(0.0, 0.0), size=(320.0, 180.0), blend="hud", tag=None,
         opacity=1.0, **kw)
```

`Screen3D` draws a thin box in metres, standing `depth` of them proud of the
plane it was placed on - so a panel put at the wall's own face ends up *on* it
rather than halfway inside it. It is drawn on the `panel` layer: depth-tested,
neither lit nor fogged, and solid, which is what a monitor is. `glow=True` draws
it additively instead, which lights a picture in a pitch-dark corridor and lets
the wall show through its darks; ask for that on purpose. `opacity` fades the
whole panel, for glass and for a screen going dead.

`Screen2D` is a sprite in world pixels; `blend="hud"` keeps the scene's own
lights from dimming what you are looking through, and `blend="alpha"` puts it
back inside them. A box's `color` look field tints the panel itself.

| Method | Does |
| --- | --- |
| `show(name=None)` | Rebuild with another scene; `None` reloads the current one |
| `set_on(on=True)`, `toggle()`, `on` | Off stops stepping the nested scene and blanks the picture |
| `set_brightness(value)` | Dim or overdrive the picture |
| `set_tint(color)` | Multiply the picture |
| `set_shape(shape)` | Cut the picture to a mask |
| `set_post(*names)` | Screen shaders for the nested frame (see [Shaders](shaders.md)) |
| `set_opacity(value)` | Fade the panel itself - see [Objects](objects.md) |
| `set_audio(mode, gain=None, reach=None)` | Flat or emitter, and how loud |
| `audio_gain()` | The level the nested scene plays at right now |
| `send(event)` | Forward one event, only when `takes_input` is on |
| `nested`, `showing`, `error`, `stack` | The live scene, its name, why it failed, the push history |

The nested scene sees a host that answers like the game it sits in: the same
`project`, `input`, `fonts`, `audio` and `save`, its own camera, renderer and
`screen` size, and `load_scene` / `play_scene` / `push_scene` / `pop_scene`
routed to `show()` - with no fades, because the picture swaps on the next frame.
`quit()` switches the screen off.

An emitter scales only what the nested scene *starts*: `_SubAudio.play`
multiplies the gain by `audio_gain()`, which is `gain * (1 - distance / reach)`
from `game.eye` to the panel, so a monitor's jingle is loud beside it and silent
across the room. The scene kind still decides what it can hold, so a
`Screen3D` belongs in a `Scene3D` and a `Screen2D` in a `Scene2D`; a `SceneUI`
accepts neither, because its object base is `UIObject`.

Three facts worth knowing:

* each screen owns a moderngl context, so a handful per scene is fine and a
  wall of fifty is not;
* a screen steps while the game runs. In the editor's Edit mode nothing is
  stepped, so a panel shows the last picture it had - black, at first.
  `warm()` steps the nested scene once for exactly that reason, and the Edit
  build calls it on every screen;
* a panel's frame often never reaches the CPU at all. When the nested rig
  shares the outer renderer's context - which it does whenever a project runs
  normally - the graded picture stays on the GPU and `nested.render()` hands
  back `None`. A scene written to paint its own chrome into that picture would
  crash on it, and the screen turns that crash into a blank panel, so anything
  a panel must show belongs in nodes. Override `render()` with a guard if a
  title band is genuinely wanted:

  ```python
  def render(self, camera=None):
      pic = super().render(camera)
      if pic is None:
          return None          # the frame stayed on the GPU
      caption(pic, self.game.fonts, "Console")
      return pic
  ```

  An `overlay=` hook, a `render()` override that reads the pixels back, or a
  standalone rig all bring the frame to the CPU, and then `render()`
  answers with real pixels - which is why a scene may see either.

## Pointing at a panel

A 3D world has no cursor, so nothing floats over the picture to click: the
engine aims instead. `Scene3D.handle_event` takes a mouse event, casts the
camera's ray through the pixel the event names - the middle of the window while
the player holds the mouse, where the crosshair is - and tries that ray against
every panel that answers `pickable()`:

```python
console = self.spawn(fe.Screen3D, (8.85, 1.95, 6.0), size=(3.6, 2.0),
                     showing="gallery_ui", input=True)
```

The nearest front-facing crossing wins. Wherever the ray met the glass is turned
into a pixel of the nested picture (`panel_uv`), the event is re-worded with
that position and handed through `send()`, and a `UIObject` behind the glass
takes the click exactly as it would in a window of its own. A motion event is
re-worded the same way, so a button under the aim lights up before it is
pressed.

| Member | Notes |
| --- | --- |
| `takes_input` (`input=`) | The switch: a panel that is only scenery never answers a ray |
| `pickable()` | Live, switched on and showing a scene - a blank panel is furniture |
| `panel_normal()` | The direction the picture faces, in world space |
| `panel_uv(world)` | A world point on that plane as one of the picture's pixels, or None when it misses the panel |
| `send(event)` | Forward one re-worded event; True when the nested scene took it |

When a panel takes a click, `input.consume(button)` lifts the button out of the
frame's pressed and released sets, so pressing a button on a monitor does not
also fire whatever the player has bound to the left mouse. A paused game, an
open menu and the caption are all answered by `Game.handle_event` before the
scene is asked, so none of them pick a panel either.

What the nested scene is host to is the same rule as ever: a `SceneUI` inside a
`Screen3D` holds `UIObject`s, and its own `game.screen` is the panel's pixel
size rather than the window's - which is how one scene fits both a wall in a
room and a window on a desktop.

## Saving a scene

```python
class Main(fe.Scene3D):
    def on_save(self, save):
        save.set("grove.crates", len(self.objects_of("crate")))
        save.flag("grove.visited")

    def on_load(self, save):
        if save.get("grove.crates"):
            for i in range(save.get("grove.crates")):
                self.spawn("crate", (i * 1.5, 0.0, 0.0))
```

`Game.save_game()` writes the camera transform and the scene name alongside
whatever your hooks put in the store. See
[Save, Config and Paths](save-config-and-paths.md).
