"""PyInstaller builds: option table, config and runner."""

from __future__ import annotations

import importlib.util
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from . import config, paths, prune
from .. import const

META_KEY = const.BUILD_META_KEY
BUILDER = const.BUILDER

SEP = ";" if os.name == "nt" else ":"


class Option:
    """One command-line switch and how the editor should render it."""

    __slots__ = ("key", "flag", "kind", "label", "group", "default",
                 "help", "choices", "off_flag")

    def __init__(self, key, flag, kind, label, default, group,
                 help="", choices=(), off_flag=None):
        self.key = key
        self.flag = flag
        self.kind = kind            # bool | str | int | list | choice
        self.label = label
        self.default = default
        self.group = group
        self.help = help
        self.choices = tuple(choices)
        self.off_flag = off_flag    # emitted when a bool is False

    def __repr__(self):
        return f"<Option {self.flag}>"


# rows here are the Build tab's paint order
OPTIONS = (
    Option("name", "--name", "str", "Name", "", "Output",
           "Bundle name; defaults to the project folder name"),
    Option("onefile", "--onefile", "bool", "One file", False, "Output",
           "Single self-extracting exe instead of a folder"),
    Option("windowed", "--windowed", "bool", "Windowed", True, "Output",
           "No console window (omit for a console build)"),
    Option("icon", "--icon", "str", "Icon", "", "Output",
           "Path to an .ico / .icns, or a .png PyInstaller converts"),
    Option("distpath", "--distpath", "str", "Dist folder", "dist", "Output",
           "Where the finished build is written"),
    Option("workpath", "--workpath", "str", "Work folder", "build", "Output",
           "Intermediate files and the generated .spec"),
    Option("specpath", "--specpath", "str", "Spec folder", "", "Output",
           "Where PyInstaller writes the .spec (default: workpath)"),
    Option("contents_directory", "--contents-directory", "str",
           "Contents dir", "", "Output",
           "Folder holding the bundle contents in a one-dir build"),
    Option("runtime_tmpdir", "--runtime-tmpdir", "str", "Runtime temp",
           "", "Output", "Runtime temporary folder for a one-file build"),
    Option("version_file", "--version-file", "str", "Version file", "",
           "Output", "Windows version resource (.txt)"),
    Option("manifest", "--manifest", "str", "Manifest", "", "Output",
           "Windows application manifest (.xml)"),

    Option("noconfirm", "--noconfirm", "bool", "No confirm", True, "Build",
           "Replace the dist folder without asking"),
    Option("clean", "--clean", "bool", "Clean cache", False, "Build",
           "Wipe PyInstaller's cache and temp files first; off means a "
           "rebuild reuses it"),
    Option("log_level", "--log-level", "choice", "Log level", "WARN",
           "Build", "How chatty the build log is",
           ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL", "FATAL")),
    Option("noupx", "--noupx", "bool", "Skip UPX", True, "Build",
           "Never compress binaries with UPX"),
    Option("upx_dir", "--upx-dir", "str", "UPX folder", "", "Build",
           "Where to find the UPX executable"),
    Option("strip", "--strip", "bool", "Strip", False, "Build",
           "Run strip on the bundled binaries (non-Windows)"),
    Option("debug", "--debug", "list", "Debug", (), "Build",
           "Bootloader debug: imports, bootloader, noarchive"),
    Option("optimize", "--optimize", "int", "Optimize", 0, "Build",
           "Python optimisation level (-1, 0, 1, 2)"),

    Option("add_data", "--add-data", "list", "Add data", (), "Sources",
           "SOURCE:DEST pairs bundled with the game"),
    Option("add_binary", "--add-binary", "list", "Add binary", (),
           "Sources", "SOURCE:DEST pairs for shared libraries"),
    Option("paths", "--paths", "list", "Search path", (), "Sources",
           "Extra import roots used while analysing the script"),
    Option("hidden_import", "--hidden-import", "list", "Hidden import",
           (), "Sources", "Modules the analyser cannot see"),
    Option("collect_submodules", "--collect-submodules", "list",
           "Collect submodules", (), "Sources",
           "Bundle every submodule of a package"),
    Option("collect_data", "--collect-data", "list", "Collect data", (),
           "Sources", "Bundle a package's data files"),
    Option("collect_all", "--collect-all", "list", "Collect all", (),
           "Sources", "Bundle data, binaries and submodules of a package"),
    Option("copy_metadata", "--copy-metadata", "list", "Copy metadata", (),
           "Sources", "Copy dist-info metadata for a package"),
    Option("exclude_module", "--exclude-module", "list", "Exclude", (),
           "Sources", "Modules to leave out of the bundle"),
    Option("runtime_hook", "--runtime-hook", "list", "Runtime hook", (),
           "Sources", "Python files run before the launcher"),
    Option("additional_hooks_dir", "--additional-hooks-dir", "list",
           "Hooks folder", (), "Sources",
           "Extra folders searched for hook-*.py files"),
    Option("python_option", "--python-option", "list", "Python option",
           (), "Sources", "Pass a -X option to the frozen interpreter"),

    Option("uac_admin", "--uac-admin", "bool", "UAC admin", False,
           "Windows", "Request elevation when the exe starts"),
    Option("uac_uiaccess", "--uac-uiaccess", "bool", "UAC uiaccess",
           False, "Windows", "Allow the exe to drive a secure desktop"),

    Option("target_arch", "--target-arch", "choice", "Target arch", "",
           "macOS", "x86_64, arm64 or universal2",
           ("", "x86_64", "arm64", "universal2")),
    Option("osx_bundle_identifier", "--osx-bundle-identifier", "str",
           "Bundle id", "", "macOS", "com.example.game"),
    Option("codesign_identity", "--codesign-identity", "str",
           "Sign identity", "", "macOS", "Code signing identity"),
    Option("entitlements_file", "--osx-entitlements-file", "str",
           "Entitlements", "", "macOS", "Entitlements plist"),

    Option("extra_args", "--", "list", "Extra args", (), "Advanced",
           "Raw arguments appended to the command line"),
)

BY_KEY = {opt.key: opt for opt in OPTIONS}
GROUPS = []
for _opt in OPTIONS:
    if _opt.group not in GROUPS:
        GROUPS.append(_opt.group)


def option(key):
    return BY_KEY[key]


def launcher_text(name):
    """The launcher entry script PyInstaller analyses for the bundle."""
    return f'''"""Generated by the Motion Engine build tab - do not edit.

Launches the "{name}" project. When frozen the project folder rides along
inside the bundle and `engine.paths` copies it beside the exe on first run.

    <exe>                  play
    <exe> --frames 90      render 90 frames and exit (build smoke test)
    <exe> <project>        play a specific project folder
"""

import sys

from emoeng.engine.game import main


def _start():
    args = list(sys.argv[1:])
    frames = None
    project = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--frames" and i + 1 < len(args):
            try:
                frames = int(args[i + 1])
            except ValueError:
                print("--frames needs a number")
                return 2
            i += 2
            continue
        if not arg.startswith("-"):
            project = arg
        i += 1
    main(project, frames=frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(_start())
'''


def shlex_join(parts):
    return subprocess.list2cmdline(parts) if os.name == "nt" else \
        shlex.join(parts)


class BuildConfig:
    """One project's option values, plus the runner machinery."""

    def __init__(self, project=None, mode=None, trim=None):
        self.project = project
        self.mode = mode
        self.trim = trim
        self.values = {}
        self.plan = None
        self.process = None
        self.lines = queue.Queue()
        self.returncode = None
        self.result = ""
        self.last_entry = None
        # a callable that logs after staging, before PyInstaller runs
        self.post_stage = None
        self.reset(project)

    def _settings(self):
        """The `build.*` config keys, with the prefix stripped off."""
        cfg = config.load(self.project)
        return {key[len("build."):]: value
                for key, value in cfg.group("build").items()}

    def _make_plan(self):
        """Ask the pruner what this build needs, honouring `build.trim`."""
        settings = self._settings()
        trim = settings.get("trim", True) if self.trim is None else self.trim
        if not trim:
            return prune.untrimmed(self.project, self.mode)
        return prune.plan(self.project, self.mode)

    def apply_plan(self, plan=None):
        """Merge a trim plan's excludes, hidden imports and data."""
        self.plan = plan if plan is not None else self._make_plan()
        self.values["exclude_module"] = list(self.plan.excludes)
        self.values["hidden_import"] = list(self.plan.hidden)
        self.values["add_data"] = [p for p in (self.plan.data_pair(SEP),)
                                   if p]
        return self.plan

    def reset(self, project=None):
        if project is not None:
            self.project = project
        settings = self._settings()
        self.values = {}
        for opt in OPTIONS:
            value = settings.get(opt.key, opt.default)
            if opt.kind == "list":
                value = []
            self.values[opt.key] = value
        root = paths.package_root()
        base = paths.app_dir()
        self.values["distpath"] = str(base / "dist")
        self.values["workpath"] = str(base / "build")
        self.values["specpath"] = str(base / "build")
        self.values["paths"] = [str(root.parent)]
        if self.project is not None:
            self.values["name"] = self.project.name.replace(" ", "_")
            # icon file, else `icon.png` beside the manifest, else empty
            icon = self.project.path / "icon.ico"
            if not icon.exists():
                icon = self.project.path / const.ICON_NAME
            if icon.exists():
                self.values["icon"] = str(icon)
        if self.values.get("name") is None or not self.values["name"]:
            self.values["name"] = "game"
        # the plan never lands in project.flig
        self.apply_plan(self._make_plan())
        self.defaults = dict(self.values)
        return self

    def load(self, project=None):
        """Apply the overrides stored in the project manifest."""
        if project is not None:
            self.project = project
        self.reset(self.project)
        if self.project is None:
            return self
        stored = self.project.meta.get(META_KEY)
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in BY_KEY:
                    self.values[key] = self._coerce(BY_KEY[key], value)
        return self

    def store(self, project=None):
        """Persist non-default values into project.flig and save it."""
        if project is not None:
            self.project = project
        if self.project is None:
            return None
        stored = {}
        for opt in OPTIONS:
            if not self.is_changed(opt.key):
                continue
            value = self.values.get(opt.key)
            if opt.kind == "list":
                value = [v for v in value if str(v).strip()]
            if value:
                stored[opt.key] = value
        if (self.project.meta.get(META_KEY) or {}) == stored:
            return stored
        self.project.meta[META_KEY] = stored
        self.project.save_meta()
        return stored

    def is_changed(self, key):
        """True when the value differs from the generated default."""
        return self.values.get(key) != self.defaults.get(key)

    @staticmethod
    def _default(opt):
        return [] if opt.kind == "list" else opt.default

    def get(self, key, default=None):
        return self.values.get(key, default)

    def _coerce(self, opt, value):
        try:
            if opt.kind == "bool":
                return bool(value)
            if opt.kind == "int":
                return int(value)
            if opt.kind == "list":
                if isinstance(value, str):
                    return [v.strip() for v in value.split(";") if v.strip()]
                return [str(v) for v in value]
            if opt.kind == "choice":
                value = str(value)
                return value if value in opt.choices else opt.default
            return str(value)
        except (TypeError, ValueError):
            return self._default(opt)

    def set(self, key, value):
        opt = BY_KEY.get(key)
        if opt is None:
            return None
        self.values[key] = self._coerce(opt, value)
        return self.values[key]

    def set_from_text(self, key, text):
        """Apply a value typed into a single-line dialog."""
        opt = BY_KEY.get(key)
        if opt is None:
            return None
        if opt.kind == "list":
            return self.set(key, [v.strip() for v in str(text).split(";")
                                  if v.strip()])
        return self.set(key, text)

    def toggle(self, key):
        opt = BY_KEY.get(key)
        if opt is None or opt.kind != "bool":
            return None
        self.values[key] = not bool(self.values.get(key))
        return self.values[key]

    def cycle(self, key, step=1):
        opt = BY_KEY.get(key)
        if opt is None or opt.kind != "choice":
            return None
        choices = list(opt.choices)
        try:
            index = choices.index(str(self.values.get(key, opt.default)))
        except ValueError:
            index = 0
        self.values[key] = choices[(index + step) % len(choices)]
        return self.values[key]

    def flag_args(self):
        """Every option rendered as PyInstaller switches."""
        args = []
        for opt in OPTIONS:
            if opt.key == "extra_args":
                continue
            value = self.values.get(opt.key)
            if opt.kind == "bool":
                if value:
                    args.append(opt.flag)
                elif opt.off_flag:
                    args.append(opt.off_flag)
            elif opt.kind == "list":
                for item in value:
                    if str(item).strip():
                        args.extend([opt.flag, str(item)])
            elif value not in ("", None):
                args.extend([opt.flag, str(value)])
        args.extend(str(a) for a in self.values.get("extra_args", ())
                    if str(a).strip())
        return args

    def entry_path(self):
        """Where the generated launcher script lives."""
        work = Path(self.values.get("workpath") or
                    (paths.app_dir() / "build"))
        name = self.values.get("name") or "game"
        return work / f"{name}_entry.py"

    def write_launcher(self):
        entry = self.entry_path()
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(launcher_text(self.values.get("name", "game")),
                         encoding="utf-8")
        self.last_entry = entry
        return entry

    def command(self, entry=None):
        entry = Path(entry) if entry is not None else self.entry_path()
        return [sys.executable, "-m", BUILDER, *self.flag_args(), str(entry)]

    def text(self, entry=None):
        return shlex_join(self.command(entry))

    def output_dir(self):
        dist = Path(self.values.get("distpath") or
                    (paths.app_dir() / "dist"))
        name = self.values.get("name") or "game"
        return dist / name

    def prepare(self):
        """Stage trimmed project data; report what the bundle carries."""
        plan = self.plan if self.plan is not None else self.apply_plan()
        if plan.mode == prune.GAME and self.project is not None:
            work = Path(self.values.get("workpath") or
                        (paths.app_dir() / "build"))
            plan.stage(work)
            self.values["add_data"] = [p for p in (plan.data_pair(SEP),) if p]
        elif not self.values.get("add_data"):
            self.values["add_data"] = [p for p in (plan.data_pair(SEP),) if p]
        return plan.lines()

    def executable(self):
        """The built game, if this machine can run it."""
        root = self.output_dir()
        if self.values.get("onefile"):
            for candidate in (root, root.with_suffix(".exe")):
                if candidate.is_file():
                    return candidate
            return None
        for name in (f"{root.name}.exe", root.name):
            candidate = root / name
            if candidate.is_file():
                return candidate
        return None

    def available(self):
        try:
            return importlib.util.find_spec(BUILDER) is not None
        except (ImportError, ValueError):
            return False

    def busy(self):
        return self.process is not None and self.process.poll() is None

    def start(self, save=True):
        """Write the launcher, spawn PyInstaller, stream output."""
        if self.busy():
            return None
        if save and self.project is not None:
            try:
                self.store()
            except OSError:
                pass
        entry = self.write_launcher()
        self.lines = queue.Queue()
        self.returncode = None
        self.result = "building"
        try:
            report = self.prepare()
        except OSError as exc:
            report = [f"cannot stage project data: {exc}"]
        for line in report:
            self.lines.put((line, "muted"))
        # a bake pass wants the staged tree before the subprocess
        if self.post_stage is not None:
            try:
                extra = self.post_stage(self.plan) or []
            except Exception as exc:                     # noqa: BLE001
                extra = [f"post-stage hook failed: {exc}"]
            for line in extra:
                self.lines.put((str(line), "muted"))
        if not self.values.get("add_data"):
            self.lines.put(("no project data staged", "warn"))
        # built after staging, so --add-data points at the trimmed mirror
        cmd = self.command(entry)
        try:
            self.process = subprocess.Popen(
                cmd, cwd=str(paths.app_dir()),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        except OSError as exc:
            self.lines.put((f"cannot start {BUILDER}: {exc}", "error"))
            self.result = "failed"
            self.returncode = -1
            return None
        self.lines.put((f"> {shlex_join(cmd)}", "muted"))
        threading.Thread(target=self._reader, daemon=True).start()
        return self.process

    def summary(self):
        """The plan report, for the Build tab's info column."""
        if self.plan is None:
            return []
        return self.plan.lines()

    def _reader(self):
        proc = self.process
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self.lines.put((line.rstrip(), "info"))
        proc.wait()
        self.returncode = proc.returncode
        self.result = "ok" if proc.returncode == 0 else "failed"
        if proc.returncode == 0:
            for text, kind in self.post_build():
                self.lines.put((text, kind))
        self.lines.put((f"build finished (exit {proc.returncode})",
                        "ok" if proc.returncode == 0 else "error"))

    def post_build(self):
        """After an OK build: drop duplicated binaries, carry the"""
        out = []
        dist = self.output_dir()
        if not self.values.get("onefile") and dist.is_dir():
            inner = dist / (self.values.get("contents_directory")
                            or "_internal")
            try:
                gone, freed = prune.dedupe(inner)
            except OSError as exc:
                gone, freed = [], 0
                out.append((f"dedupe skipped: {exc}", "warn"))
            if gone:
                out.append((f"deduped {len(gone)} duplicated binaries "
                            f"({prune.human(freed)})", "ok"))
        if dist.exists():
            self._carry_icon(dist, out)
            self._zip_bundle(dist, out)
            size = prune.human(prune.size_of(dist))
            if dist.is_dir():
                out.append((f"bundle {size} in {prune.count_of(dist)} "
                            f"files", "ok"))
            else:
                out.append((f"bundle {size}, one file", "ok"))
        return out

    def _carry_icon(self, dist, out):
        """Store `icon.png` beside the exe: the uploaded picture when"""
        if self.project is None:
            return
        into = dist if dist.is_dir() else dist.parent
        src = self.project.path / const.ICON_NAME
        try:
            if src.is_file():
                shutil.copyfile(src, into / const.ICON_NAME)
                out.append((f"icon beside the exe: {const.ICON_NAME}",
                            "ok"))
                return
            from .game import default_icon_surface
            art = default_icon_surface(self.project.name)
            if art is not None:
                import pygame
                pygame.image.save(art, str(into / const.ICON_NAME))
                out.append((f"default icon beside the exe: "
                            f"{const.ICON_NAME}", "ok"))
        except (OSError, ValueError, RuntimeError) as exc:
            out.append((f"icon not carried: {exc}", "warn"))

    def _zip_bundle(self, dist, out):
        """Zip the one-dir build output beside itself."""
        stem = dist.name if dist.is_dir() else dist.stem
        target = dist.parent / stem
        try:
            made = shutil.make_archive(str(target), "zip",
                                       root_dir=str(dist.parent),
                                       base_dir=dist.name)
            out.append((f"zipped {Path(made).name} "
                        f"({prune.human(Path(made).stat().st_size)})",
                        "ok"))
        except OSError as exc:
            out.append((f"zip skipped: {exc}", "warn"))

    def drain(self, log=None):
        """Pop queued output lines; call from the UI thread."""
        count = 0
        while True:
            try:
                text, kind = self.lines.get_nowait()
            except queue.Empty:
                break
            count += 1
            if log is not None:
                log(text, kind)
        return count

    def run_build(self, log=None):
        """Blocking build, for the command line."""
        if not self.available():
            if log:
                log(f"{BUILDER} is not installed: pip install pyinstaller",
                    "error")
            return 1
        self.start(save=False)
        if self.process is None:
            return 1
        self.drain(log)
        self.process.wait()
        self.drain(log)
        return self.returncode or 0


CLI_HELP = f"""build a project into a standalone {BUILDER} bundle

    python -m emoeng build [project] [options]

Options
  --onefile / --onedir     single exe or a folder
  --windowed / --console   hide or show the console
  --name NAME              bundle name
  --icon PATH              icon file
  --dist PATH              dist folder
  --work PATH              work folder
  --full                   bundle everything: no excludes, no hidden imports
  --app                    build the whole engine app, not one project
  --set KEY=VALUE          set any option from the table (repeatable)
  --add-data SRC;DEST      extra data (repeatable)
  --hidden-import MODULE   extra import (repeatable)
  --exclude MODULE         extra exclusion (repeatable)
  --dry-run                print the command and stop
  --list                   print every option key and exit
  --reset                  ignore the stored manifest overrides

By default the bundle is trimmed from a scan of the project's own sources
(`engine.prune`): the IDE is left out, only this project's data is staged,
and modules nothing imports - an AVIF codec, numpy's Fortran generator -
are excluded. `--dry-run` prints the plan before the command.

Anything else is passed straight through to {BUILDER}, so every one of its
switches is available even if it is not in the table above.
"""


def _cli_values(argv):
    """Split argv into (project, {key: value}, passthrough)."""
    project = None
    values = {}
    extra = []
    reset = False
    dry = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if arg == "--set" and nxt and "=" in nxt:
            key, value = nxt.split("=", 1)
            values[key] = value
            i += 2
            continue
        if arg.startswith("--set=") and "=" in arg[6:]:
            key, value = arg[6:].split("=", 1)
            values[key] = value
            i += 1
            continue
        if arg in ("--dry-run", "-n"):
            dry = True
            i += 1
            continue
        if arg == "--reset":
            reset = True
            i += 1
            continue
        if arg in ("--full", "--no-trim", "--untrimmed"):
            values["trim"] = False
            i += 1
            continue
        if arg in ("--app", "--editor"):
            values["mode"] = prune.APP
            i += 1
            continue
        table = {"--name": "name", "--icon": "icon", "--dist": "distpath",
                 "--work": "workpath", "--spec": "specpath",
                 "--add-data": "add_data", "--hidden-import": "hidden_import",
                 "--exclude": "exclude_module"}
        if arg in table and nxt is not None:
            key = table[arg]
            if BY_KEY[key].kind == "list":
                values.setdefault(key, []).append(nxt)
            else:
                values[key] = nxt
            i += 2
            continue
        if arg == "--onefile":
            values["onefile"] = True
        elif arg == "--onedir":
            values["onefile"] = False
        elif arg == "--windowed":
            values["windowed"] = True
        elif arg == "--console":
            values["windowed"] = False
        elif arg in ("-F",):
            values["onefile"] = True
        elif arg in ("-w",):
            values["windowed"] = True
        elif arg in ("-c",):
            values["windowed"] = False
        elif arg.startswith("-"):
            extra.append(arg)
            if nxt is not None and not nxt.startswith("-"):
                extra.append(nxt)
                i += 1
        elif project is None:
            project = arg
        else:
            extra.append(arg)
        i += 1
    return project, values, extra, reset, dry


def main(argv=None):
    from .loader import Project

    args = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in args):
        print(CLI_HELP)
        return 0
    if "--list" in args:
        for opt in OPTIONS:
            print(f"{opt.key:<22} {opt.flag:<24} {opt.kind:<7}"
                  f"{opt.group:<9}{opt.help}")
        return 0
    wanted, values, extra, reset, dry = _cli_values(args)
    trim = values.pop("trim", None)
    mode = values.pop("mode", None)
    try:
        project = Project(wanted) if wanted else \
            Project(Project.default_path())
    except (FileNotFoundError, ValueError) as exc:
        print(f"no project: {exc}")
        return 2
    cfg = BuildConfig(project, mode=mode, trim=trim)
    if not reset:
        cfg.load(project)
    for key, value in values.items():
        cfg.set(key, value)
    if "workpath" in values and "specpath" not in values:
        # keep the .spec beside other intermediates, not the repo
        cfg.set("specpath", cfg.get("workpath"))
    cfg.set("extra_args", extra)
    if not cfg.available():
        print(f"{BUILDER} is not installed: pip install pyinstaller")
        return 2
    for line in cfg.prepare():
        print(f"  {line}")
    if dry:
        cfg.write_launcher()
        print(cfg.text())
        return 0
    print(f"building {project.title} -> {cfg.output_dir()}")
    code = cfg.run_build(lambda text, kind=None: print(
        f"  {text}" if kind not in ("error",) else f"! {text}"))
    return code
