"""A gentle animated chromatic warp for both demo rooms."""

import emoeng as fe


class Trippy(fe.Shader):
    name = "trippy"
    mode = "screen"
    knobs = {"warp": 0.025, "hue": 0.3}

    def frag(self, g):
        x_wave = g.sin(g.dot(g.uv, g.vec2(0.0, 34.0)) + g.time * 1.7)
        y_wave = g.sin(g.dot(g.uv, g.vec2(46.0, 0.0)) - g.time * 1.2)
        warped = g.uv + g.vec2(x_wave * self.warp,
                               y_wave * self.warp)
        color = g.clamp(g.tex(warped) * 1.25, 0.0, 1.0)
        hue = g.hue(g.fract(g.time * 0.035 +
                            g.noise(warped, 9.0) * 0.15))
        g.out = g.mix(color, hue, self.hue)
