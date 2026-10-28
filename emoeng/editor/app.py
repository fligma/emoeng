"""The Motion Engine editor:"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import pygame

from .. import CODENAME, __version__, const
from ..engine import (config, input as inputmod, model as modelmod,
                      paths, player as playermod,
                      scenedoc, shaders, templates, theme, xp)
from ..engine.audio import Audio
from ..engine.loader import (META_NAME, INPUT_NAME, ASSET_NAME,
                             OBJECT_PRESETS, SCENE_PRESETS,
                             SHADER_PRESETS, Project, read_meta)
from ..engine.winchrome import WindowChrome, caption_buttons
from . import importer, mediaplayer, widgets
from .assets import AssetBrowser
from .blocktab import BlockTab
from .buildtab import BuildTab
from .codeeditor import CodeEditor
from .doctab import DocTab
from .docstab import DocsTab
from .mediaplayer import MediaPlayer
from .modeleditor import ModelEditor
from .preview import Preview
from .projectmanager import ProjectManager
from .projecttab import ProjectTab
from .settingstab import SettingsTab

CAP_H = 28
MENU_H = 22
FLASH_MS = 140          # how long a chosen menu cell keeps its click mark
TAB_H = 24
STATUS_H = 22
TREE_W = 232
INSPECT_W = 260
MIN_TREE_W = 150        # narrowest the project docks go before the tab does
MIN_INSPECT_W = 170
MIN_WORK_W = 320        # room a tab's own toolbar has to keep
OUT_H = 132
MENU_LABELS = ("File", "Edit", "View", "Project", "Help")
TAB_SCENE, TAB_DOC, TAB_CODE, TAB_BLOCKS, TAB_MODEL, TAB_ASSETS, \
    TAB_AUDIO, TAB_BUILD, TAB_DOCS, TAB_SETTINGS, TAB_PROJECT = range(11)
TAB_LABELS = ("Scene", "Document", "Code", "Blocks", "Model", "Assets",
              "Audio", "Build", "Docs", "Settings", "Project")
TAB_TIPS = (
    "Preview and edit the active scene.",
    "Edit the selected scene or object document.",
    "Edit Python source files.",
    "Build gameplay logic with visual blocks.",
    "Edit and inspect 3D and 2D models.",
    "Browse and preview project assets.",
    "Preview, trim, and organize audio.",
    "Configure and run a distributable build.",
    "Browse the engine guides and API reference.",
    "Edit engine and project settings.",
    "Edit project.flig and its input bindings.",
)
# one picture per tab, in TAB_* order
TAB_ICONS = ("tab-scene-sym", "file-object-3d", "tab-code-sym", "block-sym",
             "tab-model-sym", "tab-assets-sym", "tab-audio-sym",
             "tab-build-sym", "tab-docs-sym", "settings-sym", "settings-sym")
# which tab holds an editable document and its state
_DIRTY_TABS = ((TAB_DOC, "doctab"), (TAB_CODE, "code"),
               (TAB_BLOCKS, "blocks"), (TAB_MODEL, "model"))
# Run lives in the tab strip, not a menu
RUN_ICON = "play-sym"
FOLDERS = ("scenes", "objects", "shaders", "scripts", "models", "maps",
           "textures", "audio")
# the Project View files run-time folders and media separately
TREE_BANDS = (("code", ("scenes", "objects", "shaders", "scripts")),
              ("assets", ("models", "maps", "textures", "audio")))
# (create group, default kind) per folder's plus button
FOLDER_CREATE = {"scenes": ("scene", "new_scene"),
                 "objects": ("object", "new_object"),
                 "shaders": ("shader", "new_shader"),
                 "scripts/scenes": ("scene", "new_scene"),
                 "scripts/objects": ("object", "new_object"),
                 "scripts/shaders": ("shader", "new_shader")}
AUDIO_EXT = (".wav", ".ogg", ".mp3", ".flac")
IMAGE_EXT = (".png", ".jpg", ".jpeg")
# a document row's picture, by the kind it states
SCENE_ICONS = {"scene3d": "file-scene-3d", "scene2d": "file-scene-2d",
               "sceneui": "file-scene-ui"}
OBJECT_ICONS = {"object3d": "file-object-3d", "object2d": "file-object-2d"}
# a `.py` in scenes/ or objects/ is shown, never run
STRAY_LABEL = "   (not loaded)"

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = paths.projects_dir()

MENUS = {
    "File": [("New Project...", "new_project"),
             ("Open Project...", "open_project"),
             ("Open Folder...", "open_folder"),
             ("-", None),
             ("Project Manager", "manager"),
             ("Save", "save"),
             ("Run Game          F5", "run"),
             ("-", None),
             ("Exit", "exit")],
    "Edit": [("Undo          Ctrl+Z", "undo"),
             ("Redo          Ctrl+Y", "redo"),
             ("-", None),
             ("Cut           Ctrl+X", "cut"),
             ("Copy          Ctrl+C", "copy"),
             ("Paste         Ctrl+V", "paste"),
             ("-", None),
             ("Settings...   Ctrl+,", "tab_settings")],
    "View": [("Scene Tab         F6", "tab_scene"),
             ("Document Tab  Ctrl+D", "tab_doc"),
             ("Code Tab          F7", "tab_code"),
             ("Blocks Tab  Shift+F7", "tab_blocks"),
             ("Model Tab         F8", "tab_model"),
             ("Assets Tab        F9", "tab_assets"),
             ("Audio Tab         F10", "tab_audio"),
             ("Build Tab     Ctrl+B", "tab_build"),
             ("Docs Tab          F12", "tab_docs"),
             ("Settings Tab  Ctrl+,", "tab_settings"),
             ("Project Tab", "tab_project"),
             ("-", None),
             ("Toggle Theme  Ctrl+T", "toggle_theme"),
             ("Toggle Output", "toggle_output"),
             ("Toggle Inspector", "toggle_inspector"),
             ("-", None),
             ("Reload Project", "reload_project"),
             ("Maximize      F11", "maximize")],
    "Project": [("Play Scene", "preview"),
                ("Reload Scene", "reload_scene"),
                ("-", None),
                ("Build Game...", "build"),
                ("-", None),
                ("New 3D Scene...", "new_scene"),
                ("New 2D Scene...", "new_scene_2d"),
                ("New UI Scene...", "new_scene_ui"),
                ("-", None),
                ("New 3D Object...", "new_object"),
                ("New 2D Object...", "new_object_2d"),
                ("New UI Object...", "new_ui_object"),
                ("New Player 3D...", "new_player_3d"),
                ("New Player 2D...", "new_player_2d"),
                ("New Camera 3D...", "new_camera_3d"),
                ("New Camera 2D...", "new_camera_2d"),
                ("New Screen 3D...", "new_screen_3d"),
                ("New Screen 2D...", "new_screen_2d"),
                ("-", None),
                ("New Shader...", "new_shader"),
                ("-", None),
                ("New Model...", "new_model"),
                ("New 2D Model...", "new_model_2d"),
                ("New Script...", "new_script"),
                ("-", None),
                ("Import Asset...", "import_asset"),
                ("-", None),
                ("Project Manager", "manager")],
    "Help": [("Keyboard Shortcuts", "keys"), ("About", "about")],
}

# what each menu action does, drawn in the gutter
ACTION_ICONS = {
    "new_project": "new-folder-sym",
    "new_scene": "new-file-sym",
    "new_scene_2d": "new-file-sym",
    "new_scene_ui": "new-file-sym",
    "new_object": "new-file-sym",
    "new_object_2d": "new-file-sym",
    "new_ui_object": "new-file-sym",
    "new_player_3d": "new-file-sym",
    "new_player_2d": "new-file-sym",
    "new_camera_3d": "new-file-sym",
    "new_camera_2d": "new-file-sym",
    "new_screen_3d": "new-file-sym",
    "new_screen_2d": "new-file-sym",
    "new_model": "new-file-sym",
    "new_model_2d": "new-file-sym",
    "new_shader": "new-file-sym",
    "new_script": "new-file-sym",
    "open_project": "open-folder-sym",
    "open_folder": "open-folder-sym",
    "manager": "open-folder-sym",
    "save": "file-save-sym",
    "run": "play-sym",
    "preview": "play-sym",
    "reload_project": "reload-sym",
    "reload_scene": "reload-sym",
    "build": "tab-build-sym",
    "tab_scene": "tab-scene-sym",
    "tab_doc": "file-object-3d",
    "tab_code": "tab-code-sym",
    "tab_blocks": "block-sym",
    "tab_model": "tab-model-sym",
    "tab_assets": "tab-assets-sym",
    "tab_audio": "tab-audio-sym",
    "tab_build": "tab-build-sym",
    "tab_docs": "tab-docs-sym",
    "tab_settings": "settings-sym",
    "tab_project": "settings-sym",
    "toggle_output": "log-sym",
    "import_asset": "open-folder-sym",
    "keys": "tab-docs-sym",
    "about": "tab-docs-sym",
}

# kinds New makes: menu and dialog share one set
_CREATE_KINDS = frozenset(SCENE_PRESETS) | frozenset(OBJECT_PRESETS) | \
    frozenset({"new_model", "new_model_2d", "new_script", "new_shader"})

SCRIPT_TEMPLATE = '''"""Shared helpers; import them from a scene.

    from scripts.helpers import clamp
"""


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value
'''


def default_project():
    p = PROJECTS / const.DEFAULT_PROJECT
    if (p / "project.flig").exists():
        return p
    if PROJECTS.is_dir():
        for p in sorted(PROJECTS.iterdir()):
            if (p / "project.flig").exists():
                return p
    return None


def clean_stem(text, fallback="untitled"):
    s = "".join(c if c.isalnum() or c in "_-" else "_"
                for c in str(text).strip())
    s = s.strip("_")
    return s or fallback


# the icon a `.py` earns from its base class
CLASS_ICONS = {
    "Scene3D": "file-scene-3d",
    "Scene2D": "file-scene-2d",
    "SceneUI": "file-scene-ui",
    "Object3D": "file-object-3d",
    "Object2D": "file-object-2d",
    "UIObject": "file-object-ui",
    # players are spawnable objects; their subclasses read the same way
    "Player3D": "file-object-player3d",
    "Player2D": "file-object-player2d",
    "Player": "file-object-player3d",
}
# a component or view base earns that type's picture too
for _row in scenedoc.NODE_TYPES:
    if _row[5]:
        CLASS_ICONS.setdefault(_row[5], widgets.node_icon(_row[0]))

_BASE_RE = re.compile(r"class\s+\w+\s*\(([^)]*)\)")


def python_icon(path):
    """The icon a `.py` earns from its first engine class."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "file-code-sym"
    for match in _BASE_RE.finditer(text):
        for base in re.split(r"[,\s]+", match.group(1)):
            name = base.rsplit(".", 1)[-1].strip()
            if name in CLASS_ICONS:
                return CLASS_ICONS[name]
    return "file-code-sym"


