"""The Project tab: the manifest as a form, and one keybind table."""

import json

import pygame

from ..engine import inputmap, loader, xp
from . import settingstab, widgets

ROW_H = 26           # floor values; the real metrics come from the fonts
HEAD_H = 24
BUTTON_H = 26
LABEL_W = 184
READ_W = 68
RAIL_W = 104

# the rail, in order; `input` is the one keybind table, not a form
SECTIONS = ("game", "window", "render", "audio", "save", "debug",
            "input", "pausetrigger", "defaults")
TITLES = {"game": "Game", "window": "Window", "render": "Render",
          "audio": "Audio", "save": "Save", "debug": "Debug",
          "input": "Input Map", "pausetrigger": "Pause Trigger",
          "defaults": "Scene defaults"}
BLURBS = {
    "game": "Who the project is and where it starts. These keys stay at the "
            "top of project.flig.",
    "window": "The window the game opens with. A player's own config wins "
              "over these once they have changed it in Settings.",
    "render": "How the frame is made: pixel scale, the post chain, vsync, "
              "and the size baked lightmaps are frozen at.",
    "audio": "Volumes the mixer starts with, and the track in audio/ that "
             "begins playing on boot.",
    "save": "The slot the game writes, how often it writes itself, and "
            "whether booting loads it back.",
    "debug": "What the running game shows: the frame counter, the controls "
             "panel, and whether scenes may draw an overlay at all.",
    "input": "One table for every key in the game. Actions are polled every "
             "frame; a trigger's press broadcasts its name to the scene. It "
             "says where each binding comes from, and what the player's own "
             "config does to it.",
    "pausetrigger": "How the game pauses: mode 1 shows the engine pause menu, "
                    "mode 2 switches to a pause scene, mode 3 runs a pause script.",
    "defaults": "The starting values every scene is built with, put on the "
                "scene before its setup(), so a script still wins.",
}

# (key, label, kind, help); `game` edits the manifest's top level
GAME = (
    ("title", "Title", "text", "What the window and the build are called"),
    ("start", "Start scene", "scene", "The scene the game opens on"),
    ("version", "Version", "text", "Shown in the project list"),
    ("description", "Description", "text", "One line about the game"),
    ("seed", "Seed", "number", "The random seed every scene starts from"),
)
PAUSETRIGGER = (
    ("mode", "Pause mode", "choice", "1=engine pause menu, 2=pause scene, 3=pause script"),
    ("scene", "Pause scene", "scene", "Scene to switch to when mode=2"),
    ("script", "Pause script", "text", "Script to run when mode=3 (in scripts/)"),
)
WINDOW = (
    ("size", "Window size", "pair", "Width and height, in pixels"),
    ("fullscreen", "Start fullscreen", "bool", "Opens over the whole desktop"),
    ("resizable", "Resizable", "bool",
     "Off keeps the window at the size above"),
    ("min_size", "Minimum size", "pair",
     "The smallest the window may be dragged"),
)
RENDER = (
    ("scale", "Render scale", "number",
     "0.75 draws three quarters the pixels; 1.0 is native"),
    ("clear_color", "Clear colour", "color", "The colour behind the frame"),
    ("post", "Post chain", "post",
     "Screen shaders the whole frame runs through"),
    ("bake_on_run", "Bake on entry", "bool",
     "Bake-flagged lights freeze when a scene starts"),
    ("bake_size", "Lightmap size", "number",
     "Edge of each baked lightmap, in pixels"),
    ("vsync", "VSync", "bool", "Wait for the monitor between frames"),
    ("fps_cap", "FPS cap", "number", "0 runs as fast as it can"),
)
AUDIO = (
    ("master", "Master volume", "number", "0 silent, 1 full"),
    ("music_volume", "Music volume", "number", "The music channel alone"),
    ("music", "Boot track", "track",
     "A file in audio/ that plays from the first frame"),
)
SAVE = (
    ("slot", "Save slot", "text", "The file is saves/<slot>.json"),
    ("autosave", "Autosave every (s)", "number", "0 turns it off"),
    ("auto_load", "Load on boot", "bool",
     "Opens the slot the game was left in"),
)
DEBUG = (
    ("show_fps", "Show FPS", "bool", "The frame rate in the status bar"),
    ("show_help", "Controls at boot", "bool",
     "The help panel is open when the game starts"),
    ("overlay", "Scene overlay", "bool",
     "Off stops any scene drawing its own HUD"),
)

# the `defaults` keys this tab paints as a colour, and their words
DEFAULT_LABELS = {
    "ambient": "Ambient light", "sun_dir": "Sun direction",
    "sun_col": "Sun colour", "fog_color": "Fog colour",
    "fog_near": "Fog starts", "fog_far": "Fog ends",
    "fov": "Field of view", "near": "Near clip", "far": "Far clip",
    "eye_height": "Eye height", "move_speed": "Move speed",
    "gravity": "Gravity", "jump_speed": "Jump speed",
    "world_radius": "World radius", "camera": "Camera mode",
    "lock_input": "Lock input", "master": "Light master",
    "post": "Scene post chain",
}
DEFAULT_HINTS = {
    "ambient": "Light on everything, from nowhere",
    "sun_dir": "Where the one directional light comes from",
    "sun_col": "Its colour, multiplied into every lit surface",
    "fog_color": "The haze distance fades into",
    "fog_near": "How far before fog starts",
    "fog_far": "How far before nothing shows at all",
    "fov": "Vertical field of view, in degrees",
    "near": "Closer than this is not drawn",
    "far": "Further than this is not drawn",
    "eye_height": "How high the camera sits, in metres",
    "move_speed": "Walk and run speed, in metres per second",
    "gravity": "Downward pull, for a scene that implements it",
    "jump_speed": "Launch speed, for a scene that implements it",
    "world_radius": "How far from the origin the camera may go; 0 is off",
    "camera": "walk glues to the ground, fly is free",
    "lock_input": "The player cannot move until a script unlocks them",
    "master": "One dimmer over the whole scene; 0 is black",
    "post": "Screen shaders this scene's frame runs through",
}
DEFAULT_COLORS = ("ambient", "sun_col", "fog_color")
CHOICES = {"defaults.camera": ("walk", "fly"),
           "pausetrigger.mode": ("1", "2", "3")}


