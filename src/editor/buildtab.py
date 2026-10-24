"""The Build tab: every PyInstaller switch, the command and the runner.

The tab is a thin view over `engine.build.BuildConfig`: the option table in
that module decides what is listed here, so adding a switch there makes it
appear (and persist) without touching this file.

    build       start PyInstaller in a worker thread
    dry run     write the launcher and log the command line
    reset       back to the generated defaults
    open dist   reveal the output folder
    run         launch the built exe, if there is one
"""

import os
import subprocess
import sys

import pygame

from ..engine import build, xp
from . import widgets

ROW_H = 24
GROUP_H = 20
BUTTON_H = 28


class BuildTab:
    """Scrollable option editor plus a build console."""

    def __init__(self, app):
        self.app = app
        self.config = build.BuildConfig(None)
        self.scroll = 0
        self.area = pygame.Rect(0, 0, 0, 0)
        self.list_rect = pygame.Rect(0, 0, 0, 0)
        self.side_rect = pygame.Rect(0, 0, 0, 0)
        self.rows = []
        self.buttons = {}
        self.hover = None

    # ------------------------------------------------------------- project
    def set_project(self, project):
        self.config.load(project)
        self.scroll = 0

    def info(self):
        cfg = self.config
        rows = [
            ("Builder", build.BUILDER),
            ("Installed", "yes" if cfg.available() else "no - pip install"),
            ("Name", str(cfg.get("name"))),
            ("Output", "one file" if cfg.get("onefile") else "folder"),
            ("Dist", str(cfg.output_dir())),
            ("Command", str(len(cfg.command())) + " args"),
        ]
        if cfg.busy():
            rows.append(("Status", "building..."))
        elif cfg.result:
            rows.append(("Status", cfg.result))
        return rows

    # ------------------------------------------------------------- actions
    def start(self):
        if self.app.project is None:
            self.app.log("open a project before building", "warn")
            return
        if self.config.busy():
            self.app.log("a build is already running", "warn")
            return
        if not self.config.available():
            self.app.log("PyInstaller is missing: pip install pyinstaller",
                         "error")
            return
        if self.config.start() is None:
            return
        self.app.log(f"build started -> {self.config.output_dir()}", "ok")
        self.app.status = "building"

    def dry_run(self):
        entry = self.config.write_launcher()
        self.app.log(self.config.text(entry), "muted")
        self.app.status = "build command ready"

    def reset(self):
        self.config.reset(self.app.project)
        self.config.store()
        self.app.log("build options reset to defaults", "ok")
        self.app.status = "build options reset"

    def open_dist(self):
        folder = self.config.output_dir().parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.app.log(f"cannot create {folder}: {exc}", "error")
            return
        self._reveal(folder)

    def run_built(self):
        exe = self.config.executable()
        if exe is None:
            self.app.log("nothing built yet - press Build first", "warn")
            return
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        except OSError as exc:
            self.app.log(f"cannot run {exe.name}: {exc}", "error")
            return
        self.app.log(f"running {exe.name}", "ok")

    @staticmethod
    def _reveal(folder):
        try:
            if os.name == "nt":
                os.startfile(str(folder))           # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError:
            pass

    def edit(self, key):
        opt = build.option(key)
        value = self.config.get(key)
        if opt.kind == "list":
            text = "; ".join(str(v) for v in value)
        else:
            text = str(value)
        self.app.prompt_build_option(key, opt.flag, text, opt.help)

    # -------------------------------------------------------------- events
    def handle_event(self, e):
        if e.type == pygame.MOUSEWHEEL:
            if self.list_rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll = max(0, self.scroll - e.y * 3 * ROW_H)
                return True
            return False
        if e.type != pygame.MOUSEBUTTONDOWN or e.button != 1:
            return False
        pos = e.pos
        for name, rect in self.buttons.items():
            if rect.collidepoint(pos):
                self._button(name)
                return True
        for kind, payload, rect in self.rows:
            if kind == "option" and rect.collidepoint(pos):
                opt = payload
                if opt.kind == "bool":
                    self.config.toggle(opt.key)
                elif opt.kind == "choice":
                    self.config.cycle(opt.key)
                else:
                    self.edit(opt.key)
                self.app.status = f"build {opt.key}: {self.config.get(opt.key)}"
                return True
        return False

    def _button(self, name):
        if name == "build":
            self.start()
        elif name == "dry":
            self.dry_run()
        elif name == "reset":
            self.reset()
        elif name == "dist":
            self.open_dist()
        elif name == "run":
            self.run_built()

    # ---------------------------------------------------------------- draw
    def draw(self, surface, area, dt):
        self.area = pygame.Rect(area)
        self.config.drain(self.app.log)
        pygame.draw.rect(surface, xp.PANEL, area)
        head = pygame.Rect(area.x, area.y, area.width, 24)
        widgets.header(surface, head, "Build",
                       self.app.fonts["normal"],
                       right=("PyInstaller ready" if self.config.available()
                              else "PyInstaller missing"))
        bar = pygame.Rect(area.x + 8, head.bottom + 6, area.width - 16,
                          BUTTON_H)
        body = pygame.Rect(area.x + 8, bar.bottom + 8, area.width - 16,
                           area.bottom - bar.bottom - 16)
        self._draw_buttons(surface, bar)
        left_w = max(300, int(body.width * 0.48))
        self.list_rect = pygame.Rect(body.x, body.y, left_w, body.height)
        self.side_rect = pygame.Rect(self.list_rect.right + 10, body.y,
                                     body.right - self.list_rect.right - 10,
                                     body.height)
        self._draw_list(surface)
        self._draw_side(surface)

    def _draw_buttons(self, surface, bar):
        fonts = self.app.fonts
        specs = (("build", "Build" if not self.config.busy() else "Building",
                  True), ("dry", "Dry Run", False), ("run", "Run", False),
                 ("dist", "Open Dist", False), ("reset", "Reset", False))
        x = bar.x
        self.buttons = {}
        mouse = pygame.mouse.get_pos()
        for name, label, default in specs:
            width = 78 if name != "dist" else 92
            rect = pygame.Rect(x, bar.y, width, bar.height)
            xp.button(surface, rect, label, fonts["normal"],
                      default=default, hovered=rect.collidepoint(mouse))
            self.buttons[name] = rect
            x += width + 6
        status = self.config.result or (
            "building..." if self.config.busy() else "idle")
        if self.config.returncode is not None:
            status += f"  (exit {self.config.returncode})"
        img = widgets.cached_text(fonts["small"], status,
                                  xp.LOG_OK if self.config.result == "ok"
                                  else xp.TEXT_MUTED)
        surface.blit(img, (x + 8, bar.centery - img.get_height() // 2))

    # -- option list ------------------------------------------------------
    def _rows(self):
        rows = []
        for group in build.GROUPS:
            rows.append(("group", group, None))
            for opt in build.OPTIONS:
                if opt.group == group:
                    rows.append(("option", opt, None))
        return rows

    def _draw_list(self, surface):
        rect = self.list_rect
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        inner = rect.inflate(-6, -6)

        flat = self._rows()
        self.rows = []
        content_h = sum(GROUP_H if kind == "group" else ROW_H
                        for kind, _payload, _r in flat)
        max_scroll = max(0, content_h - inner.height)
        if self.scroll > max_scroll:
            self.scroll = max_scroll
        old = surface.get_clip()
        surface.set_clip(inner)
        y = inner.y - self.scroll
        mouse = pygame.mouse.get_pos()
        for kind, payload, _ in flat:
            height = GROUP_H if kind == "group" else ROW_H
            row = pygame.Rect(inner.x, y, inner.width, height)
            if row.bottom > inner.y and row.y < inner.bottom:
                if kind == "group":
                    self._draw_group(surface, row, payload)
                else:
                    self._draw_option(surface, row, payload,
                                      row.collidepoint(mouse))
                    self.rows.append(("option", payload, row))
            y += height
        surface.set_clip(old)
        if content_h > inner.height:
            shown = inner.height / max(1, content_h)
            xp.scrollbar(surface, pygame.Rect(rect.right - 13, rect.y + 2,
                                              11, rect.height - 4),
                         self.scroll / max(1, content_h), shown)

    def _draw_group(self, surface, row, label):
        pygame.draw.rect(surface, xp.THUMB_BG, row)
        pygame.draw.line(surface, xp.THUMB_LINE, (row.x, row.y),
                         (row.right, row.y))
        img = widgets.cached_text(self.app.fonts["normal"], label, xp.LINK)
        surface.blit(img, (row.x + 6, row.centery - img.get_height() // 2))

    def _draw_option(self, surface, row, opt, hovered):
        fonts = self.app.fonts
        if hovered:
            pygame.draw.rect(surface, xp.CARD_BG, row)
        cy = row.centery
        value = self.config.get(opt.key)
        changed = self.config.is_changed(opt.key)
        if opt.kind == "bool":
            box = xp.checkbox(surface, (row.x + 8, cy), bool(value),
                              opt.label, fonts["normal"])
            rect = pygame.Rect(row.x + 8, row.y, row.width - 16, row.height)
            if hovered:
                pygame.draw.rect(surface, xp.SELECT_BORDER, rect, 1)
            if changed:
                pygame.draw.rect(surface, xp.MODIFIED,
                                 (row.x + 1, row.y + 4, 2, row.height - 8))
            del box
            return
        label = widgets.cached_text(fonts["small"], opt.label, xp.TEXT_MUTED)
        surface.blit(label, (row.x + 8, cy - label.get_height() // 2))
        if opt.kind == "choice":
            width = min(150, max(110, row.width // 3))
            box = pygame.Rect(row.right - width - 8, row.y + 3, width,
                              row.height - 7)
            xp.combo(surface, box, str(value or "(default)"), fonts["small"],
                     hovered=hovered)
        else:
            text = str(value)
            if opt.kind == "list":
                text = f"{len(value)} entries" if value else "(none)"
            elif not text:
                text = "(default)"
            if len(text) > 42:
                text = text[:39] + "..."
            img = widgets.cached_text(fonts["small"], text,
                                      xp.LINK if changed else xp.TEXT)
            surface.blit(img, (row.right - img.get_width() - 10,
                               cy - img.get_height() // 2))
        if hovered:
            pygame.draw.rect(surface, xp.SELECT_BORDER, row, 1)

    # -- command / output --------------------------------------------------
    def _draw_side(self, surface):
        fonts = self.app.fonts
        rect = self.side_rect
        head = pygame.Rect(rect.x, rect.y, rect.width, 20)
        widgets.header(surface, head, "Command", fonts["small"])
        field = pygame.Rect(rect.x, head.bottom + 2, rect.width,
                            min(120, max(70, rect.height // 3)))
        pygame.draw.rect(surface, xp.FIELD, field)
        xp.sunken(surface, field)
        text = self.config.text()
        y = field.y + 5
        old = surface.get_clip()
        surface.set_clip(field.inflate(-2, -2))
        for line in widgets.wrap(fonts["mono"], text, field.width - 12)[:9]:
            img = widgets.cached_text(fonts["mono"], line, xp.CODE_TEXT)
            surface.blit(img, (field.x + 6, y))
            y += fonts["mono"].get_height() + 1
        surface.set_clip(old)

        rows = []
        rows.append(("bundle", str(self.config.get("name"))))
        rows.append(("mode", "one file" if self.config.get("onefile")
                     else "one folder"))
        rows.append(("console", "hidden" if self.config.get("windowed")
                     else "visible"))
        rows.append(("dist", str(self.config.output_dir())))
        exe = self.config.executable()
        rows.append(("exe", exe.name if exe is not None else "not built"))
        y = field.bottom + 8
        width = rect.width
        for label, value in rows:
            img = widgets.cached_text(fonts["small"], label, xp.TEXT_MUTED)
            surface.blit(img, (rect.x + 2, y))
            lines = widgets.wrap(fonts["small"], value, width - 74)
            for i, line in enumerate(lines[:2]):
                img = widgets.cached_text(fonts["small"], line, xp.TEXT)
                surface.blit(img, (rect.x + 74, y + i *
                                   (fonts["small"].get_height() + 1)))
            y += (fonts["small"].get_height() + 1) * max(1, len(lines[:2])) + 3
        y += 6
        hint = ("Click a switch to toggle it; click a value to type a new "
                "one. Use Extra args for switches that are not listed.")
        for i, line in enumerate(widgets.wrap(fonts["small"], hint,
                                              width - 4)[:4]):
            img = widgets.cached_text(fonts["small"], line, xp.TEXT_MUTED)
            surface.blit(img, (rect.x + 2, y + i *
                               (fonts["small"].get_height() + 1)))
