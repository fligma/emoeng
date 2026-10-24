"""Orb: a collectable eye - a spinning model plus an additive halo.

Two kinds of owned geometry, both released by dispose():
`model_object` is a tracked dynamic model instance, `dynamic` is the raw
glow billboard. `take()` despawns the orb, so the scene stops updating it
and the meshes go back to the renderer.
"""

import math

import fligengine as fe
from fligengine.engine import meshes


class Orb(fe.Entity):
    name = "orb"
    uses = ()
    clone_attrs = ("model", "tint", "halo")

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 model="orb", tint=(1.0, 0.92, 0.62),
                 halo=(1.0, 0.72, 0.30)):
        super().__init__(scene, pos, yaw, scale)
        self.model = model
        self.tint = tint
        self.halo = halo
        self.taken = False
        self.obj = None
        self.glow = None

    def build(self):
        self.obj = self.model_object(self.model, self.pos, 0.0, 1.0,
                                     self.tint)
        self.glow = self.dynamic(meshes.billboards(self.pos, 1.6, 1.6, 2,
                                                   self.halo),
                                 texture="glow", blend="add")

    def position(self):
        return (self.obj.pos[0], self.obj.pos[1], self.obj.pos[2])

    def update(self, dt):
        super().update(dt)
        bob = math.sin(self.t * 2.0) * 0.13
        pos = (self.pos[0], self.pos[1] + bob, self.pos[2])
        self.obj.set(pos=pos, yaw=self.t * 1.5)
        self.obj.update()
        pulse = 1.5 + 0.35 * math.sin(self.t * 3.0)
        self.glow.update(meshes.billboards(pos, pulse, pulse, 2, self.halo))

    def close(self, eye, dist=2.7):
        """True when `eye` is near enough to pick this up."""
        return not self.taken and math.dist(self.position(), eye) < dist

    def take(self):
        """Pick the orb up: stop animating and release its geometry."""
        if self.taken:
            return self
        self.taken = True
        self.despawn()
        return self
