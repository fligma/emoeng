"""Floor: one slab, and the only thing you can stand on."""

import emoeng as fe
from emoeng.engine import meshes


class Floor(fe.Object3D):
    name = "floor"
    span = 128.0                  # metres across, so the edge stays in fog
    seg = 4                       # flat: the segments only carry uv and depth

    def build(self):
        x, y, z = self.pos
        self.add(meshes.plane((x, y, z), (self.span, self.span), seg=self.seg,
                              uv_scale=1.0), texture="stone")
