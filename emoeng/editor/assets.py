"""The Assets tab:"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pygame

from .. import const
from ..engine import loader, scenedoc, xp
from . import widgets
from .mediaplayer import clock, wav_info, waveform_image

FOLDERS = (
    ("all", "All"),
    ("scenes", "Scenes"),
    ("objects", "Objects"),
    ("entities", "Entities"),
    ("scripts", "Scripts"),
    ("models", "Models"),
    ("maps", "Maps"),
    ("textures", "Textures"),
    ("audio", "Audio"),
)
# the folder rail wears the editor's own pictures
FOLDER_ICONS = {
    "all": "menu-sym",
    "scenes": "file-scene-3d",
    "objects": "file-object-3d",
    # an entity is a scripted actor, so it borrows the player's picture
    "entities": "file-object-player3d",
    "scripts": "file-code-sym",
    "models": "file-model-sym",
    "maps": "file-model3d-sym",
    "textures": "file-image-sym",
    "audio": "file-audio-sym",
}
# cards key on the dimensioned spellings; `.model` is solid
MODEL3D_EXTS = (scenedoc.MODEL3D_EXT, scenedoc.MODEL_EXT)
MAP3D_EXTS = (scenedoc.MAP3D_EXT,)
IMAGE_EXT = (".png", ".jpg", ".jpeg")
# optional manifest files: a keymap and import settings
SIDECAR_EXT = (".json",)
CARD_W = 116
CARD_H = 100
THUMB_H = 58
GAP = 9


def ellipsize(font, text, width):
    text = str(text)
    if font.size(text)[0] <= width:
        return text
    while len(text) > 3 and font.size(text + "...")[0] > width:
        text = text[:-1]
    return text + "..."


class AssetBrowser:
    """Grid asset viewer with generated thumbnails."""

    def __init__(self, app):
        self.app = app
        self.fonts = app.fonts
        self.project = None
        self.folder = "all"
        self.selected = None
        self.scroll = 0
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.header = pygame.Rect(0, 0, 0, 0)
        self.side = pygame.Rect(0, 0, 0, 0)
        self.side_head = pygame.Rect(0, 0, 0, 0)
        self.grid = pygame.Rect(0, 0, 0, 0)
        self.folder_rows = []
        self.cards = []
        self.import_row = pygame.Rect(0, 0, 0, 0)
        self._thumbs = {}
        self._last_click = (None, 0.0)

    def set_project(self, project):
        self.project = project
        self.selected = None
        self.scroll = 0
        self._thumbs = {}
        if project is not None:
            self.app.log("assets tab ready", "muted")

    def files(self):
        if self.project is None:
            return []
        if self.folder == "all":
            paths = [self.project.path / const.MANIFEST_NAME]
            for name in (loader.INPUT_NAME, loader.ASSET_NAME):
                side = self.project.path / name
                if side.is_file():
                    paths.append(side)
            for kind in ("scenes", "objects", "entities", "scripts",
                         "models", "maps", "textures", "audio"):
                paths.extend(self.project.files(kind))
        else:
            paths = list(self.project.files(self.folder))
        return [p for p in paths if p.is_file()]

    def _sorted_files(self):
        order = {"scenes": 1, "objects": 2, "entities": 3, "scripts": 4,
                 "models": 5, "maps": 6, "textures": 7, "audio": 8}

        def key(path):
            if path.parent == self.project.path:
                return (0, path.name.lower())     # manifest and sidecars
            return (order.get(path.parent.name, 9), path.name.lower())

        return sorted(self.files(), key=key)

    def _layout(self, rect):
        self.rect = pygame.Rect(rect)
        self.header = pygame.Rect(rect.x, rect.y, rect.width, 22)
        body = pygame.Rect(rect.x, self.header.bottom, rect.width,
                           rect.height - self.header.height)
        side_w = min(148, max(104, body.width // 4))
        self.side = pygame.Rect(body.x, body.y, side_w, body.height)
        self.side_head = pygame.Rect(self.side.x, self.side.y,
                                     self.side.width, 20)
        self.grid = pygame.Rect(self.side.right + 7, body.y + 3,
                                body.right - self.side.right - 13,
                                body.height - 6)

    def draw(self, surface, rect):
        self._layout(rect)
        pygame.draw.rect(surface, xp.FACE, self.rect)
        files = self._sorted_files()
        widgets.header(surface, self.header, "Assets", self.fonts["normal"],
                       right=f"{len(files)} files", icon="tab-assets-sym")
        self._draw_side(surface)
        self._draw_grid(surface, files)

    def _draw_side(self, surface):
        pygame.draw.rect(surface, xp.FACE, self.side)
        widgets.header(surface, self.side_head, "Folders",
                       self.fonts["small"], icon="open-folder-sym")
        pygame.draw.line(surface, xp.SHADOW, (self.side.right - 1,
                                              self.side.y),
                         (self.side.right - 1, self.side.bottom))
        self.folder_rows = []
        y = self.side_head.bottom + 2
        mouse = pygame.mouse.get_pos()
        for kind, label in FOLDERS:
            row = pygame.Rect(self.side.x, y, self.side.width - 2, 22)
            self.folder_rows.append((kind, row))
            if kind == self.folder:
                surface.fill(xp.SELECTION, row)
            elif row.collidepoint(mouse):
                surface.fill(xp.BTN_HOVER_BG, row)
            if kind == "all":
                count = len(self._sorted_files())
            elif self.project is not None:
                count = len(self.project.files(kind))
            else:
                count = 0
            color = xp.SELECT_TEXT if kind == self.folder else xp.TEXT
            tx = row.x + 8
            if widgets.draw_icon(surface, FOLDER_ICONS.get(kind, ""),
                                 pygame.Rect(tx, row.centery - 7, 14, 14)):
                tx += 18
            img = widgets.cached_text(self.fonts["normal"], label, color)
            surface.blit(img, (tx, row.centery - img.get_height() // 2))
            img = widgets.cached_text(self.fonts["small"], str(count),
                                      xp.SELECT_SUBTEXT if kind == self.folder
                                      else xp.TEXT_MUTED)
            surface.blit(img, (row.right - 8 - img.get_width(),
                               row.centery - img.get_height() // 2))
            y = row.bottom + 1
        self._draw_import_row(surface, y + 4, mouse)
        hint = widgets.cached_text(self.fonts["small"],
                                   "double-click to open", xp.TEXT_MUTED)
        surface.blit(hint, (self.side.x + 6,
                            self.side.bottom - hint.get_height() - 4))

    def _draw_import_row(self, surface, y, mouse):
        """The folder rail's *Import...* button; copies files into the project."""
        self.import_row = pygame.Rect(0, 0, 0, 0)
        if self.project is None:
            return
        rect = pygame.Rect(self.side.x, y, self.side.width - 2, 22)
        self.import_row = rect
        if rect.collidepoint(mouse):
            surface.fill(xp.BTN_HOVER_BG, rect)
        pygame.draw.rect(surface, xp.OUTLINE, rect, 1)
        tx = rect.x + 8
        if widgets.draw_icon(surface, "open-folder-sym",
                             pygame.Rect(tx, rect.centery - 7, 14, 14)):
            tx += 18
        img = widgets.cached_text(self.fonts["small"], "Import...", xp.TEXT)
        surface.blit(img, (tx, rect.centery - img.get_height() // 2))

    def _draw_grid(self, surface, files):
        pygame.draw.rect(surface, xp.CARD_BG, self.grid)
        xp.sunken(surface, self.grid)
        inner = self.grid.inflate(-3, -3)
        self.cards = []
        if not files:
            msg = "open a project" if self.project is None else "empty folder"
            img = widgets.cached_text(self.fonts["normal"], msg,
                                      xp.TEXT_MUTED)
            surface.blit(img, (inner.x + 12, inner.y + 10))
            return
        columns = max(1, (inner.width + GAP) // (CARD_W + GAP))
        rows = (len(files) + columns - 1) // columns
        content_h = rows * (CARD_H + GAP) + 4
        max_scroll = max(0, content_h - inner.height)
        self.scroll = max(0, min(self.scroll, max_scroll))
        mouse = pygame.mouse.get_pos()
        for index, path in enumerate(files):
            col = index % columns
            row = index // columns
            x = inner.x + 2 + col * (CARD_W + GAP)
            y = inner.y + 2 + row * (CARD_H + GAP) - self.scroll
            rect = pygame.Rect(x, y, CARD_W, CARD_H)
            if rect.bottom < inner.y or rect.y > inner.bottom:
                continue
            self.cards.append((rect, path))
            selected = self.selected is not None and path == self.selected
            if selected:
                surface.fill(xp.BTN_HOVER_BG, rect)
                pygame.draw.rect(surface, xp.SELECT_BORDER, rect, 2)
            elif rect.collidepoint(mouse):
                surface.fill(xp.BTN_HOVER_BG, rect)
            thumb_area = pygame.Rect(rect.x + 5, rect.y + 4,
                                     rect.width - 10, THUMB_H)
            pygame.draw.rect(surface, xp.FIELD, thumb_area)
            xp.sunken(surface, thumb_area)
            thumb = self.thumbnail(path, thumb_area.inflate(-2, -2).size)
            if thumb is not None:
                surface.blit(thumb, (thumb_area.centerx -
                                     thumb.get_width() // 2,
                                     thumb_area.centery -
                                     thumb.get_height() // 2))
            label = ellipsize(self.fonts["small"], path.name,
                              rect.width - 10)
            img = widgets.cached_text(self.fonts["small"], label, xp.TEXT)
            surface.blit(img, (rect.x + 5, thumb_area.bottom + 3))
            sub = self._folder_label(path)
            img = widgets.cached_text(self.fonts["small"], sub,
                                      xp.TEXT_MUTED)
            surface.blit(img, (rect.x + 5, rect.bottom - img.get_height() - 2))
        if max_scroll > 0:
            xp.scrollbar(surface, pygame.Rect(self.grid.right - 11,
                                              self.grid.y + 2, 9,
                                              self.grid.height - 4),
                         self.scroll / max(1, content_h),
                         self.grid.height / max(1, content_h))

    def _folder_label(self, path):
        """The small line under a card's name."""
        name = path.name
        if name == const.MANIFEST_NAME:
            return "manifest"
        if name in (loader.INPUT_NAME, loader.ASSET_NAME):
            return "project file"
        return path.parent.name

    def thumbnail(self, path, size):
        path = Path(path)
        size = (max(8, int(size[0])), max(8, int(size[1])))
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return None
        key = (str(path), mtime, size)
        if key in self._thumbs:
            return self._thumbs[key]
        suffix = path.suffix.lower()
        thumb = None
        if suffix in IMAGE_EXT:
            thumb = self._image_thumb(path, size)
        elif suffix in (".wav", ".ogg", ".mp3", ".flac"):
            thumb = waveform_image(path, size)
        elif suffix in MODEL3D_EXTS:
            thumb = self._model_thumb(path, size)
        elif suffix in MAP3D_EXTS:
            thumb = self._map_thumb(path, size)
        elif suffix == scenedoc.MODEL2D_EXT:
            thumb = self._model2d_thumb(path, size)
        elif suffix == ".py":
            thumb = self._code_thumb(path, size)
        elif suffix == ".flig":
            thumb = self._manifest_thumb(path, size)
        elif suffix in SIDECAR_EXT:
            thumb = self._code_thumb(path, size)
        self._thumbs[key] = thumb
        return thumb

    def _image_thumb(self, path, size):
        try:
            img = pygame.image.load(str(path))
            img = img.convert_alpha() if img.get_alpha() else img.convert()
        except pygame.error:
            return None
        scale = min(size[0] / max(1, img.get_width()),
                    size[1] / max(1, img.get_height()))
        target = (max(1, int(img.get_width() * scale)),
                  max(1, int(img.get_height() * scale)))
        return pygame.transform.smoothscale(img, target)

    def _model_thumb(self, path, size):
        surf = pygame.Surface(size)
        surf.fill(xp.THUMB_BG)
        verts = tris = 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            verts = len(data.get("verts", ()))
            tris = len(data.get("tris", ()))
        except Exception:
            pass
        w, h = size
        cx, cy = w // 2, int(h * 0.44)
        s = max(6, min(w, h) * 0.24)
        top = [(cx, cy - s * 1.25), (cx + s, cy - s * 0.6), (cx, cy),
               (cx - s, cy - s * 0.6)]
        left = [(cx - s, cy - s * 0.6), (cx, cy), (cx, cy + s * 1.2),
                (cx - s, cy + s * 0.55)]
        right = [(cx + s, cy - s * 0.6), (cx, cy), (cx, cy + s * 1.2),
                 (cx + s, cy + s * 0.55)]
        for poly, color in ((left, (196, 128, 52)),
                            (right, (222, 156, 72)),
                            (top, (244, 190, 110))):
            pygame.draw.polygon(surf, color, poly)
            pygame.draw.lines(surf, (120, 72, 28), True, poly, 1)
        img = widgets.cached_text(self.fonts["small"],
                                  f"{verts} verts  {tris} tris",
                                  (120, 90, 60))
        surf.blit(img, (surf.get_width() // 2 - img.get_width() // 2,
                        h - img.get_height() - 2))
        return surf

    def _map_thumb(self, path, size):
        """A map card: the solid cube in cooler stone."""
        surf = pygame.Surface(size)
        surf.fill(xp.THUMB_BG)
        tris = objs = 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tris = len(data.get("tris", ()))
            objs = len(data.get("objects", ()))
        except Exception:
            pass
        w, h = size
        cx, cy = w // 2, int(h * 0.44)
        s = max(6, min(w, h) * 0.24)
        top = [(cx, cy - s * 1.25), (cx + s, cy - s * 0.6), (cx, cy),
               (cx - s, cy - s * 0.6)]
        left = [(cx - s, cy - s * 0.6), (cx, cy), (cx, cy + s * 1.2),
                (cx - s, cy + s * 0.55)]
        right = [(cx + s, cy - s * 0.6), (cx, cy), (cx, cy + s * 1.2),
                 (cx + s, cy + s * 0.55)]
        for poly, color in ((left, (96, 116, 132)),
                            (right, (128, 150, 168)),
                            (top, (168, 188, 204))):
            pygame.draw.polygon(surf, color, poly)
            pygame.draw.lines(surf, (60, 76, 92), True, poly, 1)
        img = widgets.cached_text(self.fonts["small"],
                                  f"{tris} tris  {objs} objs",
                                  (70, 90, 108))
        surf.blit(img, (surf.get_width() // 2 - img.get_width() // 2,
                        h - img.get_height() - 2))
        return surf

    def _model2d_thumb(self, path, size):
        """A flat cutout card: one outlined quad, part count."""
        surf = pygame.Surface(size)
        surf.fill(xp.THUMB_BG)
        parts = tracks = 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            parts = len(data.get("parts", ()))
            tracks = len(data.get("tracks", ()))
        except Exception:
            pass
        w, h = size
        box = pygame.Rect(int(w * 0.26), int(h * 0.16), int(w * 0.48),
                          int(h * 0.56))
        pygame.draw.rect(surf, (108, 164, 210), box)
        pygame.draw.rect(surf, (52, 88, 120), box, 2)
        img = widgets.cached_text(self.fonts["small"],
                                  f"{parts} parts  {tracks} tracks",
                                  (90, 110, 130))
        surf.blit(img, (w // 2 - img.get_width() // 2,
                        h - img.get_height() - 2))
        return surf

    def _code_thumb(self, path, size):
        surf = pygame.Surface(size)
        surf.fill(xp.THUMB_BG)
        try:
            lines = path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()[:4]
        except OSError:
            lines = []
        y = 3
        for line in lines:
            text = line.strip()
            if not text:
                y += self.fonts["mono"].get_height()
                continue
            color = xp.SYN_KW if text.startswith(("def ", "class ",
                                                "import ", "from ")) \
                else xp.CODE_TEXT
            img = widgets.cached_text(self.fonts["mono"],
                                      ellipsize(self.fonts["mono"], text,
                                                size[0] - 6), color)
            if img is not None:
                surf.blit(img, (3, y))
            y += img.get_height() if img is not None else 12
            if y > size[1] - 4:
                break
        return surf

    def _manifest_thumb(self, path, size):
        surf = pygame.Surface(size)
        surf.fill(xp.THUMB_BG)
        # read_meta upgrades old flat manifests, matching the engine
        meta = loader.read_meta(path)
        shown = (("name", meta.get("name")),
                 ("title", meta.get("title")),
                 ("start", meta.get("start")),
                 ("scale", loader.meta_get(meta, "render", "scale")))
        y = 3
        for key, value in shown:
            if value is None:
                continue
            text = f"{key}: {value}"
            img = widgets.cached_text(self.fonts["small"],
                                      ellipsize(self.fonts["small"], text,
                                                size[0] - 6),
                                      xp.TEXT_MUTED)
            if img is None:
                continue
            if y + img.get_height() > size[1] - 2:
                break
            surf.blit(img, (3, y))
            y += img.get_height() + 1
        return surf

    def describe(self, path):
        path = Path(path)
        rows = [("File", path.name)]
        if self.project is not None:
            rows.append(("Folder", self.project.relative(path.parent)))
        try:
            stat = path.stat()
            rows.append(("Size", f"{stat.st_size / 1024:.1f} KB"))
            rows.append(("Modified", time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))))
        except OSError:
            pass
        suffix = path.suffix.lower()
        if suffix in MODEL3D_EXTS:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rows += [("Vertices", str(len(data.get("verts", ())))),
                         ("Faces", str(len(data.get("tris", ())))),
                         ("Texture", str(data.get("texture", "-")))]
            except Exception:
                pass
        elif suffix in MAP3D_EXTS:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rows += [("Vertices", str(len(data.get("verts", ())))),
                         ("Faces", str(len(data.get("tris", ())))),
                         ("Objects", str(len(data.get("objects", ()))))
                         or "(one part)"]
            except Exception:
                pass
        elif suffix == scenedoc.MODEL2D_EXT:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sheet = data.get("size") or ["-", "-"]
                rows += [("Parts", str(len(data.get("parts", ())))),
                         ("Tracks", str(len(data.get("tracks", ())))),
                         ("Sheet", f"{sheet[0]:g} x {sheet[1]:g}"),
                         ("Texture", str(data.get("texture") or "-"))]
            except Exception:
                pass
        elif suffix == scenedoc.SCENE_EXT or \
                suffix in scenedoc.OBJECT_EXTS + scenedoc.ENTITY_EXTS:
            # a document reads as the node it builds
            doc = scenedoc.load(path, scenedoc.kind_of(path) or "scene")
            row = [("Script", str(doc.get("script") or "-"))]
            if doc.get("type"):
                row = [("Type", str(doc.get("type")))] + row
            placed = list(scenedoc.walk(doc))
            if placed:
                row += [("Nodes", str(len(placed)))]
            rows += row
        elif suffix in IMAGE_EXT:
            try:
                img = pygame.image.load(str(path))
                rows.append(("Image", f"{img.get_width()} x {img.get_height()}"))
            except pygame.error:
                pass
        elif suffix in (".wav", ".ogg", ".mp3", ".flac"):
            info = wav_info(path)
            if info is not None:
                rows += [("Length", clock(info["duration"])),
                         ("Rate", f"{info['rate']} Hz"),
                         ("Channels", str(info["channels"]))]
        elif suffix == ".py":
            try:
                rows.append(("Lines", str(len(path.read_text(
                    encoding="utf-8", errors="replace").splitlines()))))
            except OSError:
                pass
        elif suffix == ".flig":
            meta = loader.read_meta(path)
            if meta:
                rows += [("Title", str(meta.get("title", "-"))),
                         ("Start", str(meta.get("start", "-"))),
                         ("Version", str(meta.get("version", "-"))),
                         ("Format", str(meta.get("format", "-"))),
                         ("Scale", str(loader.meta_get(meta, "render",
                                                        "scale", "-"))),
                         ("Post shaders", ", ".join(
                             loader.meta_get(meta, "render", "post", ()))
                             or "none")]
        elif suffix in SIDECAR_EXT and path.name in (
                loader.INPUT_NAME, loader.ASSET_NAME):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if path.name == loader.INPUT_NAME:
                actions = data.get("actions") or {}
                rows.append(("Actions",
                             ", ".join(f"{k}:{'/'.join(v)}"
                                       for k, v in actions.items()
                                       if not str(k).startswith("_"))
                             or "engine defaults"))
            else:
                for kind in ("textures", "audio"):
                    opts = data.get(kind)
                    if isinstance(opts, dict):
                        rows.append((kind.title(), ", ".join(
                            f"{k}={v}" for k, v in sorted(opts.items())
                            if not str(k).startswith("_"))))
        return rows

    def info(self):
        if self.project is None:
            return [("Folder", "-"), ("Files", "0")]
        label = dict(FOLDERS).get(self.folder, self.folder)
        rows = [("Folder", label), ("Files", str(len(self._sorted_files())))]
        if self.selected is not None:
            rows.append(("Selected", self.selected.name))
        return rows

    def handle_event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and \
                    self.selected is not None:
                self.app.activate_asset(self.selected)
                return True
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
            return self._right_click(e.pos)
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            pos = e.pos
            if self.import_row.collidepoint(pos):
                self.app.import_dialog()
                return True
            for kind, row in self.folder_rows:
                if row.collidepoint(pos):
                    self.folder = kind
                    self.scroll = 0
                    self.selected = None
                    self.app.select_asset(None)
                    return True
            for rect, path in self.cards:
                if rect.collidepoint(pos):
                    self.selected = path
                    self.app.select_asset(path)
                    now = time.time()
                    again = (self._last_click[0] == path and
                             now - self._last_click[1] < 0.42)
                    self._last_click = (path, now)
                    if again:
                        self.app.activate_asset(path)
                    return True
            return True
        if e.type == pygame.MOUSEWHEEL:
            if self.grid.collidepoint(pygame.mouse.get_pos()):
                self.scroll = max(0, self.scroll - e.y * 34)
                return True
        return False

    def _right_click(self, pos):
        """Open the shared file menu over a card row."""
        for rect, path in self.cards:
            if rect.collidepoint(pos):
                self.app.show_file_menu(path, pos)
                return True
        for kind, row in self.folder_rows:
            if kind != "all" and row.collidepoint(pos) and \
                    self.project is not None:
                self.app.show_folder_menu(self.project.dir(kind), pos)
                return True
        return False
