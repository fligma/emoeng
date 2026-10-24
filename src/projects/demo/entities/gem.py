"""Gem: a spinning model with a glow, built to be cloned.

`clone_attrs = ("size", "tint")` is the whole contract: `gem.clone(pos,
tint=...)` builds a second Gem that keeps those knobs but owns its own
geometry and clock, and the engine records the relationship - is_clone,
clone_of, root, depth and lineage all answer from that record.
"""

import math

import fligengine as fe
from fligengine.engine import meshes


class Gem(fe.Entity):
    name = "gem"
    uses = ()
    clone_attrs = ("size", "tint")

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 size=0.85, tint=(0.60, 0.82, 1.0)):
        super().__init__(scene, pos, yaw, scale)
        self.size = float(size)
        self.tint = tint
        self.obj = None
        self.glow = None

    def build(self):
        self.obj = self.model_object("orb", self.pos, 0.0, self.size,
                                     self.tint)
        pulse = self._pulse()
        self.glow = self.dynamic(
            meshes.billboards(self.pos, pulse, pulse, 2, self.tint),
            texture="glow", blend="add")

    def _pulse(self):
        return (1.35 + 0.24 * math.sin(self.t * 2.6 + self.pos[0])) * \
            (0.55 + 0.75 * self.size)

    def update(self, dt):
        super().update(dt)
        lift = 0.12 * math.sin(self.t * 1.7 + self.pos[0])
        pos = (self.pos[0], self.pos[1] + lift, self.pos[2])
        self.obj.set(pos=pos, yaw=self.t * 0.9, scale=self.size)
        self.obj.update()
        pulse = self._pulse()
        self.glow.update(meshes.billboards(pos, pulse, pulse, 2, self.tint))
