"""Star dome and moon: two additive dynamic meshes rebuilt around the eye.

Cheaper and clearer than a skybox: ~200 tiny glow quads plus the moon
disc, all inside the fog so they fade out with distance. The entity reads
`self.game.eye` every frame, so the sky stays put while the player walks.
"""

import math
import random

import fligengine as fe
from fligengine.engine import meshes


def _norm(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _quad(md, centre, normal, size, col):
    """One camera-facing quad, emitted twice so it reads from both sides."""
    helper = (0.0, 1.0, 0.0) if abs(normal[1]) < 0.98 else (1.0, 0.0, 0.0)
    right = _norm(_cross(normal, helper))
    up = _cross(right, normal)
    pts = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        pts.append((centre[0] + (right[0] * sx + up[0] * sy) * size,
                    centre[1] + (right[1] * sx + up[1] * sy) * size,
                    centre[2] + (right[2] * sx + up[2] * sy) * size))
    uv = ((0, 0), (1, 0), (1, 1), (0, 1))
    i = [md.vert(p, normal, uv[k], col) for k, p in enumerate(pts)]
    for tri in ((0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)):
        md.tri(i[tri[0]], i[tri[1]], i[tri[2]])


class Stars(fe.Entity):
    name = "stars"
    uses = ()
    clone_attrs = ("radius", "count")
    MOON_DIR = (-0.10, 0.36, -0.93)

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 radius=46.0, count=200, seed=31):
        super().__init__(scene, pos, yaw, scale)
        self.radius = float(radius)
        self.count = int(count)
        self.stars = []
        rng = random.Random(seed)
        for _ in range(self.count):
            a = rng.uniform(0.0, math.tau)
            e = math.asin(rng.uniform(0.06, 1.0)) ** 0.72
            d = (math.cos(e) * math.sin(a), math.sin(e),
                 math.cos(e) * math.cos(a))
            self.stars.append((d, rng.uniform(0.9, 1.9),
                               rng.uniform(0.35, 1.0),
                               rng.uniform(0.0, math.tau),
                               rng.uniform(0.4, 1.7),
                               rng.random() < 0.22))
        self.moon = _norm(self.MOON_DIR)
        self.mesh = None
        self.moon_mesh = None

    def build(self):
        eye = self.game.eye
        self.mesh = self.dynamic(self._mesh(eye), texture="glow",
                                 blend="add")
        self.moon_mesh = self.dynamic(self._moon_mesh(eye), texture="moon",
                                      blend="add")

    # ------------------------------------------------------------ geometry
    def _mesh(self, eye):
        md = meshes.MeshData()
        for d, size, mag, phase, speed, warm in self.stars:
            k = 0.68 + 0.32 * math.sin(self.t * speed + phase)
            b = mag * k
            col = (3.4 * b, 2.2 * b, 1.2 * b) if warm else \
                (1.9 * b, 2.2 * b, 4.4 * b)
            p = (eye[0] + d[0] * self.radius,
                 eye[1] + d[1] * self.radius,
                 eye[2] + d[2] * self.radius)
            _quad(md, p, d, size * k, col)
        d = self.moon
        p = (eye[0] + d[0] * self.radius * 1.04,
             eye[1] + d[1] * self.radius * 1.04,
             eye[2] + d[2] * self.radius * 1.04)
        _quad(md, p, d, 8.5, (0.55, 0.60, 0.82))
        return md

    def _moon_mesh(self, eye):
        md = meshes.MeshData()
        d = self.moon
        # closer than the halo: two additive quads at the same distance
        # z-fight, and the later one loses the depth test
        p = (eye[0] + d[0] * self.radius * 0.92,
             eye[1] + d[1] * self.radius * 0.92,
             eye[2] + d[2] * self.radius * 0.92)
        _quad(md, p, d, 2.6, (1.50, 1.54, 1.66))
        return md

    def update(self, dt):
        super().update(dt)
        eye = self.game.eye
        self.mesh.update(self._mesh(eye))
        self.moon_mesh.update(self._moon_mesh(eye))
