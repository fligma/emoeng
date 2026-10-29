"""The Motion Engine project manager."""

from __future__ import annotations

import json
import time

import pygame

from .. import CODENAME, __version__, const
from ..engine import config, loader, paths, scenedoc, templates, xp
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
# the starter a project grew from, read off its start scene when the
# manifest does not say: the two ways a folder tells us what it is
SCENE_TEMPLATE = {"scene3d": "game3d", "scene2d": "game2d",
                  "sceneui": "menu"}
OTHER_TEMPLATE = "other"
OTHER_LABEL = "Other"

# footer buttons and panel headers share the menu look
FOOTER_ICONS = {"new": "new-folder-sym", "folder": "open-folder-sym",
                "refresh": "reload-sym", "shortcut": "file-exec-sym",
                "rename": "file-text-sym", "icon": "file-image-sym",
                "duplicate": "new-file-sym", "delete": "blocked-sym",
                "more": "menu-sym"}

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


def _read_json(path):
    """A small JSON file as a dict, or {} when it is not one."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


class ProjectManager:
    """Project launcher drawn with the editor's Luna widgets."""

    ROW_H = 58
    RAIL_H = 21
    RAIL_W = 152
    CARD_GAP = 11

    def __init__(self, app):
        self.app = app
        self.fonts = app.fonts
        self.entries = []
        self.selected = 0
        self.scroll = 0
        self.recent = []             # folder paths, newest first
        self.recent_limit = int(config.get("editor.recent_limit"))
        self.filter = "all"          # the rail's live row
        self.rows = []               # [(visible index, rect)] this frame
        self.rail_rows = []          # [(filter key, rect)] this frame
        self.menu = None             # a row's own actions, while open
        self.menu_rows = []
        self.buttons = []
        self.search = widgets.TextField("", 48)
        self.search_focus = False
        self.search_rect = pygame.Rect(0, 0, 0, 0)
        self.list_body = pygame.Rect(0, 0, 0, 0)
        self.rail_rect = pygame.Rect(0, 0, 0, 0)
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
            "description": "",
            "template": OTHER_TEMPLATE,
            "master": 1.0,
            "music": "",
            "fps": 0,
            "vsync": False,
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
            entry["description"] = str(meta.get("description") or "")
            entry["master"] = float(loader.meta_get(meta, "audio", "master", 1.0))
            entry["music"] = str(loader.meta_get(meta, "audio", "music", "") or "")
            entry["fps"] = int(loader.meta_get(meta, "render", "fps_cap", 0) or 0)
            entry["vsync"] = bool(loader.meta_get(meta, "render", "vsync", False))
            entry["sidecars"] = tuple(name for name in
                                      (loader.INPUT_NAME, loader.ASSET_NAME)
                                      if (path / name).is_file())
            entry["updated"] = manifest.stat().st_mtime
            entry["template"] = self._template_of(path, meta.get("template"),
                                                  entry["start"])
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
        # what the search box reads, gathered once per scan
        entry["needle"] = " ".join((
            entry["title"], entry["folder"], str(path), entry["description"],
            self.template_label(entry["template"]))).lower()
        return entry

    def _template_of(self, path, named, start):
        """Which starter a project grew from: the manifest's word, else"""
        # the kind its start scene declares
        name = str(named or "")
        if name in templates.PROJECTS:
            return name
        if start and start != "-":
            kind = str(_read_json(path / "scenes" / f"{start}.scene")
                       .get("kind") or "")
            if kind in SCENE_TEMPLATE:
                return SCENE_TEMPLATE[kind]
        return OTHER_TEMPLATE

    @staticmethod
    def template_label(key):
        """A template key as the rail and the row tag spell it."""
        key = str(key or "")
        if key == OTHER_TEMPLATE:
            return OTHER_LABEL
        if key in templates.PROJECTS:
            return str(templates.spec(key)["title"])
        return key.replace("_", " ").title() if key else OTHER_LABEL

    def broken(self, entry):
        """True when a folder is gone or its manifest will not read."""
        try:
            return bool(entry["error"]) or not entry["path"].is_dir()
        except OSError:
            return True

    def matches_filter(self, entry):
        """Does the entry belong to the rail row that is lit?"""
        active = self.filter or "all"
        if active == "all":
            return True
        if active == "recent":
            return str(entry["path"]) in self.recent
        if active == "broken":
            return self.broken(entry)
        if active.startswith("tpl:"):
            return entry["template"] == active[4:]
        return True

    def visible(self):
        """The rows on show: the rail's filter, then the typed words."""
        query = self.search.text.strip().lower()
        out = [e for e in self.entries if self.matches_filter(e)]
        if not query:
            return out
        return [e for e in out if query in e["needle"]]

    def filter_rows(self):
        """[(kind, key, label, count)]: group captions, then filters."""
        entries = self.entries
        out = [("group", "", "Library", len(entries)),
               ("filter", "all", "All projects", len(entries)),
               ("filter", "recent", "Recent",
                sum(1 for e in entries
                    if str(e["path"]) in self.recent)),
               ("filter", "broken", "Broken",
                sum(1 for e in entries if self.broken(e)))]
        counts = {}
        for entry in entries:
            key = entry["template"]
            counts[key] = counts.get(key, 0) + 1
        if counts:
            out.append(("group", "", "Templates", len(entries)))
            for key in templates.template_names():
                if key in counts:
                    out.append(("filter", f"tpl:{key}",
                                self.template_label(key), counts.pop(key)))
            # a starter the engine no longer ships keeps its own row
            for key in sorted(counts):
                out.append(("filter", f"tpl:{key}", self.template_label(key),
                            counts[key]))
        return out

    def selected_entry(self):
        rows = self.visible()
        if 0 <= self.selected < len(rows):
            return rows[self.selected]
        return None

    def choose_filter(self, key):
        """Light one rail row: the list narrows to it and starts over."""
        if key == self.filter:
            return False
        self.filter = key
        self.selected = 0
        self.scroll = 0
        self._last_row = None
        label = next((text for kind, k, text, _n in self.filter_rows()
                      if kind == "filter" and k == key), key)
        self.app.status = f"filter: {label}"
        return True

    def _layout(self, area):
        self.area = pygame.Rect(area)
        margin = 18
        width = max(320, area.width - margin * 2)
        self.header = pygame.Rect(area.x + margin, area.y + 12, width, 74)
        body_top = self.header.bottom + 14
        body_bottom = area.bottom - 54
        body_h = max(120, body_bottom - body_top)
        # the rail earns its space only when the window can pay for it
        rail_w = self.RAIL_W if width >= 760 else 0
        self.rail_rect = pygame.Rect(area.x + margin, body_top, rail_w, body_h)
        list_x = self.rail_rect.right + (10 if rail_w else 0)
        list_w = min(420, max(300, int(width * 0.34)))
        list_w = min(list_w, max(240, area.right - margin - list_x - 260))
        self.list_rect = pygame.Rect(list_x, body_top, list_w, body_h)
        details_x = self.list_rect.right + 14
        self.details_rect = pygame.Rect(
            details_x, body_top, max(220, area.right - margin - details_x),
            body_h)
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
        self._draw_rail(surface)
        self._draw_list(surface)
        self._draw_details(surface)
        self._draw_footer(surface)
        if self.menu is not None:
            self._draw_menu(surface)

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

    def _draw_rail(self, surface):
        """The categories, Godot-style: captions over their own counts."""
        rect = self.rail_rect
        self.rail_rows = []
        if rect.width <= 0:
            return
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        mouse = pygame.mouse.get_pos()
        small = self.fonts["small"]
        y = rect.y + 6
        inner_w = rect.width - 8
        for kind, key, label, count in self.filter_rows():
            if kind == "group":
                if y > rect.y + 6:
                    y += 7
                img = widgets.cached_text(small, label.upper(), xp.TEXT_MUTED)
                surface.blit(img, (rect.x + 8, y))
                y += img.get_height() + 3
                continue
            row = pygame.Rect(rect.x + 4, y, inner_w, self.RAIL_H)
            if row.bottom > rect.bottom - 4:
                break
            chosen = (self.filter or "all") == key
            if chosen:
                surface.fill(xp.SELECTION, row)
            elif row.collidepoint(mouse):
                surface.fill(xp.BTN_HOVER_BG, row)
            img = widgets.cached_text(small, widgets.elide(
                small, label, row.width - 30),
                xp.SELECT_TEXT if chosen else xp.TEXT)
            surface.blit(img, (row.x + 6, row.centery - img.get_height() // 2))
            num = widgets.cached_text(small, str(count),
                                      xp.SELECT_SUBTEXT if chosen
                                      else xp.TEXT_MUTED)
            surface.blit(num, (row.right - 6 - num.get_width(),
                               row.centery - num.get_height() // 2))
            self.rail_rows.append((key, row))
            y += self.RAIL_H

    def _draw_list(self, surface):
        rows = self.visible()
        self.selected = max(0, min(self.selected, len(rows) - 1))
        total = len(self.entries)
        right = f"{total} project{'s' if total != 1 else ''}"
        if len(rows) != total:
            right = f"{len(rows)} of {right}"
        widgets.header(surface, self.list_head, "Projects",
                       self.fonts["normal"], right=right, icon="menu-sym")
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
            msg = self.empty_note()
            img = widgets.cached_text(self.fonts["normal"], msg,
                                      xp.TEXT_MUTED)
            surface.blit(img, (inner.x + 10, inner.y + 10))
            return
        page = max(1, inner.height // self.ROW_H)
        max_scroll = max(0, len(rows) - page)
        self.scroll = max(0, min(self.scroll, max_scroll))
        y = inner.y + 2 - self.scroll * self.ROW_H
        for index, entry in enumerate(rows):
            rect = pygame.Rect(inner.x, y, inner.width - 12, self.ROW_H - 2)
            y += self.ROW_H
            if rect.bottom < inner.y or rect.y > inner.bottom:
                continue
            self.rows.append((index, rect))
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

    def empty_note(self):
        """What the list says when it has nothing to show."""
        query = self.search.text.strip()
        if not self.entries:
            return "no projects yet - click New Project"
        if query:
            return f'nothing matches "{query}"'
        if self.filter == "recent":
            return "no recently opened projects yet"
        if self.filter == "broken":
            return "every project reads fine"
        return "no project in this category"

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
        right = entry["start"]
        if entry["error"]:
            right = "bad manifest"
        tag_img = widgets.cached_text(self.fonts["small"], right,
                                      xp.CLOSE_BTN_EDGE if entry["error"]
                                      else muted)
        room = rect.right - 26 - tag_img.get_width() - (badge.right + 16)
        name = widgets.elide(self.fonts["normal"], entry["title"],
                             max(40, room))
        title = widgets.cached_text(self.fonts["normal"], name, text_color)
        surface.blit(title, (badge.right + 10, rect.y + 9))
        counts = entry["counts"]
        line = (f"{counts.get('scenes', 0)} scenes  |  "
                f"{counts.get('models', 0)} models  |  "
                f"{counts.get('textures', 0)} textures")
        img = widgets.cached_text(self.fonts["small"], line, muted)
        surface.blit(img, (badge.right + 10, rect.y + 30))
        surface.blit(tag_img, (rect.right - 26 - tag_img.get_width(),
                               rect.y + 10))

    def _card(self, surface, x, y, width, title, right=None):
        """A labelled band: a caption, a hairline, then the card's rows."""
        small = self.fonts["small"]
        img = widgets.cached_text(small, title.upper(), xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (x, y))
        if right:
            num = widgets.cached_text(small, right, xp.TEXT_MUTED)
            if num is not None:
                surface.blit(num, (x + width - num.get_width(), y))
        y += (img.get_height() if img is not None
              else small.get_height()) + 2
        pygame.draw.line(surface, xp.OUTLINE, (x, y), (x + width, y))
        return y + 5

    def _field(self, surface, x, y, width, label, value, label_w=92):
        """One labelled value; the value wraps and the row grows."""
        small = self.fonts["small"]
        img = widgets.cached_text(small, label, xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (x, y + 1))
        for line in widgets.wrap(small, str(value), max(40, width - label_w))[:3]:
            art = widgets.cached_text(small, line, xp.TEXT)
            if art is not None:
                surface.blit(art, (x + label_w, y))
            y += small.get_height() + 1
        return y + 3

    def _draw_details(self, surface):
        """The chosen project, split into the cards Godot would show."""
        rect = self.details_rect
        self._stats_rects = []
        widgets.header(surface, pygame.Rect(rect.x, rect.y, rect.width, 22),
                       "Project Details", self.fonts["normal"],
                       icon="file-flig-sym")
        entry = self.selected_entry()
        x = rect.x + 10
        width = rect.width - 20
        if entry is None:
            img = widgets.cached_text(self.fonts["normal"],
                                      "Select a project to see its settings.",
                                      xp.TEXT_MUTED)
            surface.blit(img, (x, rect.y + 36))
            return
        small = self.fonts["small"]
        floor = rect.bottom - 20
        y = rect.y + 32
        title = widgets.cached_text(self.fonts["big"], entry["title"], xp.LINK)
        surface.blit(title, (x, y))
        y += title.get_height() + 2
        # identity: where it lives, what it says it is
        path_img = widgets.cached_text(
            small, widgets.elide(small, str(entry["path"]), width),
            xp.TEXT_MUTED)
        surface.blit(path_img, (x, y))
        y += path_img.get_height() + 8
        if entry["description"]:
            for line in widgets.wrap(small, entry["description"],
                                     width)[:2]:
                img = widgets.cached_text(small, line, xp.TEXT)
                surface.blit(img, (x, y))
                y += img.get_height() + 1
        y = self._field(surface, x, y, width, "Starter",
                        self.template_label(entry["template"]))
        if entry["error"]:
            img = widgets.cached_text(small, "manifest error: " + entry["error"],
                                      xp.LOG_ERROR)
            surface.blit(img, (x, y))
            y += img.get_height() + 4
        y += self.CARD_GAP
        # contents: the same six boxes, under their own caption
        y = self._card(surface, x, y, width, "Contents")
        cols = len(COUNTS) if width >= len(COUNTS) * 60 else 3
        box_w = max(44, (width - (cols - 1) * 6) // cols)
        for i, (kind, label, _exts) in enumerate(COUNTS):
            row, col = divmod(i, cols)
            box = pygame.Rect(x + col * (box_w + 6), y + row * 50, box_w, 44)
            self._stats_rects.append(box)
            surface.fill(xp.FIELD, box)
            xp.sunken(surface, box)
            count = str(entry["counts"].get(kind, 0))
            img = widgets.cached_text(self.fonts["big"], count, xp.LINK)
            surface.blit(img, (box.centerx - img.get_width() // 2,
                               box.y + 3))
            img = widgets.cached_text(small, label, xp.TEXT_MUTED)
            surface.blit(img, (box.centerx - img.get_width() // 2,
                               box.bottom - img.get_height() - 4))
        y += (len(COUNTS) + cols - 1) // cols * 50 + self.CARD_GAP - 6
        if y > floor - 40:
            return
        # window and render: how it opens and how it is drawn
        y = self._card(surface, x, y, width, "Window & Render")
        size = entry["size"]
        window = f"{size[0]} x {size[1]}" if len(size) == 2 and size[0] else "-"
        post = ", ".join(entry["post"]) or "none"
        y = self._field(surface, x, y, width, "Start scene", entry["start"])
        y = self._field(surface, x, y, width, "Window", window)
        y = self._field(surface, x, y, width, "Render scale",
                        f"{entry['scale']:g}")
        y = self._field(surface, x, y, width, "Frame rate",
                        f"{entry['fps']} fps cap" if entry["fps"]
                        else "uncapped")
        y = self._field(surface, x, y, width, "VSync",
                        "on" if entry["vsync"] else "off")
        y = self._field(surface, x, y, width, "Post shaders", post)
        y = self._field(surface, x, y, width, "Seed", str(entry["seed"]))
        y += self.CARD_GAP - 3
        if y > floor - 40:
            return
        # audio: what the manifest plays by default
        y = self._card(surface, x, y, width, "Audio")
        y = self._field(surface, x, y, width, "Master",
                        f"{entry['master']:g}")
        y = self._field(surface, x, y, width, "Music", entry["music"] or "none")
        y += self.CARD_GAP - 3
        if y > floor - 40:
            return
        # repository: the file itself and what sits beside it
        y = self._card(surface, x, y, width, "Repository")
        y = self._field(surface, x, y, width, "Git",
                        "working copy" if entry["git"] else "no repository")
        y = self._field(surface, x, y, width, "Manifest",
                        f"project.flig (format {entry['format'] or '-'})")
        y = self._field(surface, x, y, width, "Version",
                        entry["version"] or "-")
        y = self._field(surface, x, y, width, "Extras",
                        ", ".join(entry["sidecars"]) or "none")
        y = self._field(surface, x, y, width, "Updated",
                        time.strftime("%Y-%m-%d %H:%M",
                                      time.localtime(entry["updated"]))
                        if entry["updated"] else "-")
        hint = widgets.cached_text(
            small,
            "Enter opens the project. Right-click a row for more. "
            "F5 rescans.",
            xp.TEXT_MUTED)
        surface.blit(hint, (x, rect.bottom - hint.get_height() - 6))

    def _draw_footer(self, surface):
        rect = self.footer
        self.buttons = []
        mouse = pygame.mouse.get_pos()
        has_entry = self.selected_entry() is not None
        x = rect.x
        for action, label, enabled in (("new", "New Project", True),
                                       ("folder", "Open Folder...", True),
                                       ("refresh", "Refresh", True),
                                       ("duplicate", "Duplicate", has_entry),
                                       ("delete", "Delete", has_entry),
                                       ("more", "More...", has_entry)):
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
                      default=default, enabled=has_entry,
                      icon=art,
                      hovered=r.collidepoint(mouse))
            self.buttons.append((action, r))
            x = r.x - 8

    def menu_items_for(self, entry):
        """What a project row offers: the actions that need it picked."""
        if entry is None:
            return []
        return [("open", "Open Project"),
                ("rename", "Rename..."),
                ("duplicate", "Duplicate..."),
                ("icon", "Set Icon..."),
                ("shortcut", "Create Shortcut"),
                ("delete", "Delete...")]

    def open_menu(self, pos, entry):
        """A row's own actions, the menu Godot puts on a project."""
        items = self.menu_items_for(entry)
        if not items:
            return False
        self.menu = {"x": pos[0], "y": pos[1], "entry": entry, "items": items}
        return True

    def _draw_menu(self, surface):
        menu = self.menu
        items = [(label, True) for _action, label in menu["items"]]
        small = self.fonts["small"]
        wide = max(150, max(small.size(label)[0] for _a, label in
                            menu["items"]) + 26)
        x = max(0, min(menu["x"], surface.get_width() - wide - 6))
        y = max(0, min(menu["y"], surface.get_height() - 30))
        _panel, rects = xp.menu_items(surface, (x, y), items, small,
                                      width=wide)
        self.menu_rows = [(action, rect)
                          for (action, _label), rect in
                          zip(menu["items"], rects)
                          if rect is not None]

    def handle_event(self, e):
        if self.menu is not None:
            return self._menu_event(e)
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
            if e.key == pygame.K_F2:
                return self._action("rename")
            if e.key == pygame.K_DELETE:
                return self._action("delete")
            if e.mod & pygame.KMOD_CTRL and e.key == pygame.K_d:
                return self._action("duplicate")
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
            # a right click picks the row under it, then asks what to do
            for index, rect in self.rows:
                if rect.collidepoint(e.pos):
                    self.selected = index
                    entry = self.selected_entry()
                    return self.open_menu(e.pos, entry)
            return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            pos = e.pos
            if self.search_rect.collidepoint(pos):
                self.search_focus = True
                return True
            self.search_focus = False
            for key, rect in self.rail_rows:
                if rect.collidepoint(pos):
                    self.choose_filter(key)
                    return True
            for action, rect in self.buttons:
                if rect.collidepoint(pos):
                    self._action(action, pos)
                    return True
            for index, rect in self.rows:
                if rect.collidepoint(pos):
                    self.selected = index
                    now = time.time()
                    if self._last_row == index and now - self._last_click < 0.42:
                        self.open_selected()
                    self._last_row = index
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

    def _menu_event(self, e):
        """The open menu answers a click, and closes on anything else."""
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.menu = None
            return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            entry = self.menu["entry"]
            hit = next((action for action, rect in self.menu_rows
                        if rect.collidepoint(e.pos)), None)
            self.menu = None
            if hit is not None:
                self._action(hit, e.pos, entry)
            return True
        if e.type == pygame.MOUSEBUTTONDOWN:
            self.menu = None
            return True
        return True

    def _action(self, action, pos=None, entry=None):
        """One named action: from a button, a key or the row menu."""
        picked = entry or self.selected_entry()
        if action == "new":
            self.app._prompt("new_project")
        elif action == "folder":
            self.app._prompt("open_folder")
        elif action == "refresh":
            self.refresh()
            self.app.log("projects rescanned", "ok")
        elif action == "more":
            # the same menu a right click opens, for the picked row
            anchor = (pos or (self.footer.x, self.footer.y - 4))
            self.open_menu(anchor, picked)
        elif action in ("rename", "icon", "shortcut", "duplicate", "delete"):
            if picked is None:
                self.app.log("select a project first", "warn")
                return False
            if action == "shortcut":
                self.app.create_shortcut(picked["path"])
            elif action == "rename":
                self.app.prompt_project_rename(picked["path"], picked["folder"])
            elif action == "icon":
                self.app.prompt_project_icon(picked["path"])
            elif action == "duplicate":
                self.app.prompt_project_duplicate(picked["path"],
                                                  picked["folder"])
            else:
                self.app.prompt_project_delete(picked["path"])
        elif action == "open":
            self.open_selected(picked)
        elif action == "quit":
            self.app.running = False
        else:
            return False
        return True

    def open_selected(self, entry=None):
        picked = entry or self.selected_entry()
        if picked is None:
            return False
        return self.app.open_project(picked["path"])
