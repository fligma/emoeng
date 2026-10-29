# Building

`engine.build` is a front end for PyInstaller (`const.BUILDER`). It generates a
launcher, plans what the bundle needs, converts one option table into command
line switches, runs the build on a background thread and reports the result. The
table is the same one the Build tab draws, so a flag and a checkbox can never
disagree.

```powershell
python -m emoeng build projects/mygame --onefile --name mygame
```

## What a bundle is

| Piece | Detail |
| --- | --- |
| Launcher | `<workpath>/<name>_entry.py`, written by `write_launcher()`; imports `engine.game.main` and parses `--frames N` and a project path |
| Command | `python -m PyInstaller <flags> <entry>`, run with `cwd = paths.app_dir()` |
| Output | `<distpath>/<name>` - a folder, or one file with `onefile` |
| Intermediates | `workpath` and `specpath`, both defaulting to `<app_dir>/build` |
| Project data | Staged into `<workpath>/bundle/projects/<name>`, added with one `--add-data` pair |
| Sound projects | `audio/*.sfxproject` in the staged copy are rendered to `audio/<name>.wav` and the documents dropped; the project folder keeps the patterns |
| Engine release data | `tools/build_release.py` stages `projects/` and `docs/` beside the executable, so the demo and offline manual ship in the unpacked release folder |
| After a good build | `prune.dedupe()` drops duplicated DLLs, `icon.png` goes beside the exe, the output is zipped to `<distpath>/<name>.zip`, and the bundle's size and file count are printed |
| Requirement | `pip install pyinstaller`; `BuildConfig.available()` reports whether it is present |

## Motion Engine release builds

The repository release workflow builds on native Windows and Linux runners
because PyInstaller builds are platform-specific. On each runner,
`python tools/build_release.py --no-run` creates a one-directory
`MotionEngine/` bundle. The archive keeps this layout:

```
MotionEngine/
├── MotionEngine[.exe]
├── docs/       offline Markdown manual
├── projects/   demo and starter projects
└── _internal/  frozen Python runtime and engine package
```

The GitHub Actions workflow publishes the complete folder as
`MotionEngine-windows.zip` or `MotionEngine-linux.tar.gz`, preserving
executable permissions on Linux. Each release also includes a separate
standalone installer binary: `MotionEngine-installer-windows.exe` on Windows
and `MotionEngine-installer-linux` on Linux. The installer binary is not
wrapped in another archive; the app archive remains the installer’s download
target. Do not build a Windows executable on Linux or a Linux executable on
Windows; use the matching native runner.
The Linux CI job also runs the frozen game for one rendered demo frame and
starts both the project manager and standalone installer under Xvfb. The
Linux app uses the desktop's native window decorations instead of importing
pygame's optional SDL2 window-control extension. The installer excludes
NumPy, which is not part of its runtime requirements. Linux bundles are built
with Ubuntu's system Python and the installer is smoke-tested under QEMU's
baseline x86-64 CPU model; the game, project manager, and installer are tested
there to catch illegal-instruction crashes on older CPUs.
These runtime checks catch Linux GUI/OpenGL startup failures that a
successful PyInstaller build alone cannot detect.

`name` defaults to the project folder name with spaces replaced by `_`, and to
`"game"` when there is no project. `icon` is picked up automatically from
`<project>/icon.ico` if that file exists, otherwise from `<project>/icon.png`
- the picture the project manager's `Set Icon` button writes. PyInstaller
converts the PNG itself on Windows.

## Command line

```
python -m emoeng build [project] [options]
```

| Switch | Effect |
| --- | --- |
| `--onefile` / `-F` / `--onedir` | Single exe, or a folder (the default) |
| `--windowed` / `-w` / `--console` / `-c` | Hide or show the console |
| `--name NAME` | Bundle name |
| `--icon PATH` | Icon file - `.ico`, `.icns`, or a `.png` PyInstaller converts |
| `--dist PATH` / `--work PATH` / `--spec PATH` | Output, work and spec folders |
| `--add-data SRC;DEST` | Extra data (repeatable) |
| `--hidden-import MODULE` | Extra import (repeatable) |
| `--exclude MODULE` | Extra exclusion (repeatable) |
| `--full` / `--no-trim` / `--untrimmed` | Bundle everything: no excludes, no hidden imports |
| `--app` / `--editor` | Build the whole engine app rather than one project |
| `--set KEY=VALUE` | Set any option from the table (repeatable) |
| `--dry-run` / `-n` | Print the plan and the command, then stop |
| `--list` | Print every option key and exit |
| `--reset` | Ignore the overrides stored in `project.flig` |
| `-h` / `--help` | The help text |

