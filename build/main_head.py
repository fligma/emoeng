"""A small stone hall lit by warm sconces and a restless portal."""

import math

import emoeng as fe
from emoeng.engine import meshes


class Arch(fe.Object3D):
    """Block-built stone arch with a living portal in its opening."""

    def build(self):
        cx, cy, cz = self.pos
        yaw = self.yaw
        for side in (-1, 1):
            x = cx + side * 1.1
            self.add(meshes.box(centre=(x, cy + 1.2, cz),
                                size=(0.42, 2.4, 0.62), yaw=yaw,
                                col=(0.64, 0.63, 0.59)),
                     texture="stone")
        for i in range(9):
            angle = math.pi * i / 8.0
            x = cx + math.cos(angle) * 1.1
            y = cy + 2.35 + math.sin(angle) * 1.1
            self.add(meshes.box(centre=(x, y, cz),
                                size=(0.42, 0.34, 0.62),
                                yaw=yaw, lean=angle + math.pi / 2.0,
                                col=(0.72, 0.70, 0.64)),
                     texture="stone")
        portal = meshes.box(centre=(cx, cy + 1.35, cz + 0.08),
                            size=(1.74, 2.36, 0.035), yaw=yaw,
                            col=(0.86, 0.96, 1.0))
        self.add(portal, texture="glow", blend="add", shader="portal")
        for side in (-1, 1):
            self.add(meshes.box(centre=(cx + side * 1.43, cy + 1.25,
                                        cz + 0.06),
                                size=(0.08, 2.45, 0.12), yaw=yaw,
                                col=(0.24, 0.76, 0.95)),
                     texture="glow", blend="add")


class Main(fe.Scene3D):
    """Walk around the 3D hall; Tab opens its 2D companion room."""

    name = "main"
    actions = {"other_room": ["tab"]}
    controls = ("forward", "back", "left", "right", "run", "other_room")
    post = ("trippy",)
    world_radius = 0.0
    clear_color = (0.025, 0.035, 0.06)
    ambient = (0.32, 0.34, 0.42)
    sun_dir = (-0.3, 0.88, -0.5)
    sun_col = (0.35, 0.4, 0.62)
    fog_color = (0.025, 0.035, 0.06)
    fog_near = 18.0
    fog_far = 42.0

    def setup(self):
        self._room()
        self._lights()
        self.player = self.spawn(
            fe.Player3D, pos=(0.0, 0.0, 5.2), yaw=math.pi,
            eye_height=1.72, move_speed=(3.6, 6.0), world_radius=0.0)

    def spawn_point(self):
        return (0.0, 0.0, 5.2), math.pi

    def _room(self):
        self.add(meshes.plane(centre=(0.0, -0.08, 0.0),
                              size=(16.0, 20.0), seg=16, uv_scale=10.0),
                 texture="stone")

        # Back wall has a broad opening for the central arch.
        for x in (-6.0, 6.0):
            self.add(meshes.box(centre=(x, 2.5, -9.7),
                                size=(4.0, 5.0, 0.48),
                                col=(0.7, 0.69, 0.64), uv=(3, 2)),
                     texture="stone")
        self.add(meshes.box(centre=(0.0, 4.65, -9.7),
                            size=(8.0, 0.7, 0.48),
                            col=(0.7, 0.69, 0.64), uv=(4, 1)),
                 texture="stone")
        for x in (-7.8, 7.8):
            self.add(meshes.box(centre=(x, 2.5, 0.0),
                                size=(0.45, 5.0, 19.8),
                                col=(0.62, 0.64, 0.66), uv=(2, 8)),
                     texture="stone")
        self.add(meshes.box(centre=(0.0, 2.5, 9.7),
                            size=(15.6, 5.0, 0.45),
                            col=(0.62, 0.64, 0.66), uv=(8, 2)),
                 texture="stone")
        self.add(meshes.box(centre=(0.0, 5.0, 0.0),
                            size=(15.6, 0.35, 19.8),
                            col=(0.43, 0.46, 0.53), uv=(8, 10)),
                 texture="stone")

        # Heavy ribs draw the eye toward the far arch.
        for z in (-7.0, -3.0, 1.0, 5.0, 9.0):
            self.add(meshes.box(centre=(0.0, 4.72, z),
                                size=(15.2, 0.34, 0.42),
                                col=(0.5, 0.31, 0.2), uv=(8, 1)),
                     texture="bark")
        for x in (-5.9, 0.0, 5.9):
            self.spawn(Arch, pos=(x, 0.05, -9.35), tag="portal_arch")

        # Low stone plinths anchor the sconces and frame the central aisle.
        for x in (-5.8, 5.8):
            for z in (-5.3, 1.5, 7.0):
                self.add(meshes.box(centre=(x, 0.48, z),
                                    size=(1.3, 0.95, 1.3),
                                    col=(0.45, 0.48, 0.52)),
                         texture="stone")

    def _lights(self):
        for x, z, color in (
                (-6.7, -6.0, "#ffad68"),
                (6.7, -6.0, "#63d9ff"),
                (-6.7, 1.5, "#a77aff"),
                (6.7, 1.5, "#ff6fc8"),
                (0.0, -7.2, "#5cecff")):
            self.add_light(pos=(x, 3.25, z), color=color,
                           energy=2.2, radius=8.5, flicker=0.08,
                           flicker_rate=2.4, pulse=0.12,
                           pulse_rate=0.35)
        self.add_light(pos=(0.0, 4.35, 2.5), color="#ffd89a",
                       energy=1.5, radius=11.0, shape="spot",
                       aim=(math.pi, -0.65))

    def update(self, dt):
        super().update(dt)
        if self.input.pressed("other_room"):
            self.play_scene("arcade")

    def overlay(self, screen):
        area = self.hud.area
        self.hud.panel((area.x + 14, area.y + 12, 340, 66),
                       color=(13, 17, 29), alpha=195)
        self.hud.text("DEMO  /  THE PRISM HALL",
                      (area.x + 26, area.y + 20),
                      color=(0.72, 0.9, 1.0))
        self.hud.text("WASD to wander  -  Tab for the 2D room",
                      (area.x + 26, area.y + 45))

    def status(self):
        return [self.name, "Prism Hall", f"{len(self.lights)} lights"]
