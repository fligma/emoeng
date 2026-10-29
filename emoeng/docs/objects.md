# Objects

Objects are the things a scene spawns. One base class carries the shared
machinery - tree, clone, timers, camera, disposal - and four flavours add their
own kind of content.

Nothing in this engine is a whole thing on its own. A prop is a *branch*: a
plain container that says where it is, with nodes hung under it that say what
it looks like, how much room it takes up and what it gives off.

| Class | `kind` | Lives in | Built from |
| --- | --- | --- | --- |
| `GameObject` | `'object'` | base class only | tree + lifecycle |
| `Object3D` | `'3d'` | `Scene3D` | meshes, models, lights in a metre world |
| `Object2D` | `'2d'` | `Scene2D` | one textured quad in world pixels |
| `UIObject` | `'ui'` | `SceneUI` | a clickable panel plus optional text label |
| `ModelObject` | - | any 3D scene | one project model as movable dynamic meshes |
| `Screen3D` | `'3d'` | `Scene3D` | a panel that shows another scene |
| `Screen2D` | `'2d'` | `Scene2D` | a sprite that shows another scene |
| `Entity3D` | `'3d'` | `Scene3D` | NPCs/enemies with AI, health, hitboxes |
| `Entity2D` | `'2d'` | `Scene2D` | 2D NPCs/enemies with AI, health, hitboxes |

