"""The loading screen: honest progress instead of a black window.

A slow machine can take many seconds to open a project. Without these
steps the window shows nothing at all until the work is finished, and
the operating system marks it "not responding"; every boot and every
project open reports its stage here, repainting and pumping events so
the screen is always telling the truth about what it is doing.
"""

import time

import pygame

from . import ui

BG = (30, 32, 38)
TRACK = (56, 60, 70)
FILL = (52, 96, 158)
BAD = (196, 80, 72)
TEXT = (222, 226, 234)
MUTED = (140, 146, 158)


class Loading:
    """A progress screen painted onto whatever window is already open.

    `step()` sets the words and the fraction and shows them at once;
    the fraction only ever moves forward until `begin()` starts a new
    load. `fail()` turns the screen into an error card and holds it up
    long enough to be read, answering False if the window was closed."""

    def __init__(self, screen, title, note=""):
        self.screen = screen
        self.title = str(title)
        self.note = str(note)
        self.status = ""
        self.frac = 0.0
        self.error = ""
        try:
            self.big = ui.load_font("tahoma", 26, bold=True)
            self.face = ui.load_font("tahoma", 13)
            self.small = ui.load_font("tahoma", 10)
        except Exception:
            self.big = pygame.font.Font(None, 32)
            self.face = pygame.font.Font(None, 18)
            self.small = pygame.font.Font(None, 14)

    def begin(self, status="starting", frac=0.0):
        """Start a fresh load: the bar may go back to the beginning."""
        self.frac = 0.0
        self.error = ""
        return self.step(status, frac)

    def step(self, status, frac=None):
        if frac is not None:
            try:
                self.frac = max(self.frac, min(1.0, max(0.0, float(frac))))
            except (TypeError, ValueError):
                pass
        self.status = str(status)
        return self._paint()

    def fail(self, status, detail="", hold=8.0):
        """Show why the machine stopped, and let the words be read."""
        self.status = str(status)
        self.error = str(detail or "")
        self.frac = 1.0
        self._paint()
        end = time.monotonic() + max(1.0, float(hold))
        while time.monotonic() < end:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return False
            time.sleep(0.05)
            self._paint()
        return not pygame.event.peek([pygame.QUIT])

    def _paint(self):
        """One frame of the card; a broken splash must never break a load."""
        try:
            s = pygame.display.get_surface() or self.screen
            w, h = s.get_size()
            s.fill(BG)
            box = s.get_clip()
            title = self.big.render(self.title, True, TEXT)
            s.blit(title, ((w - title.get_width()) // 2, h // 2 - 56))
            bar = pygame.Rect(0, 0, min(360, w - 48), 14)
            bar.center = (w // 2, h // 2 + 12)
            pygame.draw.rect(s, TRACK, bar, border_radius=7)
            room = bar.width - 4
            got = int(room * self.frac)
            if got > 0:
                fill = BAD if self.error else FILL
                pygame.draw.rect(s, fill,
                                 (bar.x + 2, bar.y + 2, got, bar.height - 4),
                                 border_radius=6)
            word = self.error.splitlines()[0] if self.error else self.status
            line = self.face.render(word, True,
                                    BAD if self.error else TEXT)
            s.blit(line, ((w - line.get_width()) // 2, bar.bottom + 10))
            pct = self.small.render(f"{int(round(self.frac * 100))}%", True,
                                    MUTED)
            s.blit(pct, (bar.right + 8 - pct.get_width(), bar.cy
                         - pct.get_height() // 2))
            if self.note:
                note = self.small.render(self.note, True, MUTED)
                s.blit(note, ((w - note.get_width()) // 2, h - 34))
            if self.error:
                # the reason is long; wrap a few lines under the bar
                y = bar.bottom + 34
                for part in self.error.splitlines()[1:6]:
                    ln = self.small.render(part.strip()[:120], True, MUTED)
                    s.blit(ln, ((w - ln.get_width()) // 2, y))
                    y += ln.get_height() + 2
            s.set_clip(box)
            pygame.display.flip()
            pygame.event.pump()
        except Exception:
            # the load itself matters more than its messenger
            pass
        return True
