"""The Settings tab: every configuration key, live-applied, in one form."""

import os
import subprocess
import sys

import pygame

from .. import const
from ..engine import config, xp
from ..engine import input as engine_input
from . import widgets

ROW_H = 26           # floor values; the real metrics come from the fonts
HEAD_H = 24
BUTTON_H = 26
LABEL_W = 176          # the name column
READ_W = 60            # the value readout on the right

# a waiting capture swallows the click, not the row press
CAPTURE_EVENTS = (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL,
                  pygame.JOYBUTTONDOWN, pygame.JOYAXISMOTION)

# keys store pygame names; these read better in bindings
KEY_LABELS = {"escape": "Esc", "lshift": "L-Shift", "rshift": "R-Shift",
              "lctrl": "L-Ctrl", "rctrl": "R-Ctrl", "lalt": "L-Alt",
              "ralt": "R-Alt", "capslock": "Caps", "pageup": "PgUp",
              "pagedown": "PgDn", "return": "Enter", "backslash": "\\"}


def key_label(name):
    """Display text for one stored key name."""
    name = str(name)
    return KEY_LABELS.get(name) or (name.upper() if len(name) == 1
                                    else name.capitalize())


# non-key bindings, spelled the way `engine.input` writes them
MOUSE_LABELS = {"mouse:left": "Mouse L", "mouse:middle": "Mouse M",
                "mouse:right": "Mouse R", "mouse:x1": "Mouse X1",
                "mouse:x2": "Mouse X2"}
WHEEL_LABELS = {"wheel:up": "Wheel Up", "wheel:down": "Wheel Down"}


def token_label(name):
    """Display text for one binding name, key or otherwise."""
    name = str(name).lower()
    got = MOUSE_LABELS.get(name) or WHEEL_LABELS.get(name)
    if got:
        return got
    if name.startswith("joy"):
        pad, _, rest = name.partition(":")
        if rest.startswith("button"):
            return f"Pad {pad[3:]} B{rest[6:]}"
        if rest.startswith("axis"):
            return f"Pad {pad[3:]} {rest[4:]}"
        return name
    return key_label(name)


def binding_label(names):
    return "  +  ".join(token_label(n) for n in (names or ())) or "(none)"


# the controls a binding cell may hold, in `engine.input` spelling
TOKEN_KEYS = ("w", "a", "s", "d", "up", "down", "left", "right",
              "space", "lshift", "lctrl", "lalt", "tab", "return",
              "escape", "backspace", "f1", "f2", "f3", "f4", "f5",
              "f6", "f7", "f8", "f9", "f10", "f11", "f12", "e", "q",
              "r", "t", "g", "c", "v", "b", "h", "j", "k", "l", "m",
              "n", "o", "p", "u", "i", "y", "z", "x", "1", "2", "3",
              "4", "5", "6", "7", "8", "9", "0")
TOKEN_POINTER = ("mouse:left", "mouse:middle", "mouse:right", "mouse:x1",
                 "mouse:x2", "wheel:up", "wheel:down")
TOKEN_PADS = 2
TOKEN_BUTTONS = 12
TOKEN_AXES = ("axis+0", "axis-0", "axis+1", "axis-1")


def token_words():
    """Every control one binding cell can hold, commonest first."""
    out = list(TOKEN_KEYS) + list(TOKEN_POINTER)
    for pad in range(TOKEN_PADS):
        out += [f"joy{pad}:button{i}" for i in range(TOKEN_BUTTONS)]
        out += [f"joy{pad}:{axis}" for axis in TOKEN_AXES]
    return tuple(out)


