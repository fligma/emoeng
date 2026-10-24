"""Python editor tab: line numbers, syntax highlighting, selection,
undo/redo, auto-indent and clipboard.

Highlighting is a small scanner rather than a full parser: keywords,
builtins, strings (including triple-quoted), comments, numbers, def/class
names and decorators. Tokens are recomputed when the text changes; the
visible ones draw through a render cache so a full-screen repaint stays
cheap.
"""

import time
from pathlib import Path

import pygame

from ..engine import xp
from . import widgets

KEYWORDS = set("""
False None True and as assert async await break class continue def del elif
else except finally for from global if import in is lambda nonlocal not or
pass raise return try while with yield match case
""".split())

BUILTINS = set("""
abs all any ascii bin bool bytearray bytes callable chr classmethod compile
complex delattr dict dir divmod enumerate eval exec filter float format
frozenset getattr globals hasattr hash help hex id input int isinstance
issubclass iter len list locals map max memoryview min next object oct open
ord pow print property range repr reversed round set setattr slice sorted
staticmethod str sum super tuple type vars zip
""".split())

# Syntax colours live in the theme; map token kinds to xp names.
COLORS = {
    "kw": "SYN_KW",
    "builtin": "SYN_BUILTIN",
    "str": "SYN_STR",
    "comment": "SYN_COMMENT",
    "number": "SYN_NUMBER",
    "def": "SYN_DEF",
    "self": "SYN_SELF",
    "op": "SYN_OP",
    "decorator": "SYN_DECORATOR",
}


def token_color(kind):
    return getattr(xp, COLORS.get(kind, "CODE_TEXT"))


def scan(text):
    """Split source into per-line (start, end, kind) token spans."""
    lines = [[]]
    n = len(text)
    i = 0
    col = 0
    last_word = None
    while i < n:
        ch = text[i]
        if ch == "\n":
            lines.append([])
            i += 1
            col = 0
            last_word = None
            continue
        if ch == "#":
            start = col
            while i < n and text[i] != "\n":
                i += 1
                col += 1
            lines[-1].append((start, col, "comment"))
            continue
        if ch in "\"'":
            quote = ch
            triple = text.startswith(quote * 3, i)
            start = col
            step = 3 if triple else 1
            i += step
            col += step
            while i < n:
                if triple and text.startswith(quote * 3, i):
                    i += 3
                    col += 3
                    break
                if not triple and text[i] == quote:
                    i += 1
                    col += 1
                    break
                if text[i] == "\\" and i + 1 < n and text[i + 1] != "\n":
                    i += 2
                    col += 2
                    continue
                if text[i] == "\n":
                    if not triple:
                        break
                    lines[-1].append((start, col, "string"))
                    lines.append([])
                    i += 1
                    col = 0
                    start = 0
                    continue
                i += 1
                col += 1
            lines[-1].append((start, col, "string"))
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and
                            text[i + 1].isdigit()):
            start = col
            while i < n and (text[i].isalnum() or text[i] in "._"):
                i += 1
                col += 1
            lines[-1].append((start, col, "number"))
            continue
        if ch.isalpha() or ch == "_":
            word_start = i
            start = col
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
                col += 1
            word = text[word_start:i]
            if word in KEYWORDS:
                kind = "kw"
            elif word in BUILTINS:
                kind = "builtin"
            elif word == "self":
                kind = "self"
            elif last_word in ("def", "class"):
                kind = "def"
            else:
                kind = "default"
            lines[-1].append((start, col, kind))
            last_word = word
            continue
        if ch == "@" and col == 0:
            start = col
            while i < n and text[i] != "\n":
                i += 1
                col += 1
            lines[-1].append((start, col, "decorator"))
            continue
        if ch in "=+-*/%<>!&|^~:":
            start = col
            while i < n and text[i] in "=+-*/%<>!&|^~:":
                i += 1
                col += 1
            lines[-1].append((start, col, "op"))
            continue
        i += 1
        col += 1
    return lines


