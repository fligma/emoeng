"""The Preview tab: plays project scenes inside the editor."""

import math
import time
import traceback
from pathlib import Path

import pygame

from ..engine import inputmap, mapdoc, scenedoc, shaders, ui, xp
from ..engine.camera import Camera, CameraHost, wish
from ..engine.game import control_hint, register_builtin_textures
from ..engine.input import Input
from ..engine.renderer import Renderer
from ..engine.save import SaveStore
from . import api
from . import widgets

VIDEO_H = 26
SHELF_W = 214              # Edit's shelf: the node list, then properties
NODE_ROW = 18              # one row of the node list
PROP_ROW = 19              # one property line
LABEL_W = 62               # how much of a property row holds its name
SNAP_3D = 0.25             # metres a snapped move lands on
SNAP_2D = 16.0             # world pixels, for the flat scenes
SNAP_ANGLE = math.pi / 12.0    # fifteen degrees, for a snapped turn
HANDLE_PX = 62.0           # how long a gizmo arm is on screen
GRID_3D = 2.0              # metres between grid lines in Edit
GRID_2D = 128.0            # world pixels between them in a flat scene

# each tool's button and key; Q belongs to the camera
TOOLS = (("select", "Select", pygame.K_1),
         ("move", "Move", pygame.K_2),
         ("rotate", "Rotate", pygame.K_3),
         ("scale", "Scale", pygame.K_4))

# a hover hint per button, as an XP bubble
BAR_TIPS = {
    "mode_game": "Run the scene as the game does",
    "mode_edit": "Build the scene still, to place and set it",
    "prev": "Previous scene",
    "next": "Next scene",
    "play": "Start the preview",
    "pause": "Pause while running, start when stopped",
    "stop": "Unload the scene",
    "reload": "Rebuild from the files on disk",
    "focus": "The viewport takes mouse and keys (Esc releases)",
    "hud": "Show or hide the scene's overlay",
    "mute": "Mute or unmute the sound",
}
TOOL_TIPS = {
    "select": "Click picks a node, Shift-click adds to the set",
    "move": "Drag moves across the ground, Shift-drag lifts",
    "rotate": "Drag a ring to turn the picked node",
    "scale": "Drag a grip to size the picked node",
}
SWITCH_TIPS = {
    "space": "Gizmo axes follow the node (Local) or the world (Global)",
    "snap": "Snaps drags to the grid",
    "grid": "Show the ground grid (G)",
    "shapes": "Draw collision shapes over the view (H)",
    "lighting": "The scene's own lights, instead of flat and readable",
    "frame": "Frame the picked node (F)",
    "revert": "Hand the placement back to the document",
}

AXES = {"x": (204, 84, 74), "y": (98, 176, 96), "z": (88, 132, 214)}
AXIS_VECTORS = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0),
                "z": (0.0, 0.0, 1.0)}

# click-to-pick range in 3D, and the 2D drag threshold
PICK_PX = 26.0
GRAB_PX = 7.0             # how close a click must land to grab a handle
TRI_W = 13                # the room a fold triangle takes in a tree row

# node art comes from `widgets.class_icon`, reading the registry

# a box's corners in wireframe order: bottom ring, top, uprights
BOX_SIGNS = ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1),
             (-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1))
BOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7),
             (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
RING_SEG = 20               # samples around a round shape's circle
TRIGGER_RGB = (240, 158, 62)    # a see-through shape, warm on purpose
SPAWN_RGB = (112, 214, 158)     # the player-start marker, green for "go"


class SpawnMarker:
    """The map's player start as a draggable pseudo-node.

    It rides the pick, drag and gizmo rails like any placed node, but
    owns only a position and a yaw. It is not in the scene's objects:
    its home is the map document's `spawn` fields, which the editor
    writes back through `mapdoc.set_spawn`.
    """

    is_spawn = True
    alive = True
    placed_id = None
    doc_key = None

    def __init__(self, pos, yaw=0.0):
        self.pos = [float(c) for c in pos]
        self.yaw = float(yaw)
        self.objects = ()
        self.lights = ()
        self.children = ()

    def set(self, pos=None, yaw=None):
        if pos is not None:
            self.pos = [float(c) for c in pos][:3]
            while len(self.pos) < 3:
                self.pos.append(0.0)
        if yaw is not None:
            self.yaw = float(yaw)
        return self


def _seg_distance(px, py, a, b):
    """Pixel distance to a segment, for grabbing it."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    denom = dx * dx + dy * dy
    t = 0.0 if denom <= 0.0 else \
        ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def _colour_text(value):
    """A look colour as `#rrggbb`, or the written name."""
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return "#%02x%02x%02x" % tuple(
            max(0, min(255, int(round(float(c) * 255.0)))) for c in value[:3])
    return str(value)


class _FakeSurface(pygame.Surface):
    """The preview's window: a real Surface a scene can paint its HUD on.

    `Hud` reads `game.screen` and hands it to `pygame.draw.*`, which rejects
    anything that is not a Surface. A stand-in object made every overlay
    helper raise, so this is an actual surface: the scene paints its overlay
    here, and the preview blits the result over the rendered frame.
    """

    def __init__(self, size=(640, 360)):
        super().__init__(size, pygame.SRCALPHA)
        self.fill((0, 0, 0, 0))

    def fit(self, size):
        """Match the frame, and clear what the last frame painted."""
        size = (max(1, int(size[0])), max(1, int(size[1])))
        if size != self.get_size():
            pygame.Surface.__init__(self, size, pygame.SRCALPHA)
        self.fill((0, 0, 0, 0))
        return self

    def set_target(self, surface):
        """An overlay asked to aim at a frame: match its size, then clear."""
        return self.fit(surface.get_size())


class _PreviewGame(CameraHost):
    """Enough of engine.game.Game for a scene to run unchanged."""

    def __init__(self, preview):
        self.preview = preview
        self.project = None
        self.renderer = None
        self.audio = None
        self.input = preview.input
        self.fonts = preview.app.fonts
        self.save = SaveStore(None, slot="preview")
        self.screen = _FakeSurface()
        self.init_camera(eye=(0.0, 2.0, 8.0))
        self.time = 0.0
        self.last_dt = 1 / 60.0
        self.fps = 0.0
        self.state = "play"
        self.paused = False
        self.running = True

    def set_player(self, pos, yaw=None, pitch=None):
        if self.preview.mode == "edit" and \
                self.camera is self.preview.edit_cam:
            # Edit keeps its own view; the player already stands placed
            return
        player = getattr(self.preview.scene, "player", None) \
            if self.preview.scene else None
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

    def play_area(self):
        """The whole preview rect; nothing paints over the scene."""
        w, h = self.screen.get_size()
        return pygame.Rect(0, 0, w, h)

    def control_hint(self):
        """The game's own status line, from the preview's keymap."""
        return control_hint(self.input, self.preview.scene)

    @property
    def scene(self):
        """`game.scene`: the one scene the preview runs."""
        return self.preview.scene

    def load_scene(self, name=None):
        self.preview.play(name)

    def play_scene(self, name, fade=0.35):
        """No fades in the editor; swap next frame."""
        self.preview.play(name)

    def push_scene(self, name, fade=0.35):
        """Stacked like the runtime, with its own record."""
        cur = getattr(self.preview.scene, "name", None)
        if cur is not None:
            self.preview.push_stack.append(cur)
        self.preview.play(name)

    def pop_scene(self, fade=0.35):
        name = self.preview.push_stack.pop() \
            if self.preview.push_stack else None
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
        self.map_name = None      # a map played on its own, no scene of it
        self.pending = None
        self.selected = None
        self.started = False
        self.error = None
        self.time = 0.0
        self.fps = 0.0
        self._last_draw = None
        self.paused = False
        self.look = False
        self.hud = True
        self.muted = False
        self._vol_before = 0.7
        self.vol_drag = False
        self.vol_rect = pygame.Rect(0, 0, 0, 0)
        self.mouse_rel = [0, 0]
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.inner = pygame.Rect(0, 0, 0, 0)
        self.push_stack = []
        self.buttons = []
        self.tips = []          # (rect, words) drawn on hover, per frame
        self._error_logged = False
        # the viewport's mode, free camera and dragged object
        self.mode = "game"
        self.edit_cam = Camera(eye=(0.0, 3.5, 12.0), yaw=math.pi,
                               pitch=-0.26)
        self.edit_seated = False  # has Edit framed a live scene yet?
        self._play_cam = None
        self.sel = None
        self.sel_key = None
        self.sels = []          # Shift-picked set; primary is self.sel
        self.drag = None
        self.edit_moved = False
        # the tools strip and shelf: armed transform, snapping, last panels
        self.tool = "move"
        self.space = "global"
        self.snap = False
        self.grid = True
        self.tools_rect = pygame.Rect(0, 0, 0, 0)
        self.shelf_rect = pygame.Rect(0, 0, 0, 0)
        self.nodes_body = pygame.Rect(0, 0, 0, 0)
        self.node_rows = []
        self.nodes_scroll = 0
        self.nodes_max = 0
        # the tree's state: folded branches, last triangles, open menu
        self.collapsed = set()
        self.node_toggles = []
        self.node_ctx = None        # (action, rect) rows, filled as drawn
        self.node_ctx_at = (0, 0)   # where the right click opened it
        self.show_shapes = True    # Edit draws collision shapes
        self.props = []
        self.prop_fields = {}
        self.grip = None          # (property key, TextField) while typing
        self.picks = None         # the asset list under the row being typed
        self.gizmo = None         # the handle a drag is holding
        self.spawn = None         # the player-start marker, in Edit
        self._click = None        # (when, node) for a double click
        self.light_view = False   # Edit draws flat until this is switched
        self.focus_mode = False   # the viewport has the pointer and keys

    def set_project(self, project):
        self.exit_scene()
        # a project always opens in Game mode
        self.mode = "game"
        self.edit_seated = False
        self._play_cam = None
        self.sel_key = None
        self.project = project
        self.game.project = project
        self.game.save = SaveStore(project, slot="preview")
        self.paused = False
        self.started = False
        self.map_name = None
        self.error = None
        self._error_logged = False
        self.pending = None
        names = project.scene_names() if project else []
        self._load_textures()
        # choosing a scene does not run it; Play builds
        self.selected = (project.start if project and project.start in names
                         else names[0] if names else None)
        if names:
            self.app.log(f"preview scenes: {', '.join(names)}", "muted")

    def scene_names(self):
        return self.project.scene_names() if self.project else []

    def arm(self, name=None):
        """Pick the scene Play will run; starts nothing."""
        names = self.scene_names()
        if name is not None and name in names:
            self.selected = name

    def play(self, name=None):
        if self.project is None:
            return
        names = self.scene_names()
        name = name or self.scene_name or self.selected or self.project.start
        if name not in names:
            name = names[0] if names else None
        self.selected = name
        self.map_name = None
        self.started = True
        self.pending = name
        self.paused = False
        self.error = None
        self._error_logged = False

    def play_map(self, name):
        """Run one map on its own, in a bare scene built around it."""
        if self.project is None:
            return False
        stem = Path(str(name)).stem
        if self.project.map_doc(stem) is None:
            self.app.log(f"no map called {stem}", "warn")
            return False
        self.map_name = stem
        self.selected = None
        self.started = True
        self.pending = stem
        self.paused = False
        self.error = None
        self._error_logged = False
        return True

    def select_node(self, name, key):
        """Select one placed node, building its scene first."""
        self.sel_key = str(key)
        self.selected = name
        self.map_name = None
        self.started = True
        self.pending = name

    def stop(self):
        """Back to the stopped state: no scene, nothing scheduled."""
        self.started = False
        self.pending = None
        self.paused = False
        self.map_name = None
        self.error = None
        self.exit_scene()

    def reload(self):
        """Re-run the current scene, with the project's code re-imported."""
        if self.project is not None:
            self.project.reload_scripts()
        self._load_textures()
        self.pending = self.scene_name or (
            self.project.start if self.project else None)

    def _let_go(self):
        """Release held keys as releases, never as a silent drop."""
        let_go = getattr(self.input, "release_all", None) or self.input.clear
        try:
            let_go()
        except Exception:
            pass

    def begin_frame(self):
        """Open a fresh input frame; a press must not live past one."""
        try:
            self.input.begin_frame()
        except Exception:
            pass

    def blur(self):
        """Drop held keys and drags when focus leaves."""
        self.release()
        self.look = False
        self.mouse_rel = [0, 0]
        # a half-finished drag must not outlive its tab
        self.drag = None
        self.gizmo = None
        self.grip = None
        self.picks = None
        self._let_go()

    def exit_scene(self):
        if self.scene is not None:
            try:
                self.scene.on_exit()
            except Exception as exc:
                self.app.log(f"on_exit failed: {exc}", "warn")
        self.scene = None
        self.scene_name = None
        self.sel = None
        self.spawn = None
        self.drag = None
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

    def _render_scale(self):
        """Match the project's internal resolution so the scaled-pixel"""
        if self.project is None:
            return 1.0
        return max(0.25, min(1.0, float(self.project.render_scale)))

    def _ensure_renderer(self, size):
        size = (max(64, int(size[0])), max(64, int(size[1])))
        scale = self._render_scale()
        if self.renderer is None:
            self.renderer = Renderer(*size, render_scale=scale)
            self.game.renderer = self.renderer
            self._load_textures()
            self.render_size = size
            return
        if size != self.render_size:
            self.renderer.resize(*size)
            self.render_size = size
        self.renderer.set_render_scale(scale)

    def _load_textures(self):
        """Upload the built-in sheets, then this project's files."""
        if self.renderer is None:
            return
        self.renderer.project = self.project
        register_builtin_textures(self.renderer, self.project)
        if self.project is not None:
            self.project.register_textures(self.renderer)

    def _build(self, name):
        keep = self.sel_key
        # the edit view is the editor's; remember its camera
        was_active = self.scene.active if (self.scene is not None
                                           and self.mode == "edit") \
            else ...
        # a map played alone outweighs the scene of the same name
        map_name = self.map_name
        self.exit_scene()
        if name is None:
            return
        try:
            if self.mode == "edit":
                # cached edit flags on an instanced class must be cleared
                self.project.reload_objects()
            # the project's own keys and triggers, so Play hears them
            inputmap.load(self.project).apply(self.input)
            if map_name is not None and name == map_name:
                # no scene document, no script: the map alone, placed
                self.scene = self.project.map_scene(name, self.game)
            else:
                self.scene = self.project.scene(name, self.game)
            if self.mode == "edit":
                self.scene.live = True
                self.scene.editor_build = True
            # on_enter seats player and camera; Edit skips it
            if self.mode != "edit":
                self.scene.on_enter()
            self.scene_name = name
            self.error = None
            self._error_logged = False
            self.time = 0.0
            self.game.time = 0.0
            self.sel = self._find(keep)
            self.sel_key = keep if self.sel is not None else None
            self.sels = [self.sel] if self.sel is not None else []
            if self.mode == "edit":
                self._seat_edit_view(was_active)
                self._apply_view()
                self._warm_screens()
            self.app.log(f"preview: '{name}' running "
                         f"({len(self.scene.objects)} object(s), "
                         f"{len(self.scene.post or ())} post pass(es))",
                         "ok")
        except Exception as exc:
            self.scene = None
            self.scene_name = name
            self.error = "".join(traceback.format_exception_only(
                type(exc), exc)) + "\n\n" + traceback.format_exc(limit=4)
            if not self._error_logged:
                self.app.log(f"preview failed: {exc}", "error")
                self._error_logged = True

    def _find(self, key):
        """The live object a name refers to, after a rebuild."""
        if key is None or self.scene is None:
            return None
        for obj in self.scene.objects:
            if getattr(obj, "placed_id", None) == key or \
                    getattr(obj, "doc_key", None) == key:
                return obj
        return None

    def update(self, dt):
        if self.started and self.pending is not None \
                and self.renderer is not None:
            name, self.pending = self.pending, None
            self._build(name)
        if not self.started or self.scene is None:
            return
        if self.mode == "edit":
            self._edit_update(dt)
            return
        if self.paused:
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
        self.game.last_dt = dt
        # only 3D scenes are piloted by the game camera
        if getattr(self.scene, "kind", "3d") == "3d":
            self._mouse_look()
            self._camera_move(dt)
            # the game owns the camera, so it syncs shake
            self.game.sync_camera(self.scene, dt)

    def _mouse_look(self):
        dx, dy = self.mouse_rel
        self.mouse_rel = [0, 0]
        if not self.look or (dx == 0 and dy == 0):
            return
        player = None if self.mode == "edit" \
            else getattr(self.scene, "player", None)
        if player is not None and hasattr(player, "nudge"):
            # the Player owns look; the preview feeds it right-drag
            player.nudge(dx, dy)
            player.publish_camera()
            return
        cam = self.game.camera
        base = cam.wanted if cam.wanted is not None else (cam.yaw, cam.pitch)
        cam.aim(base[0] - dx * 0.0028, base[1] - dy * 0.0028,
                self.game.last_dt)

    def _camera_move(self, dt):
        scene = self.scene
        game = self.game
        if getattr(scene, "player", None) is not None:
            # the Player already integrated pos, yaw and pitch during update
            return
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

    def toggle_mode(self, mode=None):
        """Swap Game and Edit; returns the new mode."""
        want = mode or ("game" if self.mode == "edit" else "edit")
        if want == self.mode:
            return self.mode
        self.drag = None
        if want == "edit":
            self.mode = "edit"
            if not self.started:
                self.play()
            self._enter_edit()
        else:
            self._leave_edit()
            self.mode = "game"
        return self.mode

    def _keep_view(self, was_active):
        """Hold the edit camera's view across a build."""
        scene = self.scene
        if scene is None or getattr(scene, "kind", "3d") != "3d":
            return
        if was_active is not ...:
            scene.active = was_active
        cam = self.edit_cam
        if scene.active:
            self._reseat_rig(scene.cameras.get(scene.active), cam)
        else:
            self.game.camera = cam

    def _seat_edit_view(self, was_active):
        """Frame the fresh scene, then keep the camera where it was."""
        scene = self.scene
        if scene is None or getattr(scene, "kind", "3d") != "3d":
            self._keep_view(was_active)
            return False
        if not self.edit_seated:
            # Edit opened before anything was framed: take a home view
            cam = self.edit_cam
            cam.eye, cam.yaw, cam.pitch = self._home_view(scene)
            cam.stop_shake()
            self.edit_seated = True
        if self._play_cam is None and self.game.camera is not self.edit_cam:
            # remember what Play draws through, so leaving Edit restores it
            self._play_cam = self.game.camera
        self._keep_view(was_active)
        return True

    @staticmethod
    def _home_view(scene):
        """A default Edit view: back from the spawn, looking at it."""
        spot, yaw = (0.0, 0.0, 0.0), 0.0
        try:
            spot, yaw = scene.spawn_point()
        except Exception:
            pass
        eye_y = float(getattr(scene, "eye_height", 2.0) or 2.0)
        seat = max(eye_y * 2.0, 3.5)
        eye = [float(spot[0]) - math.sin(yaw) * 6.0,
               float(spot[1]) + seat,
               float(spot[2]) - math.cos(yaw) * 6.0]
        return eye, float(yaw), -0.26

    def _reseat_rig(self, rig, cam):
        """Put a scene rig where the edit camera is looking."""
        if rig is None:
            return
        rig.eye = list(cam.eye)
        rig.yaw = cam.yaw
        rig.pitch = cam.pitch
        rig.wanted = None
        rig.stop_shake()

    def _enter_edit(self):
        self.paused = False
        self.look = False
        self.mouse_rel = [0, 0]
        self._let_go()
        scene = self.scene
        if scene is not None and getattr(scene, "kind", "3d") == "3d":
            # start from the angle the game was looking through
            cam = self.edit_cam
            cam.eye = list(self.game.eye)
            cam.yaw = self.game.yaw
            cam.pitch = self.game.pitch
            cam.stop_shake()
            # an unseated eye looks from inside the floor
            seat = max(float(getattr(scene, "eye_height", 0.0) or 0.0),
                       float(getattr(getattr(scene, "player", None),
                                     "eye_height", 0.0) or 0.0), 1.5)
            ground = scene.ground_height(cam.eye[0], cam.eye[2])
            cam.eye[1] = max(float(cam.eye[1]), ground + seat)
            self._play_cam = self.game.camera
            self.game.camera = cam
            # a Camera3D scene keeps drawing through it in Edit
            if scene.active:
                self._reseat_rig(scene.cameras.get(scene.active), cam)
            self.edit_seated = True
        self.spawn = None         # the marker re-reads the map document
        self._apply_view()
        self.app.log("edit mode - drag objects or the player start", "muted")

    def _leave_edit(self):
        self.drag = None
        self.gizmo = None
        self.grip = None
        self.picks = None
        self.node_ctx = None
        self.spawn = None
        self.release()
        if self._play_cam is not None:
            self.game.camera = self._play_cam
            self._play_cam = None
        # a fresh build keeps Edit's data, drops the rest
        if self.scene_name is not None:
            self.pending = self.scene_name
        self.sel = None
        self.sel_key = None
        self.sels = []

    def _edit_update(self, dt):
        """Fly the edit camera; flat scenes pan instead."""
        scene = self.scene
        if scene is None:
            return
        if self.light_view:
            self._edit_lights(dt)
        if getattr(scene, "kind", "3d") != "3d":
            return
        self._mouse_look()
        right, fwd = self.input.move_axis()
        up = (1.0 if self.input.down("up") else 0.0) - \
             (1.0 if self.input.down("down") else 0.0)
        speed = 24.0 if self._shift() else 8.0
        self.game.camera.fly(fwd, right, up, speed, dt)

    def _edit_lights(self, dt):
        """Place and tick lights, running none of the objects."""
        scene = self.scene
        if scene is None:
            return
        for light in list(getattr(scene, "lights", ())):
            try:
                light.update(dt)
            except Exception:
                pass
        sun = getattr(scene, "sun", None)
        if sun is not None:
            try:
                sun.update(dt)
            except Exception:
                pass
            sync = getattr(scene, "sync_sun", None)
            if callable(sync):
                try:
                    sync()
                except Exception:
                    pass

    def toggle_lighting(self):
        """Edit's Lighting switch: off (the default) is flat full light."""
        self.light_view = not self.light_view
        self._apply_view()
        self.app.status = ("edit lighting: the scene's own" if self.light_view
                           else "edit lighting: full bright")
        return self.light_view

    def _apply_view(self):
        """Apply the requested look once per build."""
        scene = self.scene
        if scene is None or self.mode != "edit":
            return False
        if getattr(scene, "_edit_saved", None) is not None:
            if not self.light_view:
                return False
            return self._restore_view()
        if self.light_view:
            return False
        # everything the renderer reads about lighting, kept for the switch
        scene._edit_saved = {
            "lights": scene.lights, "sun": getattr(scene, "sun", None),
            "ambient": scene.ambient, "ambient2d": scene.ambient2d,
            "sun_col": getattr(scene, "sun_col", (0.0, 0.0, 0.0)),
            "sun_dir": getattr(scene, "sun_dir", (0.0, 1.0, 0.0)),
            "fog_near": getattr(scene, "fog_near", 1.0e6),
            "fog_far": getattr(scene, "fog_far", 1.0e6)}
        scene.lights = []
        if hasattr(scene, "sun"):
            scene.sun = None
        scene.ambient = (1.0, 1.0, 1.0)
        scene.ambient2d = (1.0, 1.0, 1.0)
        if hasattr(scene, "sun_col"):
            scene.sun_col = (0.0, 0.0, 0.0)
        if hasattr(scene, "fog_near"):
            scene.fog_near = 1.0e6
        if hasattr(scene, "fog_far"):
            scene.fog_far = 1.0e6 + 1.0
        return True

    def _restore_view(self):
        """Hand the scene back the lighting its script gave it."""
        scene = self.scene
        saved = getattr(scene, "_edit_saved", None) if scene else None
        if saved is None:
            return False
        for key, value in saved.items():
            setattr(scene, key, value)
        scene._edit_saved = None
        return True

    def _warm_screens(self):
        """Draw every screen's first frame, so Edit shows a picture."""
        scene = self.scene
        if scene is None:
            return 0
        warmed = 0
        for obj in getattr(scene, "objects", ()):
            warm = getattr(obj, "warm", None)
            if not callable(warm):
                continue
            try:
                warm()
                warmed += 1
            except Exception as exc:
                self.app.log(f"screen '{obj.tag}' failed: {exc}", "error")
        return warmed

    def _shift(self, e=None):
        """Shift for a click; events carry no `mod`."""
        return widgets.shift_held(e)

    def _local(self, pos=None):
        """A window pixel as a viewport pixel."""
        pos = pygame.mouse.get_pos() if pos is None else pos
        return (pos[0] - self.inner.x, pos[1] - self.inner.y)

    def pick(self, pos=None):
        """The object under a viewport pixel, or None."""
        scene = self.scene
        if scene is None:
            return None
        local = self._local(pos)
        if getattr(scene, "kind", "3d") == "3d":
            best, depth = None, None
            for obj in scene.objects:
                if not getattr(obj, "alive", False):
                    continue
                got = self.game.camera.project(obj.pos, self.inner.size)
                if got is None:
                    continue
                if math.hypot(got[0] - local[0], got[1] - local[1]) > PICK_PX:
                    continue
                if best is None or got[2] < depth:
                    best, depth = obj, got[2]
            if best is None:
                best = self._pick_spawn(local)
            return best
        world = scene.to_world(local)
        for obj in reversed(scene.objects):
            if not getattr(obj, "alive", False):
                continue
            rect = self._world_rect(obj)
            if rect is not None and not rect.collidepoint(world):
                continue
            if rect is None and getattr(obj, "rect", None) is not None:
                continue          # a box we cannot read is not a hit
            return obj
        return self._pick_spawn(local)

    def _pick_spawn(self, local):
        """The player-start marker, when a click lands on it."""
        mark = self.spawn
        if mark is None or self.mode != "edit":
            return None
        if self._flat():
            px, py = self._to_pixels(mark.pos)
        else:
            got = self.game.camera.project(mark.pos, self.inner.size)
            if got is None:
                return None
            px, py = got[0], got[1]
        if math.hypot(px - local[0], py - local[1]) <= PICK_PX * 0.7:
            return mark
        return None

    def _world_rect(self, obj):
        """An object's world box as a Rect, or None."""
        rect = getattr(obj, "rect", None)
        if callable(rect):
            try:
                rect = rect()
            except Exception:
                return None
        if rect is None:
            return None
        try:
            return pygame.Rect(rect)
        except (TypeError, ValueError):
            return None

    def select(self, obj):
        """Select one object whole, by its document name."""
        self.sel = obj
        self.sel_key = self._node_key(obj) if obj is not None else None
        self.sels = [obj] if obj is not None else []
        return obj

    def toggle_select(self, obj):
        """Shift-pick toggles; the last pick is primary."""
        if obj is None:
            return self.sels
        if obj in self.sels:
            self.sels.remove(obj)
        else:
            self.sels.append(obj)
        self.sel = self.sels[-1] if self.sels else None
        self.sel_key = self._node_key(self.sel) if self.sel else None
        return self.sels

    def begin_drag(self, pos=None, add=False):
        """Pick what is under the pointer and start moving it."""
        obj = self.pick(pos)
        if obj is None and not add:
            self.select(None)
            return None
        if obj is None:
            return None
        if add:
            self.toggle_select(obj)
        elif obj not in self.sels:
            self.select(obj)
        pack = [o for o in self.sels if getattr(o, "alive", False)]
        if obj not in pack:
            pack.append(obj)
        local = self._local(pos)
        self.drag = {"obj": obj, "objs": pack, "from": local,
                     "start": list(obj.pos), "world": None,
                     "was": {id(o): list(o.pos) for o in pack}}
        self.edit_moved = False
        return obj

    def drag_to(self, pos=None):
        """Move the dragged objects so the pivot follows the pointer."""
        if self.drag is None:
            return None
        obj = self.drag["obj"]
        local = self._local(pos)
        scene = self.scene
        delta = None
        if getattr(scene, "kind", "3d") == "3d":
            cam = self.game.camera
            if self._shift():
                # a plane holding Y, facing the way the camera looks
                normal = (math.sin(cam.yaw), 0.0, math.cos(cam.yaw))
                hit = cam.plane_hit(self.inner.size, local, obj.pos, normal)
                if hit is None:
                    return None
                delta = [0.0, float(hit[1]) - obj.pos[1], 0.0]
            else:
                hit = cam.plane_hit(self.inner.size, local, obj.pos,
                                    (0.0, 1.0, 0.0))
                if hit is None:
                    return None
                delta = [float(hit[0]) - obj.pos[0], 0.0,
                         float(hit[2]) - obj.pos[2]]
        else:
            world = scene.to_world(local)
            if self.drag["world"] is None:
                self.drag["world"] = scene.to_world(self.drag["from"])
            delta = [world[0] - self.drag["world"][0],
                     world[1] - self.drag["world"][1]]
        moved = self.move_object(obj, [c + d for c, d in zip(obj.pos,
                                                             delta)])
        for other in self.drag["objs"]:
            if other is not obj:
                self.move_object(other, [c + d for c, d in zip(other.pos,
                                                               delta)])
        return moved

    def move_object(self, obj, pos):
        """Put an object at `pos`, with all it built."""
        old = list(getattr(obj, "pos", pos))
        delta = [pos[i] - (old[i] if i < len(old) else 0.0)
                 for i in range(len(pos))]
        setter = getattr(obj, "set", None)
        try:
            setter(pos=pos)
        except TypeError:
            obj.pos = [float(c) for c in pos]
        if max(abs(d) for d in delta) > 1e-5:
            self.edit_moved = True
        for held in getattr(obj, "objects", ()):     # ModelObject instances
            try:
                held.set(pos=[c + d for c, d in zip(held.pos, delta)])
                held.update()
            except Exception:
                pass
        for light in getattr(obj, "lights", ()):
            if getattr(light, "follow", None) is not None:
                continue          # a follower lands where its owner does
            try:
                light.move(*delta)
            except Exception:
                pass
        self._refresh(obj)
        return obj

    def _refresh(self, obj):
        """Redraw what an object owns after a move."""
        if getattr(obj, "is_spawn", False):
            return                    # the marker owns nothing in the scene
        scene = self.scene
        if scene is not None and getattr(scene, "live", False):
            try:
                scene.relive(obj)
            except Exception:
                pass
        sync = getattr(obj, "_sync", None)
        if callable(sync):
            try:
                sync()
            except Exception:
                pass

    def end_drag(self):
        """Finish a drag: write every moved object into the document."""
        drag, self.drag = self.drag, None
        if drag is None:
            return None
        moved = []
        for obj in drag["objs"]:
            was = drag["was"].get(id(obj)) or []
            gap = max((abs(c - s) for c, s in zip(obj.pos, was)),
                      default=0.0)
            if gap >= 1e-4:
                moved.append(obj)
        if not moved or not self.edit_moved:
            return None
        for obj in moved:
            if getattr(obj, "is_spawn", False):
                self.write_spawn()
            else:
                self.write_placement(obj)
        self.pending = self.scene_name      # rebuild where they now sit
        return moved[0]

    def _sync_spawn(self):
        """Keep the Edit marker reading the live map document."""
        level = getattr(self.scene, "map", None) if self.scene else None
        if self.mode != "edit" or level is None:
            self.spawn = None
            return None
        spot, yaw = mapdoc.spawn_of(level.doc)
        if spot is None:
            # unset means the scene's own fallback: show where Play lands
            try:
                spot, yaw = self.scene.spawn_point()
            except Exception:
                spot, yaw = (0.0, 0.0, 0.0), 0.0
        pos = [float(c) for c in spot]
        while len(pos) < 3:
            pos.append(0.0)
        if self.spawn is None:
            self.spawn = SpawnMarker(pos, yaw)
        elif self.drag is None and self.gizmo is None:
            # a rebuild may land the level on a spawn someone saved
            if [round(c, 3) for c in self.spawn.pos] != \
                    [round(c, 3) for c in pos] or \
                    round(self.spawn.yaw, 3) != round(float(yaw), 3):
                self.spawn.pos, self.spawn.yaw = pos, float(yaw)
                if self.sel_key == "player start":
                    self.sel = self.spawn
        return self.spawn

    def write_spawn(self):
        """Record the player start in the map document that owns it."""
        level = getattr(self.scene, "map", None) if self.scene else None
        if level is None or self.project is None or self.spawn is None:
            return None
        mapdoc.set_spawn(level.doc, list(self.spawn.pos), self.spawn.yaw)
        path = self.project.save_map_doc(level.name, level.doc)
        if path is not None:
            self.app.log(f"player start moved in "
                         f"{self.project.relative(path)}", "ok")
            self.app.refresh_tree()
        return path

    def _doc_kind(self):
        """The document's word for the open scene."""
        kind = getattr(self.scene, "kind", "3d") if self.scene else "3d"
        return "sceneui" if kind == "ui" else f"scene{kind}"

    def _script_of(self, obj):
        """The script an object came from, if any."""
        module = type(obj).__module__
        if module.startswith(("scripts.objects.", "objects.")):
            return f"scripts/objects/{module.rsplit('.', 1)[-1]}.py"
        return None

    def _map_doc_open(self):
        """The map document a played-alone map edits, or None.

        `Play in Scene tab` on a map builds a bare scene with no `.scene`
        behind it, so every node the tab moves belongs to the `.map`
        file. A normal scene answers None: it keeps its own document and
        only the level's own nodes route away (see `_home_of`).
        """
        name = self.scene_name
        if self.project is None or name is None:
            return None
        if self.map_name is not None and name == self.map_name:
            return self.project.map_doc(name)
        return None

    def _home_of(self, placed):
        """(is_map, doc, name): the file that placed this node.

        A scene that loads a map keeps two documents' worth of nodes in
        one tree, so a node's id decides which file a drag writes back
        to - the level's `.map` or the scene's `.scene`. `name` is the
        stem that file is saved under, which a map's level knows.
        """
        level = getattr(self.scene, "map", None) if self.scene else None
        if placed is not None and level is not None and \
                mapdoc.placed(level.doc, placed) is not None:
            return True, level.doc, level.name
        open_map = self._map_doc_open()
        if open_map is not None:
            return True, open_map, self.scene_name
        return False, self.project.scene_doc(self.scene_name), \
            self.scene_name

    def _save_home(self, is_map, name, doc):
        """Write a placed node back to the folder its kind means."""
        if is_map:
            return self.project.save_map_doc(name, doc)
        return self.project.save_scene_doc(name, doc)

    def write_placement(self, obj):
        """Record one object's placement in whichever file placed it."""
        project, name = self.project, self.scene_name
        if project is None or name is None:
            return None
        placed = getattr(obj, "placed_id", None)
        is_map, doc, home = self._home_of(placed)
        if doc is None:
            doc = scenedoc.blank_scene(name, self._doc_kind())
        api = mapdoc if is_map else scenedoc
        if not is_map and not doc.get("script"):
            script = project.scene_script(name)
            if script is not None:
                doc["script"] = scenedoc.script_field("scripts/scenes",
                                                      script.name)
        fields = scenedoc.look_of(obj)
        if placed:
            entry = dict(api.placed(doc, placed) or {"id": placed})
            entry.update(fields)
            entry.setdefault("script", self._script_of(obj))
            # file a node under its holder, avoiding a root copy
            api.add_placed(doc, entry, api.parent_of(doc, placed))
            what = placed
        elif getattr(obj, "doc_key", None):
            key = obj.doc_key
            entry = dict((doc.get("overrides") or {}).get(key) or {})
            entry.update(fields)
            scenedoc.set_override(doc, key, entry)
            what = key
        else:
            return None
        path = self._save_home(is_map, home, doc)
        self.app.log(f"placed {what} in {project.relative(path)}", "ok")
        self.app.refresh_tree()
        return path

    def revert(self):
        """Hand the selection back to the document that placed it."""
        obj = self.sel
        project, name = self.project, self.scene_name
        if obj is None or project is None or name is None:
            return False
        placed = getattr(obj, "placed_id", None)
        key = getattr(obj, "doc_key", None)
        is_map, doc, home = self._home_of(placed)
        if doc is None:
            return False
        api = mapdoc if is_map else scenedoc
        if placed and api.placed(doc, placed) is not None:
            entry = api.placed(doc, placed)
            for field in scenedoc.LOOK_KEYS:
                entry.pop(field, None)
        elif key and (doc.get("overrides") or {}).get(key) is not None:
            (doc.get("overrides") or {}).pop(key, None)
        else:
            return False
        self._save_home(is_map, home, doc)
        self.app.log(f"reverted {placed or key}", "ok")
        self.app.refresh_tree()
        self.pending = name
        return True

    def _node_key(self, obj):
        """What the tree and the document both call this node."""
        if getattr(obj, "is_spawn", False):
            return "player start"
        return str(getattr(obj, "placed_id", None)
                   or getattr(obj, "doc_key", None)
                   or type(obj).__name__)

    def _nodes_of_scene(self):
        """The scene's live objects as a folder tree."""
        scene = self.scene
        if scene is None:
            return []
        live = [obj for obj in scene.objects if getattr(obj, "alive", True)]
        mine = {id(obj) for obj in live}
        out = []
        for obj in live:
            depth, parent, hidden = 0, getattr(obj, "parent", None), False
            while parent is not None and id(parent) in mine:
                depth += 1
                if self._node_key(parent) in self.collapsed:
                    hidden = True
                    break
                parent = getattr(parent, "parent", None)
            if hidden:
                continue
            kids = any(id(child) in mine
                       for child in getattr(obj, "children", ()) or ())
            out.append((obj, depth, kids))
        return out

    def _shelf_click(self, pos, shift=False):
        """A shelf click: fold, node row, value or air."""
        now = time.time()
        if self.node_ctx is not None:
            picked = None
            for action, rect in self.node_ctx:
                if rect.collidepoint(pos):
                    picked = action
                    break
            self.node_ctx = None        # a click anywhere closes the menu
            if picked == "add":
                self.app.open_node_picker(self._picker_rows(), "preview")
            elif picked == "del":
                self.remove_node()
            return True
        for key, rect in self.node_toggles:
            if rect.collidepoint(pos):
                if key in self.collapsed:
                    self.collapsed.discard(key)
                else:
                    self.collapsed.add(key)
                return True
        for obj, row in self.node_rows:
            if not row.collidepoint(pos):
                continue
            now = time.time()
            same = self._click is not None and self._click[1] is obj \
                and now - self._click[0] < 0.4
            self._click = (now, obj)
            if shift:
                self.toggle_select(obj)   # the tree picks like the viewport
            else:
                self.select(obj)
            if same:
                self.focus(obj)        # a double click frames it
            return True
        for key, field in self.prop_fields.items():
            if field.collidepoint(pos):
                self.begin_grip(key)
                return True
        if self.nodes_body.collidepoint(pos):
            self.select(None)
        return True

    def add_node(self, type_name):
        """Add a node under the selection when possible.

        A played-alone map takes its new nodes into the map document;
        a scene keeps them in its own, as it always did.
        """
        project, name = self.project, self.scene_name
        row = scenedoc.node_type(type_name)
        if project is None or name is None or row is None:
            return None
        is_map = self._map_doc_open() is not None
        api = mapdoc if is_map else scenedoc
        doc = (project.map_doc(name) if is_map
               else project.scene_doc(name) or scenedoc.blank_scene(
                   name, self._doc_kind()))
        if doc is None:
            return None
        if not is_map and not doc.get("script"):
            script = project.scene_script(name)
            if script is not None:
                doc["script"] = scenedoc.script_field("scripts/scenes",
                                                      script.name)
        label, solid = row[1], row[4] == "3d"
        parent_key = getattr(self.sel, "placed_id", None)
        parent = api.placed(doc, parent_key) if parent_key else None
        if self.sel is not None and parent is None:
            self.app.log(f"'{self._node_key(self.sel)}' is spawned by a "
                         f"script: {label} joins the "
                         f"{'map' if is_map else 'scene'}'s roots", "warn")
        # the next free name, counted as the scene counts
        index = 0
        while api.placed(
                doc, scenedoc.key(label, index, parent_key)) is not None:
            index += 1
        node_key = scenedoc.key(label, index, parent_key)
        entry = {"id": node_key, "type": str(type_name),
                 "pos": [0.0, 0.0, 0.0] if solid else [0.0, 0.0]}
        # a picked parent places at its pivot, else the origin
        api.add_placed(doc, entry, parent)
        self._save_home(is_map, name, doc)
        if parent is not None:
            self.collapsed.discard(str(parent.get("id")))
        self.sel = None
        self.sel_key = node_key
        self.pending = name          # build it, then pick it out again
        self.app.refresh_tree()
        self.app.log(f"added {node_key}", "ok")
        return entry

    def remove_node(self):
        """Take the selected nodes and their branches out.

        Each node leaves the file that placed it, so deleting a lamp a
        map brought does not edit the scene that only loads it.
        """
        project, name = self.project, self.scene_name
        if project is None or name is None:
            return False
        nodes = [o for o in (self.sels or ([self.sel] if self.sel
                                           else []))
                 if getattr(o, "placed_id", None)]
        if not nodes:
            self.app.log("only a node the document placed can be deleted",
                         "warn")
            return False
        homes = {}
        for obj in nodes:
            key = obj.placed_id
            is_map, doc, home = self._home_of(key)
            if doc is None:
                continue
            (mapdoc if is_map else scenedoc).remove_placed(doc, key)
            self.collapsed.discard(str(key))
            homes[(is_map, home)] = doc
        if not homes:
            return False
        for (is_map, home), doc in homes.items():
            self._save_home(is_map, home, doc)
        self.sel = None
        self.sel_key = None
        self.sels = []
        self.pending = name
        self.app.refresh_tree()
        what = str(nodes[0].placed_id)
        if len(nodes) > 1:
            what += f" (+{len(nodes) - 1} more)"
        self.app.log(f"removed {what}", "ok")
        return True

    def _property_rows(self):
        """What the properties block says about the selection."""
        obj = self.sel
        if obj is None or not getattr(obj, "alive", True):
            return []
        flat = self._flat()
        rows = [("class", "player start" if getattr(obj, "is_spawn", False)
                 else type(obj).__name__, None)]
        script = self._script_of(obj)
        if script:
            rows.append(("script", script, None))
        for i in range(2 if flat else len(getattr(obj, "pos", (2,)))):
            rows.append((f"pos {'xyz'[i]}", f"{obj.pos[i]:.3f}", ("pos", i)))
        if hasattr(obj, "yaw"):
            rows.append(("yaw", f"{obj.yaw:.4f}", "yaw"))
        if hasattr(obj, "rot"):
            rows.append(("rot", f"{obj.rot:.4f}", "rot"))
        if hasattr(obj, "scale"):
            rows.append(("scale", f"{obj.scale:.3f}", "scale"))
        if flat and isinstance(getattr(obj, "size", None), tuple):
            for i, axis in enumerate("wh"):
                rows.append((f"size {axis}", f"{obj.size[i]:.1f}",
                             ("size", i)))
        got = getattr(obj, "look", None) or {}
        # a picture node with no file still gets its row
        for field in ("model", "texture"):
            value = got.get(field)
            if value is None:
                value = getattr(obj, field, None)
            if value is None and field == "model" and \
                    hasattr(obj, "model_name"):
                value = ""
            if value is not None:
                rows.append((field, str(value), field))
        if got.get("color") is not None:
            rows.append(("colour", _colour_text(got["color"]), None))
        # what a node owns beyond a transform: shape, reach, switch
        for name in getattr(obj, "doc_knobs", ()) or ():
            if not hasattr(obj, name):
                continue
            value = getattr(obj, name)
            if isinstance(value, bool):
                rows.append((name, "true" if value else "false",
                             ("knob", name, None)))
            elif isinstance(value, (list, tuple)):
                for i, part in enumerate(value):
                    axis = "xyz"[i] if i < 3 else str(i)
                    rows.append((f"{name} {axis}", f"{float(part):.3f}",
                                 ("knob", name, i)))
            elif isinstance(value, (int, float)):
                rows.append((name, f"{float(value):.3f}",
                             ("knob", name, None)))
            else:
                rows.append((name, "" if value is None else str(value),
                             ("knob", name, None)))
        return rows

    def begin_grip(self, key):
        """Start typing a property value: the field takes the keyboard."""
        if self.sel is None:
            return False
        text = next((value for label, value, row_key in self.props
                     if row_key == key), "")
        self.grip = (key, widgets.TextField(text, 16))
        self.picks = self._open_picks(key)
        return True

    def _sel_class(self):
        """The engine class of the pick: it spells the words its knobs take."""
        return type(self.sel) if self.sel is not None else None

    def _pick_slot(self, key):
        """The picker a property row shows, or None."""
        if key in ("model", "texture"):
            return key
        if isinstance(key, tuple) and key[0] == "knob":
            name = key[1]
            if name in api.PICKERS or api.enumerable(name, self._sel_class()):
                return name
        return None

    def _open_picks(self, key):
        """The names this row holds, in a panel below, and a way out."""
        slot = self._pick_slot(key)
        anchor = self.prop_fields.get(key) if slot else None
        if anchor is None or not self.shelf_rect.width:
            return None
        words = api.choices(self.project, slot, self._sel_class())
        return widgets.Choices(words, anchor, self.shelf_rect,
                               add=True).filter("")

    def _picks_event(self, e):
        """The open list takes its own rows and arrows."""
        picks = self.picks
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if picks.holds(e.pos):
                word = picks.click(e.pos)
                if word is None:
                    return True         # the panel's own air: nothing to do
                return self._pick_word(word)
            self.picks = None
            return None
        if e.type != pygame.KEYDOWN:
            return None
        if e.key in (pygame.K_UP, pygame.K_DOWN):
            picks.step(-1 if e.key == pygame.K_UP else 1)
            word = picks.current()
            self.app.status = f"pick {word}" if word else "nothing matches"
            return True
        if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if picks.current() is None:
                return None     # nothing to take: submit what was typed
            return self._pick_word(picks.current())
        if e.key == pygame.K_ESCAPE:
            self.picks = None        # the list goes; the row stays open
            return True
        return None

    def _pick_word(self, word):
        """Write a picked name into the row and keep it."""
        self.picks = None
        if self.grip is None or word is None:
            return False
        key, field = self.grip
        if word == widgets.ADD_ROW:
            # not a name: empty the field and leave the keyboard in it
            field.set("")
            self.app.status = f"type a {self._pick_label(key)} of your own"
            return True
        field.set(word)
        self.set_property(key, field.text)
        self.grip = None
        self.app.status = f"{self._pick_label(key)} is {word}"
        return True

    def _pick_label(self, key):
        """The words a row is known by in the status."""
        for label, _value, row_key in self.props:
            if row_key == key:
                return label
        return str(key)

    def _grip_event(self, e):
        """Keyboard and clicks while a property value is being typed."""
        key, field = self.grip
        if self.picks is not None:
            got = self._picks_event(e)
            if got is not None:
                return got
        if e.type == pygame.KEYDOWN:
            result = field.handle(e)
            if result == "submit":
                self.set_property(key, field.text)
                self.grip = None
                self.picks = None
            elif e.key == pygame.K_ESCAPE:
                self.grip = None
                self.picks = None
            elif self.picks is not None:
                self.picks.filter(field.text)
            return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            rect = self.prop_fields.get(key)
            if rect is None or not rect.collidepoint(e.pos):
                self.set_property(key, field.text)
                self.grip = None
                self.picks = None
            return True
        return False

    def set_property(self, key, text):
        """Write a typed value onto the selection and document."""
        obj = self.sel
        if obj is None:
            return False
        if isinstance(key, tuple) and key[0] == "knob":
            return self.set_knob(key, text)
        if key in ("model", "texture"):
            return self.set_look(key, text)
        try:
            value = float(text)
        except (TypeError, ValueError):
            return False
        if isinstance(key, tuple):
            what, index = key
            if what == "pos":
                if index >= len(obj.pos):
                    return False
                obj.pos[index] = value
            elif what == "size":
                sizes = list(getattr(obj, "size", ()))
                if index >= len(sizes):
                    return False
                sizes[index] = max(1.0, value)
                obj.size = tuple(sizes)
                obj.dirty = True
            else:
                return False
        elif key == "yaw" and hasattr(obj, "yaw"):
            obj.yaw = value
        elif key == "rot" and hasattr(obj, "rot"):
            obj.rot = value
            obj.dirty = True
        elif key == "scale" and hasattr(obj, "scale"):
            obj.scale = max(0.01, value)
        else:
            return False
        self._moved(obj)
        self.edit_moved = True
        self._refresh(obj)
        if getattr(obj, "is_spawn", False):
            self.write_spawn()
        else:
            self.write_placement(obj)
        self.pending = self.scene_name
        return True

    def _moved(self, obj):
        """Tell the tree the transform changed directly."""
        moved = getattr(obj, "moved", None)
        if callable(moved):
            try:
                moved()
                return
            except Exception:
                pass
        try:
            if hasattr(obj, "push_local"):
                obj.push_local()
            if hasattr(obj, "propagate"):
                obj.propagate()
        except Exception:
            pass

    def set_knob(self, key, text):
        """Write one node setting: shape, half-size, switch or name."""
        obj = self.sel
        name, index = key[1], key[2]
        if obj is None or name not in (getattr(obj, "doc_knobs", ()) or ()):
            return False
        old = getattr(obj, name, None)
        text = str(text).strip()
        if name == "shader":
            # a look is a program name; `set_shader` resolves it
            obj.set_shader(text or None)
            self.edit_moved = True
            self._refresh(obj)
            self.write_placement(obj)
            self.pending = self.scene_name
            return True
        if isinstance(old, bool):
            value = text.lower() in ("1", "true", "yes", "on")
        elif isinstance(old, (list, tuple)):
            parts = text.replace(",", " ").split()
            try:
                nums = [float(part) for part in parts]
            except ValueError:
                return False
            if not nums:
                return False
            if index is None:
                if len(nums) not in (2, 3):
                    return False
                value = tuple(nums)
            elif index < len(old):
                value = list(old)
                value[index] = nums[0] if len(nums) == 1 \
                    else nums[min(index, len(nums) - 1)]
                value = tuple(value)
            else:
                return False
        elif isinstance(old, (int, float)):
            try:
                value = float(text)
            except ValueError:
                return False
        else:
            if not text:
                return False
            value = text
        setter = getattr(obj, "set", None)
        try:
            setter(**{name: value})
        except TypeError:
            # the node keeps the setting; a rebuild applies it
            setattr(obj, name, value)
        self.edit_moved = True
        self._refresh(obj)
        self.write_placement(obj)
        self.pending = self.scene_name
        return True

    def set_look(self, field, text):
        """Give the node its picture: a model or sheet."""
        obj = self.sel
        text = str(text).strip()
        if obj is None or not text or field not in ("model", "texture"):
            return False
        stem = Path(text).stem
        got = getattr(obj, "look", None)
        if not isinstance(got, dict):
            got = {}
            obj.look = got
        got[field] = stem
        setter = getattr(obj, "set", None)
        try:
            setter(**{field: stem})
        except TypeError:
            # write only where a name was; keep loaded models
            current = getattr(obj, field, None)
            if current is None or isinstance(current, str):
                setattr(obj, field, stem)
        missing = []
        if self.project is not None:
            if field == "texture":
                # a sheet is a file, a built-in or a colour
                if not api.known(self.project, "texture", stem):
                    missing.append(f"no texture '{stem}'")
            else:
                solid = self.project.model_path(stem).is_file()
                flat = self.project.model2d_path(stem).is_file()
                if not (solid or flat):
                    hint = (", and it is a shape the Model tab builds from"
                            if stem in api.BUILTIN_MODELS else "")
                    missing.append(f"no model '{stem}' in the project{hint}")
        if missing:
            self.app.log(f"{', '.join(missing)}: {field} set anyway", "warn")
        else:
            self.app.log(f"{field} -> {stem}", "ok")
        self.edit_moved = True
        self._refresh(obj)
        self.write_placement(obj)
        self.pending = self.scene_name
        return True

    def _edit_zoom(self, steps):
        """Wheel zooms flat scenes; the 3D camera flies."""
        scene = self.scene
        if scene is None or getattr(scene, "kind", "3d") == "3d":
            return False
        view = getattr(scene, "view", None)
        if not hasattr(view, "zoom_by"):
            return False
        view.zoom_by(steps)
        return True

    def _forward_key(self, e):
        """Hand one key event to the scene's input map, releases always.

        A press belongs to the viewport the pointer is over, but a release
        belongs to whoever took that press: dropping it because the pointer
        has since moved off - or because a hidden cursor reports an
        off-screen point - is how a key stays down and the camera keeps
        flying. A Ctrl chord is the editor's to swallow, but its release
        still has to reach the map, or the bare key underneath stays held.
        """
        if e.type == pygame.KEYUP:
            self.input.handle(e)
            return True
        if e.mod & pygame.KMOD_CTRL:
            return False
        if self.inner.collidepoint(
                getattr(e, "pos", pygame.mouse.get_pos())) or self._hover():
            self.input.handle(e)
            return True
        return False

    def _edit_event(self, e, inside):
        """Gestures Edit takes: tools, pick, gizmo, drag, fly, pan, zoom."""
        pos = getattr(e, "pos", pygame.mouse.get_pos())
        if inside and e.type == pygame.MOUSEBUTTONDOWN:
            if e.button == 1:
                local = self._local(pos)
                grip = self.gizmo_at(local)
                if grip is not None:
                    self.begin_gizmo(grip, local)
                    return True
                add = self._shift(e)
                if self.tool == "move":
                    # a body drag is the free move; Select only picks
                    self.begin_drag(pos, add=add)
                elif add:
                    obj = self.pick(pos)
                    if obj is not None:
                        self.toggle_select(obj)
                else:
                    self.select(self.pick(pos))
                return True
            if e.button == 3:
                self.look = True
                return True
        if e.type == pygame.MOUSEMOTION:
            if self.gizmo is not None:
                self.gizmo_to(e.pos)
                return True
            if self.drag is not None:
                self.drag_to(e.pos)
                return True
            if inside and self.look:
                if getattr(self.scene, "kind", "3d") != "3d":
                    view = self.scene.view
                    cur = view.anchor_center()
                    view.set_center((cur[0] - e.rel[0] / max(view.zoom, 1e-3),
                                     cur[1] - e.rel[1] / max(view.zoom, 1e-3)))
                    return True
                self.mouse_rel[0] += e.rel[0]
                self.mouse_rel[1] += e.rel[1]
                return True
        if e.type == pygame.MOUSEBUTTONUP:
            if e.button == 1 and self.gizmo is not None:
                self.end_gizmo()
                return True
            if e.button == 1 and self.drag is not None:
                self.end_drag()
                return True
            if e.button == 3:
                self.look = False
                return True
        if e.type == pygame.MOUSEWHEEL and inside:
            if self._edit_zoom(e.y):
                return True
        if e.type == pygame.KEYDOWN and self._edit_key(e):
            return True
        if e.type in (pygame.KEYDOWN, pygame.KEYUP):
            return self._forward_key(e)
        return False

    def _edit_key(self, e):
        """Edit's own shortcuts, before the scene's input map sees them."""
        if e.mod & pygame.KMOD_CTRL:
            return False              # Ctrl+S and friends are the editor's
        for name, _label, key in TOOLS:
            if e.key == key:
                self.set_tool(name)
                return True
        if e.key == pygame.K_f:
            self.focus()
            return True
        if e.key == pygame.K_g:
            self.grid = not self.grid
            return True
        if e.key == pygame.K_h:
            self.show_shapes = not self.show_shapes
            return True
        if e.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            return self.remove_node()
        if e.key == pygame.K_ESCAPE:
            if self.node_ctx is not None:
                self.node_ctx = None        # the menu closes before the pick
                return True
            self.select(None)             # one Esc empties the whole set
            return True
        return False

    def set_tool(self, name):
        """Arm one of four transforms; the gizmo follows."""
        self.tool = name
        self.gizmo = None
        self.app.status = f"scene tool: {name}"
        return name

    def _flat(self):
        """True when the open scene works in pixels."""
        return self.scene is not None and \
            getattr(self.scene, "kind", "3d") != "3d"

    def _snap_step(self):
        return SNAP_2D if self._flat() else SNAP_3D

    def _snapped(self, value, step=None):
        """Round a value onto the Snap grid."""
        if not self.snap:
            return value
        step = step or self._snap_step()
        return round(value / step) * step

    def focus(self, obj=None):
        """Put the edit camera on the selection, keeping its angle."""
        obj = self.sel if obj is None else obj
        if obj is None or self.scene is None:
            return False
        if self._flat():
            view = getattr(self.scene, "view", None)
            if view is None:
                return False
            view.set_center((float(obj.pos[0]), float(obj.pos[1])))
            return True
        cam = self.game.camera
        target = [float(c) for c in obj.pos]
        away = [cam.eye[i] - target[i] for i in range(3)]
        length = math.sqrt(sum(c * c for c in away)) or 1.0
        dist = max(3.0, 4.0 * float(getattr(obj, "scale", 1.0) or 1.0))
        cam.eye = [target[i] + away[i] / length * dist for i in range(3)]
        cam.wanted = None
        return True

    def _to_pixels(self, point):
        """A world pixel as a viewport pixel, flat scenes."""
        view = getattr(self.scene, "view", None)
        if view is None:
            return (point[0], point[1])
        vw, vh = view.view_size()
        c = view.anchor_center()
        return ((point[0] - (c[0] - vw / 2.0)) * view.zoom,
                (point[1] - (c[1] - vh / 2.0)) * view.zoom)

    @staticmethod
    def _along(pos, vec, step):
        """A point `step` along one axis vector from `pos`."""
        return (pos[0] + vec[0] * step, pos[1] + vec[1] * step,
                pos[2] + vec[2] * step)

    def _axes(self):
        """The frame the Move arms are drawn in."""
        if self.space != "local" or self.sel is None or self._flat():
            return AXIS_VECTORS
        yaw = float(getattr(self.sel, "yaw", 0.0) or 0.0)
        c, s = math.cos(yaw), math.sin(yaw)
        return {"x": (c, 0.0, -s), "y": AXIS_VECTORS["y"],
                "z": (s, 0.0, c)}

    def _handles(self):
        """The move gizmo's arms: (axis, colour, from, to) in pixels."""
        obj = self.sel
        if obj is None or not getattr(obj, "alive", True):
            return []
        if self._flat():
            px, py = self._to_pixels(obj.pos)
            return [("x", AXES["x"], (px, py), (px + HANDLE_PX, py)),
                    ("y", AXES["y"], (px, py), (px, py - HANDLE_PX))]
        cam = self.game.camera
        size = self.inner.size
        axes = self._axes()
        got = cam.project(obj.pos, size)
        if got is None:
            return []
        origin = (got[0], got[1])
        out = []
        for axis in ("x", "y", "z"):
            tip = cam.project(self._along(obj.pos, axes[axis], 1.0), size)
            if tip is None:
                continue
            dx, dy = tip[0] - origin[0], tip[1] - origin[1]
            length = math.hypot(dx, dy)
            if length < 1e-3:
                continue
            out.append((axis, AXES[axis], origin,
                        (origin[0] + dx / length * HANDLE_PX,
                         origin[1] + dy / length * HANDLE_PX)))
        return out

    def _ring(self):
        """The rotate gizmo: points around the pivot, in pixels."""
        obj = self.sel
        if obj is None or not getattr(obj, "alive", True):
            return []
        radius = HANDLE_PX * 0.9
        if self._flat():
            px, py = self._to_pixels(obj.pos)
            return [(px + math.cos(a) * radius, py + math.sin(a) * radius)
                    for a in (i * math.pi / 16.0 for i in range(33))]
        cam = self.game.camera
        size = self.inner.size
        got = cam.project(obj.pos, size)
        step = cam.project(self._along(obj.pos, AXIS_VECTORS["x"], 1.0),
                           size)
        if got is None or step is None:
            return []
        k = math.hypot(step[0] - got[0], step[1] - got[1]) or 1.0
        r = radius / k
        out = []
        for i in range(33):
            a = i * math.pi / 16.0
            got = cam.project((obj.pos[0] + math.cos(a) * r, obj.pos[1],
                               obj.pos[2] + math.sin(a) * r), size)
            out.append(None if got is None else (got[0], got[1]))
        return out

    def _scale_handle(self):
        """Where the scale gizmo's one grip sits, in pixels."""
        obj = self.sel
        if obj is None or not getattr(obj, "alive", True):
            return None
        if self._flat():
            px, py = self._to_pixels(obj.pos)
            return (px - HANDLE_PX * 0.7, py - HANDLE_PX * 0.7)
        got = self.game.camera.project(obj.pos, self.inner.size)
        if got is None:
            return None
        return (got[0] - HANDLE_PX * 0.7, got[1] - HANDLE_PX * 0.7)

    def gizmo_at(self, local):
        """What a click at a viewport pixel grabs: `move:x`, `rotate`..."""
        obj = self.sel
        if obj is None or not getattr(obj, "alive", True):
            return None
        if self.tool == "move":
            best, gap = None, GRAB_PX
            for axis, _colour, a, b in self._handles():
                d = _seg_distance(local[0], local[1], a, b)
                if d <= gap:
                    best, gap = f"move:{axis}", d
            return best
        if self.tool == "rotate":
            pts = self._ring()
            if not pts:
                return None
            if self._flat():
                px, py = self._to_pixels(obj.pos)
                d = math.hypot(local[0] - px, local[1] - py)
                return "rotate" if abs(d - HANDLE_PX * 0.9) <= 10.0 else None
            for i in range(len(pts) - 1):
                if pts[i] is not None and pts[i + 1] is not None and \
                        _seg_distance(local[0], local[1], pts[i],
                                      pts[i + 1]) <= GRAB_PX:
                    return "rotate"
            return None
        if self.tool == "scale":
            grip = self._scale_handle()
            if grip is not None and \
                    math.hypot(local[0] - grip[0],
                               local[1] - grip[1]) <= 10.0:
                return "scale"
        return None

    def begin_gizmo(self, grip, local):
        """Take hold of a handle; remember the start state."""
        obj = self.sel
        if obj is None:
            return None
        kind, _sep, axis = grip.partition(":")
        self.gizmo = {
            "kind": kind, "axis": axis or None, "obj": obj,
            "from": local, "start": list(obj.pos),
            "yaw": getattr(obj, "yaw", None),
            "rot": getattr(obj, "rot", None),
            "scale": getattr(obj, "scale", None),
            "size": tuple(getattr(obj, "size", ()) or ()),
            "vec": None, "s": None, "world": None, "angle": None,
        }
        if kind == "move":
            if self._flat():
                self.gizmo["world"] = self.scene.to_world(local)
            elif axis:
                # keep the arm's vector for the drag; Global/Local may flip
                self.gizmo["vec"] = self._axes()[axis]
                self.gizmo["s"] = self._axis_param(local, obj.pos,
                                                   self.gizmo["vec"])
        if kind == "rotate" and self._flat():
            world = self.scene.to_world(local)
            self.gizmo["angle"] = math.atan2(world[1] - obj.pos[1],
                                             world[0] - obj.pos[0])
        self.edit_moved = False
        return self.gizmo

    def gizmo_to(self, pos=None):
        """Follow the pointer with whatever handle is held."""
        drag = self.gizmo
        if drag is None:
            return None
        obj = drag["obj"]
        local = self._local(pos)
        if drag["kind"] == "move":
            return self._gizmo_move(drag, obj, local)
        if drag["kind"] == "rotate":
            return self._gizmo_rotate(drag, obj, local)
        return self._gizmo_scale(drag, obj, local)

    def _axis_param(self, local, origin, vec):
        """How far along an axis a mouse ray passes."""
        cam = self.game.camera
        origin_ray, direction = cam.ray(self.inner.size, local)
        v = vec
        w = [origin[i] - origin_ray[i] for i in range(3)]
        b = sum(v[i] * direction[i] for i in range(3))
        denom = 1.0 - b * b
        if abs(denom) < 1e-5:
            return None            # the axis points at the eye
        wd = sum(w[i] * v[i] for i in range(3))
        wu = sum(w[i] * direction[i] for i in range(3))
        return (b * wu - wd) / denom

    def _gizmo_move(self, drag, obj, local):
        axis = drag["axis"]
        start = drag["start"]
        index = "xyz".index(axis)
        if self._flat():
            world = self.scene.to_world(local)
            step = world[index] - drag["world"][index]
            target = list(start)
            target[index] = self._snapped(start[index] + step)
        else:
            vec = drag["vec"] or AXIS_VECTORS[axis]
            s = self._axis_param(local, start, vec)
            if s is None or drag["s"] is None:
                return None
            step = s - drag["s"]
            if self.space == "global":
                target = list(start)
                target[index] = self._snapped(start[index] + step)
            else:
                # a local arm is no axis: snap distance travelled
                step = self._snapped(step)
                target = [start[i] + vec[i] * step for i in range(3)]
        return self.move_object(obj, target)

    def _gizmo_rotate(self, drag, obj, local):
        if self._flat():
            if not hasattr(obj, "rot"):
                return None
            world = self.scene.to_world(local)
            angle = math.atan2(world[1] - obj.pos[1], world[0] - obj.pos[0])
            obj.rot = self._snapped(drag["rot"] + (angle - drag["angle"]),
                                    SNAP_ANGLE)
            obj.dirty = True
        else:
            if not hasattr(obj, "yaw"):
                return None
            dx = local[0] - drag["from"][0]
            obj.yaw = self._snapped(drag["yaw"] + dx * 0.012, SNAP_ANGLE)
        self.edit_moved = True
        self._refresh(obj)
        return obj

    def _gizmo_scale(self, drag, obj, local):
        factor = math.exp((drag["from"][1] - local[1]) * 0.006)
        if self._flat() and drag["size"]:
            obj.size = tuple(max(1.0, self._snapped(c * factor, 1.0))
                             for c in drag["size"])
            obj.dirty = True
        elif drag["scale"] is not None:
            obj.scale = max(0.01, self._snapped(drag["scale"] * factor, 0.1))
        else:
            return None
        self.edit_moved = True
        self._refresh(obj)
        return obj

    def end_gizmo(self):
        """Let go: write what the handle did into the document."""
        drag, self.gizmo = self.gizmo, None
        if drag is None:
            return None
        obj = drag["obj"]
        if not self.edit_moved:
            return None
        if getattr(obj, "is_spawn", False):
            self.write_spawn()
        else:
            self.write_placement(obj)
        self.pending = self.scene_name      # rebuild where it now sits
        self.edit_moved = False
        return obj

    def _video_rect(self):
        return pygame.Rect(self.rect.x, self.rect.y, self.rect.width, VIDEO_H)

    def _hover(self):
        return self.inner.collidepoint(pygame.mouse.get_pos())

    def capture(self):
        """Give the viewport the pointer and the keyboard."""
        if self.focus_mode:
            return True
        if self.scene is None or self._flat():
            self.app.log("focus needs a running 3D scene", "warn")
            return False
        self.focus_mode = True
        self.grip = None
        self.picks = None
        self.look = True
        self.mouse_rel = [0, 0]
        try:
            self.input.grab_mouse(True)
        except pygame.error:
            pass
        self.app.status = "focus on the viewport - Esc releases"
        return True

    def release(self):
        """Hand the pointer and the keyboard back to the editor."""
        was = self.focus_mode
        self.focus_mode = False
        self.look = False
        self.mouse_rel = [0, 0]
        # a key held at the moment focus ends must not stay held
        self._let_go()
        try:
            self.input.grab_mouse(False)
        except pygame.error:
            pass
        if was:
            self.app.status = "focus released"
        return was

    def _focus_event(self, e):
        """One event while the viewport owns the pointer."""
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.release()
            return True
        if e.type == pygame.KEYDOWN and self.mode == "edit" and \
                self._edit_key(e):
            return True
        if e.type in (pygame.KEYDOWN, pygame.KEYUP):
            if e.type == pygame.KEYDOWN and e.mod & pygame.KMOD_CTRL:
                return True          # the editor's shortcuts stay shut
            # a Ctrl chord's release still belongs to the key underneath
            self.input.handle(e)
            return True
        if e.type == pygame.MOUSEMOTION:
            if self.mode == "edit" and self.gizmo is not None:
                self.gizmo_to(e.pos)
            elif self.mode == "edit" and self.drag is not None:
                self.drag_to(e.pos)
            else:
                self.mouse_rel[0] += e.rel[0]
                self.mouse_rel[1] += e.rel[1]
            return True
        if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                      pygame.MOUSEWHEEL):
            if self.mode == "edit":
                return self._edit_event(e, True)
            self.input.handle(e)
            return True
        return True

    def handle_event(self, e):
        pos = getattr(e, "pos", pygame.mouse.get_pos())
        if self.focus_mode:
            return self._focus_event(e)
        if self.mode == "edit" and self.grip is not None and \
                self._grip_event(e):
            return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and \
                self.vol_rect.collidepoint(pos):
            self.vol_drag = True
            self._set_volume(pos)
            return True
        if e.type == pygame.MOUSEMOTION and self.vol_drag:
            self._set_volume(pos)
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.vol_drag:
            self.vol_drag = False
            return True
        for kind, rect in self.buttons:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and \
                    rect.collidepoint(pos):
                if kind == "prev":
                    self.cycle_scene(-1)
                elif kind == "next":
                    self.cycle_scene(1)
                elif kind == "reload":
                    self.reload()
                elif kind == "play":
                    if not self.started:
                        self.play()
                    elif self.paused:
                        self.paused = False
                elif kind == "pause":
                    if self.started:
                        self.paused = not self.paused
                elif kind == "stop":
                    self.stop()
                elif kind == "mute":
                    self.toggle_mute()
                elif kind == "hud":
                    self.hud = not self.hud
                elif kind == "mode_game":
                    self.toggle_mode("game")
                elif kind == "mode_edit":
                    self.toggle_mode("edit")
                elif kind.startswith("tool:"):
                    self.set_tool(kind.split(":", 1)[1])
                elif kind == "space":
                    self.space = "local" if self.space == "global" \
                        else "global"
                elif kind == "snap":
                    self.snap = not self.snap
                elif kind == "grid":
                    self.grid = not self.grid
                elif kind == "shapes":
                    self.show_shapes = not self.show_shapes
                elif kind == "addnode":
                    # one searchable list, filtered to what this scene can host
                    self.app.open_node_picker(self._picker_rows(),
                                              "preview")
                elif kind == "delnode":
                    self.remove_node()
                elif kind == "focus":
                    self.capture()
                elif kind == "lighting":
                    self.toggle_lighting()
                elif kind == "frame":
                    self.focus()
                elif kind == "revert":
                    self.revert()
                return True
        if e.type == pygame.MOUSEBUTTONDOWN and self.node_ctx is not None \
                and not self.shelf_rect.collidepoint(pos):
            self.node_ctx = None          # a click away closes the menu
        if self.mode == "edit" and self.shelf_rect.collidepoint(pos):
            # the shelf owns its clicks; they never reach the viewport
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                return self._shelf_click(pos, self._shift(e))
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
                return self._shelf_rclick(pos)
            if e.type == pygame.MOUSEWHEEL:
                if self.nodes_body.collidepoint(pos):
                    self.nodes_scroll = max(
                        0, min(self.nodes_max,
                               self.nodes_scroll - e.y * NODE_ROW * 3))
                return True
            return e.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION)
        inside = self.inner.collidepoint(pos)
        if self.mode == "edit":
            return self._edit_event(e, inside)
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
        if e.type in (pygame.KEYDOWN, pygame.KEYUP):
            if e.type == pygame.KEYDOWN and e.key == pygame.K_r and \
                    (inside or self._hover()) and \
                    not e.mod & pygame.KMOD_CTRL:
                self.reload()
                return True
            return self._forward_key(e)
        if self.scene is not None and (inside or self._hover()):
            try:
                if getattr(self.scene, "kind", "3d") != "3d" and \
                        e.type in (pygame.MOUSEMOTION,
                                   pygame.MOUSEBUTTONDOWN,
                                   pygame.MOUSEBUTTONUP,
                                   pygame.MOUSEWHEEL):
                    # widgets want viewport pixels; rebase on the inner rect
                    orig = e.pos
                    e.pos = (orig[0] - self.inner.x, orig[1] - self.inner.y)
                    try:
                        if self.scene.handle_event(e):
                            return True
                    finally:
                        e.pos = orig
                elif self.scene.handle_event(e):
                    return True
            except Exception as exc:
                self.app.log(f"scene event failed: {exc}", "warn")
        return False

    def _set_volume(self, pos):
        """Drag the slider to set the master level."""
        frac = xp.slider_frac(self.vol_rect, pos)
        self.app.audio.set_master(frac)
        if frac > 0.0 and self.muted:
            self.muted = False

    def toggle_mute(self):
        """Sound on/off: park the master level and restore it after."""
        audio = self.app.audio
        self.muted = not self.muted
        if self.muted:
            self._vol_before = max(float(audio.master), 0.05)
            audio.set_master(0.0)
        else:
            audio.set_master(self._vol_before)

    def _rate(self):
        """The real frame rate, timed between draws."""
        now = time.perf_counter()
        last, self._last_draw = self._last_draw, now
        if last is None:
            return
        gap = now - last
        if gap > 0.0:
            self.fps = self.fps * 0.8 + (1.0 / gap) * 0.2

    def draw(self, surface, rect, dt=1 / 60.0):
        self.rect = pygame.Rect(rect)
        pygame.draw.rect(surface, xp.FACE, self.rect)
        self._draw_video_bar(surface)
        self._rate()
        # a tools strip under the transport, a shelf beside
        top = self.rect.y + VIDEO_H
        if self.mode == "edit":
            # the strip is as tall as its captioned bands measure
            bands, used = widgets.bands(
                pygame.Rect(self.rect.x, top, self.rect.width, 240),
                self.fonts["small"], self._tool_groups())
            self.tools_rect = pygame.Rect(self.rect.x, top, self.rect.width,
                                          used)
            self._draw_tools(surface, bands)
            top += used
        else:
            self.tools_rect = pygame.Rect(0, 0, 0, 0)
        body = pygame.Rect(self.rect.x + 2, top + 2, self.rect.width - 4,
                           max(10, self.rect.bottom - top - 4))
        # the shelf only earns its width if a viewport fits
        shelf = self.mode == "edit" and body.width > SHELF_W + 260
        if shelf:
            self.shelf_rect = pygame.Rect(body.right - SHELF_W, body.y,
                                          SHELF_W, body.height)
            self.inner = pygame.Rect(body.x, body.y, body.width - SHELF_W,
                                     body.height)
        else:
            self.shelf_rect = pygame.Rect(0, 0, 0, 0)
            self.inner = body
        pygame.draw.rect(surface, (16, 18, 22), self.inner)
        xp.sunken(surface, self.inner)
        inner = self.inner.inflate(-2, -2)
        self._ensure_renderer(inner.size)
        self.update(dt)
        # Edit's look applies after the build, changing the scene
        self._apply_view()
        if self.error:
            self._draw_error(surface, inner)
            self._draw_tip(surface)
            return
        if self.scene is None:
            if self.project is None:
                msg = "Open a project to preview scenes."
            elif not self.started:
                msg = "Press Play to start."
            else:
                msg = "No scene selected."
            img = widgets.cached_text(self.fonts["normal"], msg,
                                      xp.TEXT_MUTED)
            surface.blit(img, (inner.centerx - img.get_width() // 2,
                               inner.centery - img.get_height() // 2))
            self._draw_tip(surface)
            return
        game = self.game
        # the HUD surface is the window the scene draws into this frame
        screen = game.screen.fit(inner.size)
        passes = tuple(getattr(self.scene, "post", ())) or \
            tuple(self.project.post)
        # the scene's look chains its own shaders inside the render
        self.renderer.set_clock(getattr(self.scene, "t", 0.0))
        self.renderer.set_post(shaders.resolve(self.project, passes))
        # one entry point per kind: 3D through the game camera
        frame = self.scene.render(game.camera)
        if frame.get_size() != inner.size:
            frame = pygame.transform.smoothscale(frame, inner.size)
        if self.hud:
            try:
                self.scene.overlay(screen)
            except Exception as exc:
                if not self._error_logged:
                    self.app.log(f"overlay failed: {exc}", "error")
                    self._error_logged = True
            # whatever the overlay managed to paint still reaches the frame
            frame.blit(screen, (0, 0))
        surface.blit(frame, inner.topleft)
        old = surface.get_clip()
        surface.set_clip(inner)
        if self.hud:
            img = widgets.cached_text(self.fonts["small"],
                                      self._hint(),
                                      (228, 226, 214))
            surface.blit(img, (inner.right - img.get_width() - 8,
                               inner.bottom - img.get_height() - 6))
        if self.mode == "edit":
            self._sync_spawn()
            if self.grid:
                self._draw_grid(surface)
            self._draw_selection(surface, self.inner)
            self._draw_shapes(surface)
            self._draw_gizmo(surface)
            self._draw_spawn(surface)
        if self.paused:
            ui.dim(surface, 0.45)
            img = widgets.cached_text(self.fonts["big"], "Paused",
                                      (245, 242, 232))
            surface.blit(img, (inner.centerx - img.get_width() // 2,
                               inner.centery - img.get_height() // 2))
        surface.set_clip(old)
        if shelf:
            self._draw_shelf(surface)
        self._draw_tip(surface)

    def _draw_tip(self, surface):
        """One XP bubble for the toolbar button under the pointer."""
        mouse = pygame.mouse.get_pos()
        for rect, tip in self.tips:
            if tip and rect.collidepoint(mouse):
                xp.tooltip(surface, mouse, [tip], self.fonts["small"])
                return

    def _draw_video_bar(self, surface):
        bar = self._video_rect()
        surface.fill(xp.FACE, bar)
        pygame.draw.line(surface, xp.SHADOW, (bar.x, bar.bottom - 1),
                         (bar.right, bar.bottom - 1))
        mouse = pygame.mouse.get_pos()
        self.buttons = []
        self.tips = []
        x = bar.x + 4
        # transport first, then the scene picker; play-sym starts when stopped
        running = self.started and not self.paused
        # the mode pair sits first; it decides the rest
        items = (("mode_game", "Game", None),
                 ("mode_edit", "Edit", None),
                 ("prev", "", "step-backward-sym"),
                 ("next", "", "step-forward-sym"),
                 ("play", None, "play-sym"),
                 ("pause", None, "pause-sym"),
                 ("stop", None, "stop-sym"),
                 ("reload", "Reload", "reload-sym"),
                 ("focus", "Focus", None))
        for kind, label, art in items:
            label = label or ""
            # a bare picture keeps 24 px; text adds the gap
            w = max(24, self.fonts["small"].size(label)[0] + 12 +
                    (18 if label and art else 0))
            r = pygame.Rect(x, bar.y + 2, w, bar.height - 4)
            xp.button(surface, r, label, self.fonts["small"],
                      icon=widgets.icon(art, 14) if art else None,
                      hovered=r.collidepoint(mouse),
                      pressed=((kind == "play" and running)
                               or (kind == "pause" and self.started
                                   and self.paused)
                               or (kind == "mode_game"
                                   and self.mode == "game")
                               or (kind == "mode_edit"
                                   and self.mode == "edit")
                               or (kind == "focus"
                                   and self.focus_mode)))
            self.buttons.append((kind, r))
            self.tips.append((r, BAR_TIPS.get(kind)))
            x = r.right + 3
            if kind in ("mode_edit", "stop"):
                # etch between the bands: mode | transport | the rest
                pygame.draw.line(surface, xp.SHADOW, (x + 1, bar.y + 5),
                                 (x + 1, bar.bottom - 5))
                x += 5
        name = self.scene_name or self.pending or self.selected or "-"
        # right hand cluster: fps, show/hide, sound on/off, volume slider
        right = f"{self.fps:3.0f} fps"
        img = widgets.cached_text(self.fonts["small"], right, xp.TEXT_MUTED)
        surface.blit(img, (bar.right - img.get_width() - 8,
                           bar.centery - img.get_height() // 2))
        rx = bar.right - img.get_width() - 14
        for kind, art in (("hud", "visable-sym" if self.hud
                                   else "hidden-sym"),
                          ("mute", "sound-off-sym" if self.muted
                                   else "sound-on-sym")):
            r = pygame.Rect(0, 0, 24, bar.height - 4)
            r.midright = (rx, bar.centery)
            xp.button(surface, r, "", self.fonts["small"],
                      hovered=r.collidepoint(mouse))
            widgets.draw_icon(surface, art, r)
            self.buttons.append((kind, r))
            self.tips.append((r, BAR_TIPS.get(kind)))
            rx = r.x - 4
        # the slider takes what the cluster has left, never the name's room
        room = rx - (x + 8) - 12
        self.vol_rect = pygame.Rect(0, 0, min(72, room), 14) \
            if room >= 48 else pygame.Rect(0, 0, 0, 0)
        if self.vol_rect.width:
            self.vol_rect.midright = (rx, bar.centery)
            master = float(self.app.audio.master)
            xp.slider(surface, self.vol_rect,
                      0.0 if self.muted else master, live=self.vol_drag)
            rx = self.vol_rect.x - 8
        # the scene the preview is showing, cut rather than drawn over
        room = rx - (x + 8)
        if room > 40:
            img = widgets.cached_text(
                self.fonts["normal"],
                widgets.elide(self.fonts["normal"], f"scene: {name}", room),
                xp.TEXT)
            surface.blit(img, (x + 8, bar.centery - img.get_height() // 2))

    def _tool_groups(self):
        """The Edit strip as captioned bands of (label, action, on, tip)."""
        gizmo = []
        if not self._flat():
            gizmo.append(("Local" if self.space == "local" else "Global",
                          "space", False, SWITCH_TIPS["space"]))
        gizmo += [("Snap", "snap", self.snap, SWITCH_TIPS["snap"]),
                  ("Grid", "grid", self.grid, SWITCH_TIPS["grid"])]
        return [
            ("Tool", [(label, f"tool:{name}", self.tool == name,
                       TOOL_TIPS.get(name))
                      for name, label, _key in TOOLS]),
            ("Gizmo", gizmo),
            ("Show", [("Shapes", "shapes", self.show_shapes,
                       SWITCH_TIPS["shapes"]),
                      ("Lighting", "lighting", self.light_view,
                       SWITCH_TIPS["lighting"])]),
            ("Scene", [("Frame", "frame", False, SWITCH_TIPS["frame"]),
                       ("Revert", "revert", False, SWITCH_TIPS["revert"])]),
        ]

    def _draw_tools(self, surface, bands):
        """The Edit strip: what you drag with, and what the view shows."""
        bar = self.tools_rect
        surface.fill(xp.FACE, bar)
        pygame.draw.line(surface, xp.SHADOW, (bar.x, bar.bottom - 1),
                         (bar.right, bar.bottom - 1))
        small = self.fonts["small"]
        mouse = pygame.mouse.get_pos()
        for row in bands:
            widgets.band(surface, row["frame"], row["caption"], small)
        for row in bands:
            for item, rect in row["buttons"]:
                xp.button(surface, rect, item[0], small, default=item[2],
                          hovered=rect.collidepoint(mouse))
                self.buttons.append((item[1], rect))
                self.tips.append((rect, item[3]))
        hint = ("1-4 tools  F frame  G grid  H shapes  " +
                ("RMB pan  wheel zoom" if self._flat()
                 else "RMB look  WASD fly"))
        img = widgets.cached_text(small, hint, xp.TEXT_MUTED)
        edge = bands[-1]["frame"].right + 14 if bands else bar.right
        if img is not None and bar.right - 8 - img.get_width() > edge:
            surface.blit(img, (bar.right - 8 - img.get_width(),
                               bar.centery - img.get_height() // 2))

    def _draw_shelf(self, surface):
        """Edit's shelf: the scene's nodes above, their values below."""
        area = self.shelf_rect
        if area.width <= 0:
            return
        small = self.fonts["small"]
        pygame.draw.rect(surface, xp.FACE, area)
        pygame.draw.line(surface, xp.SHADOW, (area.x, area.y),
                         (area.x, area.bottom - 1))
        head = pygame.Rect(area.x + 1, area.y, area.width - 1, 22)
        nodes = self._nodes_of_scene()
        picked = [o for o in (self.sels or ([self.sel] if self.sel else []))
                  if o is not None]
        widgets.header(surface, head, "Scene", small)
        # the Add button owns the header's right end, so the count sits left
        aw = max(38, small.size("Add")[0] + 14)
        add_rect = pygame.Rect(head.right - aw - 6, head.y + 3, aw,
                               head.height - 6)
        count = (f"{len(picked)} selected" if len(picked) > 1
                 else f"{len(nodes)} nodes")
        img = widgets.cached_text(small, count, xp.TEXT_MUTED)
        if img is not None and add_rect.x - 8 - img.get_width() > head.x + 46:
            surface.blit(img, (add_rect.x - 8 - img.get_width(),
                               head.centery - img.get_height() // 2))
        xp.button(surface, add_rect, "Add", small,
                  hovered=add_rect.collidepoint(pygame.mouse.get_pos()))
        self.buttons.append(("addnode", add_rect))
        free = area.bottom - head.bottom - 8
        split = head.bottom + 4 + max(96, int(free * 0.46))
        body = pygame.Rect(area.x + 4, head.bottom + 4, area.width - 8,
                           max(40, split - head.bottom - 8))
        pygame.draw.rect(surface, xp.FIELD, body)
        xp.sunken(surface, body)
        self.nodes_body = body
        self._draw_nodes(surface, body, nodes)
        if self.node_ctx is not None:
            self._draw_node_ctx(surface)
        props_head = pygame.Rect(area.x + 1, body.bottom + 6,
                                 area.width - 1, 22)
        label = getattr(self.sel, "doc_key", None) or ""
        widgets.header(surface, props_head, "Properties", small, right=label)
        props = pygame.Rect(area.x + 4, props_head.bottom + 4,
                            area.width - 8,
                            max(20, area.bottom - props_head.bottom - 8))
        pygame.draw.rect(surface, xp.FIELD_ALT, props)
        xp.sunken(surface, props)
        self._draw_props(surface, props)
        if self.picks is not None:
            # the asset list for the row being typed
            self.picks.draw(surface, self.fonts["small"])

    def _draw_nodes(self, surface, body, nodes):
        """The scene as a folder tree, nested by depth."""
        self.node_rows = []
        self.node_toggles = []
        self.nodes_max = max(0, len(nodes) * NODE_ROW + 4 - body.height)
        self.nodes_scroll = max(0, min(self.nodes_max, self.nodes_scroll))
        wide = body.width - (24 if self.nodes_max else 10)
        mouse = pygame.mouse.get_pos()
        old = widgets.clip(surface, body.inflate(-1, -1))
        if old is None:
            return
        y = body.y + 2 - self.nodes_scroll
        for obj, depth, kids in nodes:
            row = pygame.Rect(body.x + 3, y, wide, NODE_ROW)
            if row.bottom > body.y and row.y < body.bottom:
                picked = obj is self.sel or obj in self.sels
                if picked:
                    surface.fill(xp.SELECTION, row)
                elif row.collidepoint(mouse):
                    surface.fill(xp.BTN_HOVER_BG, row)
                self._draw_node_row(surface, row, obj, depth, picked, kids)
            self.node_rows.append((obj, row))
            y += NODE_ROW
        surface.set_clip(old)
        if self.nodes_max > 0:
            frac = self.nodes_scroll / self.nodes_max
            page = body.height / max(1.0, len(nodes) * NODE_ROW)
            xp.scrollbar(surface, pygame.Rect(body.right - 12, body.y + 2,
                                              10, body.height - 4), frac,
                         page)

    def _draw_node_row(self, surface, row, obj, depth, picked, kids):
        """One node: fold triangle, kind picture, name."""
        small = self.fonts["small"]
        key = self._node_key(obj)
        tx = row.x + 3 + depth * 10
        if kids:
            tri = pygame.Rect(tx, row.y + 3, TRI_W - 3, NODE_ROW - 6)
            open_ = key not in self.collapsed
            mid = (tri.centerx, tri.centery)
            if open_:
                pts = [(mid[0] - 3, mid[1] - 2), (mid[0] + 3, mid[1] - 2),
                       (mid[0], mid[1] + 2)]
            else:
                pts = [(mid[0] - 2, mid[1] - 3), (mid[0] + 2, mid[1]),
                       (mid[0] - 2, mid[1] + 3)]
            pygame.draw.polygon(surface, xp.TEXT, pts)
            self.node_toggles.append((key, pygame.Rect(tx, row.y,
                                                       TRI_W, NODE_ROW)))
            tx += TRI_W
        art = widgets.class_icon(type(obj).__name__)
        drew = bool(art) and widgets.draw_icon(
            surface, art, pygame.Rect(tx, row.y + 2, 13, 13))
        tx += 15 if drew else 2
        colour = (255, 255, 255) if picked else xp.TEXT
        name = widgets.elide(small, key.rsplit("/", 1)[-1],
                             row.right - tx - 6)
        img = widgets.cached_text(small, name, colour)
        if img is not None:
            surface.blit(img, (tx, row.centery - img.get_height() // 2))

    def _node_types(self):
        """The types this scene hosts, for the Add list."""
        scene = self.scene
        kind = getattr(scene, "kind", "3d") if scene else "3d"
        family = "3d" if kind == "3d" else "2d"
        base = getattr(scene, "object_base", None)
        out = []
        for row in scenedoc.node_groups():
            keep = []
            for item in row[1]:
                if item[4] != family or item[5] is None:
                    continue
                if base is not None and self.project is not None and \
                        not self.project.node_class(item[0], base):
                    continue
                keep.append(item)
            if keep:
                out.append((row[0], keep))
        return out

    def _picker_rows(self):
        """The Create Node list for this scene's types."""
        rows = []
        for group, items in self._node_types():
            for item in items:
                rows.append((("type", item[0]), item[1], group))
        scene = self.scene
        kind = getattr(scene, "kind", "3d") if scene else "3d"
        family = "3d" if kind == "3d" else "2d"
        for action, label in self.app.doctab._instance_options(family):
            rows.append((("inst", action[len("inst:"):]), label,
                         "Instantiate"))
        return rows

    def instantiate(self, relpath):
        """Place one of the project's files as a child instance.

        On a played-alone map the instance joins the level's own file,
        so a prefab stamped into a room travels with the room.
        """
        project, name = self.project, self.scene_name
        if project is None or name is None:
            return None
        path = scenedoc.resolve_instance(project, relpath)
        if path is None:
            self.app.log(f"cannot find {relpath}", "warn")
            return None
        is_map = self._map_doc_open() is not None
        api = mapdoc if is_map else scenedoc
        doc = (project.map_doc(name) if is_map
               else project.scene_doc(name) or scenedoc.blank_scene(
                   name, self._doc_kind()))
        if doc is None:
            return None
        if not is_map and not doc.get("script"):
            script = project.scene_script(name)
            if script is not None:
                doc["script"] = scenedoc.script_field("scripts/scenes",
                                                      script.name)
        is_scene = path.suffix.lower() == scenedoc.SCENE_EXT
        if is_scene:
            kind = str(scenedoc.load(path, "scene").get("kind")
                       or "scene3d").lower()
            solid = kind not in ("scene2d", "sceneui")
        else:
            solid = scenedoc.type_family(
                str(scenedoc.load(path, "object").get("type")
                    or "").lower()) == "3d"
        label = path.stem
        parent_key = getattr(self.sel, "placed_id", None)
        parent = api.placed(doc, parent_key) if parent_key else None
        index = 0
        while api.placed(
                doc, scenedoc.key(label, index, parent_key)) is not None:
            index += 1
        node_key = scenedoc.key(label, index, parent_key)
        field = "scene" if is_scene else "object"
        entry = {"id": node_key,
                 field: scenedoc.instance_field(relpath),
                 "pos": [0.0, 0.0, 0.0] if solid else [0.0, 0.0]}
        api.add_placed(doc, entry, parent)
        self._save_home(is_map, name, doc)
        if parent is not None:
            self.collapsed.discard(str(parent.get("id")))
        self.sel = None
        self.sel_key = node_key
        self.pending = name          # build it, then pick it out again
        self.app.refresh_tree()
        self.app.log(f"instanced {label} as {node_key}", "ok")
        return entry

    def _shelf_rclick(self, pos):
        """Right-click a node row: Godot's Add Child / Delete menu."""
        for obj, row in self.node_rows:
            if not row.collidepoint(pos):
                continue
            self.select(obj)
            if getattr(obj, "placed_id", None):
                self.node_ctx = []
                self.node_ctx_at = pos
            return True
        return True

    def _draw_node_ctx(self, surface):
        """The shelf's right-click menu: one small panel, two verbs."""
        small = self.fonts["small"]
        items = [("add", "Add Child Node"), ("del", "Delete Node")]
        w = max(small.size(label)[0] for _a, label in items) + 22
        panel = pygame.Rect(self.node_ctx_at[0], self.node_ctx_at[1] + 2,
                            w, NODE_ROW * len(items) + 6)
        if panel.right > self.rect.right - 4:
            panel.right = self.rect.right - 4
        if panel.bottom > self.rect.bottom - 4:
            panel.bottom = self.rect.bottom - 4
        pygame.draw.rect(surface, xp.FIELD, panel)
        xp.sunken(surface, panel)
        mouse = pygame.mouse.get_pos()
        self.node_ctx = []
        y = panel.y + 3
        for action, label in items:
            row = pygame.Rect(panel.x + 2, y, panel.width - 4, NODE_ROW)
            if row.collidepoint(mouse):
                surface.fill(xp.BTN_HOVER_BG, row)
            img = widgets.cached_text(small, label, xp.TEXT)
            if img is not None:
                surface.blit(img, (row.x + 6,
                                   row.centery - img.get_height() // 2))
            self.node_ctx.append((action, row))
            y += NODE_ROW

    def _draw_props(self, surface, body):
        """One line per value; typed ones open a field."""
        small = self.fonts["small"]
        self.props = self._property_rows()
        self.prop_fields = {}
        if not self.props:
            img = widgets.cached_text(small, "select an object",
                                      xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (body.x + 6, body.y + 5))
            return
        old = widgets.clip(surface, body.inflate(-1, -1))
        if old is None:
            return
        y = body.y + 3
        for label, value, key in self.props:
            if y + PROP_ROW > body.bottom:
                break
            row = pygame.Rect(body.x + 4, y, body.width - 8, PROP_ROW)
            img = widgets.cached_text(small, label, xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (row.x,
                                   row.centery - img.get_height() // 2))
            field = pygame.Rect(row.x + LABEL_W, row.y + 1,
                                max(10, row.width - LABEL_W), PROP_ROW - 3)
            if key is None:
                text = widgets.elide(small, value, field.width - 4)
                img = widgets.cached_text(small, text, xp.TEXT)
                if img is not None:
                    surface.blit(img, (field.x + 3,
                                       field.centery - img.get_height() // 2))
            else:
                self.prop_fields[key] = field
                if self.grip is not None and self.grip[0] == key:
                    self.grip[1].draw(surface, field, small, True)
                else:
                    xp.field(surface, field)
                    listed = self._pick_slot(key) is not None
                    room = field.width - (16 if listed else 6)
                    text = widgets.elide(small, value, max(10, room))
                    img = widgets.cached_text(small, text, xp.TEXT)
                    if img is not None:
                        surface.blit(img, (field.x + 3, field.centery -
                                           img.get_height() // 2))
                    if listed:
                        # a row with a list says so, before it is opened
                        ax = field.right - 8
                        pygame.draw.polygon(surface, xp.TEXT_MUTED, (
                            (ax - 4, field.centery - 2),
                            (ax + 4, field.centery - 2),
                            (ax, field.centery + 3)))
            y += PROP_ROW
        surface.set_clip(old)

    def _draw_gizmo(self, surface):
        """The handles for the armed tool, on the selection."""
        obj = self.sel
        if obj is None or not getattr(obj, "alive", True):
            return
        if self.tool == "move":
            for axis, colour, a, b in self._handles():
                self._arm(surface, a, b, colour, axis.upper())
        elif self.tool == "rotate":
            pts = self._ring()
            if self._flat():
                centre = self._to_pixels(obj.pos)
                pygame.draw.circle(surface, (255, 196, 64),
                                   (self.inner.x + int(centre[0]),
                                    self.inner.y + int(centre[1])),
                                   int(HANDLE_PX * 0.9), 1)
            else:
                for i in range(len(pts) - 1):
                    if pts[i] is None or pts[i + 1] is None:
                        continue
                    pygame.draw.line(
                        surface, (255, 196, 64),
                        (self.inner.x + pts[i][0], self.inner.y + pts[i][1]),
                        (self.inner.x + pts[i + 1][0],
                         self.inner.y + pts[i + 1][1]))
        elif self.tool == "scale":
            grip = self._scale_handle()
            if grip is None:
                return
            box = pygame.Rect(0, 0, 9, 9)
            box.center = (self.inner.x + int(grip[0]),
                          self.inner.y + int(grip[1]))
            pygame.draw.rect(surface, (255, 196, 64), box, 1)
            pygame.draw.line(surface, (255, 196, 64), box.center,
                             (box.centerx + 14, box.centery + 14))

    def _arm(self, surface, a, b, colour, label):
        """One arm: dark underline, coloured line, box grip."""
        origin = (self.inner.x + int(a[0]), self.inner.y + int(a[1]))
        tip = (self.inner.x + int(b[0]), self.inner.y + int(b[1]))
        pygame.draw.line(surface, (12, 14, 18), origin, tip, 3)
        pygame.draw.line(surface, colour, origin, tip, 1)
        box = pygame.Rect(0, 0, 11, 11)
        box.center = tip
        pygame.draw.rect(surface, colour, box, 1)
        img = widgets.cached_text(self.fonts["small"], label, colour)
        if img is not None:
            surface.blit(img, (box.right + 2,
                               box.centery - img.get_height() // 2))

    def _draw_spawn(self, surface):
        """The player start: a ring, the way it faces, and its name."""
        mark = self.spawn
        if mark is None:
            return
        if self._flat():
            px, py = self._to_pixels(mark.pos)
            fx, fy = math.cos(mark.yaw) * 16.0, math.sin(mark.yaw) * 16.0
        else:
            got = self.game.camera.project(mark.pos, self.inner.size)
            if got is None:
                return
            px, py = got[0], got[1]
            # the way a player looks from here: (sin yaw, 0, cos yaw)
            ahead = (mark.pos[0] + math.sin(mark.yaw) * 1.2,
                     mark.pos[1], mark.pos[2] + math.cos(mark.yaw) * 1.2)
            tip = self.game.camera.project(ahead, self.inner.size)
            fx, fy = (tip[0] - px, tip[1] - py) if tip else (0.0, -16.0)
        ox, oy = self.inner.x, self.inner.y
        centre = (int(ox + px), int(oy + py))
        pygame.draw.circle(surface, SPAWN_RGB, centre, 11, 2)
        pygame.draw.circle(surface, SPAWN_RGB, centre, 2)
        length = math.hypot(fx, fy)
        if length > 1.0:
            ex, ey = px + fx / length * 21.0, py + fy / length * 21.0
            head = (int(ox + ex), int(oy + ey))
            pygame.draw.line(surface, SPAWN_RGB, centre, head, 2)
            ang = math.atan2(fy, fx)
            for turn in (0.5, -0.5):
                pygame.draw.line(surface, SPAWN_RGB, head,
                                 (int(ox + ex - math.cos(ang - turn) * 7.0),
                                  int(oy + ey - math.sin(ang - turn) * 7.0)),
                                 2)
        img = widgets.cached_text(self.fonts["small"], "player start",
                                  SPAWN_RGB)
        if img is not None:
            surface.blit(img, (centre[0] + 13, centre[1]
                               - img.get_height() - 7))

    def _draw_grid(self, surface):
        """The grid: floor lines, or a sheet in 2D."""
        colour = (58, 64, 72)
        if self._flat():
            view = getattr(self.scene, "view", None)
            if view is None:
                return
            vw, vh = view.view_size()
            c = view.anchor_center()
            x0, y0 = c[0] - vw / 2.0, c[1] - vh / 2.0
            x = math.floor(x0 / GRID_2D) * GRID_2D
            while x <= x0 + vw:
                px = int(self.inner.x + (x - x0) * view.zoom)
                pygame.draw.line(surface, colour, (px, self.inner.y),
                                 (px, self.inner.bottom))
                x += GRID_2D
            y = math.floor(y0 / GRID_2D) * GRID_2D
            while y <= y0 + vh:
                py = int(self.inner.y + (y - y0) * view.zoom)
                pygame.draw.line(surface, colour, (self.inner.x, py),
                                 (self.inner.right, py))
                y += GRID_2D
            return
        cam = self.game.camera
        size = self.inner.size
        cx = round(cam.eye[0] / GRID_3D) * GRID_3D
        cz = round(cam.eye[2] / GRID_3D) * GRID_3D
        reach = GRID_3D * 6.0
        for i in range(-6, 7):
            for a, b in (((cx + i * GRID_3D, 0.0, cz - reach),
                          (cx + i * GRID_3D, 0.0, cz + reach)),
                         ((cx - reach, 0.0, cz + i * GRID_3D),
                          (cx + reach, 0.0, cz + i * GRID_3D))):
                pa, pb = cam.project(a, size), cam.project(b, size)
                if pa is None or pb is None:
                    continue
                pygame.draw.line(surface, colour,
                                 (self.inner.x + pa[0], self.inner.y + pa[1]),
                                 (self.inner.x + pb[0],
                                  self.inner.y + pb[1]))

    def _draw_shapes(self, surface):
        """Every shape the scene filed, as a wireframe."""
        scene = self.scene
        if scene is None or not self.show_shapes:
            return
        nodes = [node for node in getattr(scene, "colliders", ())
                 if getattr(node, "alive", True)]
        if not nodes:
            return
        if self._flat():
            self._draw_shapes2d(surface, nodes)
            return
        cam = self.game.camera
        size = self.inner.size
        for node in nodes:
            box = getattr(node, "box", None)
            if not callable(box):
                continue
            centre, half = box()
            colour = self._shape_colour(node)
            shape = str(getattr(node, "shape", "box") or "box")
            if shape == "box":
                pts = []
                for sx, sy, sz in BOX_SIGNS:
                    pts.append(cam.project((centre[0] + sx * half[0],
                                            centre[1] + sy * half[1],
                                            centre[2] + sz * half[2]), size))
                for a, b in BOX_EDGES:
                    self._line(surface, pts[a], pts[b], colour)
                continue
            r = max(half[0], half[2])
            span = max(0.0, half[1] - r) if shape == "capsule" else 0.0
            for y in ((centre[1] - span, centre[1] + span) if span > 1e-3
                      else (centre[1],)):
                self._loop(surface, self._circle(cam, size, (centre[0], y,
                                                             centre[2]),
                                                 r, "xz"), colour)
            if span > 1e-3:
                for dx in (-r, r):
                    self._line(surface,
                               cam.project((centre[0] + dx,
                                            centre[1] - span, centre[2]),
                                           size),
                               cam.project((centre[0] + dx,
                                            centre[1] + span, centre[2]),
                                           size), colour)
            elif shape == "sphere":
                for plane in ("xy", "yz"):
                    self._loop(surface, self._circle(cam, size, centre, r,
                                                     plane), colour)

    def _shape_colour(self, node):
        """Solid shapes keep the gizmo blue; triggers go warm."""
        if not bool(getattr(node, "solid", True)):
            rgb = TRIGGER_RGB
        else:
            base = getattr(type(node), "GIZMO", None) or (0.24, 0.62, 0.94)
            rgb = tuple(int(round(c * 255.0)) for c in base)
        if node is self.sel or node in self.sels:
            return rgb
        return tuple(int(c * 0.6) for c in rgb)

    def _circle(self, cam, size, centre, radius, plane):
        """A projected circle; `plane` picks its two axes."""
        pts = []
        for i in range(RING_SEG + 1):
            a = i * 2.0 * math.pi / RING_SEG
            ca, sa = math.cos(a) * radius, math.sin(a) * radius
            if plane == "xz":
                p = (centre[0] + ca, centre[1], centre[2] + sa)
            elif plane == "xy":
                p = (centre[0] + ca, centre[1] + sa, centre[2])
            else:
                p = (centre[0], centre[1] + sa, centre[2] + ca)
            pts.append(cam.project(p, size))
        return pts

    def _loop(self, surface, pts, colour):
        """A circle drawn as a ring, never a face."""
        for i in range(len(pts) - 1):
            self._line(surface, pts[i], pts[i + 1], colour)

    def _line(self, surface, a, b, colour):
        """One segment between two projected points, in window pixels."""
        if a is None or b is None:
            return
        pygame.draw.line(surface, colour,
                         (self.inner.x + int(a[0]), self.inner.y + int(a[1])),
                         (self.inner.x + int(b[0]), self.inner.y + int(b[1])))

    def _draw_shapes2d(self, surface, nodes):
        """A flat shape's box is a rectangle."""
        for node in nodes:
            rect = self._world_rect(node)
            if rect is None:
                continue
            a = self._to_pixels((rect.x, rect.y))
            b = self._to_pixels((rect.right, rect.bottom))
            box = pygame.Rect(0, 0, max(3, int(abs(b[0] - a[0]))),
                              max(3, int(abs(b[1] - a[1]))))
            box.topleft = (self.inner.x + int(min(a[0], b[0])),
                           self.inner.y + int(min(a[1], b[1])))
            pygame.draw.rect(surface, self._shape_colour(node), box, 1)

    def _hint(self):
        """The corner line: what the current mode takes."""
        if self.focus_mode:
            return "mouse turns the view  keys drive it  Esc releases"
        if self.mode == "edit":
            what = {"move": "drag to move, shift-drag vertical, "
                         "shift-click to add",
                    "rotate": "drag the ring to turn",
                    "scale": "drag the grip to size"}.get(self.tool,
                                                          "click to pick")
            lit = "lights on" if self.light_view else "full bright"
            if getattr(self.scene, "kind", "3d") == "3d":
                return (f"{self.tool}  RMB look  WASD fly  shift fast  "
                        f"{lit}  {what}")
            return f"{self.tool}  RMB pan  wheel zoom  {lit}  {what}"
        return "RMB look  WASD move  R reload"

    def _draw_selection(self, surface, area):
        """Mark every picked object and name the primary."""
        scene = self.scene
        flat = getattr(scene, "kind", "3d") != "3d"
        for obj in self.sels or ([self.sel] if self.sel else []):
            if obj is None or not getattr(obj, "alive", True):
                continue
            at = self._draw_pick_mark(surface, area, obj, flat)
            if obj is self.sel and at is not None:
                self._draw_pick_label(surface, at, obj)

    def _draw_pick_mark(self, surface, area, obj, flat):
        """Draw one object's marker; hand back where its label goes."""
        colour = (255, 196, 64)
        if not flat:
            got = self.game.camera.project(obj.pos, area.size)
            if got is None:
                return None
            mark = pygame.Rect(0, 0, 15, 15)
            mark.center = (area.x + int(got[0]), area.y + int(got[1]))
            pygame.draw.rect(surface, colour, mark, 1)
            pygame.draw.line(surface, colour, (mark.centerx - 10,
                                               mark.centery),
                             (mark.centerx + 10, mark.centery))
            pygame.draw.line(surface, colour, (mark.centerx,
                                               mark.centery - 10),
                             (mark.centerx, mark.centery + 10))
            return (mark.right + 6, mark.top)
        rect = self._world_rect(obj)
        if rect is None:
            return None
        # a world rect becomes screen once ortho is undone
        view = self.scene.view
        vw, vh = view.view_size()
        centre = view.anchor_center()
        left = area.x + (rect.x - (centre[0] - vw / 2.0)) * view.zoom
        top = area.y + (rect.y - (centre[1] - vh / 2.0)) * view.zoom
        box = pygame.Rect(int(left) - 1, int(top) - 1,
                          int(rect.width * view.zoom) + 2,
                          int(rect.height * view.zoom) + 2)
        pygame.draw.rect(surface, colour, box, 1)
        return (box.left, box.top - 16)

    def _draw_pick_label(self, surface, at, obj):
        """The picked node's name and place, beside its marker."""
        name = "player start" if getattr(obj, "is_spawn", False) \
            else getattr(obj, "doc_key", None) or type(obj).__name__
        extra = f"  +{len(self.sels) - 1} more" if len(self.sels) > 1 else ""
        words = f"{name}  " + "  ".join(f"{c:.2f}" for c in obj.pos) + extra
        img = widgets.cached_text(self.fonts["small"], words,
                                  (255, 214, 140))
        surface.blit(img, at)

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

    def info(self):
        names = self.scene_names()
        sel = self.sel
        out = [
            ("Scene", self.scene_name or self.selected or "-"),
            ("Map", self.map_name or "-"),
            ("Scenes", ", ".join(names) if names else "-"),
            ("Mode", "edit" if self.mode == "edit" else "game"),
            ("Tool", self.tool if self.mode == "edit" else "-"),
            ("Lighting", "the scene's own" if self.light_view
             else "full bright"),
            ("Focus", "viewport" if self.focus_mode else "editor"),
            ("Selected", (getattr(sel, "doc_key", None)
                          or type(sel).__name__) if sel is not None
             else "-"),
            ("State", "stopped" if not self.started else
             "paused" if self.paused else
             "error" if self.error else "running"),
            ("Draw calls", str(len(self.renderer.groups))
             if self.renderer else "0"),
        ]
        if self.scene is not None:
            kind = getattr(self.scene, "kind", "3d")
            out += [
                ("Kind", kind),
                ("Camera", getattr(self.scene, "camera", "ortho")),
                ("Objects", str(len(getattr(self.scene, "objects", ())))),
                ("Lights", str(len(self.scene.lights))),
                ("Eye", "%.1f %.1f %.1f" % tuple(self.game.eye)),
                ("View", "fov %.0f  roll %.2f" % (
                    self.game.camera.fov, self.game.camera.view_roll())),
            ]
        return out
