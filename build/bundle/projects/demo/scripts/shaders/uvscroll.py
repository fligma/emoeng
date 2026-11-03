"""slide a mesh's own sheet across it, forwards and sideways"""

import emoeng as fe


class UvScroll(fe.Shader):
    name = "uvscroll"
    mode = "uv"
    knobs = {"speed": 0.35, "tilt": 0.0, "hue": -1.0}

    def frag(self, g):
        moved = g.wmuv(g.uv, g.vec2(self.speed, self.tilt), 1.0)
        sheet = g.tex(moved)
        # a hue below zero keeps the sheet; 0..1 washes it round the wheel
        g.out = g.mix(sheet, g.hue(g.max(self.hue, 0.0)),
                      g.clamp(self.hue, 0.0, 1.0))
