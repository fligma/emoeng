"""Shared demo scripts: terrain noise and the HUD helpers every scene draws.

Props live in `entities/` (stars, flame, orb, bonfire, mote, gem) and are
placed with `self.spawn(...)`. This module is only plain functions - the
loader leaves `scripts/` for code that is not an entity or a scene.

Scenes import them with `from scripts.helpers import feature_panel, ground`
(Project puts the project folder on sys.path before importing a scene).
"""

import math

import pygame

from fligengine.engine import ui
from fligengine.engine.game import CAP_H, MENU_H, STATUS_H

# the engine paints a title bar plus a menu along the top of the window and a
# status bar along the bottom; overlays have to stay inside the gap or the
# chrome covers them
CHROME_TOP = CAP_H + MENU_H
CHROME_BOTTOM = STATUS_H


def safe_area(screen):
    """Window rect the engine chrome leaves alone."""
    w, h = screen.get_size()
    return pygame.Rect(0, CHROME_TOP, w, h - CHROME_TOP - CHROME_BOTTOM)


def safe_bottom(screen, pad=10):
    """Baseline just above the engine status bar."""
    return screen.get_height() - CHROME_BOTTOM - pad


# ------------------------------------------------------------------ terrain
def _hash(ix, iz, seed):
    n = math.sin(ix * 127.1 + iz * 311.7 + seed * 74.7) * 43758.5453
    return n - math.floor(n)


def value_noise(x, z, seed=0.0):
    """Smooth 2D value noise in -1..1."""
    ix, iz = math.floor(x), math.floor(z)
    fx, fz = x - ix, z - iz
    fx = fx * fx * (3.0 - 2.0 * fx)
    fz = fz * fz * (3.0 - 2.0 * fz)
    a = _hash(ix, iz, seed)
    b = _hash(ix + 1, iz, seed)
    c = _hash(ix, iz + 1, seed)
    d = _hash(ix + 1, iz + 1, seed)
    top = a + (b - a) * fx
    bot = c + (d - c) * fx
    return (top + (bot - top) * fz) * 2.0 - 1.0


def ground(x, z):
    """Rolling ground used by both the terrain mesh and the walk camera."""
    return (0.9 * value_noise(x * 0.045, z * 0.045, 1.0) +
            0.30 * value_noise(x * 0.13 + 9.0, z * 0.13 - 4.0, 2.0) +
            0.10 * value_noise(x * 0.31, z * 0.31, 3.0))


# --------------------------------------------------------------------- HUD
def feature_panel(screen, fonts, title, rows, pos=None, width=300,
                  accent=(126, 182, 255), caption=None):
    """Translucent list of label/value pairs used by every demo scene.

    `pos` defaults to the top-left of the safe area; `caption` is the one
    line note drawn above the panel saying what the scene demonstrates.
    """
    line_h = fonts["small"].get_height() + 2
    if pos is None:
        pos = (18, safe_area(screen).y + 20)
    rect = ui.panel(screen, (pos[0], pos[1], width, 28 + line_h * len(rows)),
                    (8, 10, 16), 170, (62, 72, 92))
    if caption:
        ui.text(screen, fonts["small"], caption,
                (rect.x + 2, rect.y - fonts["small"].get_height() - 5),
                color=(158, 168, 190))
    ui.text(screen, fonts["normal"], title, (rect.x + 10, rect.y + 5),
            color=accent)
    y = rect.y + 25
    for label, value in rows:
        ui.text(screen, fonts["small"], str(label), (rect.x + 10, y),
                color=(196, 200, 210))
        ui.text(screen, fonts["small"], str(value), (rect.right - 10, y),
                color=(238, 240, 246), align="right")
        y += line_h
    return rect


def controls(screen, fonts, pairs, y=None):
    """Bottom row of 'key action' hints, laid out left to right.

    Sits above the engine status bar. A single row keeps the band free for
    subtitles - put one at `safe_bottom(screen) - font height - 8`. Scenes
    that need a stack call `ui.hints` directly.
    """
    font = fonts["small"]
    if y is None:
        y = safe_bottom(screen) - font.get_height()
    x = 18
    for key, label in pairs:
        cap = ui.keycap(screen, font, key, (x, y))
        ui.text(screen, font, label, (cap.right + 6, y + 3),
                color=(206, 202, 190))
        x = cap.right + 16 + font.size(label)[0] + 12
