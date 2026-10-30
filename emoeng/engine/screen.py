"""Screens: a scene inside a scene - `Screen3D` and `Screen2D`."""

import math

import numpy as np
import pygame

from . import colors, shaders
from .camera import CameraHost
from .game import register_builtin_textures
from .meshes import box
from .objects import Object2D, Object3D
from .renderer import Renderer

# the shapes a screen's picture can be cut to
SHAPES = ("rect", "round", "circle", "soft")

# where a screen's sound comes from: flat or spatial
AUDIO_MODES = ("global", "emitter")


class _SubSurface(pygame.Surface):
    """What a nested scene paints its HUD on.
    `pygame.draw` refuses anything else."""

    def __init__(self, size):
        super().__init__((max(1, int(size[0])), max(1, int(size[1]))),
                         pygame.SRCALPHA)
        self.fill((0, 0, 0, 0))

    def fit(self, size):
        """Take a size, and clear the last frame."""
        size = (max(1, int(size[0])), max(1, int(size[1])))
        if size != self.get_size():
            pygame.Surface.__init__(self, size, pygame.SRCALPHA)
        self.fill((0, 0, 0, 0))
        return self

    def set_target(self, surface):
        """An overlay aimed at a frame: match it, then clear."""
        return self.fit(surface.get_size())


class _SubAudio:
    """The nested scene's audio, scaled by where the screen sits."""

    def __init__(self, audio, screen):
        self._audio = audio
        self._screen = screen

    def play(self, name, gain=1.0, **kw):
        return self._audio.play(name, float(gain) * self._screen.audio_gain(),
                                **kw)

    def __getattr__(self, name):
        return getattr(self._audio, name)


class _SubHost(CameraHost):
    """Enough of a Game for a nested scene."""

    def __init__(self, screen):
        self.owner = screen
        self.parent = screen.game
        self.project = screen.project
        self.renderer = screen.offscreen
        self.surface = _SubSurface(screen.pixels)
        self.audio = _SubAudio(screen.game.audio, screen)
        self.input = screen.game.input
        self.fonts = screen.game.fonts
        self.save = screen.game.save
        self.time = 0.0
        self.last_dt = 1 / 60.0
        self.fps = 0.0
        self.state = "play"
        self.paused = False
        self.running = True
        self.init_camera()

    @property
    def screen(self):
        """`game.screen`: the object both worlds share."""
        return self.surface

    def __getattr__(self, name):
        """Anything else the outer Game answers, this host answers too."""
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.parent, name)

    def play_area(self):
        return pygame.Rect(0, 0, *self.surface.get_size())

    def set_player(self, pos, yaw=None, pitch=None):
        scene = self.owner.nested
        player = getattr(scene, "player", None) if scene is not None else None
        if player is not None:
            teleport = getattr(player, "teleport", None)
            if teleport is not None:
                teleport(pos, yaw, pitch)
                return
            player.pos = [float(c) for c in pos]
            publish = getattr(player, "publish_camera", None)
            if publish is not None:
                publish()
            return
        cam = self.camera
        cam.eye = [float(pos[0]), float(pos[1]), float(pos[2])]
        if yaw is not None:
            cam.yaw = float(yaw)
        if pitch is not None:
            cam.pitch = float(pitch)
        cam.wanted = (cam.yaw, cam.pitch)

    def load_scene(self, name=None):
        self.owner.show(name)

    def play_scene(self, name, fade=0.35):
        """No fades; the picture swaps next frame."""
        self.owner.show(name)

    def push_scene(self, name, fade=0.35):
        cur = getattr(self.owner.nested, "name", None)
        if cur is not None:
            self.owner.stack.append(cur)
        self.owner.show(name)

    def pop_scene(self, fade=0.35):
        stack = self.owner.stack
        self.owner.show(stack.pop() if stack else None)

    def restart_scene(self):
        self.owner.show(self.owner.showing)

    def quit(self):
        self.owner.set_on(False)