def spec_of(name):
    """The row one `section.key` names, or None if this tab cannot write it."""
    section, _, key = str(name).partition(".")
    for _key, label, kind, help_text in SECTION_ROWS.get(section, ()):
        if _key == key:
            return Row(section, key, label, kind, help_text)
    return None


def to_hex(value, default=""):
    """A 0..1 triple as `#rrggbb`, for the colour rows."""
    got = loader.number_list(value)
    if not got:
        return default
    return "#" + "".join(f"{int(round(max(0.0, min(1.0, c)) * 255)):02x}"
                         for c in got[:3])


def from_hex(text):
    """`#rrggbb` as three 0..1 floats; None when it does not read."""
    raw = str(text or "").strip().lstrip("#")
    if len(raw) != 6:
        return None
    try:
        parts = [int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return None
    return [round(v, 4) for v in parts]


def _default_control(key):
    """Which editor one `defaults` key gets."""
    if key in DEFAULT_COLORS:
        return "color"
    if key == "camera":
        return "choice"
    if key == "post":
        return "post"
    kind = loader.DEFAULT_KINDS.get(key)
    return {"list": "list", "names": "post", "bool": "bool",
            "float": "number", "text": "text"}.get(kind, "text")


def _default_rows():
    """The `defaults` section as rows, in the engine's own order."""
    return tuple((key, DEFAULT_LABELS[key], _default_control(key),
                  DEFAULT_HINTS[key]) for key in loader.DEFAULT_ORDER)


SECTION_ROWS = {
    "game": GAME, "window": WINDOW, "render": RENDER, "audio": AUDIO,
    "save": SAVE, "debug": DEBUG,
    "pausetrigger": PAUSETRIGGER, "defaults": _default_rows(),
}


# the top-level keys a project cannot be written without
REQUIRED = ("name", "title", "start", "format")


class Row:
    """One manifest line: where it lives, and how it is edited."""

    def __init__(self, section, key, label, kind, help_text=""):
        self.section = section
        self.key = key
        self.label = label
        self.kind = kind
        self.help = help_text
        self.choices = CHOICES.get(f"{section}.{key}", ())

    @property
    def name(self):
        return f"{self.section}.{self.key}"


class ProjectTab:
    """Left rail of sections, right pane of rows, one Save button."""

    def __init__(self, app):
        self.app = app
        self.section = "game"
        self.scroll = 0
        self.rows = []             # (row, rect) hit targets, this frame
        self.rail_rects = []
        self.minus_rects = []      # (name, rect) trigger removes
        self.keys_rects = []       # (band, name, rect) binding cells
        self.deadzone_rect = pygame.Rect(0, 0, 0, 0)   # the tuning row
        self.buttons = {}
        self.area = pygame.Rect(0, 0, 0, 0)
        self.list_rect = pygame.Rect(0, 0, 0, 0)
        self.side_rect = pygame.Rect(0, 0, 0, 0)
        self.focus = None          # the row the help column describes
        self.capture = None        # (band, name) waiting for a control
        self.map = None            # the staged keybind table
        self.map_dirty = False
        self.dirty = False         # manifest values not yet written
        self._metrics()

    # -- plumbing --------------------------------------------------------
    def use_fonts(self, fonts):
        """Keep the page's metrics in step with a font-size change."""
        self._metrics()

    def _metrics(self):
        """Row sizes that grow with the font, never clipped."""
        fonts = getattr(self.app, "fonts", {}) or {}
        small = fonts.get("small")
        normal = fonts.get("normal")
        self.row_h = max(ROW_H, small.get_height() + 8) if small else ROW_H
        self.head_h = max(HEAD_H, small.get_height() + 6) if small \
            else HEAD_H
        self.button_h = max(BUTTON_H,
                            normal.get_height() + 10) if normal else BUTTON_H

    @property
    def project(self):
        return self.app.project

    def set_project(self, project):
        """A new project owns this page now; drop every staged value."""
        self.section = "game"
        self.project_reset()

    def project_reset(self):
        self.map = None
        self.map_dirty = False
        self.dirty = False
        self.capture = None
        self.focus = None
        self.scroll = 0

    def refresh(self):
        """The file may have changed on disk; forget the staged map."""
        self.map = None
        self.map_dirty = False

    # -- the manifest ----------------------------------------------------
    def value(self, row):
        """One manifest value as the file holds it, or None."""
        project = self.project
        if project is None:
            return None
        if row.section == "game":
            return project.meta.get(row.key)
        return project.get(row.section, row.key)

    def write(self, row, value):
        """Store one value in the manifest, in memory until Save."""
        project = self.project
        if project is None or row is None:
            return None
        if value is None:
            return self.clear(row)
        if row.section == "game":
            project.meta[row.key] = value
        else:
            project.set(row.section, row.key, value)
        self.focus = row.name
        self.dirty = True
        return value

    def clear(self, row):
        """Take one key out of the manifest, so the engine's own value wins."""
        project = self.project
        if project is None or row is None:
            return False
        if row.section == "game":
            if row.key in REQUIRED:
                self.app.log(f"{row.name} has to stay in the manifest",
                             "warn")
                return False
            project.meta.pop(row.key, None)
        else:
            block = project.meta.get(row.section)
            if not isinstance(block, dict) or row.key not in block:
                return False
            block.pop(row.key)
        self.focus = row.name
        self.dirty = True
        return True

    def text_of(self, row):
        """What a row shows: the value in words, or a placeholder."""
        value = self.value(row)
        if value is None or value == "":
            return "(not set)" if row.kind != "bool" else "off"
        if row.kind == "bool":
            return "on" if value else "off"
        if row.kind == "color":
            return to_hex(value, "(not set)")
        if row.kind in ("pair", "list", "post"):
            if row.kind == "post" and not isinstance(value, (list, tuple)):
                return str(value)
            got = loader.number_list(value)
            if row.kind == "post":
                return ", ".join(loader.name_list(value)) or "(none)"
            return ", ".join(f"{c:g}" for c in (got or ())) \
                if got else str(value)
        if row.kind == "number":
            try:
                return f"{float(value):g}"
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def form_rows(self):
        """The rows this section holds, as the manifest can write them."""
        if self.section == "input":
            return []
        return [Row(self.section, key, label, kind, help_text)
                for key, label, kind, help_text
                in SECTION_ROWS.get(self.section, ())]

    # -- the keybind table -----------------------------------------------
    def stage(self):
        """The map this tab edits, until Save writes it back."""
        if self.map is None:
            got = inputmap.load(self.project)
            self.map = inputmap.InputMap(dict(got.actions),
                                         dict(got.triggers))
            self.map_dirty = False
        return self.map

    def bind_rows(self):
        """Two bands of (name, keys, what, note) for the keybind table.

        The engine's own actions head the first band, so the table always
        shows what a player can rebind, project-declared or not. Each row
        also names where its keys came from, and whether the scene running
        in the preview has rebound it since.
        """
        mapping = self.stage()
        clashes = {}
        for token, names in mapping.conflicts():
            clashes[token] = list(names)
        seen = self.scene_binds()
        out = []
        for band, trigger in (("actions", False), ("triggers", True)):
            rows = []
            for info in mapping.labels():
                if (info["kind"] == inputmap.TRIGGER) != trigger:
                    continue
                name = info["name"]
                keys = info["keys"] or []
                shared = sorted({other for token in keys
                                 for other in clashes.get(token, ())
                                 if other != name})
                what = f"broadcasts {name.replace('_', ' ')}" if trigger \
                    else info["what"]
                rows.append({"name": name, "keys": keys, "what": what,
                             "note": (f"{settingstab.binding_label(shared)} "
                                      f"is shared" if shared else ""),
                             "here": info["here"], "band": band,
                             "source": mapping.source(name),
                             "scene": seen.get(name, "")})
            out.append((band, rows))
        return out

    def scene_binds(self):
        """What the scene in the preview rebound at load: name -> its name."""
        scene = getattr(getattr(self.app, "preview", None), "scene", None)
        if scene is None:
            return {}
        label = str(getattr(scene, "name", "") or "script")
        return {name: label for name, keys in
                (getattr(scene, "binds", None) or {}).items() if keys}

    def take_player_keys(self):
        """Copy the player's own rebinds into the staged table.

        The Settings tab edits the config one machine at a time; this keeps
        one table as the project's, and takes what a player changed only
        when asked.
        """
        mapping = self.stage()
        player = inputmap.config_table()
        engine = inputmap.engine_table()
        taken = 0
        for name, keys in player.items():
            if not keys or keys == engine.get(name):
                continue
            mapping.set_keys(name, keys, trigger=mapping.is_trigger(name))
            taken += 1
        if not taken:
            self.app.status = "the player config matches the engine"
            self.app.log("nothing in the player config to take", "muted")
            return False
        self.map_dirty = True
        self.app.status = f"{taken} player binding(s) staged"
        self.app.log(f"took {taken} binding(s) from the player config; "
                     "press Save to write them", "ok")
        return True

    def edit_deadzone(self):
        """One number for the whole table: how far a stick must travel."""
        mapping = self.stage()
        self.app.dialog_kind = "project:deadzone"
        self.app.dialog = widgets.PromptDialog(
            "Stick deadzone", "Value 0-1", f"{mapping.deadzone:.2f}",
            width=400, hint="How far a stick travels before an axis counts "
                            "as pressed. The engine uses 0.35.")

    def set_deadzone(self, text):
        """Write the typed deadzone into the staged map."""
        try:
            value = float(str(text).strip())
        except (TypeError, ValueError):
            self.app.log("the deadzone has to be a number", "warn")
            return False
        value = max(0.0, min(0.95, value))
        self.stage().set_tuning("deadzone", value)
        self.map_dirty = True
        self.app.status = f"deadzone {value:.2f}"
        return True

    # -- writing ---------------------------------------------------------
    def save(self):
        """Store the manifest, and the keybind table if it moved."""
        project = self.project
        if project is None:
            self.app.log("open a project to write settings into it", "warn")
            return False
        if self.map is not None and self.map_dirty:
            if not inputmap.save(project, self.map):
                self.app.log("the keybind table did not write", "error")
                return False
            self.map_dirty = False
        if self.dirty:
            try:
                project.save_meta()
            except OSError as exc:
                self.app.log(f"cannot write {loader.META_NAME}: {exc}",
                             "error")
                return False
            self.dirty = False
        # the values just written are the project's own fields now
        project.apply_meta()
        self.reload()
        self.app.log(f"{loader.META_NAME} saved", "ok")
        self.app.status = "project saved"
        return True

    def revert(self):
        """Throw unsaved values away and re-read the manifest."""
        project = self.project
        if project is None:
            return False
        path = project.path / loader.META_NAME
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.app.log(f"cannot re-read the manifest: {exc}", "error")
            return False
        if not isinstance(raw, dict):
            self.app.log(f"cannot re-read the manifest: {path.name} "
                         "is not an object", "error")
            return False
        project.meta = loader.section_meta(raw)
        project.apply_meta()
        self.project_reset()
        self.reload()
        self.app.log("manifest re-read from disk", "muted")
        self.app.status = "project re-read"
        return True

    def reload(self):
        """Hand the new values to the preview and the rest of the editor."""
        project = self.project
        if project is None:
            return
        inputmap.load(project, force=True)
        self.app.settings.refresh()
        try:
            self.app.preview.reload()
        except Exception as exc:                       # noqa: BLE001
            self.app.log(f"preview: {exc}", "warn")

    def reset_keys(self):
        """Back to the engine's own keymap: nothing of this project's."""
        self.map = inputmap.InputMap.defaults()
        self.map_dirty = True
        self.app.log("keybinds back to the engine defaults; press Save",
                     "muted")
        self.app.status = "keybinds reset"

    def add_trigger(self, name):
        """Name a new trigger, ready for a key."""
        clean = str(name or "").strip().replace(" ", "_")
        if not clean:
            return None
        mapping = self.stage()
        if mapping.own(clean) is not None:
            self.app.log(f"{clean} is already bound", "warn")
            return None
        mapping.add(clean, (), trigger=True)
        self.map_dirty = True
        self.app.log(f"trigger {clean} added", "ok")
        return clean

    def drop_binding(self, band, name):
        """Remove one name from the staged table."""
        mapping = self.stage()
        if band != "triggers" and mapping.is_trigger(name):
            self.app.log(f"{name} is a trigger; use its minus sign", "warn")
            return False
        mapping.remove(name)
        self.map_dirty = True
        self.app.log(f"{name} removed; press Save to write it", "muted")
        self.app.status = f"{name} removed"
        return True

    # -- events ----------------------------------------------------------
    def handle_event(self, e):
        if self.capture is not None and e.type in settingstab.CAPTURE_EVENTS:
            return self._captured(e)
        if e.type == pygame.MOUSEWHEEL:
            if self.list_rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll = max(0, self.scroll - e.y * 2 * self.row_h)
                return True
            return False
        if e.type == pygame.KEYDOWN:
            return False        # a key is only ever a capture, handled above
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            return self._press(e.pos)
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
            return self._right(e.pos)
        return False

    def _captured(self, e):
        """Store the pressed control against the waiting binding."""
        band, name = self.capture
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.capture = None
            self.app.status = "capture cancelled"
            return True
        token = settingstab.capture_token(e)
        if token is None:
            return True
        mapping = self.stage()
        keys = list(mapping.keys_of(name))
        if not getattr(e, "mod", 0) & pygame.KMOD_SHIFT:
            keys = []
        if token not in keys:
            keys.append(token)
        mapping.set_keys(name, keys, trigger=band == "triggers")
        self.map_dirty = True
        self.capture = None
        clashes = [other for token, names in mapping.conflicts()
                   if token == keys[-1] for other in names if other != name]
        self.app.status = f"{name} -> {settingstab.token_label(keys[-1])}"
        if clashes:
            self.app.log(f"{settingstab.token_label(keys[-1])} is shared "
                         f"with {', '.join(clashes)}", "warn")
        return True

    def _press(self, pos):
        for name, rect in self.buttons.items():
            if rect.collidepoint(pos):
                self._button(name)
                return True
        for index, rect in enumerate(self.rail_rects):
            if rect.collidepoint(pos):
                self.section = SECTIONS[index]
                self.scroll = 0
                self.app.status = f"{TITLES[self.section]}"
                return True
        if not self.list_rect.collidepoint(pos):
            return False
        if self.section == "input":
            return self._press_bind(pos)
        for row, rect in self.rows:
            if not rect.collidepoint(pos):
                continue
            self.focus = row.name
            self.edit(row, pygame.mouse.get_pos())
            return True
        return True

    def _press_bind(self, pos):
        """A binding cell arms a capture; a minus sign drops a trigger."""
        if self.deadzone_rect.collidepoint(pos):
            self.edit_deadzone()
            return True
        for name, rect in self.minus_rects:
            if rect.collidepoint(pos):
                self.drop_binding("triggers", name)
                return True
        for band, name, rect in self.keys_rects:
            if rect.collidepoint(pos):
                self.capture = (band, name)
                self.focus = f"{band}.{name}"
                self.app.status = f"press a control for {name}"
                return True
        return True

    def _right(self, pos):
        """RMB clears one binding, or the row under it."""
        if self.section == "input":
            for band, name, rect in self.keys_rects:
                if rect.collidepoint(pos):
                    mapping = self.stage()
                    mapping.set_keys(name, [],
                                     trigger=band == "triggers")
                    self.map_dirty = True
                    self.app.status = f"{name} unbound"
                    return True
            return False
        for row, rect in self.rows:
            if not rect.collidepoint(pos):
                continue
            self.focus = row.name
            if self.clear(row):
                self.app.status = f"{row.name} cleared"
            return True
        return False

    def edit(self, row, pos):
        """One click on one manifest row, in its kind's idiom."""
        if row.kind == "bool":
            self.write(row, not bool(self.value(row)))
            return
        if row.kind == "choice":
            self.cycle(row)
            return
        if row.kind == "color":
            self.app.pick_color(row.label, to_hex(self.value(row), "#808080"),
                                lambda text, row=row: self._color_ok(row,
                                                                     text),
                                hint=row.help)
            return
        if row.kind == "scene":
            self._choose_scene(row)
            return
        if row.kind == "track":
            self._choose_track(row)
            return
        if row.kind == "post":
            self._choose_post(row)
            return
        self._prompt(row)

    def cycle(self, row, step=1):
        choices = list(row.choices)
        if not choices:
            return None
        current = str(self.value(row) or "")
        try:
            index = choices.index(current)
        except ValueError:
            index = 0
        return self.write(row, choices[(index + step) % len(choices)])

    def _answer(self, kind, text):
        """A dialog's answer, routed back to the row or binding it is for."""
        if kind.startswith("row:"):
            row = self.find(kind[4:])
            if row is None:
                return False
            self.write(row, self.parse(row, text))
            self.app.log(f"{row.name} = {self.text_of(row)!r}", "ok")
            return True
        if kind.startswith("scene:"):
            row = self.find(kind[6:])
            if row is None or not text:
                return False
            self.write(row, str(text))
            self.app.log(f"{row.name} = {text}", "ok")
            return True
        if kind.startswith("track:"):
            row = self.find(kind[6:])
            if row is None:
                return False
            self.write(row, "" if str(text).startswith("(") else str(text))
            return True
        if kind.startswith("post:"):
            row = self.find(kind[5:])
            if row is None or not text:
                return False
            got = list(loader.name_list(self.value(row)))
            if text == "(none)":
                got = []
            elif text in got:
                got.remove(text)
            else:
                got.append(text)
            self.write(row, got)
            self.app.log(f"{row.name} = {', '.join(got) or '(none)'}", "ok")
            return True
        if kind == "trigger":
            self.add_trigger(text)
            return True
        if kind == "deadzone":
            self.set_deadzone(text)
            return True
        return False

    def parse(self, row, text):
        """Typed text, in the type this row's key wants."""
        raw = str(text or "").strip()
        if not raw:
            return None
        if row.kind == "bool":
            return raw.lower() in ("1", "on", "true", "yes")
        if row.kind == "color":
            return from_hex(raw)
        if row.kind in ("pair", "list"):
            got = loader.number_list(raw)
            return list(got) if got else raw
        if row.kind == "post":
            return list(loader.name_list(raw))
        if row.kind == "number":
            got = loader.number_list(raw)
            if not got:
                return raw
            value = got[0]
            if row.key in ("fps_cap", "bake_size", "seed"):
                return int(round(value))
            return value
        return raw

    def find(self, name):
        """One row by `section.key`, anywhere in the manifest."""
        return spec_of(name)

    # -- dialogs ---------------------------------------------------------
    def _prompt(self, row):
        """Type a value this row's control cannot offer directly."""
        self.app.dialog_kind = f"project:row:{row.name}"
        self.app.dialog = widgets.PromptDialog(
            row.label, "Value", self.text_of(row), hint=row.help,
            width=430)

    def _choose_scene(self, row):
        """Pick one of the project's scenes for `start`."""
        project = self.project
        names = list(project.scene_names()) if project is not None else []
        if not names:
            self._prompt(row)
            return
        self.app.dialog_kind = f"project:scene:{row.name}"
        self.app.dialog = widgets.ChoiceDialog(
            row.label, "Which scene does the game open on?", tuple(names),
            hint=row.help, default=max(0, names.index(str(self.value(row)))
                                       ) if str(self.value(row)) in names
            else 0)

    def _choose_track(self, row):
        """Pick the file in audio/ that starts on boot, or none."""
        project = self.project
        stems = sorted(p.stem for p in project.audio_files()) \
            if project is not None else []
        names = ("(no track)",) + tuple(stems)
        current = str(self.value(row) or "")
        self.app.dialog_kind = f"project:track:{row.name}"
        self.app.dialog = widgets.ChoiceDialog(
            row.label, "Music that starts when the game does", names,
            hint=row.help, default=max(0, names.index(current))
            if current in names else 0)

    def _choose_post(self, row):
        """Add or drop one screen shader in a post chain."""
        project = self.project
        names = ()
        if project is not None:
            got = [n for n in project.shader_names()
                   if project.shader_class(n) is not None
                   and (project.shader_doc(n) or {}).get("mode") == "screen"]
            names = ("(none)",) + tuple(got)
        if not names:
            self._prompt(row)
            return
        self.app.dialog_kind = f"project:post:{row.name}"
        self.app.dialog = widgets.ChoiceDialog(
            row.label, "Click a look to add it, or to drop it again", names,
            hint=row.help)

    def _color_ok(self, row, text):
        """The picker's `#rrggbb` answer, back into the manifest."""
        if row.kind == "color":
            self.write(row, from_hex(text))
            return
        self.write(row, text)

    # -- buttons ---------------------------------------------------------
    def _button(self, name):
        if name == "save":
            self.save()
        elif name == "revert":
            self.revert()
        elif name == "add":
            self.app.dialog_kind = "project:trigger"
            self.app.dialog = widgets.PromptDialog(
                "New trigger", "Name", "toggle_spot", width=400,
                hint="A trigger is a named input: press its key and every "
                     "scene and object with on_trigger hears that name.")
        elif name == "player":
            self.take_player_keys()
        elif name == "deadzone":
            self.edit_deadzone()
        elif name == "reset":
            self.reset_keys()

    # -- drawing ---------------------------------------------------------
    def draw(self, surface, area, dt):
        self.area = pygame.Rect(area)
        pygame.draw.rect(surface, xp.PANEL, area)
        head = pygame.Rect(area.x, area.y, area.width, self.head_h)
        project = self.project
        widgets.header(surface, head, "Project", self.app.fonts["normal"],
                       right=str(project.path.name) if project is not None
                       else "no project")
        bar = pygame.Rect(area.x + 8, head.bottom + 6, area.width - 16,
                          self.button_h)
        body = pygame.Rect(area.x + 8, bar.bottom + 8, area.width - 16,
                           area.bottom - bar.bottom - 16)
        self._draw_buttons(surface, bar)
        self.rail_rects = []
        self.rows = []
        self.minus_rects = []
        self.keys_rects = []
        if project is None:
            self.list_rect = body
            self.side_rect = pygame.Rect(body.x, body.bottom, 0, 0)
            self._draw_hint(surface, body, "open a project to edit its "
                                          "manifest")
            return
        rail = pygame.Rect(body.x, body.y, RAIL_W, body.height)
        self._draw_rail(surface, rail)
        # the pane takes a little over half the body, the notes all of what
        # is left - a binding cell must land inside `list_rect` to be clickable
        room = max(140, body.right - rail.right - 12)
        left = pygame.Rect(rail.right + 8, body.y,
                           max(140, min(int(body.width * 0.58), room)),
                           body.height)
        self.list_rect = left
        self.side_rect = pygame.Rect(left.right + 10, body.y,
                                     body.right - left.right - 10,
                                     body.height)
        if self.section == "input":
            self._draw_binds(surface, left)
        else:
            self._draw_list(surface, left)
        self._draw_side(surface)

    def _draw_hint(self, surface, rect, text):
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        img = widgets.cached_text(self.app.fonts["small"], text,
                                  xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (rect.x + 10, rect.y + 10))

    def _draw_buttons(self, surface, bar):
        fonts = self.app.fonts
        specs = [("save", "Save", True), ("revert", "Revert", False)]
        if self.section == "input":
            specs += [("add", "+ Trigger", False), ("player", "Player", False),
                      ("reset", "Reset", False)]
        x = bar.x
        mouse = pygame.mouse.get_pos()
        self.buttons = {}
        for name, label, default in specs:
            width = max(70, fonts["normal"].size(label)[0] + 22)
            rect = pygame.Rect(x, bar.y, width, bar.height)
            xp.button(surface, rect, label, fonts["normal"], default=default,
                      hovered=rect.collidepoint(mouse))
            self.buttons[name] = rect
            x += width + 6
        note = self.pending_note()
        if note:
            img = widgets.cached_text(fonts["small"], note, xp.LINK)
            surface.blit(img, (x + 8, bar.centery - img.get_height() // 2))

    def pending_note(self):
        """What has not reached the file yet, in one line."""
        parts = []
        if self.dirty:
            parts.append("manifest values changed")
        if self.map_dirty:
            parts.append("input map changed")
        return "; ".join(parts)

    def _draw_rail(self, surface, rect):
        fonts = self.app.fonts
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        mouse = pygame.mouse.get_pos()
        inner = rect.inflate(-4, -4)
        self.rail_rects = []
        y = inner.y + 2
        for name in SECTIONS:
            cell = pygame.Rect(inner.x, y, inner.width, self.head_h - 2)
            active = name == self.section
            if cell.collidepoint(mouse) or active:
                pygame.draw.rect(surface, xp.SELECTION if active
                                 else xp.CARD_BG, cell)
            img = widgets.cached_text(fonts["small"], TITLES[name],
                                      xp.SELECT_TEXT if active else xp.TEXT)
            if img is not None:
                surface.blit(img, (cell.x + 6,
                                   cell.centery - img.get_height() // 2))
            self.rail_rects.append(cell)
            y += cell.height + 1
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        widgets.header(surface, head, "", fonts["small"])

    def _draw_list(self, surface, rect):
        fonts = self.app.fonts
        head = pygame.Rect(rect.x, rect.y, rect.width, self.head_h - 4)
        widgets.header(surface, head, TITLES[self.section], fonts["small"],
                       right=loader.META_NAME)
        panel = pygame.Rect(rect.x, head.bottom + 2, rect.width,
                            rect.height - head.height - 4)
        pygame.draw.rect(surface, xp.FIELD, panel)
        xp.sunken(surface, panel)
        inner = panel.inflate(-6, -6)
        rows = self.form_rows()
        content = len(rows) * self.row_h
        self.scroll = min(self.scroll, max(0, content - inner.height))
        mouse = pygame.mouse.get_pos()
        old = surface.get_clip()
        surface.set_clip(inner)
        y = inner.y - self.scroll
        for row in rows:
            cell = pygame.Rect(inner.x, y, inner.width, self.row_h)
            if cell.bottom > inner.y and cell.y < inner.bottom:
                self._draw_row(surface, cell, row, cell.collidepoint(mouse))
                self.rows.append((row, cell))
            y += self.row_h
        if not rows:
            img = widgets.cached_text(fonts["small"], "nothing in this "
                                                     "section", xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (inner.x + 6, inner.y + 6))
        surface.set_clip(old)
        if content > inner.height:
            xp.scrollbar(surface, pygame.Rect(panel.right - 13, panel.y + 2,
                                              11, panel.height - 4),
                         self.scroll / max(1, content),
                         inner.height / max(1, content))

    def _draw_row(self, surface, row_rect, row, hovered):
        fonts = self.app.fonts
        if hovered:
            pygame.draw.rect(surface, xp.CARD_BG, row_rect)
        cy = row_rect.centery
        value = self.value(row)
        if value is not None:
            pygame.draw.rect(surface, xp.MODIFIED,
                             (row_rect.x + 1, row_rect.y + 4, 2,
                              row_rect.height - 8))
        img = widgets.cached_text(fonts["small"], row.label,
                                  xp.LINK if self.focus == row.name
                                  else xp.TEXT_MUTED)
        surface.blit(img, (row_rect.x + 8, cy - img.get_height() // 2))
        right = row_rect.right - READ_W - 6
        control = pygame.Rect(row_rect.x + LABEL_W, row_rect.y + 3,
                              max(40, right - row_rect.x - LABEL_W - 6),
                              row_rect.height - 6)
        if row.kind == "bool":
            xp.checkbox(surface, (control.x, cy), bool(value), "",
                        fonts["small"])
        elif row.kind == "choice":
            box = pygame.Rect(right - 118, row_rect.y + 3, 116,
                              row_rect.height - 6)
            xp.combo(surface, box, str(value or row.choices[0]),
                     fonts["small"], hovered=hovered)
        elif hovered:
            xp.field(surface, control)
        img = widgets.cached_text(fonts["small"], self.text_of(row),
                                  xp.TEXT if value is not None
                                  else xp.TEXT_MUTED)
        surface.blit(img, (right + 4, cy - img.get_height() // 2))
        if hovered:
            pygame.draw.rect(surface, xp.SELECT_BORDER, row_rect, 1)

    def _draw_binds(self, surface, rect):
        """One table, two bands: actions then triggers."""
        fonts = self.app.fonts
        head = pygame.Rect(rect.x, rect.y, rect.width, self.head_h - 4)
        widgets.header(surface, head, TITLES[self.section], fonts["small"],
                       right="press a cell, then a control")
        panel = pygame.Rect(rect.x, head.bottom + 2, rect.width,
                            rect.height - head.height - 4)
        pygame.draw.rect(surface, xp.FIELD, panel)
        xp.sunken(surface, panel)
        inner = panel.inflate(-6, -6)
        bands = self.bind_rows()
        content = sum(len(rows) + 1 for _b, rows in bands) * self.row_h \
            + self.row_h
        self.scroll = min(self.scroll, max(0, content - inner.height))
        mouse = pygame.mouse.get_pos()
        name_w = max(90, int(inner.width * 0.26))
        keys_w = max(90, int(inner.width * 0.30))
        y = inner.y - self.scroll
        old = surface.get_clip()
        surface.set_clip(inner)
        for band, rows in bands:
            strip = pygame.Rect(inner.x, y, inner.width, self.row_h)
            if strip.bottom > inner.y and strip.y < inner.bottom:
                self._band_head(surface, strip, band, len(rows), fonts)
            y += self.row_h
            for info in rows:
                cell = pygame.Rect(inner.x, y, inner.width, self.row_h)
                if cell.bottom > inner.y and cell.y < inner.bottom:
                    self._bind_row(surface, cell, info, name_w, keys_w,
                                   mouse)
                y += self.row_h
        footer = pygame.Rect(inner.x, y, inner.width, self.row_h)
        if footer.bottom > inner.y and footer.y < inner.bottom:
            self._deadzone_row(surface, footer, fonts, mouse)
        else:
            self.deadzone_rect = pygame.Rect(0, 0, 0, 0)
        surface.set_clip(old)
        if content > inner.height:
            xp.scrollbar(surface, pygame.Rect(panel.right - 13, panel.y + 2,
                                              11, panel.height - 4),
                         self.scroll / max(1, content),
                         inner.height / max(1, content))

    def _band_head(self, surface, rect, band, count, fonts):
        pygame.draw.rect(surface, xp.FIELD_ALT, rect)
        pygame.draw.line(surface, xp.OUTLINE, (rect.x, rect.bottom - 1),
                         (rect.right - 1, rect.bottom - 1))
        label = "Actions  (polled every frame)" if band == "actions" \
            else "Triggers  (a press broadcasts)"
        img = widgets.cached_text(fonts["small"],
                                  f"{label}   {count}", xp.LINK)
        if img is not None:
            surface.blit(img, (rect.x + 6,
                               rect.centery - img.get_height() // 2))

    def _bind_row(self, surface, cell, info, name_w, keys_w, mouse):
        """Name, its keys, and what it does; the cell is the capture."""
        fonts = self.app.fonts
        hovered = cell.collidepoint(mouse)
        if hovered:
            pygame.draw.rect(surface, xp.CARD_BG, cell)
        cy = cell.centery
        name = info["name"]
        img = widgets.cached_text(fonts["small"], name,
                                  xp.TEXT if info["here"] else xp.TEXT_MUTED)
        surface.blit(img, (cell.x + 6, cy - img.get_height() // 2))
        if info["band"] == "triggers":
            sign = pygame.Rect(cell.x + name_w - 16, cell.y + 4, 14,
                               cell.height - 8)
            mark = widgets.cached_text(fonts["small"], "\u2212", xp.LOG_WARN)
            if mark is not None:
                surface.blit(mark, (sign.x + 2,
                                    sign.centery - mark.get_height() // 2))
            self.minus_rects.append((name, sign))
        keys = pygame.Rect(cell.x + name_w + 4, cell.y + 3,
                           max(40, keys_w), cell.height - 6)
        grabbing = self.capture == (info["band"], name)
        if grabbing or hovered:
            xp.field(surface, keys)
        text = settingstab.binding_label(info["keys"]) \
            if info["keys"] else "press a control..." if grabbing \
            else "(unbound)"
        img = widgets.cached_text(fonts["small"], text,
                                  xp.LINK if grabbing else
                                  xp.LOG_WARN if info["note"] else xp.TEXT)
        if img is not None and img.get_width() <= keys.width:
            surface.blit(img, (keys.x + 4, cy - img.get_height() // 2))
        elif img is not None:
            surface.blit(widgets.cached_text(
                fonts["small"], widgets.elide(fonts["small"], text,
                                              keys.width - 8),
                                  xp.LINK if grabbing else xp.TEXT),
                (keys.x + 4, cy - img.get_height() // 2))
        self.keys_rects.append((info["band"], name, keys))
        bits = [info["what"], info["source"]]
        if info["scene"]:
            bits.append(f"{info['scene']} rebinds it")
        if info["note"]:
            bits.append(info["note"])
        what = " - ".join(bits)
        room = max(20, cell.right - keys.right - 12)
        if fonts["small"].size(what)[0] > room:
            what = widgets.elide(fonts["small"], what, room)
        img = widgets.cached_text(fonts["small"], what,
                                  xp.LOG_WARN if info["note"]
                                  else xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (keys.right + 8, cy - img.get_height() // 2))
        if hovered:
            pygame.draw.rect(surface, xp.SELECT_BORDER, cell, 1)

    def _deadzone_row(self, surface, cell, fonts, mouse):
        """The one number the table shares, under both bands."""
        hovered = cell.collidepoint(mouse)
        if hovered:
            pygame.draw.rect(surface, xp.CARD_BG, cell)
        cy = cell.centery
        img = widgets.cached_text(fonts["small"], "Stick deadzone",
                                  xp.TEXT_MUTED)
        surface.blit(img, (cell.x + 6, cy - img.get_height() // 2))
        box = pygame.Rect(cell.x + max(96, int(cell.width * 0.26)),
                          cell.y + 3, 66, cell.height - 6)
        if hovered:
            xp.field(surface, box)
        img = widgets.cached_text(fonts["small"],
                                  f"{self.stage().deadzone:.2f}", xp.TEXT)
        surface.blit(img, (box.x + 6, cy - img.get_height() // 2))
        note = "how far a stick travels before an axis counts pressed"
        room = cell.right - box.right - 12
        if fonts["small"].size(note)[0] > room:
            note = widgets.elide(fonts["small"], note, max(20, room))
        img = widgets.cached_text(fonts["small"], note, xp.TEXT_MUTED)
        surface.blit(img, (box.right + 8, cy - img.get_height() // 2))
        self.deadzone_rect = cell

    def _draw_side(self, surface):
        fonts = self.app.fonts
        rect = self.side_rect
        if rect.width <= 0:
            return
        head = pygame.Rect(rect.x, rect.y, rect.width, self.head_h - 4)
        widgets.header(surface, head, TITLES[self.section], fonts["small"])
        y = head.bottom + 6
        width = max(60, rect.width - 6)
        for line in widgets.wrap(fonts["small"], BLURBS[self.section],
                                 width):
            img = widgets.cached_text(fonts["small"], line, xp.TEXT)
            surface.blit(img, (rect.x + 2, y))
            y += fonts["small"].get_height() + 2
        y += 8
        row = self.focused_row()
        if row is not None:
            for label, value in (("key", row.name),
                                 ("kind", row.kind),
                                 ("value", self.text_of(row)),
                                 ("stored", "in the file"
                                  if self.value(row) is not None
                                  else "not in the file")):
                img = widgets.cached_text(fonts["small"], label,
                                          xp.TEXT_MUTED)
                surface.blit(img, (rect.x + 2, y))
                img = widgets.cached_text(fonts["small"], value, xp.TEXT)
                surface.blit(img, (rect.x + 74, y))
                y += fonts["small"].get_height() + 2
            y += 4
            for line in widgets.wrap(fonts["small"], row.help, width):
                img = widgets.cached_text(fonts["small"], line, xp.TEXT)
                surface.blit(img, (rect.x + 2, y))
                y += fonts["small"].get_height() + 2
            y += 8
        note = ("Click a keys cell, then press a key, mouse button, wheel "
                "notch or pad control. Shift and a second control adds "
                "another. Right-click a cell to clear it, and the minus "
                "takes a trigger out. A shared control is noted, not "
                "refused. The tail of a row says where its keys came from: "
                "the project, the player's own config, or the engine."
                if self.section == "input" else
                "Click a switch to toggle it, a colour to pick it, a name "
                "to choose it, a value to type it. Right-click puts a "
                "value back the way the engine has it.")
        for line in widgets.wrap(fonts["small"], note, width):
            img = widgets.cached_text(fonts["small"], line, xp.TEXT_MUTED)
            surface.blit(img, (rect.x + 2, y))
            y += fonts["small"].get_height() + 2
        y += 8
        for label, value in self.store_rows():
            img = widgets.cached_text(fonts["small"], label, xp.TEXT_MUTED)
            surface.blit(img, (rect.x + 2, y))
            img = widgets.cached_text(fonts["small"], value, xp.LINK)
            surface.blit(img, (rect.x + 74, y))
            y += fonts["small"].get_height() + 2

    def focused_row(self):
        """The row the help column is describing, if it still exists."""
        if not self.focus or self.section == "input":
            return None
        for row in self.form_rows():
            if row.name == self.focus:
                return row
        return None

    def store_rows(self):
        """Where this project's settings live, and what it holds."""
        project = self.project
        if project is None:
            return ()
        got = [("file", loader.META_NAME),
               ("format", str(project.file_format))]
        for section in SECTIONS:
            if section == "game":
                continue
            block = project.get(section)
            got.append((section, str(len(block or {})) + " key(s)"))
        return tuple(got)

    def info(self):
        """Lines for the Inspector."""
        project = self.project
        if project is None:
            return [("Page", "Project"), ("Project", "none open")]
        mapping = self.stage()
        rows = [("Page", TITLES[self.section]),
                ("Manifest", str(project.path.name)),
                ("Actions", str(len(mapping.actions))),
                ("Triggers", str(len(mapping.triggers)))]
        note = self.pending_note()
        if note:
            rows += [("-", ""), ("Unsaved", note)]
        return rows
