# Getting Started

## Requirements

| Need | Value |
| --- | --- |
| Python | 3.13 (the engine is developed on 3.13.13) |
| pygame | 2.6.1 (SDL 2.28.4) |
| moderngl | requires an OpenGL 3.3 core context |
| numpy, Pillow | geometry arrays and image loading |
| Platform | Windows, Linux or macOS; the borderless window chrome is best on Windows |

## Commands

Everything runs through the package. `path` is always a project folder - the
one that contains `project.flig`.

| Command | What it does |
| --- | --- |
| `python -m emoeng` | Open the editor on the project manager |
| `python -m emoeng editor [path]` | Open the editor on one project |
| `python -m emoeng editor [path] --frames 1` | Open and draw one editor frame (smoke test) |
| `python -m emoeng run [path]` | Play a project in its own window |
| `python -m emoeng run [path] --frames 120` | Stop after N frames (used by smoke tests) |
| `python -m emoeng --run [path]` | Same as `run`; the form desktop shortcuts use |
| `python -m emoeng build [path] [options]` | Freeze a project with PyInstaller |
| `python -m emoeng new <path> [title]` | Scaffold a new project |
| `python -m emoeng help` | Print the CLI help |

`emoeng/__main__.py` also runs directly (`python emoeng/__main__.py ...`) - it
inserts the package's parent onto `sys.path` when run as a script.

## Your first project

```powershell
python -m emoeng new emoeng/projects/hello "Hello World"
python -m emoeng editor emoeng/projects/hello
```

`Project.create()` writes:

| Written | From |
| --- | --- |
| `scenes/`, `objects/`, `shaders/`, `models/`, `textures/`, `audio/`, `scripts/scenes/`, `scripts/objects/`, `scripts/shaders/` | fixed folder set, made whether the template fills them or not |
| `project.flig` | `templates.manifest(...)` - `render.post` is empty on purpose |
| `scripts/scenes/<start>.py` + `scenes/<start>.scene` | the template's playable scene script and the document that places it |
| `scripts/objects/<name>.py` + `objects/<name>.obj3d`/`.obj2d` | one spawnable object and its document, which files the object's collision child under it |
| `scripts/helpers.py` | `templates.SCRIPT_TEMPLATE` |
| `models/<stem>.model3d` | `templates.MODELS` primitives, built tinted and wearing no image file |
| `maps/<stem>.map3d` | `templates.MAPS` - `game3d` ships a `room`: a floor and two walls, each its own object |
| `.gitignore`, `README.md` | `ensure_templates()` - never overwritten |

Three templates start a project, chosen in the New Project dialog (or the
`template=` argument to `Project.create`):

| Key | Title | What it gives you |
| --- | --- | --- |
| `game3d` | Game 3D | A first-person world: a grid floor, one prop, a `Player3D`, warm light |
| `game2d` | Game 2D | A flat arena: a backdrop, one sprite, a steered `Player2D`, wheel zoom |
| `menu` | Menu | Widgets on the window: a title and a button that quits |

All three ship zero PNGs and zero audio - the floor is `proctex.grid`, the
models are tinted primitives, the `game3d` starter map is three boxes of the
same procedural sheets, and a look is a file you choose to add to
`shaders/`, not a default. The generated `game3d` manifest:

```json
{
 "format": 2,
 "name": "hello",
 "title": "Hello World",
 "start": "main",
 "version": "0.1.0",
 "description": "",
 "seed": 7,
 "window": {"size": [1152, 700], "fullscreen": false},
 "render": {"scale": 0.75, "post": []},
 "save": {"slot": "autosave", "autosave": 0.0}
}
```

Press `F5` in the editor to run the project in its own window, or use
`Project > Play Scene` to play it inside the Scene tab. `F6` switches to the
Scene tab, `F7` to Code, `F12` to the in-editor Docs. `Ctrl+D` opens the
Document tab, where a `.scene` or `.obj3d`/`.obj2d` file is edited as a
form - nodes, collisions, knobs and all - instead of as JSON.

## The scene you get

The `game3d` template writes a playable `scripts/scenes/main.py` and a
`scenes/main.scene` that places its prop - the core API in one screen:

```python
class Main(fe.Scene3D):
    name = "main"
    uses = ("prop",)                # scripts/objects/prop.py must exist

    clear_color = (0.05, 0.06, 0.09)
    fog_color = (0.06, 0.07, 0.11)
    fog_near = 24.0
    fog_far = 120.0
    ambient = (0.34, 0.35, 0.40)
    sun_dir = (0.4, 0.9, 0.3)
    sun_col = (0.50, 0.48, 0.46)

    def setup(self):
        # `grid` is one of the sheets the engine always has: a new project
        # ships no image file and still has a floor to stand on
        self.renderer.texture("grid", fe.proctex.grid(128, 8))
        self.add(meshes.plane(size=(40, 40), seg=8), texture="grid")
        self.add_light((0.0, 2.6, -4.0), "fire", radius=9.0)
        self.player = self.spawn(fe.Player3D, pos=(0.0, 0.0, 6.0),
                                 move_speed=(5.0, 9.0), world_radius=19.0)
```