class ScreenMixin:
    """The part of a screen shared by 2D and 3D."""

    pixels = (320, 180)          # the nested frame's own resolution
    shape = "rect"
    brightness = 1.0
    tint = (1.0, 1.0, 1.0)
    post = ()
    takes_input = False
    audio_mode = "global"
    gain = 1.0
    reach = 20.0                 # metres before an emitter falls silent
    refresh = 30.0               # pictures per second; 0 means every frame
    cull_dist = 60.0
    showing = None

    # `pixels` and `tint` stay out: rounding breaks frame buffers
    doc_knobs = ("shape", "brightness", "post", "takes_input",
                 "audio_mode", "gain", "reach", "refresh", "cull_dist")

    # assignments mark the panel dirty, so changes land next frame
    @property
    def overlay(self):
        """`overlay(picture, screen)` painted over the frame, or None."""
        return getattr(self, "_overlay", None)

    @overlay.setter
    def overlay(self, fn):
        self._overlay = fn
        self._dirty = True

    def screen_setup(self, name=None, pixels=None, shape=None,
                     brightness=None, tint=None, post=None, audio=None,
                     audio_mode=None, input=None, overlay=None,
                     reach=None, refresh=None, cull_dist=None):
        self.offscreen = None
        self.nested = None
        self.sub = None
        self.error = None
        self.on = True
        self.stack = []
        self._busy = False
        self._want = None
        self._key = f"screen:{id(self)}"
        self._mask_key = None
        self._mask_arr = None
        self._blank = False
        self._since = 0.0
        self._dirty = True
        self.game = self.scene.game
        self.project = self.scene.project
        if pixels:
            self.pixels = (max(16, int(pixels[0])),
                           max(16, int(pixels[1])))
        if shape in SHAPES:
            self.shape = shape
        if brightness is not None:
            self.brightness = float(brightness)
        if tint is not None:
            self.tint = colors.rgb(tint, self.tint)
        if post is not None:
            self.post = tuple(post)
        if reach is not None:
            self.reach = max(1.0, float(reach))
        if audio is not None:
            self.gain = max(0.0, float(audio))
        if audio_mode in AUDIO_MODES:
            self.audio_mode = audio_mode
        if input is not None:
            self.takes_input = bool(input)
        if overlay is not None:
            self.overlay = overlay
        if refresh is not None:
            self.refresh = max(0.0, float(refresh))
        if cull_dist is not None:
            self.cull_dist = max(1.0, float(cull_dist))
        # a document may name the scene a screen shows
        name = name or (getattr(self, "look", None) or {}).get("showing")
        if name:
            self.show(name)

    def _ensure(self):
        """Make the offscreen rig and the panel's texture, once."""
        if self.offscreen is not None:
            return self.offscreen
        w, h = self.pixels
        self.offscreen = Renderer(w, h,
                                  share=getattr(self.scene, "renderer",
                                                None))
        if self.offscreen.shared is None:
            # a standalone rig has no cache, so hand it sheets
            register_builtin_textures(self.offscreen,
                                      getattr(self, "project", None))
            if self.project is not None:
                self.project.register_textures(self.offscreen)
        blank = np.zeros((h, w, 4), np.uint8)
        blank[:, :, 3] = 255
        self.scene.renderer.write_texture(self._key, blank)
        return self.offscreen

    def _ready(self):
        """Make the rig, honouring the document's `showing`."""
        self._ensure()
        look = getattr(self, "look", None) or {}
        for knob, floor in (("refresh", 0.0), ("cull_dist", 1.0)):
            if look.get(knob) is not None:
                setattr(self, knob, max(floor, float(look[knob])))
        if self.showing is None:
            want = (getattr(self, "look", None) or {}).get("showing")
            if want:
                self.show(want)

    def show(self, name=None):
        """Show a project scene; None keeps the current one."""
        if name is None:
            name = self.showing
        if name is None or self.project is None:
            return None
        if self._busy:            # a nested on_enter asked for another scene
            self._want = name
            return None
        self.showing = name
        self._ensure()
        self._drop()
        self.sub = _SubHost(self)
        self._busy = True
        try:
            self.nested = self.project.scene(name, self.sub)
            self.nested.on_enter()
            self.error = None
        except Exception as exc:      # a broken nested scene is not fatal
            self.nested = None
            self.error = f"{name}: {exc}"
        finally:
            self._busy = False
        self._dirty = True
        want, self._want = self._want, None
        if want and want != name:
            return self.show(want)
        return self.nested

    def _drop(self):
        if self.nested is not None:
            try:
                self.nested.on_exit()
            except Exception:
                pass
        self.nested = None

    def screen_update(self, dt):
        """Step the nested scene; redraw the panel when due."""
        if not self.on:
            if not self._blank:
                self._blank = True
                self._paint(None)
            return
        self._blank = False
        nested, sub = self.nested, self.sub
        if nested is None or sub is None:
            return
        self._since += dt
        passes = tuple(self.post or getattr(nested, "post", ()))
        gpu = self._gpu()
        try:
            nested.update(dt)
            sub.sync_camera(nested, dt)
            if not (self._due() and (self._dirty or self._visible())):
                return
            # the panel's look rides the nested rig's own GPU chain
            owner = getattr(self, "project", None) or \
                getattr(nested, "project", None)
            sub.renderer.set_clock(getattr(nested, "t", 0.0))
            sub.renderer.set_post(shaders.resolve(owner, passes))
            gpu = gpu and self.overlay is None
            sub.renderer.gpu_only = gpu
            try:
                pic = nested.render()
            finally:
                sub.renderer.gpu_only = False
        except Exception as exc:
            self.error = f"{self.showing}: {exc}"
            self._paint(None)
            return
        self._since = 0.0
        self._dirty = False
        if gpu:
            self._paint(sub.renderer.last_out)
            return
        if self.overlay is not None:
            try:
                self.overlay(pic, self)
            except Exception as exc:
                self.error = f"overlay: {exc}"
        self._upload(pic)

    def _due(self):
        """True when the refresh clock allows a repaint."""
        if self._dirty or self.refresh <= 0.0:
            return True
        return self._since >= 1.0 / self.refresh

    def _visible(self):
        """False only when the panel is out of the way."""
        scene = getattr(self, "scene", None)
        if scene is None or getattr(scene, "editor_build", False):
            return True
        if getattr(scene, "kind", "3d") != "3d":
            return True
        cam = getattr(scene, "view", None)
        if cam is None:
            return True
        try:
            eye = [float(c) for c in cam.eye]
            d = [float(p) - eye[i] for i, p in enumerate(self.pos[:3])]
        except (TypeError, ValueError, IndexError, AttributeError):
            return True
        dist2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        if dist2 <= 1.0:
            return True                  # the walker is inside the panel
        if dist2 > self.cull_dist * self.cull_dist:
            return False
        yaw, pitch = float(cam.yaw), float(cam.pitch)
        cp = math.cos(pitch)
        fwd = (math.sin(yaw) * cp, math.sin(pitch), math.cos(yaw) * cp)
        dist = math.sqrt(dist2)
        dot = (fwd[0] * d[0] + fwd[1] * d[1] + fwd[2] * d[2]) / dist
        half = math.radians(float(getattr(cam, "fov", 70.0)) * 0.5 + 20.0)
        return dot >= math.cos(half)

    def warm(self):
        """Step the nested scene once, to fill the panel."""
        if self.nested is None and self.showing:
            self.show(self.showing)
        if self.nested is not None and self.on:
            self._dirty = True
            self.screen_update(0.0)
        return self.nested

    def _gpu(self):
        """True when this panel's picture can stay on the GPU."""
        off = self.offscreen
        return off is not None and off.shared is not None

    def _paint(self, pic):
        """Hand a picture to the panel, cheaply when possible."""
        if self._gpu():
            self.scene.renderer.composite_panel(
                pic, self._key, shape=self.shape, tint=self.tint,
                brightness=self.brightness)
        else:
            self._upload(pic)

    def _upload(self, pic):
        """Crop the picture to the screen shape for GL."""
        w, h = self.pixels
        mask = self._mask(w, h)
        art = np.zeros((h, w, 4), np.uint8)
        art[:, :, 3] = mask
        if pic is not None:
            if pic.get_size() != (w, h):
                pic = pygame.transform.smoothscale(pic, (w, h))
            # array3d already returns a fresh array; do not copy
            arr = pygame.surfarray.array3d(pic).transpose(1, 0, 2)
            col = np.asarray(self.tint, np.float32) * self.brightness
            if col[0] == col[1] == col[2] == 1.0:
                # a plain panel needs no colour maths; skip the temporaries
                art[:, :, :3] = arr
            else:
                art[:, :, :3] = np.clip(arr * col, 0, 255).astype(np.uint8)
        self.scene.renderer.write_texture(self._key, art)

    def _mask(self, w, h):
        """The alpha mask for the current shape, cached per size."""
        key = (w, h, self.shape)
        if self._mask_key == key and self._mask_arr is not None:
            return self._mask_arr
        xs = (np.arange(w, dtype=np.float32) + 0.5)
        ys = (np.arange(h, dtype=np.float32) + 0.5)
        xg = xs[None, :]
        yg = ys[:, None]
        if self.shape == "circle":
            d = ((xg - w / 2.0) / (w / 2.0)) ** 2 + \
                ((yg - h / 2.0) / (h / 2.0)) ** 2
            mask = (d <= 1.0).astype(np.float32) * 255.0
        elif self.shape == "round":
            rad = 0.10 * min(w, h)
            dx = xg - np.clip(xg, rad, w - rad)
            dy = yg - np.clip(yg, rad, h - rad)
            mask = (np.hypot(dx, dy) <= rad).astype(np.float32) * 255.0
        elif self.shape == "soft":
            edge = np.minimum(np.minimum(xg, w - xg),
                              np.minimum(yg, h - yg))
            mask = np.clip(edge / max(2.0, 0.08 * min(w, h)),
                           0.0, 1.0) * 255.0
        else:
            mask = np.full((h, w), 255.0, np.float32)
        self._mask_key = key
        self._mask_arr = mask.astype(np.uint8)
        return self._mask_arr

    def set_on(self, on=True):
        """Switch the panel on or off; off stops stepping."""
        self.on = bool(on)
        self._dirty = True
        return self

    def toggle(self):
        return self.set_on(not self.on)

    def set_brightness(self, value=1.0):
        self.brightness = max(0.0, float(value))
        self._dirty = True
        return self

    def set_tint(self, color):
        self.tint = colors.rgb(color, self.tint)
        self._dirty = True
        return self

    def set_shape(self, shape):
        if shape in SHAPES:
            self.shape = shape
        self._dirty = True
        return self

    def set_post(self, *names):
        """The shaders this panel's picture runs through, by name."""
        self.post = tuple(names)
        self._dirty = True
        return self

    def set_audio(self, mode="global", gain=None, reach=None):
        """Choose flat sound or an emitter, and volume."""
        if mode in AUDIO_MODES:
            self.audio_mode = mode
        if gain is not None:
            self.gain = max(0.0, float(gain))
        if reach is not None:
            self.reach = max(1.0, float(reach))
        return self

    def audio_gain(self):
        """How loud this screen's scene plays right now."""
        if not self.on:
            return 0.0
        if self.audio_mode != "emitter" or \
                getattr(self.scene, "kind", "3d") != "3d":
            return float(self.gain)
        eye = self.game.eye
        d = math.dist(tuple(eye), tuple(self.pos))
        return float(self.gain) * max(0.0, 1.0 - d / self.reach)

    def send(self, e):
        """Forward an event to the nested scene."""
        if not self.takes_input or self.nested is None:
            return False
        try:
            return bool(self.nested.handle_event(e))
        except Exception:
            return False

    # -- being pointed at --------------------------------------------------
    def pickable(self):
        """Can a mouse ray land on this panel right now?"""
        return bool(self.takes_input and self.nested is not None
                    and self.on and getattr(self, "alive", True))

    def panel_normal(self):
        """The direction the picture faces, in world space."""
        return (math.sin(self.yaw), 0.0, math.cos(self.yaw))

    def panel_uv(self, world):
        """A world point on the panel to a nested pixel."""
        w, h = float(self.size[0]), float(self.size[1])
        if w <= 0.0 or h <= 0.0:
            return None
        s, c = math.sin(self.yaw), math.cos(self.yaw)
        dx = float(world[0]) - float(self.pos[0])
        dy = float(world[1]) - float(self.pos[1])
        dz = float(world[2]) - float(self.pos[2])
        along = dx * c - dz * s           # metres right of the centre
        if abs(along) > w / 2.0 or abs(dy) > h / 2.0:
            return None
        pw, ph = self.pixels
        return ((along / w + 0.5) * (pw - 1),
                (0.5 - dy / h) * (ph - 1))

    def clone_extra(self):
        """A clone starts blank: panels differ per picture."""
        return {}

    def dispose_screen(self):
        """Drop the nested scene, the offscreen rig and the texture."""
        self._drop()
        if self.offscreen is not None:
            try:
                self.offscreen.dispose()
            except Exception:
                pass
            self.offscreen = None
        outer = self.scene.renderer
        outer.drop_panel(self._key)
        tex = outer.textures.pop(self._key, None)
        if tex is not None:
            try:
                tex.release()
            except Exception:
                pass


