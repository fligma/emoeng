"""The fligengine game runtime: one XP window, one scene loop.

    from fligengine.engine.loader import Project
    from fligengine.engine.game import Game

    Game(Project("fligengine/projects/demo")).run()

The window is borderless with a Luna caption the game paints itself (drag
to move, edges to resize, min/max/close), plus a menubar and status bar, so
every project looks like a Windows XP program. The 3D view renders at
`render_scale` and gets scaled up - set 0.5 in project.flig for chunky
console pixels.
"""

import math
import sys
import time
from pathlib import Path

import pygame

from . import fx, proctex, theme, ui, xp
from .audio import Audio, build_starter_kit
from .camera import wish
from .input import Input
from .loader import Project
from .renderer import Renderer
from .save import SaveStore
from .winchrome import WindowChrome, caption_buttons

CAP_H = 28
MENU_H = 22
STATUS_H = 22
MENU_LABELS = ("Game", "View", "Help")


class Game:
    """Owns the window, the chrome, the renderer, audio and the active
    scene. Subclass to add global state, or just write scenes."""

    def __init__(self, project, title=None, size=None, render_scale=None,
                 master_volume=0.8, seed=None):
        self.project = project if isinstance(project, Project) \
            else Project(project)

        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        theme.apply(theme.load())
        self.project.title = title or self.project.title
        pygame.display.set_caption(self.project.title)

        win_size = tuple(size or self.project.size)
        self.screen = pygame.display.set_mode(win_size, pygame.RESIZABLE)
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
            else self.project.render_scale
        self.renderer = Renderer(*self.screen.get_size(),
                                 render_scale=scale)
        self._register_assets()

        self.audio = build_starter_kit(
            Audio(master=master_volume if master_volume is not None else 0.8))
        self.project.load_audio(self.audio)
        self.input = Input()
        self._bind_defaults()
        self.save = SaveStore(self.project,
                              slot=self.project.meta.get("save_slot",
                                                         "autosave"))

        self.chrome = WindowChrome()
        self.state = "play"
        self.paused = False
        self.show_help = False
        self.running = True
        self.time = 0.0
        self.last_dt = 1 / 60.0
        self.debug = False
        self.fade = 0.0
        self._fade_state = None
        self._fade_time = 0.0
        self._fade_dur = 0.35
        self._pending_scene = None
        self._fade_surface = None
        self.fps = 0.0
        self.eye = [0.0, 2.0, 0.0]
        self.yaw, self.pitch = 0.0, 0.0
        self.look_sensitivity = 0.0022
        self.menu_open = None
        self.menu_rows = []
        self.menu_items = []
        self.close_rect = pygame.Rect(0, 0, 0, 0)
        self.pause_buttons = {}
        self._size_applied = self.screen.get_size()
        self._last_cap_click = -1000
        self._shot_index = 0

        self.scene = None
        self.load_scene(self.project.start)
        self.input.grab_mouse(True)
        self.start_time = time.time()

    # ------------------------------------------------------------- setup
    def _bind_defaults(self):
        self.input.bind("forward", pygame.K_w, pygame.K_UP)
        self.input.bind("back", pygame.K_s, pygame.K_DOWN)
        self.input.bind("left", pygame.K_a, pygame.K_LEFT)
        self.input.bind("right", pygame.K_d, pygame.K_RIGHT)
        self.input.bind("run", pygame.K_LSHIFT, pygame.K_RSHIFT)
        self.input.bind("up", pygame.K_SPACE)
        self.input.bind("down", pygame.K_q, pygame.K_LCTRL)
        self.input.bind("use", pygame.K_e)
        self.input.bind("reload", pygame.K_r)

    def _register_assets(self):
        r = self.renderer
        r.texture("checker", proctex.checker(64, 8))
        r.texture("grid", proctex.grid(128, 8))
        r.texture("ground", proctex.ground(256))
        r.texture("stone", proctex.stone(128))
        r.texture("rust", proctex.rust(128))
        r.texture("bark", proctex.bark(64))
        r.texture("cloth", proctex.cloth(64))
        r.texture("flame", proctex.flame(128), rgba=True, repeat=False)
        r.texture("glow", proctex.glow(128), rgba=True, repeat=False)
        self.project.register_textures(r)

    # -------------------------------------------------------------- scene
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
        self.scene.on_enter()
        self.paused = False
        self.show_help = False
        self.time = 0.0

    def restart_scene(self):
        name = getattr(self.scene, "name", None) or self.project.start
        self.load_scene(name)

    # ------------------------------------------------------------------ flow
    def play_scene(self, name, fade=0.35):
        """Fade to black, load another scene, fade back in.

        fade=0 cuts instantly. Scenes normally call this through
        SceneBase.play_scene() so the current scene stops ticking first.
        """
        if fade is None or float(fade) <= 0.0 or self.scene is None:
            self.load_scene(name)
            return
        self._pending_scene = name
        self._fade_dur = max(0.05, float(fade))
        self._fade_time = 0.0
        self._fade_state = "out"

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
        """Teleport the camera; scenes call this from spawn_point()."""
        self.eye = [float(pos[0]), float(pos[1]), float(pos[2])]
        if yaw is not None:
            self.yaw = float(yaw)
        if pitch is not None:
            self.pitch = float(pitch)

    # ------------------------------------------------------------- camera
    def _camera_move(self, dt):
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
        if not self.input.grabbed:
            return
        dx, dy = self.input.mouse_rel
        if dx == 0 and dy == 0:
            return
        # yaw is a compass angle (forward = sin yaw, cos yaw) and, with the
        # right-handed view matrix, increasing it turns left - so turning
        # right takes the mouse delta out of yaw, not into it
        self.yaw -= dx * self.look_sensitivity
        self.pitch -= dy * self.look_sensitivity
        self.pitch = max(-1.45, min(1.45, self.pitch))

    # -------------------------------------------------------------- pause
    def pause(self):
        if self.paused:
            return
        self.paused = True
        self.state = "pause"
        self.input.grab_mouse(False)
        self.menu_open = None

    def resume(self):
        if not self.paused:
            return
        self.paused = False
        self.state = "play"
        self.input.mouse_rel = (0, 0)
        self.input.grab_mouse(True)

    def quit(self):
        self.running = False

    def screenshot(self):
        folder = Path.cwd()
        while True:
            path = folder / f"fligengine_{self._shot_index:03d}.png"
            if not path.exists():
                break
            self._shot_index += 1
        pygame.image.save(self.screen, str(path))
        print(f"screenshot: {path}")

    # ------------------------------------------------------------- events
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
        w = self.screen.get_width()
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
            return [("Toggle Fullscreen (F11)", "fullscreen"),
                    ("Toggle Help (F1)", "help"),
                    ("Toggle Debug (F3)", "debug"),
                    ("Toggle Theme (Ctrl+T)", "theme"),
                    ("-" , None),
                    ("Renderer scale: %d%%" %
                     round(self.renderer.render_scale * 100), None)]
        return [("Controls", "help"), ("About", "about")]

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
        if e.type == pygame.VIDEORESIZE:
            self._apply_size(e.size)
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_F11:
                self.chrome.toggle_fullscreen()
                return
            if e.key == pygame.K_ESCAPE:
                self.menu_open = None
                self.resume() if self.paused else self.pause()
                return
            if e.key == pygame.K_F1:
                self.show_help = not self.show_help
                return
            if e.key == pygame.K_F3:
                self.debug = not self.debug
                return
            if e.key == pygame.K_t and (e.mod & pygame.KMOD_CTRL):
                theme.toggle()
                return
            if e.key == pygame.K_F2:
                self.screenshot()
                return
            if e.key == pygame.K_F5:
                self.restart_scene()
                return
        self.input.handle(e)

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

    def _apply_size(self, size):
        size = tuple(size)
        if size == self._size_applied:
            return
        self._size_applied = size
        if self.renderer is not None:
            self.renderer.resize(*size)

    def _sync_surface(self):
        if not self.chrome.supported():
            return
        want = tuple(self.chrome.win.size)
        if not want:
            return
        if want != self.screen.get_size():
            self.screen = pygame.display.set_mode(want, pygame.RESIZABLE)
        self._apply_size(want)

    # -------------------------------------------------------------- chrome
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
                  (scene_info + f"  fps {self.fps:3.0f}").strip(),
                  "WASD move / mouse look / ESC pause / F11 fullscreen"]
        xp.statusbar(self.screen, status, panels, self.fonts["small"])
        if self.menu_open:
            pos = self._menu_cells()[self.menu_open].bottomleft
            items = [(lbl, True) for lbl, _act in self.menu_items]
            _panel, self.menu_rows = xp.menu_items(
                self.screen, pos, items, self.fonts["normal"])

    def _draw_pause(self):
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
        w, h = self.screen.get_size()
        frame = pygame.Rect(0, 0, 460, 250)
        frame.center = (w // 2, h // 2)
        body, _close = xp.message_frame(self.screen, frame,
                                        "Controls", self.fonts["normal"])
        lines = [
            "WASD / arrows      move",
            "Mouse              look",
            "Shift              run",
            "Space / Q          fly up / down (camera = fly)",
            "E                  use",
            "R                  reload scene script",
            "ESC                pause / release mouse",
            "F1                 this panel",
            "F2                 screenshot",
            "F3                 debug overlay",
            "F5                 restart scene",
            "Ctrl+T             dark / light theme",
            "F11                fullscreen",
        ]
        y = body.y + 10
        for line in lines:
            key, label = line[:19], line[19:]
            ui.text(self.screen, self.fonts["mono"], key,
                    (body.x + 16, y), color=xp.LINK)
            ui.text(self.screen, self.fonts["mono"], label,
                    (body.x + 196, y), color=xp.TEXT)
            y += self.fonts["mono"].get_height() + 3

    # -------------------------------------------------------------- frame
    def draw(self):
        frame = self.renderer.render(self.eye, self.yaw, self.pitch,
                                     self.scene)
        passes = tuple(getattr(self.scene, "post", ())) or \
            tuple(self.project.post)
        if passes:
            frame = fx.apply(frame, passes)
        if frame.get_size() != self.screen.get_size():
            frame = pygame.transform.scale(frame, self.screen.get_size())
        self.screen.blit(frame, (0, 0))
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
        """F3: live counters for the renderer, the scene and the save."""
        st = self.renderer.stats()
        scene = self.scene
        rows = [
            ("fps", f"{self.fps:5.1f}"),
            ("frame", f"{self.last_dt * 1000:5.1f} ms"),
            ("scene", getattr(scene, "name", "-")),
            ("eye", "%.1f %.1f %.1f" % tuple(self.eye)),
            ("look", f"yaw {self.yaw:.2f}  pitch {self.pitch:.2f}"),
            ("entities", str(len(getattr(scene, "entities", ())))),
            ("timers", str(len(getattr(scene, "timers", ())))),
            ("lights", str(len(getattr(scene, "lights", ())))),
            ("batches", str(st["batches"])),
            ("draws", str(st["draw_calls"])),
            ("tris", f"{st['triangles']} "
                     f"({st['static_tris']}+{st['dynamic_tris']})"),
            ("textures", str(st["textures"])),
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

    # --------------------------------------------------------------- loop
    def run(self, limit=None):
        """Main loop. `limit` stops after that many frames (smoke tests)."""
        frames = 0
        try:
            while self.running:
                dt = min(0.05, self.clock.tick(60) / 1000.0)
                self.last_dt = dt
                self.fps = self.fps * 0.9 + (1.0 / max(dt, 1e-4)) * 0.1
                self.input.begin_frame()
                for e in pygame.event.get():
                    self.handle_event(e)
                self._sync_surface()
                if self.chrome.drag and pygame.mouse.get_pressed()[0]:
                    self.chrome.update()
                if not self.paused:
                    self.time += dt
                    self._mouse_look()
                    try:
                        self.scene.update(dt)
                    except Exception as exc:
                        print(f"scene update failed: {exc!r}")
                    self._camera_move(dt)
                    self._tick_fade(dt)
                self.draw()
                pygame.display.flip()
                pygame.display.set_caption(
                    f"{self.project.title} - "
                    f"{getattr(self.scene, 'name', '')}")
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
