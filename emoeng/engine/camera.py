"""Camera rig: the transform, the frustum and the effects."""

import math

import numpy as np

from .renderer import look_at, perspective


def normalize(v):
    v = np.asarray(v, np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def wrap_angle(a):
    """Wrap an angle to [-pi, pi) so easing goes short."""
    return (float(a) + math.pi) % (2.0 * math.pi) - math.pi


def ease(current, target, dt, damping=0.0):
    """Exponential smoothing toward `target`."""
    if not dt or not damping or damping <= 0.0:
        return float(target)
    k = 1.0 - math.exp(-float(damping) * float(dt))
    return float(current) + (float(target) - float(current)) * k


def ease_angle(current, target, dt, damping=0.0):
    """`ease()` for an angle: always turns the short way round."""
    if not dt or not damping or damping <= 0.0:
        return float(target)
    k = 1.0 - math.exp(-float(damping) * float(dt))
    return float(current) + wrap_angle(target - current) * k


def wish(yaw, right, fwd):
    """World (x, z) for WASD input at `yaw`."""
    sy, cy = math.sin(yaw), math.cos(yaw)
    return (fwd * sy - right * cy, fwd * cy + right * sy)


def point_of(target):
    """(x, y, z) of a point, or anything with `pos`."""
    return getattr(target, "pos", target)


class Camera:
    """Yaw 0 looks down +Z; positive pitch looks up."""

    def __init__(self, eye=(0.0, 2.0, 8.0), yaw=0.0, pitch=0.0,
                 fov=68.0, near=0.05, far=800.0, roll=0.0, viewport=None,
                 name=None):
        self.name = None if name is None else str(name)
        self.eye = [float(c) for c in eye]
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.fov = float(fov)
        self.near = float(near)
        self.far = float(far)
        self.roll = float(roll)
        # a pixel or 0..1 rect; None fills it
        self.viewport = viewport
        self.damping = 0.0            # follow()/aim() rate, 1/s
        self.wanted = None            # (yaw, pitch) the look eases toward
        # the rate `wanted` asked for, so damping persists
        self.wanted_rate = None
        self.follow_target = None     # (x, y, z) the eye eases toward
        self.follow_offset = (0.0, 0.0, 0.0)
        self.shake_scale = 0.09       # metres of travel per unit of amount
        self.shake_roll = 0.05        # radians of tilt per unit of amount
        self.shake_freq = 14.0        # wobbles per second
        self.shake_amount = 0.0       # current strength, 0 when still
        self.shake_duration = 0.0
        self.shake_time = 0.0
        self._phase = 0.0
        self.offset = [0.0, 0.0, 0.0]  # world-space shake, view_eye() only
        self.offset_roll = 0.0

    def copy(self, **overrides):
        """A second camera with the same settings (a mirror view)."""
        kw = dict(eye=list(self.eye), yaw=self.yaw, pitch=self.pitch,
                  fov=self.fov, near=self.near, far=self.far,
                  roll=self.roll, viewport=self.viewport)
        kw.update(overrides)
        return Camera(**kw)

    def as_dict(self):
        """Plain values, handy for save files and the debug overlay."""
        return {"eye": [round(float(c), 3) for c in self.eye],
                "yaw": round(self.yaw, 4), "pitch": round(self.pitch, 4),
                "roll": round(self.roll, 4), "fov": round(self.fov, 2),
                "near": self.near, "far": self.far}

    def forward(self):
        cp = math.cos(self.pitch)
        return np.array([math.sin(self.yaw) * cp, math.sin(self.pitch),
                         math.cos(self.yaw) * cp], np.float64)

    def side(self):
        """World direction that points to the right of the screen."""
        return np.array([-math.cos(self.yaw), 0.0, math.sin(self.yaw)],
                        np.float64)

    def up(self):
        """Screen-up in world space, agreeing with `look_at` (roll-free;"""
        return np.cross(self.side(), self.forward())

    def clamp_pitch(self, limit=1.5):
        self.pitch = max(-limit, min(limit, self.pitch))

    def view_eye(self):
        """`eye` plus the live shake offset the frame renders with."""
        return [self.eye[i] + self.offset[i] for i in range(3)]

    def view_roll(self):
        return self.roll + self.offset_roll

    def view_yaw(self):
        return self.yaw

    def view_pitch(self):
        return self.pitch

    def shake(self, amount=1.0, duration=0.35, freq=None, scale=None,
              roll=None):
        """Rattle the camera."""
        amount = max(0.0, float(amount))
        if amount <= 0.0:
            self.stop_shake()
            return self.shake_amount
        if freq is not None:
            self.shake_freq = max(0.1, float(freq))
        if scale is not None:
            self.shake_scale = float(scale)
        if roll is not None:
            self.shake_roll = float(roll)
        duration = max(0.02, float(duration))
        self.shake_amount = max(self.shake_amount, amount)
        self.shake_duration = max(self.shake_time, duration)
        self.shake_time = self.shake_duration
        return self.shake_amount

    def stop_shake(self):
        """Cut the shake; put the eye back on the rig."""
        self.shake_amount = 0.0
        self.shake_time = 0.0
        self.shake_duration = 0.0
        self.offset = [0.0, 0.0, 0.0]
        self.offset_roll = 0.0
        return self

    def set_follow(self, target=None, offset=None, damping=None):
        """Follow something every frame: `update(dt)` closes the gap."""
        self.follow_target = target
        if offset is not None:
            self.follow_offset = tuple(float(c) for c in offset)
        if damping is not None:
            self.damping = max(0.0, float(damping))
        return self

    def follow(self, target, dt=0.0, damping=None, offset=None, snap=False):
        """Ease the eye toward `target` plus `offset`."""
        off = self.follow_offset if offset is None else offset
        src = point_of(target)
        want = [float(src[i]) + float(off[i]) for i in range(3)]
        rate = self.damping if damping is None else damping
        if snap:
            rate = 0.0
        self.eye = [ease(self.eye[i], want[i], dt, rate) for i in range(3)]
        return self.eye

    def aim(self, yaw=None, pitch=None, dt=0.0, damping=None, limit=1.45,
            snap=False):
        """Look at (yaw, pitch), eased when `damping` is set."""
        rate = self.damping if damping is None else float(damping)
        base = self.wanted if self.wanted is not None \
            else (self.yaw, self.pitch)
        want = (base[0] if yaw is None else float(yaw),
                base[1] if pitch is None else
                max(-limit, min(limit, float(pitch))))
        self.wanted = want
        if snap or dt <= 0.0 or rate <= 0.0:
            if yaw is not None:
                self.yaw = want[0]
            if pitch is not None:
                self.pitch = want[1]
            self.wanted = (self.yaw, self.pitch)
            self.wanted_rate = None
            return (self.yaw, self.pitch)
        self.wanted_rate = rate
        if yaw is not None:
            self.yaw = ease_angle(self.yaw, want[0], dt, rate)
        if pitch is not None:
            self.pitch = ease(self.pitch, want[1], dt, rate)
        return (self.yaw, self.pitch)

    def look_at_point(self, target, dt=0.0, damping=None, offset=None,
                      limit=1.45):
        """Point the camera at a world point."""
        point = np.asarray(point_of(target), np.float64)
        if offset is not None:
            point = point + np.asarray(offset, np.float64)
        eye = np.asarray(self.view_eye(), np.float64)
        d = normalize(point - eye)
        if math.hypot(float(d[0]), float(d[2])) < 1e-9:
            yaw = self.yaw          # straight up or down: do not spin
        else:
            yaw = math.atan2(float(d[0]), float(d[2]))
        pitch = math.asin(max(-1.0, min(1.0, float(d[1]))))
        return self.aim(yaw, pitch, dt, damping, limit)

    def matrices(self, size, near=None, far=None):
        w, h = max(2, int(size[0])), max(2, int(size[1]))
        proj = perspective(math.radians(self.fov), w / h,
                           self.near if near is None else near,
                           self.far if far is None else far)
        view = look_at(np.asarray(self.view_eye(), np.float64), self.yaw,
                       self.pitch, self.view_roll())
        return proj, view

    def mvp(self, size):
        proj, view = self.matrices(size)
        return proj @ view

    def project(self, point, size):
        """Model point to (x, y, depth) pixels, or None."""
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
        """Orbit the eye on a sphere around a target."""
        cp = math.cos(pitch)
        self.eye = [target[0] + math.sin(yaw) * cp * dist,
                    target[1] + math.sin(pitch) * dist,
                    target[2] + math.cos(yaw) * cp * dist]
        self.yaw = yaw + math.pi
        self.pitch = -pitch
        self.wanted = (self.yaw, self.pitch)
        self.clamp_pitch()

    def update(self, dt):
        """Advance shake and easing. Call once per frame, before rendering."""
        dt = max(0.0, float(dt))
        self._phase += dt
        if self.shake_time > 0.0:
            self.shake_time = max(0.0, self.shake_time - dt)
            e = self.shake_time / max(self.shake_duration, 1e-6)
            if self.shake_time <= 0.0:
                self.stop_shake()
            else:
                p = 2.0 * math.pi * self.shake_freq * self._phase
                n = (math.sin(p),
                     math.sin(p * 1.31 + 1.7),
                     math.sin(p * 0.73 + 4.1))
                amp = self.shake_amount * self.shake_scale * e
                s, u, f = self.side(), self.up(), self.forward()
                self.offset = [s[0] * n[0] * amp + u[0] * n[1] * amp +
                               f[0] * n[2] * amp * 0.5,
                               s[1] * n[0] * amp + u[1] * n[1] * amp +
                               f[1] * n[2] * amp * 0.5,
                               s[2] * n[0] * amp + u[2] * n[1] * amp +
                               f[2] * n[2] * amp * 0.5]
                self.offset_roll = (math.sin(p * 1.13 + 2.3) *
                                    self.shake_amount * self.shake_roll * e)
        rate = max(self.damping, self.wanted_rate or 0.0)
        if self.wanted is not None and dt > 0.0 and rate > 0.0:
            self.yaw = ease_angle(self.yaw, self.wanted[0], dt, rate)
            self.pitch = ease(self.pitch, self.wanted[1], dt, rate)
        if self.follow_target is not None and dt > 0.0:
            self.follow(self.follow_target, dt)
        return self


class Camera2D:
    """An orthographic rig for 2D and UI scenes."""

    projection = "ortho"

    def __init__(self, size=(640, 360), zoom=1.0, center=None,
                 viewport=None, name=None):
        self.name = None if name is None else str(name)
        self.size = [max(2, int(size[0])), max(2, int(size[1]))]
        self.zoom = float(zoom) or 1.0
        # `zoom_by()` stops world_size refitting the default rig
        self.autofit = True
        self.center = None if center is None else [float(c) for c in center]
        self.viewport = viewport
        # a shake in screen pixels (folds into center when rendering)
        self.shake_amount = 0.0
        self.shake_time = 0.0
        self.shake_duration = 0.0
        self.shake_freq = 18.0
        self.shake_scale = 6.0          # pixels of travel per unit amount
        self.offset = [0.0, 0.0]
        self._phase = 0.0

    def resize(self, size):
        self.size = [max(2, int(size[0])), max(2, int(size[1]))]
        return self

    def view_size(self):
        """The world-pixel rectangle the frame shows at this zoom."""
        return (self.size[0] / self.zoom, self.size[1] / self.zoom)

    def set_center(self, center=None, x=None, y=None):
        if center is not None:
            self.center = [float(center[0]), float(center[1])]
        else:
            cur = list(self.anchor_center())
            if x is not None:
                cur[0] = float(x)
            if y is not None:
                cur[1] = float(y)
            self.center = cur
        return self.center

    def zoom_by(self, steps, lo=0.1, hi=16.0):
        self.zoom = max(lo, min(hi, self.zoom * (1.25 ** steps)))
        self.autofit = False
        return self.zoom

    def anchor_center(self):
        """Fallback look target when no center was set."""
        if self.center is not None:
            return self.center
        return [self.size[0] / 2.0, self.size[1] / 2.0]

    def to_world(self, pixel):
        """Screen pixel -> world pixel, useful for mouse picking."""
        vw, vh = self.view_size()
        c = self.anchor_center()
        x0, y0 = c[0] - vw / 2.0, c[1] - vh / 2.0
        return (x0 + pixel[0] / self.zoom, y0 + pixel[1] / self.zoom)

    def ortho_box(self):
        """(left, right, bottom, top, near, far) for `renderer.orthographic`,"""
        vw, vh = self.view_size()
        c = self.anchor_center()
        x0 = c[0] + self.offset[0] - vw / 2.0
        y0 = c[1] + self.offset[1] - vh / 2.0
        return (x0, x0 + vw, y0 + vh, y0, -1000.0, 1000.0)

    # flat equivalents of the 3D camera probes
    def view_eye(self):
        c = self.anchor_center()
        return [c[0], c[1], 0.0]

    def view_yaw(self):
        return 0.0

    def view_pitch(self):
        return 0.0

    def view_roll(self):
        return 0.0

    def shake(self, amount=1.0, duration=0.3, freq=None, scale=None,
              roll=None):
        """Rattle the frame; `roll` is accepted and ignored so one"""
        amount = max(0.0, float(amount))
        if amount <= 0.0:
            return self.stop_shake()
        if freq is not None:
            self.shake_freq = max(0.1, float(freq))
        if scale is not None:
            self.shake_scale = float(scale)
        duration = max(0.02, float(duration))
        self.shake_amount = max(self.shake_amount, amount)
        self.shake_duration = max(self.shake_time, duration)
        self.shake_time = self.shake_duration
        return self.shake_amount

    def stop_shake(self):
        self.shake_amount = self.shake_time = self.shake_duration = 0.0
        self.offset = [0.0, 0.0]
        return self

    def update(self, dt):
        dt = max(0.0, float(dt))
        self._phase += dt
        if self.shake_time > 0.0:
            self.shake_time = max(0.0, self.shake_time - dt)
            e = self.shake_time / max(self.shake_duration, 1e-6)
            if self.shake_time <= 0.0:
                return self.stop_shake()
            p = 2.0 * math.pi * self.shake_freq * self._phase
            amp = self.shake_amount * self.shake_scale * e
            self.offset = [math.sin(p) * amp, math.sin(p * 1.7 + 1.3) * amp]
        else:
            self.offset = [0.0, 0.0]
        return self


class CameraHost:
    """Mixin: one Camera behind `eye`, `yaw` and `pitch`."""

    def init_camera(self, **kw):
        self.camera = Camera(**kw)
        return self.camera

    @property
    def eye(self):
        return self.camera.eye

    @eye.setter
    def eye(self, value):
        self.camera.eye = [float(c) for c in value]

    @property
    def yaw(self):
        return self.camera.yaw

    @yaw.setter
    def yaw(self, value):
        self.camera.yaw = float(value)
        if self.camera.wanted is not None:
            self.camera.wanted = (self.camera.yaw, self.camera.wanted[1])

    @property
    def pitch(self):
        return self.camera.pitch

    @pitch.setter
    def pitch(self, value):
        self.camera.pitch = float(value)
        if self.camera.wanted is not None:
            self.camera.wanted = (self.camera.wanted[0], self.camera.pitch)

    def shake(self, amount=1.0, duration=0.35, freq=None, scale=None,
              roll=None):
        """Rattle the camera; safe to spam from an impact handler."""
        return self.camera.shake(amount, duration, freq, scale, roll)

    def set_roll(self, roll):
        """Tilt the horizon (radians). Scenes normally use `scene.roll`."""
        self.camera.roll = float(roll)
        return self.camera.roll

    def set_viewport(self, viewport):
        """Limit the view to a rect of the render target."""
        self.camera.viewport = None if viewport is None else \
            tuple(float(c) for c in viewport)
        return self.camera.viewport

    def sync_camera(self, scene, dt):
        """Copy the scene's camera knobs on, then tick."""
        cam = self.camera
        if scene is not None:
            cam.fov = float(getattr(scene, "fov", cam.fov))
            cam.near = float(getattr(scene, "near", cam.near))
            cam.far = float(getattr(scene, "far", cam.far))
            cam.roll = float(getattr(scene, "roll", cam.roll))
            vp = getattr(scene, "viewport", None)
            if vp is not None:
                cam.viewport = tuple(float(c) for c in vp)
        cam.update(dt)
        return cam


class OrbitCamera:
    """Turntable rig for the model editor: target, distance, yaw, pitch."""

    def __init__(self, target=(0.0, 0.5, 0.0), dist=6.0, yaw=0.6,
                 pitch=0.35, fov=55.0, near=0.05, far=800.0):
        self.target = list(target)
        self.dist = float(dist)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.fov = float(fov)
        self.near = float(near)
        self.far = float(far)

    def camera(self):
        cam = Camera(fov=self.fov, near=self.near, far=self.far)
        cam.orbit(self.target, self.dist, self.yaw, self.pitch)
        return cam

    def orbit(self, dx, dy):
        self.yaw -= dx * 0.008
        self.pitch = max(-1.45, min(1.45, self.pitch + dy * 0.008))

    def zoom(self, steps):
        self.dist = max(0.6, min(120.0, self.dist * (0.88 ** steps)))

    def pan(self, dx, dy, size):
        """Pan the target one pixel per step of drag."""
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
