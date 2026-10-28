# The Editor

The editor is a pygame window drawn with the engine's own `xp` widget
primitives, in the same Luna/XP style the runtime pause screens use. It is
borderless: the painted caption strip is the titlebar. One project folder is
open at a time, and every tab reads and writes files inside that folder -
nothing is stored in a private document format.

```powershell
python -m emoeng                       # project manager, then the editor
python -m emoeng editor mygame         # straight into one project
python -m emoeng run mygame --frames 90
python -m emoeng build mygame
python -m emoeng new mygame "My Game"  # scaffold a project folder
python -m emoeng --run mygame          # the form a desktop shortcut uses
```

| First argument | Routed to |
| --- | --- |
| *(none)* | `editor.app.main(None)` - shows the project manager |
| `editor [path]` | `editor.app.main(path)` |
| `run [path] [--frames N]` | `engine.game.main(path, frames=N)` |
| `--run [path]` | rewritten to `run` before dispatch |
| `build [path] ...` | `engine.build.main(...)` - see [Building](building.md) |
| `new <path> [title]` | `Project.create(path, title=title)` |
| `-h`, `--help` | prints the module docstring |
| anything else | treated as a project path for the editor |

The editor's own loop is deliberately small
(`emoeng/editor/app.py`, `Editor.run`):

| Step | What happens |
| --- | --- |
| `clock.tick(fps_cap)` | `dt`, clamped to `0.05` s so a stall cannot jump the world |
| smoothed `fps` | `fps * 0.9 + (1/dt) * 0.1` |
| `handle_event(e)` | chrome, menus, dialogs, then the active tab, then global shortcuts |
| `code.update(dt)` | caret blink and hover-hint timing |
| `_watch_tick()` | the 2-second file watch behind hot reload |
| `_sync_surface()` | resizes the pygame surface to match the OS window |
| `draw()` + `display.flip()` | one repaint |
| `finally` block | saves any dirty code/blocks/model, stops media and audio, `pygame.quit()` |

## Window layout

| Constant | Value | Region |
| --- | --- | --- |
| `CAP_H` | 28 | Caption: title, minimize / maximize / close, drag to move |
| `MENU_H` | 22 | Menu bar: File, Edit, View, Project, Help |
| `TAB_H` | 24 | Tab strip: one picture per tab (`TAB_ICONS`) plus a default `Run  F5` button at the right; a tab whose document is unsaved wears `dirty-sym`, and on a narrow window the pictures drop out before the last tab does |
| `STATUS_H` | 22 | Status bar: project, tab name, status text, fps |
| `TREE_W` | 232 | Left dock: scene tree over the Project View |
| `INSPECT_W` | 260 | Right dock: the Inspector (toggleable) |
| `OUT_H` | 132 | Output log height, clamped to `70 … work area / 3` |

The window opens at 1280x820 with `pygame.RESIZABLE`, `vsync` when
`runtime.vsync` allows it, and `editor/appUI/icon.png` as the taskbar icon.
Drag the caption to move, drag an edge to resize, `F11` to maximize - all
through `engine.winchrome.WindowChrome`.

Paint order per frame: caption, menubar, tabstrip, docks, work area,
inspector, output, status, overlays (open menu, dialog, notice, hover tip).

### Menu bar

| Menu | Item | Action |
| --- | --- | --- |
| File | New Project... / Open Project... / Open Folder... | prompt for a name or path |
| | Project Manager, Save, `Run Game  F5`, Exit | |
| Edit | Undo `Ctrl+Z`, Redo `Ctrl+Y`, Cut, Copy, Paste | applied to the active tab only |
| | Settings... `Ctrl+,` | |
| View | one entry per tab, `Document Tab  Ctrl+D`, `Blocks Tab  Shift+F7`, `Build Tab  Ctrl+B` | |
| | Toggle Theme `Ctrl+T`, Toggle Output, Toggle Inspector | |
| | Reload Project, Maximize `F11` | |
| Project | Play Scene, Reload Scene, Build Game... | preview / build shortcuts |
| | New 3D Scene, New 2D Scene, New UI Scene | script in `scripts/scenes/` plus a `.scene` |
| | New 3D Object, New 2D Object, New UI Object, New Player 3D, New Player 2D, New Camera 3D, New Camera 2D, New Screen 3D, New Screen 2D | script in `scripts/objects/` plus an `.obj3d` / `.obj2d` |
| | New Model, New 2D Model, New Script | `models/*.model3d`, `models/*.model2d`, `scripts/*.py` |
| Help | Keyboard Shortcuts, About | the `About` notice shows `appUI/fligma-img.png` |

`Edit` entries are routed by tab: Blocks answers undo/redo, Code answers
cut/copy/paste/undo/redo, every other tab ignores them.

A command whose action appears in `app.ACTION_ICONS` gets its picture drawn
in the 18 px gutter `xp.menu_items` already leaves at the start of every row,
so rows with and without art still line up.

The bar reads the pointer when it draws (`widgets.mouse_pos()`), not from the
last motion event, so it answers the way a menu should: a label lights as the
cursor crosses it and presses in while the button is held over it, and keeps a
short `menu_flash` after a choice lands. The dropdown of the open label is
drawn from the same reading - its rows hover under the pointer and press in
while it is held - and releasing outside the row the press started on cancels
rather than firing something else.

Hover is settled for the whole editor in one place. A viewport that grabs the
mouse leaves the system cursor parked at its own centre, and every widget's
`get_pos()` read would then light a button the user is nowhere near, so
`widgets.park_pointer()` - answered each frame from `Editor.draw()` on
`preview.focus_mode` or a hidden cursor - returns an off-screen point for just
as long as the pointer is held and hands the real getter back when it is not.

### Keyboard shortcuts

| Key | Effect | Key | Effect |
| --- | --- | --- | --- |
| `F5` | run the game in a new process | `Ctrl+S` | save the active file |
| `F6` | Scene tab | `Ctrl+O` | project manager |
| `F7` | Code tab | `Ctrl+R` | reload project files |
| `Shift+F7` | Blocks tab | `Ctrl+T` | dark / light theme |
| `F8` | Model tab | `Ctrl+B` | Build tab |
| `F9` | Assets tab | `Ctrl+,` | Settings tab |
| `F10` | Audio tab | `Ctrl+N` | new scene |
| `F12` | Docs tab | `Ctrl+Shift+N` | new project |
| `F11` | maximize | `Ctrl+D` | Document tab |
| `Esc` | close a dialog / notice | | |

Shortcuts are only offered to `Editor._shortcuts` when the active tab did not
consume the key, so a tab owns its own bindings first.
`Help > Keyboard Shortcuts` repeats the list plus the per-tab hints.

## The tabs

| Tab | Module | Class | Works on |
| --- | --- | --- | --- |
| Scene | `editor.preview` | `Preview` | one scene of the project, live |
| Document | `editor.doctab` | `DocTab` | the open `.scene` / `.obj3d` / `.obj2d` files as a form |
| Code | `editor.codeeditor` | `CodeEditor` | the current `.py` as text |
| Blocks | `editor.blocktab` | `BlockTab` | the same `.py` as blocks |
| Model | `editor.modeleditor` | `ModelEditor` | one `.model3d` or `.map3d` file (a legacy `.model` opens here too) |
| Assets | `editor.assets` | `AssetBrowser` | the project folder as cards |
| Audio | `editor.mediaplayer` | `MediaPlayer` | the `audio/` folder |
| Build | `editor.buildtab` | `BuildTab` | `engine.build.BuildConfig` |
| Docs | `editor.docstab` | `DocsTab` | `engine.docs` - guides and API |
| Settings | `editor.settingstab` | `SettingsTab` | `engine.config` schema |

Switching tabs is not free of side effects - `set_tab` cleans up after the one
you leave:

| Leaving | Does |
| --- | --- |
| Code (dirty) | `flush_code()` - saves when `editor.autosave`, otherwise parks the buffer |
| Document (dirty, `editor.autosave`) | `save_all()` - writes every open document |
| Model (dirty) | `autosave()` |
| Scene | `preview.blur()` - lets go of held keys as releases and drops the look drag |
| Audio | `media.pause()` |
| Build | `build.config.store()` |
| Entering Blocks | `blocks.sync()` - shows whatever file the editor owns |

## Left dock: the two trees

`Editor.refresh_tree()` rebuilds both lists from the `Project` object.

| Tree | Rows |
| --- | --- |
| Scene tree | project root, then one row per `scene_names()` (the start scene tagged `(start)`); opening a scene reveals the nodes its document places, and beneath an instance the children that source document owns |
| Project View | root, the manifest and the two sidecars if present, then the folders `scenes, objects, shaders, scripts, models, maps, textures, audio` with their files; a scene or object document row folds into its own tree (a scene's `objects`, an object's `nodes`), and under `scripts` are the `scripts/scenes`, `scripts/objects` and `scripts/shaders` branches - where the code behind the documents actually lives |

`scenes/`, `objects/` and `shaders/` hold documents only, so a `.py` sitting in
either of the first two wears the warning symbol instead of a plain file icon:
the loader ignores it, and the real script belongs one level down in `scripts/`.

