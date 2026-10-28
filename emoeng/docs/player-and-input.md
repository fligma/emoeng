# Player and Input

Two pieces cover control: `Input` turns devices into named actions, and a
`Player` object polls those actions and moves itself. A scene never asks for a
key code; it asks for a name.

## Binding tokens

`input.parse_binding()` accepts these spellings. Anything unreadable is dropped
quietly, so a partial map cannot break a game.

| Token | Parses to | Notes |
| --- | --- | --- |
| `'w'`, `'up'`, `'space'`, `'f1'`, `'lshift'` | `('key', code)` | A pygame constant name, with or without the `K_` prefix |
| `pygame.K_w` (an int) | `('key', code)` | What code passes, as opposed to a map file |
| `'mouse:left'`, `'mouse:2'` | `('mouse', button)` | Names: `left`, `middle`, `right`, `x1`, `x2` |
| `'wheel:up'`, `'wheel:+1'`, `'wheel:-'` | `('wheel', +-1.0)` | One step of the wheel counts as a press |
| `'joy0:button0'`, `'joy1:btn5'` | `('joybutton', pad, n)` | |
| `'joy0:axis+1'`, `'joy0:ax-2'` | `('joyaxis', pad, n, sign)` | A sign in the name picks the direction |
| `''`, `True`, `'bogus'` | `None` | Ignored |

`parse_bindings(values)` takes a list of tokens, de-duplicates and drops the
unreadable ones. `_flatten()` accepts a bare string, a list or a tuple, so
`"w"`, `["w", "up"]` and `(pygame.K_w,)` all work in a map.

## Engine actions and defaults

`Input.bind_defaults()` installs this set; the config layers then override it.

| Action | Default tokens | Bound by |
| --- | --- | --- |
| `forward` | `w`, `up` | Player movement |
| `back` | `s`, `down` | Player movement |
| `left` | `a`, `left` | Player movement |
| `right` | `d`, `right` | Player movement |
| `run` | `lshift`, `rshift` | Second move speed |
| `up` | `space` | Fly / jump verbs |
| `down` | `q`, `lctrl` | Fly descent |
| `use` | `e` | Interact |
| `reload` | `r` | Free for the game |

The game layer adds the system actions from config: `pause` (escape), `help`
(f1), `debug` (f3), `screenshot` (f2), `restart` (f5), `hot_reload` (f6),
`fullscreen` (f11), `save` (f8), `load` (f9).

## Four layers, last wins

| Layer | Source | Set by |
| --- | --- | --- |
| 1 | `Input.bind_defaults()` | `Game._bind_defaults()` |
| 2 | `config` keys `input.*` | `config.bind_defaults(input)` |
| 3 | `project.input_map()` | `input.map.json`, else the manifest's `input.actions` |
| 4 | `scene.actions` / `scene.bind(...)` | The scene that is running |

Two actions sharing a binding is legal and only reported:
`Game.binding_conflicts` lists `[(token, [actions...])]` and the output log
prints one line per clash.

```python
# scripts/scenes/main.py
class Main(fe.Scene3D):
    actions = {"dash": ["mouse:left", "joy0:button5"], "grab": ["g"]}

    def update(self, dt):
        super().update(dt)
        if self.input.pressed("dash"):
            self.player.nudge(0.0, 0.0)
        if self.input.down("grab"):
            ...
```

## `Input` API

### Binding

| Method | Signature |
| --- | --- |
| `bind` | `bind(action, *bindings)` - names or pygame constants |
| `bind_action` | `bind_action(action, values)` - one iterable, as a map hands over |
| `bind_map` | `bind_map(mapping, replace=False)` - a whole `{action: tokens}` |
| `unbind` | `unbind(action)` |
| `bindings_of` | The names an action is bound to, for display |
| `actions` / `has_action` | The action vocabulary |
| `bound_by` | `bound_by(token_value)` - which actions a token would fire |
| `conflicts` | Tokens two or more actions share |