def file_row_icon(path):
    """The tree icon for any Project View file."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return python_icon(path)
    if suffix == scenedoc.SCENE_EXT or suffix in scenedoc.OBJECT_EXTS:
        return doc_icon(path)
    return widgets.FILE_ICONS.get(suffix)


def doc_icon(path):
    """The icon a document gets, by the kind it states."""
    doc = scenedoc.load(path)
    suffix = path.suffix.lower()
    if suffix in scenedoc.OBJECT_EXTS:
        kind = "object2d" if suffix == scenedoc.OBJECT2D_EXT else "object3d"
        return (widgets.node_icon(doc.get("type")) or
                OBJECT_ICONS.get(str(doc.get("type")) or "",
                                 OBJECT_ICONS[kind]))
    return SCENE_ICONS.get(str(doc.get("kind")), "file-scene-3d")


def _desktop_dir() -> Path:
    """Best-effort user Desktop folder; falls back to home."""
    home = Path.home()
    candidates = []
    if os.name == "nt":
        candidates.append(home / "Desktop")
    else:
        cfg = home / ".config" / "user-dirs.dirs"
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                if line.startswith("XDG_DESKTOP_DIR="):
                    raw = line.split("=", 1)[1].strip().strip('"')
                    candidates.append(Path(os.path.expandvars(raw)))
        except OSError:
            pass
        candidates.append(home / "Desktop")
    for c in candidates:
        if c.is_dir():
            return c
    return home


def _ps_quote(value):
    """Wrap in a PowerShell single-quoted literal (``''`` escapes ``'``)."""
    return "'" + str(value).replace("'", "''") + "'"


class Editor:
    """Owns the window, the project manager and the editor docks."""

    def __init__(self, project_path=None):
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        cfg = config.load()
        theme.apply(cfg.get("editor.theme"))
        self.fps_cap = int(cfg.get("runtime.fps_cap"))
        self.vsync = bool(cfg.get("runtime.vsync"))
        self.font_size = int(cfg.get("editor.font_size"))
        self.screen = self._make_window(1280, 820)
        pygame.display.set_caption(CODENAME)
        self.clock = pygame.time.Clock()
        self.fonts = {}
        self.build_fonts()
        self.audio = Audio(master=float(cfg.get("runtime.master_volume")),
                           music_volume=float(cfg.get("runtime.music_volume")))
        self.log_panel = widgets.OutputLog()
        self.scene_tree = widgets.TreeView()
        self.file_tree = widgets.TreeView()
        self.code = CodeEditor(self)
        self.blocks = BlockTab(self)
        self.model = ModelEditor(self)
        self.preview = Preview(self)
        self.doctab = DocTab(self)
        self.assets = AssetBrowser(self)
        self.media = MediaPlayer(self)
        self.build = BuildTab(self)
        self.docs = DocsTab(self)
        self.settings = SettingsTab(self)
        self.projecttab = ProjectTab(self)
        self.manager = ProjectManager(self)
        self.chrome = WindowChrome()
        self.project = None
        self.mode = "manager"
        self.tab = TAB_SCENE
        self.selected_asset = None
        self.folder_open = {k: True for k in FOLDERS}
        self.node_open = {}            # scene/object node folds, by scope:id
        self.menu_open = None
        self.menu_rows = []
        self.menu_press_row = -1      # dropdown row held under a mouse-down
        self.menu_flash = None        # (cell, ticks until) after a choice
        self.ctx_menu = None          # right-click file menu, when open
        self.ctx_rows = []            # its (action, rect) rows this frame
        # files handed over by a desktop drag, gathered until DROPCOMPLETE
        self._drop_buffer = []
        self.dialog = None
        self.dialog_kind = None
        self.dialog_target = None
        self.dialog_color_ok = None      # the callback a colour answer feeds
        self.notice = None
        self.notice_ok = pygame.Rect(0, 0, 82, 26)
        self.show_output = True
        self.show_inspector = True
        self.running = True
        self.theme_name = theme.current()
        self.fps = 0.0
        self._frame_times = deque(maxlen=30)
        self.dt = 1 / 60.0
        # editor.* mirrors, kept in step by apply_setting()
        self.autosave = True
        self.confirm_close = True
        self.show_fps = True
        self.open_as = "ask"
        self.hot_reload_save = True
        self.hot_reload_watch = True
        self._watch = None             # file-watch snapshot for hot reload
        self._watch_at = 0.0           # when that snapshot was last taken
        self.discard = False
        self.status = "project manager"
        self.process = None
        self.scene_tree_rect = pygame.Rect(0, 0, 0, 0)
        self.file_tree_rect = pygame.Rect(0, 0, 0, 0)
        self.dock_area = pygame.Rect(0, 0, 0, 0)
        self.output_area = pygame.Rect(0, 0, 0, 0)
        self.output_copy = pygame.Rect(0, 0, 0, 0)
        self.output_clear = pygame.Rect(0, 0, 0, 0)
        self.content_area = pygame.Rect(0, 0, 0, 0)
        self.inspector_area = pygame.Rect(0, 0, 0, 0)
        self.tab_rects = []
        self.run_rect = pygame.Rect(0, 0, 0, 0)
        self._last_size = self.screen.get_size()
        self.apply_all()

        if project_path is not None:
            if self.open_project(project_path):
                self.log(f"{CODENAME} editor ready", "ok")
            else:
                self.log(f"cannot open {project_path}; showing the "
                         "project manager", "warn")
        else:
            self.log(f"{CODENAME} project manager ready", "ok")

    def log(self, text, kind="info"):
        self.log_panel.add(text, kind)

    def relative(self, path):
        if self.project is not None:
            return self.project.relative(path)
        return str(path)

    @property
    def cfg(self):
        """The merged settings view; the Settings tab owns it."""
        return self.settings.cfg

    def _make_window(self, w, h):
        """Resizable window with framed swaps when the driver allows them."""
        try:
            surf = pygame.display.set_mode((int(w), int(h)),
                                           pygame.RESIZABLE,
                                           vsync=1 if self.vsync else 0)
        except pygame.error:
            surf = pygame.display.set_mode((int(w), int(h)),
                                           pygame.RESIZABLE)
        try:
            art = widgets.icon("icon", 32)
            if art is not None:
                pygame.display.set_icon(art)
        except pygame.error:
            pass
        return surf

    def build_fonts(self):
        """(Re)fill the font set at the configured size, in place."""
        size = max(8, min(32, int(self.font_size)))
        self.fonts.update({
            "small": pygame.font.SysFont("tahoma", max(8, size - 2)),
            "normal": pygame.font.SysFont("tahoma", size),
            # the block view's keyword text, built once here
            "bold": pygame.font.SysFont("tahoma", size, bold=True),
            "big": pygame.font.SysFont("tahoma", size + 5, bold=True),
            "title": pygame.font.SysFont("tahoma", size + 11, bold=True),
            "mono": pygame.font.SysFont("consolas", max(8, size - 1)),
        })
        widgets._TEXT_CACHE.clear()
        for name in ("code", "blocks", "model", "assets", "media", "build",
                     "docs", "manager", "settings", "preview", "doctab",
                     "projecttab"):
            part = getattr(self, name, None)
            use_fonts = getattr(part, "use_fonts", None)
            if use_fonts is not None:
                use_fonts(self.fonts)

    def apply_all(self):
        """Push every config key into the running editor once."""
        for entry in config.SCHEMA:
            self.apply_setting(entry.key, self.cfg.get(entry.key))

    def apply_setting(self, key, value):
        """Route one config value to whatever reads it."""
        group, _, leaf = str(key).partition(".")
        if group == "editor":
            if leaf == "theme":
                self.set_theme(value)
            elif leaf == "font_size":
                self.font_size = int(value)
                self.build_fonts()
            elif leaf == "line_numbers":
                self.code.numbers = bool(value)
            elif leaf == "minimap":
                self.code.minimap = bool(value)
            elif leaf == "autosave":
                self.autosave = bool(value)
                self.code.autosave = bool(value)
            elif leaf == "confirm_close":
                self.confirm_close = bool(value)
            elif leaf == "open_as":
                self.open_as = str(value)
            elif leaf == "hot_reload_save":
                self.hot_reload_save = bool(value)
            elif leaf == "hot_reload_watch":
                self.hot_reload_watch = bool(value)
            elif leaf == "recent_limit":
                self.manager.recent_limit = int(value)
        elif group == "runtime":
            if leaf == "fps_cap":
                self.fps_cap = int(value)
            elif leaf == "vsync":
                self.vsync = bool(value)
            elif leaf == "master_volume":
                self.audio.set_master(float(value))
            elif leaf == "music_volume":
                self.audio.set_music_volume(float(value))
            elif leaf == "mouse_sensitivity":
                playermod.Player.sensitivity = float(value)
            elif leaf == "show_fps":
                self.show_fps = bool(value)
        elif group == "docs":
            if leaf == "hover_hints":
                self.code.hints = bool(value)
            elif leaf == "hint_delay":
                self.code.hint_delay = float(value)
        elif group == "build" and self.project is not None:
            self.build.config.reset(self.project)

    def prompt_setting(self, key, label, value, help_text=""):
        """Type a value for a setting its control cannot take."""
        entry = config.BY_KEY.get(key)
        if entry is None:
            return
        self.dialog_kind = f"setting:{key}"
        self.dialog = widgets.PromptDialog(f"{label}", "Value", str(value),
                                           hint=help_text or entry.help,
                                           width=430)

    def pick_color(self, title, value, on_ok, hint=None, allow_none=True):
        """Open the colour picker; `on_ok` gets the answer as `#rrggbb`."""
        self.dialog_kind = "color"
        self.dialog_color_ok = on_ok
        self.dialog = widgets.ColorDialog(title=title, value=value or "",
                                          hint=hint,
                                          allow_none=allow_none)

    def flush_code(self):
        """Write the code buffer, or hold without autosave."""
        if not self.code.dirty:
            return True
        if self.autosave:
            return self.code.save()
        self.code.park()
        self.log("autosave is off; edits kept in memory", "muted")
        return True

    def request_quit(self):
        """Ask before discarding unsaved work, unless disabled."""
        if not self.confirm_close or not (self.code.dirty or self.model.dirty
                                          or self.blocks.dirty
                                          or self.doctab.dirty
                                          or self.projecttab.dirty
                                          or self.projecttab.map_dirty):
            self.running = False
            return
        self.dialog_kind = "quit"
        self.dialog = widgets.ChoiceDialog(
            "Unsaved changes",
            "A file still holds edits that have not been written to disk.",
            ("Save and quit", "Quit anyway", "Stay here"),
            hint="Quit anyway leaves the files exactly as they are on disk.",
            default=0)

    def set_theme(self, name):
        """Install a palette and drop artwork from the old."""
        name = theme.apply(name)
        widgets._TEXT_CACHE.clear()
        mediaplayer.WAVE_CACHE.clear()
        self.assets._thumbs.clear()
        self.theme_name = name
        return name

    def toggle_theme(self):
        """Swap dark/light through the settings page, so it is persisted."""
        entry = config.BY_KEY["editor.theme"]
        name = "light" if theme.current() == "dark" else "dark"
        self.settings.apply(entry, name)
        self.status = f"theme: {name}"
        return name

    def open_project(self, path):
        if path is None:
            return False
        try:
            project = Project(path)
        except Exception as exc:
            self.log(f"cannot open project: {exc}", "error")
            return False
        self.flush_code()
        if self.model.dirty:
            self.model.autosave()
        if self.doctab.dirty:
            self.doctab.save_all()
        self.model.close_model()
        self.media.stop()
        self.project = project
        self.mode = "editor"
        # engine warnings land in this project's log, heard once
        shaders.set_logger(self.log)
        self.preview.blur()
        self.preview.set_project(project)
        self.doctab.set_project(project)
        self.assets.set_project(project)
        self.media.set_project(project)
        self.build.set_project(project)
        self.settings.set_project(project)
        self.projecttab.set_project(project)
        self.blocks.set_project(project)
        self.reset_watch()
        self.manager.note_open(project.path)
        self.model.refresh_textures()
        try:
            project.load_audio(self.audio)
        except Exception as exc:
            self.log(f"audio: {exc}", "warn")
        self.folder_open = {k: True for k in FOLDERS}
        self.node_open = {}
        self.selected_asset = None
        self.refresh_tree()
        scenes = project.scene_names()
        if scenes:
            start = project.start if project.start in scenes else scenes[0]
            # the script opens; a document-only scene opens its document
            script = project.scene_script(start)
            self.open_file(script or project.scenes_dir / f"{start}.scene",
                           switch=False)
            self.preview.arm(start)      # the scene is chosen, not running
            self.tab = TAB_SCENE
        else:
            self.tab = TAB_CODE
        self.status = f"project {project.name}"
        self.log(f"opened {project.path}", "ok")
        self.log(f"{project.title}: start {project.start or '-'}; "
                 f"{len(scenes)} scene(s), {len(project.object_names())} "
                 f"object(s), {len(project.model_names())} model(s), "
                 f"{len(project.texture_files())} texture(s), "
                 f"{len(project.audio_files())} audio, "
                 f"{len(project.shader_names())} shader(s)", "muted")
        if project.legacy:
            # nothing is written on open; warn about saving
            self.log(f"manifest format {project.file_format} - saving will "
                     f"upgrade it to format {project.FORMAT}", "warn")
        return True

    def open_manager(self):
        """Save open files and return to the project list."""
        if self.project is not None:
            self.flush_code()
            if self.model.dirty:
                self.model.autosave()
            if self.doctab.dirty:
                self.doctab.save_all()
        self.media.pause()
        self.preview.blur()
        try:
            self.audio.stop_all()
        except Exception:
            pass
        self.menu_open = None
        self.menu_rows = []
        self.manager.refresh()
        self.mode = "manager"
        self.status = "project manager"
        self.log("project manager", "muted")

    def select_asset(self, path):
        self.selected_asset = Path(path) if path is not None else None

    def activate_asset(self, path):
        self.selected_asset = Path(path)
        return self.open_file(path)

    def reload_project(self):
        if self.project is None:
            return
        self.project.reload_models()
        self.preview.set_project(self.project)
        self.assets.set_project(self.project)
        self.media.refresh()
        self.projecttab.refresh()
        self.model.refresh_textures()
        if self.model.path:
            self.model.open(self.model.path)
        self.refresh_tree()
        self.status = "project reloaded"
        self.log("project reloaded (models, scenes, manifest)", "ok")

    def refresh_tree(self):
        if self.project is None:
            self.scene_tree.set_rows([])
            self.file_tree.set_rows([])
            return
        self.scene_tree.set_rows(self._scene_rows(self.project))
        self.file_tree.set_rows(self._file_rows(self.project))

    def _scene_rows(self, p):
        """The Scene list: documents and the nodes they place."""
        rows = [{"kind": "root", "label": p.title, "depth": 0,
                 "path": p.path, "key": "root", "icon": "icon"}]
        for name in p.scene_names():
            path = p.scenes_dir / f"{name}.scene"
            label = path.name + ("   (start)" if name == p.start else "")
            doc = p.scene_doc(name)
            roots = scenedoc.roots(doc) if doc else []
            opened = self.node_open.get(f"scene:{name}", True)
            rows.append({"kind": "scene", "label": label, "depth": 1,
                         "path": path, "key": f"scene:{name}",
                         "scene": name, "icon": doc_icon(path),
                         "open": opened, "has": bool(roots),
                         "fold": f"scene:{name}"})
            if opened:
                self._node_rows(p, roots, name, 2, rows)
        return rows

    def _node_rows(self, p, entries, scope, depth, rows):
        """Append one level of a document's placed nodes, then descend."""
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("id") is None:
                continue
            eid = str(entry.get("id"))
            inst = scenedoc.is_instance(entry)
            kids = [] if inst else scenedoc.children(entry)
            sdoc = None
            label = eid
            if inst:
                value, is_scene = scenedoc.instance_source(entry)
                label = f"{Path(str(value)).stem} (instance)"
                spath = scenedoc.resolve_instance(p, value)
                if spath is not None:
                    sdoc = scenedoc.load(
                        spath, "scene" if is_scene else "object")
            grafted = scenedoc.roots(sdoc) if sdoc is not None else []
            opened = self.node_open.get(f"{scope}:{eid}", True)
            rows.append({"kind": "node", "label": label, "depth": depth,
                         "key": f"node:{scope}:{eid}", "scene": scope,
                         "node": eid, "open": opened,
                         "fold": f"{scope}:{eid}",
                         "has": bool(kids) or bool(grafted),
                         "icon": widgets.node_icon(entry.get("type"))})
            if not opened:
                continue
            self._node_rows(p, kids, scope, depth + 1, rows)
            if sdoc is None:
                continue
            for centry, _cp, cdepth in scenedoc.walk(sdoc):
                cid = centry.get("id")
                if cid is None:
                    continue
                full = f"{eid}/{cid}"
                rows.append({"kind": "node", "label": str(cid),
                             "depth": depth + 1 + cdepth,
                             "key": f"node:{scope}:{full}",
                             "scene": scope, "node": full,
                             "icon": widgets.node_icon(centry.get("type"))})

    def _file_rows(self, p):
        """The Project View: two folder bands and their files."""
        rows = [{"kind": "root", "label": p.title, "depth": 0,
                 "path": p.path, "key": "root", "icon": "icon"}]
        for name in (META_NAME, INPUT_NAME, ASSET_NAME):
            path = p.path / name
            if path.is_file():
                rows.append({"kind": "file", "label": name, "depth": 1,
                             "path": path, "key": str(path),
                             "icon": file_row_icon(path)})
        for title, names in TREE_BANDS:
            rows.append({"kind": "section", "label": title, "depth": 1,
                         "key": f"section:{title}"})
            for kind in names:
                files = p.files(kind)
                opened = self.folder_open.get(kind, True)
                rows.append({"kind": "folder",
                             "label": f"{kind} ({len(files)})",
                             "depth": 1, "path": p.dir(kind),
                             "open": opened, "key": kind,
                             "create": FOLDER_CREATE.get(kind)})
                if not opened:
                    continue
                for f in files:
                    stray = kind in ("scenes", "objects") and \
                        f.suffix.lower() == ".py"
                    label = f.name + (STRAY_LABEL if stray else "")
                    row = {"kind": "file", "label": label,
                           "depth": 2, "path": f, "key": str(f),
                           "icon": "warning-sym" if stray
                           else file_row_icon(f)}
                    rows.append(row)
                    if stray or kind != "objects" or \
                            f.suffix.lower() not in scenedoc.OBJECT_EXTS:
                        continue
                    # an object document owns a branch, folding like a scene
                    scope = f"object:{f.stem}"
                    doc = p.object_doc(f.stem)
                    roots = scenedoc.roots(doc) if doc else []
                    opened = self.node_open.get(scope, True)
                    row["open"] = opened
                    row["has"] = bool(roots)
                    row["fold"] = scope
                    if opened:
                        self._node_rows(p, roots, scope, 3, rows)
                if kind == "scripts":
                    rows.extend(self._code_rows(p, 2))
        return rows

    def _code_rows(self, p, depth):
        """`scripts/scenes`, `scripts/objects` and `scripts/shaders`: the"""
        rows = []
        for sub in ("scenes", "objects", "shaders"):
            key = f"scripts/{sub}"
            d = p.dir(key)
            files = sorted(x for x in d.iterdir() if x.is_file())
            opened = self.folder_open.get(key, True)
            rows.append({"kind": "folder", "label": f"{sub} ({len(files)})",
                         "depth": depth, "path": d, "open": opened,
                         "key": key, "create": FOLDER_CREATE.get(key)})
            if not opened:
                continue
            for f in files:
                rows.append({"kind": "file", "label": f.name,
                             "depth": depth + 1, "path": f,
                             "key": str(f), "icon": file_row_icon(f)})
        return rows

    def open_file(self, path, switch=True):
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".py":
            if self.model.dirty:
                self.model.autosave()
            if str(path) != self.code.path:
                if self.code.dirty:
                    if self.autosave and not self.code.save():
                        return False
                    self.code.park()     # held in memory, not written
                if not self.code.open(path):
                    return False
            if switch:
                self.show_python()
            self.status = f"editing {path.name}"
            return True
        if suffix == scenedoc.SCENE_EXT or suffix in scenedoc.OBJECT_EXTS:
            # a document gets its own tab; raw JSON on right-click
            if self.model.dirty:
                self.model.autosave()
            if self.doctab.open(path):
                if switch:
                    self.set_tab(TAB_DOC)
                self.status = f"document {path.name}"
                return True
            # no project yet: keep the text view
            if not self.code.open(path):
                return False
            if switch:
                self.set_tab(TAB_CODE)
            self.status = f"document {path.name}"
            return True
        if suffix == scenedoc.SHADER_EXT:
            # a shader document shows JSON until a panel exists
            if self.model.dirty:
                self.model.autosave()
            if not self.code.open(path):
                return False
            if switch:
                self.set_tab(TAB_CODE)
            self.status = f"shader {path.name}"
            return True
        if suffix in (scenedoc.MODEL3D_EXT, scenedoc.MODEL_EXT,
                      scenedoc.MODEL2D_EXT, scenedoc.MAP3D_EXT):
            # both model halves open in Model, chosen by suffix
            if self.code.dirty:
                self.code.save()
            if self.model.open(path):
                self.select_asset(path)
                if switch:
                    self.set_tab(TAB_MODEL)
                self.status = f"model {path.name}"
                return True
            return False
        if suffix in AUDIO_EXT:
            self.media.load(path)
            self.select_asset(path)
            if switch:
                self.set_tab(TAB_AUDIO)
            self.status = f"audio {path.name}"
            return True
        if suffix in IMAGE_EXT:
            self.select_asset(path)
            if switch:
                self.set_tab(TAB_ASSETS)
            self.status = f"texture {path.name}"
            return True
        if suffix == ".flig" or path.name == INPUT_NAME:
            # the manifest and its input map are one form, on the Project tab
            self.select_asset(path)
            if switch:
                self.set_tab(TAB_PROJECT)
            self.status = path.name
            return True
        if path.name == ASSET_NAME:
            self.select_asset(path)
            if switch:
                self.set_tab(TAB_ASSETS)
            self.status = path.name
            return True
        self.log(f"{path.name}: open it with an external program", "muted")
        return False

    def open_raw(self, path):
        """Show a document's raw JSON in the Code tab."""
        path = Path(path)
        if self.code.dirty and str(self.code.path or "") != str(path):
            if self.autosave and not self.code.save():
                return False
            self.code.park()
        if not self.code.open(path):
            return False
        self.set_tab(TAB_CODE)
        self.status = f"raw {path.name}"
        return True

    def set_tab(self, index):
        index = max(0, min(len(TAB_LABELS) - 1, int(index)))
        if index == self.tab:
            return
        if self.tab == TAB_CODE and self.code.dirty:
            self.flush_code()
        elif self.tab == TAB_MODEL and self.model.dirty:
            self.model.autosave()
        elif self.tab == TAB_DOC and self.doctab.dirty and self.autosave:
            self.doctab.save_all()
        if self.tab == TAB_SCENE:
            self.preview.blur()
        if self.tab == TAB_AUDIO:
            self.media.pause()
        if self.tab == TAB_BUILD:
            self.build.config.store()
        self.tab = index
        if index == TAB_BLOCKS:
            self.blocks.sync()          # show the file the editor is on
        self.status = f"{TAB_LABELS[index]} tab"

    def show_code(self):
        """Put the current file in front of the Text view."""
        self.set_tab(TAB_CODE)

    def show_python(self):
        """Open the view a `.py` wants, per `editor.open_as`."""
        if self.open_as == "blocks":
            self.set_tab(TAB_BLOCKS)
            return
        if self.open_as == "ask":
            self.dialog_kind = f"open_as:{self.code.path}"
            self.dialog = widgets.ChoiceDialog(
                "Open as Text or Blocks", "Both edit the same Python file.",
                ("Blocks", "Text"),
                hint="Blocks shows the file as a graph of nodes; Settings "
                     "can make either one the default and stop the asking. "
                     "Esc or Enter opens it as Text.",
                default=1)
            return
        self.set_tab(TAB_CODE)

    def save_current(self):
        was = str(self.code.path) if self.tab in (TAB_CODE, TAB_BLOCKS) \
            else ""
        if self.tab == TAB_CODE:
            self.code.save()
        elif self.tab == TAB_DOC:
            if self.doctab.save():
                self._maybe_hot_reload(str(self.doctab.current().path))
        elif self.tab == TAB_BLOCKS:
            self.blocks.save()
        elif self.tab == TAB_SETTINGS:
            self.settings.commit()
        elif self.tab == TAB_PROJECT:
            self.projecttab.save()
        elif self.tab == TAB_MODEL:
            self.model.save()
        elif self.tab == TAB_BUILD and self.project is not None:
            self.build.config.store()
            self.log("build options saved", "ok")
        elif self.project is not None:
            self.project.save_meta()
            self.log("manifest saved", "ok")
        if was and self.hot_reload_save:
            # hot reload: a saved script re-runs the preview behind you
            self._maybe_hot_reload(was)

    def _maybe_hot_reload(self, path):
        """Reload the preview when a watched project file is saved."""
        if self.project is None or not path:
            return False
        try:
            p = Path(path)
            folder = p.parent.relative_to(self.project.path).parts[0] \
                if p.parent != self.project.path else ""
        except (OSError, IndexError, ValueError):
            return False
        if folder not in self.project.WATCHED:
            return False
        self.preview.reload()
        self.status = f"preview reloaded {self.project.relative(path)}"
        self.log(f"hot reload: {self.project.relative(path)}", "muted")
        return True

    def reset_watch(self):
        """Take the file-watch snapshot a hot reload compares against."""
        self._watch = self.project.snapshot() if self.project else None
        self._watch_at = time.time()

    def _watch_tick(self):
        """Hot reload: a script changed on disk, in this project."""
        if self.project is None or not self.hot_reload_watch:
            return False
        now = time.time()
        if now - self._watch_at < 2.0:
            return False
        self._watch_at = now
        if self._watch is None:
            self._watch = self.project.snapshot()
            return False
        changed, self._watch = self.project.changed_since(self._watch)
        if not changed:
            return False
        if self.preview.pending is not None:
            return False                # a reload is already on its way
        key = self.project.relative(changed[0])
        self.preview.reload()
        self.log(f"hot reload: {key} "
                 f"({len(changed)} file(s) changed on disk)", "muted")
        return True

    def _prompt(self, kind):
        if kind in _CREATE_KINDS and self.project is not None:
            # the unified New dialog asks name, kind, model and texture
            self.dialog_kind = "create"
            self.dialog = widgets.CreateDialog(self.project, kind,
                                               width=470)
            return
        preset = OBJECT_PRESETS.get(kind) or SCENE_PRESETS.get(kind)
        if preset is not None:
            # the loader's table owns preset wording, so add one entry
            self.dialog_kind = kind
            self.dialog = widgets.PromptDialog(
                preset[3], "Name (file stem)", preset[2], hint=preset[4],
                width=470)
            return
        spec = {
            "new_project": ("New Project", "Project folder name",
                            "my_game", "Created in emoeng/projects"),
            "open_folder": ("Open Project", "Project folder or path", "",
                            "A folder containing project.flig; relative "
                            "paths resolve in emoeng/projects"),
            "new_model": ("New Model", "Model name (file stem)", "prop",
                          f"Adds models/<name>{scenedoc.MODEL3D_EXT} and "
                          "opens the model tab"),
            "new_model_2d": ("New 2D Model", "Model name (file stem)",
                             "sprite",
                             f"Adds models/<name>{scenedoc.MODEL2D_EXT} - a "
                             "flat cutout rig - and opens the model tab"),
            "new_script": ("New Script", "Script name (file stem)", "helpers",
                           "Adds scripts/<name>.py"),
            "new_shader": ("New Shader", "Shader name (file stem)", "ripple",
                           "Adds scripts/shaders/<name>.py and "
                           f"<name>{scenedoc.SHADER_EXT} - the stock look "
                           "chosen in the dialog is written into both"),
        }
        title, label, value, hint = spec[kind]
        self.dialog_kind = kind
        extra = {}
        if kind == "new_project":
            # a new folder starts from a starter template
            extra = {
                "choices": [(key, templates.spec(key)["title"])
                            for key in templates.template_names()],
                "choice_label": "Starter",
                "hint": "Its scene, object, models and window are "
                        "written into the new folder",
            }
        self.dialog = widgets.PromptDialog(title, label, value, hint=hint,
                                           width=430, **extra)

    def prompt_project_rename(self, path, name):
        """The manager's Rename button: give the selected project a new"""
        self.dialog_kind = f"project_rename:{path}"
        self.dialog = widgets.PromptDialog(
            "Rename Project", "New folder name", name,
            hint="Renames the folder holding project.flig and updates "
                 "the name the manifest carries", width=430)

    def prompt_project_icon(self, path):
        """The manager's Set Icon button: pick an image."""
        self.dialog_kind = f"project_icon:{path}"
        self.dialog = widgets.PromptDialog(
            "Project Icon", "Image file path", "",
            hint="A PNG or JPG copied beside project.flig as icon.png - "
                 "it becomes the row badge, the window icon and the "
                 "compiled exe icon; empty clears it", width=430)

    def _rename_project(self, old, text):
        """Rename a closed project's folder and restate its manifest."""
        stem = clean_stem(str(text or "").strip(), "")
        if not stem:
            return
        if self.project is not None and self.project.path == old:
            self.log("close the project before renaming it", "warn")
            return
        new = old.with_name(stem)
        if new == old:
            return
        if new.exists():
            self.log(f"{stem} already exists", "warn")
            return
        try:
            old.rename(new)
        except OSError as exc:
            self.log(f"rename failed: {exc}", "error")
            return
        manifest = new / META_NAME
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "name" in raw:
                raw["name"] = stem
                manifest.write_text(json.dumps(raw, indent=1),
                                    encoding="utf-8")
        except (OSError, ValueError) as exc:
            self.log(f"renamed, but the manifest needs a look: {exc}",
                     "warn")
        self.manager.recent = [str(new) if p == str(old) else p
                               for p in self.manager.recent]
        self.manager.refresh()
        self.log(f"project renamed: {old.name} -> {stem}", "ok")

    def _set_project_icon(self, path, text):
        """Copy the named image into `icon.png` beside the manifest,"""
        dest = path / const.ICON_NAME
        raw = str(text or "").strip().strip('"')
        if not raw:
            try:
                dest.unlink()
                self.log("project icon cleared", "ok")
            except FileNotFoundError:
                self.log("this project has no icon to clear", "warn")
            except OSError as exc:
                self.log(f"cannot clear icon: {exc}", "error")
            self.manager.refresh()
            return
        src = Path(raw).expanduser()
        if not src.is_file():
            self.log(f"no such image: {src}", "error")
            return
        try:
            art = pygame.image.load(str(src))
            try:
                art = art.convert_alpha()
            except pygame.error:
                pass
            w, h = art.get_size()
            k = 64.0 / max(1, max(w, h))
            art = pygame.transform.smoothscale(art, (max(1, int(w * k)),
                                                     max(1, int(h * k))))
            sheet = pygame.Surface((64, 64), pygame.SRCALPHA)
            sheet.blit(art, ((64 - art.get_width()) // 2,
                             (64 - art.get_height()) // 2))
            pygame.image.save(sheet, str(dest))
        except (OSError, ValueError, pygame.error) as exc:
            self.log(f"cannot make icon: {exc}", "error")
            return
        self.log(f"project icon set: {dest}", "ok")
        self.manager.refresh()

    def open_node_picker(self, rows, target):
        """Godot's Create New Node dialog, aimed at whichever tab asked."""
        self.dialog_kind = "addnode"
        self.dialog_target = target
        self.dialog = widgets.NodeDialog(rows)

    def prompt_build_option(self, key, flag, value, hint):
        """One-line editor for a Build-tab value; routed in _dialog_ok."""
        self.dialog_kind = f"build:{key}"
        self.dialog = widgets.PromptDialog(
            f"Build option {flag}", "Value (use ; between list entries)",
            value, hint=hint, width=470)

    def _dialog_ok(self, kind, text):
        if kind == "color":
            cb, self.dialog_color_ok = self.dialog_color_ok, None
            if cb is not None:
                cb(text or "")
            return
        if kind and kind.startswith("setting:"):
            key = kind.split(":", 1)[1]
            entry = config.BY_KEY.get(key)
            if entry is not None:
                self.settings.apply(entry, text)
            return
        if kind and kind.startswith("open_as:"):
            path = kind.split(":", 1)[1]
            if str(self.code.path) != path:
                return            # a different file got opened since the ask
            if text == "Blocks" and not self.blocks.readonly():
                self.set_tab(TAB_BLOCKS)
            elif text == "Blocks":
                self.log("blocks: that file does not read as blocks - "
                         "opening it as Text", "warn")
                self.set_tab(TAB_CODE)
            else:
                self.set_tab(TAB_CODE)
            return
        if kind == "quit":
            if text == "Save and quit":
                self.code.save()
                self.model.save()
            elif text == "Quit anyway":
                # drop the dirty flags so shutdown leaves the files
                self.code.dirty = False
                self.model.dirty = False
            else:
                return
            self.running = False
            return
        if kind and kind.startswith("build:"):
            key = kind.split(":", 1)[1]
            self.build.config.set_from_text(key, text)
            self.log(f"build {key} = {self.build.config.get(key)!r}", "ok")
            self.status = f"build {key}"
            return
        if kind == "create":
            self._do_create(text or {})
            return
        if kind == "addnode":
            # the Create Node dialog routes its payload to the opener
            payload = text or {}
            if self.project is None:
                return
            dest = self.preview if self.dialog_target == "preview" \
                else self.doctab
            if payload.get("inst"):
                dest.instantiate(payload["inst"])
            elif payload.get("type"):
                dest.add_node(payload["type"])
            return
        if kind and kind.startswith("rename:"):
            self._do_rename(Path(kind.split(":", 1)[1]), text)
            return
        if kind and kind.startswith("delete:"):
            if text == "Delete":
                self._do_delete(Path(kind.split(":", 1)[1]))
            return
        if kind == "import_path":
            raw = str(text or "").strip().strip('"')
            if raw:
                self._do_import([Path(raw)])
            return
        if kind == "new_project":
            # the dialog answers a name and a starter template together
            payload = text if isinstance(text, dict) else {}
            raw = str(payload.get("name") if payload else text or "")
            stem = clean_stem(raw, "my_game")
            path = PROJECTS / stem
            if path.exists():
                self.log(f"{stem} already exists", "warn")
                return
            try:
                Project.create(path, title=raw.strip() or stem,
                               template=payload.get("choice")
                               or templates.DEFAULT_TEMPLATE)
            except Exception as exc:
                self.log(f"cannot create project: {exc}", "error")
                return
            self.open_project(path)
            return
        if kind and kind.startswith("project_rename:"):
            self._rename_project(Path(kind.split(":", 1)[1]), text)
            return
        if kind and kind.startswith("project_icon:"):
            self._set_project_icon(Path(kind.split(":", 1)[1]), text)
            return
        if kind and kind.startswith("project:"):
            # the Project tab's own dialogs: a row, a scene, a trigger name
            if self.projecttab._answer(kind.split(":", 1)[1], text):
                self.status = "project edited; press Save"
            return
        if kind == "open_folder":
            raw = text.strip().strip('"')
            if not raw:
                return
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = PROJECTS / path
            if not (path / META_NAME).exists():
                self.log(f"no {META_NAME} in {path}", "error")
                return
            self.open_project(path)
            return
        if self.project is None:
            self.log("open a project first", "warn")
            return
        stem = clean_stem(text, kind)
        if kind in SCENE_PRESETS:
            self._new_scene(kind, stem)
        elif kind in OBJECT_PRESETS:
            self._new_object(kind, stem)
        elif kind == "new_script":
            self._new_script(stem)
        elif kind == "new_shader":
            self._new_shader(stem)
        elif kind == "new_model":
            self._new_model(stem)
        elif kind == "new_model_2d":
            self._new_model_2d(stem)

    def _new_script(self, stem):
        """Write a shared helper module under `scripts/`."""
        p = self.project.scripts_dir / f"{stem}.py"
        if p.exists():
            self.log(f"scripts/{p.name} already exists", "warn")
            return
        p.write_text(SCRIPT_TEMPLATE, encoding="utf-8")
        self.refresh_tree()
        self.open_file(p)

    def _new_model(self, stem, texture="grid"):
        """Create a solid model, opened in the Model tab."""
        model = modelmod.new_model("box", 1.0, texture=texture, name=stem)
        path = self.project.store_model(model, stem)
        self.refresh_tree()
        self.model.open(path)
        self.set_tab(TAB_MODEL)
        self.log(f"created models/{stem}{path.suffix}", "ok")

    def _new_model_2d(self, stem):
        """Create a flat cutout rig, opened in Model."""
        p = self.project.models_dir / f"{stem}{scenedoc.MODEL2D_EXT}"
        if p.exists():
            self.log(f"models/{p.name} already exists", "warn")
            return
        doc = modelmod.new_model2d(stem)
        path = self.project.store_model2d(doc, stem)
        self.refresh_tree()
        self.model.open(path)
        self.set_tab(TAB_MODEL)
        self.log(f"created models/{stem}{scenedoc.MODEL2D_EXT}", "ok")

    def _new_scene(self, kind, stem, model=None, texture=None):
        """Write a scene's script and its document."""
        doc_kind, template, _stem, _title, _hint = SCENE_PRESETS[kind]
        script = self.project.scene_scripts_dir / f"{stem}.py"
        if script.exists():
            self.log(f"scripts/scenes/{script.name} already exists", "warn")
            return
        script.write_text(template, encoding="utf-8")
        doc = scenedoc.blank_scene(
            stem, doc_kind,
            scenedoc.script_field("scripts/scenes", script.name))
        self.project.save_scene_doc(stem, doc)
        self.refresh_tree()
        self.open_file(script)
        self.log(f"created scripts/scenes/{script.name} + {stem}.scene",
                 "ok")

    def _new_object(self, kind, stem, model=None, texture=None):
        """Write an object's script and the document that places it."""
        doc_kind, template, _stem, _title, _hint = OBJECT_PRESETS[kind]
        script = self.project.object_scripts_dir / f"{stem}.py"
        if script.exists():
            self.log(f"scripts/objects/{script.name} already exists",
                     "warn")
            return
        script.write_text(template, encoding="utf-8")
        doc = scenedoc.blank_object(
            stem, doc_kind,
            scenedoc.script_field("scripts/objects", script.name))
        if doc_kind in ("screen3d", "screen2d") and self.project.start:
            # a new screen shows nothing until it is told what
            doc["showing"] = self.project.start
        if model:
            doc["model"] = Path(str(model)).stem
        if texture:
            doc["texture"] = Path(str(texture)).stem
        self.project.save_object_doc(stem, doc)
        self.project.reload_objects()
        self.refresh_tree()
        self.open_file(script)
        self.log(f"created scripts/objects/{script.name} + "
                 f"{stem}{scenedoc.object_ext(doc_kind)}", "ok")

    def _new_shader(self, stem, template=None):
        """Write a shader's script and the `.shader` document beside it."""
        key = str(template or "")
        if key not in SHADER_PRESETS:
            key = next(iter(SHADER_PRESETS), "")
        if not key:
            self.log("no stock shader to copy", "error")
            return
        mode = SHADER_PRESETS[key][0]
        script = self.project.shader_scripts_dir / f"{stem}.py"
        if script.exists():
            self.log(f"scripts/shaders/{script.name} already exists",
                     "warn")
            return
        script.write_text(templates.shader_source(key, stem),
                          encoding="utf-8")
        doc = scenedoc.blank_shader(
            stem, mode,
            scenedoc.script_field("scripts/shaders", script.name),
            knobs=dict(templates.SHADERS[key][1]))
        self.project.save_shader_doc(stem, doc)
        self.refresh_tree()
        self.open_file(script)
        self.log(f"created scripts/shaders/{script.name} + "
                 f"{stem}{scenedoc.SHADER_EXT} ({mode}, from {key})", "ok")

    def _do_create(self, payload):
        """Write the files a CreateDialog answered for."""
        if self.project is None:
            self.log("open a project first", "warn")
            return
        kind = payload.get("kind")
        stem = clean_stem(payload.get("name"), kind or "untitled")
        model = payload.get("model")
        texture = payload.get("texture")
        if kind in SCENE_PRESETS:
            self._new_scene(kind, stem, model=model, texture=texture)
        elif kind in OBJECT_PRESETS:
            self._new_object(kind, stem, model=model, texture=texture)
        elif kind == "new_script":
            self._new_script(stem)
        elif kind == "new_shader":
            self._new_shader(stem, payload.get("template"))
        elif kind == "new_model":
            self._new_model(stem, texture=texture or "grid")
        elif kind == "new_model_2d":
            self._new_model_2d(stem)
        else:
            self.log(f"cannot create a {kind}", "warn")

    def import_dialog(self, folder=None):
        """Open the chooser and copy its picks in."""
        if self.project is None:
            self.log("open a project first", "warn")
            return
        picked = importer.browse("Import asset", importer.FILETYPES)
        if not picked:
            self.dialog_kind = "import_path"
            self.dialog = widgets.PromptDialog(
                "Import asset", "File path to copy in", "",
                hint="Or drag files onto the editor window.", width=470)
            return
        self._do_import(picked)

    def _do_import(self, paths):
        """Copy the given external files into the project's asset folders."""
        if self.project is None:
            return
        made, staged = importer.import_files(self.project, paths)
        if self.assets is not None:
            self.assets._thumbs = {}
        self.refresh_tree()
        if made:
            self.log(f"imported {len(made)} file(s)", "ok")
        if staged:
            self.log(f"staged {len(staged)} file(s) under "
                     f"{importer.RAW_SUBDIR.as_posix()} (not an engine "
                     "asset)", "warn")
        if not made and not staged:
            self.log("nothing imported", "warn")

    def _can_open(self, path):
        """Does Open have somewhere to take this file?"""
        suffix = path.suffix.lower()
        return suffix == ".py" or scenedoc.kind_of(path) is not None or \
            suffix in (scenedoc.MODEL3D_EXT, scenedoc.MODEL_EXT,
                       scenedoc.MODEL2D_EXT,
                       scenedoc.MAP3D_EXT) or suffix in IMAGE_EXT or \
            suffix in AUDIO_EXT or suffix == ".flig" or \
            path.name in (META_NAME, INPUT_NAME, ASSET_NAME)

    def _file_actions(self, path):
        """The right-click rows for one file."""
        acts = []
        if self._can_open(path):
            acts.append(("open", "Open"))
        kind = scenedoc.kind_of(path)
        if kind is not None:
            acts.append(("raw", "View raw JSON"))
            if kind != "shader":
                # a look is worn, not placed: absent from Add
                acts.append(("add_scene", "Add to current scene"))
        acts.append(("rename", "Rename..."))
        acts.append(("duplicate", "Duplicate"))
        acts.append(("reveal", "Reveal in Explorer"))
        acts.append(("copy_path", "Copy path"))
        acts.append(("delete", "Delete"))
        return acts

    def _folder_actions(self, path):
        """A folder row takes an import and two path actions."""
        return [("import", "Import..."),
                ("reveal", "Reveal in Explorer"),
                ("copy_path", "Copy path")]

    def show_file_menu(self, path, pos):
        """Open the file context menu over `pos` (shared with the"""
        self.ctx_menu = {"path": Path(path), "x": pos[0], "y": pos[1],
                         "actions": self._file_actions(Path(path))}

    def show_folder_menu(self, path, pos):
        self.ctx_menu = {"path": Path(path), "x": pos[0], "y": pos[1],
                         "actions": self._folder_actions(Path(path))}

    def _run_ctx(self, action, path):
        """Do what a context-menu row asked, on its file."""
        if action == "open":
            self.open_file(path)
        elif action == "raw":
            self.open_raw(path)
        elif action == "add_scene":
            self.add_doc_to_scene(path)
        elif action == "rename":
            self.file_rename(path)
        elif action == "duplicate":
            self.file_duplicate(path)
        elif action == "delete":
            self.file_delete(path)
        elif action == "reveal":
            self.reveal_path(path)
        elif action == "copy_path":
            self.copy_path(path)
        elif action == "import":
            self.import_dialog(path)

    def _ensure_scene_open(self):
        """Bring a scene document forward so instances have a home."""
        tab = self.doctab.current()
        if tab is not None and tab.kind == "scene":
            return True
        names = self.project.scene_names() if self.project else []
        if not names:
            self.log("this project has no scene to add to", "warn")
            return False
        name = (self.project.start if self.project.start in names
                else names[0])
        path = scenedoc.find_doc(self.project.scenes_dir, name, "scene")
        if path is None:
            path = self.project.scenes_dir / f"{name}{scenedoc.SCENE_EXT}"
        if not self.doctab.open(path):
            self.log("cannot open the scene document", "warn")
            return False
        self.set_tab(TAB_DOC)
        return True

    def add_doc_to_scene(self, path):
        """Instance a document as a child of the scene."""
        path = Path(path)
        if self.project is None:
            return False
        if scenedoc.kind_of(path) is None:
            self.log("only scene or object files can be instanced", "warn")
            return False
        if not self._ensure_scene_open():
            return False
        rel = self.project.relative(path).replace("\\", "/")
        if not self.doctab.instantiate(rel):
            return False
        self.doctab.save()
        return True

    def file_rename(self, path):
        """Ask for a new stem, then rename and re-point references."""
        path = Path(path)
        if self.project is None or not path.is_file():
            return
        self.dialog_kind = f"rename:{path}"
        self.dialog = widgets.PromptDialog(
            "Rename", "New name (file stem)", path.stem,
            hint="The file is renamed and any document that points at "
                 "it is updated.", width=440)

    def _do_rename(self, path, new_stem):
        path = Path(path)
        if self.project is None or not path.is_file():
            return
        stem = clean_stem(new_stem, path.stem)
        dest = path.with_name(f"{stem}{path.suffix}")
        if str(dest) == str(path):
            return
        if dest.exists():
            self.log(f"{dest.name} already exists", "warn")
            return
        try:
            path.rename(dest)
        except OSError as exc:
            self.log(f"cannot rename {path.name}: {exc}", "error")
            return
        kind = scenedoc.kind_of(dest)
        if kind is not None:
            doc = scenedoc.load(dest, kind)
            if str(doc.get("name") or "") == path.stem:
                doc["name"] = stem
                scenedoc.save(dest, doc)
        changed = self._rewrite_references(path, dest)
        self._forget_tab(path)
        self.refresh_tree()
        note = f" ({changed} reference(s) updated)" if changed else ""
        self.log(f"renamed to {dest.name}{note}", "ok")

    def file_duplicate(self, path):
        """Copy a file beside itself; a document copy stands alone."""
        path = Path(path)
        if self.project is None or not path.is_file():
            return False
        dest = importer._unique(
            path.with_name(f"{path.stem}_copy{path.suffix}"))
        try:
            shutil.copy2(path, dest)
        except OSError as exc:
            self.log(f"cannot duplicate {path.name}: {exc}", "error")
            return False
        kind = scenedoc.kind_of(dest)
        if kind is not None:
            doc = scenedoc.load(dest, kind)
            doc["name"] = dest.stem
            scenedoc.save(dest, doc)
        self.refresh_tree()
        self.log(f"duplicated to {self.relative(dest)}", "ok")
        return True

    def file_delete(self, path):
        """Confirm a delete, refusing while files still reference it."""
        path = Path(path)
        if self.project is None or not path.exists():
            return
        hits = sorted({d for (d, _e, k, v) in self._all_references()
                       if self._points_at(k, v, path)})
        if hits:
            names = ", ".join(self.relative(h) for h in hits[:6])
            if len(hits) > 6:
                names += f", +{len(hits) - 6} more"
            self.notice = ("Still in use",
                           [f"{path.name} is referenced by:", names,
                            "Remove those references before deleting."])
            self.log(f"delete blocked: {path.name} is used by "
                     f"{len(hits)} file(s)", "warn")
            return
        self.dialog_kind = f"delete:{path}"
        self.dialog = widgets.ChoiceDialog(
            "Delete file", f"Delete {path.name} from the project?",
            ("Delete", "Cancel"),
            hint="The file is removed from disk. This cannot be undone.",
            default=1)

    def _do_delete(self, path):
        path = Path(path)
        try:
            path.unlink()
        except OSError as exc:
            self.log(f"cannot delete {path.name}: {exc}", "error")
            return
        self._forget_tab(path)
        self.refresh_tree()
        self.log(f"deleted {self.relative(path)}", "ok")

    def reveal_path(self, path):
        """Open a file's folder in the OS file manager."""
        path = Path(path)
        target = path if path.is_dir() else path.parent
        try:
            if os.name == "nt":
                if path.is_file():
                    subprocess.Popen(["explorer", "/select,", str(path)])
                else:
                    os.startfile(str(target))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
            self.log(f"revealed {self.relative(path)}", "muted")
        except (OSError, ValueError) as exc:
            self.log(f"cannot reveal {path.name}: {exc}", "warn")

    def copy_path(self, path):
        """Copy a file's full path, or show it."""
        text = str(Path(path))
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            root.destroy()
            self.log(f"copied path: {text}", "ok")
            return True
        except Exception:
            self.notice = ("Path", [text])
            self.log(f"path: {text}", "muted")
            return False

    def _all_references(self):
        """[(doc_path, node_id, key, value)] for every field naming a file."""
        if self.project is None:
            return []
        out = []
        for kind in ("scenes", "objects"):
            for p in self.project.files(kind):
                dk = scenedoc.kind_of(p)
                if dk is None:
                    continue
                doc = scenedoc.load(p, dk)
                holders = [doc] + [e for e, _parent, _depth
                                   in scenedoc.walk(doc)]
                for holder in holders:
                    if not isinstance(holder, dict):
                        continue
                    eid = str(holder.get("id") or "")
                    for key in ("object", "scene", "script", "model",
                                "texture", "showing"):
                        value = holder.get(key)
                        if isinstance(value, str) and value:
                            out.append((p, eid, key, value))
        return out

    def _points_at(self, key, value, path):
        """Does a document field of this key name that file?"""
        path = Path(path)
        v = str(value).replace("\\", "/")
        rel = self.project.relative(path).replace("\\", "/")
        if key in ("object", "scene"):
            if scenedoc.instance_field(value) == rel:
                return True
            found = scenedoc.resolve_instance(self.project, value)
            return found is not None and \
                str(found.resolve()) == str(path.resolve())
        if v.lower() == rel.lower():
            return True
        if key == "script":
            sp = self.project.script_path(value)
            return sp is not None and \
                str(Path(sp).resolve()) == str(path.resolve())
        folder = path.parent.name.lower()
        stem = path.stem.lower()
        if key == "model" and folder == "models":
            return Path(v).stem.lower() == stem
        if key == "texture" and folder == "textures":
            return Path(v).stem.lower() == stem
        if key == "showing" and folder == "scenes":
            return Path(v).stem.lower() == stem
        return False

    def _new_reference(self, key, old, new):
        """The value replacing an old reference after a rename."""
        new = Path(new)
        rel = self.project.relative(new).replace("\\", "/")
        if key in ("object", "scene"):
            return scenedoc.instance_field(rel)
        if key == "script":
            folder = self.project.relative(new.parent).replace("\\", "/")
            return scenedoc.script_field(folder, new.name)
        return new.stem                         # model / texture / showing

    def _rewrite_references(self, old, new):
        """Re-point every document that names `old` at `new`; count them."""
        changed = 0
        for doc in {d for (d, _e, _k, _v) in self._all_references()}:
            if self._rewrite_doc(doc, old, new):
                changed += 1
                self._revert_tab(doc)
        return changed

    def _rewrite_doc(self, doc_path, old, new):
        doc_path = Path(doc_path)
        kind = scenedoc.kind_of(doc_path)
        if kind is None:
            return False
        doc = scenedoc.load(doc_path, kind)
        holders = [doc] + [e for e, _p, _d in scenedoc.walk(doc)]
        touched = False
        for holder in holders:
            if not isinstance(holder, dict):
                continue
            for key in ("object", "scene", "script", "model", "texture",
                        "showing"):
                value = holder.get(key)
                if isinstance(value, str) and value and \
                        self._points_at(key, value, old):
                    holder[key] = self._new_reference(key, old, new)
                    touched = True
        if touched:
            scenedoc.save(doc_path, doc)
        return touched

    def _revert_tab(self, path):
        """Re-read an open document tab from disk after a rewrite."""
        path = str(path)
        for tab in self.doctab.tabs:
            if str(tab.path) == path:
                tab.doc = scenedoc.load(tab.path, tab.kind)
                tab.sel = None
                tab.dirty = False

    def _forget_tab(self, path):
        """Drop a tab whose file was renamed or deleted."""
        path = str(path)
        keep = [t for t in self.doctab.tabs if str(t.path) != path]
        if len(keep) != len(self.doctab.tabs):
            self.doctab.tabs = keep
            self.doctab.active = min(self.doctab.active, len(keep) - 1)

    def run_game(self):
        if self.project is None:
            self.log("no project to run", "warn")
            return
        if self.process is not None and self.process.poll() is None:
            self.log("the game is already running", "warn")
            return
        if self.code.dirty:
            self.code.save()
        if self.model.dirty:
            self.model.autosave()
        base = ROOT.parent
        cmd = [sys.executable, "-m", "emoeng", "run",
               str(self.project.path)]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(base) + os.pathsep + \
            env.get("PYTHONPATH", "")
        try:
            self.process = subprocess.Popen(cmd, cwd=str(base), env=env)
        except Exception as exc:
            self.log(f"cannot start game: {exc}", "error")
            return
        self.log(f"running {self.project.name} in a new window", "ok")
        self.status = "game running"

    def _poll_process(self):
        if self.process is not None:
            code = self.process.poll()
            if code is not None:
                self.log(f"game exited (code {code})",
                         "ok" if code == 0 else "warn")
                self.process = None
                self.status = "game closed"

    def create_shortcut(self, project_path):
        """Drop a launcher for ``project_path`` on the current user's"""
        project_path = Path(project_path)
        if not (project_path / META_NAME).exists():
            self.log(f"no {META_NAME} in {project_path}", "error")
            return None
        title = project_path.name.replace("_", " ").title()
        title = read_meta(project_path).get("title") or title
        if paths.frozen():
            target = sys.executable
            args = ["--run", str(project_path)]
            cwd = str(Path(target).parent)
        else:
            base = ROOT.parent
            target = sys.executable
            args = ["-m", "emoeng", "--run", str(project_path)]
            cwd = str(base)
        desktop = _desktop_dir()
        try:
            if os.name == "nt":
                made = self._shortcut_windows(desktop, title, target,
                                              args, cwd)
            elif sys.platform == "darwin":
                made = self._shortcut_macos(desktop, title, target, args, cwd)
            else:
                made = self._shortcut_linux(desktop, title, target, args, cwd)
        except Exception as exc:
            self.log(f"shortcut failed: {exc}", "error")
            return None
        if made:
            self.log(f"shortcut created: {made}", "ok")
            self.status = f"shortcut for {title}"
        else:
            self.log("shortcut: nothing written", "warn")
        return made

    def _shortcut_windows(self, desktop, title, target, args, cwd):
        link = desktop / f"{clean_stem(title, 'project')}.lnk"
        argument_line = subprocess.list2cmdline(args)
        script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut({_ps_quote(link)}); "
            f"$s.TargetPath = {_ps_quote(target)}; "
            f"$s.Arguments = {_ps_quote(argument_line)}; "
            f"$s.WorkingDirectory = {_ps_quote(cwd)}; "
            "$s.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", script],
                       check=True, capture_output=True)
        return link

    def _shortcut_linux(self, desktop, title, target, args, cwd):
        stem = clean_stem(title, "project").lower()
        exec_line = " ".join(shlex.quote(a) for a in [target, *args])
        body = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            f"Name={title}\n"
            "GenericName=Motion Engine Project\n"
            "Comment=Launched by Motion Engine\n"
            f"Exec={exec_line}\n"
            f"Path={cwd}\n"
            "Terminal=false\n"
            "Categories=Game;Development;\n"
        )
        targets = []
        if desktop.is_dir():
            targets.append(desktop / f"{stem}.desktop")
        apps = Path.home() / ".local" / "share" / "applications"
        targets.append(apps / f"{stem}.desktop")
        made = None
        for p in targets:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
                p.chmod(0o755)
                if made is None:
                    made = p
            except OSError:
                continue
        return made

    def _shortcut_macos(self, desktop, title, target, args, cwd):
        stem = clean_stem(title, "project")
        script_path = desktop / f"{stem}.command"
        exec_line = " ".join(shlex.quote(a) for a in [target, *args])
        body = (
            "#!/bin/sh\n"
            f"cd {shlex.quote(cwd)} || exit 1\n"
            f"exec {exec_line}\n"
        )
        script_path.write_text(body, encoding="utf-8")
        script_path.chmod(0o755)
        return script_path

    def _menu_cells(self):
        cells, x = {}, 6
        for label in MENU_LABELS:
            width = self.fonts["normal"].size(label)[0] + 12
            cells[label] = pygame.Rect(x, CAP_H, width, MENU_H)
            x += width + 2
        return cells

    def _items_for(self, label):
        return MENUS[label]

    def _handle_menu_click(self, pos):
        """Press in the menu bar or an open panel.

        A row is only *armed* here and answered on release, which is what
        lets the press show as a press instead of the panel vanishing mid
        -click.
        """
        for label, rect in self._menu_cells().items():
            if rect.collidepoint(pos):
                index = MENU_LABELS.index(label)
                if self.menu_open == label:
                    self.menu_open = None
                    self.menu_flash = (index, pygame.time.get_ticks()
                                       + FLASH_MS)
                else:
                    self.menu_open = label
                self.menu_press_row = -1
                return True
        if self.menu_open:
            for i, (row, item) in enumerate(
                    zip(self.menu_rows, self._items_for(self.menu_open))):
                if row is not None and row.collidepoint(pos):
                    if item[1]:
                        self.menu_press_row = i
                    return True
            self.menu_open = None
            self.menu_press_row = -1
            return True
        return False

    def _handle_menu_release(self, pos):
        """Finish an armed dropdown row; leaving it before release cancels."""
        if self.menu_press_row < 0:
            return False
        index, self.menu_press_row = self.menu_press_row, -1
        if not self.menu_open:
            return True
        items = self._items_for(self.menu_open)
        answer = None
        if index < len(self.menu_rows) and \
                self.menu_rows[index] is not None and \
                self.menu_rows[index].collidepoint(pos) and \
                index < len(items):
            answer = items[index]
        cell = MENU_LABELS.index(self.menu_open) \
            if self.menu_open in MENU_LABELS else None
        self.menu_open = None
        if answer is None or not answer[1]:
            return True
        if cell is not None:
            self.menu_flash = (cell, pygame.time.get_ticks() + FLASH_MS)
        self._run_action(answer[1])
        return True

    def _run_action(self, action):
        if action == "exit":
            self.request_quit()
        elif action == "save":
            self.save_current()
        elif action == "run":
            self.run_game()
        elif action == "open_project":
            self.open_manager()
        elif action == "open_folder":
            self._prompt("open_folder")
        elif action == "manager":
            self.open_manager()
        elif action == "new_project":
            self._prompt("new_project")
        elif action == "import_asset":
            self.import_dialog()
        elif action in _CREATE_KINDS:
            # one path for every New entry: the unified dialog
            self._prompt(action)
        elif action == "reload_project":
            self.reload_project()
        elif action == "tab_scene":
            self.set_tab(TAB_SCENE)
        elif action == "tab_doc":
            self.set_tab(TAB_DOC)
        elif action == "tab_code":
            self.set_tab(TAB_CODE)
        elif action == "tab_blocks":
            self.set_tab(TAB_BLOCKS)
        elif action == "tab_model":
            self.set_tab(TAB_MODEL)
        elif action == "tab_assets":
            self.set_tab(TAB_ASSETS)
        elif action == "tab_audio":
            self.set_tab(TAB_AUDIO)
        elif action == "tab_build":
            self.set_tab(TAB_BUILD)
        elif action == "tab_docs":
            self.set_tab(TAB_DOCS)
        elif action == "tab_settings":
            self.set_tab(TAB_SETTINGS)
        elif action == "tab_project":
            self.set_tab(TAB_PROJECT)
        elif action == "build":
            self.set_tab(TAB_BUILD)
            self.build.start()
        elif action == "preview":
            self.set_tab(TAB_SCENE)
            self.preview.play()
        elif action == "reload_scene":
            self.preview.reload()
        elif action == "toggle_output":
            self.show_output = not self.show_output
        elif action == "toggle_theme":
            self.toggle_theme()
        elif action == "toggle_inspector":
            self.show_inspector = not self.show_inspector
        elif action == "maximize":
            self.chrome.toggle_maximize()
        elif action in ("undo", "redo", "cut", "copy", "paste"):
            if self.tab == TAB_BLOCKS and action in ("undo", "redo"):
                getattr(self.blocks, action)()
            elif self.tab == TAB_CODE:
                if action in ("cut", "copy", "paste"):
                    getattr(self.code, action)()
                elif action == "undo":
                    self.code.undo_stack()
                else:
                    self.code.redo_stack()
        elif action == "keys":
            self.notice = ("Keyboard Shortcuts", [
                "F5            run the project in its own window",
                "F6-F10        Scene / Code / Model / Assets / Audio",
                "Ctrl+D        Document tab (the open .scene/.obj file)",
                "Shift+F7      Blocks tab (the open file as blocks)",
                "F12           Docs tab (engine reference and guides)",
                "Ctrl+,        Settings tab (every stored preference)",
                "View menu      Project tab (this project's manifest and "
                "keybinds)",
                "Ctrl+B        Build tab (PyInstaller)",
                "Ctrl+S        save the active file",
                "Ctrl+O        project manager",
                "Ctrl+Z / Y    undo / redo edits",
                "Ctrl+R        reload project files",
                "Ctrl+T        toggle dark / light theme",
                "F11           maximize the window",
                "",
                "Scene tab:  RMB look, WASD move, R rebuild",
                "Model tab:  1/2/3 mode, X/Y/Z axis, Del, E extrude,",
                "            F make face, G snap, W wireframe, Home frame",
                "Audio tab:  Space play/pause, S stop, Home restart, "
                "arrows seek, L loop",
                "Build tab:  click a switch to toggle, a value to type it",
                "Blocks tab: drag from the drawer, click a slot to type it,",
                "            Del takes a block out, Ctrl+wheel zooms",
                "Settings:   drag a slider, click a switch, click a binding",
                "            then press a key to capture it",
                "Project tab:  click a manifest value to edit it, a keys cell",
                "            then a control to bind a trigger to it",
                "Docs tab:     click or arrow through a topic; hover engine",
                "            calls in the Code tab for a hint",
                "Document tab: click a value to edit it; Delete removes the",
                "            picked node; right-click a file for raw JSON",
            ])
        elif action == "about":
            self.notice = (f"About {CODENAME}", list(const.ABOUT_LINES),
                           "fligma-img")

    def _caption_press(self, pos):
        w = self.screen.get_width()
        cap = pygame.Rect(0, 0, w, CAP_H)
        b_min, b_max, b_close = caption_buttons(cap)
        if b_close.collidepoint(pos):
            self.request_quit()
            return True
        if not cap.collidepoint(pos):
            return False
        if b_min.collidepoint(pos):
            self.chrome.minimize()
        elif b_max.collidepoint(pos):
            self.chrome.toggle_maximize()
        else:
            self.chrome.begin_move(pos)
        return True

    def _sync_surface(self):
        if not self.chrome.supported():
            return
        want = tuple(self.chrome.win.size)
        if not want or want == self.screen.get_size():
            return
        self.screen = self._make_window(want[0], want[1])

    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.request_quit()
            return
        if inputmod.is_focus_lost(e):
            # the keyboard went away, and with it every pending key-up
            self.preview.blur()
            self.model.drag = None
            return
        if e.type == pygame.KEYUP and (self.notice is not None
                                       or self.dialog is not None):
            # a modal owns the presses, not the letting go of one
            self.preview.input.handle(e)
        if self.notice is not None:
            if e.type == pygame.KEYDOWN or (
                    e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and
                    self.notice_ok.collidepoint(e.pos)):
                self.notice = None
            return
        if self.dialog is not None:
            result = self.dialog.handle(e)
            if result == "ok":
                # a ChoiceDialog answers a label, a PromptDialog its field
                text = getattr(self.dialog, "answer", None)
                if text is None:
                    text = self.dialog.field.text
                kind = self.dialog_kind
                self.dialog = None
                self._dialog_ok(kind, text)
            elif result == "cancel":
                self.dialog = None
            return
        if e.type == pygame.DROPFILE and self.mode == "editor" and \
                self.project is not None:
            name = getattr(e, "file", "")
            if name:
                self._drop_buffer.append(Path(name))
            return
        if e.type == pygame.DROPCOMPLETE:
            if self.mode == "editor" and self.project is not None and \
                    self._drop_buffer:
                self._do_import(self._drop_buffer)
            self._drop_buffer = []
            return
        if self.preview.focus_mode:
            # the viewport holds the pointer; Esc hands it back
            self.preview.handle_event(e)
            return
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.chrome.drag = None
            if self._handle_menu_release(e.pos):
                return
        if self.mode == "manager":
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if self._caption_press(e.pos):
                    return
                edges = self.chrome.resize_edges(e.pos,
                                                 self.screen.get_size())
                if edges:
                    self.chrome.begin_resize(edges, e.pos)
                    return
            self.manager.handle_event(e)
            return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3 \
                and self.mode == "editor":
            if self.file_tree_rect.collidepoint(e.pos) or \
                    self.scene_tree_rect.collidepoint(e.pos):
                self._tree_right_click(e.pos)
                return
            if self.ctx_menu is not None:
                # a right click away from a tree closes it
                self.ctx_menu = None
                return
            # otherwise the press belongs to the active tab
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.ctx_menu is not None:
                answered = self._ctx_click(e.pos)
                self.ctx_menu = None
                if answered:
                    return
            if self._handle_menu_click(e.pos):
                return
            if self._caption_press(e.pos):
                return
            edges = self.chrome.resize_edges(e.pos, self.screen.get_size())
            if edges:
                self.chrome.begin_resize(edges, e.pos)
                return
            for i, rect in enumerate(self.tab_rects):
                if rect.collidepoint(e.pos):
                    self.set_tab(i)
                    return
            if self.run_rect.collidepoint(e.pos):
                self.run_game()
                return
            if self.scene_tree_rect.collidepoint(e.pos):
                self._scene_tree_click(e.pos)
                return
            if self.file_tree_rect.collidepoint(e.pos):
                self._file_tree_click(e.pos)
                return
            if self.show_output and \
                    self.output_copy.collidepoint(e.pos):
                if widgets.copy_to_clipboard(self.log_panel.text()):
                    self.log(f"copied {self.log_panel.count} line(s)", "ok")
                else:
                    self.log("clipboard unavailable on this machine",
                             "warn")
                return
            if self.show_output and \
                    self.output_clear.collidepoint(e.pos):
                self.log_panel.clear()
                return
        if e.type == pygame.MOUSEWHEEL:
            mouse = pygame.mouse.get_pos()
            if self.scene_tree_rect.collidepoint(mouse):
                self.scene_tree.scroll_by(-e.y * 2, self.scene_tree_rect)
                return
            if self.file_tree_rect.collidepoint(mouse):
                self.file_tree.scroll_by(-e.y * 2, self.file_tree_rect)
                return
            if self.show_output and self.output_area.collidepoint(mouse):
                rows = max(1, self.output_area.height // 14)
                self.log_panel.scroll_by(e.y * 2, rows)
                return

        consumed = False
        if self.tab == TAB_SCENE:
            consumed = self.preview.handle_event(e)
        elif self.tab == TAB_DOC:
            consumed = self.doctab.handle_event(e)
        elif self.tab == TAB_CODE:
            consumed = self.code.handle_event(e)
        elif self.tab == TAB_BLOCKS:
            consumed = self.blocks.handle_event(e)
        elif self.tab == TAB_MODEL:
            consumed = self.model.handle_event(e)
        elif self.tab == TAB_ASSETS:
            consumed = self.assets.handle_event(e)
        elif self.tab == TAB_AUDIO:
            consumed = self.media.handle_event(e)
        elif self.tab == TAB_BUILD:
            consumed = self.build.handle_event(e)
        elif self.tab == TAB_DOCS:
            consumed = self.docs.handle_event(e)
        elif self.tab == TAB_SETTINGS:
            consumed = self.settings.handle_event(e)
        elif self.tab == TAB_PROJECT:
            consumed = self.projecttab.handle_event(e)
        if e.type == pygame.KEYDOWN and not consumed:
            self._shortcuts(e)

    def _toggle_node(self, row):
        """Fold a scene or object tree, or one node."""
        key = row.get("fold")
        if key is None:
            return False
        self.node_open[key] = not self.node_open.get(key, True)
        self.refresh_tree()
        return True

    def _scene_tree_click(self, pos):
        fold = self.scene_tree.fold_at(pos)
        if fold is not None:
            return self._toggle_node(fold)
        row = self.scene_tree.click(pos)
        if row is None:
            return False
        kind = row.get("kind")
        if kind == "scene":
            # a running preview switches scene now; a stopped one arms
            if self.preview.started:
                self.preview.play(row["scene"])
            else:
                self.preview.arm(row["scene"])
            self.set_tab(TAB_SCENE)
        elif kind == "node":
            # tree and Scene tab share one structure; picking syncs both
            self.preview.select_node(row["scene"], row["node"])
            self.set_tab(TAB_SCENE)
        return True

    def _file_tree_click(self, pos):
        hit = self.file_tree.create_at(pos)
        if hit is not None:
            self.create_in_folder(hit)
            return True
        fold = self.file_tree.fold_at(pos)
        if fold is not None:
            return self._toggle_node(fold)
        row = self.file_tree.click(pos)
        if row is None:
            return False
        if row["kind"] == "folder":
            key = row["key"]
            self.folder_open[key] = not self.folder_open.get(key, True)
            self.refresh_tree()
        elif row["kind"] == "node":
            # a document-owned node opens the document that places it
            self._open_object_doc(row.get("scene"))
        elif row["kind"] == "file":
            self.open_file(row["path"])
        return True

    def _open_object_doc(self, scope):
        """Open the `objects/<stem>` document a node row belongs to."""
        if self.project is None or not str(scope or "").startswith("object:"):
            return False
        stem = str(scope).split(":", 1)[1]
        path = scenedoc.find_doc(self.project.objects_dir, stem, "object")
        return bool(path) and self.open_file(path)

    def create_in_folder(self, row):
        """Open the New dialog filtered to one folder's kinds."""
        if self.project is None:
            self.log("open a project first", "warn")
            return
        group, kind = row["create"]
        self.dialog_kind = "create"
        self.dialog = widgets.CreateDialog(self.project, kind, width=470,
                                           only=group)

    def _tree_right_click(self, pos):
        """The right-click menu over any file, folder or scene row."""
        row = None
        if self.file_tree_rect.collidepoint(pos):
            row = self.file_tree.click(pos)
        elif self.scene_tree_rect.collidepoint(pos):
            row = self.scene_tree.click(pos)
        self.ctx_menu = None
        if row is None:
            return
        kind = row.get("kind")
        if "path" not in row:
            return                      # a node row is not a file to manage
        path = Path(row["path"])
        if kind == "folder":
            self.show_folder_menu(path, pos)
        elif kind in ("file", "scene"):
            self.show_file_menu(path, pos)

    def _ctx_click(self, pos):
        """Was a context-menu row clicked? Returns whether it answered."""
        for action, rect in self.ctx_rows:
            if rect is not None and rect.collidepoint(pos):
                self._run_ctx(action, self.ctx_menu["path"])
                return True
        return False

    def _shortcuts(self, e):
        ctrl = bool(e.mod & pygame.KMOD_CTRL)
        if e.key == pygame.K_F5:
            self.run_game()
        elif e.key == pygame.K_F6:
            self.set_tab(TAB_SCENE)
        elif e.key == pygame.K_F7:
            if e.mod & pygame.KMOD_SHIFT:
                self.set_tab(TAB_BLOCKS)
            else:
                self.set_tab(TAB_CODE)
        elif e.key == pygame.K_F8:
            self.set_tab(TAB_MODEL)
        elif e.key == pygame.K_F9:
            self.set_tab(TAB_ASSETS)
        elif e.key == pygame.K_F10:
            self.set_tab(TAB_AUDIO)
        elif e.key == pygame.K_F12:
            self.set_tab(TAB_DOCS)
        elif e.key == pygame.K_F11:
            self.chrome.toggle_maximize()
        elif ctrl and e.key == pygame.K_d:
            self.set_tab(TAB_DOC)
        elif ctrl and e.key == pygame.K_s:
            self.save_current()
        elif ctrl and e.key == pygame.K_o:
            self.open_manager()
        elif ctrl and e.key == pygame.K_r:
            self.reload_project()
        elif ctrl and e.key == pygame.K_t:
            self.toggle_theme()
        elif ctrl and e.key == pygame.K_b:
            self.set_tab(TAB_BUILD)
        elif ctrl and e.key == pygame.K_COMMA:
            self.set_tab(TAB_SETTINGS)
        elif ctrl and e.key == pygame.K_n:
            if e.mod & pygame.KMOD_SHIFT:
                self._prompt("new_project")
            elif self.project is not None:
                self._prompt("new_scene")

    def _layout(self):
        w, h = self.screen.get_size()
        tabs = pygame.Rect(0, CAP_H + MENU_H, w, TAB_H)
        top = tabs.bottom
        status = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
        self.dock_area = pygame.Rect(0, top, TREE_W, status.y - top)
        tree, insp = self._dock_widths(w)
        self.dock_area.width = tree
        self.work_area = pygame.Rect(tree, top, w - tree - insp,
                                     status.y - top)
        self.inspector_area = pygame.Rect(w - insp, top, insp,
                                          status.y - top)
        split = max(100, min(int(self.dock_area.height * 0.28),
                             self.dock_area.height - 110))
        scene_panel = pygame.Rect(self.dock_area.x, self.dock_area.y,
                                  self.dock_area.width, split)
        fh = self.dock_area.bottom - scene_panel.bottom - 1
        file_panel = pygame.Rect(self.dock_area.x, scene_panel.bottom + 1,
                                 self.dock_area.width, fh)
        self.scene_tree_rect = pygame.Rect(
            scene_panel.x + 2, scene_panel.y + 22, scene_panel.width - 4,
            max(40, scene_panel.height - 24))
        self.file_tree_rect = pygame.Rect(
            file_panel.x + 2, file_panel.y + 22, file_panel.width - 4,
            max(60, file_panel.height - 24))
        if self.show_output:
            oh = min(OUT_H, max(70, self.work_area.height // 3))
            self.output_area = pygame.Rect(self.work_area.x,
                                           self.work_area.bottom - oh,
                                           self.work_area.width, oh)
            self.content_area = pygame.Rect(
                self.work_area.x, self.work_area.y, self.work_area.width,
                self.work_area.height - oh)
        else:
            self.output_area = pygame.Rect(0, 0, 0, 0)
            self.content_area = self.work_area.copy()

    def _dock_widths(self, w):
        """Tree and inspector widths, giving way before the document does.

        A narrow window keeps its tab's toolbar usable: the docks shrink
        down to a floor in turn, and the inspector goes first because a
        narrow tree is still navigable while a squeezed toolbar clips.
        """
        tree = TREE_W
        insp = INSPECT_W if self.show_inspector else 0
        over = tree + insp + MIN_WORK_W - w
        if over > 0 and insp:
            cut = max(0, min(over, insp - MIN_INSPECT_W))
            insp -= cut
            over -= cut
        if over > 0:
            tree -= max(0, min(over, tree - MIN_TREE_W))
        return tree, insp

    def draw(self):
        self._poll_process()
        # a viewport holding the pointer leaves the cursor where it was
        # grabbed, so no button anywhere else should read that stale point
        try:
            widgets.park_pointer(self.preview.focus_mode or
                                 pygame.mouse.get_visible() is False)
        except pygame.error:
            pass
        surface = self.screen
        surface.fill(xp.FACE)
        self._layout()
        self._draw_caption(surface)
        if self.mode == "manager":
            area = pygame.Rect(0, CAP_H, surface.get_width(),
                               surface.get_height() - CAP_H - STATUS_H)
            self.manager.draw(surface, area)
            self._draw_status(surface)
            self._draw_overlays(surface)
            pygame.draw.rect(surface, xp.CAP_BOT, surface.get_rect(), 1)
            return
        self._draw_menubar(surface)
        self._draw_tabstrip(surface)
        self._draw_docks(surface)
        self._draw_work(surface)
        if self.show_inspector:
            self._draw_inspector(surface)
        if self.show_output:
            self._draw_output(surface)
        self._draw_status(surface)
        self._draw_overlays(surface)
        pygame.draw.rect(surface, xp.CAP_BOT, surface.get_rect(), 1)

    def _draw_overlays(self, surface):
        if self.menu_open:
            self._draw_menu(surface)
        if self.ctx_menu is not None:
            self._draw_ctx(surface)
        if self.dialog is not None:
            self.dialog.draw(surface, self.fonts)
        if self.notice is not None:
            self._draw_notice(surface)
        if self.tab == TAB_CODE and self.mode == "editor" and \
                self.dialog is None and self.notice is None and \
                self.ctx_menu is None and self.code.hover_tip:
            xp.tooltip(surface, self.code.hover_point, self.code.hover_tip,
                       self.fonts["small"])
        elif self.mode == "editor" and self.dialog is None and \
                self.notice is None and self.ctx_menu is None and \
                self.menu_open is None:
            mouse = widgets.mouse_pos()
            tree_tip = getattr(self.file_tree, "hover_tip", None)
            if tree_tip:
                xp.tooltip(surface, self.file_tree.hover_point, [tree_tip],
                           self.fonts["small"])
            else:
                for index, rect in enumerate(self.tab_rects):
                    if rect.collidepoint(mouse):
                        xp.tooltip(surface, mouse, [TAB_TIPS[index]],
                                   self.fonts["small"])
                        break
                else:
                    if self.run_rect.collidepoint(mouse):
                        xp.tooltip(surface, mouse,
                                   ["Run the project with the current changes.",
                                    "Shortcut: F5"],
                                   self.fonts["small"])

    def _draw_ctx(self, surface):
        """The right-click menu over a file, folder or scene row."""
        self.ctx_rows = []
        if self.ctx_menu is None:
            return
        actions = self.ctx_menu.get("actions") or []
        if not actions:
            self.ctx_menu = None
            return
        wide = 200
        x = max(0, min(self.ctx_menu["x"],
                       surface.get_width() - wide - 6))
        line_h = self.fonts["small"].get_height() + 8
        tall = line_h * len(actions) + 12
        y = max(0, min(self.ctx_menu["y"], surface.get_height() - tall - 4))
        items = [(label, True) for _action, label in actions]
        hot = widgets.mouse_pos()
        hover = -1
        for i, (_action, rect) in enumerate(self.ctx_rows):
            if rect is not None and rect.collidepoint(hot):
                hover = i
                break
        _panel, rects = xp.menu_items(surface, (x, y), items,
                                      self.fonts["small"], width=wide,
                                      hover=hover)
        self.ctx_rows = list(zip([a for a, _l in actions], rects))

    def _draw_caption(self, surface):
        w = surface.get_width()
        cap = pygame.Rect(0, 0, w, CAP_H)
        title = f"{CODENAME} {__version__}"
        if self.mode == "manager":
            title += " - Project Manager"
        elif self.project is not None:
            title += f" - {self.project.title}"
        current = "-"
        if self.mode == "editor" and self.tab == TAB_CODE and self.code.path:
            current = self.relative(self.code.path)
        elif self.mode == "editor" and self.tab == TAB_DOC and \
                self.doctab.current():
            current = self.relative(self.doctab.current().path)
        elif self.mode == "editor" and self.tab == TAB_BLOCKS and \
                self.blocks.path:
            current = f"blocks {self.relative(self.blocks.path)}"
        elif self.mode == "editor" and self.tab == TAB_MODEL and \
                self.model.path:
            current = self.relative(self.model.path)
        elif self.mode == "editor" and self.tab == TAB_SCENE and \
                self.preview.scene_name:
            current = "scene " + self.preview.scene_name
        elif self.mode == "editor" and self.tab == TAB_AUDIO and \
                self.media.current:
            current = self.relative(self.media.current)
        elif self.mode == "editor" and self.tab == TAB_ASSETS and \
                self.selected_asset:
            current = self.relative(self.selected_asset)
        elif self.mode == "editor" and self.tab == TAB_BUILD:
            current = f"build {self.build.config.get('name')}"
        elif self.mode == "editor" and self.tab == TAB_DOCS:
            current = "docs " + self.docs.info()[0][1]
        elif self.mode == "editor" and self.tab == TAB_SETTINGS:
            current = f"settings {self.settings.group}"
        elif self.mode == "editor" and self.tab == TAB_PROJECT:
            current = f"project {META_NAME}"
        if current != "-":
            title += f" - {current}"
        if self.tab == TAB_CODE and self.code.dirty:
            title += "*"
        if self.tab == TAB_DOC and self.doctab.dirty:
            title += "*"
        if self.tab == TAB_BLOCKS and self.blocks.dirty:
            title += "*"
        if self.tab == TAB_MODEL and self.model.dirty:
            title += "*"
        xp.titlebar(surface, cap, title, self.fonts["normal"],
                    icon=widgets.icon("icon", 16))

    def _draw_menubar(self, surface):
        w = surface.get_width()
        bar = pygame.Rect(0, CAP_H, w, MENU_H)
        active = MENU_LABELS.index(self.menu_open) \
            if self.menu_open in MENU_LABELS else None
        cells = self._menu_cells()
        hot = widgets.mouse_pos()
        held = bool(pygame.mouse.get_pressed(3)[0])
        hover = pressed = None
        for i, label in enumerate(MENU_LABELS):
            if not cells[label].collidepoint(hot):
                continue
            if held:
                pressed = i
            elif active is None:
                hover = i
            break
        if pressed is None and active is None and self.menu_flash is not None:
            index, until = self.menu_flash
            if pygame.time.get_ticks() >= until:
                self.menu_flash = None
            else:
                pressed = index
        xp.menubar(surface, bar, active=active, font=self.fonts["normal"],
                   labels=MENU_LABELS, hover=hover, pressed=pressed)

    def _tab_marks(self):
        """Badges for the tabs holding an unsaved document."""
        out = [None] * len(TAB_LABELS)
        for index, holder in _DIRTY_TABS:
            part = getattr(self, holder, None)
            if part is not None and getattr(part, "dirty", False):
                out[index] = widgets.icon("dirty-sym", 10)
        return out

    def _draw_tabstrip(self, surface):
        w = surface.get_width()
        bar = pygame.Rect(0, CAP_H + MENU_H, w, TAB_H)
        marks = self._tab_marks()
        hot = widgets.mouse_pos()
        icons = [widgets.icon(name, 14) for name in TAB_ICONS]
        # drop tab art rather than the last tab when narrow
        span = 4 + sum(self.fonts["normal"].size(label)[0] + 26 +
                       (19 if art is not None else 0)
                       for label, art in zip(TAB_LABELS, icons))
        span += 13 if any(marks) else 0
        if span > bar.width - 120:
            icons = None
        # Run holds 104 px right; tabs take the rest
        strip = pygame.Rect(bar.x, bar.y, max(0, bar.width - 112), bar.height)
        self.tab_rects = xp.tabs(surface, strip, TAB_LABELS, self.tab,
                                 self.fonts["normal"], icons=icons,
                                 marks=marks, hover=self._tab_hot(hot))
        self.run_rect = pygame.Rect(bar.right - 104, bar.y + 2, 96,
                                    bar.height - 5)
        xp.button(surface, self.run_rect, "Run  F5", self.fonts["normal"],
                  default=True, icon=widgets.icon(RUN_ICON, 14),
                  hovered=self.run_rect.collidepoint(hot),
                  pressed=bool(pygame.mouse.get_pressed(3)[0])
                  and self.run_rect.collidepoint(hot))
        img = widgets.cached_text(
            self.fonts["small"],
            f"{CODENAME} {__version__}", xp.TEXT_MUTED)
        # the build number is left out rather than drawn over
        if img is not None and \
                self.run_rect.x - 12 - img.get_width() > \
                self.tab_rects[-1].right:
            surface.blit(img, (self.run_rect.x - 12 - img.get_width(),
                               bar.y + 6))

    def _tab_hot(self, hot):
        """Which tab strip cell the pointer is over, from last frame."""
        for i, rect in enumerate(self.tab_rects):
            if rect.collidepoint(hot):
                return i
        return -1

    def _draw_docks(self, surface):
        area = self.dock_area
        pygame.draw.rect(surface, xp.FACE, area)
        old = surface.get_clip()
        surface.set_clip(area)      # a long name never reaches the canvas
        scenes = self.project.scene_names() if self.project else []
        scene_head = pygame.Rect(area.x, area.y, area.width, 22)
        widgets.header(surface, scene_head, "Scene", self.fonts["normal"],
                       right=f"{len(scenes)} scenes", icon="file-scene-3d")
        if self.project is None:
            self._dock_hint(surface, self.scene_tree_rect, "no project")
        else:
            self.scene_tree.draw(surface, self.scene_tree_rect,
                                 self.fonts["normal"], self.fonts["small"])
        file_head = pygame.Rect(area.x, self.file_tree_rect.y - 22,
                                area.width, 22)
        pygame.draw.line(surface, xp.SHADOW, (area.x, file_head.y),
                         (area.right, file_head.y))
        total = 0
        if self.project is not None:
            total = 1 + sum(len(self.project.files(k)) for k in FOLDERS)
        widgets.header(surface, file_head, "Project View",
                       self.fonts["normal"], right=f"{total} files",
                       icon="block-sym")
        if self.project is None:
            self._dock_hint(surface, self.file_tree_rect, "open a project")
        else:
            self.file_tree.draw(surface, self.file_tree_rect,
                                self.fonts["normal"], self.fonts["small"])
        pygame.draw.line(surface, xp.SHADOW, (area.right - 1, area.y),
                         (area.right - 1, area.bottom))
        surface.set_clip(old)

    def _dock_hint(self, surface, rect, text):
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        img = widgets.cached_text(self.fonts["small"],
                                  widgets.elide(self.fonts["small"], text,
                                                rect.width - 16),
                                  xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (rect.x + 8, rect.y + 8))

    def _draw_work(self, surface):
        area = self.content_area
        pygame.draw.rect(surface, xp.OUTLINE, area, 1)
        inner = area.inflate(-2, -2)
        # the work area clips what tabs paint at its edge
        old = surface.get_clip()
        surface.set_clip(inner)
        if self.tab == TAB_SCENE:
            self.preview.draw(surface, inner, self.dt)
        elif self.tab == TAB_DOC:
            self.doctab.draw(surface, inner, self.dt)
        elif self.tab == TAB_CODE:
            self.code.draw(surface, inner)
        elif self.tab == TAB_BLOCKS:
            self.blocks.draw(surface, inner, self.dt)
        elif self.tab == TAB_MODEL:
            self.model.draw(surface, inner)
        elif self.tab == TAB_ASSETS:
            self.assets.draw(surface, inner)
        elif self.tab == TAB_AUDIO:
            self.media.draw(surface, inner)
        elif self.tab == TAB_BUILD:
            self.build.draw(surface, inner, self.dt)
        elif self.tab == TAB_DOCS:
            self.docs.draw(surface, inner, self.dt)
        elif self.tab == TAB_SETTINGS:
            self.settings.draw(surface, inner, self.dt)
        elif self.tab == TAB_PROJECT:
            self.projecttab.draw(surface, inner, self.dt)
        surface.set_clip(old)

    def _info_rows(self):
        if self.tab == TAB_SCENE:
            rows = list(self.preview.info())
        elif self.tab == TAB_DOC:
            rows = list(self.doctab.info())
        elif self.tab == TAB_CODE:
            rows = list(self.code.info())
        elif self.tab == TAB_BLOCKS:
            rows = list(self.blocks.info())
        elif self.tab == TAB_MODEL:
            rows = list(self.model.info())
        elif self.tab == TAB_ASSETS:
            rows = list(self.assets.info())
        elif self.tab == TAB_BUILD:
            rows = list(self.build.info())
        elif self.tab == TAB_DOCS:
            rows = list(self.docs.info())
        elif self.tab == TAB_SETTINGS:
            rows = list(self.settings.info())
        elif self.tab == TAB_PROJECT:
            rows = list(self.projecttab.info())
        else:
            rows = list(self.media.info())
        if self.project is not None:
            p = self.project
            rows += [
                ("-", ""),
                ("Project", p.title),
                ("Folder", p.name),
                ("Start", str(p.start)),
                ("Scale", f"{p.render_scale:g}"),
                ("Scenes", str(len(p.scene_names()))),
                ("Objects", str(len(p.object_names()))),
                ("Models", str(len(p.model_names())
                                + len(p.model2d_names()))),
                ("Textures", str(len(p.texture_files()))),
                ("Audio", str(len(p.audio_files()))),
            ]
        return rows

    def _draw_inspector(self, surface):
        area = self.inspector_area
        if area.width <= 0:
            return
        pygame.draw.rect(surface, xp.FACE, area)
        pygame.draw.line(surface, xp.SHADOW, (area.x, area.y),
                         (area.x, area.bottom))
        head = pygame.Rect(area.x + 1, area.y, area.width - 1, 22)
        widgets.header(surface, head, "Inspector", self.fonts["normal"],
                       icon="settings-sym")
        x = area.x + 9
        y = head.bottom + 6
        width = area.width - 18
        old = surface.get_clip()
        surface.set_clip(pygame.Rect(area.x + 1, head.bottom,
                                     area.width - 1,
                                     area.bottom - head.bottom))
        if self.tab == TAB_ASSETS and self.selected_asset is not None:
            path = self.selected_asset
            img = widgets.cached_text(self.fonts["normal"], path.name,
                                      xp.LINK)
            surface.blit(img, (x, y))
            y += img.get_height() + 1
            rel = self.relative(path)
            for line in widgets.wrap(self.fonts["small"], rel,
                                     width)[:2]:
                img = widgets.cached_text(self.fonts["small"], line,
                                          xp.TEXT_MUTED)
                if img is not None:
                    surface.blit(img, (x, y))
                    y += img.get_height() + 1
            box = pygame.Rect(x, y + 3, width, 78)
            pygame.draw.rect(surface, xp.FIELD, box)
            xp.sunken(surface, box)
            thumb = self.assets.thumbnail(path, box.inflate(-4, -4).size)
            if thumb is not None:
                surface.blit(thumb, (box.centerx - thumb.get_width() // 2,
                                     box.centery - thumb.get_height() // 2))
            y = box.bottom + 6
            for label, value in self.assets.describe(path):
                y = self._draw_property(surface, x, y, width, label, value,
                                        area.bottom - 8)
                if y < 0:
                    break
            if y >= 0:
                pygame.draw.line(surface, xp.SHADOW, (x, y + 2),
                                 (x + width, y + 2))
                y += 10
        for label, value in self._info_rows():
            y = self._draw_property(surface, x, y, width, label, value,
                                    area.bottom - 8)
            if y < 0:
                break
        surface.set_clip(old)

    def _draw_property(self, surface, x, y, width, label, value, bottom):
        if label == "-":
            pygame.draw.line(surface, xp.SHADOW, (x, y + 3),
                             (x + width, y + 3))
            return y + 9
        img = widgets.cached_text(self.fonts["small"], label, xp.TEXT_MUTED)
        surface.blit(img, (x, y + 1))
        lines = widgets.wrap(self.fonts["small"], value, width - 74)
        line_h = self.fonts["small"].get_height() + 1
        vy = y
        for line in lines[:5]:
            img = widgets.cached_text(self.fonts["small"], line, xp.TEXT)
            if img is not None:
                surface.blit(img, (x + 74, vy))
            vy += line_h
        y = max(vy, y + line_h) + 3
        if y > bottom:
            return -1
        return y

    def _draw_output(self, surface):
        area = self.output_area
        if area.height <= 0:
            return
        pygame.draw.rect(surface, xp.FACE, area)
        head = pygame.Rect(area.x + 1, area.y, area.width - 1, 20)
        widgets.header(surface, head, "Output", self.fonts["small"],
                       icon="log-sym")
        self.output_clear = pygame.Rect(head.right - 44, head.y + 2, 40, 16)
        img = widgets.cached_text(self.fonts["small"], "Clear",
                                  xp.TEXT_MUTED)
        surface.blit(img, (self.output_clear.right - img.get_width(),
                           head.centery - img.get_height() // 2))
        self.output_copy = pygame.Rect(head.right - 88, head.y + 2, 40, 16)
        img = widgets.cached_text(self.fonts["small"], "Copy",
                                  xp.TEXT_MUTED)
        surface.blit(img, (self.output_copy.right - img.get_width(),
                           head.centery - img.get_height() // 2))
        body = pygame.Rect(area.x + 2, head.bottom, area.width - 4,
                           area.bottom - head.bottom - 2)
        self.log_panel.draw(surface, body, self.fonts)

    def _draw_status(self, surface):
        w, h = surface.get_size()
        bar = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
        rate = f"fps {self.fps:3.0f}" if self.show_fps else ""
        if self.mode == "manager":
            panels = [f"{CODENAME} {__version__}", "project manager",
                      self.status, rate]
        elif self.project is not None:
            panels = [f"{self.project.title}",
                      f"tab {TAB_LABELS[self.tab]}",
                      self.status,
                      rate]
        else:
            panels = [CODENAME, "no project", self.status, rate]
        xp.statusbar(surface, bar, panels, self.fonts["small"])

    def _draw_menu(self, surface):
        pos = self._menu_cells()[self.menu_open].bottomleft
        items = self._items_for(self.menu_open)
        packed = []
        for label, action in items:
            art = widgets.icon(ACTION_ICONS[action], 14) \
                if action in ACTION_ICONS else None
            packed.append((label, action is not None, art))
        hot = widgets.mouse_pos()
        held = bool(pygame.mouse.get_pressed(3)[0])
        hover = pressed = -1
        # rows are measured from last frame's panel, which sits in the
        # same place; the pointer has no time to tell the difference
        for i, row in enumerate(self.menu_rows):
            if row is None or not row.collidepoint(hot):
                continue
            if held and i == self.menu_press_row:
                pressed = i
            else:
                hover = i
            break
        _panel, self.menu_rows = xp.menu_items(
            surface, pos, packed, self.fonts["normal"], width=190,
            hover=hover, pressed=pressed)

    def _draw_notice(self, surface):
        title, lines = self.notice[0], self.notice[1]
        picture = self.notice[2] if len(self.notice) > 2 else None
        w, h = surface.get_size()
        frame = pygame.Rect(0, 0, 560 if picture else 500, 300)
        frame.center = (w // 2, h // 2)
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 110))
        surface.blit(dim, (0, 0))
        body, _close = xp.message_frame(surface, frame, title,
                                        self.fonts["normal"])
        y = body.y + 14
        line_h = self.fonts["small"].get_height() + 3
        tx = body.x + 16
        if picture:
            # the portrait sits left of the text, scaled nearest-neighbour
            art = widgets.scaled_image(picture, 125)
            if art is not None:
                surface.blit(art, (body.x + 14, body.y + 14))
                tx = body.x + 14 + art.get_width() + 18
        for line in lines:
            img = widgets.cached_text(self.fonts["small"], line, xp.TEXT)
            if img is not None:
                surface.blit(img, (tx, y))
            y += line_h
        self.notice_ok.bottomright = (body.right - 16, body.bottom - 14)
        xp.button(surface, self.notice_ok, "OK", self.fonts["normal"],
                  default=True,
                  hovered=self.notice_ok.collidepoint(
                      pygame.mouse.get_pos()))

    def run(self):
        try:
            while self.running:
                raw = self.clock.tick(self.fps_cap or 0) / 1000.0
                # the meter reads real time; only the step clamps
                times = self._frame_times
                times.append(raw)
                self.fps = len(times) / max(sum(times), 1e-6)
                self.dt = min(0.05, raw)
                # one frame's presses, no longer: the scene reads them below
                self.preview.begin_frame()
                for e in pygame.event.get():
                    self.handle_event(e)
                if self.chrome.drag and pygame.mouse.get_pressed()[0]:
                    self.chrome.update()
                self.code.update(self.dt)
                self._watch_tick()
                self._sync_surface()
                self.draw()
                pygame.display.flip()
        finally:
            for part in (self.code, self.model, self.blocks):
                try:
                    if part.dirty:
                        part.save()
                except Exception:
                    pass
            try:
                self.media.stop()
            except Exception:
                pass
            try:
                self.audio.stop_all()
            except Exception:
                pass
            pygame.quit()


def main(project_path=None):
    Editor(project_path).run()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
