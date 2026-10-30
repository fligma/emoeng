# Blocks

The Blocks tab shows a `.py` file as a graph of nodes and writes it back as
Python. There is no second file format: the tab renders source text and saves
the same file the Code tab shows, so the two views are two windows on one file.

| Module | Role |
| --- | --- |
| `emoeng.editor.blocks` | The model: reads source into blocks with `ast`, writes blocks back to source. No pygame, no UI |
| `emoeng.editor.blocktab` | The view: measures the tree as nodes, wires them up, handles mouse and keys, keeps undo history |

```python
from emoeng.editor import blocks
module = blocks.parse(open("scripts/scenes/main.py",
                           encoding="utf-8").read())
print(module.summary(), module.counts())
print(module.render())          # the source text again
```

## How the model works

`parse()` builds an `ast` tree, and every statement becomes a `Block` of the
kind that fits it. Anything the model has no shape for becomes a `raw` block
holding plain text, so no code is ever hidden or dropped. Nested statements
become nested stacks, so a block tree mirrors the indentation of the file.

Three things decide how a block reads and is written:

* **shape** - how the tab paints it and what may sit next to it;
* **slots** - the holes in its words, which you click to type into;
* **bodies** - the nested stacks it owns, and what each one means when empty.

`Block.shape` is derived, not stored: a `def` whose name is in `blocks.HOOKS`
is a `hat`, a block with bodies is a `branch`, `raw` and `note` are `raw`, and
everything else takes the shape its `Spec` declares.

## Shapes

| Constant | Value | Meaning |
| --- | --- | --- |
| `STACK` | `stack` | A command; another statement may follow it |
| `CAP` | `cap` | Ends a stack: `return`, `break`, `continue`, `raise` |
| `BRANCH` | `branch` | Wraps one or more nested stacks |
| `HAT` | `hat` | An engine hook - nothing runs above it |
| `RAW` | `raw` | Verbatim Python the model does not restructure |

## Body modes

| Constant | Behaviour when the stack is empty |
| --- | --- |
| `REQUIRED` | Renders `pass`, so the file stays valid Python |
| `OPTIONAL` | Its keyword disappears too - no bare `else:` in the output |
| `CHAIN` | Brings its own keyword at the parent's level: `elif` |
| `SAME` | Sits beside its parent at the same indent: the `except` clauses |

| Block | Body names | Modes |
| --- | --- | --- |
| `if` | `then`, `alt` | `REQUIRED`, `CHAIN` (`else`) |
| `each` | `body`, `alt` | `REQUIRED`, `OPTIONAL` (`else`) |
| `while` | `body`, `alt` | `REQUIRED`, `OPTIONAL` (`else`) |
| `guard` | `body` | `REQUIRED` |
| `try` | `body`, `handlers`, `else`, `final` | `REQUIRED`, `SAME`, `OPTIONAL` (`else`), `OPTIONAL` (`finally`) |
| `except` | `body` | `REQUIRED` |
| `def` | `body` | `REQUIRED` |
| `class` | `body` | `REQUIRED` |

## Slots

A slot is one hole in a block's words. The tab edits it by its kind, and
`Block.check()` parses it by the same rule.

| Constant | Value | Holds |
| --- | --- | --- |
| `SLOT_VALUE` | `value` | One expression |
| `SLOT_TARGET` | `target` | An assignment or loop target |
| `SLOT_LIST` | `list` | Comma-separated names |
| `SLOT_NAME` | `name` | A single identifier |
| `SLOT_TEXT` | `text` | Free words - a keyword or an operator |
| `SLOT_CODE` | `code` | Free Python text |

`blocks.SLOT_KIND` maps slot names to those kinds; a name that is not listed is
free text. The declared mappings are `test`, `value`, `seq`, `items`, `expr`,
`types`, `cause`, `message` (value), `bases`, `names`, `args` (list), `target`,
`targets` (target), `name`, `type` (name), `op`, `word`, `src` (text) and
`decorators`, `code` (code).

`blocks.WORDS` lists the choices a keyword slot cycles through when you click
it: `if` → `if`/`elif`, `each` → `for`/`async for`, `guard` →
`with`/`async with`, `def` → `def`/`async def`, `global` →
`global`/`nonlocal`. `blocks.OPS` spells every augmented-assign operator for
the `bump` block's `op` slot (`+=`, `//=`, `|=`, `@=` and the rest).

## Categories

Sixteen drawers, in the order the tab lists them: `blocks.CATEGORIES` is
`events`, `trigger`, `scene`, `object`, `entity`, `light`, `audio`, `ui`,
`shader`, `input`, `save`, `control`, `data`, `functions`, `modules`, `code`.
The palette column paints one colour per drawer
(`blocktab.CATEGORY_COLORS`), deepened by 18% in the light theme so the same
fills stay readable in both.

| Category | Colour (dark theme) | Holds |
| --- | --- | --- |
| `events` | `(255, 173, 31)` | the hook hats, built from `HOOK_ROWS` |
| `trigger` | `(232, 96, 140)` | broadcast, listen, the signals an object emits |
| `scene` | `(72, 145, 190)` | changing scene, ambient, sun, camera, screenshot |
| `object` | `(62, 172, 150)` | spawning, models, meshes, moving a thing, the tree |
| `entity` | `(170, 90, 60)` | health, AI, teams, attack, the body it can be hit in |
| `light` | `(238, 128, 74)` | lamps, presets, switching and fading |
| `audio` | `(202, 104, 176)` | sounds, music, tones, sweeps, noise |
| `ui` | `(150, 188, 74)` | HUD lines, panels, bars, prompts, captions |
| `shader` | `(176, 106, 200)` | the `g.*` calls a look records in `frag` |
| `input` | `(206, 84, 78)` | held / pressed / released, bindings, mouse grab |
| `save` | `(176, 148, 96)` | values, totals and flags that outlive a reload |
| `control` | `(255, 200, 60)` | if, loops, try, break, raise |
| `data` | `(66, 163, 237)` | names and values |
| `functions` | `(150, 110, 220)` | def, class, return, calling a function |
| `modules` | `(90, 175, 110)` | import, from |
| `code` | `(130, 130, 140)` | note and raw |

Sixteen labels will not fit down a 176 px drawer in one column, so the strip
wraps: `_drawer_down` lays it out two per row once `CATEGORIES` is longer than
eight, and stays single-column for a shorter list. Four labels are shortened
for the chip by `blocktab.CATEGORY_TITLES` - `audio` reads `Sound`, `ui` reads
`Hud`, `functions` reads `Funcs`, `shader` reads `Look`.

