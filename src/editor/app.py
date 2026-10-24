"""The Emotion Engine editor: an XP-style IDE laid out like Godot.

    python -m fligengine              project manager, then the editor
    python -m fligengine run <path>   run a project full window

Left dock: the scene list and the project FileSystem. Centre: Scene,
Code, Model, Assets and Audio tabs. Right dock: the Inspector. Bottom:
the output log. Every pane is drawn with the engine's Luna widget
primitives; the window itself is borderless and the painted caption is
the titlebar.
"""

import os
import subprocess
import sys
from pathlib import Path

import pygame

from .. import CODENAME, __version__
from ..engine import model as modelmod, paths, theme, xp
from ..engine.audio import Audio
from ..engine.loader import META_NAME, ENTITY_TEMPLATE, Project, SCENE_TEMPLATE
from ..engine.winchrome import WindowChrome, caption_buttons
from . import mediaplayer, widgets
from .assets import AssetBrowser
from .buildtab import BuildTab
from .codeeditor import CodeEditor
from .mediaplayer import MediaPlayer
from .modeleditor import ModelEditor
from .preview import Preview
from .projectmanager import ProjectManager

CAP_H = 28
MENU_H = 22
TAB_H = 24
STATUS_H = 22
TREE_W = 232
INSPECT_W = 260
OUT_H = 132
MENU_LABELS = ("File", "Edit", "View", "Project", "Help")
TAB_SCENE, TAB_CODE, TAB_MODEL, TAB_ASSETS, TAB_AUDIO, TAB_BUILD = range(6)
TAB_LABELS = ("Scene", "Code", "Model", "Assets", "Audio", "Build")
FOLDERS = ("scenes", "entities", "scripts", "models", "textures", "audio")
AUDIO_EXT = (".wav", ".ogg", ".mp3", ".flac")
IMAGE_EXT = (".png", ".jpg", ".jpeg")

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
             ("Paste         Ctrl+V", "paste")],
    "View": [("Scene Tab         F6", "tab_scene"),
             ("Code Tab          F7", "tab_code"),
             ("Model Tab         F8", "tab_model"),
             ("Assets Tab        F9", "tab_assets"),
             ("Audio Tab         F10", "tab_audio"),
             ("Build Tab     Ctrl+B", "tab_build"),
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
                ("New Scene...", "new_scene"),
                ("New Entity...", "new_entity"),
                ("New Model...", "new_model"),
                ("New Script...", "new_script"),
                ("-", None),
                ("Project Manager", "manager")],
    "Help": [("Keyboard Shortcuts", "keys"), ("About", "about")],
}

SCRIPT_TEMPLATE = '''"""Shared helpers; import them from a scene.

    from scripts.helpers import clamp
"""


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value
'''


def default_project():
    p = PROJECTS / "demo"
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


