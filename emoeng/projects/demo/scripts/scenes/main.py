"""A stone hall whose surfaces, screen and whole picture can be re-dressed.

Everything the room is made of belongs to a named *part*, and every part is
one live mesh, so a switch on the lectern - or its key - can put a different
material on the floor, the walls, the arches, the portals, the props or the
lectern itself while you are standing in the room. Two more switches dress
the picture rather than a surface: the hall's whole frame, and the lectern
panel's own. The room starts plain: nothing is worn until you ask for it.
"""

import math

import emoeng as fe
from emoeng.engine import meshes
from scripts.scenes.dressing import Dresser, by_sheet, merge, pull

# metres from the floor to the top of the shell, and eye height on it
WALL_TOP = 5.0
EYE = 1.72


class Arch(fe.Object3D):
    """Block-built stone arch: its stones and its portal are separate parts."""

    name = "arch"

    def build(self):
        cx, cy, cz = self.pos
        yaw = self.yaw
        stones = []
        for side in (-1, 1):
            stones.append((meshes.box(centre=(cx + side * 1.1, cy + 1.2, cz),
                                      size=(0.42, 2.4, 0.62), yaw=yaw,
                                      col=(0.64, 0.63, 0.59)), "stone"))
        for i in range(9):
            angle = math.pi * i / 8.0
            stones.append((meshes.box(
                centre=(cx + math.cos(angle) * 1.1,
                        cy + 2.35 + math.sin(angle) * 1.1, cz),
                size=(0.42, 0.34, 0.62), yaw=yaw, lean=angle + math.pi / 2.0,
                col=(0.72, 0.70, 0.64)), "stone"))
        # the well itself, and the two rails that line it, share one sheet
        energy = [(meshes.box(centre=(cx, cy + 1.35, cz + 0.08),
                              size=(1.74, 2.36, 0.035), yaw=yaw,
                              col=(0.86, 0.96, 1.0)), "glow")]
        for side in (-1, 1):
            energy.append((meshes.box(
                centre=(cx + side * 1.43, cy + 1.25, cz + 0.06),
                size=(0.08, 2.45, 0.12), yaw=yaw,
                col=(0.24, 0.76, 0.95)), "glow"))
        dress = getattr(self.scene, "dress", None)
        if dress is None:
            # no dresser to file parts with, so fall back to plain statics
            for data, sheet in stones:
                self.add(data, texture=sheet)
            for data, sheet in energy:
                self.add(data, texture=sheet, blend="add")
            return
        dress.add_part("arches", by_sheet(stones), blend="opaque", owner=self)
        dress.add_part("portals", by_sheet(energy), blend="add", owner=self)