### Per frame

| Method | Notes |
| --- | --- |
| `begin_frame()` | Clear the pressed / released sets; `Game.run` and the editor's preview each call it once, before the events are drained, so a press lives exactly one frame |
| `handle(e)` | Feed one pygame event; returns `True` when it was input |
| `rescan()` | Open every plugged-in pad; returns how many are live |
| `clear()` | Forget every held action in silence - a scene watching for a release keeps watching |
| `release_all()` | Let go of everything held and report each one as released; what a lost keyboard needs |
| `grab_mouse(on=True)` | Lock and hide the pointer for look-around |

`is_focus_lost(e)` answers `WINDOWFOCUSLOST` and a `ACTIVEEVENT` that takes the
app away. SDL sends no key-up for a key you were holding when another window
came forward, so both the game and the editor answer that event with
`release_all()` - otherwise the last key pressed stays down and the camera
keeps flying.

### Asking

| Method | Returns |
| --- | --- |
| `down(action)` | Held right now |
| `pressed(action)` | Started this frame |
| `released(action)` | Stopped this frame |
| `mouse_down(button=1)` / `mouse_pressed` / `mouse_released` | Direct button state |
| `axis(positive, negative)` | Digital `-1..1` from two action names |
| `move_axis()` | `(right, forward)` in `-1..1` |
| `stick(deadzone=0.18, axis_x=0, axis_y=1, pad=None)` | The analog left stick |
| `trigger(pad=0, index=2, deadzone=0.05)` | One analog axis as `0..1` |

```python
# a scene that reads the pad as well as the keyboard
right, fwd = self.input.move_axis()
sx, sy = self.input.stick()
speed = max(abs(right) + abs(fwd), (sx * sx + sy * sy) ** 0.5)
throttle = self.input.trigger(index=5)
```

Stick axes release just as surely as a key returning to centre, above
`DEADZONE = 0.35`.

### In words

`binding_label(value)` and `binding_labels(values)` spell a token the way a help
panel does - `Mouse Left`, `Wheel Up`, `Left Shift`, `Pad 0 Button 5`. The game's
F1 panel and status-bar hint are generated from these, so a rebind shows up in
the game's own text with nothing to maintain.

## `Player3D`

A `Player3D` is an `Object3D` with `is_player = True`: spawn it like any prop,
and the scene hands it the camera.

```python
self.player = self.spawn(fe.Player3D, pos=(0.0, 2.0, 9.0),
                         move_speed=(6.0, 11.0), movement="fly")
```

