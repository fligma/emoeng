"""The Audio tab: the player and the maker behind one header.

Both views want the same width and the same tab, so the tab owns one header
with a two-button switch and hands the body to whichever side is in front.
`app.py` still talks to `self.media` alone: the names it uses - current,
dirty, load, pause, stop, set_project, draw, handle_event, info - are all
answered here.
"""

from __future__ import annotations

import pygame

from ..engine import xp
from . import widgets
from .mediaplayer import MediaPlayer
from .sfxeditor import SfxEditor

HEAD_H = 22
SUB_H = 24


class AudioTab:
    """Play the project's sounds, or edit a sound project's pattern."""

    def __init__(self, app):
        self.app = app
        self.player = MediaPlayer(app)
        self.maker = SfxEditor(app)
        self.mode = "player"
        self.header = pygame.Rect(0, 0, 0, 0)
        self.bar = pygame.Rect(0, 0, 0, 0)
        self.switch = {}            # mode -> rect, drawn this frame
        self.new_buttons = []       # (kind, rect) for New Sound / New Music

    # -- what app.py asks of the tab -----------------------------------

    @property
    def current(self):
        """The file the caption names: the pattern in front, or the track."""
        if self.mode == "maker" and self.maker.path is not None:
            return self.maker.path
        return self.player.current

    @property
    def dirty(self):
        return self.maker.dirty

    def set_project(self, project):
        self.maker.set_project(project)
        self.player.set_project(project)
        self.mode = "maker" if self.maker.doc is not None else "player"

    def refresh(self):
        self.player.refresh()

    def load(self, path):
        """A wav picked anywhere opens in the player."""
        self.set_mode("player")
        self.player.load(path)

    def play(self):
        return self.player.play()

    def toggle(self):
        return self.player.toggle()

    def pause(self):
        """Leaving the tab: the player holds its place, the preview stops."""
        self.maker.stop()
        self.player.pause()

    def stop(self):
        self.maker.stop()
        self.player.stop()

    def save(self):
        """Ctrl+S: the maker's Save is the collapse, and it asks first."""
        if self.mode != "maker":
            return False
        return self.maker.save()

    def use_fonts(self, fonts):
        self.player.fonts = fonts

    def info(self):
        return self.maker.info() if self.mode == "maker" else \
            self.player.info()

    def create(self, kind):
        """New Sound / New Music: the maker names one and opens it."""
        self.set_mode("maker")
        self.maker.prompt_new(kind)
        return True

    def set_mode(self, mode):
        mode = "maker" if mode == "maker" else "player"
        if mode == self.mode:
            return self.mode
        if self.mode == "maker":
            self.maker.stop()
        else:
            self.player.pause()
        self.mode = mode
        if mode == "maker":
            self.app.status = "sound maker"
            self.app.log("audio: the maker edits audio/*"
                         f"{'.sfxproject'}; Save collapses one to a wav",
                         "muted")
        else:
            self.app.status = "audio player"
        return mode

    # -- events and paint ----------------------------------------------

    def handle_event(self, e):
        pos = getattr(e, "pos", None)
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and \
                pos is not None:
            for mode, box in self.switch.items():
                if box.collidepoint(pos):
                    self.set_mode(mode)
                    return True
            for kind, box in self.new_buttons:
                if box.collidepoint(pos):
                    return self.create(kind)
        if self.mode == "maker":
            return self.maker.handle_event(e)
        return self.player.handle_event(e)

    def draw(self, surface, rect):
        area = pygame.Rect(rect)
        self.header = pygame.Rect(area.x, area.y, area.width, HEAD_H)
        self.bar = pygame.Rect(area.x, self.header.bottom, area.width, SUB_H)
        body = pygame.Rect(area.x, self.bar.bottom, area.width,
                           max(0, area.height - HEAD_H - SUB_H))
        if self.mode == "maker":
            self.maker.draw(surface, body)
        else:
            # the tab draws the one header, so the player paints no second
            self.player.draw(surface, body, head=0)
        right = (f"{len(self.player.files)} files" if self.mode == "player"
                 else "maker")
        widgets.header(surface, self.header, "Audio",
                       self.app.fonts["normal"], right=right,
                       icon="tab-audio-sym")
        self._draw_bar(surface)

    def _draw_bar(self, surface):
        """The Player / Sound maker switch, and New, above both views."""
        self.switch = {}
        self.new_buttons = []
        if not self.bar.height:
            return
        surface.fill(xp.FACE, self.bar)
        pygame.draw.line(surface, xp.SHADOW, (self.bar.x, self.bar.bottom - 1),
                         (self.bar.right - 1, self.bar.bottom - 1))
        font = self.app.fonts["small"]
        mouse = pygame.mouse.get_pos()
        x = self.bar.x + 6
        for mode, label, name in (("player", "Player", "tab-audio-sym"),
                                  ("maker", "Sound maker", "sound-on-sym")):
            art = widgets.icon(name, 14)
            width = font.size(label)[0] + 14 + (22 if art else 0)
            box = pygame.Rect(x, self.bar.y + 3, width,
                              self.bar.height - 6)
            xp.button(surface, box, label, font, pressed=self.mode == mode,
                      hovered=box.collidepoint(mouse), icon=art)
            self.switch[mode] = box
            x = box.right + 4
        if self.mode != "player":
            hint = widgets.cached_text(font, "Save flattens it to a wav",
                                       xp.TEXT_MUTED)
            surface.blit(hint, (self.bar.right - 8 - hint.get_width(),
                                self.bar.centery - hint.get_height() // 2))
            return
        for kind, label in (("sfx", "New Sound"), ("music", "New Music")):
            width = font.size(label)[0] + 18
            if x + 8 + width > self.bar.right - 8:
                break               # a narrow tab keeps the maker's own New
            box = pygame.Rect(x + 8, self.bar.y + 3, width,
                              self.bar.height - 6)
            xp.button(surface, box, label, font,
                      hovered=box.collidepoint(mouse))
            self.new_buttons.append((kind, box))
            x = box.right