The `events` drawer holds no block kind of its own. A hook is an ordinary `def`
whose name the engine calls, so the drawer is generated from
`blocktab.HOOK_ROWS` and drops a `def` block with the name and arguments
already filled in.

## What kind of file is open

A scene, an object, an entity and a script answer to different methods, so the
tab reads which one it holds and offers the blocks that run there.
`blocks.file_kind()` looks at the base class of the file's own `class` blocks:

| Base | Kind | The chip reads |
| --- | --- | --- |
| `Scene3D` | `scene3d` | 3D scene |
| `Scene2D` | `scene2d` | 2D scene |
| `SceneUI` | `sceneui` | UI scene |
| `Object3D` | `object3d` | 3D object |
| `Object2D` | `object2d` | 2D object |
| `UIObject` | `ui` | UI object |
| `Entity3D` | `entity3d` | 3D entity |
| `Entity2D` | `entity2d` | 2D entity |
| `Player3D` | `player3d` | 3D player |
| `Player2D` | `player2d` | 2D player |
| `Shader` | `shader` | shader |
| none of them | `script` | script |

A base is read by its last name, so `fe.Scene3D` and a bare `Scene3D` count
alike. A scene wins over an object, because a scene file usually declares a
small object of its own as well and still edits like the scene it is.

Every preset node class is a base too - `Screen3D`/`Screen2D`, `Model3D`,
`Sprite2D`, the collision and hitbox shapes, the triggers and markers, the
eight light nodes, the two emitters, the two text nodes and the two timers -
and each gives its file a kind of its own (`blocks.BASES` holds the whole
list, one entry per kind in `blocks.KINDS`).

What the kind decides:

| Where | Effect |
| --- | --- |
| drawer rows | `blocks.palette(category, kind)` drops a block whose `kinds` list does not name the file's kind |
| language drawers | a script is offered `control`, `data`, `functions`, `modules` and `code` - `SCRIPT_CATEGORIES` - and nothing that needs a scene |
| strict node drawers | a preset node's script is offered its own drawer plus the language, and nothing else - `blocks.TYPE_CATEGORIES`. An audio emitter sees `audio`, a light node sees `light`, a shader script sees `shader`, a timer sees only the language; an entity sees `object`, `entity`, `trigger` and `light` on top of the language, because it spawns and moves, has behaviour, hears signals and carries a light of its own. `blocks.fits()` consults the allowlist before the `kinds` check |
| events drawer | `HOOK_ROWS` carries the kinds a hook runs in: `on_enter` and `on_exit` are a scene's, `build` and `update` belong to any file; a scene also hears `on_map_loaded(self, level)` / `on_map_unloaded(self, level)` when a level comes or goes, a hitbox or trigger also hears `on_enter(self, other)` / `on_exit(self, other)`, a timer hears `on_timeout(self)`, and a shader script hears the `frag(self, g)` hat |
| toolbar | a chip beside the file's name says which kind was read |
| drawer on open | the palette opens on the drawer that kind is made from - `scene` for a 3D scene, `object` for a 3D object, `entity` for an entity script, `ui` for a UI scene, `light` for a light node, `audio` for an emitter, `shader` for a shader script, `functions` for a timer, `data` for a script (`blocktab.DRAWER_FOR`) |
| Inspector | `info()` lists it under *Kind* |
| an empty file | the hint names the kind: "an empty 3d scene - drag a block out of the drawer" |
| an empty drawer | the drawer says "nothing here for a 2d object" rather than going blank |

## The block palette

`blocks.SPEC` maps a kind to a `Spec(kind, label, category, shape, slots,
bodies, make, doc, node, kinds, defaults)`. The label is the block's words,
with `%name%` marking a hole. `node` is the shorter name its node's title bar
shows, filled from the block's fields the same way; left empty, the title is
the label's opening words. `kinds` lists the files the block runs in and is
empty when it runs in all of them. `defaults` is what it is dropped with, and
`blocks.DEFAULTS` holds the same words for the hand-written kinds.

