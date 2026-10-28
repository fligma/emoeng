"""Editor widgets on XP primitives: tree, field, panel."""

import os
import time

import pygame

from ..engine import colors, scenedoc, xp
from ..engine.loader import (OBJECT_PRESETS, SCENE_PRESETS, SHADER_PRESETS)

_TEXT_CACHE = {}
_CACHE_LIMIT = 8000

# A viewport that grabs the mouse leaves the system cursor parked at its own
# centre, so every `get_pos()` hover read lights a button the user is nowhere
# near. `park_pointer` answers pygame's getter with a point outside all of
# them for exactly as long as the pointer is held, which fixes the whole
# editor's hovers at once rather than one widget at a time.
_POINTER_OFF = (-32000, -32000)
_real_get_pos = pygame.mouse.get_pos
_parked = [False]


def _parked_pos():
    return _POINTER_OFF


def park_pointer(on=True):
    """Stop, or restart, widgets reacting to where the pointer sits."""
    on = bool(on)
    if on == _parked[0]:
        return
    _parked[0] = on
    pygame.mouse.get_pos = _parked_pos if on else _real_get_pos


def pointer_parked():
    """Is the pointer being held by a viewport?"""
    return _parked[0]


def mouse_pos():
    """The pointer to draw a hover with; off-screen while it is held."""
    return pygame.mouse.get_pos()


# 16x16 icons scaled nearest-neighbour, never smoothscale
_APPUI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "appUI")
_ICON_CACHE = {}


def icon(name, px=16):
    """The named PNG from editor/appUI, nearest-scaled to `px` and cached."""
    if not name:
        return None
    key = (name, int(px))
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    img = None
    try:
        raw = pygame.image.load(os.path.join(_APPUI, f"{name}.png"))
        try:
            raw = raw.convert_alpha()
        except pygame.error:
            pass
        size = (max(1, int(px)), max(1, int(px)))
        img = raw if raw.get_size() == size else pygame.transform.scale(raw,
                                                                        size)
    except (OSError, ValueError, pygame.error):
        img = None
    _ICON_CACHE[key] = img
    return img