Clicking a folder row folds it. Clicking a scene row arms the preview when it
is stopped and switches the scene at once when it is running. Clicking a node
row selects that node in the Scene tab (and clicking a node under an object
document opens that document in the Document tab), so the two trees and the
Scene shelf all show and pick one structure. Clicking a file row calls
`open_file`. Rows are 19 px (`widgets.TreeView.ROW_H`), scrolled by wheel two
rows per notch.

Right-clicking a document row in either tree puts up a two-row menu - `Edit
as Document` (the Document tab) and `View raw JSON` (the same file as text in
the Code tab). Any other right-click dismisses the menu.

A `.py` row earns its icon from the first engine class the file defines:

| Base class | Icon | Base class | Icon |
| --- | --- | --- | --- |
| `Scene3D` | `file-scene-3d` | `Object3D` | `file-object-3d` |
| `Scene2D` | `file-scene-2d` | `Object2D` | `file-object-2d` |
| `SceneUI` | `file-scene-ui` | `UIObject` | `file-object-ui` |
| `Player3D` | `file-object-player3d` | `Player2D` | `file-object-player2d` |
| *(no engine class)* | `file-code-sym` | other suffixes | `widgets.FILE_ICONS` |

A document row is iconed by `doc_icon()`: a `.scene` by the `kind` its
JSON states, an object document by its `type` - with the extension as the
fallback, because `.obj3d` and `.obj2d` already say which world the thing
is in before anything opens it.

## Right dock: the Inspector, and the log

The Inspector is a column of `label / value` rows: the selected asset (name,
relative path, thumbnail, `assets.describe()` rows) followed by the active
tab's own `info()` rows, then a fixed project block - Project, Folder, Start,
Scale, Scenes, Objects, Models, Textures, Audio.

| Log kind | Colour constant | Marked with an icon |
| --- | --- | --- |
| `info` | `xp.LOG_INFO` | - |
| `ok` | `xp.LOG_OK` | - |
| `warn` | `xp.LOG_WARN` | `warning-sym` |
| `error` | `xp.LOG_ERROR` | `error-sym` |
| `muted` | `xp.LOG_MUTED` | - |
| `fatal` | *(falls back to `LOG_INFO`)* | `fatal-sym` |

`widgets.OutputLog` stamps each line `[HH:MM:SS]`, keeps 400 lines, splits
multi-line messages, and shows `Copy` and `Clear` buttons in the panel header.
`text()` returns the bare lines with their stamps taken off (what `Copy` hands
the clipboard through `widgets.copy_to_clipboard`, then logs `copied N line(s)`),
and `count` reports how many lines are held.

## Opening a file

`Editor.open_file(path)` routes by suffix, and saves whatever it is
displacing first.

| Suffix | Result |
| --- | --- |
| `.py` | Code tab, unless `editor.open_as` asks for Blocks; an unsaved buffer is parked, not lost |
| `.model3d`, `.model`, `.map3d` | Model tab, Edit / Texture modes - a map is the same schema in `maps/`, so it opens identically |
| `.model2d` | Model tab, 2D rig mode - parts, transforms, uv, parents and tracks edited in a flat viewport |
| `.scene`, `.obj3d`, `.obj2d`, `.object` | Document tab, one small tab per open file; with no project loaded it falls back to the Code tab, and right-clicking the row there offers `View raw` |
| `.wav` `.ogg` `.mp3` `.flac` | Audio tab, loaded into the player |
| `.png` `.jpg` `.jpeg` | Assets tab, selected |
| `project.flig`, `input.map.json`, `assets.json` | Assets tab, selected |
| anything else | logged as "open it with an external program" |

Every create action goes through one prompt dialog
(`widgets.PromptDialog`, 430 px wide):

| Action | Title | Default | Writes |
| --- | --- | --- | --- |
| `new_project` | New Project | `my_game` | `Project.create(projects/<stem>, template=...)` - name plus a template choice (Game 3D / Game 2D / Menu) - then opens it |
| `open_folder` | Open Project | *(empty)* | opens a folder holding `project.flig`; relative names resolve in `projects/` |
| `new_scene` | New 3D Scene | `scene1` | `scripts/scenes/<stem>.py` from the preset template, plus an empty `scenes/<stem>.scene` pointing at it |
| `new_scene_2d` | New 2D Scene | `scene2d` | the same pair, from the 2D preset |
| `new_scene_ui` | New UI Scene | `menu` | the same pair, from the UI preset |
| `new_object` | New 3D Object | `prop` | `scripts/objects/<stem>.py` plus `objects/<stem>.obj3d` |
| `new_object_2d` | New 2D Object | `sprite` | the same pair, with a `.obj2d` |
| `new_ui_object` | New UI Object | `button` | the same pair |
| `new_player_3d` | New Player 3D | `player` | the same pair, with a `.obj3d` |
| `new_player_2d` | New Player 2D | `player2d` | the same pair, with a `.obj2d` |
| `new_camera_3d` | New Camera 3D | `camera` | the same pair |
| `new_camera_2d` | New Camera 2D | `camera2d` | the same pair |
| `new_screen_3d` | New Screen 3D | `screen` | the same pair |
| `new_screen_2d` | New Screen 2D | `screen2d` | the same pair |
| `new_model` | New Model | `prop` | `models/<stem>.model3d` from a box primitive, opened in the Model tab |
| `new_model_2d` | New 2D Model | `sprite` | `models/<stem>.model2d` |
| `new_script` | New Script | `helpers` | `scripts/<stem>.py` with a `clamp()` helper |
| `new_shader` | New Shader | `shader1` | a `shaders/<stem>.shader` document plus `scripts/shaders/<stem>.py`, chosen from the stock templates |

Names are cleaned by `clean_stem()`: anything that is not a letter, digit,
`_` or `-` becomes `_`. An existing file is refused with a warning rather than
overwritten.

The scene and object rows are driven by two tables in the loader,
`SCENE_PRESETS` and `OBJECT_PRESETS`, whose entries are `(document kind,
template, default stem, title, hint)`: one entry there gives the menu, the
prompt and the document extension one consistent answer - `save_object_doc`
writes the `.obj3d` / `.obj2d` the preset's type asks for. `_new_scene()`
writes the script and `Project.save_scene_doc()`; `_new_object()` writes
the script, `Project.save_object_doc()` and then `reload_objects()`, so the
next spawn picks the new class up. A new screen is seeded with
`"showing": project.start`, so it shows something the first time it is
placed. Opening a project also renames any legacy documents on disk:
`Project.upgrade_documents()` rewrites `.model` as `.model3d` and `.object`
as `.obj3d` / `.obj2d`, and keeps the list of touched paths as
`project.migrated`.

## Saving and hot reload

`Ctrl+S` / `File > Save` saves only the active tab: Code, Blocks, Settings
(`commit()`), Model, Build (option store), Document (`doctab.save()`) - any
other tab saves the manifest. A document's first save is deliberate - edits
live in memory until `Save` or the button - but under `editor.autosave`,
leaving the tab writes every dirty document (`save_all()`), and quitting
asks about unsaved documents.

| Mechanism | Trigger | Effect |
| --- | --- | --- |
| `_maybe_hot_reload(path)` | a save, when `editor.hot_reload_save` | reloads the preview when the saved file sits in `project.WATCHED` (`scenes/`, `objects/`, `scripts/`, `shaders/`) |
| `_watch_tick()` | every 2.0 s, when `editor.hot_reload_watch` | compares `project.snapshot()` (mtime + size) and reloads on any difference, including files written by another program |
| `preview.reload()` | the above, `R`, `Project > Reload Scene` | `project.reload_scripts()` (a real `sys.modules` sweep) then rebuilds the scene |
| `reload_project()` | `Ctrl+R` | reloads models, re-registers textures, reopens the model, refreshes the tree |

A reload always rebuilds the scene from the top - no live state is carried
across a file write. Nothing outside the watched folders disturbs the preview,
so saving a texture or a manifest stays quiet. Saving a document whose scene
the preview is showing queues a rebuild the same way: `doctab.save()` sets
`preview.pending`, and `_maybe_hot_reload` fires when
`editor.hot_reload_save` is on.

## Running the game

`F5` / `Run  F5` starts a second process, so the editor never shares a GL
context with the game:

```python
cmd = [sys.executable, "-m", "emoeng", "run", str(self.project.path)]
env["PYTHONPATH"] = str(repo_parent) + os.pathsep + env.get("PYTHONPATH", "")
self.process = subprocess.Popen(cmd, cwd=str(repo_parent), env=env)
```

Dirty code is saved and the model autosaved first. Only one game process may
run at a time; `_poll_process` logs `game exited (code N)` when it ends.

`ProjectManager > Create Shortcut` writes a launcher to the user's Desktop
that runs `<exe> --run <project>`, or `python -m emoeng --run <project>` from
source:

| Platform | File | Made by |
| --- | --- | --- |
| Windows | `<name>.lnk` | PowerShell one-liner using `WScript.Shell` |
| Linux | `<name>.desktop` on the Desktop *and* in `~/.local/share/applications` | written directly, `0o755` |
| macOS | `<name>.command` | a two-line `/bin/sh` script, `0o755` |

## Project manager

`python -m emoeng` with no path opens `editor.projectmanager.ProjectManager`
in place of the editor: the same chrome, a list of projects down the left and
a detail panel on the right. It scans `paths.projects_dir()` for folders that
hold a `project.flig`.

