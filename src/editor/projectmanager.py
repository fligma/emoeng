"""The Emotion Engine project manager.

This is the first screen you see: every folder in the projects directory
that holds a project.flig manifest, a detail panel with the manifest
values and the asset counts, and buttons to create or open a project.

    Enter / double-click   open the selected project
    Ctrl+N                 new project
    F5                     rescan the projects folder
    Esc                    clear the search, or quit
"""

from __future__ import annotations

import json
import time

import pygame

from .. import CODENAME, __version__
from ..engine import paths, xp
from . import widgets

PROJECTS = paths.projects_dir()
COUNTS = (
    ("scenes", "Scenes", (".py",)),
    ("scripts", "Scripts", (".py",)),
    ("models", "Models", (".model",)),
    ("textures", "Textures", (".png", ".jpg", ".jpeg")),
    ("audio", "Audio", (".wav", ".ogg", ".mp3", ".flac")),
)
AVATAR_COLORS = (
    (52, 96, 158), (120, 70, 140), (40, 120, 96),
    (160, 90, 48), (92, 92, 150), (150, 60, 70),
)


class ProjectManager:
    """Project launcher drawn with the same Luna widgets as the editor."""

    ROW_H = 58

    def __init__(self, app):
        self.app = app
        self.fonts = app.fonts
        self.entries = []
        self.selected = 0
        self.scroll = 0
        self.rows = []
        self.buttons = []
        self.search = widgets.TextField("", 48)
        self.search_focus = False
        self.search_rect = pygame.Rect(0, 0, 0, 0)
        self.list_body = pygame.Rect(0, 0, 0, 0)
        self.header = pygame.Rect(0, 0, 0, 0)
        self.area = pygame.Rect(0, 0, 0, 0)
        self._last_row = None
        self._last_click = 0.0
        self.refresh()

    # ------------------------------------------------------------ scanning
    def refresh(self):
        entries = []
        if PROJECTS.is_dir():
            for path in sorted(PROJECTS.iterdir(), key=lambda p: p.name.lower()):
                if (path / "project.flig").exists():
                    entries.append(self._entry(path))
        self.entries = entries
        self.selected = max(0, min(self.selected, len(self.visible()) - 1))
        self._last_row = None

    def _entry(self, path):
        entry = {
            "path": path,
            "folder": path.name,
            "title": path.name.replace("_", " ").title(),
            "start": "-",
            "size": (0, 0),
            "scale": 1.0,
            "post": (),
            "seed": 0,
            "counts": {},
            "updated": 0.0,
            "error": None,
        }
        try:
            meta = json.loads((path / "project.flig").read_text(encoding="utf-8"))
            entry["title"] = meta.get("title") or entry["title"]
            entry["start"] = meta.get("start") or "-"
            entry["size"] = tuple(meta.get("size", (0, 0)))
            entry["scale"] = float(meta.get("render_scale", 1.0))
            entry["post"] = tuple(meta.get("post", ()))
            entry["seed"] = int(meta.get("seed", 0))
            entry["updated"] = (path / "project.flig").stat().st_mtime
        except Exception as exc:
            entry["error"] = str(exc)
        for kind, _label, exts in COUNTS:
            folder = path / kind
            count = 0
            try:
                if folder.is_dir():
                    count = sum(1 for p in folder.iterdir()
                                if p.is_file() and p.suffix.lower() in exts)
            except OSError:
                count = 0
            entry["counts"][kind] = count
        return entry

    def visible(self):
        query = self.search.text.strip().lower()
        if not query:
            return self.entries
        return [e for e in self.entries
                if query in e["title"].lower()
                or query in e["folder"].lower()
                or query in str(e["path"]).lower()]

    def selected_entry(self):
        rows = self.visible()
        if 0 <= self.selected < len(rows):
            return rows[self.selected]
        return None

    # -------------------------------------------------------------- layout
    def _layout(self, area):
        self.area = pygame.Rect(area)
        margin = 18
        width = max(320, area.width - margin * 2)
        self.header = pygame.Rect(area.x + margin, area.y + 12, width, 74)
        body_top = self.header.bottom + 14
        body_bottom = area.bottom - 54
        list_w = min(520, max(340, int(width * 0.44)))
        list_w = min(list_w, max(260, width - 300))
        self.list_rect = pygame.Rect(area.x + margin, body_top, list_w,
                                     max(120, body_bottom - body_top))
        details_x = self.list_rect.right + 14
        self.details_rect = pygame.Rect(
            details_x, body_top, max(220, area.right - margin - details_x),
            max(120, body_bottom - body_top))
        self.list_head = pygame.Rect(self.list_rect.x, self.list_rect.y,
                                     self.list_rect.width, 22)
        self.search_rect = pygame.Rect(self.list_rect.x + 6,
                                       self.list_head.bottom + 4,
                                       self.list_rect.width - 12, 23)
        self.list_body = pygame.Rect(
            self.list_rect.x + 4, self.search_rect.bottom + 6,
            self.list_rect.width - 8,
            self.list_rect.bottom - self.search_rect.bottom - 10)
        self.footer = pygame.Rect(area.x + margin, area.bottom - 44,
                                  width, 34)

    # --------------------------------------------------------------- draw
    def draw(self, surface, area):
        self._layout(area)
        self._draw_header(surface)
        self._draw_list(surface)
        self._draw_details(surface)
        self._draw_footer(surface)

    def _draw_header(self, surface):
        rect = self.header
        xp.gradient_v(surface, rect, xp.CAP_TOP, xp.CAP_BOT)
        pygame.draw.rect(surface, xp.DK_SHADOW, rect, 1)
        pygame.draw.line(surface, xp.CAP_GLOW, (rect.x + 1, rect.y + 1),
                         (rect.right - 2, rect.y + 1))
        title = widgets.cached_text(self.fonts["title"], CODENAME,
                                    xp.CAPTION)
        shadow = widgets.cached_text(self.fonts["title"], CODENAME,
                                     xp.CAPTION_SHADOW)
        surface.blit(shadow, (rect.x + 20, rect.y + 16))
        surface.blit(title, (rect.x + 18, rect.y + 14))
        sub = widgets.cached_text(
            self.fonts["small"],
            "PS2-style game engine and editor", xp.SELECT_SUBTEXT)
        surface.blit(sub, (rect.x + 20, rect.y + 46))
        right = f"v{__version__}"
        img = widgets.cached_text(self.fonts["small"], right,
                                  xp.SELECT_SUBTEXT)
        surface.blit(img, (rect.right - 16 - img.get_width(), rect.y + 14))
        img = widgets.cached_text(self.fonts["small"], "projects folder",
                                  xp.CAP_GLOW)
        surface.blit(img, (rect.right - 16 - img.get_width(), rect.y + 32))
        path = widgets.cached_text(self.fonts["small"], str(PROJECTS),
                                   xp.SELECT_TEXT)
        if path.get_width() > 300:
            path = pygame.transform.smoothscale(
                path, (300, max(9, path.get_height())))
        surface.blit(path, (rect.right - 16 - path.get_width(),
                            rect.y + 48))

    def _draw_list(self, surface):
        rows = self.visible()
        self.selected = max(0, min(self.selected, len(rows) - 1))
        total = len(self.entries)
        widgets.header(surface, self.list_head, "Projects",
                       self.fonts["normal"],
                       right=f"{total} project{'s' if total != 1 else ''}")
        xp.field(surface, self.search_rect)
        self.search.draw(surface, self.search_rect, self.fonts["small"],
                         focused=self.search_focus)
        if not self.search.text:
            hint = widgets.cached_text(self.fonts["small"], "search projects",
                                       xp.TEXT_MUTED)
            surface.blit(hint, (self.search_rect.x + 5,
                                self.search_rect.centery -
                                hint.get_height() // 2))
        pygame.draw.rect(surface, xp.FIELD, self.list_body)
        xp.sunken(surface, self.list_body)
        inner = self.list_body.inflate(-2, -2)
        self.rows = []
        if not rows:
            msg = ("no projects found" if self.entries else
                   "no projects yet - click New Project")
            img = widgets.cached_text(self.fonts["normal"], msg,
                                      xp.TEXT_MUTED)
            surface.blit(img, (inner.x + 10, inner.y + 10))
            return
        page = max(1, inner.height // self.ROW_H)
        max_scroll = max(0, len(rows) - page)
        self.scroll = max(0, min(self.scroll, max_scroll))
        self._row_offset = self.scroll
        y = inner.y + 2 - self.scroll * self.ROW_H
        for i, entry in enumerate(rows):
            rect = pygame.Rect(inner.x, y, inner.width - 12, self.ROW_H - 2)
            y += self.ROW_H
            if rect.bottom < inner.y or rect.y > inner.bottom:
                continue
            self.rows.append(rect)
            index = i
            if index == self.selected:
                surface.fill(xp.SELECTION, rect)
            elif rect.collidepoint(pygame.mouse.get_pos()):
                surface.fill(xp.BTN_HOVER_BG, rect)
            self._draw_row(surface, rect, entry,
                           selected=index == self.selected)
        if max_scroll > 0:
            xp.scrollbar(surface, pygame.Rect(
                self.list_body.right - 12, self.list_body.y + 2, 10,
                self.list_body.height - 4),
                self.scroll / max(1, len(rows)),
                page / max(1, len(rows)))

    def _draw_row(self, surface, rect, entry, selected):
        folder = entry["folder"]
        color = AVATAR_COLORS[sum(ord(c) for c in folder) % len(AVATAR_COLORS)]
        badge = pygame.Rect(rect.x + 8, rect.centery - 17, 34, 34)
        pygame.draw.rect(surface, color, badge, border_radius=4)
        pygame.draw.rect(surface, xp.DK_SHADOW, badge, 1, border_radius=4)
        initials = (folder[:2] or "P").upper()
        img = widgets.cached_text(self.fonts["small"], initials,
                                  xp.SELECT_TEXT)
        surface.blit(img, (badge.centerx - img.get_width() // 2,
                           badge.centery - img.get_height() // 2))
        text_color = xp.SELECT_TEXT if selected else xp.TEXT
        muted = xp.SELECT_SUBTEXT if selected else xp.TEXT_MUTED
        title = widgets.cached_text(self.fonts["normal"], entry["title"],
                                    text_color)
        surface.blit(title, (badge.right + 10, rect.y + 9))
        counts = entry["counts"]
        line = (f"{counts.get('scenes', 0)} scenes  |  "
                f"{counts.get('models', 0)} models  |  "
                f"{counts.get('textures', 0)} textures")
        img = widgets.cached_text(self.fonts["small"], line, muted)
        surface.blit(img, (badge.right + 10, rect.y + 30))
        right = entry["start"]
        if entry["error"]:
            right = "bad manifest"
        img = widgets.cached_text(self.fonts["small"], right,
                                  xp.CLOSE_BTN_EDGE if entry["error"] else muted)
        surface.blit(img, (rect.right - 8 - img.get_width(), rect.y + 10))

    def _draw_details(self, surface):
        rect = self.details_rect
        self._stats_rects = []
        widgets.header(surface, pygame.Rect(rect.x, rect.y, rect.width, 22),
                       "Project Details", self.fonts["normal"])
        entry = self.selected_entry()
        if entry is None:
            img = widgets.cached_text(self.fonts["normal"],
                                      "Select a project to see its settings.",
                                      xp.TEXT_MUTED)
            surface.blit(img, (rect.x + 10, rect.y + 36))
            return
        x = rect.x + 10
        y = rect.y + 34
        width = rect.width - 20
        title = widgets.cached_text(self.fonts["big"], entry["title"],
                                    xp.LINK)
        surface.blit(title, (x, y))
        y += title.get_height() + 3
        path_img = widgets.cached_text(self.fonts["small"],
                                       str(entry["path"]), xp.TEXT_MUTED)
        surface.blit(path_img, (x, y))
        y += path_img.get_height() + 10
        box_w = max(54, (width - 4 * 6) // 5)
        for i, (kind, label, _exts) in enumerate(COUNTS):
            box = pygame.Rect(x + i * (box_w + 6), y, box_w, 48)
            self._stats_rects.append(box)
            surface.fill(xp.FIELD, box)
            xp.sunken(surface, box)
            count = str(entry["counts"].get(kind, 0))
            img = widgets.cached_text(self.fonts["big"], count,
                                      xp.LINK)
            surface.blit(img, (box.centerx - img.get_width() // 2,
                               box.y + 5))
            img = widgets.cached_text(self.fonts["small"], label,
                                      xp.TEXT_MUTED)
            surface.blit(img, (box.centerx - img.get_width() // 2,
                               box.bottom - img.get_height() - 5))
        y += 60
        if entry["error"]:
            img = widgets.cached_text(self.fonts["small"],
                                      "manifest error: " + entry["error"],
                                      xp.LOG_ERROR)
            surface.blit(img, (x, y))
            y += img.get_height() + 6
        size = entry["size"]
        window = f"{size[0]} x {size[1]}" if len(size) == 2 and size[0] else "-"
        post = ", ".join(entry["post"]) or "none"
        rows = [
            ("Start scene", entry["start"]),
            ("Window", window),
            ("Render scale", f"{entry['scale']:g}"),
            ("Post FX", post),
            ("Seed", str(entry["seed"])),
            ("Manifest", "project.flig"),
            ("Updated", time.strftime("%Y-%m-%d %H:%M",
                                      time.localtime(entry["updated"]))
             if entry["updated"] else "-"),
        ]
        for label, value in rows:
            img = widgets.cached_text(self.fonts["small"], label,
                                      xp.TEXT_MUTED)
            surface.blit(img, (x, y + 1))
            for line in widgets.wrap(self.fonts["small"], value,
                                     width - 92)[:2]:
                img = widgets.cached_text(self.fonts["small"], line,
                                          xp.TEXT)
                if img is not None:
                    surface.blit(img, (x + 92, y))
                    y += img.get_height() + 1
                else:
                    y += self.fonts["small"].get_height() + 1
            y += 3
            if y > rect.bottom - 52:
                break
        hint = widgets.cached_text(
            self.fonts["small"],
            "Enter opens the project. F5 rescans the projects folder.",
            xp.TEXT_MUTED)
        surface.blit(hint, (x, rect.bottom - hint.get_height() - 6))

    def _draw_footer(self, surface):
        rect = self.footer
        self.buttons = []
        mouse = pygame.mouse.get_pos()
        x = rect.x
        for action, label in (("new", "New Project"),
                              ("folder", "Open Folder..."),
                              ("refresh", "Refresh")):
            w = max(84, self.fonts["normal"].size(label)[0] + 22)
            r = pygame.Rect(x, rect.y, w, 28)
            xp.button(surface, r, label, self.fonts["normal"],
                      hovered=r.collidepoint(mouse))
            self.buttons.append((action, r))
            x = r.right + 6
        x = rect.right
        for action, label, default in (("quit", "Quit", False),
                                       ("open", "Open Project", True)):
            w = max(86, self.fonts["normal"].size(label)[0] + 24)
            r = pygame.Rect(x - w, rect.y, w, 28)
            xp.button(surface, r, label, self.fonts["normal"],
                      default=default, enabled=self.selected_entry() is not None,
                      hovered=r.collidepoint(mouse))
            self.buttons.append((action, r))
            x = r.x - 8

    # -------------------------------------------------------------- events
    def handle_event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                if self.search.text:
                    self.search.set("")
                    self.selected = 0
                    self.scroll = 0
                else:
                    self.app.running = False
                return True
            if e.key in (pygame.K_UP, pygame.K_DOWN):
                rows = self.visible()
                if rows:
                    step = -1 if e.key == pygame.K_UP else 1
                    self.selected = (self.selected + step) % len(rows)
                return True
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.open_selected()
                return True
            if e.key == pygame.K_F5:
                self.refresh()
                self.app.log("projects rescanned", "ok")
                return True
            if e.mod & pygame.KMOD_CTRL and e.key == pygame.K_n:
                self.app._prompt("new_project")
                return True
            if self.search_focus:
                self.search.handle(e)
                self.selected = 0
                self.scroll = 0
                return True
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            pos = e.pos
            if self.search_rect.collidepoint(pos):
                self.search_focus = True
                return True
            self.search_focus = False
            for action, rect in self.buttons:
                if rect.collidepoint(pos):
                    self._action(action)
                    return True
            for i, rect in enumerate(self.rows):
                if rect.collidepoint(pos):
                    self.selected = i + getattr(self, "_row_offset", 0)
                    now = time.time()
                    if self._last_row == self.selected and \
                            now - self._last_click < 0.42:
                        self.open_selected()
                    self._last_row = self.selected
                    self._last_click = now
                    return True
            return True
        if e.type == pygame.MOUSEWHEEL:
            if self.list_body.collidepoint(pygame.mouse.get_pos()):
                rows = self.visible()
                page = max(1, self.list_body.height // self.ROW_H)
                self.scroll = max(0, min(max(0, len(rows) - page),
                                         self.scroll - e.y * 2))
                return True
        return False

    def _action(self, action):
        if action == "new":
            self.app._prompt("new_project")
        elif action == "folder":
            self.app._prompt("open_folder")
        elif action == "refresh":
            self.refresh()
            self.app.log("projects rescanned", "ok")
        elif action == "open":
            self.open_selected()
        elif action == "quit":
            self.app.running = False

    def open_selected(self):
        entry = self.selected_entry()
        if entry is None:
            return False
        return self.app.open_project(entry["path"])
