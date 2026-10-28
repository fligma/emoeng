"""Layered configuration: defaults -> portable/user/project/env/CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import paths

VERSION = 1                             # config file format version
ENV_PREFIX = "EMOTION_CONFIG_"          # EMOTION_CONFIG_RUNTIME_FPS_CAP
FILE_NAME = "config.json"
LEGACY_NAME = "settings.json"           # the old theme-only file

# kinds: bool, int, float, str, choice, list
GROUPS = ("editor", "runtime", "input", "build", "docs")


class Entry:
    """One config key: type, default and label."""

    __slots__ = ("key", "kind", "default", "label", "help", "choices",
                 "lo", "hi", "restart")

    def __init__(self, key, kind, default, label, help="", choices=(),
                 lo=None, hi=None, restart=False):
        self.key = key
        self.kind = kind
        self.default = default
        self.label = label
        self.help = help
        self.choices = tuple(choices)
        self.lo = lo
        self.hi = hi
        self.restart = restart          # needs a relaunch to take effect

    @property
    def group(self):
        return self.key.split(".", 1)[0]

    def __repr__(self):
        return f"<Entry {self.key}={self.default!r}>"


def _e(key, kind, default, label, help="", choices=(), lo=None, hi=None,
       restart=False):
    entry = Entry(key, kind, default, label, help, choices, lo, hi, restart)
    SCHEMA.append(entry)
    return entry


SCHEMA = []
BY_KEY = {}

_e("editor.theme", "choice", "dark", "Theme", "Widget palette",
   ("dark", "light"))
_e("editor.open_as", "choice", "blocks", "Open scripts as",
   "How a .py file is opened from the project tree",
   ("ask", "text", "blocks"))
_e("editor.autosave", "bool", True, "Autosave",
   "Write the file when a tab or project is left")
_e("editor.font_size", "int", 13, "Editor font", "Code font size in points",
   lo=8, hi=32)
_e("editor.line_numbers", "bool", True, "Line numbers",
   "Gutter column in the code editor")
_e("editor.minimap", "bool", False, "Minimap",
   "Overview strip on the right of the code and block editors")
_e("editor.recent_limit", "int", 8, "Recent projects",
   "How many projects the manager remembers", lo=0, hi=40)
_e("editor.confirm_close", "bool", True, "Confirm close",
   "Ask before quitting with unsaved changes")
_e("editor.hot_reload_save", "bool", True, "Hot reload on save",
   "Re-run the preview scene when a project script is saved here")
_e("editor.hot_reload_watch", "bool", True, "Hot reload on change",
   "Re-run the preview when a script changes anywhere, even in "
   "another editor")

_e("runtime.fps_cap", "int", 60, "FPS cap",
   "Frames per second limit; 0 runs as fast as it can", lo=0, hi=1000)
_e("runtime.vsync", "bool", True, "VSync",
   "Synchronise swaps with the display when the driver allows it")
_e("runtime.render_scale", "float", 0.0, "Render scale override",
   "0 uses the project manifest; 0.5 renders at half resolution",
   lo=0.0, hi=2.0)
_e("runtime.fullscreen", "bool", False, "Start fullscreen",
   "Open the game window in full-screen mode", restart=True)
_e("runtime.gl_window", "bool", True, "GL-presented window",
   "Show frames straight from the window's GL context; falls back to "
   "the plain window when the driver cannot give one", restart=True)
_e("runtime.master_volume", "float", 0.8, "Master volume",
   "Applied to every sound and to music", lo=0.0, hi=1.0)
_e("runtime.music_volume", "float", 0.6, "Music volume",
   "Scale for background music on top of master", lo=0.0, hi=1.0)
_e("runtime.mouse_sensitivity", "float", 0.0022, "Mouse sensitivity",
   "Look delta per mouse unit", lo=0.0002, hi=0.02)
_e("runtime.show_fps", "bool", True, "Show FPS",
   "Frame-rate readout in the status bar")
_e("runtime.auto_save_interval", "float", 0.0, "Autosave every (s)",
   "0 disables timed autosaving of the game", lo=0.0, hi=600.0)

# Key names, not pygame constants: portable, hand-editable, driver-free.
_e("input.forward", "list", ["w", "up"], "Forward")
_e("input.back", "list", ["s", "down"], "Backward")
_e("input.left", "list", ["a", "left"], "Strafe left")
_e("input.right", "list", ["d", "right"], "Strafe right")
_e("input.run", "list", ["lshift", "rshift"], "Run")
_e("input.up", "list", ["space"], "Move up")
_e("input.down", "list", ["q", "lctrl"], "Move down")
_e("input.use", "list", ["e"], "Use / pick up")
_e("input.reload", "list", ["r"], "Reload scene")
_e("input.pause", "list", ["escape"], "Pause menu")
_e("input.help", "list", ["f1"], "Controls panel")
_e("input.debug", "list", ["f3"], "Debug overlay")
_e("input.screenshot", "list", ["f2"], "Screenshot")
_e("input.restart", "list", ["f5"], "Restart scene")
_e("input.hot_reload", "list", ["f6"], "Re-read code (hot reload)")
_e("input.fullscreen", "list", ["f11"], "Toggle fullscreen")
_e("input.save", "list", ["f8"], "Save game")
_e("input.load", "list", ["f9"], "Load game")
_e("input.capture_mouse", "list", ["f10"], "Toggle mouse capture")

_e("build.trim", "bool", True, "Trim the bundle",
   "Bundle only this project's data and drop modules it never imports")
_e("build.onefile", "bool", False, "One file",
   "Single self-extracting exe instead of a folder")
_e("build.windowed", "bool", True, "Windowed",
   "Build without a console window")
_e("build.clean", "bool", False, "Clean before build",
   "Wipe PyInstaller's cache first (slower, always fresh)")
_e("build.log_level", "choice", "WARN", "Build log",
   "How chatty the build log is",
   ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"))

_e("docs.hover_hints", "bool", True, "Hover hints",
   "Pop up a signature when the mouse rests on an API call")
_e("docs.hint_delay", "float", 0.45, "Hint delay (s)",
   "How long the pointer must rest before a hint appears",
   lo=0.0, hi=3.0)

for _entry in SCHEMA:
    BY_KEY[_entry.key] = _entry

DEFAULTS = {_e2.key: _e2.default for _e2 in SCHEMA}


def coerce(entry, value):
    """Force `value` into the entry's type; returns None when hopeless."""
    try:
        if entry.kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if entry.kind == "int":
            number = int(float(value))
        elif entry.kind == "float":
            number = float(value)
        else:
            number = None
        if number is not None:
            if entry.lo is not None:
                number = max(entry.lo, number)
            if entry.hi is not None:
                number = min(entry.hi, number)
            return int(number) if entry.kind == "int" else number
        if entry.kind == "list":
            if isinstance(value, str):
                parts = [v.strip() for v in value.replace(",", ";").split(";")]
                return [v for v in parts if v]
            return [str(v) for v in value]
        if entry.kind == "choice":
            value = str(value).strip()
            if value in entry.choices:
                return value
            folded = {c.lower(): c for c in entry.choices}
            return folded.get(value.lower())
        return str(value)
    except (TypeError, ValueError):
        return None


