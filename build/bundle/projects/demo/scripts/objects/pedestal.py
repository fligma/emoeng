"""Pedestal: the plinth a showcase stands on, and the shape it blocks with."""

import emoeng as fe
from emoeng.engine import meshes


class Pedestal(fe.Object3D):
    name = "pedestal"
    doc_knobs = fe.Object3D.doc_knobs + ("width", "depth", "height")

    width = 2.6                   # metres across, and the same deep
    depth = 2.6
    height = 0.9

    def build(self):
        x, y, z = self.pos
        # cut stone like the floor, warmed so a plinth reads as furniture
        self.add(meshes.box((x, y + self.height * 0.5, z),
                            (self.width, self.height, self.depth),
                            col=(0.74, 0.66, 0.56)),
                 texture="stone", blend="opaque")
