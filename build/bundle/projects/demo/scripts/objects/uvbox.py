"""UVBox: a cube that runs a uv shader of its own."""

import emoeng as fe
from emoeng.engine import meshes


class UVBox(fe.Object3D):
    name = "uvbox"
    side = 1.8                    # metres, a cube on the plinth

    def build(self):
        x, y, z = self.pos
        self.add(meshes.box((x, y + self.side * 0.5, z),
                            (self.side, self.side, self.side)),
                 texture="grid")
