# Project Folder

A game is a folder. Nothing is compiled first, nothing is registered, and the
engine reads exactly the files you see in the editor.

```
hello/
├── project.flig          manifest: name, start scene, window, render, save
├── input.map.json        (optional) action -> binding names
├── assets.json           (optional) how textures and audio are imported
├── README.md             written by the engine, yours to edit
├── .gitignore            written by the engine
├── icon.png              (optional) badge, window icon and exe icon
├── scenes/               one `.scene` document per scene
│   └── main.scene        what it runs, what it places, what the editor moved
├── objects/              one `.obj3d` / `.obj2d` document per object
│   └── prop.obj3d        what it is, where it sits, how it looks
├── entities/             one `.obj3d` / `.obj2d` document per entity (NPCs, enemies)
│   └── enemy.obj3d       what it is, where it sits, how it looks, AI config
├── shaders/              one `.shader` document per screen look
│   └── scanlines.shader  its mode and knobs; the class lives in scripts
├── scripts/              all of the Python
│   ├── scenes/           one Scene3D / Scene2D / SceneUI subclass per file
│   │   └── main.py
│   ├── objects/          Object3D / Object2D / UIObject subclasses
│   │   └── prop.py
│   ├── entities/         Entity3D / Entity2D subclasses (NPCs, enemies)
│   │   └── enemy.py
│   ├── shaders/          one `fe.Shader` subclass per shader
│   │   └── scanlines.py
│   └── helpers.py        shared module: `from scripts import helpers`
├── models/               .model3d (solid) and .model2d (flat, riggable) JSON
│   └── box.model3d
├── maps/                 .map3d - the same schema, in a walked folder
│   └── keep.map3d        placed by a scene's `maps` field; builds its collider
├── textures/             .png / .jpg, uploaded by file stem
├── audio/                .wav .ogg .mp3 .flac, loaded by file stem
└── saves/                written by the game; never part of the project
```

The split is the point: `scenes/` and `objects/` hold what you placed, and
`scripts/` holds what you wrote. A document names the script it runs, so the
two halves can be edited - and reverted - separately, and an object can be a
node the engine already knows with no script behind it at all.

## Folder kinds

| Kind | `const` | Holds |
| --- | --- | --- |
| `scenes` | `KINDS` | `main.scene`, one document per scene; `scene_names()` lists the stems |
| `objects` | `KINDS` | `prop.obj3d` / `prop.obj2d`; `object_names()` lists the stems |
| `entities` | `KINDS` | `enemy.obj3d` / `enemy.obj2d`; `entity_names()` lists the stems |
| `scripts` | `KINDS`, `PACKAGES` | `scripts/scenes/`, `scripts/objects/`, `scripts/entities/` and shared modules |
| `models` | `KINDS` | `Model.load` / `Model2D.load` by stem |
| `maps` | `KINDS` | `maps/<stem>.map3d` - model documents that build a mesh collider when placed; `map_names()` lists the stems |
| `textures` | `KINDS` | `Renderer.texture` by stem |
| `audio` | `KINDS` | `Audio.load` by stem |
| `shaders` | - (watched) | `scanlines.shader` documents + `scripts/shaders/*.py`; `shader_names()` lists the stems. A folder the manifest's `post` and objects read from; see [Shaders](shaders.md) |

The project root goes on `sys.path` (`Project._add_import_path()`), so the
code folders are packages: a scene writes `from scripts.helpers import
PIXELS` and an object is imported as `scripts.objects.prop`. A `.py` left
directly in `scenes/` or `objects/` belongs to the old layout, is not
imported, and the editor flags it.

## Documents

`scenes/*.scene` and `objects/*.obj3d` / `*.obj2d` are JSON documents beside
the scripts: the script says what a thing does, the document says what it is,
where it sits and how it looks. The engine only reads them - the editor writes
them as you drag in the Scene tab - but they are plain JSON with a `format`
number, so they diff cleanly and can be hand-edited. A project written before
the split, with `*.object` and `*.model` files, is read as it is and renamed
to the dimensioned spelling when the folder is opened
(`Project.upgrade_documents`).

