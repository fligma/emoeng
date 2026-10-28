# Save, Config and Paths

Three separate stores, one rule each: a **save** belongs to the game and its
player, **config** belongs to whoever runs the engine, and **paths** decides
where either may be written once the game is frozen.

## Save slots (`fe.save`)

A slot is one JSON dictionary.

```python
save = fe.SaveStore(project)             # projects/<name>/saves/autosave.json
save.set("eyes", 0)
save.add("eyes", 1)                       # numeric bump
save.flag("met_keeper")                   # True under "met_keeper"
save.save()
save.get("eyes", 0)                       # default when missing
save["eyes"]                              # KeyError when missing
"met_keeper" in save                      # flags read like a set
```

| Member | Signature | Notes |
| --- | --- | --- |
| `SaveStore` | `SaveStore(project=None, slot=const.SAVE_SLOT, autoload=True)` | `slot=None`/`""` falls back to `'autosave'` |
| `folder()` | | `<project>/saves`, or `paths.user_dir()/saves` with no project |
| `path()` | | The slot file; non-alphanumeric characters in the name become `_` |
| `load()` | | Read the file into `data`; a missing file is an empty dict, not an error |
| `save(slot=None)` | | Write and return the path used, or `None` on failure |
| `clear(save_file=True)` | | Empty the dict, and unlink the file unless asked not to |
| `get` / `set` | `get(key, default=None)`, `set(key, value)` | `set` returns the value |
| `add` | `add(key, amount=1)` | Non-numbers (and `bool`) are replaced by `amount` |
| `flag` / `unflag` | `flag(key, value=True)`, `unflag(key)` | `flag` sets, `unflag` removes the key outright |
| `has` / `pop` / `keys` | `has(key)`, `pop(key, default=None)`, `keys()` | |
| `data` | The plain dict | Read it directly for a whole-view loop |
| `loaded` / `error` | `bool`, `str` or `None` | A corrupt file sets `error` and leaves `data` empty |
| Mapping dunders | `__getitem__`, `__setitem__`, `__contains__`, `__len__` | Enough of a dict to iterate and test |

### The file on disk

```json
{
 "slot": "autosave",
 "saved": "2026-10-24 19:04:11",
 "values": { "eyes": 3, "met_keeper": true, "scene": "main",
             "pos": [1.5, 2.0, -8.0], "yaw": 1.5708, "pitch": -0.1 }
}
```

`values` is the store. A file without that wrapper is read as the values
themselves, so a hand-written `{"level": 4}` works too.

### How the game uses it

| Behaviour | Detail |
| --- | --- |
| Instance | `game.save`, built with the project and `project.save_slot` |
| `game.save_game(slot=None)` | Writes `scene`, `pos`, `yaw`, `pitch`, then calls `scene.on_save(save)`, then saves |
| `game.load_game(slot=None)` | Loads, switches to the saved scene name if it differs, `set_player(pos, yaw, pitch)`, then calls `scene.on_load(save)` |
| Timed autosave | Every `runtime.auto_save_interval` (or manifest `save.auto_save_interval`) seconds, when non-zero |
| Keys | `input.save` (F8) and `input.load` (F9) - system actions, handled by `Game._system_action` |
| Read-only folder | `save()` retries into `paths.user_dir()/saves` and stays silent |
| Hook errors | Printed as `scene on_save failed: ...`; the write still happens |

```python
class Main(fe.Scene3D):
    def on_save(self, save):
        save.set("collected", [o.tag for o in self.objects if o.collected])
        save.set("day", self.day)

    def on_load(self, save):
        self.day = int(save.get("day", 1))
        for tag in save.get("collected", ()):
            for o in self.by_tag(tag):
                o.alive = False
```

The save slot is the only thing that survives a `push_scene` / `pop_scene` pair.

## Config (`fe.config`)

One flat table of dotted keys, resolved from layers, low to high:

| Layer | File / source | Written by |
| --- | --- | --- |
| defaults | `config.SCHEMA` | The engine |
| portable | `<app_dir>/config.json` | `save()` when the user dir is unwritable |
| user | `paths.user_dir()/config.json` | `save()` (tried first) |
| migrated | an old `settings.json`'s `theme` | Adopted once, read-only |
| project | the `config` object inside `project.flig` | `write_project()` |
| env | `EMOTION_CONFIG_<GROUP>_<KEY>` | The shell |
| session | `config.set(...)` this run | Your code, until `save()` |
| cli | `Config.pin(key, value)` | A command-line flag |

