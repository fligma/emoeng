"""The gallery: the whole demo in one scene.

Six rooms, one hub, six doors. Every door teleports the player to a room
that already exists in this same scene - one set of merged batches, one
camera, one save file - so the tour never reloads anything.

Each room owns its own atmosphere (clear colour, fog, ambient, sun, fov,
post passes); the scene lerps its knobs on arrival, and the renderer
uploads only the lights nearest the eye, so thirty-odd point lights can
live in the one world without fighting for shader slots.

    WASD move   Shift run   E use a door   TAB back to the gallery
    F3 debug    ESC pause

What each room demonstrates:

    Motion Lab       engine.anim       tween, smoothing, sprite frames
    Collision Arena  engine.collision  move_slide, timers, save
    Post FX Rack     engine.fx         passes and the render scale
    Interface Hall   engine.ui         every HUD helper, one card each
    Clone Forge      entities          spawn, clone, lineage, despawn
    Catacomb         the stack in a dark room
"""

import math
import random

import pygame

import fligengine as fe
from fligengine.engine import anim, collision, meshes, theme, ui
from fligengine.engine.camera import wish
from scripts.helpers import (controls, feature_panel, ground, safe_area,
                             safe_bottom)

# ---------------------------------------------------------------- dimensions
DOOR_RING = 13.5          # hub arches, metres from the bonfire
HUB_CLAMP = 15.4          # the player never leaves the hub platform
ROOM_HALF = 13.0          # rooms are 26 x 26
ROOM_CLAMP = 12.3
DOOR_H = 4.2              # clear height of a room doorway
STEP_HALF = (0.40, 0.9, 0.40)

PORTAL_KEYS = ("motion", "arena", "postfx", "hud", "forge", "crypt")
EASES = (("ease_in_out", anim.ease_in_out),
         ("ease_in", anim.ease_in),
         ("ease_out", anim.ease_out))

PASSES = (
    (),
    ("dither",),
    ("scanlines",),
    ("vignette",),
    ("grain",),
    ("warm",),
    ("cold",),
    ("dither", "scanlines", "vignette"),
    ("dither", "grain", "warm"),
)

TINTS = ((0.55, 0.80, 1.00), (1.00, 0.84, 0.46), (1.00, 0.52, 0.42),
         (0.62, 1.00, 0.72), (0.86, 0.62, 1.00))


def _sprite_frames():
    """Four little surfaces for anim.FrameAnim, drawn with pygame."""
    frames = []
    for i in range(4):
        surf = pygame.Surface((36, 36), pygame.SRCALPHA)
        pygame.draw.circle(surf, (255, 250, 220), (18, 18), 15)
        pygame.draw.circle(surf, (255, 140, 40), (18, 18), 15, 2)
        for k in range(i + 1):
            a = 2.0 * math.pi * k / 4.0
            x = int(18 + math.cos(a) * 9)
            y = int(18 + math.sin(a) * 9)
            pygame.draw.circle(surf, (255, 120, 30), (x, y), 5)
        frames.append(surf)
    return frames


def card(screen, fonts, rect, title, accent=(126, 182, 255)):
    """One labelled swatch of HUD: panel + accent caption, inner rect back."""
    rect = ui.panel(screen, rect, (9, 11, 18), 190, (58, 68, 88))
    ui.text(screen, fonts["small"], title, (rect.x + 10, rect.y + 5),
            color=accent)
    return pygame.Rect(rect.x + 10, rect.y + 24,
                       max(10, rect.width - 20), max(10, rect.height - 30))


# ===================================================================== zones
class Zone:
    """One room of the gallery: geometry, atmosphere, panel and keys.

    The scene builds every zone once, then hands update/handle_event/draw
    only to the zone the player is standing in, so a room's timers pause
    while you are somewhere else.
    """

    key = "zone"
    title = "Zone"
    caption = ""
    tone = (0.55, 0.72, 1.0)
    floor = "stone"
    floor_col = (0.90, 0.90, 0.92)
    roof = False
    wall_h = 6.0
    keys = ()

    clear_color = (0.018, 0.020, 0.030)
    fog_color = (0.050, 0.055, 0.080)
    fog_near = 18.0
    fog_far = 54.0
    ambient = (0.26, 0.28, 0.34)
    sun_dir = (0.30, 0.80, 0.40)
    sun_col = (0.22, 0.24, 0.30)
    fov = 68.0
    post = ("dither", "vignette")

    def __init__(self, scene, centre):
        self.scene = scene
        self.cx, self.cz = float(centre[0]), float(centre[1])
        self.t = 0.0
        self.colliders = []
        # where "E back to the gallery" triggers, in world space
        self.door = (self.cx, 0.0, self.cz + ROOM_HALF - 1.2)

    # ---------------------------------------------------------- coordinates
    def at(self, x, z, y=0.0):
        return (self.cx + x, y, self.cz + z)

    def add(self, data, texture="white", blend="opaque"):
        self.scene.add(data, texture, blend)

    def put(self, model, x, z, yaw=0.0, scale=1.0, tint=None, y=0.0):
        self.scene.place_model(model, self.at(x, z, y), yaw, scale, tint)

    def solid(self, x, y, z, size, col=(0.80, 0.80, 0.84), texture="stone"):
        self.add(meshes.box(centre=self.at(x, z, y), size=size, col=col),
                 texture)

    def light(self, x, y, z, color):
        return self.scene.add_light(self.at(x, z, y), color)

    def collider(self, x, y, z, half):
        self.colliders.append(collision.aabb(self.at(x, z, y), half))

    # ------------------------------------------------------------- building
    def build(self):
        self.shell()

    def shell(self):
        """Floor, four walls with a doorway at the front, optional roof."""
        half = ROOM_HALF
        wall = (0.72, 0.72, 0.76)
        h = self.wall_h
        self.add(meshes.plane(centre=self.at(0, 0),
                              size=(half * 2, half * 2), seg=8,
                              color_fn=lambda x, z, _h: self.floor_col,
                              uv_scale=9.0), texture=self.floor)
        self.solid(0, h / 2, -half, (half * 2 + 1.0, h, 1.0), wall)
        self.solid(-half, h / 2, 0, (1.0, h, half * 2 + 1.0), wall)
        self.solid(half, h / 2, 0, (1.0, h, half * 2 + 1.0), wall)
        gap = 2.0
        seg = half - gap
        for side in (-1, 1):
            self.solid(side * (gap + seg / 2), h / 2, half, (seg, h, 1.0),
                       wall)
        self.solid(0, (DOOR_H + h) / 2, half, (gap * 2, h - DOOR_H, 1.0),
                   wall)
        if self.roof:
            self.solid(0, h + 0.3, 0, (half * 2 + 1.0, 0.6, half * 2 + 1.0),
                       (0.46, 0.46, 0.50))
        self.put("arch", 0, half - 0.7, 0.0, 0.72)

    # ------------------------------------------------------------- lifecycle
    def enter(self):
        pass

    def leave(self):
        pass

    def update(self, dt):
        self.t += dt

    def handle_event(self, e):
        return False

    def draw(self, screen, fonts, w, h):
        pass

    def status(self):
        return [self.title]

    # ----------------------------------------------------------- containment
    def contain(self, x, z):
        return (max(self.cx - ROOM_CLAMP, min(self.cx + ROOM_CLAMP, x)),
                max(self.cz - ROOM_CLAMP, min(self.cz + ROOM_CLAMP, z)))

    def entry(self):
        return (self.cx, 0.0, self.cz + ROOM_CLAMP - 3.6), math.pi

    def ground(self, x, z):
        return 0.0