```json
{"format": 1, "name": "main", "kind": "scene3d",
 "script": "scripts/scenes/main.py",
 "objects": [{"id": "crate", "type": "object3d", "pos": [2.0, 0.0, 4.0],
              "children": [
                {"id": "crate/Model3D#0", "type": "model3d",
                 "model": "crate", "pos": [0.0, 0.5, 0.0]},
                {"id": "crate/Collision3D#0", "type": "collision3d",
                 "pos": [0.0, 0.5, 0.0],
                 "knobs": {"half": [0.5, 0.5, 0.5], "solid": true}}]},
             {"id": "walker", "type": "player3d",
              "script": "scripts/objects/walker.py"}],
 "overrides": {"Walker#0": {"pos": [0.0, 1.7, 4.0]}}}
```

`objects` is a tree: an entry's `children` hang off it, and a child's `pos` is
read against its parent, so moving the crate moves its picture and its shape.
An entry names either a script or one of the engine's node types - see
[Objects](objects.md) for the whole table. A scene document may also carry a
`maps` list - bare stems or `"map"`-keyed rows with a place - and
`Project.scene()` spawns a `Map3D` for each before the object tree, so a whole
level can be one file in `maps/`. An **object** document is a tree
too: `objects/prop.obj3d` files its own branch under `nodes`, so a label or a
collision shape it owns shows up nested under every placement of it - the same
structure the Project View and Scene list draw.

A project without them runs from code exactly as before, and
`Project.create()` scaffolds `scenes/main.scene` and `objects/prop.obj3d`
alongside the scripts it has always written. [Scenes](scenes.md) and
[Objects](objects.md) cover the fields and the order they are merged in.

## The manifest

`project.flig` is JSON with two kinds of keys: flat top-level values and
sections. `loader.SECTIONS` maps each section entry onto the attribute
`Project` exposes.

| Section | Key | Becomes | Notes |
| --- | --- | --- | --- |
| `window` | `size` | `project.size` | `[w, h]` pixels |
| `window` | `fullscreen` | `project.fullscreen` | Start borderless-fullscreen |
| `render` | `render_scale` / `scale` | `project.render_scale` | Internal resolution, clamped 0.2 - 1.0 |
| `render` | `post` | `project.post` | Names of `screen` shaders the project owns; empty in a new project |
| `render` | `clear_color` | read via `project.get("render", "clear_color")` | Scene default wins unless set |
| `save` | `save_slot` / `slot` | `project.save_slot` | File name in `saves/` |
| `save` | `auto_save_interval` / `autosave` | `project.auto_save_interval` | Seconds; 0 = off |
| `input` | `actions` | `project.input_map()` | `input.map.json` overrides it |
| `assets` | `textures` | `project.asset_settings()` | `assets.json` overrides it |
| `assets` | `audio` | `project.asset_settings()` | `assets.json` overrides it |

Top-level keys (`loader.TOP_KEYS`):

| Key | Becomes | Notes |
| --- | --- | --- |
| `format` | `project.file_format` | `1` = flat legacy shape, `2` = sectioned; upgraded in memory, rewritten on save |
| `name` | `project.name` | Falls back to the folder name |
| `title` | `project.title` | Window caption |
| `start` | `project.start` | Scene stem run first; falls back to the first scene file |
| `seed` | `project.seed` | Feeds `scene.rng` |
| `version` | `project.version` | Free-form game version |
| `description` | `project.description` | Shown in the project manager |
| `author` | - | Project manager / About |
| `icon` | - | Free-form entry; the picture actually used is `icon.png` beside the manifest |
| `config` | project config layer | Runtime/editor overrides for this project |
| `build` | build overrides | Written by the Build tab (`const.BUILD_META_KEY`) |

Reading and writing values:

```python
project.get("render", "post")            # one value
project.get("render")                    # the whole section as a dict
project.set("render", "post", ["grain"]) # in memory only
project.save_meta()                      # atomic write, stamps format 2
```

`read_meta(folder)` peeks at a folder's manifest without constructing a
`Project` - that is what the project manager list uses.

## Sidecar files

Written next to the manifest, so a team can share a keymap or import settings
without merging the manifest.

`input.map.json`:

```json
{
 "format": 1,
 "_help": "action -> binding names: keys ('w'), 'mouse:left', 'wheel:up', 'joy0:button0', 'joy0:axis+1'. Empty means 'use the engine default'.",
 "actions": {
  "dash": ["lshift", "joy0:button5"],
  "use": ["e", "joy0:button2"]
 }
}
```

`assets.json`:

```json
{
 "format": 1,
 "_help": "how this project's assets are imported",
 "textures": {"filter": "linear", "wrap": "repeat", "mipmaps": true,
              "tile": 0.0,
              "sheets": {"stone": {"filter": "nearest", "tile": 2.0},
                         "sky": {"mipmaps": false}}},
 "audio": {"gain": 1.0, "gains": {"drone": 0.4, "pickup": 1.2}}
}
```

| Option | Values | Effect |
| --- | --- | --- |
| `textures.filter` | `linear`, `nearest` | Sampling; `nearest` keeps pixel art hard |
| `textures.wrap` | `repeat`, `clamp` | Tiling outside 0..1 |
| `textures.mipmaps` | bool | Generate a mipmap chain (forced off for RGBA sheets) |
| `textures.tile` | metres | How wide one repeat of a sheet is in the world; 0 leaves the sheet a picture |
| `textures.sheets` | `{stem: {option: value}}` | Per-file overrides for the four above |
| `audio.gain` | float | Applied to every file at load |
| `audio.gains` | `{stem: float}` | Per-file trim |

`sheets` is the same shape as `gains`: one entry per file stem, whose keys
replace the globals for that file only and whose absences keep them. It is what
stops a low-resolution sheet from being smeared by a project that otherwise
wants smooth sampling - a 64px `stone` painted for a two-metre wall reads as
blurred mush under `linear` with mipmaps, and one entry fixes it. The setting
belongs to the sheet and not to the model because the renderer caches one GL
texture per stem, which every model naming it then shares.

### `tile`: a sheet as a material

`tile` is the one setting that changes the *geometry* rather than the sampler.
It says how many world metres one repeat of the sheet covers, and it is what
tells the renderer whether a file is a material or a picture of one particular
thing:

* a sheet **with** a metre size re-unwraps whatever wears it. Every face is
  projected from the two axes lying across it, so an 18 m wall of a 2 m stone
  draws nine repeats and a 0.5 m post draws a quarter of one - the bricks stay
  the same size wherever they land, and nothing is pulled long down the side of
  a tall model. A moving thing is anchored to its own middle, so it carries its
  texture instead of sliding through it.
* a sheet at **0** keeps the `uv` it was drawn with, which is what a face, an
  icon, a glow or a sky wants: one picture, one thing.

That is why the default is 0. Nothing re-unwraps until a project says how big
its bricks are, so adding a sheet cannot quietly restyle a model. Only the two
lit layers ask for a material - a sprite, a UI cut-out and a glow keep their
baked 0..1 window however their sheet is set up.

A sheet with a metre size takes over from the `uv` block in
`models/<name>.model3d`: the block is still read and still written, but the
world decides where the picture lands. Where a sheet *lands* on a model with no
tile size is still the `uv` block - see [Models and Meshes](models-and-meshes.md).

```python
project.texture_settings("stone")
# {'filter': 'nearest', 'wrap': 'repeat', 'mipmaps': True, 'tile': 2.0}
project.set_texture_settings("stone", filter="nearest", mipmaps=False)
project.set_texture_settings("moss", tile=1.5)   # moss is a material now
```

`texture_settings()` answers the *effective* values for one stem - globals with
that sheet's entry merged over them. `set_texture_settings()` files one entry
and writes the sidecar; only the names it is given move, and an entry that ends
up matching the globals is dropped from `sheets` again, so the file keeps
nothing but what the project actually changed.

Both files are written by `Project.save_input_map(actions)` and
`Project.save_asset_settings(settings)`; keys starting with `_` are ignored on
read, so the `_help` note can stay.

## `Project` API

### Construction and facts

| Member | Signature / type | Notes |
| --- | --- | --- |
| `Project(path)` | raises `FileNotFoundError` with no manifest | `ValueError` on bad JSON |
| `Project.default_path()` | classmethod | `DEFAULT_PROJECT` if present, else first project folder |
| `Project.create(path, title=None, start_scene=None, template='game3d')` | classmethod | Scaffold a playable folder from one of the three templates |
| `project.path`, `.name`, `.title`, `.version`, `.description`, `.seed` | values | From the manifest |
| `project.size`, `.fullscreen`, `.render_scale`, `.post`, `.save_slot`, `.auto_save_interval`, `.start` | values | Sectioned manifest values |

### Folders and listings