def capture_token(e):
    """The binding name an event would store, or None."""
    if e.type == pygame.KEYDOWN:
        token = ("key", e.key)
    elif e.type == pygame.MOUSEBUTTONDOWN:
        notch = engine_input.WHEEL_BUTTONS.get(e.button)
        if notch is not None:
            token = ("wheel", notch)
        elif e.button in engine_input.MOUSE_NAMES:
            token = ("mouse", e.button)
        else:
            return None
    elif e.type == pygame.MOUSEWHEEL:
        if not e.y:
            return None
        token = ("wheel", 1.0 if e.y > 0 else -1.0)
    elif e.type == pygame.JOYBUTTONDOWN:
        token = ("joybutton", engine_input.pad_for_instance(e.joy), e.button)
    elif e.type == pygame.JOYAXISMOTION:
        if abs(e.value) < engine_input.DEADZONE:
            return None
        token = ("joyaxis", engine_input.pad_for_instance(e.joy), e.axis,
                 1.0 if e.value > 0 else -1.0)
    else:
        return None
    return engine_input.binding_text(token)


class SettingsTab:
    """Scrollable, grouped settings page over the config schema."""

    def __init__(self, app):
        self.app = app
        self.cfg = config.load(getattr(app, "project", None))
        self.group = config.GROUPS[0]
        self.scroll = 0
        self.rows = []             # (kind, payload, rect) hit targets
        self.tracks = {}           # key -> slider track rect
        self.buttons = {}
        self.head_rects = []
        self.area = pygame.Rect(0, 0, 0, 0)
        self.list_rect = pygame.Rect(0, 0, 0, 0)
        self.side_rect = pygame.Rect(0, 0, 0, 0)
        self.drag = None           # key whose slider thumb is held
        self.capture = None        # key waiting for a control
        self.clash = {}            # binding name -> keys using it
        self.focus = None          # last touched key, for the help column
        self._metrics()

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

    def set_project(self, project):
        self.cfg = config.load(project)
        self.scroll = 0

    def refresh(self):
        """Re-read the merged view; a file may have changed."""
        self.cfg = config.load(self.app.project)
        self.cfg.reload(self.app.project)

    def info(self):
        cfg = self.cfg
        changed = [e.key for e in config.SCHEMA if cfg.changed(e.key)]
        rows = [("Page", self.group.capitalize()),
                ("Changed", str(len(changed))),
                ("User file", str(config.user_path())),
                ("Layers", ", ".join(n for n, _ in cfg.layers) or "defaults"),
                ("Project", "yes" if cfg.project is not None else "none")]
        if self.focus:
            rows += [("-", ""),
                     ("Key", self.focus),
                     ("From", cfg.source(self.focus)),
                     ("Value", repr(cfg.get(self.focus))),
                     ("Default", repr(config.DEFAULTS.get(self.focus)))]
        return rows

    def entries(self):
        return [e for e in config.SCHEMA if e.group == self.group]

    def entry(self, key):
        return config.BY_KEY.get(key)

    def binding_conflicts(self):
        """`{binding name: [input.* key, ...]}` for a name used twice."""
        seen = {}
        for entry in config.SCHEMA:
            if entry.kind != "list" or entry.group != "input":
                continue
            for name in self.cfg.get(entry.key) or ():
                seen.setdefault(str(name).lower(), []).append(entry.key)
        return {name: keys for name, keys in seen.items() if len(keys) > 1}

    def clash_note(self, entry):
        """Other keys sharing this binding, or ''."""
        if entry is None or entry.kind != "list":
            return ""
        for name in self.cfg.get(entry.key) or ():
            others = [k for k in self.clash.get(str(name).lower(), ())
                      if k != entry.key]
            if others:
                return f"{token_label(name)} also on {', '.join(others)}"
        return ""

    def text_of(self, entry):
        return self._format(entry, self.cfg.get(entry.key))

    @staticmethod
    def _format(entry, value):
        if entry.kind == "int":
            return str(int(value))
        if entry.kind == "float":
            return f"{float(value):g}"
        if entry.kind == "list":
            return binding_label(value)
        if entry.kind == "bool":
            return "on" if value else "off"
        return str(value)

    def frac(self, entry):
        """Slider position for a ranged number, else None."""
        if entry.lo is None or entry.hi is None or entry.hi <= entry.lo:
            return None
        value = float(self.cfg.get(entry.key))
        return (value - entry.lo) / (entry.hi - entry.lo)

    def set_frac(self, entry, frac):
        """Snap a slider position to a value and apply it."""
        span = entry.hi - entry.lo
        steps = 200.0
        raw = entry.lo + max(0.0, min(1.0, frac)) * span
        raw = round(raw * steps) / steps
        if entry.kind == "int":
            raw = int(round(raw))
        return self.apply(entry, raw, commit=False)

    def apply(self, entry, value, commit=True):
        """Write one key, push it live, optionally save."""
        got = self.cfg.set(entry.key, value)
        if got is None:
            self.app.log(f"{entry.key}: rejected {value!r}", "warn")
            return None
        value = self.cfg.get(entry.key)
        self.focus = entry.key
        if entry.kind == "list":
            # a fresh binding may have just clashed with another action
            self.clash = self.binding_conflicts()
        self.app.apply_setting(entry.key, value)
        if commit:
            self.cfg.save()
            self.app.log(f"{entry.key} = {self.text_of(entry)!r}", "ok")
        return value

    def cycle(self, entry, step=1):
        choices = list(entry.choices)
        if not choices:
            return None
        current = self.cfg.get(entry.key)
        try:
            index = choices.index(current)
        except ValueError:
            index = 0
        return self.apply(entry, choices[(index + step) % len(choices)])

    def reset_one(self, key):
        entry = self.entry(key)
        if entry is None:
            return None
        self.cfg.reset(key)
        self.app.apply_setting(key, entry.default)
        self.cfg.save()
        self.app.log(f"{key} back to {entry.default!r}", "muted")
        return entry.default

    def reset_group(self):
        for entry in self.entries():
            self.cfg.reset(entry.key)
            self.app.apply_setting(entry.key, entry.default)
        self.cfg.save()
        self.app.log(f"{self.group} settings reset to defaults", "ok")
        self.app.status = f"{self.group} reset"

    def revert(self):
        """Throw away unsaved session values and re-read the files."""
        self.cfg.reload(self.app.project)
        for entry in config.SCHEMA:
            self.app.apply_setting(entry.key, self.cfg.get(entry.key))
        self.app.log("settings re-read from disk", "muted")
        self.app.status = "settings re-read"

    def copy_to_project(self):
        """Store the runtime and input overrides inside project.flig."""
        project = self.app.project
        if project is None:
            self.app.log("open a project to store settings in it", "warn")
            return
        try:
            stored = self.cfg.write_project(project)
        except OSError as exc:
            self.app.log(f"cannot write {config.FILE_NAME} layer: {exc}",
                         "error")
            return
        self.cfg.reload(project)
        self.app.log(f"{len(stored)} setting(s) copied into "
                     f"{project.path.name}/{const.MANIFEST_NAME}", "ok")
        self.app.status = "project settings written"

    def handle_event(self, e):
        if self.capture is not None and e.type in CAPTURE_EVENTS:
            return self._captured(e)
        if e.type == pygame.MOUSEWHEEL:
            if self.list_rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll = max(0, self.scroll - e.y * 2 * self.row_h)
                return True
            return False
        if e.type == pygame.KEYDOWN:
            return False        # a key is only ever a capture, handled above
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            return self._press(e.pos, e)
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
            return self._right(pygame.mouse.get_pos())
        if e.type == pygame.MOUSEMOTION and self.drag:
            entry = self.entry(self.drag)
            track = self.tracks.get(self.drag)
            if entry is not None and track is not None:
                self.set_frac(entry, xp.slider_frac(track, e.pos))
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            if self.drag:
                entry = self.entry(self.drag)
                value = self.cfg.get(self.drag)
                self.drag = None
                if entry is not None:
                    self.apply(entry, value, commit=True)
            return True
        return False

    def _captured(self, e):
        """Store the pressed control as this binding, or wait."""
        key = self.capture
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.capture = None
            self.app.status = "capture cancelled"
            return True
        name = capture_token(e)
        if name is None:
            return True
        self.capture = None
        entry = self.entry(key)
        if entry is not None:
            self.apply(entry, [name])
            self.app.status = f"{key} -> {token_label(name)}"
            others = [k for k in self.clash.get(name, ()) if k != key]
            if others:
                self.app.log(f"{token_label(name)} is also bound to "
                             f"{', '.join(others)}", "warn")
        return True

    def _press(self, pos, e):
        for name, rect in self.buttons.items():
            if rect.collidepoint(pos):
                self._button(name)
                return True
        for i, rect in enumerate(self.head_rects):
            if rect.collidepoint(pos):
                self.group = config.GROUPS[i]
                self.scroll = 0
                self.app.status = f"{self.group} settings"
                return True
        if not self.list_rect.collidepoint(pos):
            return False
        for kind, payload, rect in self.rows:
            if not rect.collidepoint(pos):
                continue
            self.focus = payload.key
            if kind == "slider":
                self.drag = payload.key
                self.set_frac(payload, xp.slider_frac(
                    self.tracks[payload.key], pos))
            elif kind == "bool":
                self.cycle_bool(payload)
            elif kind == "choice":
                self.cycle(payload, 1 if e.button == 1 else -1)
            elif kind == "list":
                self.capture = payload.key
                self.app.status = f"press a control for {payload.label}"
            else:
                self.app.prompt_setting(payload.key, payload.label,
                                        str(self.cfg.get(payload.key)),
                                        payload.help)
            return True
        return True

    def _right(self, pos):
        """RMB steps a choice backwards, reverts anything else."""
        for kind, payload, rect in self.rows:
            if not rect.collidepoint(pos):
                continue
            self.focus = payload.key
            if kind == "choice":
                self.cycle(payload, -1)
            else:
                self.reset_one(payload.key)
            return True
        return False

    def cycle_bool(self, entry):
        return self.apply(entry, not bool(self.cfg.get(entry.key)))

    def commit(self):
        """Write the user layer; returns the path written, or None."""
        path = self.cfg.save()
        self.app.log(f"settings written to {path}" if path is not None
                     else "cannot write the settings file",
                     "ok" if path is not None else "error")
        return path

    def _button(self, name):
        if name == "save":
            self.commit()
        elif name == "revert":
            self.revert()
        elif name == "reset":
            self.reset_group()
        elif name == "project":
            self.copy_to_project()
        elif name == "open":
            self._reveal(config.user_path().parent)

    @staticmethod
    def _reveal(folder):
        """Show a folder in the file browser, whatever the platform."""
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(folder))           # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError:
            pass

    def draw(self, surface, area, dt):
        self.area = pygame.Rect(area)
        pygame.draw.rect(surface, xp.PANEL, area)
        head = pygame.Rect(area.x, area.y, area.width, self.head_h)
        widgets.header(surface, head, "Settings", self.app.fonts["normal"],
                       right=str(self.app.project.name)
                       if self.app.project else "no project")
        bar = pygame.Rect(area.x + 8, head.bottom + 6, area.width - 16,
                          self.button_h)
        body = pygame.Rect(area.x + 8, bar.bottom + 8, area.width - 16,
                           area.bottom - bar.bottom - 16)
        self._draw_buttons(surface, bar)
        left_w = max(340, int(body.width * 0.58))
        self.list_rect = pygame.Rect(body.x, body.y, left_w, body.height)
        self.side_rect = pygame.Rect(self.list_rect.right + 10, body.y,
                                     body.right - self.list_rect.right - 10,
                                     body.height)
        self._draw_list(surface)
        self._draw_side(surface)

    def _draw_buttons(self, surface, bar):
        fonts = self.app.fonts
        specs = (("save", "Save", True), ("revert", "Revert", False),
                 ("reset", "Reset Group", False),
                 ("project", "Copy to Project", False),
                 ("open", "Open Folder", False))
        x = bar.x
        mouse = pygame.mouse.get_pos()
        self.buttons = {}
        for name, label, default in specs:
            width = max(76, fonts["normal"].size(label)[0] + 22)
            rect = pygame.Rect(x, bar.y, width, bar.height)
            xp.button(surface, rect, label, fonts["normal"], default=default,
                      hovered=rect.collidepoint(mouse))
            self.buttons[name] = rect
            x += width + 6
        changed = sum(1 for e in config.SCHEMA if self.cfg.changed(e.key))
        img = widgets.cached_text(fonts["small"],
                                  f"{changed} key(s) differ from the default"
                                  if changed else "all values at their default",
                                  xp.LINK if changed else xp.TEXT_MUTED)
        surface.blit(img, (x + 8, bar.centery - img.get_height() // 2))

    def _draw_list(self, surface):
        fonts = self.app.fonts
        rect = self.list_rect
        strip = pygame.Rect(rect.x, rect.y, rect.width, self.head_h)
        labels = [g.capitalize() for g in config.GROUPS]
        self.head_rects = xp.tabs(surface, strip, labels,
                                  config.GROUPS.index(self.group), fonts["small"])
        panel = pygame.Rect(rect.x, strip.bottom + 2, rect.width,
                            rect.height - self.head_h - 2)
        pygame.draw.rect(surface, xp.FIELD, panel)
        xp.sunken(surface, panel)
        inner = panel.inflate(-6, -6)

        entries = self.entries()
        self.clash = self.binding_conflicts()
        content_h = len(entries) * self.row_h
        max_scroll = max(0, content_h - inner.height)
        self.scroll = min(self.scroll, max_scroll)
        mouse = pygame.mouse.get_pos()
        self.rows = []
        self.tracks = {}
        old = surface.get_clip()
        surface.set_clip(inner)
        y = inner.y - self.scroll
        for entry in entries:
            row = pygame.Rect(inner.x, y, inner.width, self.row_h)
            if row.bottom > inner.y and row.y < inner.bottom:
                self._draw_row(surface, row, entry, row.collidepoint(mouse))
                self.rows.append((self._kind(entry), entry, row))
            y += self.row_h
        surface.set_clip(old)
        if content_h > inner.height:
            xp.scrollbar(surface, pygame.Rect(panel.right - 13, panel.y + 2,
                                              11, panel.height - 4),
                         self.scroll / max(1, content_h),
                         inner.height / max(1, content_h))

    def _kind(self, entry):
        if entry.kind == "bool":
            return "bool"
        if entry.kind == "choice":
            return "choice"
        if entry.kind == "list":
            return "list"
        if self.frac(entry) is not None:
            return "slider"
        return "number"

    def _draw_row(self, surface, row, entry, hovered):
        fonts = self.app.fonts
        if hovered:
            pygame.draw.rect(surface, xp.CARD_BG, row)
        cy = row.centery
        value = self.cfg.get(entry.key)
        changed = self.cfg.changed(entry.key)
        if changed:
            pygame.draw.rect(surface, xp.MODIFIED,
                             (row.x + 1, row.y + 4, 2, row.height - 8))
        img = widgets.cached_text(fonts["small"], entry.label,
                                  xp.LINK if changed else xp.TEXT_MUTED)
        surface.blit(img, (row.x + 8, cy - img.get_height() // 2))
        if entry.restart:
            tag = widgets.cached_text(fonts["small"], "(restart)",
                                      xp.TEXT_MUTED)
            surface.blit(tag, (row.x + 14 + img.get_width(),
                               cy - tag.get_height() // 2))
        right = row.right - READ_W - 6
        control = pygame.Rect(row.x + LABEL_W, row.y + 3,
                              max(40, right - row.x - LABEL_W - 6),
                              row.height - 6)
        kind = self._kind(entry)
        if kind == "bool":
            xp.checkbox(surface, (control.x, cy), bool(value), "",
                        fonts["small"])
        elif kind == "choice":
            box = pygame.Rect(right - 120, row.y + 3, 118, row.height - 6)
            xp.combo(surface, box, str(value), fonts["small"], hovered=hovered)
        elif kind == "slider":
            self.tracks[entry.key] = control
            xp.slider(surface, control, self.frac(entry),
                      live=self.drag == entry.key)
        elif kind == "list":
            grabbing = self.capture == entry.key
            clash = any(str(n).lower() in self.clash for n in (value or ()))
            colour = (xp.LINK if grabbing else
                      xp.LOG_WARN if clash else xp.TEXT)
            img = widgets.cached_text(fonts["small"],
                                      "press a control..." if grabbing
                                      else binding_label(value), colour)
            surface.blit(img, (control.x, cy - img.get_height() // 2))
        elif hovered:
            xp.field(surface, control)
        if kind in ("slider", "number", "bool"):
            img = widgets.cached_text(fonts["small"],
                                      self._format(entry, value),
                                      xp.LINK if changed else xp.TEXT)
            surface.blit(img, (right + 4, cy - img.get_height() // 2))
        if hovered:
            pygame.draw.rect(surface, xp.SELECT_BORDER, row, 1)

    def _draw_side(self, surface):
        fonts = self.app.fonts
        rect = self.side_rect
        head = pygame.Rect(rect.x, rect.y, rect.width, self.head_h - 4)
        widgets.header(surface, head, "About this setting", fonts["small"])
        entry = self.entry(self.focus) if self.focus else None
        y = head.bottom + 6
        width = max(60, rect.width - 6)
        body = entry.help if entry is not None else (
            "Click a switch to toggle it, a choice to step through its "
            "values, a binding to capture the next key, mouse button, "
            "wheel notch or pad control. Drag a slider to preview it, "
            "release to save it.")
        for line in widgets.wrap(fonts["small"], body, width):
            img = widgets.cached_text(fonts["small"], line, xp.TEXT)
            surface.blit(img, (rect.x + 2, y))
            y += fonts["small"].get_height() + 2
        y += 6
        if entry is not None:
            rows = [("key", entry.key),
                    ("kind", entry.kind),
                    ("value", repr(self.cfg.get(entry.key))),
                    ("default", repr(entry.default)),
                    ("from", self.cfg.source(entry.key))]
            if entry.choices:
                rows.append(("choices", ", ".join(entry.choices)))
            if entry.lo is not None:
                rows.append(("range", f"{entry.lo:g} .. {entry.hi:g}"))
            if entry.restart:
                rows.append(("note", "applies on the next launch"))
            for label, value in rows:
                img = widgets.cached_text(fonts["small"], label,
                                          xp.TEXT_MUTED)
                surface.blit(img, (rect.x + 2, y))
                img = widgets.cached_text(fonts["small"], value, xp.TEXT)
                surface.blit(img, (rect.x + 74, y))
                y += fonts["small"].get_height() + 2
            note = self.clash_note(entry)
            if note:
                for line in widgets.wrap(fonts["small"], note, width):
                    surface.blit(widgets.cached_text(fonts["small"], line,
                                                     xp.LOG_WARN),
                                 (rect.x + 2, y))
                    y += fonts["small"].get_height() + 2
            y += 6
        for line in widgets.wrap(fonts["small"],
                                 "Files: portable config.json beside the "
                                 "exe, then the user file here, then "
                                 "project.flig, then EMOTION_CONFIG_*.",
                                 width):
            img = widgets.cached_text(fonts["small"], line, xp.TEXT_MUTED)
            surface.blit(img, (rect.x + 2, y))
            y += fonts["small"].get_height() + 2
        img = widgets.cached_text(fonts["small"], str(config.user_path()),
                                  xp.LINK)
        surface.blit(img, (rect.x + 2, y + 4))
