"""darken every other row, the way a tube monitor did"""

import emoeng as fe


class Scanlines(fe.Shader):
    name = "scanlines"
    mode = "screen"
    knobs = {"amount": 0.35, "lines": 90.0}

    def frag(self, g):
        row = g.dot(g.pixel, g.vec2(0.0, 1.0))
        high = g.dot(g.size, g.vec2(0.0, 1.0))
        band = g.fract(row * self.lines / g.max(high, 1.0))
        dim = g.mix(1.0, 1.0 - self.amount, g.step(0.5, band))
        g.out = g.color * dim