def entry(key):
    """The schema entry for `key`, or None."""
    return BY_KEY.get(key)


def keys(group=None):
    out = [e2.key for e2 in SCHEMA]
    if group:
        out = [k for k in out if k.split(".", 1)[0] == group]
    return out


def portable_path():
    """`config.json` beside the exe / repo - the portable install."""
    return paths.app_dir() / FILE_NAME


def user_path():
    return paths.user_dir() / FILE_NAME


def legacy_paths():
    """The theme-only files written before `config` existed."""
    return (paths.package_root() / LEGACY_NAME,
            paths.user_dir() / LEGACY_NAME)


def env_layer():
    """`EMOTION_CONFIG_<GROUP>_<KEY>` overrides, decoded through the schema."""
    out = {}
    for env_key, raw in os.environ.items():
        if not env_key.upper().startswith(ENV_PREFIX):
            continue
        dotted = env_key[len(ENV_PREFIX):].lower().replace("_", ".")
        for key in BY_KEY:
            if key.replace(".", "_") == dotted:
                value = coerce(BY_KEY[key], raw)
                if value is not None:
                    out[key] = value
    return out


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in BY_KEY}


def _migrate_legacy():
    """Adopt `theme` from an old settings.json when missing."""
    for path in legacy_paths():
        theme = _read(path).get("editor.theme")
        if theme is None:
            try:
                raw = json.loads(Path(path).read_text(encoding="utf-8"))
                theme = str(raw.get("theme", "")).lower()
            except (OSError, ValueError):
                continue
        if theme in ("dark", "light"):
            return {"editor.theme": theme}
    return {}


