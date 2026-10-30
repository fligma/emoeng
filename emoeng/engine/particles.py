"""Particles: a CPU pool of points, drawn as one mesh per emitter."""

import math

import numpy as np

from . import colors, meshes

# the most points one emitter may ever hold
MAX_LIVE = 4096
# one frame's step, however long the frame really was: a tab that
# slept for a minute must not spend a minute of falling here
MAX_DT = 0.1

# the corners of a quad, bl, br, tr, tl, then two triangles
_SIGNS = np.array(((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)))
_TRIS = np.array((0, 1, 2, 0, 2, 3))
# the whole sheet across those corners, once flipped the way `quad2d`
# flips it: `texture()` turns the array upside down, so v = 1 is the top
_UV_UP = np.array(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)))
_UV_DOWN = np.array(((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)))


def _vec(value, fallback):
    """A vector knob as three floats, short ones padded with zeros."""
    row = list(value if value is not None else fallback)
    if not row:
        row = list(fallback)
    got = [float(c) for c in row[:3]]
    while len(got) < 3:
        got.append(0.0)
    return np.asarray(got, np.float64)


def _unit(value, fallback=(0.0, 1.0, 0.0)):
    """A direction knob as one unit vector, or the fallback's own."""
    got = _vec(value, fallback)
    n = float(np.linalg.norm(got))
    return got / n if n > 1e-6 else _vec(fallback, fallback)


def _perp(d):
    """Two unit vectors at right angles to `d`, and to each other."""
    hint = np.array((0.0, 1.0, 0.0)) if abs(float(d[1])) > 0.9 \
        else np.array((1.0, 0.0, 0.0))
    u = np.cross(d, hint)
    u /= max(1e-9, float(np.linalg.norm(u)))
    v = np.cross(d, u)
    return u, v / max(1e-9, float(np.linalg.norm(v)))


