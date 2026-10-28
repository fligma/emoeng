"""Lighting for metre and pixel worlds: `Light3D`, `Light2D`."""

import inspect
import math

import numpy as np

from . import colors, meshes, proctex

# shape ids the shader sees; keep in step with renderer.FS
POINT, SPOT, SUN, RADIAL, CONE, RECT, POLY = 0, 1, 2, 3, 4, 5, 6
TUBE, RING, WORLD = 7, 8, 9
SHAPES_3D = {"point": POINT, "spot": SPOT, "sun": SUN, "cone": SPOT,
             "tube": TUBE, "line": TUBE, "strip": TUBE, "neon": TUBE,
             "area": POINT, "omni": POINT}
SHAPES_2D = {"radial": RADIAL, "point": RADIAL, "glow": RADIAL, "circle": RADIAL,
             "cone": CONE, "torch": CONE, "fov": CONE, "spot": CONE,
             "rect": RECT, "box": RECT, "door": RECT, "poly": POLY,
             "strip": RECT, "line": RECT, "bar": RECT, "slit": RECT,
             "ring": RING, "halo": RING, "ping": RING, "shock": RING,
             "world": WORLD, "screen": WORLD, "frame": WORLD, "wash": WORLD,
             "flash": WORLD}
NAME_2D = {RADIAL: "radial", CONE: "cone", RECT: "rect", POLY: "poly",
           RING: "ring", WORLD: "world"}


def _vec(value, count, default):
    """A list of `count` floats, padded or trimmed, or `default`."""
    if value is None:
        return list(default)
    try:
        got = [float(c) for c in value]
    except (TypeError, ValueError):
        return list(default)
    if not got:
        return list(default)
    if len(got) == 1 and count > 1:
        got = got * count
    while len(got) < count:
        got.append(0.0)
    return got[:count]


def _dir3(yaw, pitch=0.0):
    """Unit vector for yaw/pitch, +Z forward."""
    cp = math.cos(pitch)
    return [math.sin(yaw) * cp, math.sin(pitch), math.cos(yaw) * cp]


def norm(vec):
    """A unit-length copy of a vector; zero stays zero."""
    length = math.sqrt(sum(float(c) * float(c) for c in vec))
    if length < 1e-6:
        return [float(c) for c in vec]
    return [float(c) / length for c in vec]


def _noise(t):
    """A cheap -1..1 wiggle from three sines."""
    return (math.sin(t * 6.3) * 0.5 + math.sin(t * 11.7 + 1.3) * 0.3 +
            math.sin(t * 23.1 + 4.1) * 0.2)


# attenuation ids in `u_light_atten[i].x`; keep in step
ATTEN = {"smooth": 0, "linear": 1, "power": 2, "inv": 3, "none": 4}
FLICKER = {"candle": 0, "bulb": 1, "fluorescent": 2, "random": 3}
# light layers are bit masks; `all` is the default
LAYERS = {"all": -1, "world": 1, "prop": 2, "player": 4, "enemy": 8,
          "fx": 16, "ui": 32, "ground": 64, "sky": 128, "water": 256}


def layer_bits(spec):
    """`"player"`, `["player", "fx"]`, `"player|fx"`, 6 or None as an int."""
    if spec is None:
        return LAYERS["all"]
    if isinstance(spec, str):
        out = 0
        for word in spec.replace("|", ",").replace("+", ",").split(","):
            word = word.strip().lower()
            if word in ("all", "*", "-1"):
                return LAYERS["all"]
            out |= LAYERS.get(word, 0)
        return out or LAYERS["all"]
    if isinstance(spec, (list, tuple, set)):
        out = 0
        for entry in spec:
            out |= LAYERS["all"] if str(entry).lower() in ("all", "*") \
                else (layer_bits(entry) if isinstance(entry, str)
                      else int(entry))
        return out or LAYERS["all"]
    return int(spec)


def atten_code(mode):
    """An attenuation name or number as its GPU id."""
    if isinstance(mode, str):
        return ATTEN.get(mode.strip().lower(), 0)
    try:
        return int(mode)
    except (TypeError, ValueError):
        return 0


def atten_value(mode, start, exponent, dist, radius):
    """The falloff curve in Python, mirroring the shader."""
    code = atten_code(mode)
    d = max(0.0, float(dist))
    if radius is None or radius <= 0.0:
        return 1.0 / (1.0 + 0.02 * d * d)
    t = d / float(radius)
    if code == ATTEN["none"]:
        return 1.0 if t <= 1.0 else 0.0
    t = min(t, 1.0)
    s = max(0.0, min(0.95, float(start or 0.0)))
    u = max(0.0, min(1.0, (t - s) / max(1e-3, 1.0 - s)))
    if code == ATTEN["linear"]:
        return 1.0 - u
    if code == ATTEN["power"]:
        return (1.0 - u) ** max(0.01, float(exponent))
    if code == ATTEN["inv"]:
        return 1.0 / (1.0 + max(0.05, float(exponent)) * t * t)
    return (1.0 - u) * (1.0 - u)


def _flicker(style, t, rate, seed):
    """The -1..1 wiggle a flickering light runs on."""
    x = t * rate + seed * 7.13
    code = FLICKER.get(style, 0) if isinstance(style, str) else int(style or 0)
    if code == FLICKER["bulb"]:
        return _noise(x * 0.4) * 0.45
    if code == FLICKER["fluorescent"]:
        n = _noise(x * 2.1)
        return -1.0 if n < -0.72 else n        # the tube drops out
    if code == FLICKER["random"]:
        return math.sin(x * 9.7) * math.cos(x * 2.3)
    return _noise(x)


def point_in_polygon(point, poly):
    """Does a world pixel fall inside a polygon?"""
    if not poly or len(poly) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > y) != (yj > y) and \
                x < (xj - xi) * (y - yi) / max(1e-9, yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def kelvin_rgb(temp):
    """A colour temperature (1000..40000 K) as an approximate rgb, 0..1."""
    t = max(1000.0, min(40000.0, float(temp))) / 100.0
    if t <= 66.0:
        r = 255.0
    else:
        r = 329.698727446 * math.pow(t - 60.0, -0.1332047592)
    if t <= 66.0:
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        g = 288.1221695283 * math.pow(t - 60.0, -0.0755148492)
    if t >= 66.0:
        b = 255.0
    elif t <= 19.0:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10.0) - 305.0447927307
    return tuple(max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b))


def ramp_rgb(stops, x, loop=False):
    """Interpolate `[(position, colour), ...]` at `x`; colours any spelling."""
    pts = [(float(a), colors.rgb(b, (1.0, 1.0, 1.0))) for a, b in stops]
    if not pts:
        return (1.0, 1.0, 1.0)
    x = float(x)
    if loop:
        span = pts[-1][0] - pts[0][0]
        if span > 0.0:
            x = pts[0][0] + (x - pts[0][0]) % span
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (a0, c0), (a1, c1) in zip(pts, pts[1:]):
        if a0 <= x <= a1:
            t = (x - a0) / max(1e-6, a1 - a0)
            return tuple(c0[i] + (c1[i] - c0[i]) * t for i in range(3))
    return pts[-1][1]


def ramp_number(stops, x, loop=False):
    """Interpolate `[(position, number), ...]` at `x`."""
    pts = [(float(a), float(b)) for a, b in stops]
    if not pts:
        return 0.0
    x = float(x)
    if loop:
        span = pts[-1][0] - pts[0][0]
        if span > 0.0:
            x = pts[0][0] + (x - pts[0][0]) % span
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (a0, v0), (a1, v1) in zip(pts, pts[1:]):
        if a0 <= x <= a1:
            t = (x - a0) / max(1e-6, a1 - a0)
            return v0 + (v1 - v0) * t
    return pts[-1][1]


def sun_direction(hour=12.0, tilt=0.25):
    """The direction sunlight travels at `hour` (0..24, 12 = overhead)."""
    a = math.pi * (float(hour) - 6.0) / 12.0
    to_sun = [-math.cos(a), math.sin(a), float(tilt)]
    return [-c for c in norm(to_sun)]


# sky tint by hour: midnight, dawn, noon, dusk
DAY_SKY = [(0.0, "night"), (4.5, "night"), (6.5, "rust"), (9.0, "fog"),
           (13.0, "white"), (17.0, "fog"), (19.0, "orange"),
           (20.5, "night"), (24.0, "night")]


def daylight(hour, sky=DAY_SKY, strength=1.0):
    """Ambient, sun colour, direction and fog for an hour."""
    h = float(hour) % 24.0
    sun_dir = sun_direction(h)
    height = max(0.0, min(1.0, -sun_dir[1] * 2.2 + 0.12))
    tint = ramp_rgb(sky, h, loop=True)
    return {"hour": h,
            "sun_dir": sun_dir,
            "sun_col": tuple(c * height * float(strength) for c in tint),
            "sun_energy": height * float(strength),
            "ambient": tuple(0.05 + 0.28 * height * c for c in tint),
            "fog": colors.mix(colors.rgb("night"), tint, height)[:3]}


def segment(x0, y0, x1, y1):
    """One wall as (x0, y0, x1, y1) world pixels."""
    return (float(x0), float(y0), float(x1), float(y1))


def rect_sides(x, y, w, h):
    """The four sides of a rect as walls."""
    x1, y1 = x + w, y + h
    return [segment(x, y, x1, y), segment(x1, y, x1, y1),
            segment(x1, y1, x, y1), segment(x, y1, x, y)]


