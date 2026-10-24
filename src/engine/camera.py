"""Cameras and the screen maths shared by the renderer, editor and games.

A Camera is the same eye/yaw/pitch rig the renderer consumes, plus
`project()` and `ray()` so tools can turn model-space points into pixels
and mouse clicks back into world rays (vertex picking, gizmos, HUD).
"""

import math

import numpy as np

from .renderer import look_at, perspective


def normalize(v):
    v = np.asarray(v, np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def wish(yaw, right, fwd):
    """World (x, z) for WASD input at `yaw`, one unit per unit of speed.

    Yaw 0 looks down +Z and `look_at` builds the view basis, so the world
    direction of screen-right is (-cos yaw, sin yaw) and a right push
    subtracts it. Game loops, the editor preview and scenes that walk
    their own collision body all come through here, so A/D cannot end up
    disagreeing with the mouse again.
    """
    sy, cy = math.sin(yaw), math.cos(yaw)
    return (fwd * sy - right * cy, fwd * cy + right * sy)


class Camera:
    """Yaw 0 looks down +Z, positive pitch looks up."""

    def __init__(self, eye=(0.0, 2.0, 8.0), yaw=0.0, pitch=0.0,
                 fov=68.0, near=0.05, far=800.0):
        self.eye = [float(c) for c in eye]
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.fov = float(fov)
        self.near = float(near)
        self.far = float(far)

    # ------------------------------------------------------------- vectors
    def forward(self):
        cp = math.cos(self.pitch)
        return np.array([math.sin(self.yaw) * cp, math.sin(self.pitch),
                         math.cos(self.yaw) * cp], np.float64)

    def side(self):
        """World direction that points to the right of the screen.

        Has to agree with `renderer.look_at`, which builds the view
        basis as (side, up, -forward): a camera looking down +Z keeps
        +X on its left, so screen-right is -X there.
        """
        return np.array([-math.cos(self.yaw), 0.0, math.sin(self.yaw)],
                        np.float64)

    def clamp_pitch(self, limit=1.5):
        self.pitch = max(-limit, min(limit, self.pitch))

    # ------------------------------------------------------------ matrices
    def matrices(self, size, near=None, far=None):
        w, h = max(2, int(size[0])), max(2, int(size[1]))
        proj = perspective(math.radians(self.fov), w / h,
                           self.near if near is None else near,
                           self.far if far is None else far)
        view = look_at(np.asarray(self.eye, np.float64), self.yaw,
                       self.pitch)
        return proj, view

    def mvp(self, size):
        proj, view = self.matrices(size)
        return proj @ view

    # ---------------------------------------------------------- projection
    def project(self, point, size):
        """Model/world point -> (x, y, depth) in pixels, or None when the
        point sits behind the eye."""
        m = self.mvp(size)
        v = m @ np.array([point[0], point[1], point[2], 1.0], np.float64)
        if v[3] <= 1e-4:
            return None
        ndc = v[:3] / v[3]
        w, h = size
        return ((ndc[0] * 0.5 + 0.5) * w,
                (1.0 - (ndc[1] * 0.5 + 0.5)) * h,
                float(v[3]))

    def ray(self, size, pos):
        """Screen pixel -> (origin, unit direction) in world space."""
        w, h = size
        nx = (pos[0] / max(1.0, w)) * 2.0 - 1.0
        ny = 1.0 - (pos[1] / max(1.0, h)) * 2.0
        inv = np.linalg.inv(self.mvp(size))

        def unproject(z):
            v = inv @ np.array([nx, ny, z, 1.0], np.float64)
            return v[:3] / v[3]

        a = unproject(-1.0)
        b = unproject(1.0)
        return a, normalize(b - a)

    def plane_hit(self, size, pos, point, normal):
        """Where the mouse ray crosses a plane through `point`."""
        origin, direction = self.ray(size, pos)
        n = normalize(normal)
        denom = float(np.dot(direction, n))
        if abs(denom) < 1e-6:
            return None
        t = float(np.dot(np.asarray(point, np.float64) - origin, n)) / denom
        if t <= 0.0:
            return None
        return origin + direction * t

    # ------------------------------------------------------------ movement
    def fly(self, fwd=0.0, right=0.0, up=0.0, speed=10.0, dt=0.0):
        f = self.forward()
        s = self.side()
        move = (f * fwd + s * right + np.array([0.0, 1.0, 0.0]) * up)
        if float(np.linalg.norm(move)) > 1e-6:
            move = normalize(move) * speed * dt
            self.eye[0] += move[0]
            self.eye[1] += move[1]
            self.eye[2] += move[2]

    def orbit(self, target, dist, yaw, pitch):
        """Place the eye on a sphere around target and look at it."""
        cp = math.cos(pitch)
        self.eye = [target[0] + math.sin(yaw) * cp * dist,
                    target[1] + math.sin(pitch) * dist,
                    target[2] + math.cos(yaw) * cp * dist]
        self.yaw = yaw + math.pi
        self.pitch = -pitch
        self.clamp_pitch()

    def look_at_point(self, target):
        d = normalize(np.asarray(target, np.float64) -
                      np.asarray(self.eye, np.float64))
        self.yaw = math.atan2(d[0], d[2])
        self.pitch = math.asin(max(-1.0, min(1.0, d[1])))


class OrbitCamera:
    """Turntable rig for the model editor: target, distance, yaw, pitch.
    `camera()` rebuilds the render Camera for the current frame."""

    def __init__(self, target=(0.0, 0.5, 0.0), dist=6.0, yaw=0.6,
                 pitch=0.35, fov=55.0):
        self.target = list(target)
        self.dist = float(dist)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.fov = float(fov)

    def camera(self):
        cam = Camera(fov=self.fov)
        cam.orbit(self.target, self.dist, self.yaw, self.pitch)
        return cam

    def orbit(self, dx, dy):
        self.yaw -= dx * 0.008
        self.pitch = max(-1.45, min(1.45, self.pitch + dy * 0.008))

    def zoom(self, steps):
        self.dist = max(0.6, min(120.0, self.dist * (0.88 ** steps)))

    def pan(self, dx, dy, size):
        """Slide the target in the camera plane, roughly one pixel per
        unit at the target's depth."""
        cam = self.camera()
        scale = self.dist * 0.0016
        target = np.asarray(self.target, np.float64)
        target = target - cam.side() * dx * scale
        target = target + np.array([0.0, 1.0, 0.0]) * dy * scale
        self.target = [float(c) for c in target]

    def frame(self, bounds, pad=1.9):
        """Point the turntable at an object's bounds."""
        if bounds is None:
            return
        lo, hi = bounds
        centre = [(lo[i] + hi[i]) * 0.5 for i in range(3)]
        radius = max(0.4, float(np.linalg.norm(
            np.asarray(hi, np.float64) - np.asarray(lo, np.float64))) * 0.5)
        self.target = centre
        self.dist = radius * pad
