"""Runtime texture synthesis: paint surfaces from numpy noise instead of"""

import inspect

import numpy as np


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def noise2d(h, w, cells, seed):
    """Smooth value noise on an h x w grid, edge-wrapping."""
    rng = np.random.default_rng(seed)
    g = rng.random((cells, cells))
    ys = np.linspace(0.0, cells, h, endpoint=False)
    xs = np.linspace(0.0, cells, w, endpoint=False)
    y0 = ys.astype(np.int32) % cells
    x0 = xs.astype(np.int32) % cells
    y1 = (y0 + 1) % cells
    x1 = (x0 + 1) % cells
    fy = _smooth(ys - np.floor(ys))[:, None]
    fx = _smooth(xs - np.floor(xs))[None, :]
    a = g[y0[:, None], x0[None, :]]
    b = g[y0[:, None], x1[None, :]]
    c = g[y1[:, None], x0[None, :]]
    d = g[y1[:, None], x1[None, :]]
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
    n = noise2d(size, size, 10, seed) * 0.55 + \
        noise2d(size, size, 34, seed + 1) * 0.28 + \
        noise2d(size, size, 96, seed + 3) * 0.17
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


def spark(size=64, color=(1.0, 0.78, 0.42), seed=1010, soft=0.55):
    """RGBA mote for particles: a hot core with a faint four-point flare.

    Small and square, because one particle is one whole sheet: the quad's
    own size is what the emitter's `size` knob turns.
    """
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xx + 0.5) / size * 2.0 - 1.0
    v = (yy + 0.5) / size * 2.0 - 1.0
    r = np.clip(np.sqrt(u * u + v * v), 0.0, 1.4)
    s = max(0.02, min(0.98, float(soft)))
    body = np.clip(1.0 - r / s, 0.0, 1.0) ** 1.8
    # the flare is a thin cross, so the mote reads as a glint, not a dot
    arms = np.clip(1.0 - np.abs(u) * 9.0, 0.0, 1.0) + \
        np.clip(1.0 - np.abs(v) * 9.0, 0.0, 1.0)
    body = np.clip(body + 0.28 * arms * np.clip(1.0 - r, 0.0, 1.0), 0.0, 1.0)
    grain = noise2d(size, size, 14, seed) * 0.25 + 0.85
    hot = np.asarray(color, np.float64)
    tint = np.ones(3) * 0.9 + hot * 0.1
    rgba = np.zeros((size, size, 4))
    rgba[..., :3] = _mix(tint[None, None, :], hot[None, None, :],
                         np.clip(body * 1.6, 0.0, 1.0)[..., None])
    rgba[..., 3] = body * grain
    return _bytes(rgba)


def smoke(size=64, seed=1111, wisp=0.5, color=(0.62, 0.60, 0.58)):
    """RGBA puff for dust and smoke: soft noise clipped to a disc."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xx + 0.5) / size * 2.0 - 1.0
    v = (yy + 0.5) / size * 2.0 - 1.0
    r = np.clip(np.sqrt(u * u + v * v), 0.0, 1.0)
    fine = noise2d(size, size, 7, seed) * 0.6 + \
        noise2d(size, size, 19, seed + 1) * 0.4
    k = max(0.02, min(0.95, float(wisp)))
    edge = np.clip((r - (1.0 - k)) / max(1e-3, k), 0.0, 1.0)
    body = np.clip((1.0 - edge) * (0.45 + 0.9 * fine), 0.0, 1.0)
    rgba = np.zeros((size, size, 4))
    rgba[..., :3] = np.asarray(color, np.float64) * \
        (0.75 + 0.45 * fine[..., None])
    rgba[..., 3] = body
    return _bytes(rgba)


def noise_rgb(size=128, seed=808, tint=(1.0, 1.0, 1.0)):
    """Coloured grain for dirt overlays and UI fills."""
    n = noise2d(size, size, 30, seed)
    col = n[..., None] * np.asarray(tint)
    return _bytes(col)


def noise(size=128, cells=6, octaves=4, seed=909, gain=0.5,
          contrast=1.0, tint=(0.62, 0.60, 0.56), base=0.0, alpha=False):
    """Fractal value noise: the generator every surface leans on."""
    size = int(max(4, size))
    total = np.zeros((size, size))
    weight = 0.0
    amp = 1.0
    band = float(max(1, int(cells)))
    for o in range(max(1, int(octaves))):
        step = int(max(1, round(band)))
        total = total + noise2d(size, size, step, seed + 7 * o) * amp
        weight += amp
        amp *= max(0.05, min(0.95, float(gain)))
        band *= 2.0
    m = total / max(1e-6, weight)
    m = np.clip((m - 0.5) * max(0.05, float(contrast)) + 0.5, 0.0, 1.0)
    m = np.clip(m + float(base), 0.0, 1.0)
    out = np.zeros((size, size, 4))
    out[..., :3] = m[..., None] * np.asarray(tint, np.float64)[:3]
    out[..., 3] = m if alpha else 1.0
    return _bytes(out if alpha or len(np.unique(out[..., 3])) > 1
                 else out[..., :3])


def solid(color=(1.0, 1.0, 1.0), size=2):
    """A flat colour as a texture, from a hex string."""
    from . import colors
    r, g, b, a = colors.rgba(color, (1.0, 1.0, 1.0, 1.0))
    out = np.zeros((size, size, 4), np.float64)
    out[..., 0], out[..., 1], out[..., 2] = r, g, b
    out[..., 3] = a
    return _bytes(out) if a < 0.999 else _bytes(out[..., :3])


# File-less sheets: (name, factory, knobs, register options).
# `tile` is metres per repeat; `repeat: False` marks a sprite.
SHEETS = (
    ("checker", checker, {"size": 64, "cells": 8}, {"tile": 0.5}),
    ("grid", grid, {"size": 128, "cells": 8}, {"tile": 1.0}),
    ("ground", ground, {"size": 256}, {"tile": 2.0}),
    ("stone", stone, {"size": 128}, {"tile": 1.0}),
    ("rust", rust, {"size": 128}, {"tile": 0.5}),
    ("bark", bark, {"size": 64}, {"tile": 0.25}),
    ("cloth", cloth, {"size": 64}, {"tile": 0.2}),
    ("noise", noise, {"size": 128, "cells": 6}, {"tile": 1.0}),
    ("flame", flame, {"size": 128}, {"rgba": True, "repeat": False}),
    ("glow", glow, {"size": 128}, {"rgba": True, "repeat": False}),
    ("spark", spark, {"size": 64}, {"rgba": True, "repeat": False}),
    ("smoke", smoke, {"size": 64}, {"rgba": True, "repeat": False}),
)

# what a renderer registers: (name, build it, options)
BUILTIN = tuple((name, (lambda make=make, over=over: make(**over)), opts)
                for name, make, over, opts in SHEETS)


def _entry(name):
    """One sheet's (factory, knob defaults, register options)."""
    for found in SHEETS:
        if found[0] == name:
            return found[1], found[2], found[3]
    return None, None, None