```powershell
$env:EMOTION_CONFIG_RUNTIME_FPS_CAP = "144"   # runtime.fps_cap
python -m emoeng run projects/mygame
```

The name is built by lowercasing what follows the prefix and turning `_` into
`.` - so `EMOTION_CONFIG_EDITOR_LINE_NUMBERS` is `editor.line_numbers`. Only
keys in the schema are decoded; a bad value for the kind is dropped.

### Module API

| Call | Notes |
| --- | --- |
| `config.load(target=None, path=None, force=False)` | The process-wide `Config`, cached in `config.CURRENT`; `target` may be a `Project` (adds its layer) or a path (an `explicit` layer); `force=True` rebuilds |
| `config.current()` | The cached one, building it if needed |
| `config.get(key, default=None)` / `config.set(key, value)` / `config.save()` | Shortcuts onto the current instance |
| `config.entry(key)` / `config.keys(group=None)` | The `Entry`, or the key list of a group |
| `config.coerce(entry, value)` | Decode a raw value to the entry's kind, or `None` |
| `config.bind_defaults(input_obj, group="input")` | Apply every `input.*` key onto an `Input` |
| `config.key_code(name)` / `config.key_name(code)` | `'lshift'` - `K_LSHIFT` and back |
| `config.portable_path()` / `config.user_path()` / `config.legacy_paths()` | Where the files live |
| `config.VERSION` / `ENV_PREFIX` / `FILE_NAME` / `LEGACY_NAME` / `GROUPS` | `1`, `EMOTION_CONFIG_`, `config.json`, `settings.json`, `('editor','runtime','input','build','docs')` |

`Config` methods: `reload`, `use_project`, `pin`, `get`, `set`, `reset`,
`reset_group`, `changed`, `source`, `is_default`, `group`, `save`,
`write_project`, `describe`, and `in` (`"runtime.fps_cap" in cfg`).

`save()` writes only keys that differ from the defaults, atomically, to the
user file and then the portable file. `write_project()` stores just the
`runtime.*` and `input.*` keys inside `project.flig`, which is how the Settings
tab ships a project's own defaults.

### `editor.*`

| Key | Kind | Default | Label | Range / choices |
| --- | --- | --- | --- | --- |
| `editor.theme` | choice | `'dark'` | Theme | `dark`, `light` |
| `editor.open_as` | choice | `'ask'` | Open scripts as | `ask`, `text`, `blocks` |
| `editor.autosave` | bool | `True` | Autosave | |
| `editor.font_size` | int | `13` | Editor font | 8 - 32 |
| `editor.line_numbers` | bool | `True` | Line numbers | |
| `editor.minimap` | bool | `False` | Minimap | |
| `editor.recent_limit` | int | `8` | Recent projects | 0 - 40 |
| `editor.confirm_close` | bool | `True` | Confirm close | |
| `editor.hot_reload_save` | bool | `True` | Hot reload on save | |
| `editor.hot_reload_watch` | bool | `True` | Hot reload on change | |

### `runtime.*`

| Key | Kind | Default | Label | Range | Restart |
| --- | --- | --- | --- | --- | --- |
| `runtime.fps_cap` | int | `60` | FPS cap | 0 - 1000 | |
| `runtime.vsync` | bool | `True` | VSync | | |
| `runtime.render_scale` | float | `0.0` | Render scale override | 0.0 - 2.0 | |
| `runtime.fullscreen` | bool | `False` | Start fullscreen | | yes |
| `runtime.master_volume` | float | `0.8` | Master volume | 0.0 - 1.0 | |
| `runtime.music_volume` | float | `0.6` | Music volume | 0.0 - 1.0 | |
| `runtime.mouse_sensitivity` | float | `0.0022` | Mouse sensitivity | 0.0002 - 0.02 | |
| `runtime.show_fps` | bool | `True` | Show FPS | | |
| `runtime.auto_save_interval` | float | `0.0` | Autosave every (s) | 0.0 - 600.0 | |

`runtime.render_scale` is an *override*: `0.0` means "not set", so the manifest
value is used. Only `runtime.fullscreen` needs a restart.

### `input.*`

Every row is a list of binding tokens and is applied by `config.bind_defaults()`.