Anything unrecognised passes straight through to PyInstaller, with its value if
it has one, so every PyInstaller switch works even when it is not in the table.
`--work` without `--spec` puts the `.spec` beside the other intermediates rather
than in the repo root.

The built game takes the same shapes:

```
<exe>                  play
<exe> --frames 90      render 90 frames and exit (build smoke test)
<exe> <project>        play a specific project folder
```

## Option table

`build.OPTIONS` is a tuple of `Option(key, flag, kind, label, default, group,
help, choices, off_flag)`. `build.GROUPS` is the group order; `build.BY_KEY` and
`build.option(key)` index it. Kinds are `bool`, `str`, `int`, `choice` and
`list`; a `list` is stored as an array and typed in dialogs separated by `;`.

### Output

| Key | Flag | Kind | Default | Meaning |
| --- | --- | --- | --- | --- |
| `name` | `--name` | str | `''` | Bundle name; defaults to the project folder name |
| `onefile` | `--onefile` | bool | `False` | Single self-extracting exe instead of a folder |
| `windowed` | `--windowed` | bool | `True` | No console window (omit for a console build) |
| `icon` | `--icon` | str | `''` | Path to an `.ico` (Windows) / `.icns` (macOS), or a `.png` PyInstaller converts |
| `distpath` | `--distpath` | str | `'dist'` | Where the finished build is written |
| `workpath` | `--workpath` | str | `'build'` | Intermediate files and the generated `.spec` |
| `specpath` | `--specpath` | str | `''` | Where the `.spec` goes (default: workpath) |
| `contents_directory` | `--contents-directory` | str | `''` | Folder holding the bundle contents in a one-dir build |
| `runtime_tmpdir` | `--runtime-tmpdir` | str | `''` | Runtime temporary folder for a one-file build |
| `version_file` | `--version-file` | str | `''` | Windows version resource (`.txt`) |
| `manifest` | `--manifest` | str | `''` | Windows application manifest (`.xml`) |

### Build

