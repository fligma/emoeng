"""The Docs tab: a reader for the engine's own documentation."""

import pygame

from ..engine import xp
from . import docs, widgets

NAV_W = 240
ROW_H = 18
HEAD_H = 20
SEARCH_H = 24


class DocsTab:
    """Two-pane documentation browser with a search filter."""

    def __init__(self, app):
        self.app = app
        try:
            self.api = docs.get()
        except Exception as exc:      # the editor must still start
            self.api = None
            app.log(f"docs: cannot read the engine sources ({exc})", "warn")
        self.query = widgets.TextField("")
        self.search_focus = False
        self.sel_key = docs.GUIDES[0]["key"]
        self.nav_scroll = 0
        self.body_scroll = 0
        self.body_max = 0
        self.area = pygame.Rect(0, 0, 0, 0)
        self.search_rect = pygame.Rect(0, 0, 0, 0)
        self.nav_rect = pygame.Rect(0, 0, 0, 0)
        self.body_rect = pygame.Rect(0, 0, 0, 0)
        self._rows = []          # [(label, key, depth, kind, rect)]

    def _filtered(self):
        if self.api is None:
            return []
        q = self.query.text.strip().lower()
        rows = []
        for label, key, depth, kind in self.api.nav():
            if kind == "group":
                if q:
                    continue
                rows.append((label, key, depth, kind))
                continue
            if q and q not in label.lower() and q not in key.lower():
                continue
            rows.append((label, key, depth, kind))
        return rows

    def _select_index(self, delta):
        keys = [r[1] for r in self._rows if r[1]]
        if not keys:
            return
        try:
            i = keys.index(self.sel_key)
        except ValueError:
            i = 0
        i = max(0, min(len(keys) - 1, i + delta))
        self.sel_key = keys[i]
        self.body_scroll = 0
        self._scroll_nav_into_view(i)

    def _scroll_nav_into_view(self, i):
        # rows include groups, so clamp against total height
        self.nav_scroll = max(0, min(self.nav_scroll,
                                     (i + 1) * ROW_H - self.nav_rect.height))

    def handle_event(self, e):
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.search_rect.collidepoint(e.pos):
                self.search_focus = True
                return True
            self.search_focus = False
            for label, key, depth, kind, rect in self._rows:
                if key and rect.collidepoint(e.pos):
                    self.sel_key = key
                    self.body_scroll = 0
                    self.app.status = f"docs: {label}"
                    return True
            return False
        if e.type == pygame.KEYDOWN and self.search_focus:
            before = self.query.text
            self.query.handle(e)
            if self.query.text != before:
                self.nav_scroll = 0
            if e.key == pygame.K_RETURN or e.key == pygame.K_KP_ENTER:
                self.search_focus = False
                self._select_index(0)
            return True
        if e.type == pygame.KEYDOWN and not self.search_focus:
            if e.key == pygame.K_UP:
                self._select_index(-1)
                return True
            if e.key == pygame.K_DOWN:
                self._select_index(1)
                return True
        if e.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if self.nav_rect.collidepoint(pos):
                self.nav_scroll = max(0, self.nav_scroll - e.y * 3 * ROW_H)
                return True
            if self.body_rect.collidepoint(pos):
                self.body_scroll = max(0, min(self.body_max,
                                              self.body_scroll - e.y * 24))
                return True
        return False

    def draw(self, surface, area, dt):
        fonts = self.app.fonts
        self.area = pygame.Rect(area)
        pygame.draw.rect(surface, xp.PANEL, area)
        head = pygame.Rect(area.x, area.y, area.width, HEAD_H)
        if self.api is None:
            widgets.header(surface, head, "Docs", fonts["normal"],
                           right="unavailable")
            img = widgets.cached_text(
                fonts["normal"],
                "The engine sources could not be read; see the output log.",
                xp.TEXT_MUTED)
            surface.blit(img, (area.x + 12, area.y + 40))
            self._rows = []
            return
        n_mods = len(self.api.modules)
        widgets.header(surface, head, "Docs", fonts["normal"],
                       right=f"{n_mods} modules, {len(self.api.entries)} "
                             f"api entries")
        self.search_rect = pygame.Rect(area.x + 8, head.bottom + 6,
                                       area.width - 16, SEARCH_H)
        xp.field(surface, self.search_rect)
        prompt = "Search guides and API..." if not self.query.text else ""
        if prompt:
            img = widgets.cached_text(fonts["small"], prompt, xp.TEXT_MUTED)
            surface.blit(img, (self.search_rect.x + 4,
                               self.search_rect.centery -
                               img.get_height() // 2))
        else:
            self.query.draw(surface, self.search_rect, fonts["normal"],
                            focused=self.search_focus)
        if self.search_focus:
            pygame.draw.rect(surface, xp.SELECT_BORDER, self.search_rect, 1)

        top = self.search_rect.bottom + 6
        bottom = area.bottom - 8
        self.nav_rect = pygame.Rect(area.x + 8, top, NAV_W,
                                    bottom - top)
        self.body_rect = pygame.Rect(self.nav_rect.right + 8, top,
                                     area.right - 8 - (self.nav_rect.right + 8),
                                     bottom - top)
        self._draw_nav(surface)
        self._draw_body(surface)

    def _draw_nav(self, surface):
        fonts = self.app.fonts
        rect = self.nav_rect
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        inner = rect.inflate(-2, -2)
        rows = self._filtered()
        content_h = len(rows) * ROW_H
        self.nav_scroll = max(0, min(self.nav_scroll,
                                     max(0, content_h - inner.height)))
        old = surface.get_clip()
        surface.set_clip(inner)
        mouse = pygame.mouse.get_pos()
        self._rows = []
        y = inner.y + 1 - self.nav_scroll
        for label, key, depth, kind in rows:
            row = pygame.Rect(inner.x, y, inner.width - 12, ROW_H)
            text_x = row.x + 6 + depth * 12
            if kind == "group":
                pygame.draw.rect(surface, xp.THUMB_BG, row)
                img = widgets.cached_text(fonts["small"], label.upper(),
                                          xp.LINK)
                surface.blit(img, (row.x + 6,
                                   row.centery - img.get_height() // 2))
            else:
                selected = key == self.sel_key
                if selected:
                    pygame.draw.rect(surface, xp.SELECTION, row)
                elif row.collidepoint(mouse):
                    pygame.draw.rect(surface, xp.BTN_HOVER_BG, row)
                if kind == "module":
                    color = xp.SELECT_TEXT if selected else xp.TEXT
                    img = widgets.cached_text(fonts["normal"], label, color)
                elif kind == "class":
                    color = xp.SELECT_TEXT if selected else xp.SYN_DEF
                    img = widgets.cached_text(fonts["small"], label, color)
                else:
                    color = xp.SELECT_TEXT if selected else xp.TEXT
                    img = widgets.cached_text(fonts["small"], label, color)
                if img:
                    surface.blit(img, (text_x,
                                       row.centery - img.get_height() // 2))
            self._rows.append((label, key, depth, kind, row))
            y += ROW_H
        surface.set_clip(old)
        if content_h > inner.height:
            xp.scrollbar(surface, pygame.Rect(rect.right - 13, rect.y + 2,
                                              11, rect.height - 4),
                         self.nav_scroll / max(1, content_h),
                         inner.height / max(1, content_h))

    def _draw_body(self, surface):
        fonts = self.app.fonts
        rect = self.body_rect
        pygame.draw.rect(surface, xp.FIELD, rect)
        xp.sunken(surface, rect)
        inner = rect.inflate(-4, -4)
        title, badge, blocks = self.api.content(self.sel_key)

        # pre-measure so the scrollbar knows the content height
        pad = 10
        width = inner.width - 2 * pad
        small_h = fonts["small"].get_height() + 1
        normal_h = fonts["normal"].get_height() + 2
        mono_h = fonts["mono"].get_height() + 2
        measured = []
        total = pad
        for style, text in blocks:
            if style == "head":
                total += normal_h + 4
                measured.append((style, [text]))
            elif style in ("sig", "loc"):
                total += (mono_h if style == "sig" else small_h) + 2
                measured.append((style, [text]))
            elif style == "sub":
                total += small_h
                measured.append((style, [text]))
            else:
                lines = (widgets.wrap(fonts["normal"], text, width)
                         if text.strip() else [""])
                total += normal_h * len(lines) + (2 if text.strip() else 4)
                measured.append(("text", lines))
        content_top = inner.y + 40
        content = pygame.Rect(inner.x, content_top, inner.width,
                              max(0, inner.bottom - content_top))
        self.body_max = max(0, total - content.height)
        self.body_scroll = max(0, min(self.body_scroll, self.body_max))

        old = surface.get_clip()
        surface.set_clip(inner)

        # heading
        pygame.draw.rect(surface, xp.FACE,
                         (inner.x, inner.y, inner.width, 34))
        pygame.draw.line(surface, xp.SHADOW, (inner.x, inner.y + 34),
                         (inner.right, inner.y + 34))
        t = widgets.cached_text(fonts["big"], title, xp.TEXT)
        surface.blit(t, (inner.x + pad, inner.y + 6))
        if badge and badge != "guide":
            b = widgets.cached_text(fonts["small"], badge, xp.TEXT_MUTED)
            surface.blit(b, (inner.x + pad + t.get_width() + 8,
                             inner.y + 14))

        surface.set_clip(content)
        y = content.y + pad - self.body_scroll
        for style, payload in measured:
            if style == "head":
                img = widgets.cached_text(fonts["normal"], payload[0],
                                          xp.LINK)
                if img:
                    surface.blit(img, (inner.x + pad, y + 2))
                y += normal_h + 4
            elif style == "sig":
                img = widgets.cached_text(fonts["mono"], payload[0],
                                          xp.SYN_DEF)
                if img:
                    if img.get_width() > width:
                        img = img.subsurface(
                            (0, 0, min(img.get_width(), width),
                             img.get_height()))
                    surface.blit(img, (inner.x + pad, y))
                y += mono_h + 2
            elif style == "loc":
                img = widgets.cached_text(fonts["small"], payload[0],
                                          xp.TEXT_MUTED)
                if img:
                    surface.blit(img, (inner.x + pad, y))
                y += small_h + 4
            elif style == "sub":
                img = widgets.cached_text(fonts["small"], payload[0],
                                          xp.TEXT_MUTED)
                if img:
                    surface.blit(img, (inner.x + pad + 10, y))
                y += small_h
            else:
                for ln in payload:
                    if ln:
                        color = (xp.SYN_COMMENT if ln.startswith(" ")
                                 else xp.TEXT)
                        img = widgets.cached_text(fonts["normal"], ln, color)
                        if img:
                            surface.blit(img, (inner.x + pad, y))
                    y += normal_h
                y += 2
        surface.set_clip(old)
        if self.body_max > 0:
            shown = content.height / max(1, total)
            xp.scrollbar(surface, pygame.Rect(rect.right - 13, rect.y + 2,
                                              11, rect.height - 4),
                         self.body_scroll / max(1, total), shown)

    def info(self):
        if self.api is None:
            return [("Viewing", "unavailable"), ("Kind", "-"),
                    ("Topics", "0"), ("Search", self.query.text or "-")]
        title, badge, _ = self.api.content(self.sel_key)
        return [
            ("Viewing", title),
            ("Kind", badge or "page"),
            ("Topics", str(len(self.api.nav())) ),
            ("Search", self.query.text or "-"),
        ]
