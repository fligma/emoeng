"""The Motion Engine project manager."""

from __future__ import annotations

import json
import time

import pygame

from .. import CODENAME, __version__, const
from ..engine import config, loader, paths, scenedoc, xp
from . import widgets

PROJECTS = paths.projects_dir()
# a folder card counts documents, not dimension halves
MODEL_EXTS = (scenedoc.MODEL3D_EXT, scenedoc.MODEL2D_EXT, scenedoc.MODEL_EXT)
OBJECT_EXTS = scenedoc.OBJECT_EXTS
COUNTS = (
    ("scenes", "Scenes", (scenedoc.SCENE_EXT,)),
    ("objects", "Objects", OBJECT_EXTS),
    ("scripts", "Scripts", (".py",)),
    ("models", "Models", MODEL_EXTS),
    ("textures", "Textures", (".png", ".jpg", ".jpeg")),
    ("audio", "Audio", (".wav", ".ogg", ".mp3", ".flac")),
)
AVATAR_COLORS = (
    (52, 96, 158), (120, 70, 140), (40, 120, 96),
    (160, 90, 48), (92, 92, 150), (150, 60, 70),
)

# footer buttons and panel headers share the menu look
FOOTER_ICONS = {"new": "new-folder-sym", "folder": "open-folder-sym",
                "refresh": "reload-sym", "shortcut": "file-exec-sym",
                "rename": "file-text-sym", "icon": "file-image-sym"}

# icon.png by path and mtime, so uploads show at once
_ICON_CACHE = {}


def project_icon(path, px=34):
    """The project's `icon.png`, squared to `px` and cached; None when"""
    img = path / const.ICON_NAME
    try:
        key = (str(img), img.stat().st_mtime_ns)
    except OSError:
        return None
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    art = None
    try:
        raw = pygame.image.load(str(img))
        try:
            raw = raw.convert_alpha()
        except pygame.error:
            pass
        art = pygame.transform.smoothscale(raw, (px, px))
    except (OSError, ValueError, pygame.error):
        art = None
    if len(_ICON_CACHE) > 256:
        _ICON_CACHE.clear()
    _ICON_CACHE[key] = art
    return art


def in_repo(path):
    """True when `path` sits inside a git working copy."""
    try:
        for p in [path, *path.parents]:
            if (p / ".git").exists():
                return True
            if p.parent == p:
                break
    except OSError:
        return False
    return False