class Config:
    """The merged view plus the writable user layer."""

    def __init__(self, project=None):
        self.layers = []                # (name, dict) low -> high precedence
        self.session = {}               # set() lands here until save()
        self.data = dict(DEFAULTS)
        self.overrides = {}             # what `save()` writes
        self.project = None
        self.reload(project)

    def reload(self, project=None):
        if project is not None:
            self.project = project
        self.layers = []
        if portable_path().is_file():
            self.layers.append(("portable", _read(portable_path())))
        if user_path().is_file():
            self.layers.append(("user", _read(user_path())))
        else:
            legacy = _migrate_legacy()
            if legacy:
                self.layers.append(("migrated", legacy))
        if self.project is not None:
            self.layers.append(("project", self._project_layer()))
        self.layers.append(("env", env_layer()))
        self.layers.append(("session", self.session))
        self.overrides = {}
        for _name, layer in self.layers:
            self.overrides.update(layer)
        self.data = dict(DEFAULTS)
        self.data.update(self.overrides)
        return self

    def _project_layer(self):
        """The `config` object inside project.flig, if the project has one."""
        if self.project is None:
            return {}
        stored = getattr(self.project, "meta", {}).get("config")
        if not isinstance(stored, dict):
            return {}
        return {k: v for k, v in stored.items()
                if k in BY_KEY and coerce(BY_KEY[k], v) is not None}

    def use_project(self, project):
        """Re-resolve with a project layer, on project open."""
        self.project = project
        return self.reload(project)

    def pin(self, key, value, layer="cli"):
        """Highest-priority value for this process, e.g. a CLI flag."""
        entry_ = BY_KEY.get(key)
        if entry_ is None:
            return None
        value = coerce(entry_, value)
        if value is None:
            return None
        self.data[key] = value
        self.layers.append((layer, {key: value}))
        return value

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        return DEFAULTS.get(key, default)

    def __contains__(self, key):
        return key in BY_KEY

    def source(self, key):
        """Which layer a value came from: 'default', 'user', 'env', ..."""
        for name, layer in reversed(self.layers):
            if key in layer:
                return name
        return "default"

    def is_default(self, key):
        return self.get(key) == DEFAULTS.get(key)

    def set(self, key, value):
        entry_ = BY_KEY.get(key)
        if entry_ is None:
            return None
        value = coerce(entry_, value)
        if value is None:
            return None
        self.data[key] = value
        self.session[key] = value
        return value

    def reset(self, key):
        """Drop every layer's value for `key`, reverting to the default."""
        for _name, layer in self.layers:
            layer.pop(key, None)
        self.overrides.pop(key, None)
        self.data[key] = DEFAULTS.get(key)

    def reset_group(self, group):
        for key in keys(group):
            self.reset(key)
        return self.save()

    def changed(self, key):
        entry_ = BY_KEY.get(key)
        if entry_ is None:
            return False
        return self.get(key) != entry_.default

    def group(self, prefix):
        return {k: self.get(k) for k in keys(prefix)}

    def save(self):
        """Persist only the keys that differ from the defaults, atomically."""
        payload = {"version": VERSION}
        for key, value in self.data.items():
            if value != DEFAULTS.get(key):
                payload[key] = value
        for path in (user_path(), portable_path()):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
                os.replace(tmp, path)
                self.overrides = {k: v for k, v in payload.items()
                                  if k != "version"}
                return path
            except OSError:
                continue
        return None

    def write_project(self, project=None):
        """Store the project-relevant keys inside project.flig."""
        project = project or self.project
        if project is None:
            return None
        stored = {k: v for k, v in self.data.items()
                  if v != DEFAULTS.get(k) and k.startswith(
                      ("runtime.", "input."))}
        meta = getattr(project, "meta", None)
        if meta is None:
            return None
        meta["config"] = stored
        project.save_meta()
        return stored

    def describe(self, key):
        entry_ = BY_KEY.get(key)
        return entry_.help if entry_ else ""

    def __repr__(self):
        return (f"<Config {len(self.overrides)} override(s) "
                f"layers={[n for n, _ in self.layers]}>")


KEY_PREFIX = "K_"


def key_code(name):
    """pygame key constant from a config key name."""
    import pygame
    text = str(name).strip().lower()
    if not text:
        return None
    for candidate in (KEY_PREFIX + text.upper(), KEY_PREFIX + text):
        code = getattr(pygame, candidate, None)
        if isinstance(code, int):
            return code
    return None


def key_name(code):
    """Config key name for a pygame constant ('up' for K_UP)."""
    names = _key_names()
    try:
        return names.get(int(code))
    except (TypeError, ValueError):
        return None


_KEY_NAMES = None


def _key_names():
    """`code -> name`, read off the constants themselves, built once."""
    global _KEY_NAMES
    if _KEY_NAMES is None:
        import pygame
        out = {}
        for constant in dir(pygame):
            if not constant.startswith(KEY_PREFIX):
                continue
            value = getattr(pygame, constant, None)
            # the first spelling wins, so aliases read back the same
            if isinstance(value, int) and not isinstance(value, bool) \
                    and value not in out:
                out[value] = constant[len(KEY_PREFIX):].lower()
        _KEY_NAMES = out
    return _KEY_NAMES


CURRENT = None


def load(target=None, path=None, force=False):
    """The process-wide Config, built once and cached."""
    global CURRENT
    project = target if hasattr(target, "meta") else None
    if project is None and target is not None:
        path = target
    if CURRENT is None or force:
        CURRENT = Config(project)
        if path is not None:
            CURRENT.layers.append(("explicit", _read(path)))
            CURRENT.data.update(CURRENT.layers[-1][1])
    elif project is not None and CURRENT.project is not project:
        CURRENT.use_project(project)
    return CURRENT


def current():
    return load()


def get(key, default=None):
    return load().get(key, default)


def set(key, value):  # noqa: A001 - the public API is config.set("a.b", v)
    return load().set(key, value)


def save():
    return load().save()


def bind_defaults(input_obj, group="input"):
    """Apply the config keymap onto an `Input` instance."""
    cfg = load()
    mapping = {key.split(".", 1)[1]: cfg.get(key) for key in keys(group)}
    return input_obj.bind_map(mapping)