def knobs(name):
    """Every knob one built-in sheet turns, and its starting value."""
    make, over, _opts = _entry(name)
    if make is None:
        return {}
    got = {p.name: p.default
           for p in inspect.signature(make).parameters.values()
           if p.default is not inspect.Parameter.empty}
    got.update({k: v for k, v in over.items() if k in got})
    return got


def accepts(name):
    """Every knob a built-in's factory takes, generated ones included."""
    make, _over, _opts = _entry(name)
    return () if make is None else tuple(inspect.signature(make).parameters)


def build(name, **over):
    """One built-in sheet as an array; None if unnamed."""
    make, base, _opts = _entry(name)
    if make is None:
        return None
    got = dict(base)
    allowed = inspect.signature(make).parameters
    got.update({k: v for k, v in over.items() if k in allowed})
    return make(**got)


def options(name):
    """How one built-in is registered: tile metres, rgba, wrap."""
    return dict(_entry(name)[2] or {})


def names():
    """The built-in sheet stems, in the order `BUILTIN` lists them."""
    return [key for key, _make, _opts in BUILTIN]


def radial(size=128, soft=0.0, mode=0, exponent=2.0, outer=(1.0, 1.0, 1.0),
           shape="circle", hole=0.0):
    """A 2D light's falloff, alpha carrying the curve."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    u = (xx + 0.5) / size * 2.0 - 1.0
    v = (yy + 0.5) / size * 2.0 - 1.0
    if str(shape) == "box":
        r = np.maximum(np.abs(u), np.abs(v))
    else:
        r = np.clip(np.sqrt(u * u + v * v), 0.0, 1.0)
    if str(shape) == "ring":
        # how far from the band, not the centre
        mid = 0.5 * (1.0 + max(0.0, min(0.95, float(hole))))
        half = max(1e-3, 1.0 - mid)
        r = np.clip(np.abs(r - mid) / half, 0.0, 1.0)
    s = max(0.0, min(0.95, float(soft)))
    k = np.clip((r - s) / max(1e-3, 1.0 - s), 0.0, 1.0)
    if int(mode) == 1:                       # linear
        body = 1.0 - k
    elif int(mode) == 2:                      # power
        body = (1.0 - k) ** max(0.01, float(exponent))
    elif int(mode) == 3:                      # inverse square
        body = 1.0 / (1.0 + max(0.05, float(exponent)) * r * r)
    elif int(mode) == 4:                      # none: a hard edge
        body = np.clip(1.0 - r * 40.0, 0.0, 1.0)
    else:                                     # smooth (the default)
        body = (1.0 - k) * (1.0 - k)
    rgba = np.zeros((size, size, 4))
    edge = np.asarray(outer, np.float64)
    for i in range(3):
        rgba[..., i] = 1.0 + (edge[i] - 1.0) * (1.0 - body)
    rgba[..., 3] = body
    return _bytes(rgba)
