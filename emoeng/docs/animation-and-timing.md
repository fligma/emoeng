# Animation and Timing

Nothing here needs a tween library. `engine.anim` holds the maths,
`engine.timers` holds the scheduler, and the clock, sprite frames and camera
easing are built on top of them.

## Where time comes from

| Clock | What it is | Advanced by |
| --- | --- | --- |
| `game.time` | Seconds since the game started | `Game.run()`, only while unpaused |
| `game.last_dt` | The frame's delta, clamped to `0.05` | every frame |
| `game.fps` | Smoothed frames per second (exponential average) | every frame |
| `scene.t` | Seconds since this scene's `setup()` ran | `Scene.update(dt)` |
| `obj.t` | Seconds since this object was spawned | `GameObject.update(dt)` |
| `game.fade` | `0.0` visible - `1.0` full black | `_tick_fade(dt)` |

`dt` is capped at 0.05 s (20 fps), so alt-tabbing across a window switch never
launches a body through a wall. Paused means paused: `scene.update()`, timers
and autosave all stop, while cameras keep ticking so a shake finishes dying.

## Easing helpers (`engine.anim`)

| Function | Signature | Result |
| --- | --- | --- |
| `clamp` | `clamp(value, lo, hi)` | `value` inside the range |
| `clamp01` | `clamp01(value)` | inside `0.0..1.0` |
| `lerp` | `lerp(a, b, t)` | `a` at `t=0`, `b` at `t=1` |
| `smoothstep` | `smoothstep(t)` | ease-in-out, flat at both ends |
| `ease_in` | `ease_in(t)` | `t ** 2` - starts slow |
| `ease_out` | `ease_out(t)` | `1 - (1 - t) ** 2` - stops slow |
| `ease_in_out` | `ease_in_out(t)` | same curve as `smoothstep` |
| `approach` | `approach(current, target, rate, dt)` | exponential smoothing, frame-rate independent |
| `move_towards` | `move_towards(current, target, max_delta)` | step capped by `max_delta` |

`approach()` is the one to use in `update()`: a fixed `rate` gives the same
feel at 30 and at 144 fps, where `lerp(a, b, 0.1)` per frame does not.

```python
def update(self, dt):
    self.volume = fe.anim.approach(self.volume, self.target, 4.0, dt)
    self.flicker = fe.anim.lerp(0.6, 1.0, fe.anim.smoothstep(
        0.5 + 0.5 * math.sin(self.t * 7.0)))
```

## `Smoothed`

A float that chases a target.

| Member | Notes |
| --- | --- |
| `Smoothed(value=0.0, rate=10.0)` | `value`, `target` and `rate` start equal |
| `update(dt)` | Move toward `target`, return the new value |
| `snap(value)` | Jump and stop chasing |

```python
self.brightness = fe.anim.Smoothed(1.0, rate=6.0)
...
def update(self, dt):
    self.brightness.target = 0.2 if self.inside_cave else 1.0
    level = self.brightness.update(dt)
    self.scene.ambient = (level, level, level)
```

## `Shake`

Decaying offset, for impacts in 2D or anywhere that is not a camera.

| Member | Notes |
| --- | --- |
| `Shake(amount=0.0, decay=3.5, seed=1)` | `seed` keeps two shakers out of phase |
| `kick(amount)` | Takes the maximum, so a small hit never cancels a big one |
| `update(dt)` | Exponential decay; snaps to `0.0` under `1e-4` |
| `offset()` | `(dx, dy)`, `(0.0, 0.0)` when idle |

Cameras carry their own: `camera.shake(amount=1.0, duration=0.35, freq=None,
scale=None, roll=None)` and `camera.stop_shake()`, and `scene.shake(...)` /
`game.shake(...)` forward to the view. Prefer those over a bare `Shake` for a
3D camera.

## `Tween`

One linear keyframe between two values, scalar or tuple.

| Member | Notes |
| --- | --- |
| `Tween(start, end, duration, ease=fe.anim.ease_in_out)` | `duration` is floored at `1e-4` |
| `update(dt)` | Advance and return the value |
| `value()` | The value right now, without advancing |
| `done` | Property - `True` at the end |

```python
def on_enter(self):
    self.tween = fe.anim.Tween((0.0, 0.0, 0.0), (0.0, 3.0, -12.0), 1.8)
    self.after(1.8, self.finish_intro)

def update(self, dt):
    super().update(dt)
    if self.tween is not None and not self.tween.done:
        self.gate.pos = self.tween.update(dt)
```

Tuples are interpolated component-wise, so a position, colour or scale all
tween through the same class.

## `FrameAnim` and sprite sheets

`FrameAnim` plays a list of pygame surfaces.

| Member | Notes |
| --- | --- |
| `FrameAnim(frames, fps=12.0, loop=True)` | `frames` are surfaces |
| `update(dt)` | Advance the clock; a looping anim wraps |
| `index` / `frame` | Current cell / current surface |
| `done` | Only meaningful with `loop=False` |

`slice_sheet(sheet, frame_w, frame_h, count=None, row=0)` cuts one row of a
sheet into surfaces - `count=None` takes every column.

In a GL scene you normally do not need it: an `Object2D` cycles its own sheet
cells.

