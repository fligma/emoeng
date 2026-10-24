"""Flame: a camera-crossed additive billboard that flickers every frame.

The smallest useful entity - it owns exactly one dynamic mesh, rebuilds it
in update() and lets dispose() (called by scene.despawn) free it again.
`size` and `tint` are in clone_attrs, so `flame.clone(pos)` builds a copy
that keeps the same look and knows it is one.
"""

import math

import fligengine as fe
from fligengine.engine import meshes


class Flame(fe.Entity):
    name = "flame"
    uses = ()                              # spawns no other entities
    clone_attrs = ("size", "tint")         # what clone() carries over

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 size=1.0, tint=(1.0, 0.50, 0.15)):
        super().__init__(scene, pos, yaw, scale)
        self.size = float(size)
        self.tint = tint

    def build(self):
        self.mesh = self.dynamic(self._mesh(), texture="flame", blend="add")

    def _mesh(self):
        wob = 1.0 + 0.10 * math.sin(self.t * 9.0) + \
            0.06 * math.sin(self.t * 23.0)
        w = 1.1 * self.size * wob
        h = 1.7 * self.size * (0.9 + 0.18 * math.sin(self.t * 13.0 + 1.3))
        return meshes.billboards(self.pos, w, h, 2, self.tint)

    def update(self, dt):
        super().update(dt)
        self.mesh.update(self._mesh())