def poly_sides(points):
    """The edges of a point list as walls."""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 2:
        return []
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    return [segment(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])]


def blockers_of(items):
    """Flatten whatever a scene calls its walls into wall segments."""
    if callable(items):
        items = items()
    out = []
    for item in items or ():
        if isinstance(item, (list, tuple)) and len(item) == 4 and \
                all(isinstance(c, (int, float)) for c in item):
            out.append(segment(*item))
            continue
        points = getattr(item, "points", None)
        if points:
            out += poly_sides(points)
            continue
        rect = getattr(item, "rect", None)
        if callable(rect):
            rect = rect()
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            out += rect_sides(*rect)
    return out


def _wall_block(walls):
    """Walls as an (N, 4) float block."""
    if isinstance(walls, np.ndarray):
        return walls.reshape(-1, 4) if walls.size % 4 == 0 \
            else np.empty((0, 4))
    try:
        got = np.asarray(walls, np.float64)
    except (TypeError, ValueError):
        return np.empty((0, 4))
    if got.ndim != 2 or got.shape[1] != 4:
        return np.empty((0, 4))
    return got


def _cast(origin, dirs, walls, limit):
    """Distance along many rays to the first wall."""
    count = len(dirs)
    reach = np.full(count, float(limit)) if np.isscalar(limit) else \
        np.asarray(limit, np.float64).reshape(count)
    if not count or not len(walls):
        return reach
    dx = dirs[:, 0][:, None]
    dy = dirs[:, 1][:, None]
    x0 = walls[None, :, 0]
    y0 = walls[None, :, 1]
    ex = walls[None, :, 2] - x0
    ey = walls[None, :, 3] - y0
    denom = dx * ey - dy * ex
    # parallel rays never cross a wall; the mask drops them
    flat = np.abs(denom) < 1e-12
    inv = 1.0 / np.where(flat, 1.0, denom)
    wx = x0 - float(origin[0])
    wy = y0 - float(origin[1])
    t = (wx * ey - wy * ex) * inv
    u = (wx * dy - wy * dx) * inv
    ok = (~flat) & (t >= 0.0) & (t <= reach[:, None]) & \
        (u >= 0.0) & (u <= 1.0)
    if not ok.any():
        return reach
    # a miss falls back to the ray's own reach
    return np.where(ok, t, reach[:, None]).min(axis=1)


def ray_hit(origin, direction, walls, limit):
    """How far a 2D ray travels before hitting a wall."""
    dirs = np.array([[float(direction[0]), float(direction[1])]])
    return float(_cast(origin, dirs, _wall_block(walls), float(limit))[0])


def _wrap(a):
    """Fold an angle into -pi..pi."""
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def visibility(origin, walls, radius, center=None, spread=None, samples=48,
               epsilon=0.0009):
    """The polygon a 2D light reaches, occluded by walls."""
    origin = (float(origin[0]), float(origin[1]))
    radius = max(1e-3, float(radius))
    block = _wall_block(walls)
    cone = spread is not None
    angles = []
    if cone:
        spread = max(1e-3, min(2.0 * math.pi, float(spread)))
        steps = max(2, int(samples))
        for i in range(steps + 1):
            angles.append(center - spread / 2.0 + spread * i / steps)
    else:
        steps = max(12, int(samples))
        angles = [2.0 * math.pi * i / steps for i in range(steps)]
    for x0, y0, x1, y1 in block:
        for px, py in ((x0, y0), (x1, y1)):
            a = math.atan2(py - origin[1], px - origin[0])
            if not cone or abs(_wrap(a - center)) <= spread / 2.0:
                angles += [a - epsilon, a, a + epsilon]
    angles = sorted(set(angles), key=lambda v: v if not cone
                    else _wrap(v - center))
    ang = np.asarray(angles, np.float64)
    dirs = np.stack((np.cos(ang), np.sin(ang)), axis=1)
    hits = _cast(origin, dirs, block, radius)
    return [(origin[0] + dirs[i, 0] * hits[i],
             origin[1] + dirs[i, 1] * hits[i]) for i in range(len(ang))]