| Row / panel | Content |
| --- | --- |
| List row (58 px) | the project's `icon.png` when one is set, otherwise a coloured badge of the folder's first two letters in capitals; then the title, `N scenes \| N models \| N textures`, and the start scene at the right - `bad manifest` in `xp.CLOSE_BTN_EDGE` when the manifest will not parse |
| Detail panel | title, full path, five count boxes (Scenes / Scripts / Models / Textures / Audio), then Start scene, Window, Render scale, Post FX, Seed, Version, Manifest (format), Extras (sidecars), Updated |
| Ordering | most-recently-opened first, then alphabetical, capped by `editor.recent_limit` |
| Search field | matches title, folder name or full path, case-insensitively |

| Input | Effect |
| --- | --- |
| `Enter` / double-click (0.42 s) | open the selected project |
| `Up` / `Down` | move the selection, wrapping |
| `F5` | rescan the projects folder |
| `Ctrl+N` | new-project prompt |
| Wheel | two rows per notch, inside the list |
| `Esc` | clear the search, or quit when it is already empty |

Footer buttons, left to right: `New Project`, `Open Folder...`, `Refresh`,
`Rename`, `Set Icon`, `Create Shortcut`, then `Quit` and `Open Project` at
the right. `New Project`, `Open Folder...` and `Refresh` work with nothing
selected; the rest need a row. The six carry `new-folder-sym`,
`open-folder-sym`, `reload-sym`, `file-text-sym`, `file-image-sym` and
`file-exec-sym`.

`Rename` asks for a new folder name, renames the folder holding
`project.flig`, restates the `name` the manifest carries and moves the
project in the recent list, so the title and the row follow at once. The
project the editor has open is refused, and so is a name already taken in
the projects folder.

`Set Icon` takes the path to a PNG or JPG, fits it into a 64x64
transparent sheet and saves it beside the manifest as `icon.png`. That one
file is the row badge, the game's window icon and the compiled exe icon;
until it exists, the folder's first two letters stand in. An empty answer
deletes it and the initials come back.

`Open Folder...` goes through the same prompt dialog as
`File > Open Project`, so a folder without a manifest is refused with a
warning instead of opening.

## Scene tab - the preview, in Game and Edit mode

The preview runs real scene code against a duck-typed stand-in for the game,
`_PreviewGame(CameraHost)`, so a scene does not know it is being previewed.

| It provides | Notes |
| --- | --- |
| `project`, `audio`, `input`, `fonts`, `eye` | audio is the editor's own bank, so preview sound obeys the Settings volumes |
| `renderer` | a dedicated `Renderer`, resized with the panel |
| `screen` | `_FakeSurface` (default 640x360) - the size is refreshed from the inner rect each frame |
| `save` | `SaveStore(project, slot="preview")`, so a preview save cannot spoil a real slot |
| `set_player`, `load_scene`, `play_scene`, `push_scene`, `pop_scene`, `restart_scene`, `quit` | scene-changing calls work; fades are skipped and the push stack is the preview's own |

The 26 px strip starts with the mode pair - `Game` and `Edit` - then the
transport, `Reload`, `Focus`, `scene: <name>`, the fps readout, the HUD and
sound buttons and the volume slider. Pressed states show the live mode,
the playback state, and whether the viewport has the pointer. `info()`
adds `Mode`, `Tool`, `Lighting`, `Focus`, `Selected` and `State` to the
Inspector.

### Game mode

The default: the scene is stepped, played and piloted exactly as in the game.

| Control | Behaviour |
| --- | --- |
| `step-backward-sym`, `step-forward-sym`, Play, Pause, Stop, `Reload` + `reload-sym` | transport strip, `VIDEO_H` 26 px |
| Right-drag | look - fed to `player.nudge(dx, dy)` + `publish_camera()` when the scene has a Player, otherwise `camera.aim()` |
| WASD / arrows, Shift, Space, Q | move, through `input.move_axis()` and `scene.move_speed` / `camera_rig` / `fly` / `walk` / `ground_height` / `world_radius` |
| `R` | rebuild the scene |
| HUD button | `visable-sym` / `hidden-sym` - turns `scene.overlay(frame)` on and off |
| Mute + slider | `sound-on-sym` / `sound-off-sym`, `xp.slider_frac` into `audio.set_master` |
| fps readout | smoothed, shown at the right of the strip |

Only `kind == "3d"` scenes are piloted by the game camera; 2D and UI scenes
render through their own `Camera2D`, and mouse positions are rebased onto the
inner rect. The internal resolution follows `project.render_scale`, clamped to
0.25-1.0, so the scaled-pixel look carries over. The frame's chain comes from
`scene.post`, or from the manifest when a scene declares none, and its names are
resolved to `screen` shaders armed on the preview renderer. Choosing a scene in
the tree `arm()`s it; nothing builds until
Play is pressed. A scene that raises during `_build` shows the last fourteen
traceback lines in the viewport instead of geometry.

### Focus - handing the viewport the pointer

The `Focus` button sits on the transport strip, so it works in Game and
Edit alike. It gives the viewport the pointer and the keyboard the way a
built game grabs the mouse:

| What happens | |
| --- | --- |
| Cursor | hidden, and `input.grab_mouse(True)` keeps it inside the window, so a look never stalls at a screen edge |
| Mouse | every move arrives as relative motion - the look, and in Edit the gizmo drags, keep working without a visible cursor |
| Keyboard | goes to the scene; `Ctrl` chords are swallowed on the press, so the editor's shortcuts stay shut while the capture lasts - but their release still reaches the scene, or the bare key underneath would stay held |
| `Esc` | the way out: releases the grab and hands pointer and keys back to the editor |
| Everything else | no dock, tab, menu or tree answers a click while captured - `Editor.handle_event` routes every event straight to the preview |

Capture needs a running 3D scene: on a flat scene or a stopped preview the
button logs `focus needs a running 3D scene` and grabs nothing. Switching
tabs or otherwise losing the preview releases it too (`blur()` calls
`release()`), so the editor can never leave a hidden cursor behind. While
focus is held the corner hint reads `mouse turns the view  keys drive it
Esc releases`, and the Inspector's `Focus` row says `viewport`.

Nothing is ever left held. A key released after the pointer has moved off the
viewport, after the cursor was hidden, or while a notice or dialog is up still
reaches the input map - a release is never the editor's to keep.
`preview.blur()` lets go with `input.release_all()`, which reports every held
action as released rather than forgetting it in silence, so a scene waiting for
a release and the edit camera both stop. Losing the window itself does the
same: SDL sends no key-up for a key held when focus goes elsewhere, so
`Editor.handle_event` answers `WINDOWFOCUSLOST` by blurring the preview and
dropping the Model tab's drag.

### Edit mode

`Edit` builds the scene but never steps it: `update()` runs `_edit_update()`
and returns, so no script, timer, player or screen ticks while you are placing
things. What you see is the scene at rest, and the mode starts the preview for
you if Play has not been pressed yet. The layout follows the Model tab: a tools
strip under the transport strip and a shelf down the right side - drawn only
when the viewport still has 260 px left, otherwise the picture keeps the width.

The strip, left to right:

| Button | Effect | Key |
| --- | --- | --- |
| `Select` `Move` `Rotate` `Scale` | arm a transform; `Move` is the default | `1` `2` `3` `4` |
| `Global` / `Local` | the frame the move arms are drawn in - the world's axes, or the body's own, turned by its `yaw` about Y; 3D only | |
| `Snap` | round what a gesture produces | toolbar only |
| `Grid` | draw the placement grid over the picture | `G` |
| `Shapes` | draw every collider as a wireframe over the picture | `H` |
| `Lighting` | off (the default) shows the scene at full bright; on hands the scene its own lights back | |
| `Frame` | frame the selection, keeping the camera's angle | `F` |
| `Revert` | drop the selection's own entry from the document and rebuild | |

The right end of the strip spells out the rest: `1-4 tools  F frame  G grid
H shapes  RMB look  WASD fly`, or `RMB pan  wheel zoom` on a flat
scene. `Snap` has no key: `S` flies the camera backwards, like every other
movement key.

A snap step is 0.25 m in 3D, 16 world pixels on a flat scene and 15° for a
turn. The grid is a line every 2 m on the floor, or a 128 px sheet behind a
flat scene.

Edit lights nothing. When a scene builds in Edit, `_apply_view()` files
away everything the renderer reads about lighting - `lights`, `sun`,
`ambient`, `ambient2d`, the sun's colour and direction, both fog distances -
and then empties it: no lights, ambient `(1, 1, 1)`, fog pushed past the
world. Every surface draws at its own colour at full brightness, so a room
built for two torches is never a wall of black while you place things. The
`Lighting` switch hands the saved values back exactly as the script wrote
them, which is how the room reads in Game - just with nothing moving; the
status line and the corner hint say `full bright` or `lights on`, and a
rebuild re-applies whichever the switch asks for.

