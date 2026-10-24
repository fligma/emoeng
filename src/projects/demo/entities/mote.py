"""Mote: the Collision Arena collectable - one additive glow quad.

Arena spawns and despawns these from update() and on timers, so it is
also the demo's example of an entity whose lifetime is owned by gameplay
rather than by setup().
"""

import math

import fligengine as fe
from fligengine.engine import meshes


class Mote(fe.Entity):
    name = "mote"
    uses = ()
    clone_attrs = ("tint",)

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 tint=(1.0, 0.62, 0.30)):
        super().__init__(scene, pos, yaw, scale)
        self.tint = tint
        self.mesh = None

    def build(self):
        self.mesh = self.dynamic(
            meshes.billboards(self.pos, 1.1, 1.1, 2, self.tint),
            texture="glow", blend="add")

    def update(self, dt):
        super().update(dt)
        y = self.pos[1] + 0.16 * math.sin(self.t * 3.2)
        size = 1.0 + 0.16 * math.sin(self.t * 4.0)
        self.mesh.update(meshes.billboards(
            (self.pos[0], y, self.pos[2]), size, size, 2, self.tint))
