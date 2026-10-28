"""Board: the physical panel a nested UI scene is shown on."""

import math

import emoeng as fe
from emoeng.engine import meshes


class Board(fe.Screen3D):
    name = "board"
    pixels = (352, 198)           # the nested UI is drawn at this size
    brightness = 1.08             # a touch hot, so it reads from the floor
    audio_mode = "global"
    frame_col = (0.30, 0.32, 0.38)
    mount_base = 0.9

    def build(self):
        self.frame = None
        self.mount = []
        self._draw_frame()
        super().build()

    def _draw_frame(self):
        """The bezel as one mesh of its own, so it can be switched off."""
        w, h = self.size
        fx, fz = math.sin(self.yaw), math.cos(self.yaw)
        # the bezel sits behind the glass, so the two never share a plane
        centre = (self.pos[0] - fx * 0.06, self.pos[1],
                  self.pos[2] - fz * 0.06)
        self.frame = self.dynamic(
            meshes.box(centre=centre, size=(w + 0.36, h + 0.36, 0.1),
                       yaw=self.yaw, col=self.frame_col),
            texture=None, blend="opaque")
        bottom = self.pos[1] - h * 0.5
        mount_x = self.pos[0] - fx * 0.14
        mount_z = self.pos[2] - fz * 0.14
        stem_height = max(0.1, bottom - self.mount_base)
        self.mount.append(self.dynamic(
            meshes.box(centre=(mount_x, self.mount_base - 0.06, mount_z),
                       size=(0.52, 0.12, 0.34), yaw=self.yaw,
                       col=(0.24, 0.27, 0.32)),
            texture="steel", blend="opaque"))
        self.mount.append(self.dynamic(
            meshes.cylinder((mount_x,
                             (bottom + self.mount_base) * 0.5, mount_z),
                            r=0.075, h=stem_height, seg=10,
                            col=(0.32, 0.36, 0.42)),
            texture="steel", blend="opaque"))
        return self.frame

    def set_frame(self, on=True):
        """Show the bezel, or leave the glass floating on its own."""
        if self.frame is None:
            self._draw_frame()
        self.frame.set_opacity(1.0 if on else 0.0)
        return bool(on)