| Key | Default | Label |
| --- | --- | --- |
| `input.forward` | `['w', 'up']` | Forward |
| `input.back` | `['s', 'down']` | Backward |
| `input.left` | `['a', 'left']` | Strafe left |
| `input.right` | `['d', 'right']` | Strafe right |
| `input.run` | `['lshift', 'rshift']` | Run |
| `input.up` | `['space']` | Move up |
| `input.down` | `['q', 'lctrl']` | Move down |
| `input.use` | `['e']` | Use / pick up |
| `input.reload` | `['r']` | Reload scene |
| `input.pause` | `['escape']` | Pause menu |
| `input.help` | `['f1']` | Controls panel |
| `input.debug` | `['f3']` | Debug overlay |
| `input.screenshot` | `['f2']` | Screenshot |
| `input.restart` | `['f5']` | Restart scene |
| `input.hot_reload` | `['f6']` | Re-read code (hot reload) |
| `input.fullscreen` | `['f11']` | Toggle fullscreen |
| `input.save` | `['f8']` | Save game |
| `input.load` | `['f9']` | Load game |
| `input.capture_mouse` | `['f10']` | Toggle mouse capture |

The label text is what the in-game F1 panel prints, so the schema is the only
place a control name needs to be right.

Mouse capture confines and hides the pointer for continuous first-person
look. Toggle it off with F10 when using remote-control software that moves an
ordinary desktop pointer; mouse motion still turns the camera, but is limited
by the screen edges. Movement keys continue to work in either mode.

### `build.*` and `docs.*`

| Key | Kind | Default | Label |
| --- | --- | --- | --- |
| `build.trim` | bool | `True` | Trim the bundle |
| `build.onefile` | bool | `False` | One file |
| `build.windowed` | bool | `True` | Windowed |
| `build.clean` | bool | `False` | Clean before build |
| `build.log_level` | choice | `'WARN'` | Build log (`TRACE`...`CRITICAL`) |
| `docs.hover_hints` | bool | `True` | Hover hints |
| `docs.hint_delay` | float | `0.45` | Hint delay (s), 0.0 - 3.0 |

`build.*` seeds the Build tab's defaults - the full option table is in
[Building](building.md).

## Paths (`fe.paths`)

| Function | In source | In a frozen build |
| --- | --- | --- |
| `frozen()` | `False` | `True` (`sys.frozen`) |
| `bundle_dir()` | The folder above `emoeng/` | `sys._MEIPASS` |
| `package_root()` | `.../emoeng` | The unpacked copy inside the bundle |
| `app_dir()` | The repo root | The exe's folder |
| `user_dir()` | `%APPDATA%/MotionEngine`, or `~/.motionengine`, or `$EMOTION_ENGINE_HOME` | The same |
| `bundled_projects()` | `emoeng/projects` | Bundle `projects/`, else the package's |
| `projects_dir()` | `bundled_projects()` | A writable `projects/` beside the exe, seeded from the bundle on first run |
| `bundled_docs()` | `emoeng/docs` | Bundle `docs/`, else the package's |
| `writable(folder)` | Create-and-probe test - `True`/`False` | The same |

| Environment override | Effect |
| --- | --- |
| `EMOTION_ENGINE_HOME` | Use this folder as the per-user dir |
| `EMOTION_PROJECTS` | Use this folder as the projects root (created if missing) |
| `EMOTION_CONFIG_<GROUP>_<KEY>` | One config value, highest ordinary layer |
| `sys._MEIPASS` / `sys.frozen` | Set by PyInstaller; read, never set |

`user_dir()` creates the folder on the way out, so a first run has somewhere to
write settings. `projects_dir()` copies the bundled projects beside the exe only
when the local folder is missing or empty - a player's edited projects are never
overwritten by a re-run. Motion Engine release archives include both `projects/`
and `docs/` beside the executable; the docs also remain inside the frozen
package for the Docs tab. `paths.PROJECTS` is `const.PROJECTS_DIRNAME`.

```python
from emoeng.engine import paths

print(paths.projects_dir())            # where Project.default_path() looks
print(paths.user_dir() / "config.json")
if not paths.writable(project.path):
    ...                                # saves will land in user_dir()
```

Related pages: [Project Folder](project-folder.md), [Game Loop](game-loop.md),
[Player and Input](player-and-input.md), [Building](building.md).