| Control | Behaviour |
| --- | --- |
| Right-drag (3D) | look; the fly camera starts from the angle the game was looking through |
| WASD / arrows + Shift | fly at 8 m/s, 24 m/s with Shift held; Space up, Q (or Ctrl) down |
| Right-drag (2D/UI) | pan the view; the wheel zooms it (`view.zoom_by`) |
| Left-click | pick - 3D by the nearest pivot within `PICK_PX`, flat by the object's own rect, topmost first |
| Left-click a handle | grab it: an arm with `Move`, the ring with `Rotate`, the grip with `Scale` |
| Left-drag a body | `Move` only: take whatever is under the pointer with you; 3D slides along the ground plane, Shift gives a plane facing the camera so up on screen is up in the world |
| Release | `write_placement()` records what the gesture did |
| `Esc` | close the Add list first; otherwise clear the selection - while `Focus` has the pointer, `Esc` releases the capture instead |
| `Del` / `Backspace` | remove the selected node the document placed, and the nodes hanging from it |
| `Ctrl`+anything | the editor's, not the scene's - `Ctrl+S` still saves |

The three gizmos sit on the selection and keep the same size on screen
(`HANDLE_PX` 62), so a handle is as easy to grab far away as near:

| Tool | What is drawn | What a drag does |
| --- | --- | --- |
| `Move` | one arm per axis, x red, y green, z blue | slides along that arm - the pointer is read where its ray passes closest to the axis line, so no handle collapses when the camera looks down it |
| `Rotate` | a ring round the pivot, projected in 3D, a circle on a flat scene | 3D turns `yaw` by 0.012 rad per pixel dragged sideways; 2D turns `rot` about the pivot |
| `Scale` | one grip, up and left of the pivot | 3D scales by `exp(pixels / 167)`; 2D resizes `size` instead |

The selection wears a yellow cross and a label naming its `doc_key` and its
coordinates - the same name the document is about to record. The corner hint
follows the armed tool: `drag to move`, `drag the ring to turn`,
`drag the grip to size`, or `click to pick` under `Select`.

Colliders own no geometry, so Edit draws them for you: every node filed in
`scene.colliders` appears as a wireframe, projected the same way as the
gizmo because the renderer has no line primitive. A box is its twelve
edges, a sphere rings on three planes, a capsule a ring at each end joined
by uprights, and a flat shape its rectangle. Solid shapes wear the
collider's blue and see-through triggers a warm orange; the picked node
draws at full strength and the rest at sixty percent. `Shapes` (or `H`)
hides the whole layer.

#### The shelf

`Scene` is a folder tree of the live nodes: one row each, indented by depth,
a parent straight before the nodes it owns - the order the scene already
builds them in, so one pass down `scene.objects` is the whole tree. A row
carries a fold triangle when it has children, the icon of its class
(`widgets.class_icon` reads the `NODE_TYPES` registry - a `CLASS_ART`
picture per engine class, the group's flat art by dimension otherwise -
so a `Model3D` node and a `.model3d` file read as one thing), and
only the last part of its document name - the indent says whose node it
is. Folds live in `preview.collapsed`, keyed by `doc_key`. A click selects,
a double click frames, the wheel over the list scrolls it, and a click on
the empty part of the list clears the selection.

The header carries an `Add` button. It opens Godot's `Create New Node`
dialog: a search line over grouped, iconed rows - every type this scene
can actually build (the half matching its kind, and only the classes its
own `object_base` accepts, so a UI scene is not handed a solid-world
shape), then the project's own object and scene files under
`Instantiate`. Typing filters, double-click or `Enter` chooses, and
choosing a type row calls `add_node()`. Right-clicking a row opens the
same dialog as `Add Child Node`, or takes the node out with `Delete
Node`:

| Question | Answer |
| --- | --- |
| Where does the node go? | Under the selected object's own entry - a `Collision3D` added while a crate is picked hangs from the crate, follows it, and the crate's script never hears about it |
| And when the selection was spawned by a script? | It has no entry to hang a node from, so the new one joins the scene's roots and the log says so |
| What is it named? | The next free `Label#index` at that level, counted with `scenedoc.key`, so a placed and a scripted node cannot come out with the same words |
| Where does it start? | On the parent's pivot - the world origin at the roots. The entry goes into the `.scene` document, the scene rebuilds, and the new node is selected |

`Del` / `Backspace` removes the selected placed node - and its whole
branch - from the document; a node a script spawned cannot be deleted this
way.

`Properties` describes the selection, headed with its `doc_key`. A value in a
sunken box can be typed into; the rest are read only:

| Row | Typed? | What it is |
| --- | --- | --- |
| `class` | no | the Python class |
| `script` | no | `scripts/objects/torch.py`, when the class came from one |
| `pos x/y/z` | yes | metres; a flat object shows `pos x/y` only |
| `yaw` / `rot` | yes | radians - a solid object's turn, or a flat one's |
| `scale` / `size w,h` | yes | one number for 3D, a width and a height on a flat scene |
| `model`, `texture` | yes | the file the node draws; a fresh `Model3D` gets an empty row to fill in, and a name with no file behind it is warned about but kept - the art may still be on its way from the Model editor |
| `colour` | no | what the object's `look` says |
| the node's knobs | yes | one row for every name in its `doc_knobs`: a `Collision3D` offers `shape`, `half x/y/z`, `solid`, `group`, `offset …`, a `Model3D` `tint`, `blend`, `stamp` and `opacity`. Every drawable node carries `opacity` - how solid it is, 0..1 - and a shape that draws nothing offers no row for it. A bool reads `true`/`false`, a tuple gets a row per part, and anything else takes the words the node stores it in |

Clicking a typed value opens a field: `Enter` or a click elsewhere commits,
`Esc` throws it away. The number is spelled the way the engine stores it, so
what is typed is exactly what the document will say; a commit writes the file
and queues a rebuild, and the next frame shows the result. A typed transform
goes through the node's `moved()` first, so its local offset from its parent
and its own children's places are worked out again before the file is
written - a tree never records a stale local position.

`write_placement()` edits `scenes/<scene>.scene`:

| The object | What is written |
| --- | --- |
| placed by the document (`placed_id`) | its own entry in the `objects` tree, at whatever depth it hangs, fields updated |
| spawned by the script (`doc_key`) | an `overrides` entry keyed `Walker#0` |

Only the transform, the look and the node's declared knobs are written -
`pos`, `yaw`, `scale`, `rot`, `size`, `model`, `texture`, `color`,
`showing`, `knobs` - so a document never becomes a second, stale copy of
what a script keeps for itself. A child records its `pos` relative to its
parent (`local_pos`) and is filed back under whoever holds it, so a move
in the tree is never counted twice on the next load.

A script is never rewritten, so it keeps naming the same objects every build.
The log says `placed Walker#0 in scenes/camp.scene` and the tree refreshes.
`Revert` goes the other way: it removes that entry and rebuilds, handing the
object back to its script. While dragging, an object moves as far as it can -
model objects, non-following lights and its own `_sync()` - and the rebuild
that follows puts the rest in place. Leaving Edit drops the selection, the
half-finished gesture and any half-typed value, then rebuilds from the
document, which is what makes placement survive a reload while gameplay state
does not. Because Edit steps nothing, a `Screen3D`/`Screen2D` would freeze
on the blank texture it was built with, so each build in Edit asks every
screen for one frame - `_warm_screens()` calls any object with a `warm()`
of its own, which is what lets you see what a panel shows while you place
it.

## Document tab

`editor.doctab.DocTab` - reached with `Ctrl+D` or `View > Document Tab` -
opens `.scene`, `.obj3d` and `.obj2d` files as a form instead of as text:
fields appear and vanish with the type you picked, so a level's objects,
collisions, lights and knobs can be set up without typing JSON. The Scene
tab's Edit mode places what the document already names; this tab is where
the names, the types and the knobs are written.

| Region | What it is |
| --- | --- |
| strip | one small tab per open document - click shows it, its close box drops it (the file is untouched; re-open from the tree any time); a dirty tab wears a `*` and boxes its close |
| toolbar | scene docs: `Scene v`, `+ Add Node`, `Duplicate`, `Remove`; every doc: `Revert`, `Save` (grey until something changed) |
| tree (scene docs) | the placed entries nested like the file, fold triangles and all; `(scene)` at the top edits the header; dragging a row onto another re-parents it, onto `(scene)` back to the roots |
| fields | the picked node's values, built for its type |

`+ Add Node` opens the same `Create New Node` dialog: the `NODE_TYPES`
registry grouped as Objects / Pictures / Physics / Players / Views /
Lights / Audio / Text / Utility, filtered by `3d` or `2d` family - so a
2D scene is never offered a `Collision3D` - with the project's own
object files under a final `Instantiate` heading. A new node takes the
next free path-name (`Collision3D#0`, a child `Collision3D#0/Model3D#0`)
and lands under the picked node. Right-clicking a tree row offers
Godot's `Add Child Node` / `Duplicate` / `Delete`.

`Remove` (or `Del`) takes the node and its branch out and prunes their
`overrides` too; `Duplicate` deep-copies the branch beside it under a new
name; a re-parent rewrites every path-name in the branch, so the tree and
the file always tell the same story.

The `Scene v` menu arms the scene in the Scene tab, previews it at once,
sets it as the start scene, or opens its raw JSON in the Code tab.

What the fields offer is the dynamic half, straight off `scenedoc` and the
node's own engine class - no per-type code in the tab:

| Picked | Rows |
| --- | --- |
| the scene | `kind` (a picker over `SCENE_KINDS`), `script`, `maps` (a multi-select over `project.map_names()`, stored as the list), and read-only counts of placed entries and overrides |
| a node | `type` (a picker over its family's createable types), `script`, `pos x/y/z` (`x/y` flat), `yaw`/`scale` or `rot`/`size w,h`, any `model` / `texture` / `color` / `showing` it carries, then one row per knob |
| an object document | the same rows for the one node the file is |

Knobs come from the class's `doc_knobs` plus its class attributes, so a
`Collision3D` offers `shape` (box / sphere / capsule), `half` as one typed
list, `solid`, `group`, `offset` and a `Light3D` offers `point` / `spot` /
`directional`; a `Map3D` offers the `map` stem it reads from `maps/`, its
`solid`, `group` and `tint`. A `maps` row writes the header list the scene
loader places before any object; leaving the last one out takes the key out
of the file entirely. A script node with no type falls back to whatever
knobs its file already carries, keeping each value's own kind. A bool row
flips on click, an enum row opens a list, everything else opens a field:
`Enter` or a click away commits, `Esc` throws it away, and a value that does
not parse logs a warning and keeps the old one.

Nothing is written per keystroke: edits live in memory until `Save` /
`Ctrl+S` hands the document to `project.save_*_doc`, so the file on disk
stays one a person could have written by hand - saving the scene the
preview is showing rebuilds it. `Revert` re-reads the file. The raw JSON
is never far: right-click a document row in either dock, or use `Scene >
View raw JSON`, and `Editor.open_raw` puts the file in the Code tab.

## Code tab

| Metric | Value |
| --- | --- |
| `CodeEditor.GUTTER` | 48 px |
| `CodeEditor.MINIMAP` | 68 px, shown when `editor.minimap` |
| Line height / char width | measured from `fonts["mono"]` (consolas) |
| Double-click window | 0.35 s to select a word |
| Wheel | scrolls the pane the pointer is over |

Highlighting is a lightweight scanner (`codeeditor.scan`), not a parser. It
emits per-line spans, mapped to theme colours:

| Token kind | Colour constant | Matched by |
| --- | --- | --- |
| `kw` | `xp.SYN_KW` | `KEYWORDS`, including `match` and `case` |
| `builtin` | `xp.SYN_BUILTIN` | `BUILTINS` |
| `string` | `xp.SYN_STR` | `'...'`, `"..."`, triple-quoted across lines |
| `comment` | `xp.SYN_COMMENT` | `#` to end of line |
| `number` | `xp.SYN_NUMBER` | digit or `.digit` runs |
| `def` | `xp.SYN_DEF` | the name right after `def` / `class` |
| `self` | `xp.SYN_SELF` | the literal word |
| `decorator` | `xp.SYN_DECORATOR` | `@` at column 0 |
| `op` | `xp.SYN_OP` | runs of `=+-*/%<>!&|^~:` |
| *(anything else)* | `xp.CODE_TEXT` | |

| Key | Effect |
| --- | --- |
| Tab / Shift+Tab | indent / outdent the selection |
| Enter | newline, copying the previous line's leading whitespace |
| Arrows, Ctrl+arrows | move; word-wise with Ctrl; shift extends the selection |
| Home / End, Ctrl+Home / End | line ends, document ends |
| PageUp / PageDown | a screenful |
| Ctrl+A / C / X / V / Z / Y | select all, copy, cut, paste, undo, redo |

Unsaved text is never thrown away: `park()` stores the buffer in
`code.parked[str(path)]`, and `open()` picks it back up. `Editor.flush_code()`
parks instead of writing when `editor.autosave` is off.

Hovering an engine call pops a tooltip: after `docs.hint_delay` seconds of
stillness the dotted identifier under the pointer is looked up in the API
index and its signature plus first doc paragraph are shown with
`xp.tooltip`. Any failure degrades to no hint - the editor cannot break on a
bad lookup.

## Blocks tab

Two views of one file: Code and Blocks edit the same Python, and
`editor.open_as` (`ask`, `text`, `blocks`) decides which one a `.py` opens in.
The model, the palette and the drag rules are documented in
[Blocks](blocks.md).

## Model tab

The tab has three modes, switched with the `Edit` / `Texture` / `UV Paint`
buttons in the `Mode` band at the start of the toolbar. Each mode
lays out its own bands, so the tools always visible are the ones that mode
uses. A `.model2d` opened here is none of these modes: a flat rig has one mode
of its own, described under [2D rig mode](#2d-rig-mode) below. A `.map3d`
opens in all three 3D modes exactly like a `.model3d`, because it *is* one -
same schema,
other folder - with its parts listed on the
[objects rail](#the-objects-rail).

### Edit mode

The toolbar is captioned **bands** laid out left to right (`widgets.bands`),
which wrap their own buttons onto further lines when the tab is too narrow for
one band, and scroll under the wheel once the stack passes 45% of the tab's
height - a thumb on the strip's edge says there is more of it, and nothing is
ever cut off past the bar. One row sits under the bands: `Name`, the name
field, the `<` / sheet / `>` cycler, the colour chip and `Colour`, then the
live hint.

| Band | Buttons |
| --- | --- |
| `Mode` | `Edit` `Texture` `UV Paint` |
| `Shape` | `Object` `Vertex` `Face` (mode, default Vertex) |
| `New` | `New`, `New Map` |
| `Add` | `Box` `Wedge` `Cyl` `Cone` `Plane` `Sphere` |
| `Edit` | `Delete` `Extrude` `Face` `Flip` `Weld` |
| `Move` | `Snap`, `X` `Y` `Z` `Free`; Object mode also has numeric X/Y/Z position fields |
| `File` | `Save` `Reload`, the model/map flip, `Undo` `Redo` |
| `View` | `Wire` `Frame` `AutoUV` |

| Input | Effect | Input | Effect |
| --- | --- | --- | --- |
| Left-drag a vertex/face | select and move | `1` / `2` / `3` | Object / Vertex / Face mode |
| Shift-click a vertex/face | add it to, or drop it from, the set | `X` / `Y` / `Z` | lock movement to an axis; press again for free |
| Left-drag an object surface | select and move only the hit object (or the selected set with Shift) | `E`, `F`, `Del` | extrude, make face, delete |
| Left-drag a gizmo arm | move the picked vertices or objects along that axis | numeric X/Y/Z fields | set the selected object's bounds-centre coordinate precisely |
| Middle / right drag | orbit / pan | `W`, `G`, `Home` | wireframe, snap, frame the model |
| Wheel | zoom | `C` | colour the picked faces (nothing picked = the whole model) |
| Left-drag empty space | orbit, and clear the pick | `Ctrl+Z/Y/S` | undo, redo, save |

A Shift pick grows the selection instead of replacing it, and the drag then
moves the union: every vertex of every picked face in Face mode, every picked
vertex in Vertex mode, every vertex of every picked object in Object mode.
That is what lets a whole wing of a map slide over without rearranging the
rest of it - the objects rail's Shift-click and this key are the same idea
one level up.

#### The vertex gizmo

With vertices picked in Vertex mode, or objects picked in Object mode, their
centre is projected through
`OrbitCamera.project` and drawn as three arms of a fixed screen length
(`GIZ_PX` 54), x red, y green, z blue - the Scene tab's `Move` handle come
to the model. Pressing within `GRAB_PX` (8) of an arm sets the axis lock and
drags along that world axis using the same ray-closest-to-axis maths the
scene editor uses. In Object mode the numeric fields move the selected
object(s) so their combined bounds centre lands at the entered coordinate;
these values are exact even when drag snapping is enabled. `Free` clears the
axis lock.

### The objects rail

A document with an `objects` list - see
[Models and Meshes](models-and-meshes.md) - puts a second shelf on the right
in Edit mode (`OBJ_W` 186, only when a viewport still fits beside it, so a
narrow window simply loses the rail). The rail is also shown on an unpartitioned
model, where its `Objects 0` header and `+ Obj` button are the entry point to
object editing. Each row (`OBJ_ROW` 22 px, wheel-scrolled) has a colour dot -
amber painted, green baked, grey plain - its name, and how many faces it
claims.

| Control | Effect |
| --- | --- |
| Click a row | pick that object: it becomes the target of Texture mode, `Colour` with nothing else picked, `AutoUV` and UV Paint, and an Object-mode drag moves only its vertices |
| Shift-click a row | add or drop that whole object on the object selection |
| Double-click a row | rename in place; `Enter` files it, `Esc` drops the edit, and a name another object holds is refused with a message rather than silently made unique |
| `+ Obj` | make the whole unpartitioned model the first object; with faces selected, carve them into a new named object; with no face selection on an already partitioned model, add a separate box object beside the model |
| `Merge` | fold the picked objects into the first-named one |

`Merge` is greyed until the pick earns it: at least two objects, and two of
their bounds meeting. Two parts nowhere near each other would merge into
nothing but a longer face list, so the button stays dead and lights up the
moment a Shift-click makes a touching pair. What the fold does - enclosed
faces dropped, the survivors welded, unreferenced vertices pruned - is
documented in [Models and Meshes](models-and-meshes.md).

`New Map` starts a map rather than a model: one `box` primitive sized 4 m,
filed as a single object named for the primitive. Nothing else differs -
carving it into floor, walls and roof is this rail's work, and the tab's
usual `Save` writes `maps/<stem>.map3d` through `Project.store_map` while it
holds a map, and `models/<stem>.model3d` through `store_model` otherwise. A
new project's `game3d` template also ships one starter, `maps/room.map3d`,
already carved into a `floor` and two walls.

The `File` band's third button names the way round the open document is about
to be filed - `To map` on a model, `To model` on a map - and pressing it
flips the document and moves its file, so no second copy is left in the other
folder. A model turned into map is carved into one object holding all its
faces, named after the model, since an object is what a lightmap, a hide and a
per-object sheet act on. Saving under a new name follows the same rule: the
file lands in the folder that matches the current kind.

A shape added with the `Add` band is placed beside the open model's bounds.
Each primitive brings its own per-metre unwrap, so nothing is re-projected
after it - see [Models and Meshes](models-and-meshes.md) for why a whole-model
`auto_uv()` pass over a shape that knows its own sheet is the stretch it shows.
On a map the new shape is carved into an object of its own, named after the
primitive and numbered when that name is taken, rather than bolted onto
whatever object sits first in the list.

### Texture mode

| Band | Buttons |
| --- | --- |
| `Mode` | `Edit` `Texture` `UV Paint` |
| `Paint` | `Paint` (armed), `All`, `Colour`, `Clear` |
| `File` | `Save` `Reload`, the model/map flip, `Undo` `Redo` |
| `View` | `Wire` `Frame` `AutoUV` |

The right-hand shelf (`PALETTE_W` 186) is two tabs under a `Sheets` /
`Settings` strip; `Sheets` lists every sheet the model can draw with: `white`,
then the ten built-ins from `proctex.BUILTIN`, then every image in the
project's `textures/` folder. Each row shows a thumbnail of the real bytes
(`_thumb`, cached per key and size) and the key a script would write. The wheel
over the shelf scrolls it; the wheel over the viewport still zooms.

| Control | Effect |
| --- | --- |
| Click a row | picks that sheet; `Paint` stays armed |
| Drag across the model | fills each face the pointer crosses in one undo step |
| `Paint` | arms the brush; off, a click only picks a face |
| `All` | every write lands on the whole model |
| `Apply all` (shelf footer) | paints the picked sheet over the model, dropping per-face tags |
| `Paint` (shelf footer) | back to face-by-face filling |
| `Colour` / `C` | a flat colour for the picked face, or the whole model |
| `Clear` | hands every face back to the model's own sheet |
| `T` | switch mode |

The brush target is the same triangle `Face` mode selects, so a click fills
one triangle, not a whole cube side. A sheet applied to "all" replaces
`model.texture` and clears every face tag: overwriting all has to mean every
face, or the old tags would keep drawing. Painting one face sets only that
face's tag. The face under the pointer is outlined in yellow while the brush
is armed and grey when it is not, so the viewport and the shelf agree about
what a click is about to do.

The object picked on the rail carries over from Edit mode, and a whole-target
write respects it: `Colour` with no face picked sets that object's own
`texture`, `AutoUV` reprojects only its faces, and a face tag still wins face
by face on any model. `All` is the override - with it on, a write means the
whole model exactly as before, so an objectless file is unaffected either way.

#### The shelf's Settings tab

The other half of the shelf holds the settings a painted model actually needs,
one row per value (`SHELF_ROW` 18 px, scrolled like the sheet list):

| Block | Row | Writes |
| --- | --- | --- |
| `image` | `filter` (`linear` / `nearest`), `mips` (`on` / `off`), `wrap` (`repeat` / `clamp`) | the picked sheet's entry in `assets.json` `textures.sheets` |
| `image` | `tile m` - metres one repeat of the sheet covers, `picture` for 0 | the same entry's `tile` |
| `generator` | one row per knob of the picked built-in (`size`, `cells`, `seed`, `octaves`, …) | the same entry, under the knob's own name |
| `tiling` | `scale x`, `scale y`, `offset x`, `offset y`, `rot deg` | the model's `uv` block, saved with the `.model3d` |

An enum row opens a popup over its choices and commits on the pick; a number
row opens a field the same way the flat part panel does, `Enter` or a click
away committing and `Esc` throwing the edit away.

Both halves land live, which is the point of putting them next to the brush:

- `filter`, `mips`, `wrap` and `tile` go through `Project.set_texture_settings()`,
  then `refresh_textures()` clears the viewport's sheet cache and re-uploads
  every file, so the preview shows the sampler state the file just asked for
  rather than the one it started with. A built-in sheet has no file, but it is
  not read-only either: the block starts from the engine's own values
  (`proctex.options`), and a turn is filed under the same `textures.sheets`
  key with `keep_all=True`, so `builtin_sheet(name, project)` rebuilds the
  picture from those numbers on the next upload - `_reload_sheet()` does that
  for the shelf and the viewport at once, and drops the sheet's cached
  thumbnail. A colour the picker painted is a sheet with no settings to keep.
- the `generator` block only appears for a built-in, since a PNG has no knobs
  to turn. It lists whatever `proctex.knobs(name)` returns - the factory's own
  defaults with this table's values over them - so `noise` offers `cells`,
  `octaves`, `gain`, `contrast` and `seed`, and a `bark` offers its `size` and
  `seed`. A number is typed and an on/off knob is picked from two words; either
  way the value is filed, not just shown, so the same sheet reads the same in
  the running game.
- `scale`, `offset` and `rot` are the model's own, so they push an undo step,
  set `dirty` and rebuild the mesh; the autosave on leaving the tab writes them
  into the file. Rotation is typed in degrees and stored in radians, the
  spelling the engine reads. A `scale` under `0.01` is refused rather than
  collapsing the picture to a line.

Give a sheet a `tile m` and the `tiling` block stops meaning anything to it -
the world now decides where the picture lands - so the block says
`overridden by this sheet's tile size` above those rows. Set it back to 0
(`picture`) and the model's own `uv` is in charge again.

The split is the same one the engine makes: how a sheet is *sampled* belongs to
the image, since one GL texture is shared by every model naming it, and where
it *lands* belongs to the model unless the sheet was given a world size, which
belongs to the wall wearing it. See
[Models and Meshes](models-and-meshes.md) for the `uv` block and
[Project Folder](project-folder.md) for `assets.json`.

The geometry itself lives in `engine.model.Model`; the tab only projects it
with `OrbitCamera.project` for picking, previews it on its own `Renderer`
under the fixed `_Studio` render settings, and writes it back through
`Project.store_model` - or `Project.store_map` while the document is a map.
`add_primitive` sets a new shape down beside the existing bounds and leaves
its own per-metre unwrap alone; `AutoUV` is the explicit fallback, and reprojects
the picked faces, or the whole model with none picked. Snapping moves to a
0.25 grid. Overlays (grid, wireframe, vertex dots) are drawn with pygame on top
of the returned frame, so `Renderer` carries no editor-only code.

### Painting a surface a colour

The `Colour` button (or `C`, or the chip itself) opens a `ColorDialog` and
writes its answer - always spelled `#rrggbb` - as the surface of the current
target: `apply_color()` tags the picked faces in Face mode, every face on the
selected vertices in Vertex mode, the picked face in Texture mode, and the
whole model when nothing is picked or `All` is on. The answer is a colour, not
a file: `renderer.color_texture()` paints a solid sheet on the spot, so a
tinted face previews immediately and needs no PNG, and the same hex stored in
`texture` / `tex` works in the running game. Emptying the field (or `None`)
hands the faces back to the model default. See
[Lighting](lighting.md) for colour spellings everywhere the engine takes one.

### UV Paint mode

`UV Paint` combines the atlas editor and live 3D surface painting in one view.
The tab holds a `UVPaint` session in `editor/uvpaint.py`. On the first visit
the session calls `unwrap.split_and_unwrap(model)` to create `uv2`; later
visits reuse the existing layout.

With an object picked on the rail the session targets that object instead of
the file: `split_and_unwrap(model, faces=obj["faces"])` unfolds only those
faces, onto their own full 0..1 square, and splits their vertices off from
the rest - so every part gets a sheet of its own and painting one never
disturbs another's patches. The `‹` / `›` target controls switch between
objects without leaving paint mode. The `uv2` wireframe drawn over the canvas
is that object's triangles alone, since the others' layouts would only get in
the way, and which regime `Save` uses follows the same pick.

The layout is a large, auto-fitted UV canvas on the left, a paintable 3D
preview at the top right, and a clickable layer stack below it. The `Fit`
button restores the full atlas view; wheel zooms over the canvas and
middle/right-drag pans it. Left-drag either on the UV canvas or on the 3D
preview paints the same active layer and updates the other view immediately.
Brush and Erase work on the 3D preview; shape, fill and eyedropper tools are
used on the UV canvas.
Middle/right-drag over the 3D preview orbits the model; its wheel zooms, and
Shift-wheel adjusts brush size in either view.

| Element | Effect |
| --- | --- |
| `Brush` `Erase` `Fill` `Line` `Rect` `Oval` `Pick` | tools, also bound to `B` `E` `F` `L` `R` `O` `K` |
| `-` `Npx` `+` / Shift-wheel | brush diameter, in atlas pixels |
| `Fit` | fit the whole atlas in the available canvas |
| `‹` / object name / `›` | switch the active object atlas while staying in UV Paint |
| `Undo` `Redo` | undo or redo strokes, including when another layer is active |
| Click a layer row / eye | select a layer or show/hide it |
| `+ layer` `- layer` | add a blank layer, or drop the active one |
| `Paste` | clipboard image as a new layer |
| `Sheet` | add a project texture as a new layer |
| eight colour chips | the palette; `Pick` samples the canvas |

Layers are `LayerStack` entries - an RGBA numpy surface, a placement offset,
and a visible flag. The stack lists the topmost layer first, with a thumbnail
and an eye toggle on every row. The composite flattens them in order over an
opaque white base. Surface strokes raycast to the nearest visible triangle
and interpolate its `uv2`, so occluded surfaces are not painted by mistake.

Saving goes through the tab's usual `Save` (`Ctrl+S`), which calls
`uvpaint.commit_to_model(stem)`: the composite is written through
`Project.store_texture` and then worn - as
`textures/{stem}-{object}-uv-tex.png` on the picked object's `texture`,
with that object's `painted` up, or as `textures/{stem}-uv-tex.png` on the
whole model when it has no objects at all. The running game then samples
the painted sheet on `uv2` and ignores the old tiled one. See
[Models and Meshes](models-and-meshes.md) for the `uv2` channel.

A middle or right drag on the canvas pans the view; the wheel zooms at
the pointer. The paint toolbar's `Undo` / `Redo` owns paint strokes; the Model tab's
`Ctrl+Z` / `Ctrl+Y` owns geometry and file-level edits, so the histories remain
independent.

### 2D rig mode

A `.model2d` document opens in the same tab but a different editor. The 3D
half is put aside entirely - `self.model` stays `None` while `self.model2d`
holds the rig - so no shape tool, orbit or paint brush reaches a flat
document, and the `Edit` / `Texture` switch is inert.

The viewport is plain pygame (no `Renderer`): it draws the rig box and each
part exactly the way `components.Sprite2D` will draw it in the game, so what
is on screen is what ships. A part is a quad sized by the rig box and its
own `scale`, cut by its `uv`, turned by its `rot` plus any `rot` track at
the playhead, and placed in rig pixels from the pivot. A `parent` names the
part a piece is hinged to; the engine does not place by it, and neither do
these previews - it is a book-keeping link for layering and tracks.

| Band | Buttons |
| --- | --- |
| `Rig` | the `2D cutout` mark |
| `Objects` | `Add`, `Duplicate`, `Delete`, `Back`, `Forward` |
| `Anim` | `Play`, `Key`, `Prev`, `Next`, `Del key` |
| `File` | `Save` `Reload` `Undo` `Redo` |
| `Move` | `Snap` |
| `View` | `Frame` |

The bands follow the same wrap-and-scroll rule as the 3D toolbar, and the row
under them holds `Name`, the rig's name field (which also takes its whole-rig
turn, in degrees), and the live hint.

| Input | Effect |
| --- | --- |
| Left-drag a part | move it (snap to the grid when `Snap` is on; `Shift` drops the snap for one drag) |
| Middle-drag, right-drag, or left-drag empty space | pan the view |
| Wheel | zoom at the pointer; `Home` frames the rig |
| `Space` | play / pause the tracks from the playhead |
| `Delete` | remove the picked part, its layers and its tracks |
| `G` | toggle the snap grid |

The right dock (`PART_W` 186, only shown when there is room) is the 2D rig's
object menu. Its **Objects** list shows parts back-to-front with a thumbnail,
a hidden strike-out and a parent dot. The `Add`, `Duplicate` and `Delete`
controls above the list work on the selected object; Shift-click in the list
selects multiple objects for group movement. Below the list are the
properties: the rig's `size`, `pivot` and `texture`, then the
picked part's `name`, `texture`, `uv`, `pos`, `rot`, `scale`, `parent` and
`visible`. Click a value to edit it - a text or number field opens in place
(the same grip pattern the Document tab uses), a `texture` or `parent` field
cycles a popup menu, `visible` flips on click. A part with no colour to
show is filled from the shared colour picker, so a preview is a real surface
key, not a lookalike.

Editing works on the document's own plain dicts. Undo is a `copy.deepcopy`
snapshot of `size`/`pivot`/`texture`/`parts`/`tracks`; any edit that mutates
a part first deep-copies the list (`_clone_parts`) so the snapshot on the
stack never shares a dict with the live document. `Key` writes the picked
part's current `rot` as a track key at the playhead; `Next` / `Prev` jump it
between keys and `Del key` drops the one under it. Saving goes through
`Project.store_model2d`, so the cache a running game reads is the file on
disk. The geometry itself lives in `engine.model.Model2D`; the tab only
reads and writes it.

## Assets tab

| Folder row | Lists |
| --- | --- |
| All | manifest, sidecars, then every asset folder |
| Scenes / Objects / Scripts / Models / Textures / Audio | `project.files(kind)` |

Each rail row wears `FOLDER_ICONS` - the same picture the Project View uses for
that kind - and the two panel headers use `tab-assets-sym` and
`open-folder-sym`.

Cards are `CARD_W` 116 x `CARD_H` 100 with a `THUMB_H` 58 thumbnail well and
`GAP` 9 between them; the folder rail is 104-148 px wide. Order is manifest
and sidecars first, then scenes, objects, scripts, models, textures, audio,
alphabetically inside each group.

| Suffix | Thumbnail, cached by mtime |
| --- | --- |
| `.png` `.jpg` `.jpeg` | the image, smoothly scaled to fit |
| `.wav` `.ogg` `.mp3` `.flac` | the real waveform from `wav_peaks` |
| `.model3d` | a drawn cube plus `N tris` |
| `.model2d` | an outlined quad plus `N parts  M tracks` |
| `.py`, `.json` | the first four lines, keywords tinted with `xp.SYN_KW` |
| `project.flig` | `name`, `title`, `start`, `render.scale` rows |

Clicking a card selects it and feeds its `describe()` rows to the Inspector;
clicking it again inside 0.42 s - or pressing `Enter` on a selected card -
calls `Editor.activate_asset()`, which is just `open_file()`, so the same
suffix routing applies. The folder rail switches the listing and clears the
selection; the wheel scrolls the grid 34 px per notch. `info()` contributes
Folder / Files / Selected rows to the Inspector.

## Audio tab

Playlist on the left (`PLAYLIST_W` 186, 34 px rows with a duration at the
right), then title, waveform, seek track and transport.

| Control | Behaviour |
| --- | --- |
| `rewind-sym`, `step-backward-sym`, `play-sym` / `pause-sym`, `stop-sym`, `step-forward-sym` | transport, picture only; the default button toggles |
| `loop-sym` + `Loop` | repeats the current file |
| `Vol` slider | this player's own gain, separate from the master |
| `Space` | play / pause |
| `S` | stop |
| `Home` | back to the start |
| Left / Right | seek 2 seconds |
| `L` | toggle loop |

`.wav` files are parsed with the standard `wave` module - `wav_peaks()`
buckets amplitudes (220 by default, `0.65` gamma) and caches by mtime, so
scrubbing costs no I/O. Other formats still play through
`pygame.mixer.music` and show a flat line. Durations fall back to the
project's sound bank, then to `pygame.mixer.Sound`. The player is independent
of the scene bank, so preview and playlist never fight.

## Build tab

| Button | Does |
| --- | --- |
| `Build` | `BuildConfig.start()` - PyInstaller in a worker thread, output drained into the log each frame |
| `Dry Run` | writes the launcher script and logs the command line |
| `Run` | launches the built executable, if there is one |
| `Open Dist` | reveals the output folder in the shell |
| `Reset` | back to the generated defaults |

Options come from `engine.build.OPTIONS` and are grouped by
`build.GROUPS`: a `bool` row is a checkbox that toggles on click, a `choice`
row is a combo that cycles, anything else opens a prompt (`;` separates list
entries). The right column shows the command in a mono field plus bundle /
mode / console / dist / exe rows. The header states `PyInstaller ready` or
`PyInstaller missing`. Every detail is in [Building](building.md).

Before PyInstaller launches, `BuildConfig.post_stage` fires
`Project.bake_for_build(plan)` when the project has any bake-flagged
light: the pass writes `textures/{name}-lm.png` for each affected
model - `textures/{model}-{object}-lm.png` for each baked object of a
file that carries objects - patches the staged document's `lightmap`
(the object's entry when there are objects), and drops
every bake node from the staged scene docs. Only `plan.staged` is
touched, so the source project keeps its bake lights and can be
baked again later. See [Lighting](lighting.md) for the pipeline.

## Docs tab

A filter box, a nav rail 240 px wide (rows 18 px), and a reading pane.

| Guides group | Keys |
| --- | --- |
| `docs.GUIDES` | Getting Started, The Project Folder, The Game Loop, Scenes, Objects, Player & Input, Bindings & Gamepad, Models & Meshes, Camera & Rendering, UI & HUD, Audio, Save, Paths & Theme, Config & Settings, Building a Release |

Below the guides, `nav()` lists every module and its top-level classes and
functions. The index is built once, lazily, by `docs.get()` - it reads
`emoeng/__init__.py`, `emoeng/const.py` and `emoeng/engine/*.py` with `ast`
and never imports them, so modules that need a GL context still document
correctly. `Docs.lookup` resolves a dotted expression by progressively
shortening the suffix (300-step budget) and preferring a method on the class
named just before it; `Docs.tip` caches results, bounded at 3000 entries.

This tab is generated from the code. The Markdown files in `emoeng/docs/`
are written prose; the two share subject matter and are maintained
separately.

## Settings tab

Five group tabs from `config.GROUPS`: `editor`, `runtime`, `input`, `build`,
`docs`. Rows are 26 px with a 176 px label column.

| Entry kind | Control |
| --- | --- |
| `bool` | checkbox - left click flips it |
| `choice` | combo - left click steps forward through the choices, right click steps back |
| `list` (`input.*`) | binding row - click, then press a key / mouse button / wheel / pad control to capture it |
| `int` / `float` with a `lo`/`hi` range | slider, snapped to 1/200 of the span (rounded again for ints) |
| anything else | click to type a value in a prompt |

A row that differs from its default gets an `xp.MODIFIED` bar; a changed
binding that clashes with another action is drawn in `xp.LOG_WARN`, and the
help column names the other keys sharing it. Right-clicking any non-choice
row resets that one key. `runtime.fullscreen` is the only entry tagged
`(restart)`. Buttons: `Save`, `Revert`, `Reset Group`, `Copy to Project`,
`Open Folder`, and a note of how many keys differ - or
`all values at their default`. Row heights grow with the font size, so nothing
is clipped at a large `editor.font_size`. The right column shows the selected
entry's help, plus its key, where the value came from, and its default.
Binding capture builds its token through `engine.input.binding_text`, so what
is stored is exactly what the runtime reads - see
[Player and Input](player-and-input.md).

Settings are layered: package default, portable `config.json`, per-user
`config.json`, project overrides, `EMOTION_CONFIG_<GROUP>_<KEY>` environment
variables. See [Save, Config and Paths](save-config-and-paths.md).

### What the editor itself reads

| Key | Default | Wired to |
| --- | --- | --- |
| `editor.theme` | `dark` | `theme.apply`, clears the text cache, wave cache and asset thumbnails |
| `editor.open_as` | `ask` | `Editor.open_as`; `ask` puts up a Blocks/Text `ChoiceDialog` |
| `editor.autosave` | `True` | `flush_code` writes or parks; also copied to `code.autosave` |
| `editor.font_size` | `13` (8-32) | `build_fonts()` rebuilds the font dict in place and calls `use_fonts` on every pane |
| `editor.line_numbers` | `True` | `code.numbers` |
| `editor.minimap` | `False` | `code.minimap` |
| `editor.recent_limit` | `8` (0-40) | `manager.recent_limit` |
| `editor.confirm_close` | `True` | `request_quit()` asks with Save and quit / Quit anyway / Stay here |
| `editor.hot_reload_save` | `True` | `_maybe_hot_reload` after `save_current` |
| `editor.hot_reload_watch` | `True` | `_watch_tick` |

Keys the editor does not route are read by the game process from the same
store when a scene runs - `input.*`, `runtime.fullscreen`, and so on. Two
exceptions are applied live because the editor owns the objects:
`runtime.master_volume` / `music_volume` go into the editor's `Audio`, and
`runtime.mouse_sensitivity` sets `Player.sensitivity`, so the preview behaves
like the built game. `docs.hover_hints` and `docs.hint_delay` configure the
Code tab's tooltips.

The font set is one dict, shared by reference:

| Key | Font |
| --- | --- |
| `small` | tahoma, `size - 2` |
| `normal` | tahoma, `size` |
| `bold` | tahoma bold, `size` - the Blocks tab's node titles and row names |
| `big` | tahoma bold, `size + 5` |
| `title` | tahoma bold, `size + 11` |
| `mono` | consolas, `size - 1` |

## Shared widget layer

| Member | Purpose |
| --- | --- |
| `icon(name, px)`, `draw_icon(surf, name, rect)` | loads `editor/appUI/<name>.png`, nearest-scaled, cached; returns `None`/`False` when missing |
| `scaled_image(name, px)` | larger artwork, drawn the same way (the About portrait) |
| `cached_text(font, text, color)` | rendered-text cache, cleared past 8000 entries |
| `wrap(font, text, width)` | greedy word wrap |
| `header(surf, rect, title, font, right, icon)` | dock header strip |
| `FILE_ICONS`, `file_icon(surf, pos, suffix, ...)` | suffix to PNG, with a procedural colour-square fallback |
| `TreeView` | the two dock lists |
| `TextField` | single-line editing, reused by search, name and prompt fields |
| `PromptDialog`, `ChoiceDialog`, `ColorDialog` | modal panels - text, 2-4 buttons, and a colour picker (hex field over the engine's named tints, answering `#rrggbb`); all three route through `Editor._dialog_ok` / `pick_color` |
| `OutputLog` | the bottom panel |

Every control is painted with `engine.xp` primitives (`button`, `checkbox`,
`combo`, `slider` / `slider_frac`, `field`, `tabs`, `menubar`, `menu_items`,
`titlebar`, `statusbar`, `tooltip`, `message_frame`, `sunken`, `raised`,
`scrollbar`, `gradient_v`) using `engine.theme` colours, so the editor and the
in-game menus are drawn by the same code. Three of them take artwork as an
optional argument - `button(icon=)`, `tabs(icons=, marks=)` and
`menu_items([(label, enabled, icon)])` - and `xp` is engine-level, so it
accepts ready surfaces, never icon names: the editor resolves those through
`widgets.icon()` first.

Artwork lives in `emoeng/editor/appUI/` and is reached only through
`widgets.icon()`, which scales nearest-neighbour and returns `None` when a
file is absent - every caller must therefore have a procedural fallback. The
names the editor asks for, in `emoeng/editor/appUI/`:

| Group | File names (minus `.png`) |
| --- | --- |
| Window | `icon` (taskbar + tree root), `fligma-img` (the About portrait) |
| Tab strip | `tab-scene-sym`, `file-object-3d` (Document), `tab-code-sym`, `tab-model-sym`, `tab-assets-sym`, `tab-audio-sym`, `tab-build-sym`, `tab-docs-sym` (`block-sym` and `settings-sym` complete the ten) |
| Project View, by suffix | `file-code-sym`, `file-image-sym`, `file-audio-sym`, `file-model-sym`, `file-model3d-sym`, `file-model2d-sym`, `file-flig-sym`, `file-text-sym`, `file-exec-sym`, `file-save-sym` |
| Project View, by Python base class | `file-scene-3d`, `file-scene-2d`, `file-scene-ui`, `file-object-3d`, `file-object-2d`, `file-object-ui`, `file-object-player3d`, `file-object-player2d` |
| Any node type | one picture for every row of `scenedoc.NODE_TYPES`, resolved by `widgets.node_icon(type)` (and `widgets.class_icon(class)`): a `CLASS_ART` name when the engine class has its own art - `node-light-sym` (a sun) for the eight light nodes, `node-timer-sym` (a clock) for timers, `sound-on-sym` for emitters, `file-text-sym` for text - otherwise the group's `FLAT_ART` by dimension (`3d` / `2d`), so cameras, screens, physics and UI all read correctly with no per-type table to keep in step. The Document tab tree/strip, the preview scene tree and the Create New Node dialog all call these |
| Log and state | `log-sym`, `warning-sym`, `error-sym`, `fatal-sym`, `dirty-sym`, `block-sym` |
| Scene + audio transport | `play-sym`, `pause-sym`, `stop-sym`, `rewind-sym`, `step-backward-sym`, `step-forward-sym`, `reload-sym`, `loop-sym`, `sound-on-sym`, `sound-off-sym`, `visable-sym`, `hidden-sym` |
| Commands | `menu-sym`, `new-file-sym`, `new-folder-sym`, `open-folder-sym`, `settings-sym` |

## Extending it

| To add | Touch |
| --- | --- |
| a tab | `TAB_*` index, `TAB_LABELS`, `TAB_ICONS`, a `MENUS["View"]` row plus its `ACTION_ICONS` entry, a `_shortcuts` key, a `_draw_work` branch, a `handle_event` branch, `_info_rows`, the caption's current-file branch, and `_DIRTY_TABS` if it edits a document |
| a menu command | one `MENUS` row plus one `_run_action` branch |
| a setting | one `_e(...)` line in `engine/config.py`; `apply_setting` routes the ones the editor itself obeys |
| a build switch | one `Option` in `engine/build.py` - the Build tab lists the table, so it appears and persists by itself |
| a pane font change | implement `use_fonts(fonts)` on the pane and name it in `build_fonts`' list |

```python
from emoeng.editor.app import Editor

ed = Editor("emoeng/projects/mygame")     # opens the project directly
ed.set_tab(3)                             # TAB_MODEL
ed.log("hello", "ok")                     # straight into the output panel
ed.run()                                  # hands over the window
```

Related pages: [Blocks](blocks.md), [Getting Started](getting-started.md),
[Project Folder](project-folder.md), [Building](building.md),
[Save, Config and Paths](save-config-and-paths.md).