class Hub(Zone):
    """The entrance: terrain, six doors, a bonfire and the props showreel."""

    key = "hub"
    title = "The Gallery"
    caption = "Six doors around the fire - walk up to one and press E."
    tone = (0.55, 0.72, 1.0)
    floor = "ground"
    keys = (("E", "enter a door"),)

    clear_color = (0.012, 0.016, 0.030)
    fog_color = (0.055, 0.068, 0.100)
    fog_near = 12.0
    fog_far = 64.0
    ambient = (0.21, 0.23, 0.30)
    sun_dir = (-0.35, 0.72, 0.40)
    sun_col = (0.18, 0.20, 0.26)
    fov = 66.0
    post = ("dither", "scanlines", "vignette")

    def __init__(self, scene, centre):
        super().__init__(scene, centre)
        self.door = None            # the hub has six, not a way back
        self.portals = []
        self.spinners = []
        self.pulse_left = 6.0
        self.pulse_on = 0.0

    # ------------------------------------------------------------- building
    def build(self):
        rng = random.Random(13)
        self.add(meshes.plane(size=(110, 110), seg=42, height_fn=ground,
                              color_fn=lambda x, z, h: (0.95, 0.95, 0.95),
                              uv_scale=18.0), texture="ground")
        self.scene.spawn("stars", (0.0, 0.0, 0.0))

        # a ring of standing stones just outside the doors
        for i in range(9):
            a = math.tau * i / 9.0
            x, z = math.cos(a) * 17.6, math.sin(a) * 17.6
            self.put("pillar", x, z, -a, 0.9 + 0.22 * rng.random(),
                     y=ground(x, z) - 0.05)

        # dead forest beyond the stones
        for _ in range(22):
            a = rng.uniform(0.0, math.tau)
            r = rng.uniform(21.0, 34.0)
            x, z = math.cos(a) * r, math.sin(a) * r
            y = ground(x, z)
            s = rng.uniform(0.8, 1.3)
            self.put("trunk", x, z, rng.uniform(0.0, math.tau), s, y=y)
            self.put("canopy", x, z, rng.uniform(0.0, math.tau), s,
                     y=y + 3.0 * s)

        # the six doors, each lit with its room's colour
        for i, key in enumerate(PORTAL_KEYS):
            a = -math.pi / 2 + math.tau * i / len(PORTAL_KEYS)
            x, z = math.cos(a) * DOOR_RING, math.sin(a) * DOOR_RING
            y = ground(x, z)
            yaw = math.atan2(-math.cos(a), -math.sin(a))
            self.put("arch", x, z, yaw, 1.0, y=y)
            tone = self.scene.zones[key].tone
            light = self.light(x, y + 3.4, z, tone)
            self.portals.append({"key": key, "pos": (x, y, z),
                                 "light": light, "tone": tone})

        # the prop showreel: crate, orb and pillar on low plinths behind the
        # fire, so the walk from the arrival point to a door stays clear
        for i, (model, tint) in enumerate((("crate", (1.0, 0.92, 0.78)),
                                           ("orb", (0.70, 1.0, 0.92)),
                                           ("pillar", (1.0, 0.80, 0.62)))):
            x, z = -5.0 + i * 5.0, -6.6
            y = ground(x, z)
            self.solid(x, y + 0.30, z, (1.1, 0.60, 1.1), (0.74, 0.72, 0.70),
                       "stone")
            self.collider(x, y + 0.30, z, (0.55, 0.30, 0.55))
            base = y + 0.60
            if model == "orb":
                # the orb model is centred on its origin, the rest stand
                base += 0.31 * 0.7
            obj = self.scene.model_object(model, (x, base, z), 0.0, 0.7, tint)
            self.spinners.append((obj, i * 1.7, base))

        # the generated primitives, side by side
        px = -8.6
        for dz, mesh, tex in (
                (2.4, meshes.cylinder(centre=self.at(px, 2.4, ground(px, 2.4)
                                                        + 0.9),
                                      r=0.45, h=1.8, seg=14,
                                      col=(0.72, 0.80, 0.92)), "stone"),
                (0.0, meshes.cone(centre=self.at(px, 0.0, ground(px, 0.0)
                                                  + 0.9),
                                  r=0.7, h=1.8, seg=12,
                                  col=(0.92, 0.72, 0.52)), "rust"),
                (-2.4, meshes.box(centre=self.at(px, -2.4, ground(px, -2.4)
                                                 + 0.9),
                                 size=(0.9, 1.8, 0.9),
                                 col=(0.80, 0.86, 0.72)), "crate")):
            self.add(mesh, texture=tex)
            self.collider(px, ground(px, dz) + 0.9, dz, (0.55, 0.9, 0.55))

        self.fire = self.scene.spawn("bonfire", (0.0, ground(0.0, 0.0), 0.0),
                                     flames=3, size=1.0,
                                     tint=(1.0, 0.45, 0.12))
        # a second, lower flame light in front of the brazier: the entity's
        # own light sits above the rim, so the iron and the ground in front
        # of the fire would otherwise stay black
        self.light(0.0, 1.1, 2.0, (0.50, 0.27, 0.14))
        self.pulse_light = self.light(0.0, 6.0, -5.0, (0.15, 0.25, 0.45))

    # ---------------------------------------------------------------- frame
    def update(self, dt):
        self.t += dt
        for obj, phase, height in self.spinners:
            obj.set(yaw=self.t * 0.9 + phase,
                    pos=(obj.pos[0], height, obj.pos[2]))
            obj.update()
        self.pulse_left -= dt
        if self.pulse_left <= 0.0:
            self.pulse_left = 6.0
            self.pulse_light["color"] = (0.55, 0.75, 1.0)
            self.scene.audio.play("chime", 0.35)
            self.scene.after(0.4, self._pulse_off)
        near = self.scene.door
        for portal in self.portals:
            lit = near is not None and near.get("portal") is portal
            portal["light"]["color"] = tuple(
                c * (1.9 if lit else 1.0) for c in portal["tone"])

    def _pulse_off(self):
        self.pulse_light["color"] = (0.15, 0.25, 0.45)

    # ----------------------------------------------------------- containment
    def entry(self):
        return (0.0, 0.0, 10.0), math.pi

    def contain(self, x, z):
        r = math.hypot(x - self.cx, z - self.cz)
        if r <= HUB_CLAMP:
            return (x, z)
        k = HUB_CLAMP / r
        return (self.cx + (x - self.cx) * k, self.cz + (z - self.cz) * k)

    def ground(self, x, z):
        return ground(x, z)

    def status(self):
        seen = sum(1 for key in PORTAL_KEYS
                   if self.scene.save.has("seen_" + key))
        return [self.title, f"rooms {seen}/{len(PORTAL_KEYS)}"]

    # ---------------------------------------------------------------- panel
    def draw(self, screen, fonts, w, h):
        rows = []
        for key in PORTAL_KEYS:
            zone = self.scene.zones[key]
            tick = "[x]" if self.scene.save.has("seen_" + key) else "[ ]"
            rows.append((zone.title, tick))
        rows.append(("-", ""))
        rows.append(("rooms visited",
                     self.scene.save.get("gallery_visits", 0)))
        rows.append(("next light pulse", f"{self.pulse_left:0.1f}s"))
        feature_panel(screen, fonts, self.title, rows, width=300,
                      caption="every room is a live test of one subsystem")


