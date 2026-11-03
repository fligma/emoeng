"""tear the picture sideways along random scanline bands, and ghost it"""

import emoeng as fe


class Glitch(fe.Shader):
    name = "glitch"
    mode = "screen"
    knobs = {"tear": 0.05, "jump": 0.012, "rows": 60.0}

    def frag(self, g):
        # one hash per band per eighth of a second decides who slips, so
        # whole strips shift together instead of every pixel jittering
        down = g.dot(g.pixel, g.vec2(0.0, 1.0))
        height = g.dot(g.size, g.vec2(0.0, 1.0))
        band = g.floor(down * self.rows / g.max(height, 1.0))
        beat = g.floor(g.time * 8.0)
        dice = g.noise(g.vec2(band, beat), 7.0)
        slip = (dice - 0.5) * self.tear * g.step(0.62, dice)
        here = g.uv + g.vec2(slip, self.jump * (dice - 0.5))
        body = g.tex(here)
        # a half-frame echo, offset the other way, reads as a bad signal
        ghost = g.tex(g.uv - g.vec2(slip * 0.7, self.jump))
        torn = g.mix(body, ghost, 0.4)
        g.out = g.mix(torn, g.hue(dice), g.step(0.9, dice) * 0.35)
