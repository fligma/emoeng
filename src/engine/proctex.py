"""Runtime texture synthesis: paint surfaces from numpy noise instead of
shipping image files.

Every builder returns a uint8 array (size, size, 3) - or RGBA for glows -
ready for `renderer.texture("name", arr)`. Handy for prototyping and for
the chunky, hand-painted PS2 look.
"""

import numpy as np


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def noise2d(h, w, cells, seed):
    """Smooth value noise on an h x w grid from a coarse random lattice."""
    rng = np.random.default_rng(seed)
    g = rng.random((cells + 1, cells + 1))
    ys = np.linspace(0.0, cells, h)
    xs = np.linspace(0.0, cells, w)
    y0 = np.clip(ys.astype(np.int32), 0, cells - 1)
    x0 = np.clip(xs.astype(np.int32), 0, cells - 1)
    fy = _smooth(ys - y0)[:, None]
    fx = _smooth(xs - x0)[None, :]
    a = g[y0[:, None], x0[None, :]]
    b = g[y0[:, None], x0[None, :] + 1]
    c = g[y0[:, None] + 1, x0[None, :]]
    d = g[y0[:, None] + 1, x0[None, :] + 1]
    top = a + (b - a) * fx
    bot = c + (d - c) * fx
    return top + (bot - top) * fy


def _mix(a, b, t):
    return a + (b - a) * t


def _bytes(col):
    return (np.clip(col, 0.0, 1.0) * 255.0).astype(np.uint8)


def checker(size=64, cells=8, a=(0.55, 0.55, 0.52), b=(0.30, 0.30, 0.34)):
    """The classic editor/placeholder checker."""
    n = size // cells
    yy, xx = np.mgrid[0:size, 0:size] // n
    mask = ((xx + yy) % 2).astype(bool)
    col = np.empty((size, size, 3))
    col[:] = a
    col[mask] = b
    return _bytes(col)


def grid(size=128, cells=8, line=(0.18, 0.20, 0.22),
         fill=(0.38, 0.40, 0.42), width=2):
    """Tiling grid texture: suits floors, crates and editor surfaces."""
    col = np.empty((size, size, 3))
    col[:] = fill
    step = max(2, size // cells)
    for i in range(0, size, step):
        col[i:i + width, :] = line
        col[:, i:i + width] = line
    return _bytes(col)


def ground(size=256, seed=101):
    broad = noise2d(size, size, 6, seed)
    fine = noise2d(size, size, 40, seed + 1)
    speck = noise2d(size, size, 140, seed + 2)
    base = np.array([0.30, 0.24, 0.16])
    dark = np.array([0.14, 0.12, 0.09])
    moss = np.array([0.15, 0.20, 0.11])
    m = broad * 0.55 + fine * 0.30 + speck * 0.15
    col = _mix(base, dark, np.clip((0.55 - m) * 1.8, 0, 1)[..., None])
    green = np.clip((m - 0.58) * 2.6, 0, 1)[..., None]
    col = _mix(col, moss, green * 0.8) * (0.8 + 0.4 * speck[..., None])
    return _bytes(col)


def stone(size=128, seed=202):
    n = noise2d(size, size, 10, seed) * 0.6 + \
        noise2d(size, size, 34, seed + 1) * 0.4
    cracks = np.clip((noise2d(size, size, 22, seed + 2) - 0.5) * 6, 0, 1)
    base = np.array([0.44, 0.42, 0.40])
    col = base * (0.65 + 0.55 * n[..., None])
    col = _mix(col, np.array([0.11, 0.10, 0.09]), cracks[..., None] * 0.5)
    return _bytes(col)


def rust(size=128, seed=303):
    """Rusted metal: orange bloom over dark iron."""
    n = noise2d(size, size, 12, seed) * 0.7 + \
        noise2d(size, size, 46, seed + 1) * 0.3
    pits = np.clip((noise2d(size, size, 30, seed + 2) - 0.62) * 5, 0, 1)
    iron = np.array([0.24, 0.23, 0.24])
    orange = np.array([0.52, 0.25, 0.10])
    col = _mix(iron, orange, np.clip((n - 0.42) * 2.2, 0, 1)[..., None])
    col *= (1.0 - 0.45 * pits[..., None])
    return _bytes(col)


def bark(size=64, seed=404):
    n_long = noise2d(size, size, 4, seed)
    n_short = noise2d(size, size, 26, seed + 1)
    m = n_long * 0.7 + n_short * 0.3
    col = _mix(np.array([0.09, 0.06, 0.04]),
               np.array([0.26, 0.17, 0.11]), m[..., None])
    return _bytes(col)


def cloth(size=64, seed=505):
    n = noise2d(size, size, 12, seed)
    weave = ((np.add.outer(np.arange(size), np.arange(size)) % 3) == 0)
    col = np.array([0.46, 0.28, 0.15]) * (0.85 + 0.3 * n[..., None])
    col *= (1.0 - 0.12 * weave[..., None])
    return _bytes(col)


def stripes(size=64, count=8, a=(0.55, 0.18, 0.12),
            b=(0.80, 0.74, 0.55), vertical=True):
    idx = (np.arange(size) * count // size) % 2
    col = np.empty((size, size, 3))
    col[:] = a
    if vertical:
        col[:, idx == 1] = b
    else:
        col[idx == 1, :] = b
    return _bytes(col)


def glow(size=128, color=(1.0, 0.62, 0.22), seed=606):
    """RGBA radial glow for additive billboards."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xx + 0.5) / size * 2.0 - 1.0
    v = (yy + 0.5) / size * 2.0 - 1.0
    r = np.clip(np.sqrt(u * u + v * v), 0, 1.4)
    body = np.clip(1.0 - r, 0.0, 1.0) ** 2.0
    flick = noise2d(size, size, 20, seed) * 0.4 + 0.8
    rgba = np.zeros((size, size, 4))
    rgba[..., :3] = np.asarray(color) * flick[..., None]
    rgba[..., 3] = body
    return _bytes(rgba)


def flame(size=128, seed=707):
    """RGBA teardrop fire sprite with a hot core."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xx + 0.5) / size
    v = 1.0 - (yy + 0.5) / size
    cx = 0.5 + 0.10 * np.sin(v * 6.0)
    w = 0.34 * (1.0 - v * 0.75)
    r = np.clip(((u - cx) / w) ** 2 + ((v - 0.42) / 0.55) ** 2, 0, 4)
    body = np.clip(1.0 - r, 0, 1) ** 1.6
    flick = noise2d(size, size, 26, seed) * 0.5 + \
        noise2d(size, size, 60, seed + 1) * 0.5
    body *= (0.75 + 0.5 * flick) * np.clip(v * 6.0, 0, 1)
    hot = np.array([1.0, 0.92, 0.55])
    mid = np.array([1.0, 0.45, 0.08])
    cool = np.array([0.55, 0.10, 0.02])
    t1 = np.clip((body - 0.55) / 0.45, 0, 1)
    t2 = np.clip((body - 0.18) / 0.5, 0, 1)
    col = _mix(_mix(cool, mid, t2[..., None]), hot, t1[..., None])
    rgba = np.concatenate([col, np.clip(body * 1.5, 0, 1)[..., None]],
                          axis=-1)
    return _bytes(rgba)


def noise_rgb(size=128, seed=808, tint=(1.0, 1.0, 1.0)):
    """Coloured grain for dirt overlays and UI fills."""
    n = noise2d(size, size, 30, seed)
    col = n[..., None] * np.asarray(tint)
    return _bytes(col)
