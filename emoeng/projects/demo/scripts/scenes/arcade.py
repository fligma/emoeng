"""A 2D companion room with colored light pools and a shifting portal."""

import math

import emoeng as fe
from emoeng.engine import meshes


WORLD = (1280.0, 720.0)


class Arcade(fe.Scene2D):
    """A flat architectural room; Tab returns to the 3D hall."""

    name = "arcade"
    world_size = WORLD
    scale_mode = "fit"
    post = ("trippy",)
    clear_color = (0.025, 0.03, 0.065)
    ambient2d = (0.23, 0.2, 0.32)
    actions = {"other_room": ["tab"]}
    controls = ("other_room",)

    def setup(self):
        self._architecture()
        self._portals()
        self._lights()
        self.add_light(pos=(640.0, 385.0), color="#ed7cff",
                       energy=1.35, radius=390.0, shape="radial",
                       pulse=0.12, pulse_rate=0.32)

    def _architecture(self):
        self.add(meshes.rect2d((640, 360), WORLD,
                               col=(0.25, 0.19, 0.32), layer=-20),
                 texture="stone", blend="alpha",
                 uv=(0.0, (8.0, 5.0)))
        self.add(meshes.rect2d((640, 465), (1140, 390),
                               col=(0.56, 0.4, 0.37), layer=-18),
                 texture="rust", blend="alpha",
                 uv=(0.0, (7.0, 3.0)))
        # The back wall, side returns and skirting make a clear room shape.
        self.add(meshes.rect2d((640, 112), (1140, 142),
                               col=(0.56, 0.61, 0.76), layer=-18),
                 texture="stone", blend="alpha",
                 uv=(0.0, (7.0, 1.0)))
        for x in (82, 1198):
            self.add(meshes.rect2d((x, 360), (96, 520),
                                   col=(0.34, 0.4, 0.56), layer=-17),
                     texture="stone", blend="alpha",
                     uv=(0.0, (1.0, 4.0)))
        self.add(meshes.rect2d((640, 258), (1140, 24),
                               col=(0.82, 0.62, 0.42), layer=-16),
                 texture="bark", blend="alpha")

        # Floor tiles and a runner lead toward the central arch.
        for row in range(4):
            y = 287 + row * 96
            self.add(meshes.rect2d((640, y), (1060, 6),
                                   col=(0.7, 0.48, 0.39), layer=-16),
                     texture="white", blend="alpha")
        self.add(meshes.rect2d((640, 462), (260, 390),
                               col=(0.32, 0.24, 0.4), layer=-15),
                 texture="cloth", blend="alpha",
                 uv=(0.0, (1.0, 3.0)))

        # Warm overhead beams echo the timber ribs of the 3D hall.
        for x in (160, 1120):
            self.add(meshes.rect2d((x, 74), (28, 76),
                                   col=(0.57, 0.35, 0.23), layer=-15),
                     texture="bark", blend="alpha")
        self.add(meshes.rect2d((640, 37), (1136, 25),
                               col=(0.62, 0.4, 0.27), layer=-15),
                 texture="bark", blend="alpha")

    def _portals(self):
        for cx in (340.0, 640.0, 940.0):
            # Dark portal well behind a pale block-built arch.
            self.add(meshes.rect2d((cx, 156), (154, 174),
                                   col=(0.12, 0.11, 0.2), layer=-14),
                     texture="white", blend="alpha")
            portal_mesh = meshes.rect2d((cx, 156), (130, 168),
                                        col=(0.76, 0.9, 1.0), layer=-13)
            self.dynamic(portal_mesh, texture="glow", blend="alpha",
                         shader="portal")
            self.add(meshes.rect2d((cx - 86, 140), (30, 200),
                                   col=(0.66, 0.68, 0.72), layer=-12),
                     texture="stone", blend="alpha")
            self.add(meshes.rect2d((cx + 86, 140), (30, 200),
                                   col=(0.66, 0.68, 0.72), layer=-12),
                     texture="stone", blend="alpha")
            for index in range(7):
                angle = math.pi * index / 6.0
                x = cx + math.cos(angle) * 86
                y = 133 - math.sin(angle) * 86
                self.add(meshes.rect2d((x, y), (34, 24),
                                       col=(0.76, 0.72, 0.68),
                                       rot=angle + math.pi / 2.0,
                                       layer=-12),
                         texture="stone", blend="alpha")
            self.add_light(pos=(cx, 180), color="#66dfff",
                           energy=1.3, radius=205.0, shape="radial",
                           pulse=0.14, pulse_rate=0.4)

    def _lights(self):
        for x, color in ((230.0, "#ffaf76"), (640.0, "#b47cff"),
                         (1050.0, "#69dbff")):
            self.add_light(pos=(x, 234.0), color=color, energy=0.9,
                           radius=300.0, shape="radial", flicker=0.04,
                           flicker_rate=1.7)

    def update(self, dt):
        super().update(dt)
        if self.input.pressed("other_room"):
            self.play_scene("main")

    def overlay(self, screen):
        area = self.hud.area
        self.hud.panel((area.x + 14, area.y + 12, 320, 66),
                       color=(13, 17, 29), alpha=195)
        self.hud.text("DEMO  /  THE ECHO ROOM",
                      (area.x + 26, area.y + 20),
                      color=(0.84, 0.7, 1.0))
        self.hud.text("Three shifting arches  -  Tab for the 3D hall",
                      (area.x + 26, area.y + 45))

    def status(self):
        return [self.name, "Echo Room", f"{len(self.lights)} lights"]