class ProjectManager:
    """Project launcher drawn with the editor's Luna widgets."""

    ROW_H = 58

    def __init__(self, app):
        self.app = app
        self.fonts = app.fonts
        self.entries = []
        self.selected = 0
        self.scroll = 0
        self.recent = []             # folder paths, newest first
        self.recent_limit = int(config.get("editor.recent_limit"))
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

    def note_open(self, path):
        """Move a project to the front of the recent list."""
        if self.recent_limit <= 0:
            return
        key = str(path)
        self.recent = [r for r in self.recent if r != key]
        self.recent.insert(0, key)
        del self.recent[self.recent_limit:]

    def refresh(self):
        entries = []
        if PROJECTS.is_dir():
            for path in sorted(PROJECTS.iterdir(), key=lambda p: p.name.lower()):
                if (path / "project.flig").exists():
                    entries.append(self._entry(path))
        order = {name: i for i, name in enumerate(self.recent)}
        if order:
            # recently opened first, then alphabetical
            entries.sort(key=lambda e: (order.get(str(e["path"]), len(order)),
                                        e["folder"].lower()))
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
            "version": "",
            "format": 0,
            "sidecars": (),
            "counts": {},
            "updated": 0.0,
            "error": None,
            "git": in_repo(path),
        }
        manifest = path / const.MANIFEST_NAME
        try:
            # section_meta first: flat manifests read the same
            meta = loader.section_meta(json.loads(
                manifest.read_text(encoding="utf-8")))
            entry["title"] = meta.get("title") or entry["title"]
            entry["start"] = meta.get("start") or "-"
            entry["size"] = tuple(loader.meta_get(meta, "window", "size",
                                                   (0, 0)))
            entry["scale"] = float(loader.meta_get(meta, "render", "scale", 1.0))
            entry["post"] = tuple(loader.meta_get(meta, "render", "post", ()))
            entry["seed"] = int(meta.get("seed", 0))
            entry["version"] = str(meta.get("version") or "")
            entry["format"] = int(meta.get("format", 1) or 1)
            entry["sidecars"] = tuple(name for name in
                                      (loader.INPUT_NAME, loader.ASSET_NAME)
                                      if (path / name).is_file())
            entry["updated"] = manifest.stat().st_mtime
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
            self.fonts["small"], const.SUBTITLE, xp.SELECT_SUBTEXT)
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
                       right=f"{total} project{'s' if total != 1 else ''}",
                       icon="menu-sym")
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
        badge = pygame.Rect(rect.x + 8, rect.centery - 17, 34, 34)
        art = project_icon(entry["path"], badge.height)
        if art is not None:
            surface.blit(art, badge.topleft)
        else:
            # no picture: first two letters on a name-picked colour
            color = AVATAR_COLORS[sum(ord(c) for c in folder)
                                  % len(AVATAR_COLORS)]
            pygame.draw.rect(surface, color, badge, border_radius=4)
            initials = (folder[:2] or "P").upper()
            img = widgets.cached_text(self.fonts["small"], initials,
                                      xp.SELECT_TEXT)
            surface.blit(img, (badge.centerx - img.get_width() // 2,
                               badge.centery - img.get_height() // 2))
        pygame.draw.rect(surface, xp.DK_SHADOW, badge, 1, border_radius=4)
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
        surface.blit(img, (rect.right - 26 - img.get_width(), rect.y + 10))

    def _draw_details(self, surface):
        rect = self.details_rect
        self._stats_rects = []
        widgets.header(surface, pygame.Rect(rect.x, rect.y, rect.width, 22),
                       "Project Details", self.fonts["normal"],
                       icon="file-flig-sym")
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
            ("Post shaders", post),
            ("Seed", str(entry["seed"])),
            ("Version", entry["version"] or "-"),
            ("Git", "working copy" if entry["git"] else "no repository"),
            ("Manifest", f"project.flig (format {entry['format'] or '-'})"),
            ("Extras", ", ".join(entry["sidecars"]) or "none"),
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
        has_entry = self.selected_entry() is not None
        for action, label, enabled in (("new", "New Project", True),
                                       ("folder", "Open Folder...", True),
                                       ("refresh", "Refresh", True),
                                       ("rename", "Rename", has_entry),
                                       ("icon", "Set Icon", has_entry),
                                       ("shortcut", "Create Shortcut",
                                        has_entry)):
            art = widgets.icon(FOOTER_ICONS.get(action, ""), 14)
            w = max(84, self.fonts["normal"].size(label)[0] + 22 +
                    (20 if art is not None else 0))
            r = pygame.Rect(x, rect.y, w, 28)
            xp.button(surface, r, label, self.fonts["normal"],
                      enabled=enabled, icon=art,
                      hovered=enabled and r.collidepoint(mouse))
            self.buttons.append((action, r))
            x = r.right + 6
        x = rect.right
        for action, label, default in (("quit", "Quit", False),
                                       ("open", "Open Project", True)):
            art = widgets.icon(FOOTER_ICONS.get(action, ""), 14)
            w = max(86, self.fonts["normal"].size(label)[0] + 24 +
                    (20 if art is not None else 0))
            r = pygame.Rect(x - w, rect.y, w, 28)
            xp.button(surface, r, label, self.fonts["normal"],
                      default=default, enabled=self.selected_entry() is not None,
                      icon=art,
                      hovered=r.collidepoint(mouse))
            self.buttons.append((action, r))
            x = r.x - 8

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
        elif action == "shortcut":
            entry = self.selected_entry()
            if entry is None:
                self.app.log("select a project first", "warn")
                return
            self.app.create_shortcut(entry["path"])
        elif action == "rename":
            entry = self.selected_entry()
            if entry is None:
                self.app.log("select a project first", "warn")
                return
            self.app.prompt_project_rename(entry["path"], entry["folder"])
        elif action == "icon":
            entry = self.selected_entry()
            if entry is None:
                self.app.log("select a project first", "warn")
                return
            self.app.prompt_project_icon(entry["path"])
        elif action == "open":
            self.open_selected()
        elif action == "quit":
            self.app.running = False

    def open_selected(self):
        entry = self.selected_entry()
        if entry is None:
            return False
        return self.app.open_project(entry["path"])