The nodes that fill such a branch are `Model3D`, `Sprite2D`, `Collision3D`,
`Hitbox3D`, `Collision2D`, `Hitbox2D`, `LightNode3D` and `LightNode2D`. They
live in `engine.components`, are exported as `fe.*`, and are documented under
[Component nodes](#component-nodes) below.

The last four rows are *entities* rather than plain objects: a thing that is
scripted with state - health, a team, an AI mode, a hitbox it can be hit in -
is an `Entity3D` / `Entity2D`, and a `Player3D` / `Player2D` is the same
machinery pointed at a camera. Their documents live in `entities/` as
`.ent3d` / `.ent2d`, while the inert ones - a wall, a lamp, a screen, a shape -
stay in `objects/`. Nothing else about them is different: an entity is spawned,
cloned, parented, faded and despawned exactly like any other object, and it is
still built from nodes hung underneath it.

## `GameObject`

### Class attributes

| Attribute | Default | Meaning |
| --- | --- | --- |
| `kind` | `'object'` | `'3d'`, `'2d'`, `'ui'` in the subclasses |
| `name` | `'object'` | Display name; also the fallback tag |
| `uses` | `()` | Object stems this object spawns, checked at load |
| `clone_attrs` | `()` | Attribute names `clone()` hands to the new constructor |
| `clone_gap` | `(1.2,)` | Nudge applied when `clone()` gets no position |
| `look_camera` | `None` | The camera `give_camera()` / `use_camera()` handed to me |
| `is_player` | (subclass) | When true, the first spawn claims the view |
| `light_layer` | `None` | Which light layers may reach me; `None` is `all` (see `Light.layer`) |

### Instance state

| Attribute | Value |
| --- | --- |
| `scene`, `game`, `project`, `renderer` | Copies of the owning handles |
| `pos` | Mutable list of floats, length matching the scene kind |
| `look` | Placement a document or the `look=` keyword gave me, filled in before `build()` |
| `doc_key` | `"Torch#0"` - the name a document uses for this instance |
| `placed_id` | The `objects` id when a scene document placed me |
| `tag` | `tag` argument, else the lower-cased class name |
| `t` | Seconds since spawn, advanced by `update()` |
| `timers` | Per-object `Timers` |
| `alive` | Bool; `False` once despawned |
| `parent` | The object that spawned me |
| `clone_of` | The object I was cloned from |
| `children`, `clones` | Objects I spawned / objects cloned from me |
| `meshes` | `DynamicMesh` instances I own |
| `objects` | `ModelObject` instances I own |
| `lights` | `Light3D` / `Light2D` objects I added; `dispose()` takes them out of the scene |

### Lifecycle

The engine always constructs `cls(scene, pos=pos, **kw)`, then calls
`attach(...)` and `build()`. Keep `scene` and `pos` first in your signature.

| Hook | Called | Use it for |
| --- | --- | --- |
| `build()` | once, right after attach | Make geometry, register textures, spawn children |
| `update(dt)` | every frame while alive | Move, animate, poll input; call `super().update(dt)` to keep `t` and timers running |
| `set(pos=None)` | whenever you move it | Position write hook for subclasses |
| `dispose()` | on despawn and on a failed build | Free meshes, models and lights - owned lights go with me |

### Tree and clone queries

| Member | Returns |
| --- | --- |
| `is_clone` / `is_original` | bool |
| `clone_depth` | Clone hops from the original (0 = none); `depth` stays free for a solid's own size |
| `root` | The original this lineage started with |
| `lineage` | Ancestors from root down to my direct source, oldest first |
| `attach(parent=None, clone_of=None, tag=None)` | Link me; `scene.spawn` does this |
| `spawn(obj, pos=None, offset=None, tag=None, **kw)` | Spawn a child through the scene API |
| `clone(pos=None, tag=None, **overrides)` | A copy of me in the scene; `clone_gap` nudges when `pos` is omitted |
| `clone_kwargs()` / `clone_extra()` | The arguments a clone inherits / the type-specific ones always passed |
| `despawn()` | Remove me and everything I spawned or cloned |

### Nodes and parents

`children` holds whatever was filed under me and `parent` is who that is. A
node's numbers are relative: `local_pos` is the offset its parent sees, `pos`
is what that works out to in the world, and only the first is ever written
down by a document - so moving a brazier moves its flame, its light and its
hitbox, because they were placed against it and not against the room.

| Member | Returns / does |
| --- | --- |
| `parent` / `children` | Who I sit under / what sits under me |
| `local_pos` | My position in my parent's frame |
| `is_child_of(other)` | bool: under them, anywhere down my branch |
| `descendants()` / `ancestors()` | Everything under me / everyone above me |
| `tree_path()` | `"Crate#0/Model3D#0"` - my branch as words |
| `world_pos()` | Where I really am (`pos`, kept in step by `follow_parent()`) |
| `child_world(local)` / `child_local(world)` | Convert between a node's frame and the world - turned by my `yaw` in 3D, my `rot` in 2D, so a node stays glued to the face it was placed on |
| `push_local()` | After moving me in the world, rework my offset from my parent |
| `follow_parent()` | Put me where my parent now is, keeping that offset |
| `propagate()` | `follow_parent()` for every node under me |
| `add_child(obj, keep_place=False)` | File an object under me; by default its `pos` reads as a place next to me, with `keep_place=True` it stays where it stands and the offset is reworked |
| `remove_child(obj)` | Take a node off me and hand it back to the scene floor |
| `set_parent(parent)` | Move my whole branch under another object (`None` = the scene) |

Both `add_child()` and `set_parent()` refuse a cycle: nothing can be a node of
its own branch.

Three things keep a branch in step. `Scene.spawn(..., parent=obj)` files the
child as it attaches, so a script's `self.spawn(...)` needs no bookkeeping;
`set()` moves call `propagate()`; and `scene.sync_tree()` runs at the end of
every update, which the editor also calls straight after a drag so a model, a
light and a hitbox follow the prop without waiting a frame. Note that
`clone_depth`, `root` and `lineage` above count *clone* hops, not tree depth.

### The same tree, spelled the Godot way

The names a Godot user reaches for are all there, added on top of the ones
above rather than replacing them - each returns the same objects, so a script
may be written in either voice and the documents, the editor and
`scene.objects` keep working.

| Name | Answers to | Notes |
| --- | --- | --- |
| `get_parent()` | `parent` | None at the top of a branch |
| `get_children()` | `children` | A fresh list, so looping over it and freeing as you go is safe |
| `get_child(index)` / `get_child_count()` | `children[i]` / `len(children)` | Past the end answers None |
| `get_tree()` | `scene` | One tree per scene; a screen's nested scene is its own |
| `is_inside_tree()` | `alive` and being in `scene.objects` | |
| `get_node(path)` | a walk down `children` | `"."` is me, `".."` whoever I sit on, `"A/B#0"` a branch and a leading `/` asks the whole scene |
| `find_child(name)` / `find_children(name)` | filtered `children` | A name is the `id` a scene document placed, a document key, a tag or a class, so `find_children("Torch")` collects my torches |
| `queue_free()` | leaves at the end of the frame | The scene drains the queue once every live object has updated |
| `free()` | `despawn()` | The Godot word for leaving right now |
| `connect(name, fn)` / `disconnect(name, fn)` | `listen()` / `unlisten()` | `fn` is a callable - one argument hears the signal's name, two hear name and value - or an object plus the name of its hook |
| `emit(name, value=None)` | `broadcast(name, value)` | |

The scene spells them the same way: `scene.get_node("Enemy#0/Hitbox3D#0")`
looks across the live tree - roots first, then every node - and
`scene.find_by_name(name)` takes the first object that answers to a document
key, a tag or a class. A node a scene document placed also answers to the `id`
the document gave it, so `get_node("Lectern")` finds the entry the editor's
tree lists by that name, and `get_node("Lectern/Screen")` walks into it.
`queue_free()` is the one that is not simply a rename:
removing an object in the middle of a loop over `get_children()` would skip the
next one, so the request waits for the end of the frame. `broadcast` and
`listen` stay exactly as they were; every object with an `on_trigger(name,
value)` hook still hears it, and a `connect("door", fn)` listener is called
beside them.

### Cameras from an object

| Method | Signature | Notes |
| --- | --- | --- |
| `give_camera` | `give_camera(name=None, follow=True, offset=None, damping=0.0, active=True, **kw)` | Build a new camera registered on the scene, owned by me |
| `use_camera` | `use_camera(cam, follow=True, offset=None, damping=0.0, active=True)` | Drive an existing scene camera by name or object |
| `adopt_camera` | same as `use_camera` | The shared half of the two above |

Object-owned cameras leave with the object: `scene.despawn()` drops every camera
whose `owner` is that object.

### Timers and subsystem shortcuts

`obj.rng`, `obj.audio`, `obj.input`, `obj.save` and `obj.hud` proxy the
scene's. `obj.after(delay, func, ...)` and `obj.every(delay, func, ...)`
schedule on the object's own timers, so they stop when the object is
despawned. `obj.hud.text(...)` and the rest of the facade work from any
object, not only from the overlay - see [UI and HUD](ui-and-hud.md).

### Opacity

Every object carries one `opacity` in 0..1, and `set_opacity(value)` is how it
changes. It is the only look that works on every kind of geometry an object can
own - a `.model3d`, a sprite, a screen, a mesh made by hand - because the number
rides on the vertices themselves rather than on a material or a second pass:

```python
ghost.set_opacity(0.35)              # seen through, not standing in
scene.spawn("curtain", look={"opacity": 0.2})
scene.every(0.02, lambda: door.set_opacity(door.opacity - 0.01))
```

Three things follow from that, and all three are useful:

* **it moves layer by itself.** Solid world geometry asked to thin is drawn in
  the lit translucent pass, and a thinned thing faded back up goes home, so a
  script never picks a blend layer for the sake of a fade. `blend_for()` is the
  pair of rules.
* **it multiplies with the texture's own alpha.** A sheet's alpha is a thing's
  *shape* and `opacity` is its *solidity*; a cut-out sprite faded to 0.5 is a
  half-there cut-out, not a rectangle.
* **it reaches down the branch.** A parent's `set_opacity()` hands the number to
  the nodes under it, so ghosting a prop ghosts its picture, its label and its
  screen.

The one thing a change cannot reach is geometry already welded into the scene's
static batch - that was stamped at build. A live editor build replays the object
with the new number; in a game, say it before `build()` (a document, a
`spawn(look=...)`) or use `dynamic()` / `model_object()` for anything meant to
fade later.

## `Object3D`

Constructor: `Object3D(scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
tag=None, opacity=1.0)`; `clone_gap = (1.2, 0.0, 0.0)`,
`doc_knobs = ('opacity', 'shader')`.

| Member | Signature | Notes |
| --- | --- | --- |
| `add` | `add(data, texture='white', blend='opaque', opacity=None, shader=None)` | Static geometry queued into the scene batch; `opacity` left out reads the object's own; a `uv` `shader` keeps this mesh live |
| `dynamic` | `dynamic(data, texture='white', blend='add', view_model=False, on_top=False, opacity=None, shader=None)` | A `DynamicMesh` I own and can reshape each frame |
| `place_model` | `place_model(name, pos=None, yaw=None, scale=None, tint=None, opacity=None, shader=None)` | Stamp a `.model3d` statically; `shader` is a `texture` look baked into the sheet |
| `model_object` | `model_object(name, pos=None, yaw=None, scale=None, tint=None, texture=None, blend='opaque', opacity=None)` | A movable model instance |
| `light` | `light(pos=None, color=(1.0, 0.62, 0.24), shape=None, follow=False, offset=None, **kw)` | A `Light3D` in the scene, listed on `self.lights` and taken out again by `dispose()` |
| `ground` | `ground(x=None, z=None)` | `scene.ground_height` at my position |
| `set_camera` | `set_camera(height=1.7, fov=72.0, near=None, far=None, roll=None, **opts)` | Ride me: the eye sits `height` above my ground |
| `set` | `set(pos=None, yaw=None, scale=None, opacity=None)` | Write transform and solidity |
| `set_opacity` | `set_opacity(value)` | Fade me and my nodes; see [Opacity](#opacity) |
| `set_shader` | `set_shader(name_or_None)` | Wear a `uv` or `texture` shader the project owns by stem; a `screen` name is refused with one log line, `None` clears it - see [Shaders](shaders.md) |
| `look` | `look(yaw, pitch)` | Turn me |
| `move` | `move(wish, run, dt)` | `wish` is `(x, z)` world input; slides along the ground |
| `eye` | | The look-from point |

```python
class Brazier(fe.Object3D):
    name = "brazier"
    uses = ("flame",)
    clone_attrs = ("size", "tint")
    clone_gap = (2.4, 0.0, 0.0)

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 size=1.0, tint=(0.8, 0.5, 0.2)):
        super().__init__(scene, pos, yaw, scale)
        self.size = float(size)
        self.tint = tint

    def build(self):
        self.place_model("brazier", self.pos, scale=self.size)
        self.lamp = self.light(pos=(self.pos[0], self.pos[1] + 1.2,
                                    self.pos[2]), color=self.tint,
                               radius=9.0, flicker=0.26, glow=0.9)
        self.flame = self.spawn("flame", offset=(0.0, 1.1, 0.0))

    def update(self, dt):
        super().update(dt)
        self.lamp.kelvin(1600 + 400 * math.sin(self.t * 0.7))
```

`dispose()` removes every light in `self.lights`, so a despawned prop never
leaves a lamp hanging in the room. Anything `lights.Light3D` takes works as a
keyword here - `radius`, `energy`, `atten`, `angle`, `inner`, `glow`, `cookie`,
`pulse`, `layer`, `priority`, `tag` - and `follow=True` hands the light to the
object itself, with `offset` in metres (`local=True` reads it as the object's
own axes) and `align=True` turning it to match. See
[Lighting](lighting.md).

## `Object2D`

Constructor:

```python
Object2D(scene, pos=(0.0, 0.0), size=(64.0, 64.0), texture='white',
         col=(1.0, 1.0, 1.0), rot=0.0, anchor=(0.5, 0.5), grid=(1, 1),
         frame=0, uv=None, flip=False, tag=None, blend='alpha',
         opacity=1.0)
```

| Parameter | Meaning |
| --- | --- |
| `size` | World pixels wide and tall |
| `texture` | Texture key, or a colour - `"#7f8aa3"`, `"gold"` and `(60, 122, 214)` all paint a solid sheet; `'white'` is a 1x1 and shows `col` alone |
| `col` | Linear RGB multiply |
| `rot` | Radians |
| `anchor` | `(0.5, 0.5)` centres on `pos`; `(0, 0)` puts `pos` at the top-left |
| `grid` | `(cols, rows)` - turns one image into a sprite sheet |
| `frame` | Cell index inside `grid` |
| `uv` | Explicit `(u0, v0, u1, v1)`, overriding `grid`/`frame` |
| `flip` | Mirror horizontally |
| `blend` | `'alpha'` or `'add'` |
| `opacity` | 0..1 solidity - see [Opacity](#opacity). A flat layer is already blended, so thinning a sprite draws it thinner rather than moving it, and its `col`'s fourth number does the same job |

| Member | Signature | Notes |
| --- | --- | --- |
| `cell_uv` | | The window currently shown, in image space |
| `quad` | | The `meshes.quad2d` for this frame |
| `set` | `set(pos=None, size=None, col=None, rot=None, texture=None, anchor=None, uv=None, flip=None, opacity=None)` | Any subset; the mesh is rebuilt |
| `move` / `move_to` | `move(dx=0.0, dy=0.0)` / `move_to(x=None, y=None)` | Position |
| `set_frame` | `set_frame(index)` | Pick a sprite-sheet cell |
| `animate` | `animate(fps=8.0, frames=None)` | Cycle cells; `frames` are indices (default: all of them) |
| `light` | `light(pos=None, color="torch", shape="radial", radius=None, follow=False, offset=None, **kw)` | A `Light2D` drawn into the scene's light mask, removed by `dispose()`; `radius` defaults to this sprite's own size |
| `rect` / `contains` | | Axis-aligned box in world pixels; point test |
| `clone_attrs` | `('size', 'texture', 'grid', 'anchor')` | What a copy inherits |
| `clone_gap` | `(32.0, 0.0)` | |

```python
class Coin(fe.Object2D):
    name = "coin"
    def build(self):
        self.set(texture="coins", grid=(8, 1))
        self.animate(fps=12.0)
        self.lamp = self.light(color="gold", soft=0.5, pulse=0.3,
                               follow=True, cast=False)
    def update(self, dt):
        super().update(dt)
        self.move(dy=-40.0 * dt)
```

`follow=True` rides the sprite; `align=True` turns a `cone`, `ring` or `rect`
with its `rot`, which is what a field of view wants, and `cast` (on by
default) lets the scene's `blockers` hide what is behind them.

## `UIObject`

`UIObject` is an `Object2D` that answers the mouse. Hover, press and click are
routed by the scene; either pass a callable as `action` or override `on_click`.

```python
UIObject(scene, pos=(0.0, 0.0), size=(160.0, 40.0), text='',
         color=(0.16, 0.42, 0.78), hover_color=None, press_color=None,
         text_color=(1.0, 1.0, 1.0), font_size=18, font_name='tahoma',
         texture='white', anchor=(0.5, 0.5), enabled=True, action=None,
         tag=None, **kw)
```

| Member | Notes |
| --- | --- |
| `set_text(text)` | Re-renders the label texture |
| `set(...)` | All `Object2D` fields plus `text`, `color`, `enabled` |
| `click()` | Fire the click callbacks - safe to call from code |
| `on_click` / `on_hover` / `on_leave` | Override in a subclass |
| `handle_event(e, world_pos)` | Called by the scene with a mouse event |
| `clone_attrs` | `('size', 'text', 'color', 'font_size', 'anchor')` |
| `clone_gap` | `(0.0, 40.0)` - copies stack downward |

`hover_color` and `press_color` default to `None`, which means that state keeps
the base colour; `_state_color()` picks press, then hover, then base, and
`_apply_state()` rebuilds the quad only when the colour actually changes.
`click()` runs the `action` callable first and then `on_click()`.
Every colour here takes any spelling `fe.colors` reads, so
`color="#26364a"` and `color=(0.15, 0.21, 0.29)` are the same button.
Widgets default to the `hud` blend layer, which the renderer draws after the
2D light mask - a menu stays readable in a dark room.

```python
class Toggle(fe.UIObject):
    def build(self):
        super().build()
        self.set_text("Sound: on")

    def on_click(self):
        self.on = not getattr(self, "on", True)
        self.set_text(f"Sound: {'on' if self.on else 'off'}")
        self.scene.game.audio.set_master(0.8 if self.on else 0.0)
```

## `ModelObject`

A project model drawn as one dynamic mesh per surface, not a scene object - you
get one from `scene.model_object(...)` or `obj.model_object(...)`.

```python
ModelObject(scene, model, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
            tint=None, texture=None, blend='opaque', opacity=1.0)
```

| Member | Notes |
| --- | --- |
| `set(pos=None, yaw=None, scale=None)` | Move and turn; the GPU meshes are re-uploaded |
| `set_surface(face, key)` | Retexture one face on this instance - a sheet name or a colour (`None` = the model default) |
| `set_opacity(opacity)` | Fade the instance; its meshes are re-uploaded, not rebuilt |
| `update(dt=0.0)` | Hook; nothing moves unless you move it |
| `dispose()` | Release the GPU meshes |

```python
door = scene.model_object("door", (0.0, 0.0, -4.0))
scene.every(0.02, lambda: door.set(yaw=door.yaw + 0.05))
```

## Screens

A screen is an object like any other, except that what it draws is another
scene: `Screen3D` in a `Scene3D`, `Screen2D` in a `Scene2D`. The picture is the
nested scene's live frame, so the script attached to the panel can switch it,
dim it, tint it, mask it, forward input to it and place its sound in the room.

```python
class Screen(fe.Screen3D):          # scripts/objects/screen.py, type "screen3d"
    channel = "menu"                # shown when no document says otherwise

    def build(self):
        super().build()
        self.set_audio("emitter", gain=0.8, reach=14.0)
```

`name=` - or the document's `showing` - picks the scene, and every knob is a
method: `show`, `set_on`, `set_brightness`, `set_tint`, `set_shape`,
`set_post`, `set_audio`, `audio_gain`, `send` and `overlay`.
[Scenes](scenes.md) carries the whole keyword and method table.

The panel is a *thing in the room*: a thin box standing `depth` metres proud of
the plane it was placed on, drawn on the `panel` layer - depth-tested, so it
hides what hangs behind it, and neither lit nor fogged, because a monitor makes
its own light. That is what keeps a dark picture black instead of a window onto
the wall behind it. Two ways to argue with it: `glow=True` draws the picture
additively instead, which is a real choice for a screen in a pitch-dark corridor
or a hologram meant to have no back, and costs you the darks - an additive panel
adds itself to the wall, so the wall shows straight through it. And `opacity`
fades the whole panel, which is how glass and a dying monitor are done.

## Component nodes

The nodes a branch is built out of live in `engine.components` and are exported
as `fe.*`. Each does one job, each is createable from the editor's Add Node
list with no Python written at all, and each states in `doc_knobs` which
attributes a document may write - so nothing private to a script leaks into the
file.

| Node | Base | One job | `doc_knobs` |
| --- | --- | --- | --- |
| `Model3D` | `Object3D` | Draw one `models/<name>.model3d` at the node's own transform | `tint`, `blend`, `stamp`, `opacity`, `shader` |
| `Sprite2D` | `Object2D` | One quad, or every part of a `models/<name>.model2d` rig with its tracks playing | `playing`, `speed`, `opacity`, `shader` |
| `Collider3D` | `Object3D` | The shape the two solid 3D nodes share: a box, a sphere or a capsule | `shape`, `half`, `solid`, `group`, `offset` |
| `Collision3D` | `Collider3D` | Stops movers. Invisible in the game, a translucent blue gizmo in Edit | the same five |
| `Hitbox3D` | `Collider3D` | Stops nothing and reports who is in it | plus `notice`, `oneshot` |
| `Collision2D` | `Object2D` | A rect in a pixel world that a 2D mover cannot pass | `solid`, `group` |
| `Hitbox2D` | `Collision2D` | The flat trigger | plus `notice`, `oneshot` |
| `LightNode3D` | `Object3D` | A light that rides the node it hangs on | `shape`, `color`, `radius`, `energy`, `angle`, `inner`, `layer`, `glow`, `flicker`, `pulse`, `enabled` |
| `LightNode2D` | `Sprite2D` | The flat twin, drawn into the scene's light mask | `shape`, `color`, `radius`, `energy`, `angle`, `cast`, `outer`, `enabled` |

A plain `Object3D` or `Object2D` is a legal node as well, and the useful one:
it draws nothing on its own, which is exactly what makes it the thing a
picture, a shape and a lamp get hung from.

### Shapes, movers and triggers

`Collider3D` owns no geometry - a wall of them can cover a level while the
picture of that level stays somebody else's job. Everything else about it comes
from `box()`, the `(centre, half)` pair a sweep tests:

| Member | Notes |
| --- | --- |
| `shape`, `half`, `offset` | `box` \| `sphere` \| `capsule`; metres from the centre to each face; where the shape sits relative to the node, so a picture's pivot and its feet can disagree without either being moved |
| `centre()` / `box()` / `radius()` | The world middle; the `(centre, half)` a sweep tests, scaled by the node; the one number a round shape needs |
| `contains(point)` / `touches(other)` | Is a world point in me; does another `box()` overlap me |
| `gizmo(col=None)` | The translucent `MeshData` the Edit view draws, faces outward so you can see through it; `GIZMO` is its colour |
| `solid` / `group` | `False` reports and never stops; `group` says whose move this shape blocks - `""` stops everybody, a name blocks only the movers that use it |
| `build()` / `dispose()` | File me in `scene.colliders`, and take the filing off when I go |

The scene does the rest: `add_collider` / `remove_collider`, `colliders_of(group,
solid=None)` for the nodes a mover should reckon with, `collider_boxes` /
`collider_rects` for their shapes, `move_body` / `move_body2d` to sweep a body
through them, and `hits_at(point)` for the triggers covering a spot. A
`Player3D`'s move already goes through that sweep with its own `body_half` and
`collide_group`, so a wall placed in the editor is a wall in the game with no
script anywhere. See [Collision](collision.md).

A `Hitbox3D` keeps `inside` - the bodies in it right now - and calls
`on_enter(other)` / `on_exit(other)` at most once each per body, because a door
that locked itself twelve times because the player stood still is not a door, it
is a stutter. `notice` says whose bodies to watch, and `watching()` is the list
it picks out:

| `notice` | Watches |
| --- | --- |
| `""` (default) | The scene's player |
| a tag or a class name | Every live object matching it |
| `"*"` | Everything the scene holds, except me |

`oneshot = True` fires once and then stops watching, and `body_of(obj)` is the
box an object presents - its own shape if it has one, a `body_half` guess if
not. A script reads a hitbox its document placed by walking `self.children`.

### Hanging nodes from a script

The same branch can be built in code. `self.spawn(...)` parents the child to me
by itself: the position you give is the world position, and the offset from my
parent is worked out from it.

```python
class Crate(fe.Object3D):
    name = "crate"

    def build(self):
        self.spawn(fe.Model3D, pos=self.pos, model="crate")
        self.spawn(fe.Collision3D, pos=(self.pos[0], 0.9, self.pos[2]),
                   half=(0.9, 0.9, 0.9))
```

Placed from the page, the scene document writes that branch as `children`, one
entry per node - see [Scenes](scenes.md).

## Documents (`objects/*.obj3d`, `entities/*.ent3d`)

An object has two files, and the extension says which world the thing lives in:
`objects/torch.obj3d` beside `scripts/objects/torch.py`, or
`objects/lantern.obj2d` for a sprite in a flat scene. The script is the class,
the document is where it sits and how it looks. `Project.object()` reads both
and hangs the document's look fields on the class as `look_defaults`, so a plain
`self.spawn("torch")` already lands where the document says.

An entity is the same pair in the other folder: `entities/guard.ent3d` beside
`scripts/entities/guard.py`, read by `Project.entity()`. The folder is decided
by the extension and the extension by the `type` - `scenedoc.doc_family(type)`
asks the registry which family a node type belongs to, and `doc_ext(type)`
answers the spelling - so a `player3d` document is written as
`entities/visitor.ent3d` and never as `objects/visitor.obj3d`. A name is
resolved from either folder: `self.spawn("guard")`, a scene document's
`"object": "guard"` and a `uses = ("guard",)` entry all look in `entities/`
first and `objects/` after, so moving a thing between the two folders changes
no script.

```json
{
 "format": 1,
 "name": "torch",
 "type": "object3d",
 "script": "scripts/objects/torch.py",
 "pos": [0.0, 0.0, 0.0],
 "yaw": 0.0,
 "scale": 1.0
}
```

A document with no `script` is a whole object too: its `type` names one of the
engine's own nodes and there is no Python to write. That is how a level gets
filled from the page, and a script is only written when something has to
*happen*.

```json
{
 "format": 1,
 "name": "lantern",
 "type": "sprite2d",
 "model": "lantern",
 "pos": [36.0, 40.0]
}
```

| Field | Holds |
| --- | --- |
| `type` | The node the file makes - see the table below |
| `script` | The project-relative `.py`; the document's own stem is tried when it is missing, and with no script at all the `type` alone builds the node. An entity's stem is looked for under `scripts/entities/` |
| `pos` | Three numbers for a `.obj3d` / `.ent3d`, two for a `.obj2d` / `.ent2d` |
| `yaw`, `scale` | The solid world's turn and size |
| `rot`, `size` | The flat world's turn and box |
| `model`, `texture`, `color` | Optional look fields: a `models/<name>.model3d` or `.model2d` stem, a sheet, a tint |
| `shader` | A `uv`/`texture` look by stem; a `models`/`textures`/`shaders` slot in the editor lists the project's files and the built-ins to pick from |
| `showing` | A screen's scene - the keyword the screen's own constructor calls `name` |
| `knobs` | What the node owns beyond a transform - a shape, a reach, a picture - set straight onto it before `build()` |
| `nodes` | The document's own branch (a label, a shape), filed the way a scene files `objects`; grafted under every placement |

Every type you can create is one row of `scenedoc.NODE_TYPES`, which the
editor's Create New Node dialog, the file extension and the Blocks drawer
all read, so a new node type is one line added to a table rather than
three places changed.

| `type` | Label | Group | Stored as | Built by |
| --- | --- | --- | --- | --- |
| `object3d` | Object3D | Objects | `.obj3d` | `Object3D` |
| `object2d` | Object2D | Objects | `.obj2d` | `Object2D` |
| `ui` | UIObject | Objects | `.obj2d` | `UIObject` |
| `model3d` | Model3D | Pictures | `.obj3d` | `Model3D` |
| `sprite2d` | Sprite2D | Pictures | `.obj2d` | `Sprite2D` |
| `collision3d` | Collision3D | Physics | `.obj3d` | `Collision3D` |
| `hitbox3d` | Hitbox3D | Physics | `.obj3d` | `Hitbox3D` |
| `trigger3d` | Trigger3D | Physics | `.obj3d` | `Trigger3D` |
| `collision2d` | Collision2D | Physics | `.obj2d` | `Collision2D` |
| `hitbox2d` | Hitbox2D | Physics | `.obj2d` | `Hitbox2D` |
| `trigger2d` | Trigger2D | Physics | `.obj2d` | `Trigger2D` |
| `entity3d` | Entity3D | Entities | `.ent3d` | `Entity3D` |
| `entity2d` | Entity2D | Entities | `.ent2d` | `Entity2D` |
| `player3d` | Player3D | Entities | `.ent3d` | `Player3D` |
| `player2d` | Player2D | Entities | `.ent2d` | `Player2D` |
| `camera3d` | Camera3D | Views | `.obj3d` | only code |
| `camera2d` | Camera2D | Views | `.obj2d` | only code |
| `screen3d` | Screen3D | Views | `.obj3d` | `Screen3D` |
| `screen2d` | Screen2D | Views | `.obj2d` | `Screen2D` |
| `light3d` | Light3D | Lights | `.obj3d` | `LightNode3D` |
| `omnilight3d` | OmniLight3D | Lights | `.obj3d` | `OmniLight3D` |
| `spotlight3d` | SpotLight3D | Lights | `.obj3d` | `SpotLight3D` |
| `directionallight3d` | DirectionalLight3D | Lights | `.obj3d` | `DirectionalLight3D` |
| `light2d` | Light2D | Lights | `.obj2d` | `LightNode2D` |
| `pointlight2d` | PointLight2D | Lights | `.obj2d` | `PointLight2D` |
| `conelight2d` | ConeLight2D | Lights | `.obj2d` | `ConeLight2D` |
| `rectlight2d` | RectLight2D | Lights | `.obj2d` | `RectLight2D` |
| `audio3d` | AudioEmitter3D | Audio | `.obj3d` | `AudioEmitter3D` |
| `audio2d` | AudioEmitter2D | Audio | `.obj2d` | `AudioEmitter2D` |
| `text3d` | Text3D | Text | `.obj3d` | `Text3D` |
| `text2d` | Text2D | Text | `.obj2d` | `Text2D` |
| `timer3d` | Timer3D | Utility | `.obj3d` | `Timer3D` |
| `timer2d` | Timer2D | Utility | `.obj2d` | `Timer2D` |
| `marker3d` | Marker3D | Utility | `.obj3d` | `Marker3D` |
| `marker2d` | Marker2D | Utility | `.obj2d` | `Marker2D` |

Each preset node also owns its Blocks drawer: `blocks.TYPE_CATEGORIES`
lists the drawers one type may use, so an emitter only ever offers sound
and language blocks, a light only light and language blocks, and so on -
see [Blocks](blocks.md).

The stored-as column is the point of the split: a `Collision2D` has no
business in a solid world, and `scenedoc.doc_ext(type)` is what turns a type
into the extension its documents use - `object_ext()` and `entity_ext()` are
its two halves. `scenedoc.OBJECT_TYPES` is the same rows
without the family and the class, for a reader that only wanted the labels.
Where a script defines a class, that class decides behaviour; the type still
says which scene kind can host it, which folder its document is written into
and which drawer draws it, and
[Blocks](blocks.md) picks its drawers from it.

`Project.upgrade_documents()` renames a project's legacy `.object` and `.model`
files for you when it opens, reading each document's `type` to work out which
half an `.object` was, and moves an entity left in `entities/` with an object's
extension onto `.ent3d` / `.ent2d`. A `.scene` can place the same object, in
which case its own entry overrides the object document's defaults, and a
`look=` keyword at the spawn site overrides both - see [Scenes](scenes.md).

## `Entity3D`

A base class for 3D NPCs, enemies - and, through `Player3D`, players. Health,
AI, teams, attack timing and the hitbox it can be hit in all come from one
mixin, `EntityBehaviour`, mixed in above `Object3D`; the same mixin makes
`Entity2D`. What differs between the worlds is answered by the class underneath
- which two axes it walks on, how it turns, which colliders it may wear - so
both halves of every table below mean the same thing in metres and in pixels.

Constructor: `Entity3D(scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
tag=None, opacity=1.0, **knobs)`; `clone_gap = (2.0, 0.0, 0.0)`,
`clone_attrs = ('health', 'max_health', 'ai_type', 'ai_config', 'hitbox_shape', 'hitbox_half')`.

The knobs a document may set on me are those same names, so an
`entities/guard.ent3d` carrying `"health": 40, "ai_type": "patrol"` is applied
before `build()` with no script at all.

### Health system

| Attribute | Default | Meaning |
| --- | --- | --- |
| `health` | `100.0` | Current health |
| `max_health` | `100.0` | Maximum health |
| `invulnerable_time` | `0.0` | Seconds of invulnerability after taking damage |

| Method | Signature | Notes |
| --- | --- | --- |
| `take_damage` | `take_damage(amount, source=None)` | Apply damage; calls `on_hit` or `on_death` |
| `heal` | `heal(amount)` | Restore health up to `max_health` |
| `die` | `die(source=None)` | Called when health reaches 0; calls `on_death` then `dispose()` |
| `on_hit` | `on_hit(source)` | Override: called when damaged but not killed |
| `on_death` | `on_death(source)` | Override: called when killed |

### AI system

| Attribute | Default | Meaning |
| --- | --- | --- |
| `ai_type` | `'none'` | `'none'`, `'follow'`, `'patrol'`, `'wander'`, `'aggro'` |
| `ai_config` | `{}` | Dict of AI-specific settings (e.g. waypoints for patrol) |
| `ai_state` | `'idle'` | Current AI state (internal) |
| `ai_target` | `None` | What the AI is targeting (usually `self.scene.player`) |
| `ai_timer` | `0.0` | Timer for AI decisions |

Every one of these is copied onto the instance as it is built. A patrol keeps
its `current_waypoint` in `ai_config`, and a wanderer its destination, so a
class-level dict shared by every guard would hand one guard's waypoint to the
next; `EntityBehaviour.__init__` copies `ai_config`, `hitbox_half`,
`hitbox_size` and `move_speed` first, which is why two entities of one class
walk different routes.

| AI Type | Behavior |
| --- | --- |
| `none` | No AI, entity sits still |
| `follow` | Moves toward `ai_target` at walk speed |
| `patrol` | Walks between waypoints in `ai_config["waypoints"]` |
| `wander` | Picks random destinations every few seconds |
| `aggro` | Idle until player in `aggro_range`, then chase and attack |

### Combat

| Attribute | Default | Meaning |
| --- | --- | --- |
| `team` | `'neutral'` | `'player'`, `'enemy'`, `'neutral'`, `'friendly'` |
| `aggro_range` | `10.0` | Distance to start chasing (metres) |
| `deaggro_range` | `20.0` | Distance to lose interest |
| `attack_range` | `1.5` | Distance to attack |
| `attack_damage` | `10.0` | Damage per attack |
| `attack_cooldown` | `1.0` | Seconds between attacks |
| `attack_timer` | `0.0` | Internal cooldown timer |
| `move_speed` | `(3.0, 6.0)` | `(walk, run)` speed in m/s |

| Method | Notes |
| --- | --- |
| `_perform_attack()` | Override to implement actual attack logic; default calls `take_damage` on `ai_target` |

### Hitbox

| Attribute | Default | Meaning |
| --- | --- | --- |
| `hitbox_shape` | `'box'` | `'box'`, `'sphere'`, `'capsule'` |
| `hitbox_half` | `(0.5, 1.0, 0.5)` | Half-extents for box shape |
| `hitbox_radius` | `0.5` | Radius for sphere/capsule |
| `hitbox_height` | `2.0` | Height for capsule |

The hitbox is automatically created as a non-solid `Collider3D` in the `"entity"` group when the entity is built.

### One call per knob

Each number above can also be set with a single call, and each call hands back
`self` so several can be chained. These are what the Blocks palette lowers to
- a block that writes two attributes in one line can never be read back as a
block, and a block that makes one call can - but they are ordinary methods and
a script is free to use them:

| Call | Sets |
| --- | --- |
| `set_health(value)` | `health`; reaching 0 kills me, as losing the last of it in a fight does |
| `set_max_health(value)` | `max_health`, trimming what I have now to fit |
| `set_team(name)` | `team` |
| `set_ai(ai_type, config=None)` | `ai_type` and, when given, `ai_config`; I start the new behaviour fresh |
| `set_ai_target(target)` | `ai_target` |
| `set_aggro_range(distance, deaggro=None)` | `aggro_range`, and `deaggro_range` (twice the reach when left out) |
| `set_attack(range=None, damage=None, cooldown=None)` | `attack_range`, `attack_damage`, `attack_cooldown`; only the ones given move |
| `set_move_speed(walk, run=None)` | `move_speed` - a pair for 3D, one number for 2D, where `run` is the `run_ratio` step instead |
| `set_hitbox(shape, half=None, radius=None, height=None)` | my 3D collider, rebuilt to the new shape |
| `set_hitbox2d(shape, size=None, radius=None)` | my flat collider, rebuilt to the new shape |

| Read | Answers |
| --- | --- |
| `is_dead()` | `health <= 0` |
| `distance_to(other)` | How far another object stands, measured on my plane |
| `take_damage(amount, source=None)` | Apply damage; True when it landed |
| `heal(amount)` | Restore health |
| `kill(source=None)` | Out of health at once: my death runs, then I go |
| `die(source=None)` | What the last point of health calls: `on_death`, then `dispose()` |

### Example

```python
class Goblin(fe.Entity3D):
    name = "goblin"
    health = 80.0
    max_health = 80.0
    ai_type = "aggro"
    aggro_range = 12.0
    attack_range = 2.0
    attack_damage = 12.0
    move_speed = (2.5, 6.0)
    hitbox_shape = "capsule"
    hitbox_radius = 0.4
    hitbox_height = 1.6

    def build(self):
        # A simple capsule body
        self.add(meshes.capsule(centre=(0, 0.8, 0), radius=0.4, height=1.6,
                                col=(0.4, 0.6, 0.3)), texture="white")

    def on_hit(self, source):
        # Flash red when hit
        self.flash_hit()

    def on_death(self, source):
        # Drop loot
        self.scene.spawn("coin", pos=self.pos)
```

## `Entity2D`

A base class for 2D NPCs and enemies, and the flat half of the same
`EntityBehaviour` mixin - so the health, AI, combat and one-call setter tables
above are this class's tables, in world pixels and with a rect or a circle for
a hitbox. Inherits from `Object2D`.

Constructor:
```python
Entity2D(scene, pos=(0.0, 0.0), size=(64.0, 64.0), texture='white',
         col=(1.0, 1.0, 1.0), rot=0.0, anchor=(0.5, 0.5), grid=(1, 1),
         frame=0, uv=None, flip=False, tag=None, blend='alpha',
         opacity=1.0, **knobs)
```

### Health system

Same as `Entity3D`: `health`, `max_health`, `invulnerable_time`, `take_damage`,
`heal`, `kill`, `die`, `is_dead`, `distance_to`, `on_hit`, `on_death` - and the
same one-call setters, with `set_hitbox2d(shape, size=None, radius=None)` in
place of `set_hitbox`.

### AI system

Same AI types as `Entity3D` but in 2D world pixels:
- `follow`: moves toward target
- `patrol`: walks between waypoints
- `wander`: random destinations
- `aggro`: chases and attacks player

AI config works the same way, using `self.ai_config`.

### Combat

| Attribute | Default | Meaning |
| --- | --- | --- |
| `team` | `'neutral'` | Team affiliation |
| `aggro_range` | `200.0` | Pixels to start chasing |
| `deaggro_range` | `400.0` | Pixels to lose interest |
| `attack_range` | `32.0` | Pixels to attack |
| `attack_damage` | `10.0` | Damage per attack |
| `attack_cooldown` | `1.0` | Seconds between attacks |
| `move_speed` | `100.0` | Pixels per second |

### Hitbox

| Attribute | Default | Meaning |
| --- | --- | --- |
| `hitbox_shape` | `'rect'` | `'rect'` or `'circle'` |
| `hitbox_radius` | `24.0` | Radius for circle |
| `hitbox_size` | `(48.0, 48.0)` | Width/height for rect |

Hitbox is created as a non-solid `Collider2D` in the `"entity"` group.

### Example

```python
class Slime(fe.Entity2D):
    name = "slime"
    health = 50.0
    max_health = 50.0
    ai_type = "wander"
    hitbox_shape = "circle"
    hitbox_radius = 20.0
    move_speed = 60.0

    def build(self):
        look = self.look if isinstance(self.look, dict) else {}
        col = look.get("color") or (0.3, 0.7, 0.9)
        self.set(texture="slime", col=col)
        super().build()

    def on_death(self, source):
        # Split into two smaller slimes
        for _ in range(2):
            self.scene.spawn("slime_small", pos=self.pos)
```

## What the scene keeps

`scene.objects` is the live list, iterated in spawn order every frame - a
node's own entries are in it as well, which is why `obj.children` says who
holds whom. Use `scene.objects_of("crate")` to find instances of one class or
file - the name is looked for in `entities/` first and then in `objects/`, so
`objects_of("guard")` finds the guard wherever its document ended up - and
`scene.by_tag("door_front")` for a single named one. Tags default to
the lower class name, so set one explicitly when two instances must be told
apart. `scene.colliders` is the parallel list of filed shape nodes, and
`scene.player` the object that claimed the view. Anything marked by
`queue_free()` leaves `objects` once the frame's updates are done, before the
draw.