class Sim:
    """Points in a fixed pool, kept packed in the first `n` slots.

    Nothing is ever allocated while the game runs: `cap` slots hold the
    emitter's whole life, and a full pool recycles its oldest points, so
    the mesh drawn from it always has the same shape.
    """

    def __init__(self, cap=256):
        self.cap = 0
        self.n = 0
        self.pos = self.vel = np.zeros((0, 3), np.float64)
        self.age = self.life = self.rand = np.zeros(0, np.float64)
        self.grow(cap)

    def grow(self, cap):
        """Re-pool for a new size, keeping what is alive."""
        want = int(max(1, min(int(cap or 1), MAX_LIVE)))
        if want == self.cap:
            return self
        old = min(self.n, want)
        pos = np.zeros((want, 3), np.float64)
        vel = np.zeros((want, 3), np.float64)
        age = np.zeros(want, np.float64)
        life = np.ones(want, np.float64)
        rand = np.zeros(want, np.float64)
        for row, dst in ((self.pos, pos), (self.vel, vel), (self.age, age),
                         (self.life, life), (self.rand, rand)):
            take = min(old, len(row), len(dst))
            if take:
                dst[:take] = row[:take]
        self.cap, self.pos, self.vel = want, pos, vel
        self.age, self.life, self.rand = age, life, rand
        self.n = min(old, want)
        return self

    # -- filling ------------------------------------------------------------
    def _reserve(self, want):
        """Room for `want` slots at the end, oldest points dropped first."""
        if self.n + want > self.cap:
            self.cut(self.n + want - self.cap)
        at = self.n
        self.n += want
        return at

    def cut(self, count):
        """Drop the `count` oldest points, keeping the pool packed."""
        count = int(max(0, min(count, self.n)))
        if not count:
            return self
        left = self.n - count
        for row in (self.pos, self.vel, self.age, self.life, self.rand):
            row[:left] = row[count:self.n]
        self.n = left
        return self

    def spawn(self, count, origin, direction, spread, speed, lifetime,
              rng=None, jitter=0.0, flat=False):
        """Aim `count` points away from `origin`; how many got in."""
        count = int(count)
        if count <= 0 or self.cap <= 0:
            return 0
        count = min(count, self.cap)
        rng = rng if rng is not None else np.random.default_rng()
        at = self._reserve(count)
        sl = slice(at, self.n)
        dice = rng.random((count, 4))
        d = _unit(direction)
        aim = float(max(0.0, min(math.pi / 2.0, float(spread or 0.0))))
        if flat:
            # a fan in the plane: the arc either side of the direction
            base = math.atan2(float(d[1]), float(d[0]))
            ang = base + aim * (2.0 * dice[:, 0] - 1.0)
            dirs = np.stack([np.cos(ang), np.sin(ang),
                             np.zeros(count)], axis=1)
        else:
            # a cone: the cosine walks evenly between the walls
            u = 1.0 - dice[:, 0] * (1.0 - math.cos(aim))
            phi = 2.0 * math.pi * dice[:, 1]
            sin_t = np.sqrt(np.clip(1.0 - u * u, 0.0, 1.0))
            side, up = _perp(d)
            dirs = (d * u[:, None]
                    + side * (sin_t * np.cos(phi))[:, None]
                    + up * (sin_t * np.sin(phi))[:, None])
        moving = max(0.0, float(speed or 0.0))
        self.vel[sl] = dirs * (moving * (0.7 + 0.6 * dice[:, 2]))[:, None]
        start = _vec(origin, (0.0, 0.0, 0.0))
        spot = np.repeat(start[None, :], count, axis=0)
        kick = max(0.0, float(jitter or 0.0))
        if kick:
            shake = rng.standard_normal((count, 3)) * kick
            if flat:
                shake[:, 2] = 0.0     # a flat world keeps its one sheet
            spot = spot + shake
        self.pos[sl] = spot
        self.age[sl] = 0.0
        self.life[sl] = max(0.02, float(lifetime or 1.0)) * \
            (0.75 + 0.5 * rng.random(count))
        self.rand[sl] = dice[:, 3]
        return count

    # -- running ------------------------------------------------------------
    def step(self, dt, gravity=None, drag=0.0, flat=False):
        """Age, push and move every point; returns how many are left."""
        dt = max(0.0, min(float(dt or 0.0), MAX_DT))
        if self.n == 0 or dt <= 0.0:
            return self.n
        live = slice(0, self.n)
        if gravity is not None:
            g = _vec(gravity, (0.0, 0.0, 0.0))
            if flat:
                g[2] = 0.0
            if float(np.linalg.norm(g)):
                self.vel[live] += (g * dt)[None, :]
        rub = max(0.0, float(drag or 0.0))
        if rub:
            self.vel[live] *= max(0.0, 1.0 - rub * dt)
        self.pos[live] += self.vel[live] * dt
        self.age[live] += dt
        self.cull()
        return self.n

    def cull(self):
        """Take out the points that spent their life."""
        if self.n == 0:
            return self
        keep = self.age[:self.n] < self.life[:self.n]
        left = int(keep.sum())
        if left == self.n:
            return self
        for row in (self.pos, self.vel, self.age, self.life, self.rand):
            row[:left] = row[:self.n][keep]
        self.n = left
        return self

    def reset(self):
        """Empty the pool; the mesh keeps its shape and draws nothing."""
        self.n = 0
        return self

    def playing(self):
        """Is anything still in the air?"""
        return self.n > 0