The engine's own blocks are not written out here: their rows, words and
defaults all come from the engine's own signatures (see
[Blocks from the engine](#blocks-from-the-engine)). What is left is the
language itself and the handful of engine blocks that write something other
than one plain call.

| Kind | Says | Drawer | Shape | Writes |
| --- | --- | --- | --- | --- |
| `do` | run *expr* | data | stack | the expression as a statement |
| `set` | set *target* to *value* | data | stack | `target = value`, or `target: type = value` |
| `bump` | change *target* by *op* *value* | data | stack | `target += value` |
| `forget` | forget *targets* | data | stack | `del names` |
| `global` | *word* *names* | data | stack | `global name` / `nonlocal name` |
| `pass` | do nothing | control | stack | `pass` |
| `if` | if *test* then | control | branch | `if test:` with optional `elif` / `else` stacks |
| `each` | for each *target* in *seq* | control | branch | `for target in seq:` with optional `else` |
| `while` | repeat while *test* | control | branch | `while test:` with optional `else` |
| `guard` | use *items* as a stack | control | branch | `with items:` |
| `try` | try | control | branch | `try:` plus handlers, optional `else` / `finally` |
| `except` | except *types* as *name* | control | branch | `except Types as e:` |
| `break` | break out | control | cap | `break` |
| `continue` | skip to next | control | cap | `continue` |
| `assert` | assert *test* else *message* | control | stack | `assert test` / `assert test, message` |
| `raise` | raise *types* from *cause* | control | cap | `raise`, `raise Types`, `raise ... from cause` |
| `def` | when *name* is called with *args* | functions | branch, hat for a hook | `def name(args):`, `def name() -> type:`, decorators |
| `class` | make a *name* that is a *bases* | functions | branch | `class Name(Bases):` |
| `return` | give back *value* | functions | cap | `return` / `return value` |
| `import` | bring in *names* | modules | stack | `import a.b`, `import a.b as c` |
| `from` | from *src* import *names* | modules | stack | `from src import name`, `from src import *` |
| `note` | *code* | code | raw-drawn | a comment, kept exactly as written |
| `raw` | *code* | code | raw | Python the model shows but never restructures |

New statement shape = one more `SPEC` entry plus its `make` function. Nothing
in the tab is specialised for a kind.

### Entity blocks

The `entity` drawer is the behaviour an `Entity3D` or `Entity2D` carries: its
health, its AI, its team, its attack, its walking speed, the body it can be hit
in and the way it leaves. Twenty-three blocks, in two families that answer one
question - *whose entity is this about*:

| Family | Kinds | Receiver | Built by | Files |
| --- | --- | --- | --- | --- |
| mine | `health`, `maxhealth`, `ai`, `aitarget`, `team`, `aggro`, `attack`, `speed`, `hitbox`, `hitbox2d` | `self` | a `Call` in `api.py`, its rows read off the setter's own signature | `blocks.ENTITY_KINDS` - the two entity kinds, the two object kinds and the two player kinds |
| who | `set_health`, `heal`, `damage`, `kill`, `leave`, `set_ai`, `set_ai_target`, `set_team`, `set_aggro_range`, `set_attack`, `set_move_speed`, `set_hitbox`, `set_hitbox2d` | whoever the *who* row names, dropped with `self.player` | a `make` in `blocks.py` | `blocks.ACTOR_KINDS` - the same six plus the three scene kinds, because a scene tells entities what to do |

The two hitbox pairs are split by world: `blocks.ENT3D_KINDS` and
`blocks.ENT2D_KINDS` keep a flat shape out of a solid script and a solid one
out of a flat script. A *hitshape* row takes the words that entity's own class
lists - `box`, `sphere`, `capsule` on a 3D body, `rect` or `circle` on a flat
one - and the engine folds anything it does not list into the shape its size
already makes.

Every block lowers to one engine call, which is the whole reason it can be a
block rather than a `raw` note: `who.set_ai("patrol", config)` reads back as
itself, while the two attribute pokes it replaces - `who.ai_type = "patrol"`
and `who.ai_config = config` - are ordinary statements a reader cannot tell
from any other pair of assignments. Those calls are the setters
`EntityBehaviour` owns, each one writing only the rows it was given and
answering with the entity, so an empty row leaves what it had in place.

| Kind | Says | A fresh block writes |
| --- | --- | --- |
| `health` | set my health to *health* | `self.set_health(100.0)` |
| `maxhealth` | set my full health to *health* | `self.set_max_health(100.0)` |
| `ai` | switch my AI to *ai_type* with *config* | `self.set_ai("follow", config={})` |
| `aitarget` | follow *target* | `self.set_ai_target(self.player)` |
| `team` | join the *team* team | `self.set_team("enemy")` |
| `aggro` | notice a target *distance* away | `self.set_aggro_range(15.0)` |
| `attack` | attack with reach *range* for *damage* every *cooldown*s | `self.set_attack(range=2.0, damage=15.0, cooldown=1.5)` |
| `speed` | walk at *walk* and run at *run* | `self.set_move_speed(3.0, run=8.0)` |
| `hitbox` | set my hitbox to *hitshape* | `self.set_hitbox("box", half=(0.5, 1.0, 0.5))` |
| `hitbox2d` | set my flat hitbox to *hitshape* | `self.set_hitbox2d("box", size=(32.0, 48.0))` |
| `set_health` | set *who* health to *value* | `self.player.set_health(100.0)` |
| `heal` | heal *who* by *amount* | `self.player.heal(10.0)` |
| `damage` | damage *who* by *amount* from *source* | `self.player.take_damage(10.0, None)` |
| `kill` | kill *who* from *source* | `self.player.kill(None)` |
| `leave` | take *who* out at the end of the frame | `self.player.queue_free()` |
| `set_ai` | set *who* AI to *ai_type* with *config* | `self.player.set_ai("follow", {})` |
| `set_ai_target` | set *who* AI target to *target* | `self.player.set_ai_target(self.scene.player)` |
| `set_team` | set *who* team to *team* | `self.player.set_team("enemy")` |
| `set_aggro_range` | set *who* aggro range to *distance* and off at *deaggro* | `self.player.set_aggro_range(15.0, None)` |
| `set_attack` | set *who* attack: reach *range*, damage *dmg*, cooldown *cd* | `self.player.set_attack(2.0, 15.0, 1.5)` |
| `set_move_speed` | set *who* move speed to *walk* (run *run*) | `self.player.set_move_speed(3.0, 8.0)` |
| `set_hitbox` | set *who* hitbox: *shape* *params* | `self.player.set_hitbox("box", (0.5, 1.0, 0.5))` |
| `set_hitbox2d` | set *who* 2D hitbox: *shape* *params* | `self.player.set_hitbox2d("rect", (32.0, 48.0))` |

`leave` is `queue_free()` and not the object drawer's `remove` call to
`self.despawn(...)`: it leaves when the frame's work is done, so dropping an
entity while walking `self.get_children()` cannot shift the row being walked.
The tree calls the entity script also owns - `node` for `get_node`, `free` for
the same `queue_free` on whatever it is mixed into - sit in the `object`
drawer, and the signal calls `connect` / `emit` in the `trigger` one; see
[Objects](objects.md) for what each does.

### Blocks from the engine

Most of the engine's blocks are built from the engine itself, in
`emoeng/editor/api.py`. One `Call` names the expression a block writes and the
function its rows come from:

```python
Call("place", "place the model %model% at %pos%", "self.place_model",
     "Scene3D.place_model", kinds=("scene3d",))
```

`inspect.signature` turns `place_model(name, pos=None, yaw=None, scale=None,
tint=None)` into five rows - `model`, `pos`, `yaw`, `scale`, `tint` - in the
engine's own order. A fresh block writes the rows that have no default, then
any filled row by name, so the one above lands as
`self.place_model("crate", (0.0, 0.0, 0.0))` and filling `yaw` adds `yaw=1.0`
after it. A parameter the engine grows becomes a row on the block with no edit
in `blocks.py`.

What a signature cannot say, `Call` adds:

| Member | For |
| --- | --- |
| `skip` | a parameter a block never shows: `spawn`'s `parent` and `clone_of` |
| `names` | the word a row is shown under: `f0` reads `hz`, `name` reads `model` |
| `extra` | rows `**kw` forwards, per object class: `_PROP3D`, `_PROP2D`, `_PANEL` |
| `head`, `fixed` | the constants a call always writes, in place or by name: `fe.UIObject`, `enabled=False` |
| `quoted` | rows the engine reads as a string: a light's `shape="point"` |
| `seeds` | rows that have a default a fresh block still fills, because a light with no `shape` is not a light |
| `by_name` | a required row written by name, where the position is taken by another argument |
| `kinds` | the files the block runs in; empty means every kind |

| Drawer | Built from | A fresh block writes |
| --- | --- | --- |
| `scene` | `play_scene`, `push_scene`, `pop_scene`, `load_map`, `change_map`, `unload_map`, `set_ambient`, `set_sun`, `add_camera`, `set_active_camera`, `shake`, `follow`, `look_at`, `set_post`, `set_shader_knob` | `self.play_scene("menu")`, `self.set_sun(dir=(0.4, 0.8, 0.3), color=(1.0, 1.0, 1.0))` |
| `object` | `spawn`, `place_model`, `model_object`, `add`, `dynamic`, and the words the object classes take | `self.spawn("spark", (0.0, 0.0, 0.0))`, `self.place_model("crate", (0.0, 0.0, 0.0))` |
| `entity` | the setters `EntityBehaviour` owns: `set_health`, `set_max_health`, `set_ai`, `set_ai_target`, `set_team`, `set_aggro_range`, `set_attack`, `set_move_speed`, `set_hitbox`, `set_hitbox2d` | `self.set_health(100.0)`, `self.set_attack(range=2.0, damage=15.0, cooldown=1.5)` (see [Entity blocks](#entity-blocks)) |
| `trigger` | `self.connect`, `self.disconnect`, `self.emit`, on top of the scene's own `broadcast` / `listen` / `unlisten` | `self.connect("door", self.on_door)`, `self.emit("door", True)` |
| `light` | `add_light`, `add_preset`, `remove_light`, `Object3D.light` | `self.add_light(pos=(0.0, 0.0, 0.0), color=(1.0, 1.0, 1.0), shape="point")` |
| `audio` | `Audio.play`, `tone`, `sweep`, `music`, `noise`, `set_master` | `self.audio.play("pickup")`, `self.audio.tone("pickup", freq=440.0)` |
| `ui` | `Hud.text`, `panel`, `bar`, `prompt`, `hints`, `subtitle` | `self.hud.bar((12, 12, 200, 40), 0.6)` |
| `shader` | `Builder.tex`, `noise`, `mix`, `ramp`, `hue`, `smoothstep`, `clamp`, `wmuv` | `g.out = g.tex(g.uv)` (see [The shader drawer](#the-shader-drawer)) |
Three spawn blocks take their words from the object class rather than from
`spawn()` itself, and two build a widget with no class at all:

| Kind | Says | A fresh block writes | Files |
| --- | --- | --- | --- |
| `spawn` | spawn *obj* at *pos* | `self.spawn("spark", (0.0, 0.0, 0.0))` | every kind |
| `spawn3d` | spawn the 3D prop *obj* at *pos* yawed *yaw* scaled *scale* | `self.spawn("spark", (0.0, 0.0, 0.0), yaw=0.0, scale=1.0)` | 3D scene, 3D object |
| `spawn2d` | spawn the sprite *obj* at *pos* | `self.spawn("spark", (0.0, 0.0, 0.0), texture="stone")` | 2D scene, 2D object |
| `spawnui` | spawn the widget *obj* at *pos* saying *text* | `self.spawn("spark", (0.0, 0.0, 0.0), text="ready")` | 2D scene, UI scene |
| `button` | button *text* at *pos* | `self.spawn(fe.UIObject, pos=(0.0, 0.0, 0.0), text="ready")` | 2D scene, UI scene |
| `label` | label *text* at *pos* | the same line, plus `enabled=False` | 2D scene, UI scene |

`spawn(**kw)` hands whatever a block writes to the object class, so `spawn3d`
carries the two words every `Object3D` takes, `spawn2d` the words of an
`Object2D` and `spawnui` the words of a `UIObject`. `button` and `label` need
no class: they build a `UIObject` on the spot, and the one word that tells
them apart is `enabled` - a label is disabled so the mouse passes through it.
Both write it themselves, so a label never reads back as a button.

The blocks that write something other than one plain call stay in `blocks.py`:

| Kind | Says | Writes |
| --- | --- | --- |
| `restart` | start this scene again | `self.game.restart_scene()` |
| `shot` | take a screenshot | `self.game.screenshot()` |
| `remove` | take *who* out of the scene | `self.despawn(None)` |
| `move` | move *who* to *pos* | `self.player.set(pos=(0.0, 0.0, 0.0))` |
| `face` | turn *who* to *yaw* radians | `self.player.set(yaw=0.0)` |
| `clone` | clone *who* at *pos* | `self.player.clone(None)` |
| `lighton` | switch the light *who* on | `lamp.on()` |
| `lightoff` | switch the light *who* off | `lamp.off()` |
| `flash` | flash *who* by *amount* for *seconds* s | `lamp.flash(2.0, 0.14)` |
| `fade` | fade *who* to *amount* over *seconds* s | `lamp.fade_to(0.0, 1.0)` |
| `nomusic` | stop the music | `self.audio.stop_music()` |
| `silence` | stop every sound | `self.audio.stop_all()` |
| `crosshair` | draw the crosshair | `self.hud.crosshair()` |
| `held` | while *action* is held | `if self.input.down("forward"):` |
| `pressed` | if *action* was pressed | `if self.input.pressed("use"):` |
| `released` | if *action* was let go | `if self.input.released("use"):` |
| `bind` | bind *action* to *key* | `self.bind("dash", "lshift")` |
| `unbind` | stop listening for *action* | `self.input.unbind("dash")` |
| `grab` | capture the mouse: *word* | `self.input.grab_mouse(True)` |
| `remember` | remember *key* as *value* | `self.save.set("seen_intro", True)` |
| `count` | add *amount* to *key* | `self.save.add("solved", 1)` |
| `mark` | mark *key* done | `self.save.flag("seen_intro")` |
| `unmark` | unmark *key* | `self.save.unflag("seen_intro")` |
| `savenow` | write the save now | `self.game.save_game()` |
| `loadnow` | read the save now | `self.game.load_game()` |
| `call` | call *fn* with *args* | `action()` |
| `callon` | call *fn* on *who* with *args* | `self.action()` |
| `after` | delay *seconds* s then call *fn* | `self.after(1.0, action)` |
| `every` | every *seconds* s call *fn* | `self.every(1.0, action)` |

Two slots hold bare words rather than Python: `lamp`'s *shape* cycles every
shape `Engine.add_light` knows (`point`, `spot`, `sun`, `tube`, `radial`,
`cone`, `rect`, `strip`, `ring`, `poly`, `world`) and is quoted for the call,
and `grab`'s *word* cycles `True`/`False` - both lists live in `blocks.WORDS`.
Everything else is an expression slot - `"crate"`, `(0.0, 2.0, 0.0)`,
`self.player` - and an empty `call` argument slot gives `action()` rather than
`action(())`.

The one-shot and repeating timers are the ones a scene already owns:
`Scene.after(seconds, fn)` and `Scene.every(seconds, fn)` drop their callback
when the scene unloads, so a block cannot leave a timer running into the next
level.

The preset nodes each get the methods they own, and nothing else - a block
whose `kinds` name `audio3d` never turns up in a scene:

| Kind | Says | A fresh block writes | Files |
| --- | --- | --- | --- |
| `settext` | set the words to *text* | `self.set_text("ready")` | 3D text, 2D text |
| `emitplay` | play the emitter sound *sound* at *amount* volume | `self.play(sound="fountain")` | 3D emitter, 2D emitter |
| `emitstop` | stop the emitter | `self.stop()` | 3D emitter, 2D emitter |
| `timerstart` | start the timer | `self.start()` | 3D timer, 2D timer |
| `timerstop` | stop the timer | `self.stop()` | 3D timer, 2D timer |

An emitter's stop and a timer's stop are the same call, so either block
reads back as the other; the file they write is identical either way. A
light node's own script switches its beam through the `who` slots of
`lighton`, `lightoff`, `flash` and `fade` - the receiver there is
`self.beam`, the light the node carries.

### The shader drawer

A `scripts/shaders/*.py` file - a class built on `fe.Shader` - reads as the
`shader` kind and is offered a drawer of its own, plus the language and
nothing else (`blocks.TYPE_CATEGORIES`). Its entry point is the `frag` hook
hat (`self, g`) that `HOOK_ROWS` drops, and its rows are the calls the
builder `g` records. Each is a `Call` whose `owner` is a `Builder` method
(`api.OWNERS["Builder"]`), so its argument rows come straight from the
engine signature.

A look paints by *assigning* - a bare `g.tex(...)` records nothing - so each
shader block owns the line it writes through `Call.writes`, and reads back
only from an assignment to exactly that name (`api.read_assign`).

| Kind | Says | A fresh block writes | Writes |
| --- | --- | --- | --- |
| `paint` | paint the sheet as it is seen at *uv* | `g.out = g.tex(g.uv)` | `g.out` |
| `grain` | paint the noise over *uv* at *scale* | `g.out = g.noise(g.uv, 1.0)` | `g.out` |
| `wash` | paint between *a* and *b* by *t* | `g.out = g.mix(g.color, g.color, 0.5)` | `g.out` |
| `ramp` | paint up from *a* to *b* as *t* climbs | `g.out = g.ramp(g.color, g.color, 0.5)` | `g.out` |
| `hue` | paint the hue of *h* | `g.out = g.hue(g.time)` | `g.out` |
| `soft` | paint *x* eased between *a* and *b* | `g.out = g.smoothstep(0.0, 1.0, x)` | `g.out` |
| `safe` | paint *x* kept between *lo* and *hi* | `g.out = g.clamp(x, 0.0, 1.0)` | `g.out` |
| `slide` | slide *uv* along *direction* at *speed* | `g.uv = g.wmuv(g.uv, (1.0, 0.0), 1.0)` | `g.uv` |

`slide` is the one row that paints nothing: it writes `g.uv`, the
coordinates every later row reads, so the sheet scrolls. A plain read of
`g` needs no block of its own - `set g.out to g.time` already round-trips
through the ordinary `set` block, and `g.uv`, `g.time`, `g.color` are the
rows' placeholders.

### Choosing an asset by name

Many rows name something the project keeps - a sheet, a model, a shader, a
sound, a scene - rather than an expression. Typing into one of those slots
opens a filtered list under it (`blocktab._open_picks`, painted with
`widgets.Choices` in the same style as the other popups): first the stems
found in the project's folder, then the names the engine always knows, with
duplicates dropped. The list narrows as you type; Up/Down move, Enter or Tab
keeps the pick, Esc puts the list away but leaves the slot open. A picked
word arrives quoted when the `Call` lists that row as `quoted`.

What each row can list is `api.PICKERS`, keyed by the row's own name so only
the slots that really take an asset open a list:

| Row | Folder | Also offers |
| --- | --- | --- |
| `texture`, `sprite` | `textures` | the `proctex` names and any `#rrggbb` colour |
| `model` | `models` | the primitive list |
| `shader` | `shaders` | nothing built in |
| `sound` | `audio` | the built-in synth tones |
| `path` | `audio` | nothing built in |
| `scene` | `scenes` | nothing built in |
| `map` | `maps` - both `.map3d` and `.map2d` stems | nothing built in |
| `obj` | `objects` and `entities` | nothing built in |

`api.choices(project, slot)` builds the list, and `api.known` checks a word
against it - a colour spelling counts for a sheet, since the renderer turns
it into a solid texture with no file. The Scene tab's shelf uses the same
tables: a `texture`, `model` or `shader` value row opens the list on click
(`preview._open_picks`).

### Defaults a dropped block starts with

| Kind | Slot words |
| --- | --- |
| `do` | `expr=None` |
| `set` | `target=name`, `value=None` |
| `bump` | `target=name`, `op=+=`, `value=1` |
| `forget` | `targets=name` |
| `global` | `word=global`, `names=name` |
| `import` | `names=emoeng` |
| `from` | `src=emoeng.engine`, `names=name` |
| `if` | `test=True`, `word=if` |
| `each` | `target=item`, `seq=[]`, `word=for` |
| `while` | `test=True` |
| `guard` | `items=None`, `word=with` |
| `raise` | `types=RuntimeError` |
| `assert` | `test=True` |
| `def` | `word=def`, `name=action`, `args=self` |
| `class` | `name=Thing`, `bases=object` |
| `note` | `code=# note` |
| `raw` | `code=pass` |
| `remove` | `who=None` - the call is a no-op until it is filled |
| `move`, `face`, `clone` | `who=self.player` (plus `pos` / `yaw`) |
| `lighton`, `lightoff` | `who=lamp` |
| `flash` | `who=lamp`, `amount=2.0`, `seconds=0.14` |
| `fade` | `who=lamp`, `amount=0.0`, `seconds=1.0` |
| `held`, `pressed`, `released` | `action="forward"` / `"use"` |
| `bind` | `action="dash"`, `key="lshift"` |
| `unbind` | `action="dash"` |
| `grab` | `word=True` |
| `remember` | `key="seen_intro"`, `value=True` |
| `count` | `key="solved"`, `amount=1` |
| `mark`, `unmark` | `key="seen_intro"` |
| `call`, `callon` | `fn=action`, `args=` (empty), `who=self` |
| `after`, `every` | `seconds=1.0`, `fn=action` |

The engine kinds with no slot at all are complete the moment they land: `pop`,
`restart`, `shot`, `nomusic`, `silence`, `crosshair`, `savenow`, `loadnow`.

A generated block is dropped with the words its call cannot do without - the
rows with no default - plus the few `seeds` that make it do something: a
`spawn3d` arrives with `obj`, `pos`, `yaw` and `scale` filled, a `sun` with
`dir` and `color`. `api.START` holds the valid Python for each row and
`api.WORDS` the example an empty row shows, so a fresh block never leaves the
file broken while it is being named.

`new_block("try")` also attaches `except Exception:` to its `handlers` stack,
because a `try` with nothing to catch is not Python yet.

## Reading engine calls back

A block's words are plain Python, so a file written in the Code tab already
holds the same calls the palette writes. `api.read(node)` is what gives those
calls their block back, and it answers `(kind, fields)` or `None`:

* the dotted function must be one an entry writes: `self.add_light` is the
  `lamp` block's, `self.add_light(` with another receiver is nobody's;
* the first arguments must be the constants the block always writes - a
  `button` is `self.spawn(fe.UIObject, ...)` and nothing else;
* no argument may go unshown: an extra keyword, a `**kwargs`, or two spellings
  of one row keep the call as a `do` block rather than lose it;
* every row the engine cannot do without must be filled;
* a `quoted` row comes back bare: `shape="point"` in the call is *point* in
  the block.

Entries are tried from the narrowest first - the block with the most constant
arguments, then the fewest rows - so `self.spawn(fe.UIObject, pos=...,
enabled=True)` lands on the block that can show every word it holds.

`blocks.CALLS` still handles the calls about fifteen of the hand-written
blocks write, because no signature describes them - a method on another
object, a constant-only line:

```python
CALLS[("self.game.restart_scene", 0)] = ("restart", (), {})
CALLS[("self.save.set", 2)] = ("remember", ("key", "value"), {})
CALLS[("self.after", 2)] = ("after", ("seconds", "fn"), {})
```

Recognition is a convenience, not a second format: a block read from source
keeps its sticky words, so `render()` gives the file back character for
character either way. Nothing is written differently because a block was
recognised.

Calls keyed on the receiver's own method - `lamp.off()`, `self.player.set(...)`,
`action()` - are read by a second table, `blocks.METHODS`. An entry names the
method, the keyword that tells it apart (if any) and the block it belongs to:

```python
METHODS = (
    ("set", "pos", "move", ()),           # self.player.set(pos=...)
    ("set", "yaw", "face", ()),           # self.player.set(yaw=...)
    ("off", None, "lightoff", ()),         # lamp.off()
    ("fade_to", None, "fade", ("amount", "seconds")),
)
```

The receiver fills the `who` row, and the arguments fill the rest. Only a
plain `a.b.c` path is accepted as a receiver, because `(a + b).foo()` cannot be
written back out in front of a dot without changing what runs. A call of any
other name is still something a block can hold: a bare `action()` reads as
`call`, and `self.player.spin(1)` as `callon`, unless a signature (first) or one
of the tables above already claims it. A call with a keyword argument stays a
`do` block, because neither shape has a row to put it in.

A branch whose test is one input call reads back as the input block that wrote
it - `if self.input.down("forward"):` is `held`, `pressed` or `released`
(`blocks.INPUT_TESTS`) - as long as it has no `else`, which those blocks do not
own.

Every block the drawer offers is checked against itself: a fresh block is
written out to Python, read again, and has to come back as the block it was,
because one that came back as a `do` would change its own drawer the first
time the file was saved and reopened. Two shapes cannot answer that way and are
expected not to: a block that holds a stack carries a `pass` inside it once it
has been read again, and a `note` is a comment, which the parser keeps as the
lines above the block after it rather than as a block. `tools/smoke_editor.py`
walks the whole palette and fails on anything else.

## Hook names

`blocks.HOOKS` is the list of method names that make a `def` read as an event
hat. It is a drawing vocabulary, not a promise: the functions the engine
actually calls are listed in
[Objects](objects.md) and [Scenes](scenes.md), and a `def` of any name in this
tuple simply reads as a hook and may only sit at the top of the file or inside
a class.

```python
("setup", "build", "update", "overlay", "draw", "handle_event", "on_enter",
 "on_exit", "on_timeout", "on_save", "on_load", "on_map_loaded",
 "on_map_unloaded", "on_trigger", "status", "place",
 "spawn_point", "ground_height", "interact", "use", "trigger", "collide",
 "dispose", "attach", "set", "set_camera", "clone_kwargs", "poll_look",
 "poll_move", "apply_look", "apply_move", "publish_camera", "teleport",
 "face", "look_at", "forward", "is_moving", "look", "move", "frag",
 "__init__", "__call__", "__str__", "__repr__", "__enter__", "__exit__")
```

The drawer's own descriptions of the hooks it advertises
(`blocktab.HOOK_ROWS`):

| Name | Arguments the engine passes | When |
| --- | --- | --- |
| `setup` | `self` | once, when a scene or object comes in |
| `build` | `self` | once, right after setup, to make the geometry |
| `update` | `self, dt` | every frame |
| `handle_event` | `self, e` | for each key, button or quit event |
| `draw` | `self` | when this object is asked to paint itself |
| `overlay` | `self, screen` | after the world, straight on the screen |
| `on_enter` | `self` | when the player arrives here (a scene) |
| `on_exit` | `self` | when the player leaves (a scene) |
| `on_enter` | `self, other` | when something moves into this shape (a hitbox or trigger) |
| `on_exit` | `self, other` | when something leaves this shape (a hitbox or trigger) |
| `on_timeout` | `self` | when this timer's wait is up |
| `on_save` | `self, save` | before a save is written |
| `on_load` | `self, save` | after a save is read |
| `on_map_loaded` | `self, level` | after a map is built or swapped in |
| `on_map_unloaded` | `self, level` | after this scene's map is taken out |
| `dispose` | `self` | last, when the object is going away |
| `frag` | `self, g` | records the picture a shader paints, once at compile |

## Sticky source

Every block remembers the text it was read with, so an untouched block writes
back byte for byte - comment spacing, line breaks and all. Only a block whose
slots changed is rebuilt from those slots.

| Member | What it does |
| --- | --- |
| `original` | The words the file was read with |
| `good` | The last words that parsed |
| `fields` | The words the slots hold now |
| `edited` | True when `fields` differs from `original` |
| `is_source()` | True when the block still holds the words it was read with |
| `text`, `indent` | Its own captured source and the column it was read at |
| `statement()` | The source line(s) it owns - verbatim when untouched |
| `draft()` | The half-typed words, only ever used for `check()` |
| `check()` | Why the words are not valid Python, or `None` |
| `set_field(name, value)` | Edit a slot; returns the problem, keeps the words either way |
| `revert(to_file=False)` | Back to the last words that parsed, or with `to_file` to the words from the file |
| `read_word(name, value)` | Record a keyword the source itself spells (`elif`), so the block still reads as untouched |

Typing a bad slot never throws your words away and never corrupts the file: the
slot gets a ring, the block keeps writing the last words that parsed, and
`save()` reports what was left unwritten. `check()` skips any slot whose words
already parsed, so rendering a whole file costs no extra `ast` work on the
blocks nobody touched.

A `raw` block is the escape hatch: `match` statements, one-line blocks and any
other shape the model does not know ride through it as text, read from their own
column so the code inside keeps its shape.

## `blocks` module API

| Function | Returns |
| --- | --- |
| `parse(text)` | A `Module`; a file that does not parse becomes one `raw` block plus `module.readonly` explaining why |
| `new_block(kind, fields=None, pre=())` | A palette block with its defaults filled in and its stacks empty |
| `spec(kind)` | The `Spec` for a kind, or `None` |
| `palette(category=None, kind=None)` | Rows `{"kind", "label", "shape", "doc", "category"}`, grouped by drawer then sorted by label; `kind` drops the blocks that do not run in that kind of file |
| `drawers(kind=None)` | `[(category, rows)]`, one entry per drawer in `CATEGORIES` order |
| `fits(spec, kind)` | Whether a block may be dropped into that kind of file |
| `file_kind(module)` | The kind of file a `Module` holds, from the base class it declares |
| `KINDS` | `kind -> the words the toolbar shows`: `scene3d` is "3D scene", `omnilight3d` is "omni light", and `script` is "script" |
| `BASES` | Base class name -> kind, one entry per engine class a file can build on |
| `SCRIPT_CATEGORIES` | The drawers a plain script is offered |
| `TYPE_CATEGORIES` | `kind -> drawers`: the strict palette of a preset node's own script - its own drawer plus the language |
| `CATEGORIES` | The drawers in the order the palette lists them |
| `DEFAULTS` | `kind -> {slot: words}`: what a hand-written block dropped from the drawer starts with |
| `CALLS` | `(dotted name, positional count) -> (kind, slots, keywords)`: the calls the hand-written blocks read back |
| `METHODS` | The calls one object's method writes back as a block: `("off", None, "lightoff", ())` |
| `INPUT_TESTS` | `self.input.down` -> `held`, and the two beside it |
| `search(module, needle)` | Blocks whose own words contain the needle |
| `outline(module)` | `[(pid, words, kind, depth)]` for every block |
| `block_source(block, unit="    ")` | One block back to Python on its own |
| `tree_of(text)` | `ast.dump` of a file, or `None` when it does not parse |
| `same_tree(a, b)` | Whether two files mean the same program, spelling aside |
| `can_view(text)` | Whether the block view has anything to show |
| `round_trip(text)` | `(True, None)` when parse-then-render gives the file back exactly, else `(False, "line N: was ... now ...")` |

`Module.render()` and the file on disk are compared by `diff(text)`, which
answers `(row, was, now)` for the first line that disagrees.

## `.block` files (layout persistence)

When you arrange blocks on the canvas, the tab automatically saves their
positions to a companion file next to the `.py` script called
`{scriptname}.block`. This JSON file stores only the hand-placed node
positions (nodes placed by the automatic layout are re-measured each time).

```json
{
  "layout": {
    "1": [120, 80],
    "2": [300, 150],
    "3": [300, 280]
  }
}
```

The keys are the block PIDs (persistent IDs) and the values are `[x, y]`
board coordinates. This means:
- Your custom layout survives closing and reopening the file
- The automatic layout still works for new blocks you haven't moved
- You can share the `.block` file with your team to keep the graph tidy
- The file is small and text-based, so it plays nice with version control

If you delete the `.block` file, the tab falls back to the automatic layout.

## `Block` API

| Group | Members |
| --- | --- |
| Identity | `pid`, `kind`, `spec`, `shape`, `label()`, `lineno`, `end` |
| Words | `fields`, `original`, `good`, `edited`, `is_source()`, `statement()`, `draft()`, `check()`, `sample(text=None)`, `set_field()`, `revert()`, `read_word()`, `words(name)` |
| Children | `bodies`, `stack(name)`, `body_names()`, `attach(blocks, name)`, `all()`, `find(pid)`, `__iter__` |
| Position | `parent`, `slot`, `index()`, `depth()`, `moved`, `mark_moved()`, `remove()` |
| Writing | `lines(unit="    ", outer="", level=0)`, `own_lines(pad)`, `source(unit="    ")`, `pre`, `leads`, `gaps`, `indent`, `pad_for(outer)`, `shift(line, pad)` |

`__repr__` reads `<Block if 'score > 100' >`; `label()` collapses a raw or
comment block to its first 200 characters on one line.

## `Module` API

| Group | Members |
| --- | --- |
| Contents | `blocks`, `tail`, `source`, `unit`, `newline`, `final_newline`, `readonly`, `error`, `__len__`, `__iter__` |
| Looking | `all()`, `find(pid)`, `counts()`, `errors`, `is_clean()`, `summary()` |
| Editing | `insert(block, parent=None, slot=None, index=None)`, `move(block, ...)`, `replace(block, kind, fields=None)`, `remove(block)`, `revert(block=None, to_file=False)`, `holder()`, `slot_for()`, `attach()` |
| Writing | `lines()`, `render(strict=False)`, `diff(text=None)` |

`render(strict=True)` raises `ValueError` instead of quietly dropping half-typed
words; `save()` uses that form and falls back to the forgiving one when a slot
is broken. `insert()` refuses a parent that is inside the block being moved, so
a stack can never hold itself. `replace()` keeps the words the new kind also
owns and keeps the nested stacks whose body name still exists.

`slot_for()` falls back to the parent's first stack when a slot name is not one
the parent owns, and `_landing()` sends a block dropped on a command or a cap to
the stack that holds the target, right after it - a drop can therefore never
lose a block into a stack nobody reads.

## Using the model without the tab

```python
from emoeng.editor import blocks

module = blocks.parse(Path("scripts/objects/crate.py")
                      .read_text(encoding="utf-8"))
for kind, count in sorted(module.counts().items()):
    print(f"{kind}: {count}")

# add `self.spin(0.5)` to the end of every hook body
target = next((b for b in module.all()
               if b.kind == "def" and b.fields.get("name") == "update"), None)
if target is not None:
    target.attach([blocks.new_block("do", {"expr": "self.spin(0.5)"})], "body")
    Path("scripts/objects/crate.py").write_text(module.render(),
                                                encoding="utf-8")

print(blocks.round_trip(module.render()))    # (True, None) when text is stable
print(module.errors, module.summary())
```

The tab uses the same calls; nothing about the format needs pygame.

## The tab

| Region | Detail |
| --- | --- |
| Toolbar | `Text`, `Reload`, \|, `Undo`, `Redo`, \|, `Tidy`, `-`, `Fit`, `+`, \|, `Save`; it also shows the file's kind in a chip, and `Fit` zooms until the whole board is in view and shows the percentage it landed on |
| Drawer | Category strip down the left, then the rows of the open drawer, with a doc line under the hovered row |
| Canvas | The file as Blueprint nodes on a dark dotted board - `CANVAS_BG (30, 33, 40)`, `CANVAS_DOT (49, 54, 64)`, dots every `DOT_STEP 26` - with vertical and horizontal scroll strips |
| Strip | A broken slot or an uncompilable file puts a red strip above the canvas; clicking it jumps to the node that needs attention |

| Metric | Value | Metric | Value |
| --- | --- | --- | --- |
| `BAR_H` | 28 | `DRAWER_W` | 176 |
| `NODE_PAD` | 11 | `TOOL_H` | 30 |
| `NODE_GAP` | 30 | `CAT_W` | 10 |
| `PIN_ROOM` | 13 | `DRAG_AFTER` | 4 px |
| `GUTTER` | 15 | `SCROLL_STEP` | 28 |
| `PILL_PAD` | 8 | `MAX_TYPE` | 4000 chars |
| `PILL_MIN` | 44 | zoom range | 0.05 - 2.0 |
| `VALUE_MAX` | 250 | `RAW_MAX` | 430 |

`layout()` fills `self.place` with each node's rect, title bar, value fields,
body rows and pins, and `self.wires` with one `(pid, port, pid, port)` tuple per
wire. A node keeps the place it was put; one that has never been moved takes
the next slot of the automatic board, a column per nesting depth, `NODE_GAP` of
air under the node before it and `NODE_GAP` between one column and the next -
a column starts after the widest card in the column before it, so a body of a
body stays within reach instead of drifting a fixed distance away. Hand-placed
positions live in `self.pos`, remembered per file in `self._layouts` under a
path through the tree, and `tidy()` throws them all away. A place `layout()`
chose is marked in `self.auto` and dropped when the zoom changes, because a
column is measured in the zoom of the moment; a place the player chose is kept,
so the board re-flows around the cards they moved rather than dragging them.
A value field never grows past `VALUE_MAX` and a raw node's code is cut off at
`RAW_MAX`, so one long expression cannot stretch a node across the board. A
block dropped from
the drawer lands under the mouse, slid down until it touches no other node -
`_free_spot()` - so a drop can never hide the rows the player was aiming at,
and `_reveal()` scrolls the board to the new card when it landed out of sight.

A node is a category-coloured title bar, a slate body (`NODE_BG (41, 45, 55)`
to `NODE_BG_BOT (34, 37, 46)`), one row per value - a pin coloured by
`TYPE_COLORS`, the value's friendly name, then a dark field - and one row per
body. Exec pins sit in the gutter down the left edge: a wire arrives on the top
edge and leaves from the bottom one, so a stack of nodes in one column links up
with a short straight run of wire. Words are painted with the zoom: each is a
cached full-size render scaled down to the current zoom, and a node's width is
its words at that zoom, so a board can be shrunk until the whole file is one
map. The floors are there so nothing divides by zero: a metric never rounds to
less than a few pixels.

### Mouse and keys

| Input | Result |
| --- | --- |
| Drag from a drawer row | Carries a new block; a second click puts it back |
| Drag a node's title bar | Moves it anywhere on the board; the pointer must travel `DRAG_AFTER` pixels before a click becomes a drag |
| Release a node over a body row | Adds it to that stack; let go anywhere else and it simply stays there |
| Drag from an out or body pin | Draws a wire; dropped on another node, the source is made to run first (from a body pin, the node becomes the last block of that stack) |
| Middle drag | Pans the board |
| Wheel | Scrolls; a sideways notch, or Shift held, pans across |
| Ctrl + wheel | Zooms by 15% steps |
| Click a slot | Types in it - Enter keeps the words, Esc drops them, Tab keeps and closes |
| Click a keyword or operator slot | Steps through its choices instead of opening the editor |
| `+` / `-` / `0` | Zoom in, out, back to 100% |
| `Del` / `Backspace` | Takes the selected block out |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo, over a history of 80 rendered states |
| `Esc` | Puts a drawn wire away, then a carried node, then a carried block, then clears the selection |
| Right click | The block's menu |

A multi-line slot (the `code` of a `raw` or `note` block) keeps Enter for a
newline and uses Ctrl+Enter to commit; Up and Down move between its lines.

### Right-click menu

| Entry | Appears on | Does |
| --- | --- | --- |
| Undo the words typed into it | a block with a broken slot | `module.revert(block)` |
| Collapse it to plain code | any structured block | `module.replace(block, "raw", {"code": ...})` |
| Turn it back into blocks | a `raw` block | re-parses its text, when it is exactly one known block |
| Duplicate it | any structured block | a copy of the block and everything it wraps, right below it |
| Take it out | any structured block | removes it from its stack |
| Edit it as Text | always | switches to the Code tab with the file as it now is |

### Drop rules

| Rule | Enforced by |
| --- | --- |
| An `except` may only land on a `try`'s `handlers` stack, and that stack takes nothing else | `accepts()`, `can_drop()` |
| A hook (`hat`) may only go at the top of the file or into a class - never inside a statement | `accepts()` |
| A block cannot be dropped inside itself | `accepts()`, `Module.insert()` |
| A wire only plugs in where the stack allows the block | `accepts()`, `_connect()` |
| A drop on a body row fills that stack, and the card lands beside the node that owns the row; on a node, it goes just before it; on bare board, it goes at the end of the file | `_drop_at()`, `_drop()` |
| A read-only file accepts no drops at all | `readonly()` |

## Reading, saving, reloading

| Call | Behaviour |
| --- | --- |
| `open(path, text=None)` | Parses a file; with no `text` it follows the Code tab's unsaved buffer, so the two views never disagree |
| `sync(force=False)` | Shows whatever file the Code tab currently owns, re-reading it when the disk holds bytes this view did not write |
| `text()` | What the file would look like on disk right now |
| `save()` | Renders and writes, then reopens the result in the Text view; logs each broken slot and writes the safe render |
| `reload()` / `revert()` | Throws the blocks away and reads the file again |
| `errors()` | `[(pid, why)]` for the slots that do not parse |
| `info()` | Rows for the Inspector: file, kind, view, block count, raw count, zoom, changed, and the selection |
| `next_problem()` | Scrolls to the next broken slot |

`_refresh()` compiles the rendered file after every change, so a block that
reads fine on its own but makes an unloadable file is caught before a save is
offered. History stores rendered text rather than model snapshots, so undo
cannot leave the tree in a state the parser would not have produced.

Two settings decide how a `.py` opens: `editor.open_as` (`ask`, `text`,
`blocks`) and the Code/Blocks tabs being two views of one file. `Editor.show_python()`
puts up a Text-or-Blocks question when `open_as` is `ask`.

Related pages: [The Editor](editor.md), [Objects](objects.md),
[Scenes](scenes.md), [Project Folder](project-folder.md).
