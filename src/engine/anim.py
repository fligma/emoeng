"""Small animation kit: easing, smoothed values, camera shake and
frame-based sprite playback. Enough to keep a PS2-style game moving
without pulling in a tween library.
"""

import math

import pygame


# ----------------------------------------------------------------- easing
def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value


def clamp01(value):
    return clamp(value, 0.0, 1.0)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    t = clamp01(t)
    return t * t * (3.0 - 2.0 * t)


def ease_in(t):
    return clamp01(t) ** 2


def ease_out(t):
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 2


def ease_in_out(t):
    return smoothstep(t)


def approach(current, target, rate, dt):
    """Exponential smoothing that is stable at any frame rate."""
    return current + (target - current) * (1.0 - math.exp(-rate * dt))


def move_towards(current, target, max_delta):
    if abs(target - current) <= max_delta:
        return target
    return current + math.copysign(max_delta, target - current)


class Smoothed:
    """A float that chases a target, with an optional snap threshold."""

    def __init__(self, value=0.0, rate=10.0):
        self.value = float(value)
        self.target = float(value)
        self.rate = float(rate)

    def update(self, dt):
        self.value = approach(self.value, self.target, self.rate, dt)
        return self.value

    def snap(self, value):
        self.value = self.target = float(value)


class Shake:
    """Decaying camera/2D shake; `offset()` returns (dx, dy)."""

    def __init__(self, amount=0.0, decay=3.5, seed=1):
        self.amount = float(amount)
        self.decay = float(decay)
        self.seed = int(seed)
        self.t = 0.0

    def kick(self, amount):
        self.amount = max(self.amount, float(amount))

    def update(self, dt):
        self.t += dt
        self.amount *= math.exp(-self.decay * dt)
        if self.amount < 1e-4:
            self.amount = 0.0

    def offset(self):
        if self.amount <= 0.0:
            return (0.0, 0.0)
        return (math.sin(self.t * 63.1 + self.seed) * self.amount,
                math.sin(self.t * 47.7 + self.seed * 2.3) * self.amount)


class Tween:
    """Linear keyframe tween between two values."""

    def __init__(self, start, end, duration, ease=ease_in_out):
        self.start = start
        self.end = end
        self.duration = max(1e-4, float(duration))
        self.ease = ease
        self.t = 0.0

    def update(self, dt):
        self.t = min(self.duration, self.t + dt)
        return self.value()

    def value(self):
        k = self.ease(self.t / self.duration)
        if isinstance(self.start, (int, float)):
            return lerp(self.start, self.end, k)
        return tuple(lerp(a, b, k) for a, b in zip(self.start, self.end))

    @property
    def done(self):
        return self.t >= self.duration


class FrameAnim:
    """Sprite-sheet playback from a list of surfaces."""

    def __init__(self, frames, fps=12.0, loop=True):
        self.frames = list(frames)
        self.fps = float(fps)
        self.loop = loop
        self.time = 0.0

    def update(self, dt):
        self.time += dt
        if self.loop:
            self.time %= max(1e-4, len(self.frames) / self.fps)

    @property
    def index(self):
        if not self.frames:
            return 0
        i = int(self.time * self.fps)
        return i % len(self.frames) if self.loop else \
            min(i, len(self.frames) - 1)

    @property
    def frame(self):
        return self.frames[self.index] if self.frames else None

    @property
    def done(self):
        return not self.loop and self.time >= len(self.frames) / self.fps


def slice_sheet(sheet, frame_w, frame_h, count=None, row=0):
    """Cut a horizontal sprite sheet into frames."""
    out = []
    cols = sheet.get_width() // frame_w
    count = cols if count is None else min(count, cols)
    for i in range(count):
        frame = pygame.Surface((frame_w, frame_h), pygame.SRCALPHA)
        frame.blit(sheet, (0, 0),
                   (i * frame_w, row * frame_h, frame_w, frame_h))
        out.append(frame)
    return out