def clip_walls(origin, points, walls, samples=8, radius=0.0):
    """Pull an outline's edges in to whatever walls they cross."""
    if not walls or not points:
        return list(points)
    block = _wall_block(walls)
    if not len(block):
        return list(points)
    step = max(1.0, (radius or 200.0) / max(2, int(samples)))
    spots = []
    for a, b in zip(points, points[1:] + points[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = max(2, int(math.hypot(dx, dy) / step))
        for i in range(n):
            t = i / float(n)
            spots.append((a[0] + dx * t, a[1] + dy * t))
    ox, oy = float(origin[0]), float(origin[1])
    local = np.asarray(spots, np.float64) - (ox, oy)
    span = np.hypot(local[:, 0], local[:, 1])
    # a sample on the light itself has no direction
    ok = span >= 1e-6
    dirs = local / np.where(ok, span, 1.0)[:, None]
    hits = _cast((ox, oy), dirs, block, np.where(ok, span, 0.0))
    out = []
    for i, spot in enumerate(spots):
        if not ok[i] or hits[i] >= span[i]:
            out.append(spot)
        else:
            out.append((ox + dirs[i, 0] * hits[i],
                        oy + dirs[i, 1] * hits[i]))
    return out


class Light:
    """Shared state for every light: position, colour, energy, animation."""

    dims = 3
    blend = "opaque"
    gpu_slots = True
    # one shared dimmer for every light; blackout, fade, exposure
    master = 1.0

    def __init__(self, scene=None, pos=None, color="torch", energy=1.0,
                 radius=0.0, tag=None, enabled=True, priority=0.0,
                 follow=None, offset=None, align=False, local=False,
                 aim=None, seed=0,
                 flicker=0.0, flicker_rate=9.0, flicker_style="candle",
                 pulse=0.0, pulse_rate=1.0, blink=None, alpha=1.0,
                 atten="smooth", falloff=0.0, exponent=2.0, layer=-1,
                 negative=False, cookie=None, outer=None, gate=None,
                 bake=False, **kw):
        self.scene = scene
        self.pos = _vec(pos, self.dims, (0.0,) * self.dims)
        self.color = colors.rgb(color, (1.0, 0.67, 0.27))
        self.energy = float(energy)
        self.radius = float(radius or 0.0)
        self.tag = tag or type(self).__name__.lower()
        self.enabled = bool(enabled)
        self.priority = float(priority or 0.0)
        self.follow = follow if hasattr(follow, "pos") else None
        self.offset = None if offset is None else \
            _vec(offset, self.dims, (0.0,) * self.dims)
        self.align = bool(align)
        self.local = bool(local)
        # an aimed light's bias from what it follows, in degrees
        self.aim = None if aim is None else _vec(aim, 2, (0.0, 0.0))
        self.seed = int(seed or 0)
        self.flicker = float(flicker or 0.0)
        self.flicker_rate = float(flicker_rate or 9.0)
        self.flicker_style = str(flicker_style or "candle")
        self.pulse = float(pulse or 0.0)
        self.pulse_rate = float(pulse_rate or 1.0)
        self.alpha = max(0.0, min(1.0, float(alpha)))
        self.atten = atten if atten in ATTEN else "smooth"
        self.falloff = max(0.0, min(0.95, float(falloff or 0.0)))
        self.exponent = max(0.01, float(exponent or 2.0))
        self.layer = layer_bits(layer)
        self.negative = bool(negative)
        # baked lights are painted once into a lightmap
        self.bake = bool(bake)
        self.cookie = cookie
        self.outer = None if outer is None else colors.rgb(outer, None)
        self.t = 0.0
        self.intensity = self.energy if self.enabled else 0.0
        self.dirty = True
        self.mesh = None
        self.poly = None            # the last outline it drew, for queries
        self._late = dict(kw)       # shape knobs the subclass claims below
        self._fade = None
        self._flash = None
        self._blink = None
        self._blink_on = True
        self._blink_left = 0.0
        self._blink_dim = 0.0
        self._sputter = None
        self._ramp = None
        self._grow = None
        self._motion = None
        self._gate = gate
        self._timers = []
        if blink:
            self.blink(blink)
        self._apply_late()

    def _apply_late(self):
        """Hand the kwargs a subclass understands over to `set()`."""
        if not self._late:
            return
        kw, self._late = self._late, {}
        self.set(**kw)

    # -- state ----------------------------------------------------------------
    def set(self, pos=None, color=None, energy=None, radius=None,
            enabled=None, priority=None, follow=None, offset=None,
            align=None, local=None, aim=None, tag=None, alpha=None,
            atten=None, falloff=None, exponent=None, layer=None,
            negative=None, cookie=None, outer=None, flicker=None,
            flicker_rate=None, flicker_style=None, pulse=None,
            pulse_rate=None, **kw):
        """Change anything about the light; it updates itself next frame."""
        changed = False
        if pos is not None:
            self.pos = _vec(pos, self.dims, self.pos)
            changed = True
        if color is not None:
            self.color = colors.rgb(color, self.color)
            changed = True
        if energy is not None:
            self.energy = float(energy)
            if self._ramp is not None:
                self._ramp["base"] = self.energy
            self._fade = self._flash = None
            changed = True
        if radius is not None:
            self.radius = float(radius)
            changed = True
        if enabled is not None:
            self.enabled = bool(enabled)
            changed = True
        if priority is not None:
            self.priority = float(priority)
        if tag is not None:
            self.tag = str(tag)
        if follow is not None:
            self.follow = None if follow is False else follow
            changed = True
        if offset is not None:
            self.offset = None if offset is True else \
                _vec(offset, self.dims, (0.0,) * self.dims)
            changed = True
        if align is not None:
            self.align = bool(align)
        if local is not None:
            self.local = bool(local)
        if aim is not None:
            self.aim = None if aim is False else _vec(aim, 2, (0.0, 0.0))
        if alpha is not None:
            self.alpha = max(0.0, min(1.0, float(alpha)))
        if atten is not None:
            self.atten = atten if atten in ATTEN else "smooth"
        if falloff is not None:
            self.falloff = max(0.0, min(0.95, float(falloff)))
        if exponent is not None:
            self.exponent = max(0.01, float(exponent))
        if layer is not None:
            self.layer = layer_bits(layer)
        if negative is not None:
            self.negative = bool(negative)
            self.dirty = True
        if cookie is not None:
            self.cookie = cookie
        if outer is not None:
            self.outer = colors.rgb(outer, self.outer)
        for name, got in (("flicker", flicker), ("flicker_rate", flicker_rate),
                          ("pulse", pulse), ("pulse_rate", pulse_rate)):
            if got is not None:
                setattr(self, name, float(got))
        if flicker_style is not None:
            self.flicker_style = str(flicker_style)
        for name, value in kw.items():
            if hasattr(self, name) and not callable(getattr(self, name)):
                setattr(self, name, value)
                changed = True
        self.dirty = self.dirty or changed
        return self

    def move(self, *delta):
        """Nudge by a per-axis delta: metres or pixels."""
        for i, d in enumerate(delta):
            if i < self.dims and d:
                self.pos[i] += float(d)
        self.dirty = True
        return self

    def move_to(self, *pos):
        self.pos = _vec(pos, self.dims, self.pos)
        self.dirty = True
        return self

    def at(self, obj, offset=None, align=None, local=None, aim=None):
        """Ride another object: the player, a car, a torch."""
        self.follow = obj
        if offset is not None:
            self.offset = _vec(offset, self.dims, (0.0,) * self.dims)
        if align is not None:
            self.align = bool(align)
        if local is not None:
            self.local = bool(local)
        if aim is not None:
            self.aim = None if aim is False else _vec(aim, 2, (0.0, 0.0))
        self.dirty = True
        return self

    def detach(self):
        """Stop following."""
        self.follow = None
        return self

    def level(self):
        """Intensity x alpha x dimmer, negated when it eats light."""
        k = self.intensity * self.alpha * self.master
        return -k if self.negative else k

    def tint(self, factor=1.0):
        """Colour x `level()` x `factor`, for the GPU or mesh."""
        k = self.level() * float(factor)
        return tuple(c * k for c in self.color)

    def distance_to(self, pos):
        """Straight-line distance to a point, in this light's own units."""
        other = _vec(pos, self.dims, (0.0,) * self.dims)
        return math.sqrt(sum((self.pos[i] - other[i]) ** 2
                             for i in range(self.dims)))

    @property
    def x(self):
        return self.pos[0]

    @x.setter
    def x(self, value):
        self.pos[0] = float(value)
        self.dirty = True

    @property
    def y(self):
        return self.pos[1]

    @y.setter
    def y(self, value):
        self.pos[1] = float(value)
        self.dirty = True

    @property
    def range(self):
        """Alias of `radius`, for people coming from other engines."""
        return self.radius

    @range.setter
    def range(self, value):
        self.radius = float(value)
        self.dirty = True

    # -- asking ----------------------------------------------------------------
    def strength_at(self, pos):
        """How much of this light reaches a point."""
        if self.intensity <= 0.0:
            return 0.0
        if self.kind == SUN:
            return self.level()
        att = atten_value(self.atten, self.falloff, self.exponent,
                          self.distance_to(pos), self.radius)
        if att <= 0.0:
            return 0.0
        if self.kind == SPOT:
            delta = [float(pos[i]) - self.pos[i] for i in range(3)]
            n = math.sqrt(sum(c * c for c in delta))
            if n < 1e-6:
                return self.level()
            want = norm(self.dir)
            hit = sum(want[i] * delta[i] / n for i in range(3))
            half = math.radians(max(0.5, min(179.0, self.angle))) / 2.0
            cos_out, cos_in = math.cos(half), math.cos(half * self.inner)
            if hit <= cos_out:
                return 0.0
            if hit < cos_in:
                att *= (hit - cos_out) / max(1e-6, cos_in - cos_out)
        return self.level() * att

    def contains(self, pos):
        """Is a point inside the light's shape at all?"""
        return abs(self.strength_at(pos)) > 0.0

    def affects(self, obj):
        """Layer test: does this light reach that object?"""
        want = layer_bits(getattr(obj, "light_layer", None))
        if want == LAYERS["all"] or self.layer == LAYERS["all"]:
            return True
        return bool(self.layer & want)

    def link(self, *names):
        """Restrict the light to named layers: `flash.link("player", "fx")`."""
        return self.set(layer=layer_bits(list(names) or ["all"]))

    def unlink(self):
        """Reach every object again (the default)."""
        return self.set(layer=LAYERS["all"])

    def kelvin(self, temp):
        """Set the colour from a kelvin temperature, 1700 a candle."""
        return self.set(color=kelvin_rgb(temp))

    def gpu(self):
        """(pos, colour x level, dir, cone shape)"""
        half = math.radians(max(0.5, min(179.0, getattr(self, "angle", 42.0))))
        half /= 2.0
        cos_out = math.cos(half)
        cos_in = math.cos(half * max(0.0, min(0.999, self.inner)))
        return (self.pos, self.tint(), norm(getattr(self, "dir", (0, -1, 0))),
                (self.radius, cos_in, cos_out, float(self.kind)),
                (float(atten_code(self.atten)), self.falloff, self.exponent,
                 float(getattr(self, "length", 0.0) or 0.0)))

    # -- switching --------------------------------------------------------------
    def on(self):
        return self.set(enabled=True)

    def off(self):
        return self.set(enabled=False)

    def toggle(self):
        return self.set(enabled=not self.enabled)

    def enable(self, value):
        return self.set(enabled=bool(value))

    def gate(self, fn):
        """Only shine while `fn` says so."""
        self._gate = fn
        self.dirty = True
        return self

    def ungate(self):
        """Drop the `gate()` predicate."""
        self._gate = None
        self.dirty = True
        return self

    def fade_to(self, energy=1.0, secs=0.5, keep=True, rate=None):
        """Ease `energy` over `secs`. `keep=False` switches the light off"""
        self._fade = {"from": self.energy, "to": float(energy),
                      "t": 0.0, "secs": max(1e-4, float(secs)),
                      "keep": bool(keep)}
        if rate is not None:
            self._fade["secs"] = 1.0 / max(1e-3, float(rate))
        self.dirty = True
        return self

    def flash(self, amount=2.0, secs=0.14):
        """One bright kick decaying back to `energy`."""
        self._flash = {"base": self.energy, "amount": float(amount),
                       "t": 0.0, "secs": max(1e-3, float(secs))}
        self.dirty = True
        return self

    def blink(self, spec):
        """Alternating on and off. `spec` is `(on_secs, off_secs)`, or"""
        if isinstance(spec, dict):
            on = float(spec.get("on", 0.5))
            off = float(spec.get("off", on))
            dim = float(spec.get("dim", 0.0))
        else:
            parts = [float(c) for c in spec]
            on = parts[0]
            off = parts[1] if len(parts) > 1 else parts[0]
            dim = parts[2] if len(parts) > 2 else 0.0
        self._blink = (max(1e-3, on), max(1e-3, off), dim)
        self._blink_on = True
        self._blink_left = on
        self._blink_dim = dim
        self.dirty = True
        return self

    def steady(self):
        """Undo blink, strobe, sputter, ramp, flash, fade and grow."""
        self._blink = self._flash = self._fade = None
        self._sputter = self._ramp = self._grow = None
        self.dirty = True
        return self

    def strobe(self, rate=8.0, duty=0.5):
        """A hard, fast on/off: camera flash, alarm."""
        half = 1.0 / max(0.01, float(rate))
        duty = max(0.01, min(0.99, float(duty)))
        return self.blink((half * duty, half * (1.0 - duty), 0.0))

    def sputter(self, amount=0.9, rate=2.5):
        """Random dropouts: a dying bulb or failing circuit."""
        self._sputter = (max(0.0, min(1.0, float(amount))),
                         max(0.01, float(rate)))
        self.dirty = True
        return self

    def ramp(self, stops, secs=4.0, loop=True):
        """Play a keyframed colour and energy curve."""
        col, en = [], []
        for entry in stops:
            at, tint, level = _ramp_entry(entry)
            if tint is not None:
                col.append((at, tint))
            if level is not None:
                en.append((at, level))
        if not col and not en:
            self._ramp = None
            return self
        self._ramp = {"col": col, "en": en, "secs": max(1e-3, float(secs)),
                      "loop": bool(loop), "t": 0.0, "base": self.energy}
        self.dirty = True
        return self

    def throb(self, rate=1.2, amount=0.7):
        """A fast, deep pulse: an alert lamp, a beating heart."""
        return self.pulsing(amount, rate)

    def breathe(self, rate=0.25, amount=0.5):
        """A slow in-out, never below `1 - amount` energy."""
        self.pulse = float(amount) / 2.0
        self.pulse_rate = float(rate)
        self.energy *= 1.0 - self.pulse
        self.dirty = True
        return self

    def flickering(self, amount=0.18, rate=9.0, seed=None):
        """Organic jitter, the kind an open flame needs."""
        self.flicker = float(amount)
        self.flicker_rate = float(rate)
        if seed is not None:
            self.seed = int(seed)
        self.dirty = True
        return self

    def pulsing(self, amount=0.35, rate=1.0):
        """Sine the energy forever: a lighthouse, a warning lamp."""
        self.pulse = float(amount)
        self.pulse_rate = float(rate)
        self.dirty = True
        return self

    def grow(self, radius=None, secs=0.5, loop=False, dim=False):
        """Run the reach outward (or inward) from where it stands."""
        target = float(radius) if radius is not None else self.radius * 2.0
        if target <= 0.0:
            self._grow = None
            return self
        self._grow = {"from": self.radius, "to": target, "secs":
                      max(1e-3, float(secs)), "t": 0.0,
                      "loop": bool(loop), "dim": bool(dim),
                      "energy": self.energy}
        self.dirty = True
        return self

    # -- moving on its own -------------------------------------------------------
    def orbit(self, radius=1.0, secs=6.0, phase=0.0, plane=None):
        """Circle about its own spot forever."""
        plane = plane or ((0, 1) if self.dims == 2 else (0, 2))
        self._motion = {"kind": "orbit", "base": list(self.pos),
                        "radius": float(radius), "plane": tuple(plane[:2]),
                        "secs": float(secs) or 1.0, "phase": float(phase),
                        "t": 0.0}
        self.dirty = True
        return self

    def sway(self, amount=0.4, secs=3.0, axis=0):
        """Rock back and forth: a swinging lantern."""
        raw = amount if isinstance(amount, (list, tuple)) else [amount]
        self._motion = {"kind": "sway", "base": list(self.pos),
                        "amount": [float(c) for c in raw],
                        "axis": int(axis), "secs": float(secs) or 1.0,
                        "t": 0.0}
        self.dirty = True
        return self

    def path(self, points, secs=8.0, loop=True):
        """Walk a polyline of world positions at a steady pace."""
        pts = [_vec(p, self.dims, (0.0,) * self.dims) for p in points or ()]
        if len(pts) < 2:
            self._motion = None
            return self
        legs, total = [], 0.0
        for a, b in zip(pts, pts[1:]):
            d = math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(self.dims)))
            legs.append((a, b, d))
            total += d
        self._motion = {"kind": "path", "legs": legs, "total": max(1e-3, total),
                        "secs": float(secs) or 1.0, "loop": bool(loop),
                        "t": 0.0}
        self.dirty = True
        return self

    def still(self):
        """Stop `orbit` / `sway` / `path` where the light stands."""
        self._motion = None
        return self

    def _run_motion(self, dt):
        """Advance whatever self-moving animation is set."""
        mo = self._motion
        mo["t"] += dt
        k = mo["t"]
        if mo["kind"] == "orbit":
            a = mo["phase"] + 2.0 * math.pi * k / mo["secs"]
            base = mo["base"]
            pos = list(base)
            i0, i1 = mo["plane"]
            if i0 < self.dims:
                pos[i0] = base[i0] + math.cos(a) * mo["radius"]
            if i1 < self.dims:
                pos[i1] = base[i1] + math.sin(a) * mo["radius"]
            self.pos = pos
        elif mo["kind"] == "sway":
            a = math.sin(2.0 * math.pi * k / mo["secs"])
            base = mo["base"]
            pos = list(base)
            amount = mo["amount"]
            for i in range(self.dims):
                if len(amount) == 1:
                    if i == mo["axis"]:
                        pos[i] = base[i] + amount[0] * a
                elif i < len(amount):
                    pos[i] = base[i] + amount[i] * a
            self.pos = pos
        else:
            total = mo["total"]
            x = (k % mo["secs"]) / mo["secs"] * total if mo["loop"] else \
                min(1.0, k / mo["secs"]) * total
            for a, b, d in mo["legs"]:
                if x > d:
                    x -= d
                    continue
                t = x / max(1e-6, d)
                self.pos = [a[i] + (b[i] - a[i]) * t for i in range(self.dims)]
                break
        self.dirty = True

    # -- colour / energy curves ---------------------------------------------------
    def _run_grow(self, dt):
        """Ease `radius`, and energy when `dim` was asked."""
        g = self._grow
        g["t"] += dt
        k = min(1.0, g["t"] / g["secs"])
        e = k * k * (3.0 - 2.0 * k)                  # smoothstep: quick start
        self.radius = g["from"] + (g["to"] - g["from"]) * e
        if g["dim"]:
            self.energy = g["energy"] * (1.0 - k)
        self.dirty = True
        if k >= 1.0:
            if not g["loop"]:
                self._grow = None
                return
            g["t"] = 0.0
            self.radius = g["from"]
            if g["dim"]:
                self.energy = g["energy"]

    def _run_ramp(self, dt):
        r = self._ramp
        r["t"] += dt
        x = r["t"] / r["secs"]
        x = x % 1.0 if r["loop"] else min(1.0, x)
        if r["col"]:
            self.color = ramp_rgb(r["col"], x, loop=r["loop"])
        if r["en"]:
            self.energy = r["base"] * ramp_number(r["en"], x, loop=r["loop"])
        self.dirty = True
        if not r["loop"] and x >= 1.0:
            self._ramp = None

    # -- timers -------------------------------------------------------------------
    def after(self, secs, fn):
        """Call `fn(self)` once, `secs` from now."""
        self._timers.append({"left": float(secs), "every": 0.0, "runs": 1,
                             "fn": fn})
        return self

    def every(self, secs, fn, count=None):
        """Call `fn(self)` every `secs`, `count` times - forever if None."""
        self._timers.append({"left": float(secs), "every": float(secs),
                             "runs": int(count) if count else -1, "fn": fn})
        return self

    def _run_timers(self, dt):
        if not self._timers:
            return
        keep = []
        for entry in self._timers:
            entry["left"] -= dt
            if entry["left"] > 0.0:
                keep.append(entry)
                continue
            entry["fn"](self)
            entry["runs"] -= 1
            if entry["every"] and entry["runs"] != 0:
                entry["left"] = entry["every"]
                keep.append(entry)
        self._timers = keep

    # -- frame -------------------------------------------------------------------
    def update(self, dt):
        """Advance every animation; hands back the intensity."""
        self.t += dt
        self._run_timers(dt)
        if self.follow is not None:
            self._track(self.follow)
            self.dirty = True
        if self._motion is not None:
            self._run_motion(dt)
        if self._ramp is not None:
            self._run_ramp(dt)
        if self._grow is not None:
            self._run_grow(dt)
        if self._fade is not None:
            fade = self._fade
            fade["t"] += dt
            k = min(1.0, fade["t"] / fade["secs"])
            k = k * k * (3.0 - 2.0 * k)              # smoothstep
            self.energy = fade["from"] + (fade["to"] - fade["from"]) * k
            if k >= 1.0:
                self._fade = None
                if not fade["keep"]:
                    self.enabled = False
            self.dirty = True
        if self._flash is not None:
            flash = self._flash
            flash["t"] += dt
            k = min(1.0, flash["t"] / flash["secs"])
            self.energy = flash["base"] * (1.0 + flash["amount"]
                                           * (1.0 - k) * (1.0 - k))
            if k >= 1.0:
                self.energy = flash["base"]
                self._flash = None
            self.dirty = True
        if self._blink is not None:
            on_secs, off_secs, dim = self._blink
            self._blink_left -= dt
            if self._blink_left <= 0.0:
                self._blink_on = not self._blink_on
                self._blink_left = on_secs if self._blink_on else off_secs
        level = self.energy if self._switched_on() else 0.0
        if self._blink is not None and not self._blink_on:
            level *= self._blink_dim
        if self._sputter is not None:
            depth, rate = self._sputter
            n = _noise(self.t * rate * 3.7 + self.seed * 5.3)
            if n < 0.0:                            # a dropout, deepest at the
                level *= (1.0 - depth) * (1.0 + n)  # middle of the dip
        if self.pulse:
            level *= 1.0 + self.pulse * math.sin(
                2.0 * math.pi * self.pulse_rate * self.t)
        if self.flicker:
            level *= 1.0 + self.flicker * _flicker(
                self.flicker_style, self.t, self.flicker_rate, self.seed)
        self.intensity = max(0.0, level)
        return self.intensity

    def _switched_on(self):
        """`enabled` and whatever the `gate()` predicate says."""
        if not self.enabled:
            return False
        if self._gate is None:
            return True
        try:
            return bool(self._gate(self))
        except TypeError:
            return bool(self._gate())

    def _track(self, obj):
        """Sit on the followed object; optionally share its look."""
        got = getattr(obj, "pos", None)
        if got is None:
            return
        base = _vec(got, self.dims, self.pos)
        off = self.offset or [0.0] * self.dims
        if self.local:
            off = self._local(off, obj)
        self.pos = [base[i] + (off[i] if i < len(off) else 0.0)
                    for i in range(self.dims)]
        if self.align:
            self._aim(obj)

    def _local(self, off, obj):
        """Turn an owner-frame offset into world axes."""
        a = getattr(obj, "yaw", None)
        if a is None:
            a = getattr(obj, "rot", 0.0)
        a = float(a or 0.0)
        c, s = math.cos(a), math.sin(a)
        if self.dims == 2:
            return [off[0] * c - off[1] * s,
                    off[0] * s + off[1] * c]
        # yaw about y, in the engine's +Z-forward basis
        return [off[0] * c + off[2] * s, off[1], -off[0] * s + off[2] * c]

    def _aim(self, obj):
        """Subclass hook: point along the owner's view."""

    # -- bookkeeping -------------------------------------------------------------
    def add_to(self, scene=None):
        """Put this light in the scene's list."""
        scene = self.scene if scene is None else scene
        if scene is not None:
            self.scene = scene
            if self not in scene.lights:
                scene.lights.append(self)
        return self

    def copy(self, scene=None, pos=None, tag=None, add=True):
        """A second light like this one, animation included."""
        got = type(self)(scene or self.scene,
                         pos=self.pos if pos is None else pos,
                         color=self.color, energy=self.energy,
                         radius=self.radius, enabled=self.enabled,
                         priority=self.priority, tag=tag or self.tag,
                         flicker=self.flicker, seed=self.seed,
                         flicker_rate=self.flicker_rate,
                         flicker_style=self.flicker_style,
                         pulse=self.pulse, pulse_rate=self.pulse_rate,
                         alpha=self.alpha, atten=self.atten,
                         falloff=self.falloff, exponent=self.exponent,
                         layer=self.layer, negative=self.negative,
                         cookie=self.cookie, outer=self.outer,
                         offset=self.offset, align=self.align,
                         local=self.local, aim=self.aim)
        self._copy_shape(got)
        if add:
            got.add_to(scene)
        return got

    def _copy_shape(self, other):
        """Subclass hook: carry the shape knobs across a copy."""

    def to_dict(self):
        """Everything a save file needs to put this light back."""
        data = {"kind": type(self).__name__, "pos": list(self.pos),
                "color": list(self.color), "energy": self.energy,
                "radius": self.radius, "enabled": self.enabled,
                "priority": self.priority, "tag": self.tag,
                "alpha": self.alpha, "atten": self.atten,
                "falloff": self.falloff, "exponent": self.exponent,
                "layer": self.layer, "negative": self.negative,
                "bake": self.bake,
                "flicker": self.flicker,
                "flicker_style": self.flicker_style,
                "pulse": self.pulse, "pulse_rate": self.pulse_rate,
                "align": self.align, "local": self.local}
        if self.aim is not None:
            data["aim"] = list(self.aim)
        if self.offset is not None:
            data["offset"] = list(self.offset)
        if self.cookie:
            data["cookie"] = self.cookie
        if self.outer:
            data["outer"] = list(self.outer)
        data.update(self._shape_dict())
        return data

    def _shape_dict(self):
        return {"shape": getattr(self, "shape_name", None)}

    @classmethod
    def from_dict(cls, data, scene=None):
        """Rebuild a light from `to_dict()`; the right class by `kind`."""
        kind = str(data.get("kind") or "")
        target = {"Light3D": Light3D, "Light2D": Light2D}.get(kind, cls)
        if target is cls and cls is Light:
            target = Light3D
        return target(scene, **_light_kwargs(data))

    def dispose(self):
        self._timers = []
        self._gate = None
        self.follow = None
        if self.mesh is not None:
            self.mesh.dispose()
            self.mesh = None

    # old projects kept lights as plain dicts; keys still work
    def __getitem__(self, name):
        return self.get(name)

    def __setitem__(self, name, value):
        self.set(**{name: value})

    def get(self, name, default=None):
        return getattr(self, name, default)

    def keys(self):
        return ("pos", "color", "energy", "radius", "enabled", "alpha",
                "atten", "layer")

    def __repr__(self):
        where = " ".join(f"{c:.1f}" for c in self.pos)
        return "<{0} {1} {2} {3} i={4:.2f}{5}>".format(
            type(self).__name__, self.tag, where,
            getattr(self, "shape_name", ""), self.intensity,
            "" if self.enabled else " off")