class Motion(Zone):
    """engine.anim: three spinners, a tween, glow bobbers, a sprite sheet."""

    key = "motion"
    title = "Motion Lab"
    caption = "engine.anim - tween, smoothing, sprite frames, model spin"
    tone = (0.35, 0.62, 1.0)
    floor = "grid"
    floor_col = (0.72, 0.74, 0.80)
    keys = (("1/2/3", "easing"),)

    clear_color = (0.020, 0.022, 0.030)
    fog_color = (0.050, 0.055, 0.075)
    fog_near = 16.0
    fog_far = 56.0
    ambient = (0.24, 0.26, 0.32)
    sun_dir = (0.30, 0.80, 0.40)
    sun_col = (0.24, 0.24, 0.30)
    post = ("dither", "vignette")

    def build(self):
        self.shell()
        self.spinners = []
        for i, (model, tint, rate) in enumerate((
                ("crate", (0.95, 0.85, 0.70), 0.9),
                ("orb", (0.70, 0.95, 0.85), 1.7),
                ("pillar", (0.85, 0.80, 1.00), 0.5))):
            x = -5.0 + i * 5.0
            self.solid(x, 0.4, -6.0, (1.6, 0.8, 1.6), (0.78, 0.78, 0.82))
            self.collider(x, 0.4, -6.0, (0.8, 0.4, 0.8))
            obj = self.scene.model_object(model, self.at(x, -6.0, 0.8), 0.0,
                                          0.9, tint)
            self.spinners.append((obj, rate, 0.8))

        self.slide = anim.Tween(-2.6, 2.6, 2.4, EASES[0][1])
        self.slide_dir = 1.0
        self.slide_obj = self.scene.model_object(
            "crate", self.at(0.0, -1.0, 0.8), 0.0, 0.7, (1.0, 0.85, 0.55))
        self.ease_index = 0

        self.bobbers = []
        for i in range(4):
            x = 6.0 + (i % 2) * 1.9
            z = -2.2 + (i // 2) * 2.4
            mesh = self.scene.renderer.new_dynamic(
                meshes.billboards(self.at(x, z, 1.7), 1.0, 1.0, 2,
                                  (0.30, 0.70, 1.00)),
                texture="glow", blend="add")
            self.bobbers.append((mesh, x, z, i * 0.9))

        self.chase = anim.Smoothed(1.6, rate=4.0)
        self.chase_mesh = self.scene.renderer.new_dynamic(
            meshes.billboards((0.0, 1.6, 0.0), 0.8, 0.8, 2,
                              (1.0, 0.55, 0.35)),
            texture="glow", blend="add")

        self.frames = anim.FrameAnim(_sprite_frames(), fps=6.0)
        self.lights_add()
        self.scene.audio.tone("blip", 660.0, 120, "sine", 0.16)
        self.blip_left = 2.4

    def lights_add(self):
        self.light(-5.0, 4.0, -8.0, (0.55, 0.30, 0.20))
        self.light(4.0, 4.0, -2.0, (0.20, 0.45, 0.60))

    def update(self, dt):
        self.t += dt
        for obj, rate, height in self.spinners:
            obj.set(yaw=self.t * rate, pos=(obj.pos[0], height, obj.pos[2]))
            obj.update()

        self.slide.update(dt)
        if self.slide.done:
            self.slide_dir *= -1.0
            self.slide = anim.Tween(-2.6, 2.6, 2.4,
                                    EASES[self.ease_index][1])
        x = self.slide.value() * self.slide_dir
        self.slide_obj.set(pos=self.at(x, -1.0, 0.8), yaw=self.t * 0.6)
        self.slide_obj.update()

        for mesh, bx, bz, phase in self.bobbers:
            y = 1.7 + 0.45 * math.sin(self.t * 2.2 + phase)
            col = (0.25 + 0.20 * math.sin(self.t * 3.0 + phase), 0.55, 1.0)
            mesh.update(meshes.billboards(self.at(bx, bz, y), 1.0, 1.0, 2,
                                          col))

        self.chase.target = self.scene.game.eye[1]
        self.chase.update(dt)
        eye = self.scene.game.eye
        self.chase_mesh.update(meshes.billboards(
            (eye[0], self.chase.value, eye[2]), 0.7, 0.7, 2,
            (1.0, 0.55, 0.35)))

        self.frames.update(dt)
        self.blip_left -= dt
        if self.blip_left <= 0.0:
            self.blip_left = 2.4
            self.scene.audio.play("blip", 0.22)

    def handle_event(self, e):
        if e.type == pygame.KEYDOWN and e.key in (pygame.K_1, pygame.K_2,
                                                  pygame.K_3):
            self.ease_index = (e.key - pygame.K_1) % len(EASES)
            self.slide = anim.Tween(-2.6, 2.6, 2.4,
                                    EASES[self.ease_index][1])
            return True
        return False

    def status(self):
        return [self.title, f"ease {EASES[self.ease_index][0]}"]

    def draw(self, screen, fonts, w, h):
        right, fwd = self.scene.input.move_axis()
        rows = [
            ("right / forward", f"{right:+.2f}  {fwd:+.2f}"),
            ("tween", f"{self.slide.value():+.2f}  {self.slide.t:0.1f}s"),
            ("easing", EASES[self.ease_index][0]),
            ("smoothed eye y", f"{self.chase.value:0.2f}"),
            ("sprite frame", f"{self.frames.index + 1}/4"),
            ("spinners", len(self.spinners)),
            ("glow meshes", len(self.bobbers) + 1),
        ]
        feature_panel(screen, fonts, self.title, rows, width=300,
                      caption="everything here is engine.anim")

        top = safe_bottom(screen) - 170
        x0, cw, ch = 18, 84, 54
        t = (self.t * 0.5) % 1.0
        for i, (label, fn) in enumerate(EASES):
            box = pygame.Rect(x0 + i * (cw + 14), top, cw, ch)
            ui.panel(screen, box, (8, 10, 16), 170, (60, 70, 90))
            ui.text(screen, fonts["small"], label, (box.x + 5, box.y + 2),
                    color=(200, 206, 220))
            pts = []
            for s in range(21):
                k = s / 20.0
                pts.append((box.x + 4 + int(k * (cw - 8)),
                            box.bottom - 6 - int(fn(k) * (ch - 22))))
            pygame.draw.lines(screen, (120, 190, 255), False, pts, 1)
            mx = box.x + 4 + int(t * (cw - 8))
            my = box.bottom - 6 - int(fn(t) * (ch - 22))
            pygame.draw.circle(screen, (255, 214, 120), (mx, my), 3)
        frame = self.frames.frame
        if frame is not None:
            screen.blit(frame, (x0 + 3 * (cw + 14) + 6, top + 12))
            ui.text(screen, fonts["small"], "FrameAnim",
                    (x0 + 3 * (cw + 14) + 50, top + 20),
                    color=(206, 212, 226))


class Arena(Zone):
    """engine.collision + timers + save: crates you slide along, motes."""

    key = "arena"
    title = "Collision Arena"
    caption = "collision.move_slide, engine.timers and the save file"
    tone = (1.0, 0.45, 0.30)
    floor = "ground"
    floor_col = (0.80, 0.78, 0.78)
    keys = (("R", "reset run"),)

    clear_color = (0.030, 0.018, 0.020)
    fog_color = (0.075, 0.055, 0.055)
    fog_near = 16.0
    fog_far = 52.0
    ambient = (0.34, 0.30, 0.31)
    sun_dir = (0.25, 0.85, 0.30)
    sun_col = (0.36, 0.30, 0.29)
    post = ("dither", "scanlines", "vignette")

    SPAWN_EVERY = 2.4
    MAX_MOTES = 5

    def entry(self):
        # the crate grid leaves the x=0 lane open, so arrive down the aisle
        # behind the last row instead of inside a crate
        return (self.cx, 0.0, self.cz + 10.6), math.pi

    def build(self):
        self.shell()
        rng = random.Random(4)
        self.walls = []
        # a sparse grid on a 4 m pitch, cross-shaped lanes left open, so the
        # run from the door to the far wall is always clear and the room is
        # readable instead of a wall of crates
        for gx in range(-2, 3):
            for gz in range(-2, 3):
                if gx == 0 or gz == 0:
                    continue
                if rng.random() < 0.25:
                    continue
                x, z = gx * 4.0, gz * 4.0
                size = rng.uniform(1.8, 2.4)
                height = size * 0.85
                self.walls.append((x, height / 2, z, size, height))
                self.solid(x, height / 2, z, (size, height, size),
                           (0.86, 0.70, 0.58), "crate")
                self.collider(x, height / 2, z,
                              (size / 2, height / 2, size / 2))

        self.light(0.0, 5.0, -2.0, (0.85, 0.35, 0.25))
        self.light(-8.0, 3.0, 6.0, (0.25, 0.45, 0.85))
        self.light(8.0, 3.4, -6.0, (0.70, 0.50, 0.25))
        self.light(0.0, 3.2, 9.0, (0.55, 0.42, 0.28))

        self.shake = anim.Shake(decay=4.0, seed=7)
        self.mote_left = self.SPAWN_EVERY
        self.score = 0
        self.best = int(self.scene.save.get("arena_best", 0))
        self.total = int(self.scene.save.get("arena_total", 0))
        self.hits = (False, False, False)
        self.scene.audio.tone("pop", 880.0, 140, "sine", 0.20)
        self.drop_mote()

    def drop_mote(self):
        if len(self.scene.entities_of("mote")) >= self.MAX_MOTES:
            return
        rng = random.Random(int(self.t * 1000) & 0xFFFF)
        x = z = 0.0
        for _ in range(24):
            x = rng.uniform(-9.5, 9.5)
            z = rng.uniform(-9.5, 9.5)
            box = collision.aabb(self.at(x, z, 1.0), (0.9, 1.0, 0.9))
            if not any(collision.overlap(box, b) for b in self.colliders):
                break
        tint = (1.0, 0.55 + rng.random() * 0.3, 0.28)
        self.scene.spawn("mote", self.at(x, z, 1.1), tint=tint)

    def update(self, dt):
        self.t += dt
        self.shake.update(dt)
        self.mote_left -= dt
        if self.mote_left <= 0.0:
            self.mote_left = self.SPAWN_EVERY
            self.drop_mote()

        eye = self.scene.game.eye
        for mote in self.scene.entities_of("mote"):
            if math.dist((mote.pos[0], eye[1], mote.pos[2]), tuple(eye)) < 1.5:
                self._collect(mote)

    def _collect(self, mote):
        mote.despawn()
        self.score += 1
        self.total += 1
        self.shake.kick(0.9)
        self.scene.audio.play("pop", 0.5)
        if self.score > self.best:
            self.best = self.score
        self.scene.save.set("arena_best", self.best)
        self.scene.save.set("arena_total", self.total)
        self.scene.save.save()

    def handle_event(self, e):
        if e.type == pygame.KEYDOWN and e.key == pygame.K_r:
            for mote in self.scene.entities_of("mote"):
                mote.despawn()
            self.score = 0
            self.mote_left = self.SPAWN_EVERY
            self.scene.audio.play("gate", 0.4)
            return True
        return False

    def status(self):
        return [self.title, f"score {self.score}", f"best {self.best}"]

    def draw(self, screen, fonts, w, h):
        dx, dy = self.shake.offset()
        live = len(self.scene.entities_of("mote"))
        rows = [
            ("score", self.score),
            ("best", self.best),
            ("collected ever", self.total),
            ("motes live", f"{live}/{self.MAX_MOTES}"),
            ("colliders", len(self.colliders)),
            ("save slot", self.scene.save.slot),
        ]
        panel = feature_panel(screen, fonts, self.title, rows, width=300,
                              caption="move_slide resolves the body per axis")
        bar_y = panel.bottom + 14
        ui.bar(screen, (panel.x + dx * 6, bar_y + dy * 6, 190, 12),
               self.mote_left / self.SPAWN_EVERY,
               fill=(220, 90, 60), border=(240, 226, 210))
        ui.text(screen, fonts["small"], "next mote",
                (panel.x + 198, bar_y - 2), color=(226, 220, 210))
        if self.hits[0] or self.hits[2]:
            ui.text(screen, fonts["small"], "sliding along a crate",
                    (panel.x + 198, bar_y + 18), color=(255, 200, 120))


class PostFX(Zone):
    """engine.fx: the pass list walks itself, render scale is forced."""

    key = "postfx"
    title = "Post FX Rack"
    caption = "engine.fx - nine pass stacks and the render scale"
    tone = (0.55, 0.85, 0.45)
    floor = "checker"
    floor_col = (0.92, 0.92, 0.92)
    keys = (("Space", "pause"), ("1-9", "pick"), ("[ ]", "scale"))

    clear_color = (0.030, 0.026, 0.040)
    fog_color = (0.060, 0.050, 0.080)
    fog_near = 14.0
    fog_far = 54.0
    ambient = (0.26, 0.24, 0.30)
    sun_dir = (0.30, 0.82, 0.34)
    sun_col = (0.28, 0.24, 0.26)
    post = ("dither", "scanlines", "vignette")

    def build(self):
        self.shell()
        for i in range(-3, 4):
            x = i * 3.2
            self.add(meshes.cylinder(centre=self.at(x, -5.5, 1.6), r=0.45,
                                     h=3.2, seg=12,
                                     col=(0.80, 0.84, 0.92)),
                     texture="stone")
            self.collider(x, 1.6, -5.5, (0.5, 1.6, 0.5))
            self.solid(x, 0.6, 4.4, (1.6, 1.2, 1.6), (0.92, 0.70, 0.55),
                       "crate")
            self.collider(x, 0.6, 4.4, (0.8, 0.6, 0.8))
            colour = (0.90, 0.35 + 0.08 * i, 0.25) if i % 2 else \
                (0.25, 0.55, 0.95)
            self.light(x, 3.0, -2.0, colour)

        self.glows = []
        for i in range(9):
            a = math.tau * i / 9.0
            x, z = math.cos(a) * 4.6, math.sin(a) * 4.6
            mesh = self.scene.renderer.new_dynamic(
                meshes.billboards(self.at(x, z, 1.4), 1.3, 1.3, 2,
                                  (0.7, 0.45 + 0.3 * math.cos(a), 0.9)),
                texture="glow", blend="add")
            self.glows.append((mesh, x, z, i))

        self.index = 0
        self.auto = True
        self.cycle_left = 3.0
        self.scale = self.scene.base_scale
        self.scene.audio.tone("tick", 520.0, 90, "square", 0.12)

    def enter(self):
        self.scene.game.renderer.set_render_scale(self.scale)

    def leave(self):
        self.scene.game.renderer.set_render_scale(self.scene.base_scale)

    def update(self, dt):
        self.t += dt
        for mesh, x, z, i in self.glows:
            y = 1.4 + 0.35 * math.sin(self.t * 1.8 + i)
            size = 1.2 + 0.25 * math.sin(self.t * 2.6 + i * 0.7)
            mesh.update(meshes.billboards(
                self.at(x, z, y), size, size, 2,
                (0.7, 0.5 + 0.3 * math.cos(i), 0.9)))
        self.cycle_left -= dt
        if self.cycle_left <= 0.0:
            self.cycle_left = 3.0
            if self.auto:
                self.index = (self.index + 1) % len(PASSES)
                self.post = PASSES[self.index]

    def _apply(self):
        self.post = PASSES[self.index]
        self.scene.audio.play("tick", 0.28)

    def handle_event(self, e):
        if e.type != pygame.KEYDOWN:
            return False
        if e.key == pygame.K_SPACE:
            self.auto = not self.auto
            return True
        if pygame.K_1 <= e.key <= pygame.K_9:
            index = e.key - pygame.K_1
            if index < len(PASSES):
                self.index = index
                self.auto = False
                self._apply()
            return True
        if e.key == pygame.K_0:
            self.index = 0
            self.auto = False
            self._apply()
            return True
        if e.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            step = -0.1 if e.key == pygame.K_LEFTBRACKET else 0.1
            self.scale = max(0.3, min(1.0, self.scale + step))
            self.scene.game.renderer.set_render_scale(self.scale)
            return True
        return False

    def status(self):
        return [self.title, "+".join(self.post) or "no passes",
                f"{self.scale * 100:.0f}%"]

    def draw(self, screen, fonts, w, h):
        rows = []
        for i, passes in enumerate(PASSES):
            label = "+".join(passes) or "none"
            mark = ">" if i == self.index else " "
            rows.append((f"{mark} {i}  {label}", "on" if i == self.index
                         else ""))
        rows.append(("-", ""))
        rows.append(("auto cycle", "on" if self.auto else "paused"))
        rows.append(("next pass", f"{self.cycle_left:0.1f}s"))
        rows.append(("render scale", f"{self.scale * 100:.0f}%"))
        feature_panel(screen, fonts, self.title, rows, width=300,
                      caption="passes run on the render-scale framebuffer")


class Hud(Zone):
    """engine.ui: every helper, one card each, laid out as a spec sheet."""

    key = "hud"
    title = "Interface Hall"
    caption = "engine.ui - each helper drawn once, in its own card"
    tone = (0.95, 0.75, 0.30)
    floor = "grid"
    floor_col = (0.80, 0.82, 0.88)
    keys = (("[ ]", "bar"), ("M", "menu"), ("D", "dim"), ("C", "aim"))

    clear_color = (0.014, 0.016, 0.022)
    fog_color = (0.040, 0.044, 0.058)
    fog_near = 12.0
    fog_far = 46.0
    ambient = (0.20, 0.22, 0.28)
    sun_dir = (0.35, 0.80, 0.45)
    sun_col = (0.18, 0.20, 0.26)
    post = ("dither", "vignette")

    MENU_ROWS = ("New game", "Continue", "Options", "Quit")
    HELPERS = 10

    def build(self):
        self.shell()
        for i in range(8):
            a = math.tau * i / 8.0
            if math.sin(a) > 0.62:          # keep the doorway clear
                continue
            x, z = math.cos(a) * 9.6, math.sin(a) * 9.6
            self.put("pillar", x, z, -a, 0.78)
            self.collider(x, 2.0, z, (0.6, 2.0, 0.6))

        self.solid(0.0, 0.45, 0.0, (1.8, 0.9, 1.8), (0.86, 0.88, 0.94))
        self.collider(0.0, 0.45, 0.0, (0.9, 0.45, 0.9))
        self.orb = self.scene.spawn("orb", self.at(0.0, 0.0, 1.28),
                                    halo=(1.0, 0.74, 0.34))
        self.fire = self.scene.spawn("bonfire", self.at(-7.4, -7.4),
                                     flames=2, size=0.8)
        self.light(6.6, 3.4, 5.2, (0.28, 0.48, 0.92))

        self.value = 0.62
        self.menu_row = 0
        self.dimmed = False
        self.cross = 9
        self.ticks = 0

    def update(self, dt):
        self.t += dt
        self.ticks = int(self.t)

    def handle_event(self, e):
        if e.type != pygame.KEYDOWN:
            return False
        if e.key == pygame.K_LEFTBRACKET:
            self.value = max(0.0, self.value - 0.08)
            return True
        if e.key == pygame.K_RIGHTBRACKET:
            self.value = min(1.0, self.value + 0.08)
            return True
        if e.key == pygame.K_m:
            self.menu_row = (self.menu_row + 1) % len(self.MENU_ROWS)
            return True
        if e.key == pygame.K_d:
            self.dimmed = not self.dimmed
            self.scene.audio.play("tick", 0.25)
            return True
        if e.key == pygame.K_c:
            self.cross = 7 if self.cross >= 13 else self.cross + 2
            return True
        return False

    def status(self):
        return [self.title, f"bar {self.value * 100:.0f}%",
                f"menu {self.MENU_ROWS[self.menu_row]}"]

    def draw(self, screen, fonts, w, h):
        if self.dimmed:
            ui.dim(screen, 0.32)
        top = safe_area(screen).y + 8
        gap = 12
        cw = (w - 36 - gap * 3) // 4
        ch = 140
        self._card_text(screen, fonts, pygame.Rect(18, top, cw, ch))
        self._card_bar(screen, fonts,
                       pygame.Rect(18 + (cw + gap), top, cw, ch))
        self._card_keys(screen, fonts,
                        pygame.Rect(18 + (cw + gap) * 2, top, cw, ch))
        self._card_menu(screen, fonts,
                        pygame.Rect(18 + (cw + gap) * 3, top, cw, ch))

        row2 = top + ch + gap
        half = (w - 36 - gap) // 2
        self._card_hints(screen, fonts, pygame.Rect(18, row2, half, 92))
        self._card_notes(screen, fonts,
                         pygame.Rect(18 + half + gap, row2, half, 92))

        ui.crosshair(screen, (w // 2, h // 2), self.cross, 4)
        ui.prompt(screen, fonts["normal"], "E", "ui.prompt",
                  (w // 2, int(h * 0.60)))
        ui.subtitle(screen, fonts["small"],
                    [f"theme {theme.current()}   ·   clock {self.ticks}s"],
                    safe_bottom(screen) - fonts["small"].get_height() - 10)

    def _card_text(self, screen, fonts, rect):
        inner = card(screen, fonts, rect, "ui.text")
        ui.text(screen, fonts["normal"], "shadowed", inner.topleft,
                color=(238, 240, 246))
        ui.text(screen, fonts["small"], "right aligned",
                (inner.right, inner.y + 24), color=(196, 202, 214),
                align="right")
        ui.text(screen, fonts["small"], "centred",
                (inner.centerx, inner.y + 42), color=(196, 202, 214),
                align="centre")
        ui.text(screen, fonts["small"], "alpha 140",
                (inner.x, inner.y + 60), color=(196, 202, 214), alpha=140)
        ui.text(screen, fonts["small"], "shadow · align · alpha",
                (inner.x, inner.bottom - 18), color=(128, 136, 152))

    def _card_bar(self, screen, fonts, rect):
        inner = card(screen, fonts, rect, "ui.bar")
        ui.bar(screen, (inner.x, inner.y + 4, inner.width, 16), self.value,
               fill=(80, 170, 250), border=(230, 230, 236))
        ui.text(screen, fonts["small"], f"{self.value * 100:0.0f}%",
                (inner.x, inner.y + 26), color=(230, 232, 238))
        ui.text(screen, fonts["small"], "[ ]", (inner.right, inner.y + 26),
                color=(126, 182, 255), align="right")
        ui.text(screen, fonts["small"], "frac · fill · border",
                (inner.x, inner.bottom - 18), color=(128, 136, 152))

    def _card_keys(self, screen, fonts, rect):
        inner = card(screen, fonts, rect, "ui.keycap")
        x = inner.x
        for key in ("W", "A", "S", "D"):
            x = ui.keycap(screen, fonts["small"], key, (x, inner.y + 6)).right
            x += 6
        ui.text(screen, fonts["small"], "mapped movement keys",
                (inner.x, inner.y + 40), color=(196, 202, 214))
        x = inner.x
        for key in ("SHIFT", "ESC"):
            cap = ui.keycap(screen, fonts["small"], key, (x, inner.y + 66))
            x = cap.right + 6
        ui.text(screen, fonts["small"], "standalone caps",
                (inner.x, inner.bottom - 18), color=(128, 136, 152))

    def _card_menu(self, screen, fonts, rect):
        inner = card(screen, fonts, rect, "ui.menu")
        ui.menu(screen, fonts["small"], self.MENU_ROWS,
                self.menu_row, (inner.x, inner.y), width=inner.width)

    def _card_hints(self, screen, fonts, rect):
        inner = card(screen, fonts, rect, "ui.hints")
        ui.hints(screen, fonts["small"],
                 (("[ ]", "bar value"), ("M", "menu row"),
                  ("D", "dim the frame")),
                 (inner.x, inner.y + 2))

    def _card_notes(self, screen, fonts, rect):
        inner = card(screen, fonts, rect, "window chrome", (200, 208, 226))
        ui.text(screen, fonts["small"],
                f"{self.HELPERS} helpers · panel, bar, text, menu,",
                inner.topleft, color=(206, 212, 226))
        ui.text(screen, fonts["small"], "keycap, hints, prompt, subtitle,",
                (inner.x, inner.y + 16), color=(206, 212, 226))
        ui.text(screen, fonts["small"],
                f"crosshair · dim {'on' if self.dimmed else 'off'}",
                (inner.x, inner.y + 32), color=(206, 212, 226))


class Forge(Zone):
    """The entity API: one original, a clone, a clone of the clone."""

    key = "forge"
    title = "Clone Forge"
    caption = "entities - spawn by file, clone, read the lineage, despawn"
    tone = (0.72, 0.55, 1.0)
    floor = "grid"
    floor_col = (0.86, 0.88, 0.94)
    keys = (("C", "clone"), ("X", "despawn"), ("R", "rebuild"))

    clear_color = (0.018, 0.020, 0.032)
    fog_color = (0.050, 0.055, 0.085)
    fog_near = 14.0
    fog_far = 54.0
    ambient = (0.28, 0.30, 0.38)
    sun_dir = (-0.25, 0.80, 0.45)
    sun_col = (0.20, 0.22, 0.28)
    post = ("dither", "vignette")

    ROW_Y = 1.5
    SLOT = 2.6

    def build(self):
        self.shell()
        for i in range(6):
            # half-step offset: no pillar sits on the +Z axis where the
            # player arrives, so the row is never blocked
            a = math.tau * (i + 0.5) / 6.0
            x, z = math.cos(a) * 8.6, math.sin(a) * 8.6
            self.put("pillar", x, z, -a, 0.8)
            self.collider(x, 2.0, z, (0.6, 2.0, 0.6))
        self.solid(1.3, 0.2, -1.0, (10.4, 0.4, 2.4), (0.80, 0.82, 0.88))
        for i in range(3):
            x = self._slot(i)[0]
            self.solid(x, 0.65, -1.0, (1.5, 0.9, 1.5), (0.90, 0.90, 0.94))
            self.collider(x, 0.65, -1.0, (0.75, 0.45, 0.75))
        self.light(1.3, 4.6, -3.4, (0.30, 0.45, 0.90))
        self.light(6.4, 2.2, 2.0, (0.85, 0.40, 0.25))
        self.light(1.3, 1.4, 2.4, (0.55, 0.52, 0.48))

        self.row = []
        self.message = ""
        self.scene.audio.tone("blip", 640.0, 110, "sine", 0.16)
        self.reset_row()

    def _slot(self, index):
        return (-1.4 + index * self.SLOT, self.ROW_Y, -1.0)

    def reset_row(self):
        """One original from the scene, then a copy, then a copy of a copy."""
        for gem in reversed(self.row):
            gem.despawn()
        self.row = []
        root = self.scene.spawn("gem", self.at(-1.4, -1.0, self.ROW_Y),
                                tint=TINTS[0])
        self.row.append(root)
        self.row.append(root.clone(self.at(1.2, -1.0, self.ROW_Y),
                                   tint=TINTS[1]))
        self.row.append(self.row[1].clone(self.at(3.8, -1.0, self.ROW_Y),
                                          tint=TINTS[2], size=0.62))
        self.message = "spawned one gem, then cloned it twice"

    def live(self):
        return [gem for gem in self.row if gem.alive]

    def clone_last(self):
        gems = self.live()
        if not gems:
            self.message = "no gems left - R rebuilds the row"
            self.scene.audio.play("bump", 0.2)
            return
        source = gems[-1]
        x = min(9.4, source.pos[0] - self.cx + self.SLOT)
        copy = source.clone(self.at(x, -1.0, self.ROW_Y),
                            tint=TINTS[len(gems) % len(TINTS)],
                            size=max(0.5, source.size - 0.06))
        self.row.append(copy)
        self.message = (f"cloned depth {source.depth} -> depth {copy.depth}")
        self.scene.audio.play("blip", 0.4)

    def drop_last(self):
        gems = self.live()
        if not gems:
            self.message = "nothing to despawn"
            return
        newest = gems[-1]
        depth = newest.depth
        newest.despawn()
        self.row = [gem for gem in self.row if gem.alive]
        self.message = f"disposed depth {depth}"
        self.scene.audio.play("bump", 0.3)

    def handle_event(self, e):
        if e.type != pygame.KEYDOWN:
            return False
        if e.key == pygame.K_c:
            self.clone_last()
            return True
        if e.key == pygame.K_x:
            self.drop_last()
            return True
        if e.key == pygame.K_r:
            self.reset_row()
            return True
        return False

    def status(self):
        gems = self.live()
        deepest = max((gem.depth for gem in gems), default=0)
        return [self.title, f"{len(gems)} gems", f"depth {deepest}"]

    def draw(self, screen, fonts, w, h):
        gems = self.live()
        rows = []
        for i, gem in enumerate(gems):
            kind = "original" if gem.is_original else f"clone d{gem.depth}"
            rows.append((f"{i}  {kind}", f"x {gem.pos[0] - self.cx:+.1f}"))
        rows.append(("-", ""))
        rows.append(("live gems", len(gems)))
        rows.append(("scene entities", len(self.scene.entities)))
        if gems:
            newest = gems[-1]
            rows.append(("is_clone", newest.is_clone))
            rows.append(("root", "original" if newest.root is gems[0]
                         else "elsewhere"))
            rows.append(("lineage", " -> ".join(
                f"d{a.depth}" for a in newest.lineage) or "none"))
        feature_panel(screen, fonts, self.title, rows, width=300,
                      caption="clone() builds a tracked copy, depth and all")
        if self.message:
            ui.text(screen, fonts["small"], self.message,
                    (18, safe_bottom(screen) - 44), color=(206, 216, 236))


class Crypt(Zone):
    """Tight fog, four bonfires and a relic: the stack in a dark room."""

    key = "crypt"
    title = "Catacomb"
    caption = "the same APIs in the dark - fog, bonfires and a relic"
    tone = (0.62, 0.45, 1.0)
    floor = "stone"
    floor_col = (0.85, 0.85, 0.85)
    roof = True
    wall_h = 5.0
    keys = ()

    clear_color = (0.010, 0.008, 0.012)
    fog_color = (0.055, 0.024, 0.020)
    fog_near = 3.0
    fog_far = 22.0
    ambient = (0.30, 0.22, 0.19)
    sun_dir = (0.0, 1.0, 0.0)
    sun_col = (0.10, 0.07, 0.06)
    fov = 66.0
    post = ("dither", "vignette")

    def build(self):
        self.shell()
        for i in range(6):
            a = math.tau * i / 6.0
            x, z = math.cos(a) * 9.4, math.sin(a) * 9.4
            self.put("pillar", x, z, -a, 0.74)
            self.collider(x, 2.0, z, (0.55, 2.0, 0.55))

        self.fires = []
        for x, z in ((6.4, 6.4), (-6.4, 6.4), (6.4, -6.4), (-6.4, -6.4)):
            self.fires.append(self.scene.spawn(
                "bonfire", self.at(x, z), flames=2, size=0.72,
                tint=(1.0, 0.42, 0.10)))
            self.collider(x, 0.6, z, (0.5, 0.6, 0.5))

        self.solid(0.0, 0.5, 0.0, (2.6, 1.0, 1.6), (0.68, 0.66, 0.62))
        self.collider(0.0, 0.5, 0.0, (1.3, 0.5, 0.8))
        self.relic = self.scene.spawn("orb", self.at(0.0, 0.0, 1.36),
                                      halo=(0.55, 0.72, 1.0))
        self.taken = False
        self.prompt = None

    def update(self, dt):
        self.t += dt
        self.prompt = None
        if self.relic.alive and self.relic.close(self.scene.game.eye, 2.6):
            self.prompt = "take the relic"

    def handle_event(self, e):
        if e.type == pygame.KEYDOWN and e.key == pygame.K_e and \
                self.prompt is not None:
            self.relic.take()
            self.taken = True
            self.prompt = None
            self.scene.audio.play("pickup", 0.7)
            self.scene.save.flag("relic_taken")
            self.scene.save.save()
            return True
        return False

    def status(self):
        return [self.title, "relic taken" if self.taken else "relic waiting"]

    def draw(self, screen, fonts, w, h):
        rows = [
            ("relic", "taken" if self.taken else "on the altar"),
            ("bonfires", len(self.fires)),
            ("fog", f"{self.fog_near:0.0f} - {self.fog_far:0.0f} m"),
            ("roof", "stone"),
        ]
        feature_panel(screen, fonts, self.title, rows, width=260,
                      caption="a closed room: tight fog, four lights")
        if self.prompt:
            ui.prompt(screen, fonts["normal"], "E", self.prompt,
                      (w // 2, int(h * 0.60)))


# ==================================================================== scene
class Gallery(fe.SceneBase):
    name = "gallery"
    uses = ("stars", "bonfire", "mote", "gem", "orb")
    camera = "walk"
    move_speed = (5.0, 8.8)
    eye_height = 1.7
    world_radius = 0.0          # the zones contain the player themselves
    fov = 66.0

    clear_color = Hub.clear_color
    fog_color = Hub.fog_color
    fog_near = Hub.fog_near
    fog_far = Hub.fog_far
    ambient = Hub.ambient
    sun_dir = Hub.sun_dir
    sun_col = Hub.sun_col
    post = Hub.post

    LAYOUT = (
        (Hub, "hub", (0.0, 0.0)),
        (Motion, "motion", (0.0, -190.0)),
        (Arena, "arena", (92.0, -190.0)),
        (PostFX, "postfx", (-92.0, -190.0)),
        (Hud, "hud", (-92.0, -282.0)),
        (Forge, "forge", (0.0, -282.0)),
        (Crypt, "crypt", (92.0, -282.0)),
    )

    # ------------------------------------------------------------- building
    def setup(self):
        self.lock_input = True          # the scene resolves movement
        self.base_scale = self.renderer.render_scale
        self.zones = {}
        for cls, key, centre in self.LAYOUT:
            self.zones[key] = cls(self, centre)
        for zone in self.zones.values():
            zone.build()
        self.hub = self.zones["hub"]
        self.zone = self.hub
        self.door = None
        self.flash = 0.0
        self.banner = 5.0
        self.step_left = 0.0
        self.audio.tone("chime", 760.0, 260, "sine", 0.20)
        self.audio.tone("bump", 150.0, 110, "sine", 0.30)
        self.audio.play("drone", 0.22, loops=-1)

    # ------------------------------------------------------------- movement
    def _move_body(self, dt):
        """Swept-box movement through the current room's colliders."""
        zone = self.zone
        right, fwd = self.input.move_axis()
        run = self.input.down("run")
        speed = self.move_speed[1] if run else self.move_speed[0]
        vx, vz = wish(self.game.yaw, right, fwd)
        vx *= speed * dt
        vz *= speed * dt
        eye = self.game.eye
        pos, hits = collision.move_slide((eye[0], 0.9, eye[2]),
                                         (vx, 0.0, vz), zone.colliders,
                                         STEP_HALF)
        x, z = zone.contain(pos[0], pos[2])
        self.game.set_player((x, zone.ground(x, z) + self.eye_height, z))
        if zone is self.zones["arena"]:
            zone.hits = hits
            if (hits[0] or hits[2]) and not getattr(self, "_bumped", False):
                self.audio.play("bump", 0.10)
            self._bumped = hits[0] or hits[2]

    # ---------------------------------------------------------------- frame
    def update(self, dt):
        super().update(dt)              # entities
        self._move_body(dt)
        self.zone.update(dt)
        self._tune(dt)
        self._scan_doors()

        self.flash = max(0.0, self.flash - dt * 2.4)
        self.banner = max(0.0, self.banner - dt)
        if any(self.input.down(k) for k in ("forward", "back", "left",
                                            "right")):
            self.step_left -= dt
            if self.step_left <= 0.0:
                self.step_left = 0.34
                self.audio.play("step", 0.12)

    def _tune(self, dt):
        """Lerp the renderer knobs toward the room's atmosphere."""
        zone = self.zone
        k = min(1.0, dt * 4.0)
        for name in ("clear_color", "fog_color", "ambient", "sun_col",
                     "sun_dir"):
            cur = getattr(self, name)
            tgt = getattr(zone, name)
            setattr(self, name, tuple(c + (t - c) * k for c, t in zip(cur, tgt)))
        self.fog_near += (zone.fog_near - self.fog_near) * k
        self.fog_far += (zone.fog_far - self.fog_far) * k
        self.fov += (zone.fov - self.fov) * k
        self.post = zone.post

    def _scan_doors(self):
        """Pick the door the player is close enough to use."""
        eye = self.game.eye
        best, best_d = None, 3.0
        for door in self._doors():
            dx = door["pos"][0] - eye[0]
            dz = door["pos"][2] - eye[2]
            d = math.hypot(dx, dz)
            if d < best_d:
                best, best_d = door, d
        self.door = best

    def _doors(self):
        doors = []
        if self.zone is self.hub:
            for portal in self.hub.portals:
                zone = self.zones[portal["key"]]
                doors.append({"pos": portal["pos"], "target": portal["key"],
                              "label": f"enter {zone.title}",
                              "portal": portal})
        else:
            zone = self.zone
            doors.append({"pos": zone.door, "target": "hub",
                          "label": "back to the gallery"})
        return doors

    # -------------------------------------------------------------- travels
    def go(self, key):
        """Teleport into another room of the same scene."""
        zone = self.zones[key]
        self.zone.leave()
        self.zone = zone
        pos, yaw = zone.entry()
        self.game.set_player(pos, yaw, 0.0)
        zone.enter()
        self.flash = 0.9
        self.banner = 5.0
        self.door = None
        self._bumped = False
        self.audio.play("gate", 0.5)
        if key != "hub":
            self.save.flag("seen_" + key)
            self.save.add("gallery_visits", 1)
            self.save.save()

    def handle_event(self, e):
        if e.type != pygame.KEYDOWN:
            return False
        if e.key == pygame.K_TAB:
            if self.zone is not self.hub:
                self.go("hub")
            return True
        if e.key == pygame.K_e and self.door is not None:
            self.go(self.door["target"])
            return True
        return self.zone.handle_event(e)

    # -------------------------------------------------------------- queries
    def spawn_point(self):
        pos, yaw = self.hub.entry()
        return pos, yaw

    def ground_height(self, x, z):
        return self.zone.ground(x, z)

    def status(self):
        return self.zone.status()

    # -------------------------------------------------------------- overlay
    def overlay(self, screen):
        w, h = screen.get_size()
        fonts = self.game.fonts
        zone = self.zone
        zone.draw(screen, fonts, w, h)

        ui.crosshair(screen, (w // 2, h // 2), 9, 4)
        if self.door is not None:
            ui.prompt(screen, fonts["normal"], "E", self.door["label"],
                      (w // 2, int(h * 0.62)))
        controls(screen, fonts, list(zone.keys) + [("TAB", "gallery"),
                                                   ("ESC", "pause")])
        if self.banner > 0.0:
            ui.subtitle(screen, fonts["normal"],
                        [zone.title, zone.caption],
                        safe_bottom(screen) - fonts["small"].get_height()
                        - 12)
        if self.flash > 0.004:
            shade = pygame.Surface((w, h))
            shade.fill((0, 0, 0))
            shade.set_alpha(int(255 * min(1.0, self.flash)))
            screen.blit(shade, (0, 0))
