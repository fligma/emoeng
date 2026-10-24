"""Bonfire: brazier, point light and a cluster of child Flames.

This is the entity-to-entity case. `uses` names entities/flame.py, the
module imports that class directly, and every flame is spawned through
the scene API - so the flames are tracked, updated and disposed like any
other entity, and despawning the bonfire takes its flames with it.
"""

import math

import fligengine as fe
from entities.flame import Flame


class Bonfire(fe.Entity):
    name = "bonfire"
    uses = ("flame",)                      # entity files this one spawns
    clone_attrs = ("flames", "size", "tint")

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 flames=3, size=1.3, tint=(1.0, 0.48, 0.14)):
        super().__init__(scene, pos, yaw, scale)
        self.flames = int(flames)
        self.size = float(size)
        self.tint = tint
        self.fire = None
        self.sparks = []

    def build(self):
        self.place_model("brazier", self.pos, self.yaw, self.scale)
        self.fire = self.light(
            (self.pos[0], self.pos[1] + 1.9 * self.scale, self.pos[2]),
            (0.95, 0.45, 0.18))
        count = max(1, self.flames)
        size = self.size * self.scale
        # the brazier bowl starts at y=0.72 in the model, so lift the flame
        # to sit inside it - a billboard centred lower pokes out under the
        # stem and reads as fire leaking out of the bottom
        lift = 0.72 * self.scale + 0.85 * size
        for i in range(count):
            a = math.tau * i / count
            r = 0.16 * self.scale
            self.sparks.append(self.spawn(
                Flame,
                offset=(math.cos(a) * r, lift, math.sin(a) * r),
                size=size, tint=self.tint))

    def update(self, dt):
        super().update(dt)
        warm = 0.46 + 0.13 * math.sin(self.t * 11.0)
        self.fire["color"] = (1.0, warm, 0.16 + 0.04 * math.sin(self.t * 17.0))