def _light_kwargs(data):
    """`to_dict()` output back into constructor keywords."""
    kw = {"pos": data.get("pos"), "color": data.get("color", "torch"),
          "energy": data.get("energy", 1.0),
          "radius": data.get("radius", 0.0),
          "enabled": data.get("enabled", True),
          "priority": data.get("priority", 0.0), "tag": data.get("tag"),
          "alpha": data.get("alpha", 1.0),
          "atten": data.get("atten", "smooth"),
          "falloff": data.get("falloff", 0.0),
          "exponent": data.get("exponent", 2.0),
          "layer": data.get("layer", -1),
          "negative": data.get("negative", False),
          "bake": data.get("bake", False),
          "flicker": data.get("flicker", 0.0),
          "flicker_style": data.get("flicker_style", "candle"),
          "pulse": data.get("pulse", 0.0),
          "pulse_rate": data.get("pulse_rate", 1.0)}
    shape = data.get("shape")
    if shape:
        kw["shape"] = shape
    for name in ("dir", "angle", "inner", "soft", "cast", "size", "glow",
                 "samples", "points", "cookie", "outer", "blur", "edge",
                 "hole", "length", "width", "offset", "align", "local",
                 "aim"):
        if name in data and data[name] is not None:
            kw[name] = data[name]
    return {k: v for k, v in kw.items() if v is not None}