| Key | Flag | Kind | Default | Meaning |
| --- | --- | --- | --- | --- |
| `noconfirm` | `--noconfirm` | bool | `True` | Replace the dist folder without asking |
| `clean` | `--clean` | bool | `False` | Wipe PyInstaller's cache first; off means a rebuild reuses it |
| `log_level` | `--log-level` | choice | `'WARN'` | `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `CRITICAL`, `FATAL` |
| `noupx` | `--noupx` | bool | `True` | Never compress binaries with UPX |
| `upx_dir` | `--upx-dir` | str | `''` | Where to find the UPX executable |
| `strip` | `--strip` | bool | `False` | Run `strip` on bundled binaries (non-Windows) |
| `debug` | `--debug` | list | `()` | Bootloader debug: `imports`, `bootloader`, `noarchive` |
| `optimize` | `--optimize` | int | `0` | Python optimisation level (`-1`, `0`, `1`, `2`) |

### Sources

| Key | Flag | Kind | Meaning |
| --- | --- | --- | --- |
| `add_data` | `--add-data` | list | `SOURCE:DEST` pairs bundled with the game |
| `add_binary` | `--add-binary` | list | `SOURCE:DEST` pairs for shared libraries |
| `paths` | `--paths` | list | Extra import roots used while analysing the script |
| `hidden_import` | `--hidden-import` | list | Modules the analyser cannot see |
| `collect_submodules` | `--collect-submodules` | list | Every submodule of a package |
| `collect_data` | `--collect-data` | list | A package's data files |
| `collect_all` | `--collect-all` | list | Data, binaries and submodules of a package |
| `copy_metadata` | `--copy-metadata` | list | `dist-info` metadata for a package |
| `exclude_module` | `--exclude-module` | list | Modules to leave out |
| `runtime_hook` | `--runtime-hook` | list | Python files run before the launcher |
| `additional_hooks_dir` | `--additional-hooks-dir` | list | Extra folders searched for `hook-*.py` |
| `python_option` | `--python-option` | list | Pass a `-X` option to the frozen interpreter |

All default to an empty list, and all are repeatable.

### Windows / macOS / Advanced

| Key | Flag | Kind | Default | Meaning |
| --- | --- | --- | --- | --- |
| `uac_admin` | `--uac-admin` | bool | `False` | Request elevation when the exe starts |
| `uac_uiaccess` | `--uac-uiaccess` | bool | `False` | Allow the exe to drive a secure desktop |
| `target_arch` | `--target-arch` | choice | `''` | `x86_64`, `arm64` or `universal2` |
| `osx_bundle_identifier` | `--osx-bundle-identifier` | str | `''` | `com.example.game` |
| `codesign_identity` | `--codesign-identity` | str | `''` | Code signing identity |
| `entitlements_file` | `--osx-entitlements-file` | str | `''` | Entitlements plist |
| `extra_args` | `--` | list | `()` | Raw arguments appended to the command line |

`extra_args` is appended last by `flag_args()` and never rendered as a flag.

## `BuildConfig` API

```python
from emoeng.engine import build
cfg = build.BuildConfig(project)      # mode=None, trim=None -> read from config
cfg.load(project)                     # apply project.flig's `build` overrides
cfg.set("onefile", True)
print(cfg.text())                     # the whole command, as one string
```

| Group | Members |
| --- | --- |
| Setup | `BuildConfig(project=None, mode=None, trim=None)`, `reset(project=None)`, `apply_plan(plan=None)` |
| Access | `get(key, default=None)`, `set(key, value)`, `set_from_text(key, text)`, `toggle(key)`, `cycle(key, step=1)`, `is_changed(key)`, `values`, `defaults`, `plan` |
| Persistence | `load()` reads `project.meta["build"]`, `store()` writes only changed keys and calls `save_meta()` |
| Command | `flag_args()`, `entry_path()`, `write_launcher()`, `command(entry=None)`, `text(entry=None)`, `output_dir()`, `executable()` |
| Staging | `prepare()` - stage the trimmed mirror and return its report lines |
| Running | `available()`, `busy()`, `start(save=True)`, `drain(log=None)`, `run_build(log=None)`, `post_build()`, `summary()` |
| Result | `process`, `returncode`, `result` (`"building"` / `"ok"` / `"failed"`), `lines` (a queue of `(text, kind)`), `last_entry` |

`start()` is non-blocking: it spawns the process, streams its output into
`cfg.lines` from a reader thread and runs `post_build()` on that thread when the
exit code is `0`. `drain(log)` empties the queue from the UI thread.
`run_build(log)` is the blocking form the CLI uses. Kinds are `info`, `ok`,
`warn`, `error` and `muted`, which is what the Build tab colours its log by.

`BuildConfig(project, mode, trim)`: `mode` is `prune.GAME` or `prune.APP`, and
`trim=None` means "ask the config's `build.trim`".

## Bundle pruning (`fe.prune`)

PyInstaller follows the launcher's static import graph, so a game drifts towards
"everything installed". `prune` measures the gap and `build` applies it. It reads
source with `ast` and never executes a project file, so it sees imports
PyInstaller cannot - a project's `.py` files ride along as data.

```python
from emoeng.engine import prune
p = prune.plan(project)          # a game bundle
p.excludes                       # --exclude-module values
p.hidden                         # --hidden-import values
p.data_pair(";")                 # the one --add-data pair
p.stage(workroot)                # filtered mirror of the project folder
p.lines()                        # report for the Build tab / CLI log
```

| Call | Meaning |
| --- | --- |
| `plan(project=None, mode=None)` | `GAME` when a project is given, else `APP` |
| `full_plan(project=None)` | The app/editor bundle: `TOOLING` stays in, every project ships |
| `untrimmed(project=None, mode=None)` | No excludes, no hidden imports - for chasing a bad exclusion |
| `scan_source(text)` | `(names, engine_names)` from one module, including features reached through an alias (`import emoeng as fe` then `fe.proctex...`) |
| `scan_folder(folder, pattern="**/*.py")` | The union over a folder, skipping junk |
| `scan_project(project)` | Both sets across `scenes/`, `objects/`, `scripts/` |
| `engine_graph()` | Dotted names the engine's runtime modules import |
| `external_roots(names, base)` | The outside packages a set of names needs |
| `skipped(rel)` | Whether a project-relative path is authoring junk |
| `size_of(path)` / `count_of(path)` | Bytes / file count, for the report |
| `dedupe(folder)` | Delete duplicated binaries; returns `(gone, freed)` |
| `human(num)` | Bytes as a readable string |

| `TrimPlan` member | Contents |
| --- | --- |
| `mode` / `name` | `game` or `app`, and the bundle name |
| `imports` / `engine` / `base_engine` / `extra` / `uses` | What the scan found and what the bundle must keep |
| `hidden` / `excludes` | The two flag lists `apply_plan()` pushes into the build |
| `staged` | The mirror folder once `stage()` has written it, else `None` |
| `files_kept`, `bytes_kept`, `files_skipped`, `bytes_skipped`, `source_bytes` | Counters for the report |
| `data_dest()` | `emoeng/projects/<name>` (game) or `emoeng/projects` (app) |
| `data_pair(sep)` | The `--add-data` value, from the mirror when there is one |
| `stage(workroot=None, dry=False)` | Copy only new or changed files, delete what the project no longer has; `dry=True` only counts |
| `lines()` / `reason(module)` | The report and the reason a module is dead weight |

### What is left out, and why

| Set | Contents |
| --- | --- |
| `TOOLING` | `emoeng.editor`, `emoeng.engine.build`, `emoeng.engine.prune`, `emoeng.__main__` - excluded from a game bundle |
| `DEAD` | Measured dead weight with a reason each: `PIL.AvifImagePlugin` (AVIF codec, the loader reads png/jpg only), `PIL.MpegImagePlugin`, `PIL.MicImagePlugin`, `PIL.FpxImagePlugin`, `numpy.f2py`, `numpy.testing`, `numpy.distutils`, `pygame.tests`, `pygame.examples`, `OpenGL.GLU`, `tkinter`, `unittest`, `pydoc_data`, `setuptools`, `pkg_resources`, `ssl` |
| `SKIP_DIRS` | `__pycache__`, `saves`, `.git`, `.idea`, `.vscode`, `dist`, `build`, `.raw_assets`, `.import_cache`, `backup`, `_backup` |
| `SKIP_SUFFIX` | `.pyc`, `.pyo`, `.ase`, `.psd`, `.xcf`, `.blend`, `.tmp`, `.bak`, `.orig`, `.swp`, `.log`, `.drain`, `.thumb` |
| `SKIP_NAMES` | `Thumbs.db`, `desktop.ini`, `.DS_Store`, `ehthumbs.db` |
| `LOCAL` | `scenes`, `objects`, `scripts` - a project's own folders, resolved by the loader, never hidden imports |
| `DUPLICATE_DIRS` / `DUPLICATE_SUFFIX` | `pygame` / `.dll` - written twice by PyInstaller; the top level is on the DLL search path, so the nested copies are dropped after the build |

`DEAD` entries are only excluded when nothing asked for them, and a plugin is
treated as a sibling rather than a subordinate: `import PIL.Image` is not an ask
for `PIL.AvifImagePlugin`.

## A first build, end to end

```powershell
python -m emoeng new projects/mygame "My Game"
python -m emoeng build projects/mygame --dry-run     # read the plan and command
python -m emoeng build projects/mygame               # build it
.\dist\mygame\mygame.exe --frames 120                # smoke test the bundle
```

`--dry-run` prints the plan (`mode`, project file counts, engine module counts,
hidden and excluded lists) and then the exact command line, and writes the
launcher without touching PyInstaller. `--frames 120` renders 120 frames and
exits, which is how a bundle is checked without a player.

Related pages: [Project Folder](project-folder.md),
[Save, Config and Paths](save-config-and-paths.md), [The Editor](editor.md).
