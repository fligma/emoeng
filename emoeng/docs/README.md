# Motion Engine Documentation

Motion Engine (`emoeng`) is a Python game engine built on pygame, moderngl and
numpy, with its own editor. A game is a folder of plain files - Python scenes,
JSON manifests, JSON models, PNG textures, WAV/OGG audio - that the engine runs
as-is and freezes into an executable when you want to ship it.

Version documented here: `const.VERSION` (see [Constants](#constants)).

## Pages

| Page | What it covers |
| --- | --- |
| [Getting Started](getting-started.md) | Install, run the editor, scaffold a project, first scene, default keys |
| [Project Folder](project-folder.md) | Folder layout, `project.flig` manifest, sidecar files, `Project` API |
| [Game Loop](game-loop.md) | `Game`, the frame order, window state, scene switching, save/reload hotkeys |
| [Scenes](scenes.md) | `Scene`, `Scene3D`, `Scene2D`, `SceneUI` - hooks, class attributes, spawning, cameras, `.scene` documents with a node tree, screens |
| [Objects](objects.md) | `GameObject`, `Object3D`, `Object2D`, `UIObject`, `ModelObject`, `Screen3D`/`Screen2D`, cloning, node types and hierarchy, `.obj3d` / `.obj2d` documents |
| [Player and Input](player-and-input.md) | `Player3D`, `Player2D`, `Input`, binding tokens, rebinding, gamepads |
| [Camera and Rendering](camera-and-rendering.md) | `Camera`, `Camera2D`, `CameraHost`, `OrbitCamera`, `Renderer`, shader `post` chains |
| [Shaders](shaders.md) | `Shader` modes (`screen`/`uv`/`texture`), the `g` builder, `.shader` documents, stock templates |
| [Lighting](lighting.md) | `Light`, `Light3D`, `Light2D`, shapes, occlusion, presets, animation, colour as a texture |
| [Models and Meshes](models-and-meshes.md) | `.model3d` / `.model2d` formats, `Model` API, `meshes` builders, `proctex` |
| [Animation and Timing](animation-and-timing.md) | `anim` easing, `Smoothed`, `Shake`, `Tween`, `FrameAnim`, `Timer`/`Timers` |
| [Collision](collision.md) | AABB helpers, swept movement, sphere depenetration, ground clamping |
| [UI and HUD](ui-and-hud.md) | `engine.ui` HUD drawing, the `self.hud` facade, `UIObject` widgets, `xp` widget primitives, `theme` |
| [Audio](audio.md) | `Audio` bank, positional sound, music, the built-in synth, per-file gains, `.sfxproject` sound projects |
| [Save, Config and Paths](save-config-and-paths.md) | `SaveStore` slots, the layered config schema, `paths` locations |
| [Building](building.md) | PyInstaller front end, every build option, bundle pruning, command-line build |
| [Editor](editor.md) | The IDE: tabs, menus, shortcuts, project manager, hot reload, preview |
| [Blocks](blocks.md) | The Blocks tab: reading and writing `.py` as a graph of nodes, and a palette for every scene and object type |

## Module map

`import emoeng as fe` gives you the authoring names; `import emoeng.engine as
engine` gives you the modules themselves.

| Module | Contents |
| --- | --- |
| `fe.anim` | Easing functions, `Smoothed`, `Shake`, `Tween`, `FrameAnim`, `slice_sheet` |
| `fe.audio` | `Audio` sound bank, mixer setup, synth (`tone`, `sweep`, `noise`) |
| `fe.build` | `BuildConfig`, the PyInstaller option table, command-line build |
| `fe.camera` | `Camera`, `Camera2D`, `CameraHost`, `OrbitCamera`, angle easing |
| `fe.collision` | AABB construction, ray tests, `move_slide`, `sphere_push`, `ground_clamp` |
| `fe.components` | The document's own nodes: `Model3D`, `Sprite2D`, `Collision3D`/`2D`, `Hitbox3D`/`2D`, `LightNode3D`/`2D` |
| `fe.colors` | One colour parser: hex / `rgb()` / tuples / words, colour as a texture key |
| `fe.config` | Layered settings: schema, `Config`, env overrides, key-name mapping |
| `fe.const` | Identity constants: name, version, file names, folder kinds |
| `fe.Game` | Runtime: window, chrome, renderer, audio, camera, one scene loop |
| `fe.input` | `Input`: named actions bound to keys, mouse, wheel and gamepad |
| `fe.lights` | `Light`, `Light3D`, `Light2D`, shapes, falloff, presets, 2D occlusion maths |
| `fe.loader` | `Project`: manifest, sidecars, asset loading, hot reload, scaffolding |
| `fe.meshes` | Geometry builders returning `MeshData`; 2D quads and billboards |
| `fe.model` | `Model`, `Model2D`, primitive factories, `.model3d` / `.model2d` IO |
| `fe.objects` | `GameObject`, `Object3D`, `Object2D`, `UIObject`, `ModelObject` |
| `fe.paths` | File locations in source and in a frozen build |
| `fe.player` | `Player3D`, `Player2D` (`Player` is an alias of `Player3D`) |
| `fe.proctex` | Runtime texture synthesis from numpy noise |
| `fe.prune` | Bundle planning: what one project needs, what to leave out |
| `fe.renderer` | `Renderer`, `DynamicMesh`, projection and view matrices |
| `fe.save` | `SaveStore`: JSON save slots with flags and counters |
| `fe.scene` | `Scene`, `Scene3D`, `Scene2D`, `SceneUI` |
| `fe.scenedoc` | `.scene` / `.obj3d` / `.obj2d` / `.shader` documents: format, node types, look fields, project paths |
| `fe.screen` | `Screen3D`, `Screen2D` - one scene shown inside another |
| `fe.shaders` | `Shader`, the `g` `Builder`, GLSL compile, `ShaderPass`, the project's shader registry |
| `fe.sfx` | `.sfxproject` patterns: `render`, `write_wav`, `flatten`, sidechained tone tracks and wav samples |
| `fe.templates` | Starter projects, stock shaders and colour-only assets a new project is built from |
| `fe.theme` | Dark/light palettes for editor and runtime chrome |
| `fe.timers` | `Timer`, `Timers`: delayed and repeating calls |
| `fe.ui` | HUD drawing: text, panels, bars, crosshair, prompts, menus, subtitles |
| `fe.winchrome` | Borderless window behaviour: drag, resize, maximize, fullscreen |
| `fe.xp` | Luna/XP widget primitives the editor and pause screens are drawn with |

`build` and `prune` are authoring tools. They are resolved lazily through
`engine.__getattr__`, so a shipped game never imports - and never bundles -
them.

## Names you re-export

| Name | Module | Meaning |
| --- | --- | --- |
| `Scene`, `Scene3D`, `Scene2D`, `SceneUI` | `engine.scene` | Playable screens |
| `GameObject`, `Object3D`, `Object2D`, `Entity3D`, `Entity2D`, `UIObject`, `ModelObject` | `engine.objects` | Things a scene spawns |
| `Model3D`, `Sprite2D`, `Collision3D`, `Hitbox3D`, `Collision2D`, `Hitbox2D`, `LightNode3D`, `LightNode2D` | `engine.components` | Nodes a document places with no script |
| `Player`, `Player3D`, `Player2D` | `engine.player` | Controllable objects |
| `Screen3D`, `Screen2D` | `engine.screen` | A scene shown inside another scene |
| `Light`, `Light2D`, `Light3D` | `engine.lights` | Lights in either world |
| `Camera`, `Camera2D`, `CameraHost`, `OrbitCamera` | `engine.camera` | View rigs |
| `Renderer`, `DynamicMesh` | `engine.renderer` | The GL front end |
| `Shader` | `engine.shaders` | A look a project owns as a file |
| `Model`, `new_model` | `engine.model` | Mesh documents |
| `Model2D`, `new_model2d` | `engine.model` | Flat rig documents: parts and tracks |
| `Project` | `engine.loader` | A project folder |
| `Game` | `engine.game` | The runtime |
| `Input` | `engine.input` | Named action bindings |
| `SaveStore` | `engine.save` | Save slots |
| `Timer`, `Timers` | `engine.timers` | Scheduling |
| `const` | `emoeng.const` | Identity constants |

## <a name="constants"></a>Constants (`fe.const`)

| Constant | Value | Used for |
| --- | --- | --- |
| `NAME` | `'emoeng'` | Package name, import root |
| `CODENAME` | `'Motion Engine'` | Spoken name |
| `VERSION` | `'1.0'` | Window titles, About dialog, project stamping |
| `TITLE` / `SUBTITLE` | `'Motion Engine'` / `'Game engine and editor'` | Chrome text |
| `AUTHOR` | `'fligma'` | Manifest default |
| `WEBSITE` | `'https://github.com/fligma'` | About dialog |
| `ENGINE_NAME` | `'MotionEngine'` | Executable and screenshot prefix |
| `USER_DIR_NAME` | `'MotionEngine'` | Per-user save/settings folder name |
| `MANIFEST_NAME` | `'project.flig'` | Project marker file |
| `ICON_NAME` | `'icon.png'` | Project picture beside the manifest: manager badge, window and exe icon |
| `INPUT_MAP_NAME` | `'input.map.json'` | Keymap sidecar |
| `ASSET_MAP_NAME` | `'assets.json'` | Asset-import sidecar |
| `GITIGNORE_NAME` / `README_NAME` | `'.gitignore'` / `'README.md'` | Folder docs |
| `PROJECTS_DIRNAME` | `'projects'` | Projects root |
| `DEFAULT_PROJECT` | `'demo'` | Preferred project when one is not named |
| `PROJECT_FORMAT` | `2` | Manifest shape this version writes |
| `SAVE_SLOT` | `'autosave'` | Default slot name |
| `BUILDER` | `'PyInstaller'` | Freezer used by the Build tab |
| `BUILD_META_KEY` | `'build'` | Manifest section holding build overrides |
| `KINDS` | `('scenes', 'objects', 'scripts', 'models', 'maps', 'textures', 'audio')` | Asset folders |
| `PACKAGES` | `('scenes', 'objects', 'scripts')` | Folders imported as Python packages |

## How a game fits together

```python
import emoeng as fe

class Main(fe.Scene3D):                 # scripts/scenes/main.py
    name = "main"
    uses = ("crate",)                   # objects/crate.obj3d, or its script

    def setup(self):                    # once, before the first frame
        self.renderer.texture("ground", fe.proctex.ground(256))
        self.add(fe.meshes.plane(size=(60, 60)), texture="ground")
        self.player = self.spawn(fe.Player3D, pos=(0.0, 0.0, 9.0))
        self.spawn("crate", (2.0, 0.0, 4.0))

    def update(self, dt):               # every frame
        super().update(dt)

game = fe.Game("emoeng/projects/mygame")
game.run()
```

The usual way to run that is the editor or `python -m emoeng run <path>`, not a
hand-written `Game(...)` call - see [Game Loop](game-loop.md).
