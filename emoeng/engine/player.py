"""Players: objects you spawn, in two flavours."""

import math

import numpy as np
import pygame

from .camera import ease, ease_angle, normalize, wish
from .objects import Object2D, Object3D


class Player3D(Object3D):
    """First-person 3D controller driven by the Input API."""

    name = "player3d"
    is_player = True
    clone_attrs = ()

    move_speed = (6.0, 12.0)           # (walk, run) m/s
    eye_height = 2.0                   # above ground in walk mode
    movement = "walk"                  # "walk" | "fly"
    world_radius = 128.0               # hard clamp from origin; 0 = off
    sensitivity = 0.0022               # radians per pixel of mouse_rel
    pitch_limit = 1.45                 # radians (~83 degrees)
    aim_damping = 0.0                  # >0 eases the look (head smoothing)
    fov = None                         # None keeps the scene's field of view
    lock_input = False
    first_person = True                # write the eye into my camera too
    # my body as a mover sees it: one box
    body_half = (0.35, 0.9, 0.35)
    collide_group = "player"           # the `group` a shape may name to
                                       # stop only bodies like mine
    doc_knobs = ("movement", "eye_height", "world_radius", "sensitivity",
                 "aim_damping", "lock_input", "first_person", "body_half",
                 "collide_group")

    def __init__(self, scene, pos=(0.0, 2.0, 0.0), yaw=0.0, scale=1.0,
                 tag=None, **knobs):
        super().__init__(scene, pos=pos, yaw=yaw, scale=scale, tag=tag)
        self.pitch = 0.0
        self.velocity = [0.0, 0.0, 0.0]
        # which axes the last move ran into
        self.hits = (False, False, False)
        # where the mouse wants to look, when `aim_damping` is easing
        self.aim = (self.yaw, self.pitch)
        self.set_knobs(knobs)
        self.input.bind_defaults()

    def give_camera(self, name=None, follow=False, offset=None,
                    damping=0.0, active=True, **kw):
        """Player flavour: the default rig is first-person (no follow)."""
        cam = self.scene.add_camera(name=name, **kw)
        return self.adopt_camera(cam, follow=follow, offset=offset,
                                 damping=damping, active=active)

    def use_camera(self, cam, follow=False, offset=None, damping=0.0,
                   active=True):
        """Drive an existing scene camera by name or object."""
        if isinstance(cam, str):
            found = self.scene.cameras.get(cam)
            if found is None:
                raise KeyError(f"scene has no camera '{cam}'")
            cam = found
        return self.adopt_camera(cam, follow=follow, offset=offset,
                                 damping=damping, active=active)

    def poll_look(self):
        """(dx, dy) mouse delta for this frame, or zeros."""
        if self.lock_input:
            return (0.0, 0.0)
        return self.input.mouse_rel

    def poll_move(self):
        """(right, forward, up, run) sampled from bound actions."""
        if self.lock_input:
            return (0.0, 0.0, 0.0, False)
        right, fwd = self.input.move_axis()
        up = self.input.axis("up", "down")
        run = self.input.down("run")
        return (right, fwd, up, run)

    def update(self, dt):
        """Advance clock/timers, then drive pos/yaw/pitch from input."""
        super().update(dt)
        self.apply_look(dt)
        self.apply_move(dt)
        self.publish_camera()

    def apply_look(self, dt=0.0):
        dx, dy = self.poll_look()
        if dx == 0 and dy == 0:
            return
        self.nudge(dx, dy, dt)

    def nudge(self, dx, dy, dt=0.0):
        """Turn the head by a raw pixel delta."""
        # yaw increases leftward: right mouse push lowers it
        want = (self.aim[0] - dx * self.sensitivity,
                max(-self.pitch_limit,
                    min(self.pitch_limit,
                        self.aim[1] - dy * self.sensitivity)))
        self.aim = want
        if self.aim_damping > 0.0 and dt > 0.0:
            # ease toward the wanted angle instead of jumping to it
            self.yaw = ease_angle(self.yaw, want[0], dt, self.aim_damping)
            self.pitch = ease(self.pitch, want[1], dt, self.aim_damping)
        else:
            self.yaw, self.pitch = want

    def apply_move(self, dt):
        right, fwd, up, run = self.poll_move()
        speed = self.move_speed[1] if run else self.move_speed[0]
        rig = getattr(self.scene, "camera_rig", None)
        if rig is not None and rig is not self:
            # a prop claimed the camera; position follows the rig
            rig.look(self.yaw, self.pitch)
            if not self.lock_input:
                rig.move(wish(self.yaw, right, fwd), run, dt)
            ex, ey, ez = rig.eye()
            self.pos[0], self.pos[1], self.pos[2] = ex, ey, ez
            return
        vx, vz = wish(self.yaw, right, fwd)
        delta = [vx * speed * dt, 0.0, vz * speed * dt]
        if self.movement == "fly":
            delta[1] = up * speed * dt
        sweep = getattr(self.scene, "move_body", None)
        if sweep is None:
            self.pos = [float(p) + float(d)
                        for p, d in zip(self.pos, delta)]
        else:
            self.pos, self.hits = sweep(self.pos, delta, self.body_half,
                                        self.collide_group)
        self._clamp_to_world()

    def _clamp_to_world(self):
        ground = self.scene.ground_height(self.pos[0], self.pos[2])
        if self.movement == "walk":
            self.pos[1] = ground + self.eye_height
        else:
            self.pos[1] = max(self.pos[1], ground + 0.6)
        if self.world_radius:
            r = math.hypot(self.pos[0], self.pos[2])
            if r > self.world_radius:
                k = self.world_radius / r
                self.pos[0] *= k
                self.pos[2] *= k

    def publish_camera(self):
        """Mirror pos/yaw/pitch onto the camera this player drives."""
        cam = self.look_camera or getattr(self.game, "camera", None)
        if cam is None:
            g = self.game
            g.eye = [float(c) for c in self.pos]
            g.yaw = self.yaw
            g.pitch = self.pitch
        else:
            if self.look_camera is None or self.first_person:
                cam.eye = [float(c) for c in self.pos]
            cam.yaw = float(self.yaw)
            cam.pitch = float(self.pitch)
            cam.wanted = (cam.yaw, cam.pitch)
            if self.fov is not None and self.look_camera is not None:
                cam.fov = float(self.fov)
        if self.fov is not None:
            self.scene.fov = float(self.fov)

    def teleport(self, pos, yaw=None, pitch=None):
        """Drop the player somewhere and look a direction."""
        px, py, pz = (float(pos[0]), float(pos[1]), float(pos[2]))
        if self.movement == "walk":
            py = self.scene.ground_height(px, pz) + self.eye_height
        if pitch is None:
            pitch = self.pitch
        if yaw is not None:
            self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.pos = [px, py, pz]
        self.aim = (self.yaw, self.pitch)
        self.publish_camera()

    def face(self, yaw, pitch=None):
        """Set yaw (and optionally pitch) without moving."""
        self.yaw = float(yaw)
        if pitch is not None:
            self.pitch = max(-self.pitch_limit,
                             min(self.pitch_limit, float(pitch)))
        self.aim = (self.yaw, self.pitch)
        self.publish_camera()

    def look_at(self, target, damping=None):
        """Turn the head toward a world point."""
        d = normalize(np.asarray(target, np.float64) -
                      np.asarray(self.pos, np.float64))
        yaw = math.atan2(float(d[0]), float(d[2]))
        pitch = math.asin(max(-1.0, min(1.0, float(d[1]))))
        rate = self.aim_damping if damping is None else float(damping)
        if rate > 0.0:
            self.aim = (yaw, max(-self.pitch_limit,
                                 min(self.pitch_limit, pitch)))
        else:
            self.face(yaw, pitch)
        return (self.yaw, self.pitch)

    def forward(self):
        """Unit forward vector from yaw/pitch, for raycasts and aim."""
        cp = math.cos(self.pitch)
        return (math.sin(self.yaw) * cp, math.sin(self.pitch),
                math.cos(self.yaw) * cp)

    def is_moving(self):
        right, fwd, up, _run = self.poll_move()
        return bool(right or fwd or up)

    def __repr__(self):
        where = " ".join(f"{c:g}" for c in self.pos)
        return f"<Player3D {self.tag} ({where}) yaw {self.yaw:.2f} " \
               f"pitch {self.pitch:.2f}>"