| Knob | Default | Meaning |
| --- | --- | --- |
| `move_speed` | `(6.0, 12.0)` | Walk and run, metres per second |
| `eye_height` | `2.0` | Eye above the ground in walk mode |
| `movement` | `'walk'` | `'walk'` (grounded) or `'fly'` (free) |
| `world_radius` | `128.0` | Hard clamp from origin; `0` disables it |
| `sensitivity` | `0.0022` | Mouse pixels to radians |
| `pitch_limit` | `1.45` | Radians up or down |
| `aim_damping` | `0.0` | When set, look eases instead of snapping |
| `fov` | `None` | Override the scene's field of view |
| `lock_input` | `False` | Frozen (the scene's `lock_input` propagates here) |
| `first_person` | `True` | Publish the eye at the head rather than behind it |
| `body_half` | `(0.35, 0.9, 0.35)` | The box the sweep moves - that is how a `Collision3D` stops you |
| `collide_group` | `"player"` | Who you are to a shape: a `Collision3D` naming this `group` holds back only bodies like yours; a shape with `group=""` stops everybody |

| Method | Signature | Notes |
| --- | --- | --- |
| `set_knobs` | `set_knobs(knobs)` | Apply per-instance overrides; raises `TypeError` for a name the class does not have, so a misspelled knob cannot pass silently |
| `give_camera` | `give_camera(name=None, follow=False, offset=None, damping=0.0, active=True, **kw)` | Own camera; default is first person |
| `use_camera` | `use_camera(cam, follow=False, ...)` | Drive a scene camera |
| `poll_look` | | `(dx, dy)` mouse delta for this frame |
| `poll_move` | | `(right, forward, up, run)` from bound actions |
| `apply_look` / `apply_move` | `apply_look(dt=0.0)` / `apply_move(dt)` | Turn and step |
| `nudge` | `nudge(dx, dy, dt=0.0)` | Turn the head by a raw pixel delta |
| `publish_camera` | | Mirror `pos` / `yaw` / `pitch` onto the camera |
| `teleport` | `teleport(pos, yaw=None, pitch=None)` | Drop somewhere and look |
| `face` | `face(yaw, pitch=None)` | Turn without moving |
| `look_at` | `look_at(target, damping=None)` | Head toward a world point |
| `forward` | | Unit look vector, for raycasts |
| `is_moving` | | Any movement input this frame |

The player is Godot-style: it polls the actions itself, integrates its own
transform and publishes it onto the camera it drives, so
`scene.set_active_camera("wide")` can cut to a parked angle without the player
hijacking it back. Every move goes through `scene.move_body()`, swept against
the shapes the documents filed - a wall placed in the editor is a wall in the
game with no script anywhere - and `self.hits` is the `(hit_x, hit_y, hit_z)`
the last sweep answered with. See [Collision](collision.md).

### Third person without a rewrite

```python
class Player(fe.Player3D):
    def build(self):
        self.model_object("orb", scale=0.5)      # a body to look at
        self.give_camera(follow=True, offset=(0.0, 3.2, -6.0), damping=0.12)
        self.first_person = False
```

### Invisible player driving the map

The player can also own nothing and publish signals, which is how a marble game
keeps the ball's physics in the scene:

```python
class Ball(fe.Player3D):
    first_person = False

    def build(self):
        self.give_camera(follow=True, offset=(0.0, 5.0, -7.0), damping=0.1)

    def apply_move(self, dt):
        right, fwd, up, run = self.poll_move()
        self.scene.roll(right, fwd, run)        # the course owns the physics
```

## `Player2D`

A steered `Object2D` that keeps the ortho camera centred on itself.

| Knob | Default | Meaning |
| --- | --- | --- |
| `move_speed` | `320.0` | World pixels per second |
| `run_multiplier` | `1.8` | Applied while `run` is held |
| `bounds` | `None` | `(w, h)` box; `None` uses the scene's `world_size`, `0` roams free |
| `wheel_zoom` | `True` | Wheel over the view zooms the camera |
| `follows_view` | `True` | Keep my camera centred on me |
| `lock_input` | `False` | Frozen |
| `body_radius` | `None` | How round I am to a `Collision2D`; `None` takes half the sprite's shorter side |
| `collide_group` | `"player"` | The `group` word, as in 3D |

Methods: `set_knobs`, `camera()`, `apply_move(dt)` (swept through
`scene.move_body2d`, with `hits` answering `(hit_x, hit_y)`),
`publish_camera()`, `teleport(pos)`, `handle_event(e, pos=None)` (the wheel),
`update(dt)` (advances clock, timers and sprite frames).

```python
class Paddle(fe.Player2D):
    move_speed = 420.0
    bounds = (960.0, 540.0)

    def apply_move(self, dt):
        super().apply_move(dt)
        self.pos[1] = self.scene.world_size[1] - 60.0   # keep to the bottom row
```

## Controlling without a Player

Scenes with no player object are driven by the game loop itself: `Game`
polls the same actions for 3D scenes and calls `_camera_move(dt)` /
`_mouse_look()`. `game.set_player(pos, yaw, pitch)` teleports that camera and
`game.follow(target)` chases something with it. A 2D or UI scene owns its own
rig and the loop leaves it alone.