class Main(fe.Scene3D):
    """Walk the 3D hall; Tab opens its 2D companion room."""

    name = "main"
    # a room's bindings stay after it is left, so the hall reclaims the two
    # the flat room borrows for walking: W and S steer there, not here
    actions = {"other_room": ["tab"], "up": ["space"],
               "down": ["q", "lctrl"]}
    controls = ("forward", "back", "left", "right", "run", "other_room")
    post = ()                    # the hall starts undressed
    world_radius = 0.0
    clear_color = (0.025, 0.035, 0.06)
    ambient = (0.32, 0.34, 0.42)
    sun_dir = (-0.3, 0.88, -0.5)
    sun_col = (0.35, 0.4, 0.62)
    fog_color = (0.025, 0.035, 0.06)
    fog_near = 18.0
    fog_far = 42.0

    def setup(self):
        self.dress = Dresser(self)
        self.state = {}          # trigger -> the one word its switch shows
        self.note = ""           # what the room last said over the bus
        self._room()
        self._lectern()
        self._lights()
        self.player = self.spawn(
            fe.Player3D, pos=(0.0, 0.0, 5.2), yaw=math.pi,
            eye_height=EYE, move_speed=(3.6, 6.0), world_radius=0.0)

    def spawn_point(self):
        return (0.0, 0.0, 5.2), math.pi

    # -- the hall, as parts -----------------------------------------------
    def _room(self):
        self.dress.add("floor", meshes.plane(centre=(0.0, -0.08, 0.0),
                                             size=(16.0, 20.0), seg=16,
                                             uv_scale=10.0),
                       texture="stone")

        # the shell: a back wall pierced by three arches, two returns, a
        # front wall and a lid - all one sheet, so all one draw call
        shell = []
        for x in (-6.0, 6.0):
            shell.append(meshes.box(centre=(x, 2.5, -9.7),
                                    size=(4.0, WALL_TOP, 0.48),
                                    col=(0.7, 0.69, 0.64)))
        shell.append(meshes.box(centre=(0.0, 4.65, -9.7), size=(8.0, 0.7, 0.48),
                                col=(0.7, 0.69, 0.64)))
        for x in (-7.8, 7.8):
            shell.append(meshes.box(centre=(x, 2.5, 0.0),
                                    size=(0.45, WALL_TOP, 19.8),
                                    col=(0.62, 0.64, 0.66)))
        shell.append(meshes.box(centre=(0.0, 2.5, 9.7), size=(15.6, WALL_TOP, 0.45),
                                col=(0.62, 0.64, 0.66)))
        shell.append(meshes.box(centre=(0.0, 5.0, 0.0),
                                size=(15.6, 0.35, 19.8),
                                col=(0.43, 0.46, 0.53)))
        self.dress.add("walls", merge(*shell), texture="stone")

        # heavy ribs draw the eye toward the far arches
        ribs = [meshes.box(centre=(0.0, 4.72, z), size=(15.2, 0.34, 0.42),
                           col=(0.5, 0.31, 0.2))
                for z in (-7.0, -3.0, 1.0, 5.0, 9.0)]
        self.dress.add("arches", merge(*ribs), texture="bark")
        for x in (-5.9, 0.0, 5.9):
            self.spawn(Arch, pos=(x, 0.05, -9.35), tag="portal_arch")

        # low plinths anchor the aisles, and the cups above the sconces
        props = [meshes.box(centre=(x, 0.48, z), size=(1.3, 0.95, 1.3),
                            col=(0.45, 0.48, 0.52))
                 for x in (-5.8, 5.8) for z in (-5.3, 1.5, 7.0)]
        self.dress.add("props", merge(*props), texture="stone")
        # a rod and a cup on each wall light, so the glow has something to
        # stand on; one merged mesh, so the part still costs one draw call
        sconce = []
        for x, z in ((-6.7, -6.0), (6.7, -6.0), (-6.7, 1.5), (6.7, 1.5)):
            sconce.append(meshes.box(centre=(x + math.copysign(0.4, x),
                                             2.9, z),
                                     size=(0.9, 0.12, 0.12),
                                     col=(0.55, 0.56, 0.62)))
            sconce.append(meshes.cylinder((x, 3.06, z), r=0.2, h=0.24,
                                          seg=10, col=(0.85, 0.76, 0.6)))
        self.dress.add("props", merge(*sconce), texture="steel")

        self._colliders()

    def _colliders(self):
        """The hall stops you where it looks like it would."""
        # the shell's own boxes, matched face for face
        for x in (-7.8, 7.8):
            self.spawn(fe.Collision3D, pos=(x, WALL_TOP / 2.0, 0.0),
                       half=(0.225, WALL_TOP / 2.0, 9.9), tag="wall")
        self.spawn(fe.Collision3D, pos=(0.0, WALL_TOP / 2.0, 9.7),
                   half=(7.8, WALL_TOP / 2.0, 0.225), tag="wall")
        # one full-width stop behind the arches: their portals are windows,
        # not doors, and a lintel high overhead would never be felt anyway
        self.spawn(fe.Collision3D, pos=(0.0, WALL_TOP / 2.0, -9.72),
                   half=(7.8, WALL_TOP / 2.0, 0.26), tag="wall")
        for x in (-5.8, 5.8):
            for z in (-5.3, 1.5, 7.0):
                self.spawn(fe.Collision3D, pos=(x, 0.48, z),
                           half=(0.65, 0.475, 0.65), tag="plinth")

    # -- the lectern, and the screen that stands on it ---------------------
    def _lectern(self):
        """A reading stand in the hall's middle, holding the switch board."""
        body = [
            meshes.box(centre=(0.0, 0.10, 0.0), size=(1.5, 0.20, 1.1),
                       col=(0.42, 0.44, 0.50)),
            meshes.box(centre=(0.0, 0.62, 0.0), size=(0.9, 0.85, 0.6),
                       col=(0.47, 0.49, 0.55)),
            meshes.box(centre=(0.0, 1.05, 0.05), size=(1.4, 0.12, 0.8),
                       col=(0.55, 0.52, 0.46)),
            meshes.box(centre=(0.0, 1.40, 0.30), size=(0.16, 0.70, 0.16),
                       col=(0.36, 0.38, 0.44)),
        ]
        self.dress.add("lectern", merge(*body), texture="stone")
        # the bezel sits behind the glass, so the two never share a plane
        self.dress.add("lectern",
                       meshes.box(centre=(0.0, 1.75, 0.36),
                                  size=(2.32, 1.45, 0.10),
                                  col=(0.30, 0.32, 0.38)),
                       texture=None)
        self.spawn(fe.Collision3D, pos=(0.0, 0.60, 0.0),
                   half=(0.75, 0.60, 0.55), tag="lectern")
        self.lectern = self.spawn(
            fe.Screen3D, pos=(0.0, 1.75, 0.42), yaw=0.0, size=(2.0, 1.125),
            tag="lectern_panel", name="lectern", pixels=(512, 288),
            brightness=1.08, input=True, audio_mode="global")
        self.dress.set_panel(self.lectern)

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

    # -- the bus -----------------------------------------------------------
    def on_trigger(self, name, value=None):
        """One switch, or its key: re-dress one part of the hall."""
        got = pull(self.dress, name)
        if got is None:
            return super().on_trigger(name, value)
        word, self.note = got
        self.state[str(name)] = word
        return word

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
        self.hud.text("WASD to walk  -  Tab for the 2D room",
                      (area.x + 26, area.y + 45))
        # the crosshair is the pointer: the lectern answers a look and a click
        self.hud.crosshair()
        if self.note:
            self.hud.text(self.note, (area.x + 14, area.y + area.h - 34),
                          color=(0.85, 0.9, 1.0))

    def status(self):
        return [self.name, "Prism Hall", f"{len(self.lights)} lights"]
