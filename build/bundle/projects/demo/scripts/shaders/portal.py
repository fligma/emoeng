"""An animated, noisy energy field for the room's portal arches."""

import emoeng as fe


class Portal(fe.Shader):
    name = "portal"
    mode = "uv"
    knobs = {"speed": 0.32}

    def frag(self, g):
        rising = g.wmuv(g.uv, (0.08, self.speed), 1.0)
        drifting = g.wmuv(g.uv, (-0.12, self.speed * 0.65), 1.0)
        field = g.clamp(0.18 + g.noise(rising, 23.0) * 0.56
                        + g.noise(drifting, 47.0) * 0.42, 0.0, 1.0)
        g.out = g.mix(g.vec3(0.015, 0.12, 0.18),
                      g.vec3(0.18, 0.92, 0.78), field)