def _ramp_entry(entry):
    """One `ramp()` stop as (at, colour, energy)."""
    if isinstance(entry, dict):
        return (float(entry.get("at", entry.get("t", 0.0))),
                entry.get("color"), entry.get("energy"))
    parts = list(entry)
    at = float(parts[0])
    tint = parts[1] if len(parts) > 1 else None
    level = parts[2] if len(parts) > 2 else None
    if isinstance(tint, (int, float)) and level is None:
        return at, None, float(tint)         # a bare (at, energy) stop
    return at, tint, level


def luminance_at(pos, items, ambient=0.0):
    """Total light at a point from any lights."""
    total = float(ambient)
    for entry in items or ():
        if isinstance(entry, Light):
            total += entry.strength_at(pos)
    return max(0.0, total)


def set_master(value=1.0, scene=None):
    """Dim or boost every light at once; 0 is blackout."""
    value = max(0.0, min(4.0, float(value)))
    Light.master = value
    if scene is not None:
        scene.master = value
    return value


def get_master():
    """The dimmer `set_master()` last moved."""
    return Light.master


class Light3D(Light):
    """A metre-world light: point, spot, sun or tube."""

    dims = 3
    blend = "opaque"
    gpu_slots = True

    def __init__(self, scene=None, pos=(0.0, 0.0, 0.0), color="torch",
                 shape="point", dir=None, yaw=None, pitch=None, angle=42.0,
                 inner=0.6, glow=0.0, energy=1.0, radius=18.0, length=0.0,
                 **kw):
        self.shape_name = str(shape or "point").lower()
        self.kind = SHAPES_3D.get(self.shape_name, POINT)
        self.dir = _vec(dir, 3, None) if dir is not None else \
            _dir3(float(yaw), float(pitch or 0.0)) if yaw is not None \
            else _dir3(0.0, float(pitch)) if pitch is not None \
            else [0.0, -1.0, 0.0]
        self.angle = float(angle)
        self.inner = max(0.0, min(1.0, float(inner)))
        self.length = max(0.0, float(length or 0.0))
        self.glow = float(glow) if isinstance(glow, (int, float)) else \
            (1.0 if glow else 0.0)
        self._glow_mesh = None
        self._spin = None
        self._sweep = None
        kw.pop("cast", None)
        kw.pop("blockers", None)
        kw.pop("blur", None)
        kw.pop("points", None)
        kw.pop("soft", None)
        kw.pop("hole", None)
        kw.pop("width", None)
        super().__init__(scene, pos=pos, color=color, energy=energy,
                         radius=radius, **kw)
        if self.kind == SUN:
            self.align = False

    @property
    def z(self):
        return self.pos[2]

    @z.setter
    def z(self, value):
        self.pos[2] = float(value)
        self.dirty = True

    def _set_shape(self, shape=None, dir=None, yaw=None, pitch=None,
                   angle=None, inner=None, glow=None, length=None):
        if shape is not None:
            self.shape_name = str(shape).lower()
            self.kind = SHAPES_3D.get(self.shape_name, POINT)
        if dir is not None:
            self.dir = _vec(dir, 3, self.dir)
        if yaw is not None:
            self.dir = _dir3(float(yaw), float(pitch or 0.0))
        elif pitch is not None:
            self.dir = _dir3(self.yaw(), float(pitch))
        if angle is not None:
            self.angle = float(angle)
        if inner is not None:
            self.inner = max(0.0, min(1.0, float(inner)))
        if length is not None:
            self.length = max(0.0, float(length))
        if glow is not None:
            self.glow = float(glow) if isinstance(glow, (int, float)) else \
                (1.0 if glow else 0.0)

    def set(self, shape=None, dir=None, yaw=None, pitch=None, angle=None,
            inner=None, glow=None, length=None, **kw):
        self._set_shape(shape, dir, yaw, pitch, angle, inner, glow, length)
        return super().set(**kw)

    def yaw(self):
        """The cone's heading, as the yaw a Player3D uses."""
        return math.atan2(self.dir[0], self.dir[2])

    def turn(self, yaw, pitch=None):
        """Aim the cone with yaw and optional pitch, radians."""
        self.dir = _dir3(float(yaw), self.elevation() if pitch is None
                         else float(pitch))
        self.dirty = True
        return self

    def elevation(self):
        """How far the cone points above the horizon, in radians."""
        d = norm(self.dir)
        return math.asin(max(-1.0, min(1.0, d[1])))

    def look_at(self, target):
        """Aim the cone at a world point."""
        want = _vec(target, 3, self.pos)
        delta = [want[i] - self.pos[i] for i in range(3)]
        if abs(delta[0]) < 1e-6 and abs(delta[2]) < 1e-6:
            self.dir = [0.0, 1.0 if delta[1] >= 0 else -1.0, 0.0]
        else:
            self.dir = _dir3(math.atan2(delta[0], delta[2]),
                             math.atan2(delta[1], math.hypot(delta[0],
                                                              delta[2])))
        self.dirty = True
        return self

    def _aim(self, obj):
        """Point down the followed object's own view axis, plus `aim`."""
        yaw = getattr(obj, "yaw", None)
        if yaw is None:
            return
        pan, tilt = self.aim or (0.0, 0.0)
        self.dir = _dir3(float(yaw) + math.radians(pan),
                         float(getattr(obj, "pitch", 0.0) or 0.0) +
                         math.radians(tilt))

    def spin(self, secs=6.0, reverse=False):
        """Keep turning at a steady rate."""
        if secs is None:
            self._spin = None
            return self
        rate = 2.0 * math.pi / (float(secs) or 1.0)
        self._spin = -rate if reverse else rate
        return self

    def sweep(self, a0=-0.7, a1=0.7, secs=4.0):
        """Oscillate between two yaws instead of circling."""
        if a0 is None:
            self._sweep = None
            return self
        self._sweep = (float(a0), float(a1), float(secs) or 1.0, 0.0)
        return self

    def set_time(self, hour, strength=1.0, day=None):
        """Drive a sun from the clock: direction, colour, energy."""
        got = daylight(hour, sky=day or DAY_SKY, strength=strength)
        return self.set(dir=got["sun_dir"], color=got["sun_col"],
                        energy=max(0.0, got["sun_energy"]))

    def update(self, dt):
        if self._spin is not None:
            self.dir = _dir3(self.yaw() + self._spin * dt, self.elevation())
            self.dirty = True
        if self._sweep is not None:
            a0, a1, secs, t = self._sweep
            t += dt
            k = 0.5 - 0.5 * math.cos(2.0 * math.pi * t / secs)
            self.dir = _dir3(a0 + (a1 - a0) * k, self.elevation())
            self._sweep = (a0, a1, secs, t)
            self.dirty = True
        level = super().update(dt)
        self._draw_glow(level)
        return level

    def _draw_glow(self, level):
        """The visible flame: additive crossed quads on the light itself."""
        if self.glow <= 0.0 or self.scene is None or level <= 0.0:
            if self._glow_mesh is not None and self._glow_mesh.count:
                self._glow_mesh.update(_empty3d())
            return
        r = self.scene.renderer
        if not r.has_texture("light_glow"):
            # white body so the vertex colour tints it
            r.texture("light_glow", proctex.glow(color=(1.0, 1.0, 1.0)),
                      rgba=True, filter="nearest", mipmaps=False)
        size = self.glow * (0.92 + 0.08 * _noise(self.t * 7.3 + self.seed))
        data = meshes.billboards(self.pos, size, size, count=3,
                                 col=self.tint())
        if self._glow_mesh is None:
            self._glow_mesh = r.new_dynamic(data, texture="light_glow",
                                            blend="add")
        else:
            self._glow_mesh.update(data)

    def _tube_distance(self, pos):
        """Distance from the tube's line, and position along it."""
        want = norm(self.dir)
        d = [float(pos[i]) - self.pos[i] for i in range(3)]
        along = max(0.0, min(self.length or 1e-3,
                             sum(want[i] * d[i] for i in range(3))))
        perp = math.sqrt(sum((d[i] - want[i] * along) ** 2 for i in range(3)))
        return perp, along

    def strength_at(self, pos):
        """The base query with the tube's line distance folded in."""
        if self.kind != TUBE or self.length <= 0.0:
            return Light.strength_at(self, pos)
        if self.intensity <= 0.0:
            return 0.0
        perp, along = self._tube_distance(pos)
        att = atten_value(self.atten, self.falloff, self.exponent, perp,
                          self.radius)
        # the last 15% fades out at each cap
        ends = min(1.0, along / max(1e-3, 0.15 * self.length),
                   (self.length - along) / max(1e-3, 0.15 * self.length))
        return self.level() * att * max(0.0, ends)

    def _copy_shape(self, other):
        other.set(shape=self.shape_name, dir=self.dir, angle=self.angle,
                  inner=self.inner, glow=self.glow, length=self.length)

    def _shape_dict(self):
        return {"shape": self.shape_name, "dir": list(self.dir),
                "angle": self.angle, "inner": self.inner,
                "glow": self.glow, "length": self.length}

    def dispose(self):
        if self._glow_mesh is not None:
            self._glow_mesh.dispose()
            self._glow_mesh = None
        super().dispose()


