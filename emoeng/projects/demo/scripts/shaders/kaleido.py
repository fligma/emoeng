"""fold a surface's own picture into turning wedges, and dye them"""

import emoeng as fe


class Kaleido(fe.Shader):
    name = "kaleido"
    mode = "uv"
    knobs = {"sides": 8.0, "spin": 0.18, "amount": 0.8}

    def frag(self, g):
        # there is no angle to read off a mesh, so the fold is cut from
        # what a surface does have: which way it faces, and where its
        # sheet has run to. Both are folded back on themselves, which is
        # what makes neighbouring faces mirror each other.
        face = g.dot(g.normal, g.vec3(1.7, 2.3, 3.1))
        wedge = g.fract(g.dot(g.uv, g.vec2(self.sides, self.sides * 0.6))
                        + g.time * self.spin + face * 0.11)
        folded = g.abs(wedge * 2.0 - 1.0)
        sheet = g.tex(g.uv * g.vec2(folded + 0.25, 1.0 - folded * 0.5))
        dye = g.hue(g.fract(folded + g.time * 0.05))
        g.out = g.mix(sheet, dye, self.amount)