class Screen3D(ScreenMixin, Object3D):
    """A panel in a 3D scene showing another scene."""

    name = "screen3d"
    clone_attrs = ("size", "depth")
    doc_knobs = ScreenMixin.doc_knobs + ("opacity",)

    depth = 0.06                  # metres the panel stands off its wall

    def __init__(self, scene, pos=(0.0, 0.0, 0.0), yaw=0.0, scale=1.0,
                 size=(3.2, 1.8), glow=False, depth=None, tag=None,
                 opacity=1.0, **kw):
        super().__init__(scene, pos, yaw, scale, tag=tag, opacity=opacity)
        self.size = (float(size[0]), float(size[1]))
        self.glow = bool(glow)
        if depth is not None:
            self.depth = float(depth)
        self.screen_setup(**kw)

    def build(self):
        self._ready()
        w, h = self.size
        col = self.look.get("color") if isinstance(self.look, dict) else None
        blend = "add" if self.glow else "panel"
        if getattr(self.scene, "editor_build", False):
            # additive panels wash out over the grid; Edit shows straight
            blend = "panel"
        # centre the box half its depth forward, never straddling
        d = self.depth
        centre = (self.pos[0] + math.sin(self.yaw) * d * 0.5, self.pos[1],
                  self.pos[2] + math.cos(self.yaw) * d * 0.5)
        # `self.add` reads my `opacity` off the owner link
        self.add(box(centre=centre, size=(w, h, d),
                     yaw=getattr(self, "yaw", 0.0), col=col or (1, 1, 1)),
                 texture=self._key,
                 blend=blend)

    def update(self, dt):
        super().update(dt)
        self.screen_update(dt)

    def dispose(self):
        self.dispose_screen()
        super().dispose()


class Screen2D(ScreenMixin, Object2D):
    """A sprite showing another scene, in 2D or UI."""

    name = "screen2d"
    clone_attrs = ("size",)
    doc_knobs = ScreenMixin.doc_knobs + ("opacity",)

    def __init__(self, scene, pos=(0.0, 0.0), size=(320.0, 180.0),
                 blend="hud", tag=None, opacity=1.0, **kw):
        super().__init__(scene, pos=pos, size=size, texture="white",
                         blend=blend, tag=tag, opacity=opacity)
        self.screen_setup(**kw)

    def build(self):
        self._ready()
        self.texture = self._key
        super().build()

    def update(self, dt):
        super().update(dt)
        self.screen_update(dt)

    def dispose(self):
        self.dispose_screen()
        super().dispose()