| Member | Notes |
| --- | --- |
| `grid = (cols, rows)` | How the texture is carved |
| `frame` | The cell index currently showing |
| `set_frame(index)` | One cell, immediately |
| `cell_uv()` | The `(u0, v0, u1, v1)` of `frame` |
| `animate(fps=8.0, frames=None)` | Start cycling; `frames` are cell indices, default every cell |
| `animate(0)` | Stop, leaving the current frame |

```python
class Torch(fe.Object2D):
    def build(self):
        super().build()
        self.grid = (8, 2)
        self.animate(10.0, frames=list(range(8)))     # the top row only
```

`Object2D.update(dt)` advances the cell clock, so a paused game freezes its
sprites too.

## Timers

`scene.after` / `scene.every` are the short forms of the `Timers` scheduler.

| Call | Fires | Returns |
| --- | --- | --- |
| `after(delay, func, *args, **kwargs)` | Once | a `Timer` |
| `every(delay, func, *args, **kwargs)` | Forever, until cancelled | a `Timer` |
| `cancel(timer)` | Marks it dead; harmless to pass anything else | the timer |
| `clear()` | Kill everything in the pool | `None` |
| `update(dt)` | Run due callbacks; returns how many fired | `int` |

A repeating timer adds its own `delay` back to the remaining time instead of
resetting to full, so a `every(0.5)` tick does not drift as frames jitter. A
delay of `0` repeats once per frame. A callback that raises is printed as
`timer ... failed: ...` and the loop carries on.

| `Timer` member | Notes |
| --- | --- |
| `left` / `delay` | Countdown and period, seconds |
| `repeat` | Whether it reschedules |
| `cancel()` | Set `dead` |
| `reset(delay=None)` | Restart it, optionally on a new period |

```python
def setup(self):
    self.every(0.25, self.pulse_lamp)
    self.handle = self.every(1.0, self.tick_clock)   # extra args forwarded
    self.after(12.0, self.timers.cancel, self.handle)  # ten ticks, then stop

def tick_clock(self):
    self.count += 1
    self.status_text = f"{self.count} / 10"
```

Every `GameObject` owns a `Timers` too - `self.timers` - which is cleared with
the object, so a prop can schedule its own work without touching the scene.

## Easing a camera

Damping lives on the camera rather than in a tween object.

| Call | Effect |
| --- | --- |
| `camera.aim(yaw, pitch, dt, damping=0.0, limit=1.45, snap=False)` | Turn; `damping` eases through `anim.approach` |
| `camera.follow(target, dt, damping=None, offset=None, snap=False)` | Glide toward `target + offset` |
| `camera.set_follow(target=None, offset=None, damping=None)` | Arm a follow that runs every frame |
| `camera.look_at_point(target, dt, damping=None, ...)` | Aim at a world point, easing |
| `cam = scene.add_camera(...); cam.set_follow(ball, offset=(0, 5, -7), damping=8)` | A chase cam in two lines |

`damping` is a rate, not a blend factor: higher arrives sooner. `0.0` (the
default) snaps. Angle easing goes through `camera.wrap_angle()` so the camera
never turns the long way round.

```python
def update(self, dt):
    super().update(dt)
    self.camera.look_at_point(self.brazier.pos, dt, damping=3.0)
```

## Fades and scene changes

Transitions are time-based and owned by the game.

| Call | Behaviour |
| --- | --- |
| `scene.play_scene(name, fade=0.35)` | Fade out, load, fade in; `fade=0` cuts |
| `scene.push_scene(name, fade=0.35)` | Same, and remembers where to come back to |
| `scene.pop_scene(fade=0.35)` | Rebuild the scene underneath |
| `game.play_scene(...)` etc. | The same three, for when no scene is running |
| `game.fade` | Read the current darkness, `0.0..1.0` |

The scene swap happens at full black, so `setup()` runs unseen. A scene that
fails to load during a fade is printed as `play_scene('name') failed: ...` and
the fade finishes into whatever did load.

```python
def on_gate_opened(self):
    self.push_scene("interior", fade=0.5)

# and back, from the interior scene
def on_exit_pressed(self):
    self.pop_scene(fade=0.4)
```

Popped scenes are rebuilt from `setup()`, so the only thing that survives a
push/pop is the save slot - see [Save, Config and Paths](save-config-and-paths.md).

## Frame-rate independent movement

| Pattern | Why |
| --- | --- |
| `pos += velocity * dt` | Distance per second, not per frame |
| `anim.approach(cur, target, rate, dt)` | Same easing curve at any frame rate |
| `anim.move_towards(cur, target, max_step)` | Fixed maximum step per frame |
| `every(1.0 / fps, tick)` | Run something at a nominal frame rate |
| `scene.t` / `obj.t` | Phase a sine without counting frames |

```python
class Moth(fe.Object3D):
    def build(self):
        self.home = tuple(self.pos)      # where it was spawned

    def update(self, dt):
        super().update(dt)              # advances self.t
        angle = self.t * 1.4 + self.home[0]
        self.pos[0] = self.home[0] + math.cos(angle) * 1.6
        self.pos[2] = self.home[2] + math.sin(angle) * 1.6
        self.pos[1] = self.home[1] + 0.4 * math.sin(angle * 3.0)
```

Related pages: [Game Loop](game-loop.md), [Scenes](scenes.md),
[Objects](objects.md), [Camera and Rendering](camera-and-rendering.md).
