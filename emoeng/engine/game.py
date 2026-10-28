"""The emoeng game runtime: one XP window, one scene loop."""

import math
import sys
import time
from collections import deque
from pathlib import Path

import pygame

from .. import const
from . import config, inputmap, paths, proctex, shaders, theme, ui
from . import wincontext, xp
from .audio import Audio, build_starter_kit
from .camera import CameraHost, wish
from .input import Input, binding_labels, is_focus_lost
from .loader import Project, int_pair
from .renderer import Renderer
from .save import SaveStore
from .winchrome import WindowChrome, caption_buttons

CAP_H = 28
MENU_H = 22
STATUS_H = 22
MENU_LABELS = ("Game", "View", "Help")
SHOT_PREFIX = const.ENGINE_NAME.lower() + "_"


def default_icon_surface(text="", px=32):
    """The fallback window badge: the first two letters of `text`,"""
    try:
        pygame.font.init()
        surf = pygame.Surface((px, px), pygame.SRCALPHA)
        surf.fill((52, 96, 158, 255))
        font = pygame.font.SysFont("tahoma", max(8, int(px * 0.55)),
                                   bold=True)
        initials = (str(text).strip()[:2] or "P").upper()
        img = font.render(initials, True, (255, 255, 255))
        surf.blit(img, ((px - img.get_width()) // 2,
                        (px - img.get_height()) // 2))
        return surf
    except (pygame.error, OSError, ValueError):
        return None


def project_icon_surface(project, px=32):
    """The picture the window wears: the project's `icon.png` beside"""
    candidates = []
    root = getattr(project, "path", None)
    if root is not None:
        candidates.append(Path(root) / const.ICON_NAME)
    if paths.frozen():
        candidates.append(paths.app_dir() / const.ICON_NAME)
    for cand in candidates:
        try:
            if cand.is_file():
                art = pygame.image.load(str(cand))
                try:
                    art = art.convert_alpha()
                except pygame.error:
                    pass
                return pygame.transform.smoothscale(art, (px, px))
        except (OSError, ValueError, pygame.error):
            continue
    name = str(getattr(project, "name", "") or
               getattr(project, "title", ""))
    return default_icon_surface(name, px)


# the words a sheet is registered with, as a project may file them too
SHEET_OPTIONS = ("tile", "rgba", "repeat", "filter", "mipmaps", "wrap")


def builtin_sheet(name, project=None):
    """(array, register options) for one built-in, this project's turn on."""
    over = {}
    if project is not None:
        find = getattr(project, "sheet_overrides", None)
        if find is not None:
            try:
                over = find(name) or {}
            except Exception:
                over = {}
    opts = proctex.options(name)
    opts.update({k: v for k, v in over.items() if k in SHEET_OPTIONS})
    arr = proctex.build(name, **over)
    if arr is None:
        return None, {}
    mips = opts.get("mipmaps", True)
    kwargs = {"rgba": arr.ndim == 3 and arr.shape[2] >= 4,
              "repeat": (opts.get("repeat", True) is not False
                         and str(opts.get("wrap", "repeat")) == "repeat"),
              "filter": str(opts.get("filter", "linear")),
              "mipmaps": mips not in (False, "off", 0, "0"),
              "tile": opts.get("tile", 0.0)}
    return arr, kwargs


def register_builtin_textures(renderer, project=None):
    """Upload the file-less sheets, with a project's turns applied.

    Each one carries its own `tile` in metres, so it is laid over the uv the
    way a shader would: the same grain per metre on a small crate and a
    wide wall, instead of one picture stretched over whatever fits.
    """
    for name, _make, _opts in proctex.BUILTIN:
        arr, kwargs = builtin_sheet(name, project)
        if arr is not None:
            renderer.texture(name, arr, **kwargs)
    return renderer


# what the status bar has room for: (action, word)
CONTROLS_HINT = (("forward", "move"), ("use", "use"),
                 ("pause", "pause"))


def control_hint(keys, scene, hints=CONTROLS_HINT):
    """The live keymap, squeezed into one status-bar line."""
    def text(action):
        return binding_labels(keys.bindings_of(action))

    if getattr(scene, "kind", "3d") != "3d":
        got = text("pause")
        return f"{got} pause" if got else ""
    parts = []
    for action, word in hints:
        got = text(action)
        if got:
            parts.append(f"{got.split(',')[0].strip()} {word}")
    if parts:
        parts.insert(1, "mouse look")
    more = text("help")
    if more:
        parts.append(f"{more} for the rest")
    return "  /  ".join(parts)


class Game(CameraHost):
    """Owns window, chrome, renderer, audio and camera."""

    def __init__(self, project, title=None, size=None, render_scale=None,
                 master_volume=None, seed=None):
        self.project = project if isinstance(project, Project) \
            else Project(project)
        cfg = config.load(self.project)
        self.cfg = cfg

        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        theme.apply(theme.load())
        self.project.title = title or self.project.title
        pygame.display.set_caption(self.project.title)
        # the window icon: uploaded, beside-exe, or the default
        art = project_icon_surface(self.project)
        if art is not None:
            try:
                pygame.display.set_icon(art)
            except pygame.error:
                pass

        win_size = tuple(size or self.project.size)
        # fullscreen: the project ships it, the player can set it
        self.fullscreen = bool(self._pick("runtime.fullscreen", "window",
                                          "fullscreen", False))
        self.resizable = bool(self._pick("", "window", "resizable", True))
        self.min_size = int_pair(self._pick("", "window", "min_size", None),
                                 self.project.min_size)
        self.vsync = bool(self._pick("runtime.vsync", "render", "vsync",
                                     True))
        # `runtime.gl_window` asks for a GL-presented window
        self.gl_wanted = bool(cfg.get("runtime.gl_window"))
        self.gl_ok = False
        self.winctx = None
        self.screen = self._set_mode(win_size)
        self.clock = pygame.time.Clock()
        self.fonts = {
            "small": pygame.font.SysFont("tahoma", 11),
            "normal": pygame.font.SysFont("tahoma", 13),
            "big": pygame.font.SysFont("tahoma", 18, bold=True),
            "title": pygame.font.SysFont("tahoma", 28, bold=True),
            "mono": pygame.font.SysFont("consolas", 12),
        }
        self.icon = None

        scale = render_scale if render_scale is not None \
            else (cfg.get("runtime.render_scale") or self.project.render_scale)
        if self.gl_ok:
            # a missing GL context falls back to the plain window
            try:
                self.renderer = Renderer(*self.screen.get_size(),
                                         render_scale=scale,
                                         windowed=True)
                self.winctx = wincontext.GLWindow(self.renderer)
            except Exception as exc:
                print(f"gl window unavailable: {exc!r}")
                if getattr(self, "renderer", None) is not None:
                    self.renderer.dispose()
                    self.renderer = None
                self.gl_wanted = self.gl_ok = False
                self.screen = self._set_mode(win_size)
        if not self.gl_ok:
            self.renderer = Renderer(*self.screen.get_size(),
                                     render_scale=scale)
        # a plain-word shader name resolves through the project
        self.renderer.project = self.project
        self._register_assets()

        master = master_volume if master_volume is not None \
            else self._pick("runtime.master_volume", "audio", "master", None)
        self.music_key = str(self._pick("", "audio", "music", "") or "")
        self.audio = build_starter_kit(Audio(
            master=master if master is not None else 0.8,
            music_volume=self._pick("runtime.music_volume", "audio",
                                    "music_volume", 0.6)))
        self.project.load_audio(self.audio)
        self.boot_music()
        self.input = Input()
        self._bind_defaults()
        self.save = SaveStore(self.project, slot=self.project.save_slot)
        # `save.auto_load`: open the slot the game boots into
        self.auto_load = bool(self._pick("", "save", "auto_load", False))
        
        # pause trigger config
        pt = self.project.get("pausetrigger") or {}
        self._pause_mode = int(pt.get("mode", 1) or 1)
        self._pause_scene = pt.get("scene")
        self._pause_script = pt.get("script")

        self.chrome = WindowChrome()
        self.state = "play"
        self.paused = False
        self.help_at_boot = bool(self._pick("", "debug", "show_help", False))
        self.show_help = self.help_at_boot
        # `debug.overlay`: off, and the scene's `overlay()` never draws
        self.overlay_on = bool(self._pick("", "debug", "overlay", True))
        self.running = True
        self.time = 0.0
        self.last_dt = 1 / 60.0
        self.debug = False
        self.fps_cap = int(self._pick("runtime.fps_cap", "render",
                                      "fps_cap", 60))
        self.show_fps = bool(self._pick("runtime.show_fps", "debug",
                                        "show_fps", True))
        self.autosave_every = float(self._pick("runtime.auto_save_interval",
                                               "save", "autosave", 0.0))
        self._autosave_in = self.autosave_every
        self.fade = 0.0
        self._fade_state = None
        self._fade_time = 0.0
        self._fade_dur = 0.35
        self._pending_scene = None
        self._fade_surface = None
        self.fps = 0.0
        # meters read raw frame seconds, never the clamped step
        self.frame_ms = 0.0
        self._frame_times = deque(maxlen=30)
        self._caption = None
        # one Camera behind `eye`/`yaw`/`pitch`
        self.init_camera(eye=(0.0, 2.0, 0.0))
        self.look_sensitivity = float(cfg.get("runtime.mouse_sensitivity"))
        self.menu_open = None
        self.menu_rows = []
        self.menu_items = []
        self.close_rect = pygame.Rect(0, 0, 0, 0)
        self.pause_buttons = {}
        self._size_applied = self.screen.get_size()
        self._last_cap_click = -1000
        self._shot_index = 0
        # pause trigger state
        self._pause_mode = 1
        self._pause_scene = None
        self._pause_script = None
        self._paused_scene = None
        self._paused_scene_name = None

        self.scene = None
        self.scene_stack = []       # push_scene/pop_scene history
        self.mouse_capture = True
        self.load_scene(self.project.start)
        self.show_help = self.help_at_boot
        if self.auto_load and self.save.path().is_file():
            self.load_game()
        self.start_time = time.time()

    def _pick(self, cfg_key, section, key, default):
        """Config wins once the player has changed it; else the manifest."""
        if cfg_key:
            got = self.cfg.get(cfg_key)
            if got is not None and got != config.DEFAULTS.get(cfg_key):
                return got
        got = self.project.get(section, key) if section else None
        if got is not None:
            return got
        return default

    def boot_music(self):
        """Start the track `audio.music` names, when the project ships it."""
        if not self.music_key:
            return False
        for path in self.project.audio_files():
            if path.stem == self.music_key:
                return self.audio.music(path)
        return False

    def _set_mode(self, size):
        """Create the window; vsync when config asks."""
        flags = (pygame.RESIZABLE if self.resizable else 0) | \
            (pygame.FULLSCREEN if self.fullscreen else 0)
        self.gl_ok = False
        if self.gl_wanted:
            try:
                surf = self._set_mode_gl(size, flags)
            except (TypeError, pygame.error):
                self.gl_wanted = False
            else:
                self.gl_ok = True
                return surf
        if self.vsync:
            try:
                return pygame.display.set_mode(size, flags, vsync=1)
            except (TypeError, pygame.error):
                self.vsync = False      # driver cannot swap synchronously
        return pygame.display.set_mode(size, flags)

    def _set_mode_gl(self, size, flags):
        """The GL branch: an OPENGL surface doubles-buffered window,"""
        gl_flags = flags | pygame.OPENGL | pygame.DOUBLEBUF
        try:
            win = pygame.display.set_mode(size, gl_flags,
                                          vsync=1 if self.vsync else 0)
        except TypeError:
            if not self.vsync:
                raise
            self.vsync = False
            win = pygame.display.set_mode(size, gl_flags)
        return pygame.Surface(win.get_size(), pygame.SRCALPHA)

    def _bind_defaults(self):
        """Engine defaults, then the project's actions and triggers."""
        self.input_map = inputmap.load(self.project, force=True)
        self.input_map.apply(self.input)
        self.binding_conflicts = self.input.conflicts()
        for name, actions in self.binding_conflicts:
            print(f"input: '{name}' is bound to {' and '.join(actions)}")
        return self.input

    # lines no binding can name: look and Ctrl+T
    CONTROLS_EXTRA = (("Mouse", "Look around"),
                      ("Ctrl+T", "Dark / light theme"),
                      ("F6", "Re-read code (hot reload)"))

    def key_text(self, action):
        """The controls an action is bound to, in words."""
        return binding_labels(self.input.bindings_of(action))

    def control_hint(self):
        """The live keymap, squeezed into one status-bar panel."""
        return control_hint(self.input, self.scene)

    def controls(self):
        """(control, what it does) pairs for the help panel."""
        lines = [ln for ln in self.CONTROLS_EXTRA
                 if getattr(self.scene, "kind", "3d") == "3d" or
                 ln[1] != "Look around"]
        for key in config.keys("input"):
            action = key.split(".", 1)[1]
            got = self.key_text(action)
            if got:
                lines.append((got, config.BY_KEY[key].label))
        for action in getattr(self.scene, "controls", ()) or ():
            got = self.key_text(action)
            if got:
                lines.append((got, str(action).replace("_", " ").title()))
        for name in self.trigger_names():
            got = self.key_text(name)
            if got:
                lines.append((got, f"broadcast {name.replace('_', ' ')}"))
        return lines

    def trigger_names(self):
        """Every trigger the project's input map declares."""
        return inputmap.load(self.project).names(trigger=True)

    def reload_config(self):
        """Re-read the config and apply the live-able knobs."""
        cfg = config.load(self.project)
        self.fps_cap = int(self._pick("runtime.fps_cap", "render",
                                      "fps_cap", 60))
        self.show_fps = bool(self._pick("runtime.show_fps", "debug",
                                        "show_fps", True))
        self.overlay_on = bool(self._pick("", "debug", "overlay", True))
        self.look_sensitivity = float(cfg.get("runtime.mouse_sensitivity"))
        self.autosave_every = float(self._pick("runtime.auto_save_interval",
                                               "save", "autosave", 0.0))
        self._autosave_in = self.autosave_every
        self.audio.set_master(self._pick("runtime.master_volume", "audio",
                                         "master", 0.8))
        self.audio.set_music_volume(self._pick("runtime.music_volume",
                                               "audio", "music_volume", 0.6))
        scale = float(cfg.get("runtime.render_scale") or 0.0)
        if scale:
            self.renderer.set_render_scale(scale)
        self._bind_defaults()
        return cfg

    def reload_code(self):
        """Re-read the project's code without restarting the game."""
        name = getattr(self.scene, "name", None) or self.project.start
        try:
            self.project = Project(self.project.path)
        except (OSError, ValueError) as exc:
            print(f"reload: the manifest did not read: {exc}")
            return False
        self.project.reload_scripts()
        track = self.audio.music_key
        try:
            self.audio.stop()
            self.project.load_audio(self.audio)
            if track is not None:
                # straight back where the music was, no silent gap
                for p in self.project.audio_files():
                    if p.stem == track:
                        self.audio.music(p, fade_ms=0)
                        break
        except Exception as exc:
            print(f"reload: audio kept as it was: {exc}")
        self._register_assets()
        self._bind_defaults()
        try:
            self.load_scene(name)
        except Exception as exc:
            print(f"reload: scene '{name}' did not load: {exc}")
            return False
        self._pending_scene = None
        print(f"reloaded code and scene '{name}'")
        return True

    def _register_assets(self):
        register_builtin_textures(self.renderer, self.project)
        self.project.register_textures(self.renderer)

    def load_scene(self, name=None):
        name = name or self.project.start
        if name is None:
            raise ValueError("project has no scenes")
        if self.scene is not None:
            try:
                self.scene.on_exit()
            except Exception:
                pass
        self.scene = self.project.scene(name, self)
        actions = getattr(self.scene, "actions", None)
        if actions:
            # a scene can add bindings; they stay until rebound
            self.input.bind_map(actions)
            self.binding_conflicts = self.input.conflicts()
        self.scene.on_enter()
        self.paused = False
        self.show_help = False
        self.time = 0.0
        # only 3D scenes pilot a grabbed mouse
        self.input.grab_mouse(self.mouse_capture and
                              getattr(self.scene, "kind", "3d") == "3d")

    def restart_scene(self):
        name = getattr(self.scene, "name", None) or self.project.start
        self.load_scene(name)

    def save_game(self, slot=None):
        """Snapshot camera and scene into the store, then write."""
        if slot is not None:
            self.save.slot = str(slot)
        self.save.set("scene", getattr(self.scene, "name",
                                       self.project.start))
        self.save.set("pos", [round(float(v), 3) for v in self.eye])
        self.save.set("yaw", round(self.yaw, 4))
        self.save.set("pitch", round(self.pitch, 4))
        self._scene_hook("on_save", self.save)
        path = self.save.save()
        print(f"saved {self.save.slot} -> {path}")
        return path

    def load_game(self, slot=None):
        """Read the store, switch to its scene, restore."""
        if slot is not None:
            self.save.slot = str(slot)
        data = self.save.load()
        name = data.get("scene")
        if name and name != getattr(self.scene, "name", None):
            self.load_scene(name)
        pos = data.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            self.set_player(pos, data.get("yaw"), data.get("pitch"))
        self._scene_hook("on_load", self.save)
        print(f"loaded {self.save.slot} ({len(self.save)} keys)")
        return data

    def _scene_hook(self, name, *args):
        """Call an optional scene hook; never break the loop."""
        hook = getattr(self.scene, name, None)
        if hook is None:
            return False
        try:
            hook(*args)
        except Exception as exc:
            print(f"scene {name} failed: {exc!r}")
            return False
        return True

    def play_scene(self, name, fade=0.35):
        """Fade to black, load another scene, fade back in."""
        if fade is None or float(fade) <= 0.0 or self.scene is None:
            self.load_scene(name)
            return
        self._pending_scene = name
        self._fade_dur = max(0.05, float(fade))
        self._fade_time = 0.0
        self._fade_state = "out"

    def push_scene(self, name, fade=0.35):
        """Stack another scene over the current one."""
        cur = getattr(self.scene, "name", None) or self.project.start
        self.scene_stack.append(cur)
        self.play_scene(name, fade=fade)

    def pop_scene(self, fade=0.35):
        """Leave the top scene and rebuild the one underneath it."""
        name = self.scene_stack.pop() if self.scene_stack else None
        self.play_scene(name, fade=fade)

    def _tick_fade(self, dt):
        """Advance the fade; swaps the scene at full black."""
        if self._fade_state is None:
            return
        self._fade_time += dt
        k = min(1.0, self._fade_time / self._fade_dur)
        if self._fade_state == "out":
            self.fade = k
            if k < 1.0:
                return
            name, self._pending_scene = self._pending_scene, None
            if name:
                try:
                    self.load_scene(name)
                except Exception as exc:
                    print(f"play_scene('{name}') failed: {exc!r}")
            self._fade_state = "in"
            self._fade_time = 0.0
        else:
            self.fade = 1.0 - k
            if k >= 1.0:
                self.fade = 0.0
                self._fade_state = None

    def set_player(self, pos, yaw=None, pitch=None):
        """Teleport the camera."""
        player = getattr(self.scene, "player", None) if self.scene else None
        if player is not None:
            teleport = getattr(player, "teleport", None)
            if teleport is not None:
                teleport(pos, yaw, pitch)
                return
            player.pos = [float(c) for c in pos]
            if yaw is not None:
                player.yaw = float(yaw)
            if pitch is not None and hasattr(player, "pitch"):
                player.pitch = float(pitch)
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
        cam.stop_shake()

    def follow(self, target, offset=None, damping=None):
        """Chase an object or a point with the damped camera."""
        return self.camera.set_follow(target, offset, damping)

    def _camera_move(self, dt):
        """Legacy movement for scenes without a Player object."""
        if getattr(self.scene, "player", None) is not None:
            return
        s = self.scene
        rig = getattr(s, "camera_rig", None)
        right, fwd = self.input.move_axis()
        run = self.input.down("run")
        if rig is not None:
            rig.look(self.yaw, self.pitch)
            if not getattr(s, "lock_input", False):
                rig.move(wish(self.yaw, right, fwd), run, dt)
            ex, ey, ez = rig.eye()
            self.eye[0], self.eye[1], self.eye[2] = ex, ey, ez
            return
        speed = s.move_speed[1] if run else s.move_speed[0]
        vx, vz = wish(self.yaw, right, fwd)
        vx *= speed * dt
        vz *= speed * dt
        vy = (1.0 if self.input.down("up") else 0.0) - \
             (1.0 if self.input.down("down") else 0.0)
        if not getattr(s, "lock_input", False):
            self.eye[0] += vx
            self.eye[2] += vz
            if s.camera == "fly":
                self.eye[1] += vy * speed * dt
        ground = s.ground_height(self.eye[0], self.eye[2])
        if s.camera == "walk":
            self.eye[1] = ground + s.eye_height
        else:
            self.eye[1] = max(self.eye[1], ground + 0.6)
        r = math.hypot(self.eye[0], self.eye[2])
        if s.world_radius and r > s.world_radius:
            k = s.world_radius / r
            self.eye[0] *= k
            self.eye[2] *= k

    def _mouse_look(self):
        """Legacy look for scenes without a Player object."""
        if getattr(self.scene, "player", None) is not None:
            return
        dx, dy = self.input.mouse_rel
        if dx == 0 and dy == 0:
            return
        # yaw increases leftward: turning right subtracts from it
        cam = self.camera
        base = cam.wanted if cam.wanted is not None else (cam.yaw, cam.pitch)
        cam.aim(base[0] - dx * self.look_sensitivity,
                base[1] - dy * self.look_sensitivity, self.last_dt)

    def pause(self):
        if self.paused:
            return
        
        # Reload pause config in case it changed
        pt = self.project.get("pausetrigger") or {}
        self._pause_mode = int(pt.get("mode", 1) or 1)
        self._pause_scene = pt.get("scene")
        self._pause_script = pt.get("script")
        
        if self._pause_mode == 1:
            # Engine pause menu (current behavior)
            self.paused = True
            self.state = "pause"
            self.input.grab_mouse(False)
            self.menu_open = None
        elif self._pause_mode == 2:
            # Pause scene: switch to pause scene, save current scene state
            if self._pause_scene and self._pause_scene != getattr(self.scene, "name", None):
                self._paused_scene_name = getattr(self.scene, "name", None)
                # Save current scene state
                self._paused_scene = {
                    "name": self._paused_scene_name,
                    "time": self.time,
                    "eye": list(self.eye) if hasattr(self, "eye") else [0, 2, 0],
                    "yaw": self.yaw if hasattr(self, "yaw") else 0,
                    "pitch": self.pitch if hasattr(self, "pitch") else 0,
                }
                # Call on_exit on current scene
                if self.scene:
                    try:
                        self.scene.on_exit()
                    except Exception:
                        pass
                # Load pause scene
                self.load_scene(self._pause_scene)
                self.paused = True
                self.state = "pause"
                self.input.grab_mouse(False)
            else:
                # Fallback to engine pause
                self.paused = True
                self.state = "pause"
                self.input.grab_mouse(False)
                self.menu_open = None
        elif self._pause_mode == 3:
            # Pause script: run the selected script
            if self._pause_script:
                self._run_pause_script(self._pause_script)
            self.paused = True
            self.state = "pause"
            self.input.grab_mouse(False)
            self.menu_open = None
        else:
            # Default to engine pause
            self.paused = True
            self.state = "pause"
            self.input.grab_mouse(False)
            self.menu_open = None

    def _run_pause_script(self, script_name):
        """Run a script from scripts/ as the pause action."""
        try:
            script_path = self.project.scripts_dir / f"{script_name}.py"
            if script_path.is_file():
                # Import and run the script
                import importlib.util
                spec = importlib.util.spec_from_file_location(f"pause_{script_name}", str(script_path))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                # Look for a pause function or just execute the module
                if hasattr(module, "on_pause"):
                    module.on_pause(self)
                elif hasattr(module, "pause"):
                    module.pause(self)
        except Exception as exc:
            print(f"pause script '{script_name}' failed: {exc!r}")

    def resume(self):
        if not self.paused:
            return
        
        if self._pause_mode == 2 and self._paused_scene_name:
            # Return to the paused scene
            name = self._paused_scene_name
            self._paused_scene_name = None
            self._paused_scene = None
            self.load_scene(name)
        else:
            self.paused = False
            self.state = "play"
            self.input.mouse_rel = (0, 0)
            self.input.grab_mouse(self.mouse_capture and
                                  getattr(self.scene, "kind", "3d") == "3d")

    def quit(self):
        self.running = False

    def screenshot(self):
        folder = Path.cwd()
        while True:
            path = folder / f"{SHOT_PREFIX}{self._shot_index:03d}.png"
            if not path.exists():
                break
            self._shot_index += 1
        if self.winctx is not None:
            # pixels live on the GPU; ask for the last swap
            pygame.image.save(self.winctx.capture(), str(path))
        else:
            pygame.image.save(self.screen, str(path))
        print(f"screenshot: {path}")

    def _caption_press(self, pos):
        if self.chrome.fullscreen:
            return False
        w, _ = self.screen.get_size()
        cap = pygame.Rect(0, 0, w, CAP_H)
        b_min, b_max, b_close = caption_buttons(cap)
        if b_close.collidepoint(pos):
            self.quit()
            return True
        if not cap.collidepoint(pos):
            return False
        if b_min.collidepoint(pos):
            self.chrome.minimize()
        elif b_max.collidepoint(pos):
            self.chrome.toggle_maximize()
        else:
            now = pygame.time.get_ticks()
            if now - self._last_cap_click < 400:
                self.chrome.toggle_maximize()
                self._last_cap_click = 0
                return True
            self._last_cap_click = now
            self.chrome.begin_move(pos)
        return True

    def _menu_cells(self):
        font = self.fonts["normal"]
        cells, x = {}, 6
        for label in MENU_LABELS:
            width = font.size(label)[0] + 12
            cells[label] = pygame.Rect(x, CAP_H, width, MENU_H)
            x += width + 2
        return cells

    def _items_for(self, label):
        if label == "Game":
            return [("Resume" if self.paused else "Pause", "toggle_pause"),
                    ("Restart Scene", "restart"),
                    ("-", None),
                    ("Screenshot", "screenshot"),
                    ("Quit", "quit")]
        if label == "View":
            return [(self._menu_key("Toggle Fullscreen", "fullscreen"),
                     "fullscreen"),
                    (self._menu_key("Toggle Help", "help"), "help"),
                    (self._menu_key("Toggle Debug", "debug"), "debug"),
                    ("Toggle Theme (Ctrl+T)", "theme"),
                    ("-" , None),
                    ("Renderer scale: %d%%" %
                     round(self.renderer.render_scale * 100), None)]
        return [("Controls", "help"), ("About", "about")]

    def _menu_key(self, text, action):
        """A menu label quoting the key actually bound."""
        got = self.key_text(action)
        return f"{text} ({got})" if got else text

    def _run_menu_action(self, action):
        if action == "toggle_pause":
            self.resume() if self.paused else self.pause()
        elif action == "restart":
            self.restart_scene()
        elif action == "screenshot":
            self.screenshot()
        elif action == "fullscreen":
            self.chrome.toggle_fullscreen()
        elif action == "help":
            self.show_help = not self.show_help
        elif action == "debug":
            self.debug = not self.debug
        elif action == "theme":
            theme.toggle()
        elif action == "quit":
            self.quit()
        elif action == "about":
            self.show_help = True

    def _handle_menu_click(self, pos):
        cells = self._menu_cells()
        for label, rect in cells.items():
            if rect.collidepoint(pos):
                if self.menu_open == label:
                    self.menu_open = None
                else:
                    self.menu_open = label
                    self.menu_items = self._items_for(label)
                return True
        if self.menu_open:
            for row, item in zip(self.menu_rows, self.menu_items):
                if row is not None and row.collidepoint(pos):
                    label, action = item
                    if action is not None:
                        self._run_menu_action(action)
                    self.menu_open = None
                    return True
            self.menu_open = None
        return False

    def _pause_click(self, pos):
        # Only handle pause button clicks for mode 1
        if self._pause_mode != 1:
            return False
        for action, rect in self.pause_buttons.items():
            if rect.collidepoint(pos):
                if action == "resume":
                    self.resume()
                elif action == "restart":
                    self.restart_scene()
                    self.resume()
                elif action == "quit":
                    self.quit()
                return True
        return False

    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.quit()
            return
        if is_focus_lost(e):
            # the keyboard went away with no key-up for the key held down
            self.input.release_all()
            return
        if e.type == pygame.VIDEORESIZE:
            self._apply_size(e.size)
        if e.type == pygame.KEYDOWN and e.key == pygame.K_t and \
                (e.mod & pygame.KMOD_CTRL):
            theme.toggle()                # a chord, so it stays a raw key
            return
        self.input.handle(e)
        if self._system_action(e):
            return

        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.chrome.drag = None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self._handle_menu_click(e.pos):
                return
            if self.paused:
                if self._pause_click(e.pos):
                    return
                if self._caption_press(e.pos):
                    return
                edges = self.chrome.resize_edges(
                    e.pos, self.screen.get_size())
                if edges:
                    self.chrome.begin_resize(edges, e.pos)
                    return
                self.menu_open = None
                return
            if not self.input.grabbed:
                if self._caption_press(e.pos):
                    return
                edges = self.chrome.resize_edges(
                    e.pos, self.screen.get_size())
                if edges:
                    self.chrome.begin_resize(edges, e.pos)
                    return
        if self.menu_open and e.type == pygame.MOUSEBUTTONDOWN:
            self.menu_open = None
        if self.paused:
            return
        if self.scene is not None:
            try:
                if self.scene.handle_event(e):
                    return
            except Exception as exc:
                print(f"scene handle_event failed: {exc!r}")

    def _system_action(self, e):
        """Fixed-function keys, taken from the configured action keymap."""
        if e.type != pygame.KEYDOWN:
            return False
        pressed = self.input.pressed
        if pressed("fullscreen"):
            self.chrome.toggle_fullscreen()
        elif pressed("pause"):
            self.menu_open = None
            self.resume() if self.paused else self.pause()
        elif pressed("help"):
            self.show_help = not self.show_help
        elif pressed("debug"):
            self.debug = not self.debug
        elif pressed("screenshot"):
            self.screenshot()
        elif pressed("restart"):
            self.restart_scene()
        elif pressed("hot_reload"):
            self.reload_code()
        elif pressed("save"):
            self.save_game()
        elif pressed("load"):
            self.load_game()
        elif pressed("capture_mouse"):
            self.mouse_capture = not self.mouse_capture
            self.input.grab_mouse(
                self.mouse_capture and
                getattr(self.scene, "kind", "3d") == "3d")
        else:
            return False
        return True

    def _clamped(self, size):
        """A window size no smaller than `window.min_size`."""
        if not self.resizable or self.fullscreen or not self.min_size:
            return tuple(size)
        return (max(size[0], self.min_size[0]), max(size[1], self.min_size[1]))

    def _apply_size(self, size):
        size = tuple(size)
        if size == self._size_applied:
            return
        self._size_applied = size
        if self.gl_ok and size != self.screen.get_size():
            # the layer and its texture must both follow a resize
            self.screen = pygame.Surface(size, pygame.SRCALPHA)
            self.winctx.resize(size)
        if self.renderer is not None:
            self.renderer.resize(*size)

    def _sync_surface(self):
        if not self.chrome.supported():
            return
        want = self._clamped(tuple(self.chrome.win.size))
        # a dummy window answers nonsense; never pass it on
        if not want or min(want) < 1:
            return
        if self.gl_ok:
            # SDL resizes the GL back buffer; no set_mode needed
            self._apply_size(want)
            return
        if want != self.screen.get_size():
            self.screen = self._set_mode(want)
        self._apply_size(want)

    def _draw_chrome(self):
        if self.chrome.fullscreen:
            self.close_rect = pygame.Rect(0, 0, 0, 0)
            return
        w, h = self.screen.get_size()
        name = getattr(self.scene, "name", "") if self.scene else ""
        title = self.project.title + (f" - {name}" if name else "")
        cap = pygame.Rect(0, 0, w, CAP_H)
        self.close_rect = xp.titlebar(self.screen, cap, title,
                                      self.fonts["normal"], icon=self.icon)
        menu = pygame.Rect(0, CAP_H, w, MENU_H)
        active = MENU_LABELS.index(self.menu_open) \
            if self.menu_open in MENU_LABELS else None
        xp.menubar(self.screen, menu, active=active,
                   font=self.fonts["normal"], labels=MENU_LABELS)
        status = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
        scene_info = ""
        if self.scene is not None:
            try:
                scene_info = " | ".join(str(p) for p in self.scene.status())
            except Exception:
                scene_info = ""
        panels = [self.project.title + (f" - {name}" if name else ""),
                  (scene_info + (f"  fps {self.fps:3.0f}"
                                 if self.show_fps else "")).strip(),
                  self.control_hint()]
        xp.statusbar(self.screen, status, panels, self.fonts["small"])
        if self.menu_open:
            pos = self._menu_cells()[self.menu_open].bottomleft
            items = [(lbl, True) for lbl, _act in self.menu_items]
            _panel, self.menu_rows = xp.menu_items(
                self.screen, pos, items, self.fonts["normal"])

    def _draw_pause(self):
        # Only draw the engine pause menu for mode 1
        # Modes 2 and 3 show their own content (pause scene or script result)
        if self._pause_mode != 1:
            return
        w, h = self.screen.get_size()
        ui.dim(self.screen, 0.55)
        frame = pygame.Rect(0, 0, 380, 210)
        frame.center = (w // 2, h // 2)
        body, _close = xp.message_frame(self.screen, frame,
                                        self.project.title,
                                        self.fonts["normal"], icon=self.icon)
        title = self.fonts["big"].render("Paused", True, xp.TEXT)
        self.screen.blit(title, (body.centerx - title.get_width() // 2,
                                 body.y + 18))
        hint = self.fonts["small"].render(
            "ESC resumes  |  mouse is released so you can move the window",
            True, xp.TEXT_MUTED)
        self.screen.blit(hint, (body.centerx - hint.get_width() // 2,
                                body.y + 46))
        bw, bh = 108, 28
        gap = 8
        total = bw * 3 + gap * 2
        x0 = frame.x + (frame.w - total) // 2
        y = frame.bottom - 46
        self.pause_buttons = {
            "resume": pygame.Rect(x0, y, bw, bh),
            "restart": pygame.Rect(x0 + bw + gap, y, bw, bh),
            "quit": pygame.Rect(x0 + 2 * (bw + gap), y, bw, bh),
        }
        mouse = pygame.mouse.get_pos()
        xp.button(self.screen, self.pause_buttons["resume"], "Resume",
                  self.fonts["normal"], default=True,
                  hovered=self.pause_buttons["resume"].collidepoint(mouse))
        xp.button(self.screen, self.pause_buttons["restart"], "Restart",
                  self.fonts["normal"],
                  hovered=self.pause_buttons["restart"].collidepoint(mouse))
        xp.button(self.screen, self.pause_buttons["quit"], "Quit",
                  self.fonts["normal"],
                  hovered=self.pause_buttons["quit"].collidepoint(mouse))

    def _draw_help(self):
        """The F1 panel, generated from the live keymap (`controls`)."""
        w, h = self.screen.get_size()
        font = self.fonts["mono"]
        lines = self.controls()
        # columns sized from the keymap, not fixed widths
        key_w = max([font.size(k)[0] for k, _t in lines] or [0]) + 14
        text_w = max([font.size(t)[0] for _k, t in lines] or [120])
        line_h = font.get_height() + 3
        frame = pygame.Rect(0, 0, min(w - 40, 64 + key_w + text_w),
                            min(h - 40, 58 + line_h * len(lines)))
        frame.center = (w // 2, h // 2)
        body, _close = xp.message_frame(self.screen, frame,
                                        "Controls", self.fonts["normal"])
        y = body.y + 10
        for key, text in lines:
            ui.text(self.screen, font, key, (body.x + 16, y),
                    color=xp.LINK)
            ui.text(self.screen, font, text, (body.x + 16 + key_w, y),
                    color=xp.TEXT)
            y += line_h

    def play_area(self):
        """The window minus its bars: the overlay area."""
        w, h = self.screen.get_size()
        if self.chrome.fullscreen:
            return pygame.Rect(0, 0, w, h)
        return pygame.Rect(0, CAP_H + MENU_H, w,
                           max(1, h - CAP_H - MENU_H - STATUS_H))

    def _view_rect(self):
        """Window rect the rendered frame belongs in."""
        tw, th = self.renderer.target
        w, h = self.screen.get_size()
        vp = self.renderer.viewport
        if not vp or tuple(vp) == (0, 0, tw, th):
            return pygame.Rect(0, 0, w, h)
        return pygame.Rect(round(vp[0] * w / tw), round(vp[1] * h / th),
                           max(1, round(vp[2] * w / tw)),
                           max(1, round(vp[3] * h / th)))

    def _view_box(self):
        """The last viewport as a bottom-origin GL uv box."""
        tw, th = self.renderer.target
        vp = self.renderer.viewport
        if not vp or tuple(vp) == (0, 0, tw, th):
            return (0.0, 0.0, 1.0, 1.0)
        x, y, w, h = vp
        gl_y = th - y - h
        return (x / tw, gl_y / th, (x + w) / tw, (gl_y + h) / th)

    def draw(self):
        # one entry point: 3D via game camera, else ortho rig
        passes = tuple(getattr(self.scene, "post", ())) or \
            tuple(self.project.post)
        # looks are project shaders, run on the GPU
        self.renderer.set_clock(getattr(self.scene, "t", 0.0))
        self.renderer.set_post(
            shaders.resolve(self.project, passes))
        gpu = self.winctx is not None
        if gpu:
            self.renderer.gpu_only = True
        try:
            frame = self.scene.render(self.camera)
        finally:
            if gpu:
                self.renderer.gpu_only = False
        if gpu:
            # the graded texture goes to the back buffer, then swap
            cc = getattr(self.scene, "clear_color", (0.02, 0.02, 0.03))
            self._draw_layer()
            self.winctx.present(self.renderer.last_out,
                                self._view_box(), self.screen, cc[:3])
            return
        rect = self._view_rect()
        if frame.get_size() != rect.size:
            frame = pygame.transform.scale(frame, rect.size)
        if rect.size != self.screen.get_size():
            cc = getattr(self.scene, "clear_color", (0.02, 0.02, 0.03))
            self.screen.fill(tuple(round(c * 255) for c in cc[:3]))
        self.screen.blit(frame, rect.topleft)
        self._draw_layer()

    def _draw_layer(self):
        """The pygame half of a frame: overlay, bars, panels, fade."""
        if self.winctx is not None:
            self.screen.fill((0, 0, 0, 0))
        if self.overlay_on:
            try:
                self.scene.overlay(self.screen)
            except Exception as exc:
                ui.text(self.screen, self.fonts["small"],
                        f"overlay error: {exc}", (12, 40),
                        color=xp.LOG_ERROR)
        self._draw_chrome()
        if self.debug:
            self._draw_debug()
        if self.show_help:
            self._draw_help()
        if self.paused:
            self._draw_pause()
        if self.fade > 0.001:
            self._draw_fade()
        w, h = self.screen.get_size()
        if not self.chrome.fullscreen:
            pygame.draw.rect(self.screen, xp.CAP_BOT, (0, 0, w, h), 1)

    def _draw_fade(self):
        size = self.screen.get_size()
        if self._fade_surface is None or \
                self._fade_surface.get_size() != size:
            self._fade_surface = pygame.Surface(size)
            self._fade_surface.fill((0, 0, 0))
        self._fade_surface.set_alpha(int(255 * max(0.0, min(1.0,
                                                     self.fade))))
        self.screen.blit(self._fade_surface, (0, 0))

    def _draw_debug(self):
        """F3: live renderer, camera and scene counters."""
        st = self.renderer.stats()
        scene = self.scene
        cam = self.camera
        rows = [
            ("fps", f"{self.fps:5.1f}"),
            ("frame", f"{self.frame_ms:5.1f} ms"),
            ("scene", getattr(scene, "name", "-")),
            ("eye", "%.1f %.1f %.1f" % tuple(cam.eye)),
            ("look", f"yaw {cam.yaw:.2f}  pitch {cam.pitch:.2f}  "
                     f"roll {cam.view_roll():.3f}"),
            ("frustum", f"fov {cam.fov:.0f}  near {cam.near:g}  "
                        f"far {cam.far:g}"),
            ("shake", f"{cam.shake_amount:.2f} "
                      f"({cam.shake_time:.2f}s left)"),
            ("objects", str(len(getattr(scene, "objects", ())))),
            ("timers", str(len(getattr(scene, "timers", ())))),
            ("lights", str(len(getattr(scene, "lights", ())))),
            ("batches", str(st["batches"])),
            ("draws", str(st["draw_calls"])),
            ("tris", f"{st['triangles']} "
                     f"({st['static_tris']}+{st['dynamic_tris']})"),
            ("textures", str(st["textures"])),
            ("viewport", "%d %d %d %d" % tuple(st["viewport"])),
            ("target", "%d x %d @ %d%%" % (st["target"][0], st["target"][1],
                                            round(st["render_scale"] * 100))),
            ("save", f"{self.save.slot}  {len(self.save)} keys"),
        ]
        font = self.fonts["small"]
        line_h = font.get_height() + 2
        pad = 8
        key_w = max(font.size(k)[0] for k, _v in rows) + 6
        val_w = max(font.size(v)[0] for _k, v in rows)
        w, h = self.screen.get_size()
        box = pygame.Rect(0, 0, pad * 2 + key_w + val_w,
                          pad * 2 + line_h * len(rows))
        box.topright = (w - 12, CAP_H + MENU_H + 12)
        shade = pygame.Surface(box.size, pygame.SRCALPHA)
        shade.fill((8, 10, 16, 210))
        self.screen.blit(shade, box.topleft)
        pygame.draw.rect(self.screen, xp.CAP_GLOW, box, 1)
        y = box.y + pad
        for key, value in rows:
            ui.text(self.screen, font, key, (box.x + pad, y),
                    color=xp.TEXT_MUTED)
            ui.text(self.screen, font, value, (box.x + pad + key_w, y),
                    color=xp.TEXT)
            y += line_h

    def run(self, limit=None):
        """Main loop. `limit` stops after that many frames (smoke tests)."""
        frames = 0
        try:
            while self.running:
                raw = self.clock.tick(self.fps_cap) / 1000.0
                times = self._frame_times
                times.append(raw)
                self.frame_ms = sum(times) / len(times) * 1000.0
                self.fps = 1000.0 / max(self.frame_ms, 1e-3)
                # only the simulation step is clamped, never raw time
                dt = min(0.05, raw)
                self.last_dt = dt
                self.input.begin_frame()
                for e in pygame.event.get():
                    self.handle_event(e)
                self.input.poll_keys()
                self._sync_surface()
                if self.chrome.drag and pygame.mouse.get_pressed()[0]:
                    self.chrome.update()
                if not self.paused:
                    self.time += dt
                    # the loop pilots a perspective camera for 3D only
                    three_d = getattr(self.scene, "kind", "3d") == "3d"
                    if three_d:
                        self._mouse_look()
                    try:
                        self.scene.update(dt)
                    except Exception as exc:
                        print(f"scene update failed: {exc!r}")
                    if three_d:
                        self._camera_move(dt)
                        self.sync_camera(self.scene, dt)
                    self._tick_fade(dt)
                    if self.autosave_every > 0.0:
                        self._autosave_in -= dt
                        if self._autosave_in <= 0.0:
                            self._autosave_in = self.autosave_every
                            self.save_game()
                self.draw()
                pygame.display.flip()
                # send a caption only when the scene changed
                title = f"{self.project.title} - " \
                    f"{getattr(self.scene, 'name', '')}"
                if title != self._caption:
                    self._caption = title
                    pygame.display.set_caption(title)
                frames += 1
                if limit is not None and frames >= limit:
                    break
        finally:
            self.audio.stop_all()
            pygame.quit()


def main(project_path=None, frames=None):
    """Convenience entry: run a project folder (or the demo)."""
    if project_path is None:
        project_path = Project.default_path()
    Game(Project(project_path)).run(limit=frames)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
