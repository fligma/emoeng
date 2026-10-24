"""The Preview tab: plays the project's scenes inside the editor window.

The scene code is the same code the real Game runs - the preview just
provides a duck-typed stand-in (`_PreviewGame`) that owns a dedicated
Renderer, exposes project/audio/input/fonts/eye and implements
set_player()/load_scene(). Every scene reload imports the module fresh,
so editing a scene and pressing Reload shows the change without leaving
the editor.

Right-drag looks, WASD moves, R rebuilds the scene. For a true full
window run use Project > Run Game (a separate process).
"""

import math
import traceback

import pygame

from ..engine import fx, ui, xp
from ..engine.camera import wish
from ..engine.input import Input
from ..engine.renderer import Renderer
from ..engine.save import SaveStore
from . import widgets

VIDEO_H = 26


class _PreviewGame:
    """Enough of engine.game.Game for a scene to run unchanged."""

    def __init__(self, preview):
        self.preview = preview
        self.project = None
        self.renderer = None
        self.audio = None
        self.input = preview.input
        self.fonts = preview.app.fonts
        self.save = SaveStore(None, slot="preview")
        self.eye = [0.0, 2.0, 8.0]
        self.yaw = 0.0
        self.pitch = 0.0
        self.time = 0.0
        self.fps = 0.0
        self.state = "play"
        self.paused = False
        self.running = True

    def set_player(self, pos, yaw=None, pitch=None):
        self.eye = [float(pos[0]), float(pos[1]), float(pos[2])]
        if yaw is not None:
            self.yaw = float(yaw)
        if pitch is not None:
            self.pitch = float(pitch)

    def load_scene(self, name=None):
        self.preview.play(name)

    def play_scene(self, name, fade=0.35):
        """No fades in the editor: swap the scene on the next frame."""
        self.preview.play(name)

    def restart_scene(self):
        self.preview.reload()

    def quit(self):
        self.preview.paused = True


