"""Editor widgets drawn with the XP primitives: tree view, text field,
prompt dialog, output log, icons and a small render cache.

The cache matters: the code editor re-renders every visible token each
frame, and pygame font rendering is far too slow for that uncached.
"""

import time

import pygame

from ..engine import xp

_TEXT_CACHE = {}
_CACHE_LIMIT = 8000


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


def header(surf, rect, title, font, right=None):
    """Dock header strip: caption on a beige bar with a hairline."""
    surf.fill(xp.FACE, rect)
    pygame.draw.line(surf, xp.HILITE, (rect.x, rect.y),
                     (rect.right - 1, rect.y))
    pygame.draw.line(surf, xp.SHADOW, (rect.x, rect.bottom - 1),
                     (rect.right - 1, rect.bottom - 1))
    label = cached_text(font, title, xp.TEXT_MUTED)
    surf.blit(label, (rect.x + 8, rect.centery - label.get_height() // 2))
    if right:
        img = cached_text(font, right, xp.TEXT_MUTED)
        surf.blit(img, (rect.right - 8 - img.get_width(),
                        rect.centery - img.get_height() // 2))
    return rect


_ICON_COLORS = {
    ".py": ((66, 110, 180), "Py"),
    ".model": ((190, 120, 40), "3D"),
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


def file_icon(surf, pos, suffix, font, size=14):
    color, label = _ICON_COLORS.get(suffix.lower(),
                                    ((120, 120, 110), "??"))
    rect = pygame.Rect(pos[0], pos[1], size, size)
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
    """Flat list of project rows with folder toggles and a scrollbar."""

    ROW_H = 19

    def __init__(self):
        self.rows = []
        self.rects = []
        self.scroll = 0
        self.selected = None
        self.hover = -1

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
        self._clamp(area)
        inner = area.inflate(-2, -2)
        y = inner.y + 2 - self.scroll * self.ROW_H
        self.rects = []
        rows = len(self.rows)
        count = self.visible(inner) + 1
        for i in range(self.scroll, min(rows, self.scroll + count)):
            row = self.rows[i]
            rect = pygame.Rect(inner.x, y, inner.width - 12, self.ROW_H)
            self.rects.append(rect)
            if rect.collidepoint(mouse):
                self.hover = i
            if i == self.selected or rect.collidepoint(mouse):
                bg = xp.SELECTION if i == self.selected else xp.BTN_HOVER_BG
                surf.fill(bg, rect)
            indent = 8 + row.get("depth", 0) * 12
            tx = rect.x + indent
            if row.get("kind") == "folder":
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
            else:
                img = cached_text(small, "proj", (70, 90, 140))
                surf.blit(img, (tx, rect.y + 3))
                tx += 26
            color = (255, 255, 255) if i == self.selected else xp.TEXT
            label = cached_text(font, row["label"], color)
            surf.blit(label, (tx, rect.y + 2))
            y += self.ROW_H
        max_scroll = max(0, rows - self.visible(inner))
        if max_scroll > 0:
            frac = self.scroll / max(1, rows)
            page = self.visible(inner) / max(1, rows)
            xp.scrollbar(surf, pygame.Rect(area.right - 13, area.y + 2,
                                           11, area.height - 4), frac, page)

    def click(self, pos):
        for i, rect in enumerate(self.rects):
            if rect.collidepoint(pos):
                self.selected = i + self.scroll
                return self.rows[self.selected]
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


class PromptDialog:
    """One-field XP dialog: New Scene, New Model, Rename..."""

    def __init__(self, title, label, value="", on_ok=None, width=400,
                 hint=None):
        self.title = title
        self.label = label
        self.hint = hint
        self.field = TextField(value)
        self.on_ok = on_ok
        self.width = width
        self.rect = pygame.Rect(0, 0, width, 150 if not hint else 172)
        self.ok = pygame.Rect(0, 0, 86, 26)
        self.cancel = pygame.Rect(0, 0, 86, 26)
        self.focus = True

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
        if self.hint:
            img = cached_text(fonts["small"], self.hint, xp.TEXT_MUTED)
            surf.blit(img, (body.x + 16, field.bottom + 8))
        mouse = pygame.mouse.get_pos()
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
        return None


class OutputLog:
    """Scrolling text panel with severity colours."""

    COLORS = {
        "info": "LOG_INFO",
        "ok": "LOG_OK",
        "warn": "LOG_WARN",
        "error": "LOG_ERROR",
        "muted": "LOG_MUTED",
    }

    def __init__(self, max_lines=400):
        self.lines = []
        self.max_lines = max_lines
        self.scroll = 0

    def add(self, text, kind="info"):
        stamp = time.strftime("%H:%M:%S")
        for chunk in str(text).splitlines() or [""]:
            self.lines.append((f"[{stamp}] {chunk}", kind))
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]
        self.scroll = 0

    def clear(self):
        self.lines = []
        self.scroll = 0

    def scroll_by(self, dy, rows):
        self.scroll = max(0, min(max(0, len(self.lines) - rows),
                                 self.scroll - dy))

    def draw(self, surf, area, fonts):
        pygame.draw.rect(surf, xp.LOG_BG, area)
        xp.sunken(surf, area)
        inner = area.inflate(-6, -4)
        line_h = fonts["small"].get_height() + 1
        rows = max(1, inner.height // line_h)
        total = len(self.lines)
        self.scroll = max(0, min(max(0, total - rows), self.scroll))
        start = max(0, total - rows - self.scroll)
        y = inner.y
        for text, kind in self.lines[start:start + rows]:
            img = cached_text(fonts["small"], text,
                              getattr(xp, self.COLORS.get(kind, "LOG_INFO")))
            surf.blit(img, (inner.x, y))
            y += line_h
        if total > rows:
            xp.scrollbar(surf, pygame.Rect(area.right - 13, area.y + 2,
                                           11, area.height - 4),
                         start / max(1, total), rows / max(1, total))
        return rows