| Member | Returns |
| --- | --- |
| `dir(kind)` | `path/<kind>`, created if missing |
| `scenes_dir`, `objects_dir`, `scripts_dir`, `models_dir`, `maps_dir`, `textures_dir`, `audio_dir`, `shaders_dir`, `shader_scripts_dir`, `saves_dir` | the same, per kind |
| `files(kind)` | every file in that folder |
| `scene_names()`, `object_names()`, `script_names()`, `shader_names()` | stems |
| `model_names()`, `model2d_names()`, `map_names()` | `.model3d` (old `.model` too) / `.model2d` / `.map3d` stems |
| `texture_files()`, `audio_files()` | paths |
| `relative(path)` | project-relative display path |
| `model_path(name)`, `model2d_path(name)`, `object_path(name)` | path for a stem |

### Assets

| Member | Notes |
| --- | --- |
| `model(name)` / `store_model(model, name=None)` | Load-and-cache / save-and-refresh a `.model3d` |
| `map(name)` / `store_map(model, name=None)` | The same pair for `maps/<stem>.map3d`, read through the model loader; `map_path(name)` prefers the `.map3d` spelling |
| `model2d(name)` / `store_model2d(model, name=None)` | Same for `.model2d` |
| `texture(name)` | Load a texture file into a numpy array |
| `register_textures(renderer, verbose=None)` | Upload every file, filtered as `assets.json` asks, per sheet included |
| `texture_settings(name)` | The effective filter / wrap / mipmaps / tile for one stem |
| `set_texture_settings(name, **opts)` | File one sheet's settings and write the sidecar |
| `load_audio(audio)` | Fill the bank with this project's gains applied |
| `reload_models()`, `reload_objects()`, `reload_scripts()` | Drop caches so the next read re-imports |

### Code

| Member | Notes |
| --- | --- |
| `object(name, base=Object3D)` | The class an object name means: `scripts/objects/<name>.py` when it has a script, one of `engine.components` when its document names only a `type`. The `.obj3d` / `.obj2d` beside it becomes the class's `look_defaults` |
| `node_class(type, base)` | The engine class a document's `type` states, or None when the scene's kind cannot host it |
| `scene(name, game, plan=None)` | Import the document's `script` (or `scripts/scenes/<name>.py`), check `uses`, `setup()`, place the document's object tree, `finish_build()` |
| `scene_script(name)` | The `.py` a scene runs, read from its document's `script` field |
| `scene_doc(name)` / `save_scene_doc(name, doc)` | Read `scenes/<name>.scene` fresh / write it |
| `object_doc(name)` / `save_object_doc(name, doc)` | The same pair for `objects/<name>.obj3d` or `.obj2d`, by the document's `type` |
| `shader_doc(name)` / `save_shader_doc(name, doc)` | Read / write `shaders/<name>.shader` |
| `shader_class(name)` / `shader_script(name)` | The `fe.Shader` class a stem means, and the `scripts/shaders/<name>.py` it is imported from |
| `load_shaders()` | Import every `scripts/shaders/*.py`; name -> class, mirroring object scripts |
| `upgrade_documents()` | Rename legacy `.object` / `.model` files; run for you when the project opens |
| `check_uses(cls, seen=None, base=Object3D)` | Object stems a scene (or object) needs but the project lacks |
| `snapshot(kinds=None)` / `changed_since(snap, kinds=None)` | mtime+size watch over `WATCHED` = `scenes`, `objects`, `scripts`, `shaders` |
| `touch(kind, name)` | Create an empty file (the editor's New buttons) |
| `ensure_templates(gitignore=True, readme=True)` | Write the folder docs, never overwriting |

## A note on `uses`

A scene names the objects it spawns:

```python
class Main(fe.Scene3D):
    uses = ("prop", "gem")
```

`Project.scene()` runs `check_uses()` before anything is built, so a missing
`scripts/objects/gem.py` fails with `scene 'main' needs
scripts/objects/gem.py` instead of failing later inside `spawn()`. An object
that needs no script passes the check on its document alone: an
`objects/gem.obj3d` naming a type the engine knows is a whole object. The same
check follows an object's own `uses`, so a prop that spawns motes drags
`scripts/objects/motes.py` into the check too. It is also how the bundle pruner
knows which object files a game actually needs.

## Saving and the `saves/` folder

The game writes `saves/<slot>.json` (default slot `autosave`). The generated
`.gitignore` excludes `saves/` and `__pycache__/` - saved state is per player,
not part of the project. See [Save, Config and Paths](save-config-and-paths.md).