class Light2D(Light):
    """A light in a pixel world, drawn into the mask."""

    dims = 2
    blend = "light"
    gpu_slots = False

    def __init__(self, scene=None, pos=(0.0, 0.0), color="torch",
                 shape="radial", radius=190.0, dir=0.0, angle=360.0,
                 inner=0.0, soft=0.18, cast=True, blockers=None, size=None,
                 samples=48, energy=1.0, blur=0.0, points=None, hole=0.0,
                 length=None, width=None, align=False, **kw):
        self.shape_name = NAME_2D.get(SHAPES_2D.get(
            str(shape or "radial").lower(), RADIAL), "radial")
        self.kind = SHAPES_2D.get(self.shape_name, RADIAL)
        self.dir = float(dir)                    # degrees, screen-style
        self.angle = max(1.0, min(360.0, float(angle)))
        self.inner = float(inner)
        self.soft = max(0.0, min(1.0, float(soft)))
        self.cast = bool(cast)
        self.blockers = blockers
        self.hole = max(0.0, min(0.95, float(hole or 0.0)))
        self.size = None if size is None else _vec(size, 2, (200.0, 200.0))
        if length is not None or width is not None:
            # a strip is written `length=, width=`; both land in `size`
            base = self.size or [float(radius or 0.0) * 2.0,
                                 float(radius or 0.0) * 2.0]
            self.size = [float(length) if length is not None else base[0],
                         float(width) if width is not None else base[1]]
        self.samples = max(8, int(samples))
        self.blur = max(0.0, min(1.0, float(blur or 0.0)))
        self.points = None if points is None else [
            (float(p[0]), float(p[1])) for p in points]
        self._walls = None
        self._copies = 1
        self._spin = None
        self._sweep = None
        super().__init__(scene, pos=pos, color=color, energy=energy,
                         radius=radius, align=align, **kw)

    def _set_shape(self, shape=None, dir=None, angle=None, inner=None,
                   soft=None, cast=None, blockers=None, size=None,
                   samples=None, blur=None, points=None, hole=None,
                   length=None, width=None):
        if shape is not None:
            self.kind = SHAPES_2D.get(str(shape).lower(), self.kind)
            self.shape_name = NAME_2D.get(self.kind, "radial")
        if dir is not None:
            self.dir = float(dir)
        if angle is not None:
            self.angle = max(1.0, min(360.0, float(angle)))
        if inner is not None:
            self.inner = float(inner)
        if soft is not None:
            self.soft = max(0.0, min(1.0, float(soft)))
            self.dirty = True
        if cast is not None:
            self.cast = bool(cast)
            self.dirty = True
        if blockers is not None:
            self.blockers = blockers
            self._walls = None
            self.dirty = True
        if hole is not None:
            self.hole = max(0.0, min(0.95, float(hole)))
            self.dirty = True
        if size is not None or length is not None or width is not None:
            base = self.size or [self.radius * 2.0, self.radius * 2.0]
            if size is not None:
                base = _vec(size, 2, base)
            self.size = [float(length) if length is not None else base[0],
                         float(width) if width is not None else base[1]]
            self.dirty = True
        if samples is not None:
            self.samples = max(8, int(samples))
            self.dirty = True
        if blur is not None:
            self.blur = max(0.0, min(1.0, float(blur)))
            self.dirty = True
        if points is not None:
            self.points = [(float(p[0]), float(p[1])) for p in points]
            self.dirty = True

    def set(self, shape=None, dir=None, angle=None, inner=None, soft=None,
            cast=None, blockers=None, size=None, samples=None, blur=None,
            points=None, hole=None, length=None, width=None, **kw):
        self._set_shape(shape, dir, angle, inner, soft, cast, blockers, size,
                        samples, blur, points, hole, length, width)
        return super().set(**kw)

    def radians(self):
        """The heading in radians, which is what the maths wants."""
        return math.radians(self.dir)

    def turn(self, angle):
        """Set the heading; values above 6.3 are radians."""
        a = float(angle)
        self.dir = math.degrees(a) if abs(a) <= 6.3 else a
        self.dirty = True
        return self

    def look_at(self, point, offset=0.0):
        """Point the cone at a world pixel, in degrees."""
        dx = float(point[0]) - self.pos[0]
        dy = float(point[1]) - self.pos[1]
        self.dir = math.degrees(math.atan2(dy, dx)) + float(offset)
        self.dirty = True
        return self

    def _aim(self, obj):
        """Follow a 2D object's own facing (`rot` is radians)."""
        for name in ("facing", "rot", "yaw"):
            got = getattr(obj, name, None)
            if isinstance(got, (int, float)) and self.kind in (CONE, RING,
                                                               RECT):
                self.dir = math.degrees(float(got)) + (self.aim or
                                                       (0.0, 0.0))[0]
                return

    def is_cone(self):
        return self.kind == CONE or (self.kind in (RADIAL, RING) and
                                     self.angle < 359.9)

    def _feather(self):
        """A cone's soft sides, or None for a hard cut."""
        if self.inner <= 0.0 or not self.is_cone():
            return None
        half = 0.5 * math.radians(self.angle)
        core = half * max(0.0, min(0.999, self.inner))
        soft = max(1e-6, half - core)
        heading = self.radians()

        def rim(dx, dy):
            off = abs(_wrap(math.atan2(dy, dx) - heading))
            k = max(0.0, min(1.0, (half - off) / soft))
            return k * k * (3.0 - 2.0 * k)
        return rim

    def spin(self, secs=6.0, reverse=False):
        """Keep turning at a steady rate."""
        if secs is None:
            self._spin = None
            return self
        rate = 360.0 / (float(secs) or 1.0)
        self._spin = -rate if reverse else rate
        return self

    def sweep(self, a0=-45.0, a1=45.0, secs=4.0):
        """Rock between two headings instead of circling."""
        if a0 is None:
            self._sweep = None
            return self
        self._sweep = (float(a0), float(a1), float(secs) or 1.0, 0.0)
        return self

    def update(self, dt):
        if getattr(self, "_spin", None):
            self.dir += self._spin * dt
            self.dirty = True
        if getattr(self, "_sweep", None) is not None:
            a0, a1, secs, t = self._sweep
            t += dt
            k = 0.5 - 0.5 * math.cos(2.0 * math.pi * t / secs)
            self.dir = a0 + (a1 - a0) * k
            self._sweep = (a0, a1, secs, t)
            self.dirty = True
        level = super().update(dt)
        self._sync_mesh()
        return level

    # -- geometry -------------------------------------------------------------
    def walls(self):
        """The blockers this light sees around."""
        got = self.blockers
        if got is None and self.scene is not None:
            got = getattr(self.scene, "blockers", None)
        if self._walls is None or self.dirty:
            self._walls = blockers_of(got)
        return self._walls

    def view_box(self):
        """The world rectangle a `world` light must cover."""
        cam = getattr(self.scene, "view", None) if self.scene else None
        if not hasattr(cam, "ortho_box"):
            cam = getattr(self.scene, "active_camera", None) if self.scene \
                else None
        box = getattr(cam, "ortho_box", None)
        if callable(box):
            left, right, below, above = box()[:4]
            return ((left + right) / 2.0, (above + below) / 2.0,
                    abs(right - left) * 1.02, abs(below - above) * 1.02)
        size = self.radius * 2.0
        return (self.pos[0], self.pos[1], size, size)

    def _corners(self):
        """A rect / strip's four world corners, turned by `dir`."""
        w, h = self.size or (self.radius * 2.0, self.radius * 2.0)
        c, s = math.cos(self.radians()), math.sin(self.radians())
        out = []
        for lx, ly in ((-w / 2.0, -h / 2.0), (w / 2.0, -h / 2.0),
                       (w / 2.0, h / 2.0), (-w / 2.0, h / 2.0)):
            out.append((self.pos[0] + lx * c - ly * s,
                        self.pos[1] + lx * s + ly * c))
        return out

    def outline(self):
        """The lit polygon in world pixels, occluded if `cast`."""
        if self.kind == WORLD:
            return None                       # the frame wash needs no polygon
        if self.kind == POLY:
            pts = list(self.points or ())
            if not pts:
                return None
            return self._clipped(pts) if self.cast else pts
        if self.kind == RECT:
            return self._clipped(self._corners()) if self.cast \
                else self._corners()
        spread = math.radians(self.angle) if self.is_cone() else None
        if not self.cast:
            return self._ring(spread)
        return visibility(self.pos, self.walls(), self.radius,
                          center=self.radians() if spread is not None else None,
                          spread=spread, samples=self.samples)

    def _clipped(self, points):
        """`points` pulled in to every wall it crosses."""
        return clip_walls(self.pos, points, self.walls(), self.samples,
                          self.radius)

    def shapes(self):
        """Every outline this light draws, three with `blur`."""
        main = self.outline()
        self.poly = main
        # nothing to soften unless it casts, with a centre
        if not self.blur or not self.cast or self.kind in (RECT, POLY, WORLD):
            self._copies = 1
            return [main]
        walls = self.walls()
        spread = math.radians(self.angle) if self.is_cone() else None
        out = [main]
        if spread is not None:
            lean = spread * 0.5 * self.blur
            for sign in (1.0, -1.0):
                out.append(visibility(self.pos, walls, self.radius,
                                      center=self.radians() + sign * lean,
                                      spread=spread, samples=self.samples))
        else:
            shift = self.radius * 0.16 * self.blur
            for dx, dy in ((shift, 0.0), (-shift, 0.0), (0.0, shift),
                           (0.0, -shift)):
                out.append(visibility((self.pos[0] + dx, self.pos[1] + dy),
                                      walls, self.radius,
                                      samples=self.samples))
        self._copies = len(out)
        return out

    def _ring(self, spread):
        """An even circle or cone, unoccluded."""
        steps = max(8, self.samples // 2)
        if spread is None:
            return None                      # a plain quad does the same job
        half = spread / 2.0
        out = []
        for i in range(steps + 1):
            a = self.radians() - half + spread * i / steps
            out.append((self.pos[0] + math.cos(a) * self.radius,
                        self.pos[1] + math.sin(a) * self.radius))
        return out

    def mesh_for(self):
        """The mask mesh, uv'd so the gradient fits."""
        span = 2.0 * self.radius
        items = self.shapes()
        if self.kind == WORLD:
            # a flat wash: `white` means no texture, an even film
            cx, cy, w, h = self.view_box()
            return meshes.quad2d((cx, cy), (w, h), col=self.color,
                                 uv=(0.0, 0.0, 1.0, 1.0))
        if self.kind == RECT:
            return self._rect_mesh()
        m = meshes.MeshData()
        for shape in items:
            if shape is None:
                m.append(meshes.quad2d(self.pos, (span, span),
                                       col=self.color,
                                       uv=(0.0, 0.0, 1.0, 1.0)))
            elif len(shape) >= 3:
                m.append(self._fan(shape, span))
        return m

    def _rect_mesh(self):
        """A rect or strip as a fan of four corners."""
        pts = self.poly or self.outline() or self._corners()
        w, h = self.size or (self.radius * 2.0, self.radius * 2.0)
        a = -self.radians()
        c, s = math.cos(a), math.sin(a)
        cx, cy = self.pos

        def uv(px, py):
            dx, dy = px - cx, py - cy
            return (0.5 + (dx * c - dy * s) / max(1e-3, w),
                    0.5 + (dx * s + dy * c) / max(1e-3, h))

        m = meshes.MeshData()
        n = (0.0, 0.0, 1.0)
        centre = m.vert((cx, cy, 0.0), n, uv(cx, cy), self.color)
        ring = [m.vert((p[0], p[1], 0.0), n, uv(p[0], p[1]), self.color)
                for p in pts]
        if len(ring) < 3:
            return m
        for i in range(len(ring)):
            m.tri(centre, ring[i], ring[(i + 1) % len(ring)])
        return m

    def _fan(self, points, span):
        """Triangle-fan `points` about the light, uv'd into the gradient."""
        m = meshes.MeshData()
        n = (0.0, 0.0, 1.0)
        cx, cy = self.pos
        col = self.color
        rim = self._feather()
        centre = m.vert((cx, cy, 0.0), n, (0.5, 0.5), col)
        ring = []
        for px, py in points:
            k = 1.0 if rim is None else rim(px - cx, py - cy)
            ring.append(m.vert((px, py, 0.0), n,
                               (0.5 + (px - cx) / span,
                                0.5 + (py - cy) / span),
                               tuple(c * k for c in col)))
        if len(ring) < 3:
            ring = ring * 3
        for a, b in zip(ring, ring[1:] + ring[:1]):
            m.tri(centre, a, b)
        return m

    def strength_at(self, pos):
        """How much of this light reaches a world pixel."""
        if self.intensity <= 0.0:
            return 0.0
        if self.kind == WORLD:
            return self.level()
        if self.kind == RECT and not self.poly:
            # before the first draw, the analytic box answers
            w, h = self.size or (self.radius * 2.0, self.radius * 2.0)
            a = self.radians()
            c, s = math.cos(a), math.sin(a)
            dx = float(pos[0]) - self.pos[0]
            dy = float(pos[1]) - self.pos[1]
            lx = dx * c + dy * s
            ly = -dx * s + dy * c
            if abs(lx) > w / 2.0 or abs(ly) > h / 2.0:
                return 0.0
            return self.level()
        if self.poly and len(self.poly) > 2 and \
                not point_in_polygon(pos, self.poly):
            return 0.0
        if self.kind in (POLY, RECT):
            return self.level()
        d = self.distance_to(pos)
        if self.kind == RING:
            # fold distance onto the band the way the gradient does
            mid = 0.5 * (1.0 + self.hole)
            half = max(1e-3, 1.0 - mid)
            d = min(1.0, abs(d / max(1e-3, self.radius) - mid) / half) \
                * self.radius
        att = atten_value(self.atten, self.falloff or self.soft,
                          self.exponent, d, self.radius)
        if att <= 0.0:
            return 0.0
        if self.is_cone():
            delta = (float(pos[0]) - self.pos[0],
                     float(pos[1]) - self.pos[1])
            n = math.hypot(delta[0], delta[1])
            if n < 1e-6:
                return self.level()
            got = math.degrees(math.atan2(delta[1], delta[0]))
            off = abs(_wrap(math.radians(got - self.dir)))
            if off > math.radians(self.angle / 2.0):
                return 0.0
            rim = self._feather()
            if rim is not None:
                att *= rim(delta[0], delta[1])
        return self.level() * att

    def _sync_mesh(self):
        """Push this light's shape into the renderer's mask pass."""
        if self.scene is None:
            return
        r = self.scene.renderer
        if self.intensity <= 0.0:
            if self.mesh is not None and self.mesh.count:
                self.mesh.update(_empty2d())
            return
        if self.kind == WORLD:
            # follows the camera, since it covers what it sees
            self.dirty = True
        key = r.light_texture(self)
        if self.mesh is None:
            self.mesh = r.new_dynamic(self.mesh_for(), texture=key,
                                      blend=self.blend)
            self.dirty = False
        elif self.dirty:
            self.mesh.update(self.mesh_for())
            self.dirty = False
        # one draw call: falloff is texture, energy is `boost`
        self.mesh.boost = self.level() / max(1, self._copies)
        self.mesh.texture = key
        # a cookie must exist, sheet or colour, else dropped
        self.mesh.cookie = r.resolve_texture(self.cookie) if self.cookie \
            else None

    def _copy_shape(self, other):
        other.set(shape=self.shape_name, dir=self.dir, angle=self.angle,
                  inner=self.inner, soft=self.soft, cast=self.cast,
                  size=self.size, samples=self.samples, blur=self.blur,
                  points=self.points, hole=self.hole)

    def _shape_dict(self):
        return {"shape": self.shape_name, "dir": self.dir,
                "angle": self.angle, "inner": self.inner,
                "soft": self.soft, "cast": self.cast,
                "blur": self.blur, "samples": self.samples,
                "hole": self.hole,
                "size": list(self.size) if self.size else None,
                "points": [list(p) for p in self.points]
                          if self.points else None}


def _empty3d():
    """One degenerate triangle: an empty-but-valid mesh nothing draws."""
    m = meshes.MeshData()
    v = m.vert((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0), (0.0, 0.0, 0.0))
    m.tri(v, v, v)
    return m


_empty2d = _empty3d


def coerce(entry, scene=None):
    """A Light for anything a scene lists."""
    if isinstance(entry, Light):
        return entry
    if isinstance(entry, dict):
        pos = entry.get("pos") or (0.0, 0.0, 0.0)
        cls = Light2D if len(pos) <= 2 else Light3D
        fallback = 190.0 if cls is Light2D else 0.0
        return cls(scene, pos=pos, color=entry.get("color", "torch"),
                   energy=entry.get("energy", 1.0),
                   radius=entry.get("radius", fallback),
                   enabled=entry.get("enabled", True),
                   tag=entry.get("tag"))
    cls = Light2D if len(getattr(entry, "pos", (0, 0, 0))) <= 2 else Light3D
    return cls(scene, pos=getattr(entry, "pos", None),
               color=getattr(entry, "color", "torch"))


# presets are shortcuts: plain constructor keywords
PRESETS = {
    "candle": dict(color="flame", energy=0.55, radius=2.6, falloff=0.1,
                   flicker=0.34, flicker_rate=11.0, glow=0.22),
    "campfire": dict(color="flame", energy=1.15, radius=9.0, falloff=0.12,
                     flicker=0.26, flicker_rate=8.0, glow=0.9),
    "torch": dict(color="torch", energy=1.0, radius=14.0, shape="spot",
                  angle=54, inner=0.5, flicker=0.18, glow=0.5),
    "lantern": dict(color="torch", energy=0.9, radius=8.0, flicker=0.12,
                    glow=0.7, soft=0.2),
    "flashlight": dict(color="white", energy=1.3, radius=26.0, shape="spot",
                       angle=34, inner=0.85, falloff=0.05, atten="power",
                       exponent=1.4),
    "bulb": dict(color="white", energy=0.95, radius=10.0, falloff=0.35),
    "streetlamp": dict(color=(255, 214, 150), energy=1.1, radius=16.0,
                       falloff=0.2, flicker=0.03, flicker_rate=3.0),
    "neon": dict(color="cyan", energy=1.1, radius=12.0, falloff=0.55,
                 flicker=0.05, flicker_rate=17.0, soft=0.6),
    "fluorescent": dict(color="white", energy=1.0, radius=13.0,
                        falloff=0.45, flicker=0.4,
                        flicker_style="fluorescent", flicker_rate=13.0),
    "siren": dict(color="red", energy=1.6, radius=22.0, shape="spot",
                  angle=70, spin=1.2, strobe=(9.0, 0.45)),
    "lighthouse": dict(color="white", energy=2.0, radius=60.0, shape="spot",
                       angle=12, inner=0.7, spin=6.0),
    "searchlight": dict(color="white", energy=1.8, radius=40.0, shape="spot",
                        angle=18, inner=0.4, sweep=(-0.8, 0.8, 5.0)),
    "firefly": dict(color="gold", energy=0.6, radius=2.2, pulse=0.6,
                    pulse_rate=0.7, glow=0.5, soft=0.3),
    "lava": dict(color="blood", energy=0.8, radius=6.0, pulse=0.2,
                 pulse_rate=0.25, soft=0.4),
    "monitor": dict(color="blue", energy=0.7, radius=5.0, flicker=0.06,
                    flicker_rate=23.0, soft=0.5),
    "sun": dict(shape="sun", color="white", energy=0.8,
                dir=sun_direction(10.0)),
    "tube": dict(color="white", energy=1.0, radius=7.0, shape="tube",
                 length=8.0, falloff=0.45, soft=0.45),
    # 2D shapes that are worth having by name
    "pool": dict(color="white", energy=0.35, radius=160.0, soft=0.3),
    "doorway": dict(color="white", energy=0.7, shape="rect", radius=160.0,
                    size=(120.0, 200.0)),
    "strip": dict(color="cyan", energy=0.9, radius=200.0, shape="strip",
                  length=200.0, width=14.0, soft=0.4),
    "ping": dict(color="cyan", energy=0.9, radius=220.0, shape="ring",
                 hole=0.7, soft=0.1,
                 grow={"secs": 1.6, "dim": True, "loop": True}),
    "wash": dict(color="white", energy=0.3, shape="world"),
    "blackout": dict(color="white", energy=1.0, shape="world",
                     negative=True),
    "void": dict(color="white", energy=1.0, radius=180.0, soft=0.35,
                 negative=True),
    "shadow": dict(color="white", energy=0.75, radius=90.0, soft=0.2,
                   negative=True),
}
# presets that only make sense in a pixel world
_2D_ONLY = ("pool", "doorway", "void", "shadow", "strip", "ping", "wash",
            "blackout")
# a 3D shape name has no 2D twin; borrow closest
_DIM_SHAPE = {"spot": "cone", "point": "radial", "sun": "radial",
              "cone": "cone", "radial": "radial", "rect": "rect",
              "poly": "poly", "tube": "strip", "strip": "strip",
              "ring": "ring", "world": "world"}


def preset(name, scene=None, pos=None, dim=None, tag=None, **kw):
    """A common light, ready to drop in."""
    spec = dict(PRESETS.get(str(name), {}))
    spec.update(kw)
    if dim is None:
        dim = 2 if str(name) in _2D_ONLY else 3
    cls = Light2D if int(dim) == 2 else Light3D
    verbs = {}
    for word in ("spin", "sweep", "strobe", "sputter", "ramp", "orbit",
                 "sway", "path", "gate", "grow"):
        if word in spec:
            verbs[word] = spec.pop(word)
    shape = spec.pop("shape", None)
    if cls is Light2D:
        shape = _DIM_SHAPE.get(str(shape or "").lower(), shape)
        if shape in (None, "sun"):
            shape = "radial"
    elif shape == "cone":
        shape = "spot"
    accepted = _ctor_names(cls)
    ctor = {k: v for k, v in spec.items() if k in accepted}
    rest = {k: v for k, v in spec.items() if k not in accepted}
    if shape:
        ctor["shape"] = shape
    if cls is Light3D:
        ctor["dir"] = ctor.pop("dir", None) or _dir3(0.0, -0.6)
    light = cls(scene, pos=pos, tag=tag or str(name), **ctor)
    if rest:
        light.set(**rest)
    _apply_verbs(light, verbs)
    return light


def _ctor_names(cls):
    """The keyword names a light class actually takes."""
    got = set()
    for target in (cls, Light):
        try:
            got.update(inspect.signature(target.__init__).parameters)
        except (TypeError, ValueError):
            pass
    got.discard("self")
    got.discard("kw")
    got.add("shape")
    return got


_SPREAD = ("sweep", "strobe", "sputter", "orbit", "sway")
_WHOLE = ("ramp", "path", "gate", "grow")


def _apply_verbs(light, verbs):
    """Run a preset's animation verbs in order."""
    for word in _WHOLE:
        if word in verbs:
            got = getattr(light, word, None)
            if got is None:
                continue
            value = verbs[word]
            if isinstance(value, dict):
                got(**value)
            else:
                got(value)
    for word in _SPREAD:
        if word in verbs:
            got = getattr(light, word, None)
            if got is None:
                continue
            value = verbs[word]
            if isinstance(value, (list, tuple)):
                got(*value)
            else:
                got(value)
    if "spin" in verbs and hasattr(light, "spin"):
        light.spin(verbs["spin"])