class Player2D(Object2D):
    """A sprite steered through 2D space, camera locked on."""

    name = "player2d"
    is_player = True
    clone_attrs = ()

    move_speed = 320.0                 # world pixels per second
    run_multiplier = 1.8               # with the `run` action held
    bounds = None                      # (w, h) box from the origin, or 0
    wheel_zoom = True
    follows_view = True
    lock_input = False
    # radius to a Collision2D; None takes half my sprite
    body_radius = None
    collide_group = "player"
    doc_knobs = ("move_speed", "run_multiplier", "bounds", "wheel_zoom",
                 "follows_view", "lock_input", "body_radius",
                 "collide_group")

    def __init__(self, scene, pos=(0.0, 0.0), size=(32.0, 32.0),
                 texture="white", col=(1.0, 1.0, 1.0), rot=0.0,
                 anchor=(0.5, 0.5), grid=(1, 1), frame=0, uv=None,
                 flip=False, tag=None, blend="alpha", **knobs):
        super().__init__(scene, pos=pos, size=size, texture=texture,
                         col=col, rot=rot, anchor=anchor, grid=grid,
                         frame=frame, uv=uv, flip=flip, tag=tag,
                         blend=blend)
        # which axes the last move ran into (see Player3D.hits)
        self.hits = (False, False)
        self.set_knobs(knobs)
        self.input.bind_defaults()

    def camera(self):
        """The rig I drive: mine, or the scene's default view."""
        return self.look_camera or getattr(self.scene, "view2d", None)

    def update(self, dt):
        """Advance clock/timers/frames, then move and drag the view."""
        super().update(dt)
        self.apply_move(dt)
        self.publish_camera()

    def apply_move(self, dt):
        if self.lock_input:
            return
        ax = self.input.axis("right", "left")
        ay = self.input.axis("down", "up")   # world y grows downward
        if not (ax or ay):
            return
        run = self.input.down("run")
        speed = self.move_speed * (self.run_multiplier if run else 1.0)
        n = math.hypot(ax, ay)
        delta = [ax / n * speed * dt, ay / n * speed * dt]
        sweep = getattr(self.scene, "move_body2d", None)
        if sweep is None:
            self.pos = [float(p) + float(d) for p, d in zip(self.pos,
                                                             delta)]
        else:
            self.pos, self.hits = sweep(self.pos, delta,
                                        self.rounded(), self.collide_group)
        self._clamp_to_world()
        self.dirty = True

    def rounded(self):
        """My radius against a flat wall, in world pixels."""
        if self.body_radius is not None:
            return float(self.body_radius)
        return min(float(self.size[0]), float(self.size[1])) * 0.5

    def _clamp_to_world(self):
        b = self.bounds if self.bounds is not None \
            else getattr(self.scene, "world_size", None)
        if b:
            self.pos[0] = max(0.0, min(float(b[0]), self.pos[0]))
            self.pos[1] = max(0.0, min(float(b[1]), self.pos[1]))

    def publish_camera(self):
        """Centre my camera on me (its shake/easing stays its own)."""
        cam = self.camera()
        if cam is not None and self.follows_view:
            cam.set_center(self.pos)
        return cam

    def handle_event(self, e, pos=None):
        """Wheel over the view zooms the camera I drive."""
        if self.wheel_zoom and e.type == pygame.MOUSEWHEEL:
            cam = self.camera()
            if cam is not None:
                cam.zoom_by(e.y)
                return True
        return False

    def teleport(self, pos, yaw=None, pitch=None):
        """Drop somewhere and take the view with me."""
        self.pos = [float(pos[0]), float(pos[1])]
        if yaw is not None:
            self.rot = float(yaw)
        self.dirty = True
        self.publish_camera()
        return self


# back-compat: the original single flavour keeps its name
Player = Player3D