def draw_icon(surf, name, rect):
    """Blit an icon centred in `rect`; False without art."""
    img = icon(name, min(rect.width, rect.height))
    if img is None:
        return False
    surf.blit(img, (rect.centerx - img.get_width() // 2,
                    rect.centery - img.get_height() // 2))
    return True


def scaled_image(name, px):
    """A larger piece of appUI artwork (the About portrait); nearest"""
    img = icon(name, px)
    if img is None:
        try:
            raw = pygame.image.load(os.path.join(_APPUI, f"{name}.png"))
            img = pygame.transform.scale(raw, (int(px), int(px)))
        except (OSError, ValueError, pygame.error):
            return None
    return img


def cached_text(font, text, color):
    if not text:
        return None
    key = (id(font), text, color)
    img = _TEXT_CACHE.get(key)
    if img is None:
        if len(_TEXT_CACHE) > _CACHE_LIMIT:
            _TEXT_CACHE.clear()
        img = font.render(text, True, color)
        _TEXT_CACHE[key] = img
    return img


def wrap(font, text, width):
    """Greedy word wrap into lines that fit `width` pixels."""
    words = str(text).split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for word in words[1:]:
        trial = current + " " + word
        if font.size(trial)[0] <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def elide(font, text, width):
    """`text` cut to `width` pixels with a `...` tail."""
    text = str(text)
    if not text or font is None or width <= 0:
        return text
    if font.size(text)[0] <= width:
        return text
    tail = "..."
    room = width - font.size(tail)[0]
    cut = text
    while cut and font.size(cut)[0] > room:
        cut = cut[:-1]
    return (cut.rstrip() + tail) if cut.strip() else tail


def clip(surf, rect):
    """Set `rect` as the clip, intersected with the current."""
    old = surf.get_clip()
    inner = old.clip(rect)
    if inner.width <= 0 or inner.height <= 0:
        return None
    surf.set_clip(inner)
    return old


def shift_held(event=None):
    """Whether Shift is down for this click."""
    mod = getattr(event, "mod", None)
    if mod is None:
        mod = pygame.key.get_mods()
    return bool(mod & pygame.KMOD_SHIFT)


def header(surf, rect, title, font, right=None, icon=None):
    """Dock header: a caption on a beige hairline bar."""
    surf.fill(xp.FACE, rect)
    pygame.draw.line(surf, xp.HILITE, (rect.x, rect.y),
                     (rect.right - 1, rect.y))
    pygame.draw.line(surf, xp.SHADOW, (rect.x, rect.bottom - 1),
                     (rect.right - 1, rect.bottom - 1))
    tx = rect.x + 8
    if icon and draw_icon(surf, icon,
                          pygame.Rect(tx, rect.centery - 8, 16, 16)):
        tx += 20
    # the count keeps its room; a long caption is cut
    right_img = cached_text(font, right, xp.TEXT_MUTED) if right else None
    end = rect.right - 8
    if right_img is not None:
        end -= right_img.get_width() + 8
    label = cached_text(font, elide(font, title, end - tx), xp.TEXT_MUTED)
    if label is not None:
        surf.blit(label, (tx, rect.centery - label.get_height() // 2))
    if right_img is not None:
        surf.blit(right_img, (rect.right - 8 - right_img.get_width(),
                              rect.centery - right_img.get_height() // 2))
    return rect


BAND_CAP = 12            # the caption line sitting on a band's top edge
BAND_H = 20              # the height of a band's buttons
BAND_PAD = 7             # room either side of a band's buttons
BAND_GAP = 6             # between neighbouring bands on one row


def bands(area, font, groups, cap=None, height=BAND_H, pad=BAND_PAD,
          gap=BAND_GAP, spread=True):
    """Flow captioned bands of buttons into rows across `area`'s width.

    `groups` is [(caption, [item, ...])], and an item is a sequence whose
    first entry is the button's label; it is handed back untouched, so a
    caller can keep its action beside its box. Returns (bands, height used),
    each band a dict of `caption`, `frame`, `buttons` [(item, rect)], the
    row it sits on and that row's height. A band that does not fit starts
    the next row rather than running off the edge, and a band wider than
    the strip turns its own buttons onto extra lines: a narrow window is
    allowed to cost height, never a button nobody can reach. The caption
    sits on the frame's top edge with the buttons below it, so the two can
    never overlap however tall the font is. Rows are measured first and
    then spread, so a row of sections fills the strip instead of stacking
    its spare room against one end.
    """
    cap = font.get_height() if cap is None else cap
    width = max(40, area.width - 6)
    room = max(24, width - pad * 2)
    sized = []
    for caption, items in groups:
        cells = [(item, max(24, font.size(str(item[0]))[0] + 14))
                 for item in items]
        lines, run, filled = [], [], 0
        for cell in cells:
            need = cell[1] + (4 if run else 0)
            if run and filled + need > room:
                lines.append(run)
                run, filled = [], 0
            run.append(cell)
            filled += cell[1] + (4 if len(run) > 1 else 0)
        if run:
            lines.append(run)
        wide = max(sum(w for _item, w in line) + (len(line) - 1) * 4
                   for line in lines)
        # a caption is never cut short, but it cannot outgrow the strip
        wide = min(max(wide, font.size(caption)[0] + 20) + pad * 2, width)
        sized.append((caption, lines, wide))
    rows = []
    run, filled = [], 0
    for entry in sized:
        need = entry[2] + (gap if run else 0)
        if run and filled + need > width:
            rows.append(run)
            run, filled, need = [], 0, entry[2]
        run.append(entry)
        filled += need
    if run:
        rows.append(run)
    out = []
    top = area.y + 8
    for n, row in enumerate(rows):
        step = gap
        if spread and len(row) > 1:
            slack = width - sum(entry[2] for entry in row)
            step = max(gap, min(gap * 3, slack / (len(row) - 1)))
        tall = max(cap + len(lines) * (height + 4) for _c, lines, _w in row)
        x = area.x + 3
        for caption, lines, wide in row:
            frame = pygame.Rect(int(x), top, wide,
                                cap + len(lines) * (height + 4) - 4 + 4)
            lined = []
            for li, line in enumerate(lines):
                bx = frame.x + pad
                y = frame.y + cap + li * (height + 4)
                for item, w in line:
                    lined.append((item, pygame.Rect(bx, y, w, height)))
                    bx += w + 4
            out.append({"caption": caption, "frame": frame,
                        "buttons": lined, "row": n, "row_h": tall})
            x = frame.right + step
        top += tall + 10
    return out, top - area.y


def band(surf, frame, caption, font):
    """Etched frame around a band of buttons, its caption on the top edge."""
    return xp.groupbox(surf, frame, caption, font)


# real 16x16 art per suffix; unknown names get a square
FILE_ICONS = {
    ".py": "file-code-sym",
    ".model": "file-model3d-sym",
    ".model3d": "file-model3d-sym",
    ".map3d": "file-model3d-sym",
    ".model2d": "file-model2d-sym",
    ".scene": "file-scene-3d",
    ".object": "file-object-3d",
    ".obj3d": "file-object-3d",
    ".obj2d": "file-object-2d",
    ".shader": "file-flig-sym",
    ".png": "file-image-sym",
    ".jpg": "file-image-sym",
    ".jpeg": "file-image-sym",
    ".wav": "file-audio-sym",
    ".ogg": "file-audio-sym",
    ".mp3": "file-audio-sym",
    ".flac": "file-audio-sym",
    ".flig": "file-flig-sym",
    ".json": "file-flig-sym",
    ".txt": "file-text-sym",
}

# node art off `NODE_TYPES`; bare types use family art
CLASS_ART = {"Model3D": "file-model3d-sym",
             "Sprite2D": "file-model2d-sym",
             "UIObject": "file-object-ui",
             "Object3D": "file-object-3d",
             "Object2D": "file-object-2d",
             "Player3D": "file-object-player3d",
             "Player2D": "file-object-player2d",
             # presets: light wears the sun, timer the clock
             "LightNode3D": "node-light-sym",
             "OmniLight3D": "node-light-sym",
             "SpotLight3D": "node-light-sym",
             "DirectionalLight3D": "node-light-sym",
             "LightNode2D": "node-light-sym",
             "PointLight2D": "node-light-sym",
             "ConeLight2D": "node-light-sym",
             "RectLight2D": "node-light-sym",
             "Timer3D": "node-timer-sym",
             "Timer2D": "node-timer-sym",
             "AudioEmitter3D": "sound-on-sym",
             "AudioEmitter2D": "sound-on-sym",
             "Text3D": "file-text-sym",
             "Text2D": "file-text-sym"}
FLAT_ART = {"3d": "file-object-3d", "2d": "file-object-2d"}


def node_icon(type_name):
    """The icon for a registry node type, by `type`."""
    row = scenedoc.node_type(type_name)
    if row is None:
        return None
    return CLASS_ART.get(row[5] or row[1], FLAT_ART.get(row[4]))


def class_icon(class_name):
    """The same picture, by engine class name."""
    for row in scenedoc.NODE_TYPES:
        if row[5] == class_name:
            return CLASS_ART.get(class_name, FLAT_ART.get(row[4]))
    return None


_ICON_COLORS = {
    ".py": ((66, 110, 180), "Py"),
    ".model": ((190, 120, 40), "3D"),
    ".model3d": ((190, 120, 40), "3D"),
    ".map3d": ((190, 120, 40), "Mp"),
    ".model2d": ((70, 140, 190), "2D"),
    ".scene": ((52, 124, 82), "Sc"),
    ".object": ((120, 96, 160), "Ob"),
    ".obj3d": ((120, 96, 160), "O3"),
    ".obj2d": ((70, 140, 190), "O2"),
    ".shader": ((150, 80, 160), "Sh"),
    ".png": ((70, 150, 90), "Im"),
    ".jpg": ((70, 150, 90), "Im"),
    ".wav": ((150, 80, 160), "Sd"),
    ".ogg": ((150, 80, 160), "Sd"),
    ".mp3": ((150, 80, 160), "Sd"),
    ".flac": ((150, 80, 160), "Sd"),
    ".flig": ((120, 96, 160), "Fl"),
    ".json": ((120, 96, 160), "Js"),
    ".txt": ((120, 120, 110), "Tx"),
}


def file_icon(surf, pos, suffix, font, size=16):
    rect = pygame.Rect(pos[0], pos[1], size, size)
    if draw_icon(surf, FILE_ICONS.get(str(suffix).lower(), ""), rect):
        return rect
    color, label = _ICON_COLORS.get(str(suffix).lower(),
                                    ((120, 120, 110), "??"))
    pygame.draw.rect(surf, color, rect, border_radius=2)
    pygame.draw.rect(surf, (30, 30, 30), rect, 1, border_radius=2)
    img = cached_text(font, label, (255, 255, 255))
    if img.get_width() > size - 2:
        img = pygame.transform.smoothscale(img, (size - 2,
                                                 max(6, img.get_height() - 2)))
    surf.blit(img, (rect.centerx - img.get_width() // 2,
                    rect.centery - img.get_height() // 2))
    return rect


class TreeView:
    """A flat project-row list with toggles and a scrollbar."""

    ROW_H = 19

    def __init__(self):
        self.rows = []
        self.rects = []
        self.create_rects = []      # (row, rect) for "+" buttons this frame
        self.fold_rects = []        # (row, rect) for a node's fold chevron
        self.scroll = 0
        self.selected = None
        self.hover = -1
        self.hover_tip = None
        self.hover_point = (0, 0)

    def set_rows(self, rows):
        self.rows = rows
        self.scroll = 0

    def visible(self, area):
        return max(1, area.height // self.ROW_H)

    def _clamp(self, area):
        rows = len(self.rows)
        max_scroll = max(0, rows - self.visible(area))
        self.scroll = max(0, min(self.scroll, max_scroll))
        return max_scroll

    def scroll_by(self, dy, area):
        self.scroll += dy
        self._clamp(area)

    def draw(self, surf, area, font, small):
        pygame.draw.rect(surf, xp.FIELD, area)
        xp.sunken(surf, area)
        self.hover = -1
        mouse = pygame.mouse.get_pos()
        self.hover_tip = None
        self.hover_point = mouse
        self._clamp(area)
        inner = area.inflate(-2, -2)
        # the loop starts at `scroll`, top row first
        y = inner.y + 2
        self.rects = []
        self.create_rects = []
        self.fold_rects = []
        rows = len(self.rows)
        count = self.visible(inner) + 1
        old_clip = surf.get_clip()
        surf.set_clip(inner)         # never paint over the neighbouring dock
        for i in range(self.scroll, min(rows, self.scroll + count)):
            if y > inner.bottom - 2:
                break
            row = self.rows[i]
            kind = row.get("kind")
            rect = pygame.Rect(inner.x, y, inner.width - 12, self.ROW_H)
            self.rects.append(rect)
            if rect.collidepoint(mouse):
                self.hover = i
            if kind != "section" and (i == self.selected or
                                      rect.collidepoint(mouse)):
                bg = xp.SELECTION if i == self.selected else xp.BTN_HOVER_BG
                surf.fill(bg, rect)
            indent = 8 + row.get("depth", 0) * 12
            tx = rect.x + indent
            if kind == "section":
                # a muted caption leading the band, deliberately unselectable
                img = cached_text(small, elide(small, row["label"],
                                               rect.right - tx),
                                  xp.TEXT_MUTED)
                if img is not None:
                    surf.blit(img, (tx, rect.y + 4))
                y += self.ROW_H
                continue
            # nodes and tree scenes fold from a chevron
            if row.get("has") and kind in ("node", "scene", "file"):
                chev = "+" if not row.get("open", True) else "-"
                box = pygame.Rect(tx, rect.y, 11, self.ROW_H)
                self.fold_rects.append((row, box))
                if box.collidepoint(mouse):
                    self.hover_tip = ("Expand " if not row.get("open", True)
                                       else "Collapse ") + row["label"]
                surf.blit(cached_text(small, chev, xp.TEXT), (tx, rect.y + 3))
                tx += 12
            icon_name = row.get("icon")
            drawn = bool(icon_name) and draw_icon(
                surf, icon_name, pygame.Rect(tx, rect.y + 1, 16, 16))
            if drawn:
                tx += 20
            elif row.get("kind") == "folder":
                chev = "+" if not row.get("open") else "-"
                surf.blit(cached_text(small, chev, xp.TEXT),
                          (tx, rect.y + 3))
                tx += 12
            elif row.get("kind") == "file":
                file_icon(surf, (tx, rect.y + 3),
                          row["path"].suffix, small, 13)
                tx += 18
            elif row.get("kind") == "scene":
                icon = pygame.Rect(tx, rect.y + 3, 13, 13)
                pygame.draw.rect(surf, (52, 124, 82), icon,
                                 border_radius=2)
                pygame.draw.rect(surf, (24, 62, 40), icon, 1,
                                 border_radius=2)
                pygame.draw.polygon(surf, (255, 255, 255),
                                    [(icon.x + 4, icon.y + 3),
                                     (icon.x + 10, icon.centery),
                                     (icon.x + 4, icon.bottom - 3)])
                tx += 18
            elif row.get("kind") == "node":
                dot = pygame.Rect(tx + 3, rect.centery - 2, 5, 5)
                pygame.draw.rect(surf, xp.TEXT_MUTED, dot, border_radius=2)
                tx += 16
            else:
                img = cached_text(small, "proj", (70, 90, 140))
                surf.blit(img, (tx, rect.y + 3))
                tx += 26
            color = (255, 255, 255) if i == self.selected else xp.TEXT
            # rows end at the scroll strip; long names cut
            plus = row.get("create")
            room = rect.right - tx - 2 - (17 if plus else 0)
            label = cached_text(font, elide(font, row["label"], room), color)
            if label is not None:
                surf.blit(label, (tx, rect.y + 2))
            if plus:
                box = pygame.Rect(rect.right - 15, rect.y + 2, 13,
                                  self.ROW_H - 4)
                self.create_rects.append((row, box))
                if box.collidepoint(mouse):
                    surf.fill(xp.BTN_HOVER_BG, box)
                    self.hover_tip = f"Create an item in {row['label']}."
                pygame.draw.line(surf, xp.TEXT,
                                 (box.centerx - 4, box.centery),
                                 (box.centerx + 4, box.centery))
                pygame.draw.line(surf, xp.TEXT,
                                 (box.centerx, box.centery - 4),
                                 (box.centerx, box.centery + 4))
            y += self.ROW_H
        surf.set_clip(old_clip)
        max_scroll = max(0, rows - self.visible(inner))
        if max_scroll > 0:
            frac = self.scroll / max_scroll
            page = self.visible(inner) / max(1, rows)
            xp.scrollbar(surf, pygame.Rect(area.right - 13, area.y + 2,
                                           11, area.height - 4), frac, page)

    def click(self, pos):
        for i, rect in enumerate(self.rects):
            if rect.collidepoint(pos):
                row = self.rows[i + self.scroll]
                if row.get("kind") == "section":
                    return None         # a heading is not a row you pick
                self.selected = i + self.scroll
                return self.rows[self.selected]
        return None

    def create_at(self, pos):
        """The folder row whose plus sits at `pos`, or None."""
        for row, rect in self.create_rects:
            if rect.collidepoint(pos):
                return row
        return None

    def fold_at(self, pos):
        """The node row whose chevron sits at `pos`, or None."""
        for row, rect in self.fold_rects:
            if rect.collidepoint(pos):
                return row
        return None


class TextField:
    """Single-line text input with a caret."""

    def __init__(self, text="", max_len=64):
        self.text = text
        self.caret = len(text)
        self.max_len = max_len

    def set(self, text):
        self.text = str(text)
        self.caret = len(self.text)

    def handle(self, e):
        if e.type != pygame.KEYDOWN:
            return None
        if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return "submit"
        if e.key == pygame.K_BACKSPACE:
            if self.caret > 0:
                self.text = self.text[:self.caret - 1] + self.text[self.caret:]
                self.caret -= 1
                return "changed"
        elif e.key == pygame.K_DELETE:
            self.text = self.text[:self.caret] + self.text[self.caret + 1:]
            return "changed"
        elif e.key == pygame.K_LEFT:
            self.caret = max(0, self.caret - 1)
        elif e.key == pygame.K_RIGHT:
            self.caret = min(len(self.text), self.caret + 1)
        elif e.key == pygame.K_HOME:
            self.caret = 0
        elif e.key == pygame.K_END:
            self.caret = len(self.text)
        elif e.unicode and e.unicode.isprintable() and len(self.text) < \
                self.max_len:
            self.text = self.text[:self.caret] + e.unicode + \
                self.text[self.caret:]
            self.caret += 1
            return "changed"
        return None

    def draw(self, surf, rect, font, focused=True):
        xp.field(surf, rect)
        img = cached_text(font, self.text, xp.TEXT)
        if img is not None:
            surf.blit(img, (rect.x + 4, rect.centery - img.get_height() // 2))
        if focused and (time.time() * 2) % 1 < 0.6:
            cx = rect.x + 4 + font.size(self.text[:self.caret])[0]
            pygame.draw.line(surf, xp.CARET, (cx, rect.y + 3),
                             (cx, rect.bottom - 3))
        return rect


class Choices:
    """The list under a field: words it can take."""

    ROW_H = 18
    MAX_ROWS = 9
    WIDE = 170

    def __init__(self, words, anchor, bounds):
        self.all = [str(word) for word in words]
        self.anchor = pygame.Rect(anchor)
        self.bounds = pygame.Rect(bounds)
        self.words = list(self.all)
        self.hidden = 0
        self.sel = 0 if self.words else -1
        self.rows = []
        self.rect = pygame.Rect(0, 0, 0, 0)

    def filter(self, text):
        """Keep the words matching what has been typed so far."""
        want = str(text or "").strip().strip("'\"").lower()
        got = list(self.all)
        if want:
            head = [word for word in got if word.lower().startswith(want)]
            rest = [word for word in got
                    if word not in head and want in word.lower()]
            got = head + rest
        self.words = got[:self.MAX_ROWS]
        self.hidden = len(got) - len(self.words)
        self.sel = 0 if self.words else -1
        return self

    def step(self, delta):
        """Move the highlight, wrapping round the list."""
        if self.words:
            self.sel = (self.sel + delta) % len(self.words)
        return self.current()

    def current(self):
        """The highlighted word, or None while the list is empty."""
        if 0 <= self.sel < len(self.words):
            return self.words[self.sel]
        return None

    def click(self, pos):
        """The word whose row is under the point, else None."""
        for word, rect in self.rows:
            if rect.collidepoint(pos):
                return word
        return None

    def holds(self, pos):
        """Whether the point is inside the panel."""
        return self.rect.collidepoint(pos)

    def _place(self, font):
        """The panel's box: under the field unless it overflows."""
        rows = max(1, len(self.words) + (1 if self.hidden else 0))
        wide = self.WIDE
        if font is not None and self.words:
            wide = max(wide, max(font.size(word)[0] for word in
                                 self.words) + 22)
        wide = max(80, min(wide, max(80, self.bounds.width - 4)))
        tall = rows * self.ROW_H + 6
        x = max(self.bounds.x + 1,
                min(self.anchor.x, self.bounds.right - wide - 1))
        y = self.anchor.bottom + 1
        if y + tall > self.bounds.bottom:
            y = max(self.bounds.y + 1, self.anchor.top - tall - 1)
        self.rect = pygame.Rect(x, y, wide, tall)

    def draw(self, surface, font):
        """Paint the rows, highlighted first, then the rest."""
        self._place(font)
        pygame.draw.rect(surface, xp.FACE, self.rect)
        pygame.draw.rect(surface, xp.OUTLINE, self.rect, 1)
        mouse = pygame.mouse.get_pos()
        self.rows = []
        if not self.words:
            img = cached_text(font, "nothing matches", xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (self.rect.x + 6,
                                   self.rect.y + 3 +
                                   (self.ROW_H - img.get_height()) // 2))
            return self.rect
        y = self.rect.y + 3
        for index, word in enumerate(self.words):
            row = pygame.Rect(self.rect.x + 2, y, self.rect.width - 4,
                              self.ROW_H)
            if index == self.sel:
                surface.fill(xp.SELECTION, row)
            elif row.collidepoint(mouse):
                surface.fill(xp.BTN_HOVER_BG, row)
            ink = xp.SELECT_TEXT if index == self.sel else xp.TEXT
            img = cached_text(font, elide(font, word, row.width - 10), ink)
            if img is not None:
                surface.blit(img, (row.x + 5,
                                   row.centery - img.get_height() // 2))
            self.rows.append((word, row))
            y += self.ROW_H
        if self.hidden:
            img = cached_text(font, f"+{self.hidden} more", xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (self.rect.x + 6, y + 1))
        return self.rect


class PromptDialog:
    """One-field XP dialog: New Scene, New Model, Rename..."""

    PICK_W = 168

    def __init__(self, title, label, value="", on_ok=None, width=400,
                 hint=None, choices=None, choice_label="Template",
                 choice=None):
        self.title = title
        self.label = label
        self.hint = hint
        self.field = TextField(value)
        self.choices = [(str(v), str(t)) for v, t in (choices or ())]
        self.choice_label = choice_label
        values = [v for v, _t in self.choices]
        self.choice = choice if choice in values else \
            (values[0] if values else None)
        self.on_ok = on_ok
        self.width = width
        height = 150 if not hint else 172
        if self.choices:
            height += 32
        self.rect = pygame.Rect(0, 0, width, height)
        self.ok = pygame.Rect(0, 0, 86, 26)
        self.cancel = pygame.Rect(0, 0, 86, 26)
        self.pick = pygame.Rect(0, 0, self.PICK_W, 24)
        self.focus = True

    @property
    def answer(self):
        """The two answers as one payload, or None."""
        if not self.choices:
            return None
        return {"name": self.field.text, "choice": self.choice}

    def choice_text(self):
        """The label of the option currently on show."""
        for value, text in self.choices:
            if value == self.choice:
                return text
        return ""

    def cycle(self):
        """Step the chooser on to the next option."""
        if not self.choices:
            return None
        values = [v for v, _t in self.choices]
        try:
            i = values.index(self.choice)
        except ValueError:
            i = -1
        self.choice = values[(i + 1) % len(values)]
        return self.choice

    def _layout(self, size):
        self.rect.center = (size[0] // 2, size[1] // 2)
        f = self.rect
        self.ok.bottomright = (f.right - 14, f.bottom - 14)
        self.cancel.bottomright = (self.ok.x - 8, self.ok.bottom)

    def draw(self, surf, fonts):
        size = surf.get_size()
        self._layout(size)
        ui_dim = pygame.Surface(size, pygame.SRCALPHA)
        ui_dim.fill((0, 0, 0, 110))
        surf.blit(ui_dim, (0, 0))
        body, _close = xp.message_frame(surf, self.rect, self.title,
                                        fonts["normal"])
        surf.blit(cached_text(fonts["normal"], self.label, xp.TEXT),
                  (body.x + 16, body.y + 14))
        field = pygame.Rect(body.x + 16, body.y + 38, body.width - 32, 24)
        self.field.draw(surf, field, fonts["normal"], self.focus)
        y = field.bottom
        mouse = pygame.mouse.get_pos()
        if self.choices:
            # the second answer: label left, one stepping button right
            self.pick = pygame.Rect(field.right - self.PICK_W,
                                    field.bottom + 8, self.PICK_W, 24)
            surf.blit(cached_text(fonts["normal"], self.choice_label,
                                  xp.TEXT),
                      (body.x + 16, self.pick.y + 4))
            xp.button(surf, self.pick, self.choice_text(), fonts["normal"],
                      hovered=self.pick.collidepoint(mouse))
            y = self.pick.bottom
        if self.hint:
            img = cached_text(fonts["small"], self.hint, xp.TEXT_MUTED)
            surf.blit(img, (body.x + 16, y + 10))
        xp.button(surf, self.ok, "OK", fonts["normal"], default=True,
                  hovered=self.ok.collidepoint(mouse))
        xp.button(surf, self.cancel, "Cancel", fonts["normal"],
                  hovered=self.cancel.collidepoint(mouse))
        return body

    def handle(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                return "cancel"
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return "ok"
            self.field.handle(e)
            return None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.ok.collidepoint(e.pos):
                return "ok"
            if self.cancel.collidepoint(e.pos):
                return "cancel"
            if self.choices and self.pick.collidepoint(e.pos):
                self.cycle()
        return None


# bare asset kinds offered beside presets, with stems
ASSET_KINDS = (("new_model", "Model", "prop"),
               ("new_model_2d", "2D Model", "sprite"),
               ("new_script", "Script", "helpers"))


class CreateDialog:
    """The Godot-like New dialog: name, kind and picture."""

    CAP_H = 28
    ROW_H = 19
    FIELD_H = 24
    BTN_H = 26

    def __init__(self, project, kind, width=470, only=None):
        self.project = project
        self.width = width
        self.only = only
        self.rows = self._build_rows()                       # (kind, label)
        self.selected = self._index_of(kind) or self._first_kind()
        self.field = TextField(self._default_stem(self.selected))
        self.models = self._stems("models")
        self.textures = self._stems("textures")
        self.templates = list(SHADER_PRESETS)
        self.model = None
        self.texture = None
        self.template = self.templates[0] if self.templates else None
        self.answer = None
        self.rect = pygame.Rect(0, 0, width, 300)
        self.row_rects = []
        self.name_rect = pygame.Rect(0, 0, 100, self.FIELD_H)
        self.model_rect = pygame.Rect(0, 0, 100, self.BTN_H)
        self.texture_rect = pygame.Rect(0, 0, 100, self.BTN_H)
        self.template_rect = pygame.Rect(0, 0, 100, self.BTN_H)
        self.ok = pygame.Rect(0, 0, 86, self.BTN_H)
        self.cancel = pygame.Rect(0, 0, 86, self.BTN_H)
        self.close_rect = pygame.Rect(0, 0, 0, 0)

    def _build_rows(self):
        """[(kind, label)] with a group heading (kind None) before each."""
        rows = []
        if self.only in (None, "scene"):
            rows.append((None, "Scene"))
            for key, preset in SCENE_PRESETS.items():
                rows.append((key, preset[3].replace("New ", "")))
        if self.only in (None, "object"):
            rows.append((None, "Object"))
            for key, preset in OBJECT_PRESETS.items():
                rows.append((key, preset[3].replace("New ", "")))
        if self.only in (None, "shader"):
            rows.append((None, "Shader"))
            rows.append(("new_shader", "Look"))
        if self.only in (None, "asset"):
            rows.append((None, "Asset"))
            for key, label, _stem in ASSET_KINDS:
                rows.append((key, label))
        return rows

    def _index_of(self, kind):
        for key, _label in self.rows:
            if key == kind:
                return key
        return None

    def _first_kind(self):
        """The first real row; headings are not kinds."""
        for key, _label in self.rows:
            if key is not None:
                return key
        return None

    def _default_stem(self, kind):
        preset = OBJECT_PRESETS.get(kind) or SCENE_PRESETS.get(kind)
        if preset is not None:
            return preset[2]
        if kind == "new_shader":
            return str(self.template or "shader")
        for key, _label, stem in ASSET_KINDS:
            if key == kind:
                return stem
        return "untitled"

    def _stems(self, folder):
        if self.project is None:
            return []
        return sorted(p.stem for p in self.project.files(folder))

    def uses_picture(self):
        """A pictured thing can carry a model and texture."""
        return self.selected in OBJECT_PRESETS

    def uses_template(self):
        """A shader is written from one of the stock looks."""
        return self.selected == "new_shader"

    def template_title(self):
        """The chosen look's own words, for its chooser button."""
        row = SHADER_PRESETS.get(str(self.template))
        return row[2] if row else ""

    def select(self, kind):
        """Pick a kind; re-seed the name if unchanged."""
        if kind is None or self._index_of(kind) is None:
            return
        if self.field.text == self._default_stem(self.selected):
            self.field.set(self._default_stem(kind))
        self.selected = kind

    def _cycle(self, which):
        """Advance a chooser through the project's files, or a shader"""
        if which == "templates":
            options, name = list(self.templates), "template"
        else:
            options, name = [None] + getattr(self, which), which[:-1]
        current = getattr(self, name)
        try:
            i = options.index(current)
        except ValueError:
            i = 0
        nxt = options[(i + 1) % len(options)] if options else None
        if which == "templates" and self.field.text == str(current or ""):
            self.field.set(nxt or "")
        setattr(self, name, nxt)

    def _layout(self, size):
        kind_rows = len(self.rows)
        right = 2 + (2 if self.uses_picture() else 0) \
            + (1 if self.uses_template() else 0)
        body_h = max(kind_rows * self.ROW_H + 8, self.FIELD_H * right + 40)
        height = self.CAP_H + 12 + body_h + 12 + self.BTN_H + 14
        self.rect = pygame.Rect(0, 0, self.width, height)
        self.rect.center = (size[0] // 2, size[1] // 2)
        body = pygame.Rect(self.rect.x + 1, self.rect.y + self.CAP_H,
                           self.rect.width - 2, self.rect.height -
                           self.CAP_H - 1)
        col_w = (body.width - 32) // 2
        left = pygame.Rect(body.x + 12, body.y + 8, col_w, body.height)
        rx = left.right + 12
        self.row_rects = []
        y = left.y
        for _kind, _label in self.rows:
            self.row_rects.append(pygame.Rect(left.x, y, left.width,
                                              self.ROW_H))
            y += self.ROW_H
        self.name_rect = pygame.Rect(rx, body.y + 8, body.right - 12 - rx,
                                     self.FIELD_H)
        ry = self.name_rect.bottom + 10
        if self.uses_picture():
            self.model_rect = pygame.Rect(rx, ry, body.right - 12 - rx,
                                          self.BTN_H)
            self.texture_rect = pygame.Rect(rx, self.model_rect.bottom + 6,
                                            body.right - 12 - rx,
                                            self.BTN_H)
        if self.uses_template():
            self.template_rect = pygame.Rect(rx, ry, body.right - 12 - rx,
                                             self.BTN_H)
        bottom = self.rect.bottom - 14
        self.ok.bottomright = (body.right - 12, bottom)
        self.cancel.bottomright = (self.ok.x - 8, bottom)
        return body

    def draw(self, surf, fonts):
        body = self._layout(surf.get_size())
        dim = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 110))
        surf.blit(dim, (0, 0))
        _body, close = xp.message_frame(surf, self.rect, "New",
                                          fonts["normal"])
        self.close_rect = close
        mouse = pygame.mouse.get_pos()
        for (kind, label), rect in zip(self.rows, self.row_rects):
            if kind is None:
                img = cached_text(fonts["small"], label, xp.TEXT_MUTED)
                if img is not None:
                    surf.blit(img, (rect.x + 2, rect.centery -
                                    img.get_height() // 2))
                continue
            if kind == self.selected:
                surf.fill(xp.SELECTION, rect)
            elif rect.collidepoint(mouse):
                surf.fill(xp.BTN_HOVER_BG, rect)
            color = xp.SELECT_TEXT if kind == self.selected else xp.TEXT
            img = cached_text(fonts["normal"], elide(fonts["normal"], label,
                                                     rect.width - 6), color)
            if img is not None:
                surf.blit(img, (rect.x + 6, rect.centery -
                                img.get_height() // 2))
        surf.blit(cached_text(fonts["small"], "Name (file stem)",
                              xp.TEXT_MUTED),
                  (self.name_rect.x, self.name_rect.y - 12))
        self.field.draw(surf, self.name_rect, fonts["normal"], True)
        if self.uses_picture():
            self._draw_chooser(surf, fonts, self.model_rect, "Model",
                               self.model)
            self._draw_chooser(surf, fonts, self.texture_rect, "Texture",
                               self.texture)
        if self.uses_template():
            self._draw_chooser(surf, fonts, self.template_rect, "Stock look",
                               self.template_title())
        xp.button(surf, self.ok, "Create", fonts["normal"], default=True,
                  hovered=self.ok.collidepoint(mouse))
        xp.button(surf, self.cancel, "Cancel", fonts["normal"],
                  hovered=self.cancel.collidepoint(mouse))
        return body

    def _draw_chooser(self, surf, fonts, rect, label, value):
        surf.blit(cached_text(fonts["small"], label, xp.TEXT_MUTED),
                  (rect.x, rect.y - 12))
        text = value if value else f"(no {label.lower()})"
        xp.button(surf, rect, elide(fonts["normal"], text, rect.width - 22),
                  fonts["normal"],
                  hovered=rect.collidepoint(pygame.mouse.get_pos()))

    def handle(self, e):
        """Return "ok" once Create is pressed; `answer` holds the payload."""
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                return "cancel"
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._commit()
            self.field.handle(e)
            return None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for (kind, _label), rect in zip(self.rows, self.row_rects):
                if kind is not None and rect.collidepoint(e.pos):
                    self.select(kind)
                    return None
            if self.model_rect.collidepoint(e.pos) and self.uses_picture():
                self._cycle("models")
                return None
            if self.texture_rect.collidepoint(e.pos) and self.uses_picture():
                self._cycle("textures")
                return None
            if self.template_rect.collidepoint(e.pos) and \
                    self.uses_template():
                self._cycle("templates")
                return None
            if self.ok.collidepoint(e.pos):
                return self._commit()
            if self.cancel.collidepoint(e.pos) or \
                    self.close_rect.collidepoint(e.pos):
                return "cancel"
            if not self.rect.collidepoint(e.pos):
                return "cancel"
        return None

    def _commit(self):
        if not (self.field.text or "").strip():
            return None
        self.answer = {"kind": self.selected,
                       "name": self.field.text.strip(),
                       "model": self.model if self.uses_picture() else None,
                       "texture": (self.texture if self.uses_picture()
                                   else None),
                       "template": (self.template if self.uses_template()
                                    else None)}
        return "ok"


class NodeDialog:
    """The Create New Node dialog: search over grouped rows."""

    CAP_H = 28
    ROW_H = 20
    FIELD_H = 24
    BTN_H = 26
    VIEW_ROWS = 12        # entries shown before the list scrolls

    def __init__(self, rows, title="Create New Node", width=440):
        self.rows = list(rows)
        self.title = title
        self.width = width
        self.field = TextField("", 64)      # the search line
        self.answer = None
        self.sel = 0 if self.rows else None
        self.scroll = 0
        self.rect = pygame.Rect(0, 0, width, 380)
        self.field_rect = pygame.Rect(0, 0, width - 24, self.FIELD_H)
        self.list_rect = pygame.Rect(0, 0, width - 24, 100)
        self.row_rects = []                 # (row index, rect) drawn live
        self.ok = pygame.Rect(0, 0, 86, self.BTN_H)
        self.cancel = pygame.Rect(0, 0, 86, self.BTN_H)
        self.close_rect = pygame.Rect(0, 0, 0, 0)

    def _visible(self):
        """The entries shown right now: headings before each group run."""
        want = self.field.text.strip().lower()
        out = []
        last = None
        for i, (payload, label, group) in enumerate(self.rows):
            if want and want not in f"{label} {group} {payload[1]}".lower():
                continue
            if group != last:
                out.append(("head", group))
                last = group
            out.append(("row", i, label))
        return out

    def _shown_ids(self):
        return [ent[1] for ent in self._visible() if ent[0] == "row"]

    def _resel(self):
        """After filtering, keep a surviving row picked."""
        ids = self._shown_ids()
        if self.sel not in ids:
            self.sel = ids[0] if ids else None

    def _step(self, d):
        ids = self._shown_ids()
        if not ids:
            return
        if self.sel not in ids:
            self.sel = ids[0]
        else:
            self.sel = ids[max(0, min(len(ids) - 1,
                                      ids.index(self.sel) + d))]
        self._ensure_visible()

    def _ensure_visible(self):
        pos = None
        for p, ent in enumerate(self._visible()):
            if ent[0] == "row" and ent[1] == self.sel:
                pos = p
                break
        if pos is None:
            return
        if pos < self.scroll:
            self.scroll = pos
        elif pos >= self.scroll + self.VIEW_ROWS:
            self.scroll = pos - self.VIEW_ROWS + 1

    @staticmethod
    def _icon(payload):
        """Types take registry art; prefabs take their document's."""
        if payload[0] == "type":
            return node_icon(payload[1])
        tail = "." + str(payload[1]).rsplit(".", 1)[-1].lower()
        return FILE_ICONS.get(tail)

    def _layout(self, size):
        shown = self._visible()
        max_scroll = max(0, len(shown) - self.VIEW_ROWS)
        self.scroll = max(0, min(self.scroll, max_scroll))
        count = min(len(shown), self.VIEW_ROWS) or 1
        height = (self.CAP_H + 10 + self.FIELD_H + 8 +
                  count * self.ROW_H + 10 + self.BTN_H + 14)
        self.rect = pygame.Rect(0, 0, self.width, height)
        self.rect.center = (size[0] // 2, size[1] // 2)
        body = pygame.Rect(self.rect.x + 1, self.rect.y + self.CAP_H,
                           self.rect.width - 2,
                           self.rect.height - self.CAP_H - 1)
        self.field_rect = pygame.Rect(body.x + 12, body.y + 8,
                                      body.width - 24, self.FIELD_H)
        self.list_rect = pygame.Rect(body.x + 12, self.field_rect.bottom + 8,
                                     body.width - 24,
                                     count * self.ROW_H + 4)
        bottom = self.rect.bottom - 14
        self.ok.bottomright = (body.right - 12, bottom)
        self.cancel.bottomright = (self.ok.x - 8, bottom)
        return body

    def draw(self, surf, fonts):
        body = self._layout(surf.get_size())
        dim = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 110))
        surf.blit(dim, (0, 0))
        _body, close = xp.message_frame(surf, self.rect, self.title,
                                        fonts["normal"])
        self.close_rect = close
        self.field.draw(surf, self.field_rect, fonts["normal"], True)
        small = fonts["small"]
        pygame.draw.rect(surf, xp.FIELD_ALT, self.list_rect)
        xp.sunken(surf, self.list_rect)
        old = surf.get_clip()
        surf.set_clip(self.list_rect.inflate(-2, -2))
        y = self.list_rect.y + 2 - self.scroll * self.ROW_H
        self.row_rects = []
        for ent in self._visible():
            rect = pygame.Rect(self.list_rect.x + 2, y,
                               self.list_rect.width - 4, self.ROW_H)
            if ent[0] == "head":
                img = cached_text(small, ent[1], xp.TEXT_MUTED)
                if img is not None:
                    surf.blit(img, (rect.x + 2, rect.centery -
                                    img.get_height() // 2))
            else:
                self._draw_row(surf, fonts, rect, ent)
                if self.list_rect.colliderect(rect):
                    self.row_rects.append((ent[1], rect))
            y += self.ROW_H
        surf.set_clip(old)
        shown = self._visible()
        if len(shown) > self.VIEW_ROWS:
            max_scroll = len(shown) - self.VIEW_ROWS
            xp.scrollbar(surf, pygame.Rect(self.list_rect.right - 12,
                                           self.list_rect.y + 2, 10,
                                           self.list_rect.height - 4),
                         self.scroll / max(1, max_scroll),
                         self.VIEW_ROWS / max(1.0, len(shown)))
        mouse = pygame.mouse.get_pos()
        xp.button(surf, self.ok, "Add", fonts["normal"], default=True,
                  hovered=self.ok.collidepoint(mouse))
        xp.button(surf, self.cancel, "Cancel", fonts["normal"],
                  hovered=self.cancel.collidepoint(mouse))
        img = cached_text(small, "type to filter - double-click or Enter "
                                 "adds", xp.TEXT_MUTED)
        surf.blit(img, (body.x + 14, self.ok.y + self.BTN_H // 2 -
                        img.get_height() // 2))
        return body

    def _draw_row(self, surf, fonts, rect, ent):
        _kind, i, label = ent
        if i == self.sel:
            surf.fill(xp.SELECTION, rect)
        elif rect.collidepoint(pygame.mouse.get_pos()):
            surf.fill(xp.BTN_HOVER_BG, rect)
        tx = rect.x + 4
        art = self._icon(self.rows[i][0])
        if art and draw_icon(surf, art, pygame.Rect(tx, rect.y + 2, 16, 16)):
            tx += 20
        color = xp.SELECT_TEXT if i == self.sel else xp.TEXT
        img = cached_text(fonts["small"],
                          elide(fonts["small"], label, rect.right - tx - 6),
                          color)
        if img is not None:
            surf.blit(img, (tx, rect.centery - img.get_height() // 2))

    def handle(self, e):
        """Return `ok` when a row commits; `answer` holds it."""
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                return "cancel"
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._commit()
            if e.key == pygame.K_UP:
                self._step(-1)
                return None
            if e.key == pygame.K_DOWN:
                self._step(1)
                return None
            before = self.field.text
            self.field.handle(e)
            if self.field.text != before:
                self._resel()
            return None
        if e.type == pygame.MOUSEWHEEL:
            self.scroll += -e.y
            return None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for i, rect in self.row_rects:
                if rect.collidepoint(e.pos):
                    if i == self.sel:
                        return self._commit()    # the second click adds
                    self.sel = i
                    return None
            if self.ok.collidepoint(e.pos):
                return self._commit()
            if self.cancel.collidepoint(e.pos) or \
                    self.close_rect.collidepoint(e.pos):
                return "cancel"
            if not self.rect.collidepoint(e.pos):
                return "cancel"
        return None

    def _commit(self):
        """Add the picked row, else the first visible one."""
        ids = self._shown_ids()
        if self.sel not in ids and ids:
            self.sel = ids[0]
        if self.sel not in ids:
            return None
        payload = self.rows[self.sel][0]
        self.answer = {"type": payload[1] if payload[0] == "type" else None,
                       "inst": payload[1] if payload[0] == "inst" else None}
        return "ok"


class ColorDialog:
    """Colour picker: a hex field over named tints."""

    CAP_H = 28
    FIELD_H = 24
    CELL = 20
    GAP = 4
    PER_ROW = 8
    BTN_H = 26

    def __init__(self, title="Colour", value="", hint=None, width=396,
                 allow_none=False):
        self.title = title
        self.hint = hint
        self.allow_none = bool(allow_none)
        self.names = sorted(colors.NAMED)
        self.field = TextField(self._spell(value), 24)
        self.answer = None
        self.bad = False
        self.hover = None
        self.width = width
        self.rect = pygame.Rect(0, 0, width, 160)
        self.body = pygame.Rect(0, 0, width, 150)
        self.field_rect = pygame.Rect(0, 0, 100, self.FIELD_H)
        self.chip = pygame.Rect(0, 0, 60, self.FIELD_H)
        self.close_rect = pygame.Rect(0, 0, 0, 0)
        self.swatch_rects = []
        self.ok = pygame.Rect(0, 0, 86, self.BTN_H)
        self.cancel = pygame.Rect(0, 0, 86, self.BTN_H)
        self.none_btn = pygame.Rect(0, 0, 86, self.BTN_H)

    @staticmethod
    def _spell(value):
        """The opening text: a colour key, else empty."""
        return colors.key(value) if colors.is_spelling(value) else ""

    def _layout(self, size, fonts):
        rows = max(1, -(-len(self.names) // self.PER_ROW))      # ceil
        cell = self.CELL + self.GAP
        line_h = fonts["small"].get_height() + 2
        height = (self.CAP_H + 10 + self.FIELD_H + 6 + line_h + 6 +
                  cell * rows + 10 + self.BTN_H + 14)
        self.rect = pygame.Rect(0, 0, self.width, height)
        self.rect.center = (size[0] // 2, size[1] // 2)
        body = pygame.Rect(self.rect.x + 1, self.rect.y + self.CAP_H,
                           self.rect.width - 2,
                           self.rect.height - self.CAP_H - 1)
        x = body.x + 14
        self.field_rect = pygame.Rect(x, body.y + 10,
                                      body.width - 32 - 62, self.FIELD_H)
        self.chip = pygame.Rect(self.field_rect.right + 12,
                                self.field_rect.y, 50, self.FIELD_H)
        self.note_y = self.field_rect.bottom + 6
        grid_y = self.note_y + line_h + 6
        self.swatch_rects = []
        for i in range(len(self.names)):
            r, c = divmod(i, self.PER_ROW)
            self.swatch_rects.append(pygame.Rect(x + c * cell, grid_y +
                                                 r * cell, self.CELL,
                                                 self.CELL))
        bottom = self.rect.bottom - 14
        self.ok.bottomright = (body.right - 14, bottom)
        self.cancel.bottomright = (self.ok.x - 8, bottom)
        self.none_btn.bottomright = (self.cancel.x - 8, bottom)
        return body

    def draw(self, surf, fonts):
        body = self._layout(surf.get_size(), fonts)
        dim = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 110))
        surf.blit(dim, (0, 0))
        _body, close = xp.message_frame(surf, self.rect, self.title,
                                        fonts["normal"])
        self.close_rect = close
        self.field.draw(surf, self.field_rect, fonts["normal"], True)
        got = colors.rgba(self.field.text or "")
        fill = colors.bytes_rgb(got) if got else (128, 128, 128)
        pygame.draw.rect(surf, fill, self.chip)
        pygame.draw.rect(surf, xp.OUTLINE, self.chip, 1)
        note = self.hint or ""
        color = xp.TEXT_MUTED
        if self.hover is not None and self.hover < len(self.names):
            name = self.names[self.hover]
            note = f"{name}  {colors.key(colors.NAMED[name])}"
            color = xp.TEXT
        if self.bad:
            note = "not a colour - try #3c7ad6, rgb(60, 122, 214) or torch"
            color = xp.LOG_ERROR
        img = cached_text(fonts["small"], note, color) if note else None
        if img:
            surf.blit(img, (body.x + 14, self.note_y))
        mouse = pygame.mouse.get_pos()
        for i, rect in enumerate(self.swatch_rects):
            pygame.draw.rect(surf, colors.NAMED[self.names[i]], rect)
            edge = xp.HILITE if rect.collidepoint(mouse) or i == self.hover \
                else xp.SHADOW
            pygame.draw.rect(surf, edge, rect, 1)
        xp.button(surf, self.ok, "OK", fonts["normal"], default=True,
                  hovered=self.ok.collidepoint(mouse))
        xp.button(surf, self.cancel, "Cancel", fonts["normal"],
                  hovered=self.cancel.collidepoint(mouse))
        if self.allow_none:
            xp.button(surf, self.none_btn, "None", fonts["normal"],
                      hovered=self.none_btn.collidepoint(mouse))
        return body

    def handle(self, e):
        """Return `ok` with `answer`, `cancel`, or None."""
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                return "cancel"
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._commit()
            self.field.handle(e)
            self.bad = False
            return None
        if e.type == pygame.MOUSEMOTION:
            self.hover = next((i for i, r in enumerate(self.swatch_rects)
                               if r.collidepoint(e.pos)), None)
            return None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for i, rect in enumerate(self.swatch_rects):
                if rect.collidepoint(e.pos):
                    self.field.set(colors.key(colors.NAMED[self.names[i]]))
                    self.bad = False
                    return None
            if self.ok.collidepoint(e.pos):
                return self._commit()
            if self.allow_none and self.none_btn.collidepoint(e.pos):
                self.answer = ""
                return "ok"
            if self.cancel.collidepoint(e.pos) or \
                    self.close_rect.collidepoint(e.pos):
                return "cancel"
            if not self.rect.collidepoint(e.pos):
                return "cancel"
        return None

    def _commit(self):
        """OK or Enter: the typed colour becomes the answer."""
        raw = (self.field.text or "").strip()
        if not raw:
            if not self.allow_none:
                self.bad = True
                return None
            self.answer = ""
            return "ok"
        got = colors.rgba(raw)
        if got is None:
            self.bad = True
            return None
        self.answer = colors.key(got)
        return "ok"


class ChoiceDialog:
    """Modal question with 2-4 buttons; the clicked label becomes `answer`."""

    CAP_H = 28
    BTN_H = 26

    def __init__(self, title, message, options, hint=None, width=420,
                 default=0):
        self.title = title
        self.message = str(message)
        self.options = [str(o) for o in options] or ("OK",)
        self.hint = hint
        self.width = width
        self.default = max(0, min(default, len(self.options) - 1))
        self.answer = None
        self.hover = None
        self.rect = pygame.Rect(0, 0, width, 130)
        self.body = pygame.Rect(0, 0, width, 100)
        self.close_rect = pygame.Rect(0, 0, 0, 0)
        self.button_rects = []

    def _layout(self, size, fonts):
        inner_w = self.width - 32
        lines = wrap(fonts["normal"], self.message, inner_w)
        hint_lines = wrap(fonts["small"], self.hint, inner_w) if self.hint \
            else []
        line_h = fonts["normal"].get_height() + 2
        small_h = fonts["small"].get_height() + 2
        btn_w = max(104, max(fonts["normal"].size(o)[0] + 26
                             for o in self.options))
        stacked = (btn_w + 8) * len(self.options) + 24 > self.width
        btn_h = (self.BTN_H * len(self.options)
                 + 6 * (len(self.options) - 1)) if stacked else self.BTN_H
        height = self.CAP_H + 12 + line_h * len(lines) + 8 + btn_h + 14
        if hint_lines:
            height += small_h * len(hint_lines) + 4
        self.rect = pygame.Rect(0, 0, self.width, height)
        self.rect.center = (size[0] // 2, size[1] // 2)
        self.body = pygame.Rect(self.rect.x + 1, self.rect.y + self.CAP_H,
                                self.rect.width - 2,
                                self.rect.height - self.CAP_H - 1)
        bottom = self.rect.bottom - 14
        if stacked:
            self.button_rects = [pygame.Rect(
                self.rect.centerx - btn_w // 2,
                bottom - (i + 1) * self.BTN_H - 6 * i, btn_w, self.BTN_H)
                for i in range(len(self.options))]
        else:
            row = btn_w * len(self.options) + 8 * (len(self.options) - 1)
            x = self.rect.right - 14 - row
            self.button_rects = [pygame.Rect(x + i * (btn_w + 8),
                                             bottom - self.BTN_H,
                                             btn_w, self.BTN_H)
                                 for i in range(len(self.options))]
        return lines, hint_lines

    def draw(self, surf, fonts):
        lines, hint_lines = self._layout(surf.get_size(), fonts)
        ui_dim = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        ui_dim.fill((0, 0, 0, 110))
        surf.blit(ui_dim, (0, 0))
        body, close = xp.message_frame(surf, self.rect, self.title,
                                       fonts["normal"])
        self.close_rect = close
        self.body = body
        y = body.y + 12
        for line in lines:
            surf.blit(cached_text(fonts["normal"], line, xp.TEXT),
                      (body.x + 16, y))
            y += fonts["normal"].get_height() + 2
        y += 8
        for line in hint_lines:
            surf.blit(cached_text(fonts["small"], line, xp.TEXT_MUTED),
                      (body.x + 16, y))
            y += fonts["small"].get_height() + 2
        mouse = pygame.mouse.get_pos()
        for i, rect in enumerate(self.button_rects):
            xp.button(surf, rect, self.options[i], fonts["normal"],
                      default=i == self.default,
                      hovered=rect.collidepoint(mouse) or i == self.hover)
        return body

    def handle(self, e):
        """Return `ok` once an option is chosen; `answer` holds it."""
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._pick(self.default)
            if e.key == pygame.K_ESCAPE:
                return self._pick(len(self.options) - 1)
            step = {pygame.K_DOWN: 1, pygame.K_RIGHT: 1, pygame.K_UP: -1,
                    pygame.K_LEFT: -1}.get(e.key)
            if step is not None:
                self.default = (self.default + step) % len(self.options)
                self.hover = self.default
            return None
        if e.type == pygame.MOUSEMOTION:
            self.hover = next((i for i, r in enumerate(self.button_rects)
                               if r.collidepoint(e.pos)), None)
            return None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if not self.button_rects:
                return None        # never drawn yet: nothing to hit
            for i, rect in enumerate(self.button_rects):
                if rect.collidepoint(e.pos):
                    return self._pick(i)
            if self.close_rect.collidepoint(e.pos):
                return self._pick(len(self.options) - 1)
            if not self.rect.collidepoint(e.pos):
                return self._pick(len(self.options) - 1)
        return None

    def _pick(self, index):
        self.answer = self.options[index]
        return "ok"


def copy_to_clipboard(text):
    """Put `text` on the system clipboard; report whether it landed."""
    text = str(text)
    try:
        pygame.scrap.init()
        pygame.scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
        return True
    except Exception:
        pass
    if os.name == "nt":
        try:
            import subprocess
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", "Set-Clipboard -Value @input"],
                           input=text, capture_output=True, text=True,
                           timeout=4)
            return True
        except Exception:
            return False
    return False


class OutputLog:
    """Scrolling text panel with severity colours."""

    COLORS = {
        "info": "LOG_INFO",
        "ok": "LOG_OK",
        "warn": "LOG_WARN",
        "error": "LOG_ERROR",
        "muted": "LOG_MUTED",
    }

    # a 16x16 symbol before lines that need one
    SEVERITY_ICONS = {"warn": "warning-sym", "error": "error-sym",
                      "fatal": "fatal-sym"}

    def __init__(self, max_lines=400):
        self.lines = []
        self.max_lines = max_lines
        self.scroll = 0

    def add(self, text, kind="info"):
        stamp = time.strftime("%H:%M:%S")
        for chunk in str(text).splitlines() or [""]:
            self.lines.append((f"[{stamp}] {chunk}", chunk, kind))
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]
        self.scroll = 0

    def clear(self):
        self.lines = []
        self.scroll = 0

    @property
    def count(self):
        """How many lines the panel holds."""
        return len(self.lines)

    def text(self):
        """The log as plain lines, without their time stamps."""
        return "\n".join(raw for _shown, raw, _kind in self.lines)

    def scroll_by(self, dy, rows):
        self.scroll = max(0, min(max(0, len(self.lines) - rows),
                                 self.scroll - dy))

    def draw(self, surf, area, fonts):
        pygame.draw.rect(surf, xp.LOG_BG, area)
        xp.sunken(surf, area)
        inner = area.inflate(-6, -4)
        line_h = max(fonts["small"].get_height() + 1, 17)
        rows = max(1, inner.height // line_h)
        total = len(self.lines)
        self.scroll = max(0, min(max(0, total - rows), self.scroll))
        start = max(0, total - rows - self.scroll)
        y = inner.y
        for shown, _raw, kind in self.lines[start:start + rows]:
            x = inner.x
            mark = self.SEVERITY_ICONS.get(kind)
            if mark and draw_icon(surf, mark, pygame.Rect(x, y, 16, 16)):
                x += 18
            img = cached_text(fonts["small"], shown,
                              getattr(xp, self.COLORS.get(kind, "LOG_INFO")))
            surf.blit(img, (x, y))
            y += line_h
        if total > rows:
            xp.scrollbar(surf, pygame.Rect(area.right - 13, area.y + 2,
                                           11, area.height - 4),
                         start / max(1, total), rows / max(1, total))
        return rows