class Preview:
    """Live 3D viewport running one scene of the open project."""

    def __init__(self, app):
        self.app = app
        self.fonts = app.fonts
        self.input = Input()
        self.game = _PreviewGame(self)
        self.game.audio = app.audio
        self.renderer = None
        self.render_size = (0, 0)
        self.project = None
        self.scene = None
        self.scene_name = None
        self.pending = None
        self.error = None
        self.time = 0.0
        self.fps = 0.0
        self.paused = False
        self.look = False
        self.mouse_rel = [0, 0]
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.inner = pygame.Rect(0, 0, 0, 0)
        self.buttons = []
        self._error_logged = False

    # ------------------------------------------------------------- project
    def set_project(self, project):
        self.exit_scene()
        self.project = project
        self.game.project = project
        self.game.save = SaveStore(project, slot="preview")
        self.paused = False
        self.error = None
        self._error_logged = False
        names = project.scene_names() if project else []
        if self.renderer is not None and project is not None:
            project.register_textures(self.renderer)
        self.pending = project.start if project else None
        if self.pending is None and names:
            self.pending = names[0]
        if names:
            self.app.log(f"preview scenes: {', '.join(names)}", "muted")

    def scene_names(self):
        return self.project.scene_names() if self.project else []

    def play(self, name=None):
        if self.project is None:
            return
        names = self.scene_names()
        name = name or self.scene_name or self.game.project.start
        if name not in names:
            name = names[0] if names else None
        self.pending = name
        self.paused = False

    def reload(self):
        self.pending = self.scene_name or (
            self.project.start if self.project else None)

    def blur(self):
        """Drop held keys / look drag when another tab takes focus."""
        self.look = False
        self.mouse_rel = [0, 0]
        try:
            self.input.clear()
        except Exception:
            pass

    def exit_scene(self):
        if self.scene is not None:
            try:
                self.scene.on_exit()
            except Exception as exc:
                self.app.log(f"on_exit failed: {exc}", "warn")
        self.scene = None
        self.scene_name = None
        try:
            self.app.audio.stop()
        except Exception:
            pass

    def cycle_scene(self, step):
        names = self.scene_names()
        if not names:
            return
        try:
            i = names.index(self.scene_name)
        except ValueError:
            i = 0
        self.play(names[(i + step) % len(names)])

    # ------------------------------------------------------------ renderer
    def _render_scale(self):
        """Match the project's internal resolution so the PS2 look carries
        over into the editor viewport."""
        if self.project is None:
            return 1.0
        return max(0.25, min(1.0, float(self.project.render_scale)))

    def _ensure_renderer(self, size):
        size = (max(64, int(size[0])), max(64, int(size[1])))
        scale = self._render_scale()
        if self.renderer is None:
            self.renderer = Renderer(*size, render_scale=scale)
            self.game.renderer = self.renderer
            if self.project is not None:
                self.project.register_textures(self.renderer)
            self.render_size = size
            return
        if size != self.render_size:
            self.renderer.resize(*size)
            self.render_size = size
        self.renderer.set_render_scale(scale)

    def _build(self, name):
        self.exit_scene()
        if name is None:
            return
        try:
            self.scene = self.project.scene(name, self.game)
            self.scene.on_enter()
            self.scene_name = name
            self.error = None
            self._error_logged = False
            self.time = 0.0
            self.game.time = 0.0
            self.app.log(f"preview: '{name}' running", "ok")
        except Exception as exc:
            self.scene = None
            self.scene_name = name
            self.error = "".join(traceback.format_exception_only(
                type(exc), exc)) + "\n\n" + traceback.format_exc(limit=4)
            if not self._error_logged:
                self.app.log(f"preview failed: {exc}", "error")
                self._error_logged = True

    # -------------------------------------------------------------- update
    def update(self, dt):
        if self.pending is not None and self.renderer is not None:
            name, self.pending = self.pending, None
            self._build(name)
        if self.scene is None or self.paused:
            return
        self.time += dt
        self.game.time = self.time
        self.game.fps = self.fps
        try:
            self.scene.update(dt)
        except Exception as exc:
            if not self._error_logged:
                self.app.log(f"scene update failed: {exc}", "error")
                self._error_logged = True
        self._mouse_look()
        self._camera_move(dt)

    def _mouse_look(self):
        dx, dy = self.mouse_rel
        self.mouse_rel = [0, 0]
        if not self.look or (dx == 0 and dy == 0):
            return
        self.game.yaw -= dx * 0.0028
        self.game.pitch -= dy * 0.0028
        self.game.pitch = max(-1.45, min(1.45, self.game.pitch))

    def _camera_move(self, dt):
        scene = self.scene
        game = self.game
        rig = getattr(scene, "camera_rig", None)
        right, fwd = self.input.move_axis()
        run = self.input.down("run")
        if rig is not None:
            rig.look(game.yaw, game.pitch)
            if not getattr(scene, "lock_input", False):
                rig.move(wish(game.yaw, right, fwd), run, dt)
            ex, ey, ez = rig.eye()
            game.eye = [ex, ey, ez]
            return
        speed = scene.move_speed[1] if run else scene.move_speed[0]
        vx, vz = wish(game.yaw, right, fwd)
        vx *= speed * dt
        vz *= speed * dt
        vy = (1.0 if self.input.down("up") else 0.0) - \
             (1.0 if self.input.down("down") else 0.0)
        if not getattr(scene, "lock_input", False):
            game.eye[0] += vx
            game.eye[2] += vz
            if scene.camera == "fly":
                game.eye[1] += vy * speed * dt
        ground = scene.ground_height(game.eye[0], game.eye[2])
        if scene.camera == "walk":
            game.eye[1] = ground + scene.eye_height
        else:
            game.eye[1] = max(game.eye[1], ground + 0.6)
        r = math.hypot(game.eye[0], game.eye[2])
        if scene.world_radius and r > scene.world_radius:
            k = scene.world_radius / r
            game.eye[0] *= k
            game.eye[2] *= k

    # -------------------------------------------------------------- events
    def _video_rect(self):
        return pygame.Rect(self.rect.x, self.rect.y, self.rect.width, VIDEO_H)

    def _hover(self):
        return self.inner.collidepoint(pygame.mouse.get_pos())

    def handle_event(self, e):
        pos = getattr(e, "pos", pygame.mouse.get_pos())
        for kind, rect in self.buttons:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and \
                    rect.collidepoint(pos):
                if kind == "prev":
                    self.cycle_scene(-1)
                elif kind == "next":
                    self.cycle_scene(1)
                elif kind == "reload":
                    self.reload()
                elif kind == "pause":
                    self.paused = not self.paused
                return True
        inside = self.inner.collidepoint(pos)
        if inside and e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
            self.look = True
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 3:
            self.look = False
            return True
        if inside and e.type == pygame.MOUSEMOTION and self.look:
            self.mouse_rel[0] += e.rel[0]
            self.mouse_rel[1] += e.rel[1]
            return True
        if e.type in (pygame.KEYDOWN, pygame.KEYUP) and \
                (inside or self._hover()):
            if e.type == pygame.KEYDOWN and e.key == pygame.K_r:
                self.reload()
                return True
            self.input.handle(e)
            return True
        if self.scene is not None and (inside or self._hover()):
            try:
                if self.scene.handle_event(e):
                    return True
            except Exception as exc:
                self.app.log(f"scene event failed: {exc}", "warn")
        return False

    # ---------------------------------------------------------------- draw
    def draw(self, surface, rect, dt=1 / 60.0):
        self.rect = pygame.Rect(rect)
        pygame.draw.rect(surface, xp.FACE, self.rect)
        self._draw_video_bar(surface)
        frames = int(self.fps * 0.9 + (1.0 / max(dt, 1e-4)) * 0.1)
        self.fps = frames
        self.inner = pygame.Rect(self.rect.x + 2,
                                 self.rect.y + VIDEO_H + 2,
                                 self.rect.width - 4,
                                 self.rect.height - VIDEO_H - 4)
        pygame.draw.rect(surface, (16, 18, 22), self.inner)
        xp.sunken(surface, self.inner)
        inner = self.inner.inflate(-2, -2)
        self._ensure_renderer(inner.size)
        self.update(dt)
        if self.error:
            self._draw_error(surface, inner)
            return
        if self.scene is None:
            msg = "No scene selected."
            if self.project is None:
                msg = "Open a project to preview scenes."
            img = widgets.cached_text(self.fonts["normal"], msg,
                                      xp.TEXT_MUTED)
            surface.blit(img, (inner.centerx - img.get_width() // 2,
                               inner.centery - img.get_height() // 2))
            return
        game = self.game
        frame = self.renderer.render(game.eye, game.yaw, game.pitch,
                                     self.scene)
        passes = tuple(getattr(self.scene, "post", ())) or \
            tuple(self.project.post)
        if passes:
            frame = fx.apply(frame, passes)
        if frame.get_size() != inner.size:
            frame = pygame.transform.smoothscale(frame, inner.size)
        try:
            self.scene.overlay(frame)
        except Exception as exc:
            if not self._error_logged:
                self.app.log(f"overlay failed: {exc}", "error")
                self._error_logged = True
        surface.blit(frame, inner.topleft)
        old = surface.get_clip()
        surface.set_clip(inner)
        img = widgets.cached_text(self.fonts["small"],
                                  "RMB look  WASD move  R reload",
                                  (228, 226, 214))
        surface.blit(img, (inner.right - img.get_width() - 8,
                           inner.bottom - img.get_height() - 6))
        if self.paused:
            ui.dim(surface, 0.45)
            img = widgets.cached_text(self.fonts["big"], "Paused",
                                      (245, 242, 232))
            surface.blit(img, (inner.centerx - img.get_width() // 2,
                               inner.centery - img.get_height() // 2))
        surface.set_clip(old)

    def _draw_video_bar(self, surface):
        bar = self._video_rect()
        surface.fill(xp.FACE, bar)
        pygame.draw.line(surface, xp.SHADOW, (bar.x, bar.bottom - 1),
                         (bar.right, bar.bottom - 1))
        mouse = pygame.mouse.get_pos()
        self.buttons = []
        x = bar.x + 4
        for kind, label, tip in (("prev", "<", "previous scene"),
                                 ("next", ">", "next scene"),
                                 ("reload", "Reload", "rebuild the scene"),
                                 ("pause", "Play" if self.paused else "Pause",
                                  "pause the preview")):
            w = max(24, self.fonts["small"].size(label)[0] + 12)
            r = pygame.Rect(x, bar.y + 2, w, bar.height - 4)
            xp.button(surface, r, label, self.fonts["small"],
                      hovered=r.collidepoint(mouse))
            self.buttons.append((kind, r))
            x = r.right + 4
        name = self.scene_name or self.pending or "-"
        img = widgets.cached_text(self.fonts["normal"], f"scene: {name}",
                                  xp.TEXT)
        surface.blit(img, (x + 8, bar.centery - img.get_height() // 2))
        right = f"{self.fps:3.0f} fps"
        img = widgets.cached_text(self.fonts["small"], right, xp.TEXT_MUTED)
        surface.blit(img, (bar.right - img.get_width() - 8,
                           bar.centery - img.get_height() // 2))

    def _draw_error(self, surface, area):
        pygame.draw.rect(surface, (42, 24, 24), area)
        old = surface.get_clip()
        surface.set_clip(area.inflate(-6, -4))
        y = area.y + 8
        img = widgets.cached_text(self.fonts["normal"],
                                  f"scene '{self.scene_name}' failed to load",
                                  (255, 160, 150))
        surface.blit(img, (area.x + 10, y))
        y += img.get_height() + 6
        for line in self.error.splitlines()[-14:]:
            if not line:
                y += self.fonts["small"].get_height() + 1
                continue
            img = widgets.cached_text(self.fonts["small"], line,
                                      (238, 214, 206))
            surface.blit(img, (area.x + 10, y))
            y += img.get_height() + 1
            if y > area.bottom - 10:
                break
        surface.set_clip(old)

    # ---------------------------------------------------------------- info
    def info(self):
        names = self.scene_names()
        out = [
            ("Scene", self.scene_name or "-"),
            ("Scenes", ", ".join(names) if names else "-"),
            ("State", "paused" if self.paused else
             "error" if self.error else "running"),
            ("Draw calls", str(len(self.renderer.groups))
             if self.renderer else "0"),
        ]
        if self.scene is not None:
            out += [
                ("Camera", self.scene.camera),
                ("Entities", str(len(self.scene.entities))),
                ("Lights", str(len(self.scene.lights))),
                ("Eye", "%.1f %.1f %.1f" % tuple(self.game.eye)),
            ]
        return out
