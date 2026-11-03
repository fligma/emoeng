"""breathe a slow colour wheel through a surface, on the sheet's own shape"""

import emoeng as fe


class TintPulse(fe.Shader):
    name = "tintpulse"
    mode = "uv"
    knobs = {"speed": 0.5, "depth": 0.75}

    def frag(self, g):
        sheet = g.tex(g.uv)
        # the wheel rides the sheet's brightness, so the pattern survives
        wheel = g.hue(g.fract(g.time * self.speed * 0.12 + g.grey(sheet)))
        swell = 0.5 + 0.5 * g.sin(g.time * self.speed)
        g.out = g.mix(sheet, wheel, self.depth * swell)