class CodeEditor:
    GUTTER = 48

    def __init__(self, app):
        self.app = app
        self.font = app.fonts["mono"]
        self.small = app.fonts["small"]
        self.line_h = self.font.get_height() + 3
        self.char_w = max(5, self.font.size("M")[0])
        self.path = None
        self.lines = [""]
        self.tokens = [[]]
        self.cx = self.cy = 0
        self.anchor = None
        self.scroll = 0
        self.dirty = False
        self.blink = 0.0
        self.undo = []
        self.redo = []
        self.clipboard = ""
        self.area = pygame.Rect(0, 0, 0, 0)
        self.scrollbar = pygame.Rect(0, 0, 0, 0)
        self.selecting = False
        self.thumb_drag = False
        self._last_click = 0.0

    # -------------------------------------------------------------- files
    @property
    def text(self):
        return "\n".join(self.lines)

    def open(self, path):
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.app.log(f"cannot open {p}: {exc}", "error")
            return False
        self.path = str(p)
        self.lines = [line.expandtabs(4) for line in
                      text.replace("\r\n", "\n").split("\n")]
        if not self.lines:
            self.lines = [""]
        self.cx = self.cy = 0
        self.anchor = None
        self.scroll = 0
        self.dirty = False
        self.undo.clear()
        self.redo.clear()
        self._rehighlight()
        self.app.log(f"editing {self.app.project.relative(path)}", "muted")
        return True

    def save(self):
        if not self.path:
            return False
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(self.text)
        except OSError as exc:
            self.app.log(f"save failed: {exc}", "error")
            return False
        self.dirty = False
        self.app.log(f"saved {self.app.project.relative(self.path)}", "ok")
        return True

    def _rehighlight(self):
        self.tokens = scan(self.text)

    def _changed(self):
        self.dirty = True
        self._rehighlight()

    # ---------------------------------------------------------- selection
    def sel(self):
        if self.anchor is None:
            return None
        a = (self.anchor[0], self.anchor[1])
        b = (self.cy, self.cx)
        return (a, b) if a <= b else (b, a)

    def has_selection(self):
        s = self.sel()
        return s is not None and s[0] != s[1]

    def selected_text(self):
        s = self.sel()
        if s is None:
            return ""
        (l0, c0), (l1, c1) = s
        if l0 == l1:
            return self.lines[l0][c0:c1]
        parts = [self.lines[l0][c0:]]
        parts += self.lines[l0 + 1:l1]
        parts.append(self.lines[l1][:c1])
        return "\n".join(parts)

    def delete_selection(self):
        s = self.sel()
        if s is None or s[0] == s[1]:
            return
        (l0, c0), (l1, c1) = s
        if l0 == l1:
            self.lines[l0] = self.lines[l0][:c0] + self.lines[l0][c1:]
        else:
            merged = self.lines[l0][:c0] + self.lines[l1][c1:]
            self.lines[l0:l1 + 1] = [merged]
        self.cy, self.cx = l0, c0
        self.anchor = None

    def set_caret(self, line, col, extend=False):
        line = max(0, min(len(self.lines) - 1, line))
        col = max(0, min(len(self.lines[line]), col))
        if extend and self.anchor is None:
            self.anchor = (self.cy, self.cx)
        elif not extend:
            self.anchor = None
        self.cy, self.cx = line, col
        self.blink = 0.0

    # ------------------------------------------------------------ history
    def _snapshot(self):
        self.undo.append((self.text, self.cy, self.cx))
        if len(self.undo) > 120:
            self.undo.pop(0)
        self.redo.clear()

    def undo_stack(self):
        if not self.undo:
            return
        self.redo.append((self.text, self.cy, self.cx))
        text, cy, cx = self.undo.pop()
        self.lines = text.split("\n")
        self.cy, self.cx = cy, cx
        self.anchor = None
        self._changed()

    def redo_stack(self):
        if not self.redo:
            return
        self.undo.append((self.text, self.cy, self.cx))
        text, cy, cx = self.redo.pop()
        self.lines = text.split("\n")
        self.cy, self.cx = cy, cx
        self.anchor = None
        self._changed()

    # ------------------------------------------------------------ editing
    def insert(self, s):
        self._snapshot()
        if self.has_selection():
            self.delete_selection()
        if s == "\n":
            self._newline()
        else:
            line = self.lines[self.cy]
            self.lines[self.cy] = line[:self.cx] + s + line[self.cx:]
            self.cx += len(s)
        self._changed()

    def _newline(self):
        line = self.lines[self.cy]
        head, tail = line[:self.cx], line[self.cx:]
        indent = line[:len(line) - len(line.lstrip(" \t"))]
        extra = "    " if head.rstrip().endswith(":") else ""
        self.lines[self.cy] = head
        self.lines.insert(self.cy + 1, indent + extra + tail)
        self.cy += 1
        self.cx = len(indent) + len(extra)

    def backspace(self):
        if self.has_selection():
            self._snapshot()
            self.delete_selection()
            self._changed()
            return
        self._snapshot()
        if self.cx > 0:
            line = self.lines[self.cy]
            self.lines[self.cy] = line[:self.cx - 1] + line[self.cx:]
            self.cx -= 1
        elif self.cy > 0:
            prev = self.lines[self.cy - 1]
            self.cx = len(prev)
            self.lines[self.cy - 1] = prev + self.lines[self.cy]
            del self.lines[self.cy]
            self.cy -= 1
        self._changed()

    def delete_forward(self):
        if self.has_selection():
            self._snapshot()
            self.delete_selection()
            self._changed()
            return
        self._snapshot()
        line = self.lines[self.cy]
        if self.cx < len(line):
            self.lines[self.cy] = line[:self.cx] + line[self.cx + 1:]
        elif self.cy + 1 < len(self.lines):
            self.lines[self.cy] = line + self.lines[self.cy + 1]
            del self.lines[self.cy + 1]
        self._changed()

    def indent(self, outdent=False):
        self._snapshot()
        s = self.sel()
        if s is not None:
            (l0, _c0), (l1, c1) = s
            if c1 == 0 and l1 > l0:
                l1 -= 1
            for ln in range(l0, l1 + 1):
                if outdent:
                    line = self.lines[ln]
                    strip = min(4, len(line) - len(line.lstrip(" ")))
                    self.lines[ln] = line[strip:]
                else:
                    self.lines[ln] = "    " + self.lines[ln]
            self.cy = l1
        else:
            if outdent:
                line = self.lines[self.cy]
                strip = min(4, len(line) - len(line.lstrip(" ")))
                self.lines[self.cy] = line[strip:]
                self.cx = max(0, self.cx - strip)
            else:
                self.lines[self.cy] = \
                    self.lines[self.cy][:self.cx] + "    " + \
                    self.lines[self.cy][self.cx:]
                self.cx += 4
        self._changed()

    # ----------------------------------------------------------- clipboard
    def copy(self):
        if not self.has_selection():
            return
        text = self.selected_text()
        self.clipboard = text
        try:
            pygame.scrap.init()
            pygame.scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
        except Exception:
            pass

    def cut(self):
        if not self.has_selection():
            return
        self.copy()
        self._snapshot()
        self.delete_selection()
        self._changed()

    def paste(self):
        text = self.clipboard
        try:
            pygame.scrap.init()
            raw = pygame.scrap.get(pygame.SCRAP_TEXT)
            if raw:
                text = raw.decode("utf-8", errors="replace").replace("\x00", "")
        except Exception:
            pass
        if not text:
            return
        self._snapshot()
        if self.has_selection():
            self.delete_selection()
        chunks = text.replace("\r\n", "\n").split("\n")
        line = self.lines[self.cy]
        if len(chunks) == 1:
            self.lines[self.cy] = line[:self.cx] + chunks[0] + line[self.cx:]
            self.cx += len(chunks[0])
        else:
            head = line[:self.cx] + chunks[0]
            tail = chunks[-1] + line[self.cx:]
            middle = chunks[1:-1]
            self.lines[self.cy:self.cy + 1] = [head] + middle + [tail]
            self.cy += len(chunks) - 1
            self.cx = len(chunks[-1])
        self._changed()

    # ------------------------------------------------------------ movement
    def move(self, dx, dy, extend=False, word=False):
        if dy:
            self.set_caret(self.cy + dy, self.cx, extend)
            self.cx = min(self.cx, len(self.lines[self.cy]))
        if dx:
            if word:
                if dx > 0:
                    while self.cx < len(self.lines[self.cy]) and \
                            self.lines[self.cy][self.cx].isalnum():
                        self.cx += 1
                    while self.cx < len(self.lines[self.cy]) and \
                            self.lines[self.cy][self.cx] in " \t(.,:":
                        self.cx += 1
                else:
                    while self.cx > 0 and \
                            self.lines[self.cy][self.cx - 1] in " \t(.,:":
                        self.cx -= 1
                    while self.cx > 0 and \
                            self.lines[self.cy][self.cx - 1].isalnum():
                        self.cx -= 1
                self.set_caret(self.cy, self.cx, extend)
                return
            col = self.cx + dx
            if col < 0 and self.cy > 0:
                self.cy -= 1
                col = len(self.lines[self.cy])
            elif col > len(self.lines[self.cy]) and \
                    self.cy + 1 < len(self.lines):
                self.cy += 1
                col = 0
            self.set_caret(self.cy, col, extend)
        if not extend:
            self.anchor = None

    def line_start(self, extend=False):
        line = self.lines[self.cy]
        stripped = len(line) - len(line.lstrip(" "))
        col = 0 if self.cx <= stripped else stripped
        self.set_caret(self.cy, col, extend)

    def line_end(self, extend=False):
        self.set_caret(self.cy, len(self.lines[self.cy]), extend)

    # -------------------------------------------------------------- events
    def handle_event(self, e):
        if self.path is None:
            return False
        ctrl = e.mod & pygame.KMOD_CTRL if hasattr(e, "mod") else False
        if e.type == pygame.KEYDOWN:
            shift = bool(e.mod & pygame.KMOD_SHIFT)
            if e.key == pygame.K_TAB:
                self.indent(outdent=bool(e.mod & pygame.KMOD_SHIFT))
                return True
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.insert("\n")
                return True
            if e.key == pygame.K_BACKSPACE:
                self.backspace()
                return True
            if e.key == pygame.K_DELETE:
                self.delete_forward()
                return True
            if e.key == pygame.K_LEFT:
                self.move(-1, 0, shift, bool(e.mod & pygame.KMOD_CTRL))
                return True
            if e.key == pygame.K_RIGHT:
                self.move(1, 0, shift, bool(e.mod & pygame.KMOD_CTRL))
                return True
            if e.key == pygame.K_UP:
                self.move(0, -1, shift)
                return True
            if e.key == pygame.K_DOWN:
                self.move(0, 1, shift)
                return True
            if e.key == pygame.K_HOME:
                if e.mod & pygame.KMOD_CTRL:
                    self.set_caret(0, 0, shift)
                else:
                    self.line_start(shift)
                return True
            if e.key == pygame.K_END:
                if e.mod & pygame.KMOD_CTRL:
                    self.set_caret(len(self.lines) - 1,
                                   len(self.lines[-1]), shift)
                else:
                    self.line_end(shift)
                return True
            if e.key == pygame.K_PAGEUP:
                self.move(0, -max(1, self.area.height // self.line_h), shift)
                return True
            if e.key == pygame.K_PAGEDOWN:
                self.move(0, max(1, self.area.height // self.line_h), shift)
                return True
            if ctrl and e.key == pygame.K_a:
                self.anchor = (0, 0)
                self.set_caret(len(self.lines) - 1, len(self.lines[-1]))
                self.cx = len(self.lines[self.cy])
                return True
            if ctrl and e.key == pygame.K_c:
                self.copy()
                return True
            if ctrl and e.key == pygame.K_x:
                self.cut()
                return True
            if ctrl and e.key == pygame.K_v:
                self.paste()
                return True
            if ctrl and e.key == pygame.K_z:
                self.undo_stack()
                return True
            if ctrl and e.key == pygame.K_y:
                self.redo_stack()
                return True
            if e.unicode and e.unicode.isprintable():
                self.insert(e.unicode)
                return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.scrollbar.collidepoint(e.pos):
                self.thumb_drag = True
                self._scroll_to(e.pos[1])
                return True
            if self.area.collidepoint(e.pos):
                now = time.time()
                line, col = self._pos_to_caret(e.pos)
                if now - self._last_click < 0.35:
                    self._select_word(line, col)
                else:
                    self.set_caret(line, col)
                    self.selecting = True
                self._last_click = now
                return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.selecting = False
            self.thumb_drag = False
        if e.type == pygame.MOUSEMOTION:
            if self.thumb_drag:
                self._scroll_to(e.pos[1])
            elif self.selecting and pygame.mouse.get_pressed()[0]:
                line, col = self._pos_to_caret(e.pos)
                self.set_caret(line, col, extend=True)
        if e.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - e.y * 3)
        return False

    def _select_word(self, line, col):
        text = self.lines[line]
        a = col
        while a > 0 and (text[a - 1].isalnum() or text[a - 1] == "_"):
            a -= 1
        b = col
        while b < len(text) and (text[b].isalnum() or text[b] == "_"):
            b += 1
        self.anchor = (line, a)
        self.set_caret(line, b)

    def _scroll_to(self, y):
        if self.scrollbar.height <= 0:
            return
        total = max(1, len(self.lines))
        rows = max(1, self.area.height // self.line_h)
        frac = (y - self.scrollbar.y) / max(1, self.scrollbar.height)
        self.scroll = int(max(0.0, min(1.0, frac)) * max(0, total - rows))

    def _pos_to_caret(self, pos):
        line = self.scroll + (pos[1] - self.area.y) // self.line_h
        line = max(0, min(len(self.lines) - 1, line))
        col = round((pos[0] - self.area.x) / self.char_w)
        col = max(0, min(len(self.lines[line]), col))
        return line, col

    # ---------------------------------------------------------------- draw
    def update(self, dt):
        self.blink += dt

    def draw(self, surface, rect):
        rect = pygame.Rect(rect)
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        inner = rect.inflate(-2, -2)
        gutter = pygame.Rect(inner.x, inner.y, self.GUTTER, inner.height)
        pygame.draw.rect(surface, xp.GUTTER_BG, gutter)
        pygame.draw.line(surface, xp.GUTTER_LINE,
                         (gutter.right - 1, inner.y),
                         (gutter.right - 1, inner.bottom))
        sb = 12 if len(self.lines) * self.line_h > inner.height - 4 else 0
        self.area = pygame.Rect(gutter.right + 4, inner.y + 2,
                                inner.width - gutter.width - 8 - sb,
                                inner.height - 6)
        self.scrollbar = pygame.Rect(inner.right - 13, inner.y + 2,
                                     11, inner.height - 4)
        rows = max(1, self.area.height // self.line_h)
        max_scroll = max(0, len(self.lines) - rows)
        self.scroll = max(0, min(self.scroll, max_scroll))
        if self.cy < self.scroll:
            self.scroll = self.cy
        elif self.cy >= self.scroll + rows:
            self.scroll = self.cy - rows + 1

        if self.path is None:
            img = widgets.cached_text(self.font,
                                      "Select a .py file in the project tree.",
                                      xp.TEXT_MUTED)
            surface.blit(img, (self.area.centerx - img.get_width() // 2,
                               self.area.centery - img.get_height() // 2))
            return

        selection = self.sel()
        old_clip = surface.get_clip()
        surface.set_clip(self.area)
        y = self.area.y
        for i in range(self.scroll, min(len(self.lines), self.scroll + rows)):
            line_rect = pygame.Rect(self.area.x, y, self.area.width,
                                    self.line_h)
            if i == self.cy:
                surface.fill(xp.CODE_CURRENT, line_rect)
            if selection:
                (l0, c0), (l1, c1) = selection
                if l0 <= i <= l1:
                    a = c0 if i == l0 else 0
                    b = c1 if i == l1 else len(self.lines[i])
                    if b > a:
                        x0 = self.area.x + a * self.char_w
                        x1 = self.area.x + b * self.char_w
                        surface.fill(xp.CODE_SELECT,
                                     (x0, y, max(2, x1 - x0), self.line_h))
            if i == self.cy and not self.has_selection() and \
                    (self.blink % 1.0) < 0.55:
                cx = self.area.x + self.cx * self.char_w
                pygame.draw.line(surface, xp.CARET,
                                 (cx, y + 1), (cx, y + self.line_h - 2))
            y += self.line_h

        y = self.area.y
        for i in range(self.scroll, min(len(self.lines), self.scroll + rows)):
            self._draw_line(surface, i, self.area.x, y)
            num = widgets.cached_text(self.small, str(i + 1), xp.GUTTER_TEXT)
            surface.blit(num, (gutter.right - 8 - num.get_width(),
                               y + 2))
            y += self.line_h
        surface.set_clip(old_clip)

        if max_scroll > 0:
            xp.scrollbar(surface, self.scrollbar,
                         self.scroll / max(1, len(self.lines)),
                         rows / max(1, len(self.lines)))
        # modified marker in the gutter
        if self.dirty:
            pygame.draw.rect(surface, xp.MODIFIED,
                             (rect.x + 3, rect.y + 3, 4, 4))

    def _draw_line(self, surface, idx, x, y):
        line = self.lines[idx]
        tokens = self.tokens[idx] if idx < len(self.tokens) else []
        pos = 0
        for start, end, kind in tokens:
            if start > pos:
                img = widgets.cached_text(self.font, line[pos:start],
                                          xp.CODE_TEXT)
                if img:
                    surface.blit(img, (x + pos * self.char_w, y))
            if end > start:
                img = widgets.cached_text(
                    self.font, line[start:end], token_color(kind))
                if img:
                    surface.blit(img, (x + start * self.char_w, y))
            pos = max(pos, end)
        if pos < len(line):
            img = widgets.cached_text(self.font, line[pos:], xp.CODE_TEXT)
            if img:
                surface.blit(img, (x + pos * self.char_w, y))

    # ---------------------------------------------------------------- info
    def info(self):
        name = self.app.project.relative(self.path) if self.path else "-"
        return [
            ("File", name),
            ("Lines", str(len(self.lines))),
            ("Caret", f"line {self.cy + 1}, col {self.cx + 1}"),
            ("State", "modified" if self.dirty else "saved"),
        ]