The prop is placed by the scene's document, not by code - and its own
`objects/prop.obj3d` files a `Collision3D` under it, so dragging the prop
in Edit mode drags its shape along too. That is the node tree: a scene row
opens onto the nodes it places, and a node opens onto the children its
source document owns.

The demo project (`emoeng/projects/demo`) is a pair of rooms that wear the
same clothes. **Prism Hall** is a walkable 3D stone room that starts plain -
no shader on any surface, no wash on the picture - with a lectern standing in
the middle holding a `Screen3D` of nine switches. Click one through the glass
and a single part of the room changes its material: the floor, the walls, the
arches, the portals, the plinths, the lectern. Two more dress a whole picture
rather than a surface - the hall's own frame, and the panel's - and the last
puts everything back. Keys **1** to **9** do the same thing as the nine
switches, because a click on a panel and a press of a key both just broadcast
a named trigger and let the room answer it. Solid collision shapes stop you at
the walls, the plinths and the stand.

Press **Tab** for **Echo Room**, the same room drawn flat. Here there is no
pointer inside a picture, so the switches are `Hitbox2D` plates on the floor:
walk the `Player2D` up to one with **WASD** and a dialog opens over it naming
what it activates, how to pull it and what the room answered last. Stand on it
and press **E**, or click the plate. Its lectern holds a readout instead of a
board. The project's [demo README](../projects/demo/README.md)
has the complete controls and feature map.

Four ideas do all the work:

| Idea | API |
| --- | --- |
| A scene is a `Scene` subclass in `scripts/scenes/`, placed by a `scenes/<name>.scene` document | `fe.Scene3D`, `fe.Scene2D`, `fe.SceneUI` |
| Static geometry is queued, then merged into batches | `scene.add(...)`, `scene.place_model(...)`, `scene.finish_build()` |
| Everything that moves is an object the scene spawns | `scene.spawn(cls_or_stem, pos, **kw)` - and a document can hang nodes under it |
| The player is one of those objects | `scene.spawn(fe.Player3D, pos)` - it claims the camera |

## Default keys

Actions are named and rebound through configuration; these are the shipped
defaults.

| Action | Default | What happens |
| --- | --- | --- |
| `forward` / `back` | `W` `Up` / `S` `Down` | Move |
| `left` / `right` | `A` `Left` / `D` `Right` | Strafe |
| `run` | `L-Shift` `R-Shift` | Second move speed |
| `up` / `down` | `Space` / `Q` `L-Ctrl` | Fly mode elevation |
| `use` | `E` | Interact - your scene decides what it means |
| `reload` | `R` | Free for the game to use (the engine does not) |
| Mouse | look | 3D scenes only |

Engine-level keys, also configurable:

| Key | Action name | Effect |
| --- | --- | --- |
| `Esc` | `pause` | Pause overlay |
| `F1` | `help` | Controls panel, generated from the live keymap |
| `F2` | `screenshot` | PNG next to the game |
| `F3` | `debug` | Renderer, camera and scene counters |
| `F5` | `restart` | Restart the current scene |
| `F6` | `hot_reload` | Re-read the project's code without quitting |
| `F8` / `F9` | `save` / `load` | Write / read the autosave slot |
| `F11` | `fullscreen` | Borderless fullscreen |
| `Ctrl+T` | (not rebindable) | Dark / light theme |

## Where the settings live

Configuration resolves through six layers, lowest first. See
[Save, Config and Paths](save-config-and-paths.md).

| Layer | Where |
| --- | --- |
| Defaults | `config.SCHEMA` |
| Portable | `config.json` beside the exe or repo |
| User | per-user `MotionEngine/config.json` |
| Project | the `config` object inside `project.flig` |
| Environment | `EMOTION_CONFIG_<GROUP>_<KEY>` |
| Command line | `Config.pin(...)` |

## Next reads

| If you want to | Go to |
| --- | --- |
| Lay out a bigger game | [Project Folder](project-folder.md), [Scenes](scenes.md) |
| Make something move | [Objects](objects.md), [Animation and Timing](animation-and-timing.md) |
| Ship a menu or HUD | [UI and HUD](ui-and-hud.md) |
| Look at how it renders | [Camera and Rendering](camera-and-rendering.md) |
| Turn it into an .exe | [Building](building.md) |