def _shade(sim, size, end_size, color, end_color, alpha=1.0):
    """(half, rgb, a) per slot: a spent slot is nothing at all."""
    cap, n = sim.cap, sim.n
    t = np.zeros(cap, np.float64)
    if n:
        t[:n] = np.clip(sim.age[:n] / np.maximum(sim.life[:n], 1e-6),
                        0.0, 1.0)
    half = np.zeros(cap, np.float64)
    col = np.zeros((cap, 3), np.float64)
    a = np.zeros(cap, np.float64)
    if n:
        live = t[:n]
        start = np.asarray(colors.rgb(color, (1.0, 1.0, 1.0)), np.float64)
        stop = start if end_color is None else np.asarray(
            colors.rgb(end_color, (1.0, 1.0, 1.0)), np.float64)
        col[:n] = start + (stop - start) * live[:, None]
        wide = float(size) + (float(end_size) - float(size)) * live
        # a point fades in over its first breath and out as it dies
        a[:n] = float(alpha) * np.clip(live / 0.08, 0.0, 1.0) * \
            (1.0 - live ** 3)
        half[:n] = 0.5 * np.maximum(wide, 0.0) * (0.75 + 0.5 *
                                                  sim.rand[:n])
    return half, col, a


def _place(sim, origin, turn, scale, local, flat=False):
    """Every slot's centre: the pool's own, or lifted into the world."""
    pos = sim.pos
    if not local:
        return pos
    out = pos.copy()
    if turn:
        c, s = math.cos(turn), math.sin(turn)
        if flat:
            x, y = pos[:, 0], pos[:, 1]
            out[:, 0], out[:, 1] = x * c - y * s, x * s + y * c
        else:
            x, z = pos[:, 0], pos[:, 2]
            out[:, 0], out[:, 2] = x * c + z * s, z * c - x * s
    out *= float(scale or 1.0)
    return out + _vec(origin, (0.0, 0.0, 0.0))[None, :]


def _mesh(centre, right, up, half, nrm, col, a, uv):
    """`len(half)` quads as one MeshData, dead slots collapsed to nothing."""
    cap = len(half)
    edge = right[None, None, :] * _SIGNS[:, 0, None] + \
        up[None, None, :] * _SIGNS[:, 1, None]
    pos = centre[:, None, :] + edge[None, :, :] * half[:, None, None]
    m = meshes.MeshData()
    m.pos = pos.reshape(cap * 4, 3).tolist()
    m.nrm = np.repeat(nrm[None, :], cap * 4, axis=0).tolist()
    m.uv = np.tile(uv, (cap, 1)).tolist()
    m.col = np.concatenate(
        [np.repeat(col[:, None, :], 4, axis=1),
         a[:, None, None].repeat(4, axis=1)], axis=2
    ).reshape(cap * 4, 4).tolist()
    m.idx = (np.arange(cap, dtype=np.int64)[:, None] * 4
             + _TRIS[None, :]).ravel().tolist()
    return m


def pool3d(sim, size=0.12, end_size=0.0, color=(1.0, 1.0, 1.0),
           end_color=None, alpha=1.0, view_yaw=0.0, origin=(0.0, 0.0, 0.0),
           yaw=0.0, node_scale=1.0, local=False):
    """Every point as a quad turned to face the view, in world metres."""
    half, col, a = _shade(sim, size, end_size, color, end_color, alpha)
    centre = _place(sim, origin, yaw, node_scale, local)
    c, s = math.cos(view_yaw), math.sin(view_yaw)
    return _mesh(centre, np.array((c, 0.0, -s)), np.array((0.0, 1.0, 0.0)),
                 half, np.array((s, 0.0, c)), col, a, _UV_UP)


def pool2d(sim, size=6.0, end_size=0.0, color=(1.0, 1.0, 1.0),
           end_color=None, alpha=1.0, origin=(0.0, 0.0), rot=0.0,
           node_scale=1.0, local=False):
    """Every point as a flat quad, in a 2D scene's world pixels."""
    half, col, a = _shade(sim, size, end_size, color, end_color, alpha)
    centre = _place(sim, origin, rot, node_scale, local, flat=True)
    # the flat world's y grows downward, as `quad2d` writes it
    return _mesh(centre, np.array((1.0, 0.0, 0.0)),
                 np.array((0.0, 1.0, 0.0)), half,
                 np.array((0.0, 0.0, 1.0)), col, a, _UV_DOWN)
