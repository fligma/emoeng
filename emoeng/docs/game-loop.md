# Game Loop

`fe.Game` owns everything a running game needs: the window and its XP chrome,
the renderer, the audio bank, input, the camera, the save store, and exactly
one live scene. You normally never write this class - the CLI and the editor do
- but you can subclass it to add global state.

```python
import emoeng as fe
from emoeng.engine.loader import Project

game = fe.Game(Project("emoeng/projects/hello"), title="Hello", size=(1280, 720))
game.run()
```

## Constructor

| Parameter | Default | Meaning |
| --- | --- | --- |
| `project` | required | A `Project`, or a path to one |
| `title` | `None` | Overrides the manifest title |
| `size` | `None` | Overrides `window.size` |
| `render_scale` | `None` | Overrides config, then manifest |
| `master_volume` | `None` | Overrides `runtime.master_volume` |
| `seed` | `None` | Reserved; scenes take their seed from the project |

What it builds, in order: `config.load(project)` -> `pygame.init()` (mixer
pre-initialised 44100 Hz, 16-bit, stereo, 512 buffer) -> theme applied ->
window mode (resizable, `vsync=1` when configured) -> fonts -> `Renderer` ->
project textures registered -> `Audio` + starter kit + project sounds ->
`Input` + keymap layers -> `SaveStore` -> `WindowChrome` -> camera -> the start
scene.

## Attributes you read from a scene

| Attribute | Type | Notes |
| --- | --- | --- |
| `game.project` | `Project` | The open folder |
| `game.scene` | `Scene` | The live scene |
| `game.screen` | `pygame.Surface` | The window surface, for `overlay()` drawing |
| `game.renderer`, `game.audio`, `game.input`, `game.save`, `game.chrome` | subsystems | Also reachable as `scene.renderer` etc. |
| `game.camera` | `Camera` | One rig behind `eye` / `yaw` / `pitch` (`CameraHost`) |
| `game.eye`, `game.yaw`, `game.pitch` | values | Live camera transform |
| `game.fonts` | dict | `small` 11, `normal` 13, `big` 18 bold, `title` 28 bold, `mono` 12 |
| `game.time` | float | Seconds of unpaused play |
| `game.last_dt`, `game.fps` | float | The clamped simulation step, and the real rate |
| `game.frame_ms` | float | Mean frame time over the last 30 frames - what the meters show |
| `game.paused`, `game.show_help`, `game.debug` | bool | Overlay states |
| `game.running` | bool | Set `False` (or call `quit()`) to leave the loop |
| `game.fps_cap`, `game.vsync`, `game.fullscreen` | values | Window pacing |
| `game.autosave_every` | float | Seconds; 0 = off |
| `game.fade` | float | Current fade 0..1 |
| `game.scene_stack` | list | `push_scene` history |
| `game.cfg` | `Config` | The merged settings view |
| `game.binding_conflicts` | list | Tokens shared by two actions |

## Methods you call

| Method | Signature | Effect |
| --- | --- | --- |
| `run` | `run(limit=None)` | Main loop; `limit` stops after N frames |
| `load_scene` | `load_scene(name=None)` | Build a scene fresh (default: the current name) |
| `restart_scene` | | Rebuild the current scene from scratch |
| `play_scene` | `play_scene(name, fade=0.35)` | Fade out, swap, fade in |
| `push_scene` | `push_scene(name, fade=0.35)` | Stack a scene (a menu over the world) |
| `pop_scene` | `pop_scene(fade=0.35)` | Return to the scene underneath |
| `save_game` | `save_game(slot=None)` | Camera + scene snapshot into the store |
| `load_game` | `load_game(slot=None)` | Read the slot, switch scene, restore |
| `set_player` | `set_player(pos, yaw=None, pitch=None)` | Teleport the camera (legacy, no Player) |
| `follow` | `follow(target, offset=None, damping=None)` | Chase an object or point |
| `pause` / `resume` / `quit` | | Freeze updates, leave the loop |
| `shutdown` | | Release the scene's GPU objects, then the context; safe to call twice |
| `screenshot` | | PNG named `motionengine_<n>.png` |
| `play_area` | | `Rect` the scene's HUD is seen through, minus the chrome bars |
| `reload_code` | | Re-read scripts, objects, models, textures and the scene |
| `reload_config` | | Re-read config and apply the live-able knobs |
| `key_text` | `key_text(action)` | The bindings of an action, in words |
| `control_hint` | | One-line key hint for the status bar |
| `controls` | | `(control, meaning)` pairs for the F1 panel |

## Frame order

`Game.run()` does this every iteration:

| Step | Detail |
| --- | --- |
| 1. `clock.tick(fps_cap)` | The frame time the clock measured, kept as measured |
| 2. fps estimate | `frame_ms` is the mean of the last 30 raw frame times and `fps` is `1000 / frame_ms`, so the meters report the rate the loop is really running at |
| 3. `input.begin_frame()` | Clears per-frame pressed/released sets |
| 4. event pump | `handle_event(e)` for every queued pygame event |
| 5. `_sync_surface()` | Adopt a new window surface after a resize |
| 6. chrome drag | `chrome.update()` while the caption is held |
| 7. if not paused | `time += dt`; `_mouse_look()` (3D only) |
| 8. `scene.update(dt)` | Wrapped in `try/except` - it prints `scene update failed: ...` and keeps running |
| 9. 3D only | `_camera_move(dt)` then `sync_camera(scene, dt)` |
| 10. `_tick_fade(dt)` | Swaps the pending scene at full black |
| 11. timed autosave | When `autosave_every > 0` |
| 12. `draw()` | See below |
| 13. `display.flip()` | Then the caption is re-set to `title - scene name` |

A `finally` block stops every sound, calls `shutdown()` and then
`pygame.quit()`, so a crash still leaves a clean process. That order is not
a style choice. `pygame.quit()` destroys the GL context, and any moderngl
object still alive then is freed by whichever garbage collection finds it
first - on a software driver (a headless Linux runner, for instance) a
`__del__` that calls into a dead context is a segfault at exit with no
Python frame to blame. `shutdown()` therefore releases everything the engine
made, in order outward from the scene, collects what a scene switch or a
rebuild left unreachable, and closes the context last, all while the driver
is still there to hear it.

Only the step the simulation sees is clamped: `dt = min(0.05, raw)`. A 200 ms
hitch - a window drag, an alt-tab, a GC pause - must not move a body 200 ms in
one go, but hiding it from the meter would be lying. `last_dt` is the clamped
step; `frame_ms` and `fps` are the measurement.

### Inside `draw()`

| Step | Detail |
| --- | --- |
| `scene.render(self.camera)` | The scene's own active view wins over the passed camera |
| `set_post(resolve(project, passes))` | `scene.post` if set, else `project.post`; screen shaders armed on the renderer, in order |
| scale to the view rect | The internal render target is stretched up |
| letterbox fill | `scene.clear_color` when the view is smaller than the window |
| `scene.overlay(screen)` | Your HUD code; an exception prints `overlay error:` on screen instead of killing the frame |
| `_draw_chrome()` | Caption, menu bar, status bar |
| `_draw_debug()` | F3 counters |
| `_draw_help()` | F1 panel, generated from the live keymap |
| `_draw_pause()` | Pause screen |
| `_draw_fade()` | Fade wash |

## Scene updates and pausing

`Game.paused` freezes step 7-11: `scene.update()` is not called, so no timers
fire, no object moves and no camera eases. The scene still renders, the chrome
still responds and the pause menu still takes clicks. To pause from a scene:

```python
class Main(fe.Scene3D):
    def setup(self):
        self.every(30.0, self.game.pause)     # an unwelcome break
```

## Hot reload

| From | What |
| --- | --- |
| `F6` in a running game | `reload_code()`: rebuild `Project`, forget imported `scripts`/`objects`, reload the scene's code, re-fill audio and textures |
| Save inside the editor | The preview restarts when a watched file is written (`editor.hot_reload_save`) |
| External editor | A file watch (`editor.hot_reload_watch`) picks up writes made outside |

Scenes are imported fresh each load under a generated module name, so a
hot reload genuinely re-executes `scripts/scenes/main.py`.

## Window chrome

The runtime window is borderless with a drawn caption (`winchrome.WindowChrome`
plus `xp.titlebar`), a `Game / View / Help` menu bar and a status bar. Dragging
the caption, grabbing an edge to resize, minimizing, maximizing to the work area
and manual borderless fullscreen are all handled by `WindowChrome`; games add
their own HUD on top.

| Constant | Value |
| --- | --- |
| `CAP_H` | 28 |
| `MENU_H` | 22 |
| `STATUS_H` | 22 |
| `MENU_LABELS` | `('Game', 'View', 'Help')` |

Those bars are painted after `scene.overlay()`, so they cover whatever the
scene drew underneath them. `game.play_area()` is the rect that is left -
`(0, CAP_H + MENU_H, w, h - CAP_H - MENU_H - STATUS_H)` - and the whole window
when the chrome is fullscreen. `scene.hud.area` is the same rect, and every
default HUD position the `Hud` facade picks is measured from it.

## Standalone entry point

```python
from emoeng.engine.game import main
main("emoeng/projects/hello", frames=120)   # frames=None runs until closed
```

`main()` falls back to `Project.default_path()` when no path is given, which is
why `python -m emoeng run` with no argument opens the demo project if one is
present.

When the loop ends, `main()` calls `finish_process()`: it flushes the two
streams and ends the process there, because neither SDL nor moderngl promises
to free what they made for themselves before Python's last collection runs.
There is nothing left to lose at that point - saves and config write as they
change, not on the way out. Set `EMOENG_NO_HARD_EXIT` to keep the interpreter's
own exit path instead, which is what an embedded run should do.
