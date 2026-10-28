"""Lamp: a slim post and shade, so a light has somewhere to sit."""

import emoeng as fe
from emoeng.engine import meshes


class Lamp(fe.Object3D):
    name = "lamp"
    doc_knobs = fe.Object3D.doc_knobs + ("height", "radius")

    height = 1.6                  # metres from its foot to the shade
    radius = 0.09                 # the post's own thickness

    def build(self):
        x, y, z = self.pos
        top = y + self.height
        self.add(meshes.cylinder((x, y + self.height * 0.5, z),
                                 r=self.radius, h=self.height, seg=10),
                 texture="rust")
        self.add(meshes.cylinder((x, top + 0.05, z), r=0.32, h=0.1, seg=12),
                 texture="rust")
        # an unlit warm bead, so the shade reads as the source
        self.add(meshes.cylinder((x, top + 0.16, z), r=0.11, h=0.18, seg=8,
                                 col=(1.0, 0.72, 0.42)),
                 texture="white", blend="add")
