"""PS2-flavoured screen effects.

The renderer already does the heavy lifting (low internal resolution,
vertex-colour lighting, distance fog). These are the cheap frame passes a
scene can ask for: 16-bit style dithering, scanlines, vignette, grain and
fades. Overlays are cached per size so a per-frame pass stays a blit.
"""

import numpy as np
import pygame

_CACHE = {}

_BAYER4 = np.array([[0, 8, 2, 10],
                    [12, 4, 14, 6],
                    [3, 11, 1, 9],
                    [15, 7, 13, 5]], np.float32) / 16.0


def _key(surf, name, *args):
    return (surf.get_width(), surf.get_height(), name) + args


def dither(surf, levels=32):
    """Quantise colour with a 4x4 Bayer matrix - the banded, 16-bit look
    without a shader pass."""
    w, h = surf.get_size()
    arr = pygame.surfarray.array3d(surf).astype(np.float32)
    tile = _BAYER4[np.arange(h)[:, None] % 4, np.arange(w)[None, :] % 4]
    step = 255.0 / max(2, levels - 1)
    arr = np.floor(arr / step + tile.T[..., None] - 0.5) * step
    np.clip(arr, 0, 255, out=arr)
    return pygame.surfarray.make_surface(arr.astype(np.uint8))


def _overlay(size, name, builder):
    key = (size, name)
    if key not in _CACHE:
        _CACHE[key] = builder(size)
    return _CACHE[key]


def scanlines(surf, strength=70, step=3):
    """Dark CRT lines, built once per size."""
    def build(size):
        w, h = size
        ov = pygame.Surface(size, pygame.SRCALPHA)
        for y in range(0, h, step):
            pygame.draw.line(ov, (0, 0, 0, strength), (0, y), (w, y))
        return ov
    surf.blit(_overlay(surf.get_size(), ("scan", strength, step), build),
              (0, 0))


def vignette(surf, strength=150):
    """Darkened corners; the console-era tunnel vision."""
    def build(size):
        w, h = size
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        dx = (xx / max(1, w - 1) - 0.5) * 2.0
        dy = (yy / max(1, h - 1) - 0.5) * 2.0
        r = np.clip(np.sqrt(dx * dx + dy * dy) - 0.45, 0.0, 1.4) / 1.4
        alpha = np.clip(r * r * strength, 0, 255).astype(np.uint8)
        ov = pygame.Surface(size, pygame.SRCALPHA)
        ov.fill((0, 0, 0, 255))
        a = pygame.surfarray.pixels_alpha(ov)
        a[:] = alpha.T
        del a
        return ov
    surf.blit(_overlay(surf.get_size(), ("vig", strength), build), (0, 0))


def grain(surf, amount=14, seed=None):
    """One frame of film noise."""
    w, h = surf.get_size()
    rng = np.random.default_rng(seed)
    noise = rng.integers(-amount, amount + 1, (w, h, 1), dtype=np.int16)
    arr = pygame.surfarray.array3d(surf).astype(np.int16) + noise
    np.clip(arr, 0, 255, out=arr)
    return pygame.surfarray.make_surface(arr.astype(np.uint8))


def fade(surf, color=(0, 0, 0), amount=0.0):
    """Flat colour wash; amount 0..1."""
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0:
        return
    ov = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    ov.fill((color[0], color[1], color[2], int(255 * amount)))
    surf.blit(ov, (0, 0))


def tint(surf, color, amount=0.0):
    """Colour wash that keeps the image visible (damage, acid, torchlight)."""
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0.0:
        return
    ov = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    ov.fill((color[0], color[1], color[2], int(255 * amount)))
    surf.blit(ov, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)


def apply(surf, names):
    """Run a chain of named passes, e.g. ("dither", "scanlines")."""
    for name in names:
        fn = _PASSES.get(name)
        if fn is not None:
            out = fn(surf)
            if out is not None:
                surf = out
    return surf


_PASSES = {
    "dither": dither,
    "scanlines": scanlines,
    "vignette": vignette,
    "grain": grain,
    # pre-tuned colour passes so scenes can name them in `post` too
    "fade": lambda s: fade(s, (0, 0, 0), 0.18),
    "warm": lambda s: tint(s, (1.0, 0.74, 0.44), 0.18),
    "cold": lambda s: tint(s, (0.44, 0.70, 1.0), 0.18),
}


def passes():
    """Names usable in a scene's `post` tuple."""
    return tuple(_PASSES)


def clear_cache():
    _CACHE.clear()