class Editor:
    """Owns the window, the project manager and the editor docks."""

    def __init__(self, project_path=None):
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        theme.apply(theme.load())
        self.screen = pygame.display.set_mode((1280, 820),
                                              pygame.RESIZABLE)
        pygame.display.set_caption(CODENAME)
        self.clock = pygame.time.Clock()
        self.fonts = {
            "small": pygame.font.SysFont("tahoma", 11),
            "normal": pygame.font.SysFont("tahoma", 13),
            "big": pygame.font.SysFont("tahoma", 18, bold=True),
            "title": pygame.font.SysFont("tahoma", 24, bold=True),
            "mono": pygame.font.SysFont("consolas", 12),
        }
        self.audio = Audio(master=0.7)
        self.log_panel = widgets.OutputLog()
        self.scene_tree = widgets.TreeView()
        self.file_tree = widgets.TreeView()
        self.code = CodeEditor(self)
        self.model = ModelEditor(self)
        self.preview = Preview(self)
        self.assets = AssetBrowser(self)
        self.media = MediaPlayer(self)
        self.build = BuildTab(self)
        self.manager = ProjectManager(self)
        self.chrome = WindowChrome()
        self.project = None
        self.mode = "manager"
        self.tab = TAB_SCENE
        self.selected_asset = None
        self.folder_open = {k: True for k in FOLDERS}
        self.menu_open = None
        self.menu_rows = []
        self.dialog = None
        self.dialog_kind = None
        self.notice = None
        self.notice_ok = pygame.Rect(0, 0, 82, 26)
        self.show_output = True
        self.show_inspector = True
        self.running = True
        self.theme_name = theme.current()
        self.fps = 0.0
        self.dt = 1 / 60.0
        self.status = "project manager"
        self.process = None
        self.scene_tree_rect = pygame.Rect(0, 0, 0, 0)
        self.file_tree_rect = pygame.Rect(0, 0, 0, 0)
        self.dock_area = pygame.Rect(0, 0, 0, 0)
        self.output_area = pygame.Rect(0, 0, 0, 0)
        self.output_clear = pygame.Rect(0, 0, 0, 0)
        self.content_area = pygame.Rect(0, 0, 0, 0)
        self.inspector_area = pygame.Rect(0, 0, 0, 0)
        self.tab_rects = []
        self.run_rect = pygame.Rect(0, 0, 0, 0)
        self._last_size = self.screen.get_size()

        if project_path is not None:
            if self.open_project(project_path):
                self.log(f"{CODENAME} editor ready", "ok")
            else:
                self.log(f"cannot open {project_path}; showing the "
                         "project manager", "warn")
        else:
            self.log(f"{CODENAME} project manager ready", "ok")

    # ------------------------------------------------------------- helpers
    def log(self, text, kind="info"):
        self.log_panel.add(text, kind)

    def relative(self, path):
        if self.project is not None:
            return self.project.relative(path)
        return str(path)

    # --------------------------------------------------------------- theme
    def toggle_theme(self):
        """Swap dark/light, drop the cached artwork and remember it."""
        name = theme.toggle()
        widgets._TEXT_CACHE.clear()
        mediaplayer.WAVE_CACHE.clear()
        self.assets._thumbs.clear()
        self.theme_name = name
        self.status = f"theme: {name}"
        self.log(f"theme: {name}", "muted")
        return name

    # ------------------------------------------------------------- project
    def open_project(self, path):
        if path is None:
            return False
        try:
            project = Project(path)
        except Exception as exc:
            self.log(f"cannot open project: {exc}", "error")
            return False
        if self.code.dirty:
            self.code.save()
        if self.model.dirty:
            self.model.autosave()
        self.model.close_model()
        self.media.stop()
        self.project = project
        self.mode = "editor"
        self.preview.blur()
        self.preview.set_project(project)
        self.assets.set_project(project)
        self.media.set_project(project)
        self.build.set_project(project)
        self.model.refresh_textures()
        try:
            project.load_audio(self.audio)
        except Exception as exc:
            self.log(f"audio: {exc}", "warn")
        self.folder_open = {k: True for k in FOLDERS}
        self.selected_asset = None
        self.refresh_tree()
        scenes = project.scene_names()
        if scenes:
            start = project.start if project.start in scenes else scenes[0]
            self.open_file(project.scenes_dir / f"{start}.py", switch=False)
            self.preview.play(start)
            self.tab = TAB_SCENE
        else:
            self.tab = TAB_CODE
        self.status = f"project {project.name}"
        self.log(f"opened {project.path}", "ok")
        return True

    def open_manager(self):
        """Save the open files and go back to the project list."""
        if self.project is not None:
            if self.code.dirty:
                self.code.save()
            if self.model.dirty:
                self.model.autosave()
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
        p = self.project
        rows = [{"kind": "root", "label": p.title, "depth": 0,
                 "path": p.path, "key": "root"}]
        for name in p.scene_names():
            label = f"{name}.py"
            if name == p.start:
                label += "   (start)"
            rows.append({"kind": "scene", "label": label, "depth": 1,
                         "path": p.scenes_dir / f"{name}.py",
                         "key": f"scene:{name}", "scene": name})
        self.scene_tree.set_rows(rows)

        rows = [{"kind": "root", "label": p.title, "depth": 0,
                 "path": p.path, "key": "root"}]
        rows.append({"kind": "file", "label": META_NAME, "depth": 1,
                     "path": p.path / META_NAME,
                     "key": str(p.path / META_NAME)})
        for kind in FOLDERS:
            files = p.files(kind)
            opened = self.folder_open.get(kind, True)
            rows.append({"kind": "folder", "label": f"{kind} ({len(files)})",
                         "depth": 1, "path": p.dir(kind), "open": opened,
                         "key": kind})
            if opened:
                for f in files:
                    rows.append({"kind": "file", "label": f.name,
                                 "depth": 2, "path": f, "key": str(f)})
        self.file_tree.set_rows(rows)

    def open_file(self, path, switch=True):
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".py":
            if self.model.dirty:
                self.model.autosave()
            if str(path) != self.code.path:
                if self.code.dirty and not self.code.save():
                    return False
                if not self.code.open(path):
                    return False
            if switch:
                self.set_tab(TAB_CODE)
            self.status = f"editing {path.name}"
            return True
        if suffix == ".model":
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
        if suffix == ".flig":
            self.select_asset(path)
            if switch:
                self.set_tab(TAB_ASSETS)
            self.status = "project manifest"
            return True
        self.log(f"{path.name}: open it with an external program", "muted")
        return False

    # ---------------------------------------------------------------- tabs
    def set_tab(self, index):
        index = max(0, min(len(TAB_LABELS) - 1, int(index)))
        if index == self.tab:
            if index == TAB_SCENE and self.preview.scene is None:
                self.preview.play()
            return
        if self.tab == TAB_CODE and self.code.dirty:
            self.code.save()
        elif self.tab == TAB_MODEL and self.model.dirty:
            self.model.autosave()
        if self.tab == TAB_SCENE:
            self.preview.blur()
        if self.tab == TAB_AUDIO:
            self.media.pause()
        if self.tab == TAB_BUILD:
            self.build.config.store()
        self.tab = index
        if index == TAB_SCENE:
            self.preview.play()
        self.status = f"{TAB_LABELS[index]} tab"

    def save_current(self):
        if self.tab == TAB_CODE:
            self.code.save()
        elif self.tab == TAB_MODEL:
            self.model.save()
        elif self.tab == TAB_BUILD and self.project is not None:
            self.build.config.store()
            self.log("build options saved", "ok")
        elif self.project is not None:
            self.project.save_meta()
            self.log("manifest saved", "ok")

    # ------------------------------------------------------------ projects
    def _prompt(self, kind):
        spec = {
            "new_project": ("New Project", "Project folder name",
                            "my_game", "Created in fligengine/projects"),
            "open_folder": ("Open Project", "Project folder or path", "",
                            "A folder containing project.flig; relative "
                            "paths resolve in fligengine/projects"),
            "new_scene": ("New Scene", "Scene name (file stem)", "scene1",
                          "Adds scenes/<name>.py from the starter template"),
            "new_entity": ("New Entity", "Entity name (file stem)", "prop",
                           "Adds entities/<name>.py - a prop scenes spawn"),
            "new_model": ("New Model", "Model name (file stem)", "prop",
                          "Adds models/<name>.model and opens the model tab"),
            "new_script": ("New Script", "Script name (file stem)", "helpers",
                           "Adds scripts/<name>.py"),
        }
        title, label, value, hint = spec[kind]
        self.dialog_kind = kind
        self.dialog = widgets.PromptDialog(title, label, value, hint=hint,
                                           width=430)

    def prompt_build_option(self, key, flag, value, hint):
        """One-line editor for a Build-tab value; routed in _dialog_ok."""
        self.dialog_kind = f"build:{key}"
        self.dialog = widgets.PromptDialog(
            f"Build option {flag}", "Value (use ; between list entries)",
            value, hint=hint, width=470)

    def _dialog_ok(self, kind, text):
        if kind and kind.startswith("build:"):
            key = kind.split(":", 1)[1]
            self.build.config.set_from_text(key, text)
            self.log(f"build {key} = {self.build.config.get(key)!r}", "ok")
            self.status = f"build {key}"
            return
        if kind == "new_project":
            stem = clean_stem(text, "my_game")
            path = PROJECTS / stem
            if path.exists():
                self.log(f"{stem} already exists", "warn")
                return
            try:
                Project.create(path, title=text.strip() or stem)
            except Exception as exc:
                self.log(f"cannot create project: {exc}", "error")
                return
            self.open_project(path)
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
        if kind == "new_scene":
            p = self.project.scenes_dir / f"{stem}.py"
            if p.exists():
                self.log(f"scenes/{p.name} already exists", "warn")
                return
            p.write_text(SCENE_TEMPLATE, encoding="utf-8")
            self.refresh_tree()
            self.open_file(p)
            self.log(f"created scenes/{p.name}", "ok")
        elif kind == "new_entity":
            p = self.project.entities_dir / f"{stem}.py"
            if p.exists():
                self.log(f"entities/{p.name} already exists", "warn")
                return
            p.write_text(ENTITY_TEMPLATE, encoding="utf-8")
            self.project.reload_entities()
            self.refresh_tree()
            self.open_file(p)
            self.log(f"created entities/{p.name}", "ok")
        elif kind == "new_script":
            p = self.project.scripts_dir / f"{stem}.py"
            if p.exists():
                self.log(f"scripts/{p.name} already exists", "warn")
                return
            p.write_text(SCRIPT_TEMPLATE, encoding="utf-8")
            self.refresh_tree()
            self.open_file(p)
        elif kind == "new_model":
            model = modelmod.new_model("box", 1.0, texture="grid",
                                       name=stem)
            path = self.project.store_model(model, stem)
            self.refresh_tree()
            self.model.open(path)
            self.set_tab(TAB_MODEL)
            self.log(f"created models/{stem}.model", "ok")

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
        cmd = [sys.executable, "-m", "fligengine", "run",
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

    # --------------------------------------------------------------- menus
    def _menu_cells(self):
        w = self.screen.get_width()
        cells, x = {}, 6
        for label in MENU_LABELS:
            width = self.fonts["normal"].size(label)[0] + 12
            cells[label] = pygame.Rect(x, CAP_H, width, MENU_H)
            x += width + 2
        return cells

    def _items_for(self, label):
        return MENUS[label]

    def _handle_menu_click(self, pos):
        for label, rect in self._menu_cells().items():
            if rect.collidepoint(pos):
                self.menu_open = None if self.menu_open == label else label
                return True
        if self.menu_open:
            for row, item in zip(self.menu_rows,
                                 self._items_for(self.menu_open)):
                if row is not None and row.collidepoint(pos):
                    self.menu_open = None
                    if item[1]:
                        self._run_action(item[1])
                    return True
            self.menu_open = None
            return True
        return False

    def _run_action(self, action):
        if action == "exit":
            self.running = False
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
        elif action == "new_scene":
            self._prompt("new_scene")
        elif action == "new_entity":
            self._prompt("new_entity")
        elif action == "new_model":
            self._prompt("new_model")
        elif action == "new_script":
            self._prompt("new_script")
        elif action == "reload_project":
            self.reload_project()
        elif action == "tab_scene":
            self.set_tab(TAB_SCENE)
        elif action == "tab_code":
            self.set_tab(TAB_CODE)
        elif action == "tab_model":
            self.set_tab(TAB_MODEL)
        elif action == "tab_assets":
            self.set_tab(TAB_ASSETS)
        elif action == "tab_audio":
            self.set_tab(TAB_AUDIO)
        elif action == "tab_build":
            self.set_tab(TAB_BUILD)
        elif action == "build":
            self.set_tab(TAB_BUILD)
            self.build.start()
        elif action == "preview":
            self.set_tab(TAB_SCENE)
            self.preview.reload()
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
            if self.tab == TAB_CODE:
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
                "Audio tab:  Space play/pause, S stop, arrows seek, L loop",
                "Build tab:  click a switch to toggle, a value to type it",
            ])
        elif action == "about":
            self.notice = (f"About {CODENAME}", [
                f"{CODENAME} (fligengine {__version__}) - a PS2-style",
                "Python game engine and editor.",
                "",
                "Vertex renderer (moderngl), .model files with an",
                "inbuilt model editor, Python scenes with syntax",
                "highlighting, assets browser, audio media player,",
                "XP window chrome and PS2-style post FX.",
                "",
                "Games: python -m fligengine run <project>",
            ])

    # --------------------------------------------------------------- window
    def _caption_press(self, pos):
        w = self.screen.get_width()
        cap = pygame.Rect(0, 0, w, CAP_H)
        b_min, b_max, b_close = caption_buttons(cap)
        if b_close.collidepoint(pos):
            self.running = False
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
        self.screen = pygame.display.set_mode(want, pygame.RESIZABLE)

    # --------------------------------------------------------------- events
    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if self.notice is not None:
            if e.type == pygame.KEYDOWN or (
                    e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and
                    self.notice_ok.collidepoint(e.pos)):
                self.notice = None
            return
        if self.dialog is not None:
            result = self.dialog.handle(e)
            if result == "ok":
                text = self.dialog.field.text
                kind = self.dialog_kind
                self.dialog = None
                self._dialog_ok(kind, text)
            elif result == "cancel":
                self.dialog = None
            return
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.chrome.drag = None
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
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
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
        elif self.tab == TAB_CODE:
            consumed = self.code.handle_event(e)
        elif self.tab == TAB_MODEL:
            consumed = self.model.handle_event(e)
        elif self.tab == TAB_ASSETS:
            consumed = self.assets.handle_event(e)
        elif self.tab == TAB_AUDIO:
            consumed = self.media.handle_event(e)
        elif self.tab == TAB_BUILD:
            consumed = self.build.handle_event(e)
        if e.type == pygame.KEYDOWN and not consumed:
            self._shortcuts(e)

    def _scene_tree_click(self, pos):
        row = self.scene_tree.click(pos)
        if row is None:
            return False
        if row.get("kind") == "scene":
            self.preview.play(row["scene"])
            self.set_tab(TAB_SCENE)
        return True

    def _file_tree_click(self, pos):
        row = self.file_tree.click(pos)
        if row is None:
            return False
        if row["kind"] == "folder":
            key = row["key"]
            self.folder_open[key] = not self.folder_open.get(key, True)
            self.refresh_tree()
        elif row["kind"] == "file":
            self.open_file(row["path"])
        return True

    def _shortcuts(self, e):
        ctrl = bool(e.mod & pygame.KMOD_CTRL)
        if e.key == pygame.K_F5:
            self.run_game()
        elif e.key == pygame.K_F6:
            self.set_tab(TAB_SCENE)
        elif e.key == pygame.K_F7:
            self.set_tab(TAB_CODE)
        elif e.key == pygame.K_F8:
            self.set_tab(TAB_MODEL)
        elif e.key == pygame.K_F9:
            self.set_tab(TAB_ASSETS)
        elif e.key == pygame.K_F10:
            self.set_tab(TAB_AUDIO)
        elif e.key == pygame.K_F11:
            self.chrome.toggle_maximize()
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
        elif ctrl and e.key == pygame.K_n:
            if e.mod & pygame.KMOD_SHIFT:
                self._prompt("new_project")
            elif self.project is not None:
                self._prompt("new_scene")

    # ---------------------------------------------------------------- draw
    def _layout(self):
        w, h = self.screen.get_size()
        tabs = pygame.Rect(0, CAP_H + MENU_H, w, TAB_H)
        top = tabs.bottom
        status = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
        self.dock_area = pygame.Rect(0, top, TREE_W, status.y - top)
        insp = INSPECT_W if self.show_inspector else 0
        self.work_area = pygame.Rect(TREE_W, top, w - TREE_W - insp,
                                     status.y - top)
        self.inspector_area = pygame.Rect(w - insp, top, insp,
                                          status.y - top)
        split = max(100, min(int(self.dock_area.height * 0.28),
                             self.dock_area.height - 110))
        scene_panel = pygame.Rect(self.dock_area.x, self.dock_area.y,
                                  self.dock_area.width, split)
        file_panel = pygame.Rect(self.dock_area.x, scene_panel.bottom + 1,
                                 self.dock_area.width,
                                 self.dock_area.bottom - scene_panel.bottom - 1)
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

    def draw(self):
        self._poll_process()
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
        if self.dialog is not None:
            self.dialog.draw(surface, self.fonts)
        if self.notice is not None:
            self._draw_notice(surface)

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
        elif self.mode == "editor" and self.tab == TAB_MODEL and self.model.path:
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
        if current != "-":
            title += f" - {current}"
        if self.tab == TAB_CODE and self.code.dirty:
            title += "*"
        if self.tab == TAB_MODEL and self.model.dirty:
            title += "*"
        xp.titlebar(surface, cap, title, self.fonts["normal"])

    def _draw_menubar(self, surface):
        w = surface.get_width()
        bar = pygame.Rect(0, CAP_H, w, MENU_H)
        active = MENU_LABELS.index(self.menu_open) \
            if self.menu_open in MENU_LABELS else None
        xp.menubar(surface, bar, active=active, font=self.fonts["normal"],
                   labels=MENU_LABELS)

    def _draw_tabstrip(self, surface):
        w = surface.get_width()
        bar = pygame.Rect(0, CAP_H + MENU_H, w, TAB_H)
        self.tab_rects = xp.tabs(surface, bar, TAB_LABELS, self.tab,
                                 self.fonts["normal"])
        self.run_rect = pygame.Rect(bar.right - 104, bar.y + 2, 96,
                                    bar.height - 5)
        xp.button(surface, self.run_rect, "Run  F5", self.fonts["normal"],
                  default=True,
                  hovered=self.run_rect.collidepoint(
                      pygame.mouse.get_pos()))
        img = widgets.cached_text(
            self.fonts["small"],
            f"{CODENAME} {__version__}", xp.TEXT_MUTED)
        surface.blit(img, (self.run_rect.x - 12 - img.get_width(),
                           bar.y + 6))

    def _draw_docks(self, surface):
        area = self.dock_area
        pygame.draw.rect(surface, xp.FACE, area)
        scenes = self.project.scene_names() if self.project else []
        scene_head = pygame.Rect(area.x, area.y, area.width, 22)
        widgets.header(surface, scene_head, "Scene", self.fonts["normal"],
                       right=f"{len(scenes)} scenes")
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
        widgets.header(surface, file_head, "FileSystem",
                       self.fonts["normal"], right=f"{total} files")
        if self.project is None:
            self._dock_hint(surface, self.file_tree_rect, "open a project")
        else:
            self.file_tree.draw(surface, self.file_tree_rect,
                                self.fonts["normal"], self.fonts["small"])
        pygame.draw.line(surface, xp.SHADOW, (area.right - 1, area.y),
                         (area.right - 1, area.bottom))

    def _dock_hint(self, surface, rect, text):
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        img = widgets.cached_text(self.fonts["small"], text, xp.TEXT_MUTED)
        surface.blit(img, (rect.x + 8, rect.y + 8))

    def _draw_work(self, surface):
        area = self.content_area
        pygame.draw.rect(surface, xp.OUTLINE, area, 1)
        inner = area.inflate(-2, -2)
        if self.tab == TAB_SCENE:
            self.preview.draw(surface, inner, self.dt)
        elif self.tab == TAB_CODE:
            self.code.draw(surface, inner)
        elif self.tab == TAB_MODEL:
            self.model.draw(surface, inner)
        elif self.tab == TAB_ASSETS:
            self.assets.draw(surface, inner)
        elif self.tab == TAB_AUDIO:
            self.media.draw(surface, inner)
        elif self.tab == TAB_BUILD:
            self.build.draw(surface, inner, self.dt)

    def _info_rows(self):
        if self.tab == TAB_SCENE:
            rows = list(self.preview.info())
        elif self.tab == TAB_CODE:
            rows = list(self.code.info())
        elif self.tab == TAB_MODEL:
            rows = list(self.model.info())
        elif self.tab == TAB_ASSETS:
            rows = list(self.assets.info())
        elif self.tab == TAB_BUILD:
            rows = list(self.build.info())
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
                ("Entities", str(len(p.entity_names()))),
                ("Models", str(len(p.model_names()))),
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
        widgets.header(surface, head, "Inspector", self.fonts["normal"])
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
        widgets.header(surface, head, "Output", self.fonts["small"])
        self.output_clear = pygame.Rect(head.right - 44, head.y + 2, 40, 16)
        img = widgets.cached_text(self.fonts["small"], "Clear",
                                  xp.TEXT_MUTED)
        surface.blit(img, (self.output_clear.right - img.get_width(),
                           head.centery - img.get_height() // 2))
        body = pygame.Rect(area.x + 2, head.bottom, area.width - 4,
                           area.bottom - head.bottom - 2)
        self.log_panel.draw(surface, body, self.fonts)

    def _draw_status(self, surface):
        w, h = surface.get_size()
        bar = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
        if self.mode == "manager":
            panels = [f"{CODENAME} {__version__}", "project manager",
                      self.status, f"fps {self.fps:3.0f}"]
        elif self.project is not None:
            panels = [f"{self.project.title}",
                      f"tab {TAB_LABELS[self.tab]}",
                      self.status,
                      f"fps {self.fps:3.0f}"]
        else:
            panels = [CODENAME, "no project", self.status,
                      f"fps {self.fps:3.0f}"]
        xp.statusbar(surface, bar, panels, self.fonts["small"])

    def _draw_menu(self, surface):
        pos = self._menu_cells()[self.menu_open].bottomleft
        items = self._items_for(self.menu_open)
        packed = [(label, action is not None) for label, action in items]
        _panel, self.menu_rows = xp.menu_items(
            surface, pos, packed, self.fonts["normal"], width=190)

    def _draw_notice(self, surface):
        title, lines = self.notice
        w, h = surface.get_size()
        frame = pygame.Rect(0, 0, 500, 300)
        frame.center = (w // 2, h // 2)
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 110))
        surface.blit(dim, (0, 0))
        body, _close = xp.message_frame(surface, frame, title,
                                        self.fonts["normal"])
        y = body.y + 14
        line_h = self.fonts["small"].get_height() + 3
        for line in lines:
            img = widgets.cached_text(self.fonts["small"], line, xp.TEXT)
            if img is not None:
                surface.blit(img, (body.x + 16, y))
            y += line_h
        self.notice_ok.bottomright = (body.right - 16, body.bottom - 14)
        xp.button(surface, self.notice_ok, "OK", self.fonts["normal"],
                  default=True,
                  hovered=self.notice_ok.collidepoint(
                      pygame.mouse.get_pos()))

    # ---------------------------------------------------------------- loop
    def run(self):
        try:
            while self.running:
                self.dt = min(0.05, self.clock.tick(60) / 1000.0)
                self.fps = self.fps * 0.9 + (1.0 / max(self.dt, 1e-4)) * 0.1
                for e in pygame.event.get():
                    self.handle_event(e)
                if self.chrome.drag and pygame.mouse.get_pressed()[0]:
                    self.chrome.update()
                self._sync_surface()
                self.draw()
                pygame.display.flip()
        finally:
            for part in (self.code, self.model):
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
