"""The Model tab: a turntable viewport for model files."""

import copy
import math
from pathlib import Path

import numpy as np
import pygame

from ..engine import (colors, meshes, model as modelmod, proctex,
                      scenedoc, xp)
from ..engine.camera import OrbitCamera
from ..engine.game import builtin_sheet, register_builtin_textures
from ..engine.renderer import Renderer
from . import uvpaint, widgets

TOOL_H = 26              # the name row under the captioned bands
AXIS_VECTORS = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0),
                "z": (0.0, 0.0, 1.0)}
MODES = (("object", "Object"), ("vertex", "Vertex"), ("face", "Face"))
PRIMITIVES = (("box", "Box"), ("wedge", "Wedge"), ("cylinder", "Cyl"),
              ("cone", "Cone"), ("plane", "Plane"), ("sphere", "Sphere"))
# the tab's two half names, shared with the picker
UI_MODES = (("edit", "Edit"), ("texture", "Texture"), ("uv", "UV Paint"))
PALETTE_W = 186          # the texture shelf, only in texture mode
OBJ_W = 186              # the objects rail, only in 3D edit mode
OBJ_ROW = 22             # one object row in that rail
SWATCH = 26              # thumbnail size in the palette
SWATCH_ROW = 32          # one swatch row, thumbnail plus its name
SHELF_TAB = 20          # the shelf's Sheets / Settings strip
SHELF_CAP = 15          # a section line inside the shelf's sheet list
SHELF_ROW = 18           # one field row in the shelf's Settings block
# per-sheet image options; `mipmaps` is the bool
SHEET_CHOICE = {"filter": ("linear", "nearest"),
                "wrap": ("repeat", "clamp"),
                "mipmaps": ("on", "off")}
SHEET_PROPS = (("filter", "filter"), ("mipmaps", "mips"), ("wrap", "wrap"))
# the number option: world metres one sheet repeat covers
SHEET_NUM_PROPS = (("tile", "tile m"),)
# every image option a sheet can be filed under
SHEET_WORDS = ("filter", "wrap", "mipmaps", "tile")
# the model's own uv block, one field per number
TILING_PROPS = (("uv_scale", "scale x", 0), ("uv_scale", "scale y", 1),
                ("uv_offset", "offset x", 0), ("uv_offset", "offset y", 1),
                ("uv_rot", "rot deg", None))
PART_W = 186             # the parts/properties panel, only in flat mode
PART_ROW = 20            # one part row in that list
FLAT_PROP_ROW = 18       # one rig or part field row
FLAT_MIN = 0.1           # the zoom a flat viewport cannot leave
FLAT_MAX = 16.0
FLAT_PROPS = (("name", "name", "text"), ("texture", "texture", "enum"),
              ("uv", "uv", "vec"), ("pos", "pos x", "num"),
              ("pos", "pos y", "num"), ("rot", "rot", "num"),
              ("scale", "scale x", "num"), ("scale", "scale y", "num"),
              ("parent", "parent", "enum"), ("visible", "visible",
                                             "bool"))
UV_DEFAULT = (0.0, 0.0, 1.0, 1.0)
POS_DEFAULT = (0.0, 0.0)
SCALE_DEFAULT = (1.0, 1.0)
# the gizmo's three move arms, in the scene tab's colours
AXES = {"x": (204, 84, 74), "y": (98, 176, 96), "z": (88, 132, 214)}
GIZ_PX = 54.0            # how long a vertex arm draws on screen
GRAB_PX = 8.0            # how close a click must be to take an arm


class _Studio:
    """Render settings for the model viewport."""

    clear_color = (0.075, 0.082, 0.10)
    fog_color = (0.085, 0.092, 0.115)
    fog_near = 35.0
    fog_far = 160.0
    ambient = (0.58, 0.58, 0.62)
    sun_dir = (0.45, 0.85, 0.30)
    sun_col = (0.72, 0.68, 0.60)
    fov = 55.0
    lights = [{"pos": (3.2, 5.0, 2.4), "color": (0.50, 0.46, 0.40)}]


def _seg_distance(px, py, a, b):
    """Pixel distance to a segment, for grabbing an arm."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    denom = dx * dx + dy * dy
    t = 0.0 if denom <= 0.0 else \
        ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def _bounds_hit(b1, b2):
    """Do two corner boxes overlap on all three axes?"""
    if b1 is None or b2 is None:
        return False
    lo1, hi1 = b1
    lo2, hi2 = b2
    return all(lo1[k] <= hi2[k] and lo2[k] <= hi1[k] for k in range(3))


def _has_holes(img):
    """Does a picture carry empty pixels the renderer will drop?"""
    if not img.get_flags() & pygame.SRCALPHA:
        return False
    try:
        arr = pygame.surfarray.pixels_alpha(img)
    except pygame.error:
        return False
    try:
        return bool(arr.min() < 250)
    finally:
        del arr


def _over_checker(img):
    """Lay a cut-out over a checker, so its holes read as holes."""
    w, h = img.get_size()
    cell = max(4, min(w, h) // 4)
    got = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            tone = (58, 62, 72) if (x // cell + y // cell) % 2 else (42, 46, 54)
            pygame.draw.rect(got, tone, (x, y, cell, cell))
    got.blit(img, (0, 0))
    return got


class ModelEditor:
    """Vertex/face editor for one .model3d, cutout-rig editor for one"""

    def __init__(self, app):
        self.app = app
        self.font = app.fonts["normal"]
        self.small = app.fonts["small"]
        self.renderer = None
        self.render_size = (0, 0)
        self.studio = _Studio()
        self.orbit = OrbitCamera()
        self.model = None
        self.path = None
        self.meshes = []
        self.dirty = False
        self.name_field = widgets.TextField("model", 32)
        self.name_focus = False
        self.mode = "vertex"
        self.ui_mode = "edit"       # "edit" shapes, "texture" paints
        self.uvpaint = None         # the paint session, made on 'uv' entry
        self._uvpaint_sessions = {}
        self._paint_preview_key = "__model_paint_preview__"
        self._paint_preview_revision = -1
        self.paint_key = None       # the sheet the palette picked
        self.paint_on = True        # a click fills the face under it
        self.paint_all = False      # ...or the whole model at once
        self.axis = None
        self.snap = True
        self.snap_step = 0.25
        self.wire = True
        self.sel_verts = set()
        self.sel_face = None
        self.sel_faces = set()     # extra faces Shift adds to the pick
        self.sel_obj = None        # the primary object of a parted model
        self.sel_objs = []         # the picked objects, primary last
        self.is_map = False        # the open file is a maps/*.map3d
        self.obj_rect = pygame.Rect(0, 0, 0, 0)   # the objects rail
        self.obj_body = pygame.Rect(0, 0, 0, 0)   # its scrolling list
        self.obj_rows = []         # (name, rect) the rail drew
        self.obj_scroll = 0
        self.obj_add_rect = pygame.Rect(0, 0, 0, 0)
        self.obj_merge_rect = pygame.Rect(0, 0, 0, 0)
        self.rename_obj = None     # the object name being retyped
        self.obj_field = widgets.TextField("", 32)
        self.obj_focus = False
        self._last_obj = (None, 0)   # (name, ticks) for a double click
        self.hover_vert = None
        self.undo = []
        self.redo = []
        self.buttons = []
        self.bands = []             # the toolbar's captioned bands
        self.bands_h = 0            # how tall those bands came out
        self.band_scroll = 0        # a stack too tall to show scrolls
        self.band_max = 0
        self.band_rows = []         # the height of each toolbar row
        self.name_from = 0          # where the name row starts in `buttons`
        self.bar_rect = pygame.Rect(0, 0, 0, 0)
        self.toolbar_h = 0          # bands plus the name row
        self.hint_x = 0             # where the name row's hint may start
        self.viewport = pygame.Rect(0, 0, 0, 0)
        self.inner = pygame.Rect(0, 0, 0, 0)
        self.name_rect = pygame.Rect(0, 0, 0, 0)
        self.drag = None
        self.message = ""
        self.color_rect = pygame.Rect(0, 0, 0, 0)
        self.palette_rect = pygame.Rect(0, 0, 0, 0)
        self.palette_rows = []      # (key, rect) down the shelf
        self.palette_scroll = 0
        self.palette_max = 0
        self.apply_rect = pygame.Rect(0, 0, 0, 0)
        self.paint_rect = pygame.Rect(0, 0, 0, 0)
        self.palette_body = pygame.Rect(0, 0, 0, 0)
        self.palette_tab = "sheets"     # "sheets" list, "settings" fields
        self.sheets_tab = pygame.Rect(0, 0, 0, 0)
        self.settings_tab = pygame.Rect(0, 0, 0, 0)
        self.tex_fields = []        # (spec, rect) the Settings block drew
        self.hover_face = None
        self._thumbs = {}           # (key, px) -> a scaled preview
        self.model2d = None
        self.sel_part = None        # index into model2d.parts
        self.sel_parts = []         # the picked set, primary last
        self.flat_view = {"cx": 0.0, "cy": 0.0, "zoom": 3.0}
        self.playing = False
        self.play_t = 0.0
        self._play_at = 0           # ticks at the last animation step
        self._sheet = {}            # texture key -> the full-size surface
        self.grip = None            # (spec, TextField) while a field types
        self.popup = None           # {"x","y","items","target"}
        self.popup_rows = []
        self.part_rows = []         # (index, rect) the panel drew
        self.prop_fields = []       # (spec, rect) the panel drew
        self.panel_rect = pygame.Rect(0, 0, 0, 0)
        self.parts_body = pygame.Rect(0, 0, 0, 0)
        self.props_body = pygame.Rect(0, 0, 0, 0)
        self.parts_scroll = 0
        self.props_scroll = 0
        self.part_add_rect = pygame.Rect(0, 0, 0, 0)
        self.part_duplicate_rect = pygame.Rect(0, 0, 0, 0)
        self.part_delete_rect = pygame.Rect(0, 0, 0, 0)

    def use_fonts(self, fonts):
        """Re-adopt the app fonts after a size change."""
        self.font = fonts["normal"]
        self.small = fonts["small"]

    def _flat_path(self, path):
        """Is this name in the flat half of the format?"""
        return Path(str(path)).suffix.lower() == ".model2d"

    def _document(self):
        """Whichever document the tab is holding, 3D or flat."""
        return self.model2d if self.model2d is not None else self.model

    def open(self, path):
        """Read a model file; the suffix picks the mode."""
        try:
            flat = self._flat_path(path)
            if flat:
                doc = modelmod.Model2D.load(path)
            else:
                doc = modelmod.Model.load(path)
        except Exception as exc:
            self.app.log(f"cannot open {Path(path).name}: {exc}", "error")
            return False
        if self.model2d is not None or flat:
            # flat mode drops the 3D document and its gear
            self.close_model()
        if flat:
            self.model2d = doc
            self.path = str(doc.path)
            self.name_field.set(doc.name)
            self.sel_part = 0 if doc.parts else None
            self.sel_parts = [0] if doc.parts else []
            self.flat_view = {"cx": 0.0, "cy": 0.0, "zoom": 3.0}
            self.playing = False
            self.play_t = 0.0
            self._play_at = 0
            self.grip = self.popup = None
            self.parts_scroll = self.props_scroll = 0
            self.undo.clear()
            self.redo.clear()
            self.dirty = False
        else:
            self.model = doc
            self.path = str(doc.path)
            self.is_map = Path(str(doc.path)).suffix.lower() == \
                scenedoc.MAP3D_EXT
            self.name_field.set(doc.name)
            self.paint_key = doc.texture
            self.uvpaint = None
            self._uvpaint_sessions.clear()
            self.sel_verts.clear()
            self.sel_face = None
            self.sel_faces.clear()
            self.sel_obj = None
            self.sel_objs = []
            self.rename_obj = None
            self.obj_scroll = 0
            self._sync_obj_pick()
            self.hover_vert = None
            self.undo.clear()
            self.redo.clear()
            self.dirty = False
            self.orbit.frame(doc.bounds())
            self._refresh_mesh()
        self.message = f"opened {self.app.project.relative(self.path)}"
        self.app.log(f"opened {self.app.project.relative(self.path)}"
                     f" ({'2D rig' if flat else 'model'})", "muted")
        return True

    def save(self):
        if self.model2d is not None:
            return self._save_flat()
        if self.model is None:
            return False
        name = (self.name_field.text or self.model.name or "model").strip()
        stem = Path(name).stem or "model"
        for session in self._uvpaint_sessions.values():
            if not session.has_edits and not (
                    session is self.uvpaint and
                    self.ui_mode == "uv"):
                continue
            if not session.commit_to_model(stem):
                return False
            if session is self.uvpaint:
                self._paint_preview_revision = (
                    id(session), session.revision, session.objname)
        try:
            if self.is_map:
                path = self.app.project.store_map(self.model, stem)
            else:
                path = self.app.project.store_model(self.model, stem)
        except Exception as exc:
            self.app.log(f"save failed: {exc}", "error")
            return False
        self.model.name = stem
        self._after_save(stem, path)
        return True

    def _save_flat(self):
        """Write the rig through the project, cache included."""
        name = (self.name_field.text or self.model2d.name
                or "model2d").strip()
        stem = Path(name).stem or "model2d"
        try:
            path = self.app.project.store_model2d(self.model2d, stem)
        except Exception as exc:
            self.app.log(f"save failed: {exc}", "error")
            return False
        self._after_save(stem, path)
        return True

    def _after_save(self, stem, path):
        was = self.path
        if self.model2d is not None:
            self.model2d.name = stem
        self.path = str(path)
        self.name_field.set(stem)
        self.dirty = False
        self.app.log(f"saved {self.app.project.relative(path)}", "ok")
        # a save that moved the document - a new name, or model to map -
        # leaves no second copy of it behind
        self._drop_old(was, path)
        self.app.refresh_tree()

    def _drop_old(self, was, path):
        """Delete the file this document used to live in, if it moved."""
        project = self.app.project
        if not was or not path or project is None or \
                str(was) == str(path) or not Path(str(was)).is_file():
            return
        home = (Path(project.models_dir).resolve(),
                Path(project.maps_dir).resolve())
        old = Path(str(was)).resolve()
        if old.parent not in home:
            return
        try:
            old.unlink()
        except OSError as exc:
            self.app.log(f"old file kept: {exc}", "warn")
            return
        project.reload_models()
        self.app.log(f"moved off {project.relative(old)}", "muted")

    def autosave(self):
        if self._document() is not None and self.dirty:
            self.save()

    def close_model(self):
        """Drop whatever document the tab holds, in either mode."""
        self._drop_meshes()
        self.model = None
        self.model2d = None
        self.path = None
        self.uvpaint = None
        self._uvpaint_sessions.clear()
        self.sel_verts.clear()
        self.sel_face = None
        self.sel_faces.clear()
        self.sel_obj = None
        self.sel_objs = []
        self.rename_obj = None
        self.obj_scroll = 0
        self.is_map = False
        self.sel_part = None
        self.sel_parts = []
        self.grip = self.popup = None
        self.name_focus = False
        self.playing = False
        self.dirty = False

    def new_model2d(self):
        """A blank rig: one 'body' part covering the whole sheet."""
        self.autosave()        # a button press must not eat unsaved edits
        self.close_model()
        doc = modelmod.new_model2d("rig")
        self.model2d = doc
        self.name_field.set(doc.name)
        self.sel_part = 0
        self.sel_parts = [0]
        self.flat_view = {"cx": 0.0, "cy": 0.0, "zoom": 3.0}
        self.playing = False
        self.play_t = 0.0
        self.undo.clear()
        self.redo.clear()
        self.dirty = True
        self.message = "new 2D rig - add parts, then Save"

    def refresh_textures(self):
        # a new project or re-imported image stales every preview
        self._thumbs.clear()
        if self.renderer is not None and self.app.project is not None:
            try:
                register_builtin_textures(self.renderer, self.app.project)
                self.app.project.register_textures(self.renderer)
            except Exception as exc:
                self.app.log(f"textures: {exc}", "warn")

    def new_model(self, kind="box"):
        self.autosave()        # a button press must not eat unsaved edits
        model = modelmod.new_model(kind, 1.0, texture="grid", name=kind)
        self._adopt(model)
        self.message = f"new {kind} - edit it, then Save"
        return model

    def new_map(self, kind="box"):
        """A fresh map: one primitive as a named object."""
        self.autosave()
        model = modelmod.new_model(kind, 4.0, texture="grid", name="map")
        self._adopt(model)
        self.is_map = True
        self._wrap_object(kind)
        self.message = f"new map ({kind}) - split into objects, then Save"
        return model

    def _free_name(self, want):
        """`want`, given a suffix if the model already calls a part that."""
        got = set(self.model.object_names()) if self.model is not None \
            else set()
        n, name = 1, str(want)
        while name in got:
            n += 1
            name = f"{want}{n}"
        return name

    def _wrap_object(self, want, faces=None):
        """File faces as one new object; all of them by default."""
        if self.model is None:
            return None
        mine = set(range(len(self.model.tris))) if faces is None \
            else {int(f) for f in faces}
        if not mine:
            return None
        # align_objects hands any unclaimed face to the first object, so a
        # shape that file already swallowed has to be taken back first
        for o in self.model.objects:
            o["faces"] = [f for f in o["faces"] if f not in mine]
        entry = {"name": self._free_name(want), "faces": sorted(mine),
                 "texture": None, "painted": False, "lightmap": None}
        self.model.objects = [o for o in self.model.objects if o["faces"]] \
            + [entry]
        self.model.align_objects()
        self._sync_obj_pick()
        return entry

    def _adopt(self, model):
        self.model = model
        self.path = None
        self.is_map = False
        self.paint_key = model.texture
        self.uvpaint = None
        self._uvpaint_sessions.clear()
        self.undo.clear()
        self.redo.clear()
        self.orbit.frame(model.bounds())
        self.sel_verts.clear()
        self.sel_face = None
        self.sel_faces.clear()
        self.sel_obj = None
        self.sel_objs = []
        self.rename_obj = None
        self.obj_scroll = 0
        self._sync_obj_pick()
        self.dirty = True
        self.name_field.set(self.model.name)
        self._refresh_mesh()

    def set_ui_mode(self, mode):
        """Switch the tab between shaping geometry and painting sheets."""
        if mode == self.ui_mode or self.model2d is not None:
            return
        self.ui_mode = mode
        self.name_focus = False
        self.drag = None
        self.sel_face = None
        self.sel_faces.clear()
        if mode == "texture":
            self.sel_verts.clear()
            if self.paint_key is None and self.model is not None:
                # start on the sheet the model already draws with
                self.paint_key = self.model.texture
            self.message = "texture mode - pick a sheet, then fill faces"
        elif mode == "uv":
            # a paint session is one model's; lay the atlas out
            self.sel_verts.clear()
            if self.model is None:
                self.message = "uv paint needs a model"
            else:
                target = self.sel_obj if self.model.has_objects else None
                self.uvpaint = self._uvpaint_for(target)
                if self.uvpaint.ensure_unwrapped():
                    self.message = "uv paint - draw the atlas, then Save"
                else:
                    self.message = self.uvpaint.message or "nothing to unwrap"
        else:
            self.message = "edit mode - shapes and vertices"

    def _uvpaint_for(self, objname):
        key = (id(self.model), objname)
        session = self._uvpaint_sessions.get(key)
        if session is None:
            session = uvpaint.UVPaint(self, self.model)
            session.objname = objname
            self._uvpaint_sessions[key] = session
        return session

    def pick_paint_color(self, session):
        """Choose the active UV brush colour."""
        current = "#" + "".join(f"{int(c):02x}" for c in session.color[:3])

        def apply(value):
            got = colors.rgba(value)
            if got is None:
                self.message = "not a paint colour"
                return
            session.color = [round(channel * 255) for channel in got]
            session.message = "paint colour changed"

        self.app.pick_color("Paint colour", current, apply,
                            hint="Choose a colour for the UV brush.",
                            allow_none=False)

    def uv_pick_texture(self, session):
        """The paint toolbar's 'sheet' button: add a textures/ sheet layer."""
        keys = [k for k in self.texture_keys()
                if self._texture_path(k) is not None]
        if not keys:
            self.message = "no textures/ sheets to add"
            return
        self.popup = {"x": 0, "y": 0,
                      "items": [(k, k) for k in keys],
                      "target": ("uvtex", session)}
        for b in getattr(session, "buttons", []):
            if b["action"] == ("sheet", None):
                self.popup["x"] = b["rect"].x
                self.popup["y"] = b["rect"].bottom
                break

    def add_primitive(self, kind):
        if self.model2d is not None:
            self.message = "this is a 2D rig - use Add Part"
            return
        if self.model is None:
            self.new_model(kind)
            return
        self._push_undo()
        b = self.model.bounds()
        # set the new shape beside the old one
        off = (b[1][0] + 1.0, 0.0, 0.0) if b else (0.0, 0.0, 0.0)
        before = len(self.model.tris)
        self.model.add_primitive(kind, 1.0, offset=off)
        # the new shape brings its own per-metre unwrap, so nothing is
        # re-projected here: a whole-model pass would squeeze its narrow
        # faces into a slice of the picture
        # a map is a list of objects, so a new shape is one of its own
        made = None
        if self.is_map and len(self.model.tris) > before:
            entry = self._wrap_object(kind,
                                      range(before, len(self.model.tris)))
            made = entry["name"] if entry else None
        self.dirty = True
        self._refresh_mesh()
        self.message = f"added {kind}" + (f" as {made}" if made else "")

    def cycle_texture(self, step):
        if self.model is None or self.model2d is not None:
            return
        names = self.texture_names()
        if not names:
            return
        try:
            i = names.index(self.model.texture)
        except ValueError:
            i = 0
        self.model.texture = names[(i + step) % len(names)]
        self.dirty = True
        self._refresh_mesh()

    def texture_names(self):
        """The sheets `<` and `>` walk through."""
        if self.renderer is None:
            return ["white"]
        names = sorted(k for k in self.renderer.textures
                       if k != "white" and not k.startswith("#") and
                       not str(k).startswith("__model_paint_preview__"))
        return ["white"] + names

    def texture_keys(self):
        """Every sheet the palette offers: the built-ins, then textures/*."""
        keys = ["white"] + [name for name, _make, _opts in proctex.BUILTIN]
        project = self.app.project
        if project is not None:
            for path in project.texture_files():
                if path.stem not in keys:
                    keys.append(path.stem)
        return keys

    def _sheet_use(self):
        """How many faces, or rig parts, each sheet is worn by."""
        out = {}
        if self.model2d is not None:
            for part in self.model2d.parts:
                key = part.get("texture") or self.model2d.texture or "white"
                out[key] = out.get(key, 0) + 1
            return out
        if self.model is None:
            return {}
        model = self.model
        tags = model.align_tex()
        owner = {}
        for entry in model.objects:
            if entry.get("texture"):
                for face in entry["faces"]:
                    owner[face] = entry["texture"]
        for face in range(len(model.tris)):
            tag = tags[face] if face < len(tags) else None
            key = owner.get(face) or tag or model.texture or "white"
            if colors.is_spelling(key):
                continue        # a colour is not a sheet on the shelf
            out[key] = out.get(key, 0) + 1
        return out

    def _texture_path(self, key):
        """The file behind a palette key, or None."""
        project = self.app.project
        if project is None:
            return None
        for ext in (".png", ".jpg", ".jpeg"):
            path = project.textures_dir / f"{key}{ext}"
            if path.is_file():
                return path
        return None

    def _thumb(self, key, px):
        """A preview of a sheet, built once and reused."""
        got = self._thumbs.get((key, px))
        if got is not None:
            return got
        surf = None
        path = self._texture_path(key)
        if path is not None:
            try:
                surf = pygame.image.load(str(path))
            except (pygame.error, OSError):
                surf = None
        elif key == "white":
            surf = pygame.Surface((8, 8))
            surf.fill((255, 255, 255))
        else:
            arr = proctex.build(key)
            if arr is not None:
                surf = pygame.image.frombuffer(
                    arr.tobytes(), (arr.shape[1], arr.shape[0]),
                    "RGBA" if arr.shape[2] == 4 else "RGB")
        if surf is None:
            return None
        got = pygame.transform.smoothscale(surf, (px, px))
        if _has_holes(got):
            # a cut-out is shown over a checker, so its blank areas read as
            # the holes the renderer drops rather than as a black square
            got = _over_checker(got)
        self._thumbs[(key, px)] = got
        return got

    # a `.model2d` edits here, in rig pixels
    def get_part(self, index=None):
        """The picked part's dict, or an empty one."""
        if self.model2d is None:
            return {}
        i = self.sel_part if index is None else index
        if i is None or not 0 <= i < len(self.model2d.parts):
            return {}
        return self.model2d.parts[i]

    def _sheet_surf(self, key):
        """A full-size sheet, loaded once per key."""
        if not key or colors.is_spelling(key):
            return None
        got = self._sheet.get(key)
        if got is not None:
            return got
        path = self._texture_path(key)
        surf = None
        if path is not None:
            try:
                surf = pygame.image.load(str(path))
            except (pygame.error, OSError):
                surf = None
        elif key == "white":
            surf = pygame.Surface((8, 8))
            surf.fill((255, 255, 255))
        else:
            arr = proctex.build(key)
            if arr is not None:
                surf = pygame.image.frombuffer(
                    arr.tobytes(), (arr.shape[1], arr.shape[0]),
                    "RGBA" if arr.shape[2] == 4 else "RGB")
        self._sheet[key] = surf
        return surf

    def _part_scale(self, part):
        s = part.get("scale") or SCALE_DEFAULT
        if isinstance(s, (int, float)):
            return (float(s), float(s))
        return (float(s[0]), float(s[1]))

    def _part_shown(self, part):
        return part.get("visible", True) is not False

    def _part_world(self, part, t=None):
        """A part's centre in rig pixels, after the rig turn."""
        p = part.get("pos") or POS_DEFAULT
        return (self.model2d.size[0] * (0.5 - self.model2d.pivot[0]) +
                float(p[0]),
                self.model2d.size[1] * (0.5 - self.model2d.pivot[1]) +
                float(p[1]))

    def _to_local(self, x, y):
        z = self.flat_view["zoom"]
        return ((x - self.inner.centerx) / z + self.flat_view["cx"],
                (y - self.inner.centery) / z + self.flat_view["cy"])

    def _to_world(self, x, y):
        z = self.flat_view["zoom"]
        return ((x - self.inner.centerx) * z + self.flat_view["cx"],
                (y - self.inner.centery) * z + self.flat_view["cy"])

    def _rig_rot(self):
        """The whole rig turned by the name field's arrow."""
        try:
            return math.radians(float(self.name_field.text or 0.0))
        except ValueError:
            return 0.0

    def _rig_origin(self):
        """The rig box's top-left in local pixels."""
        m = self.model2d
        c, s = math.cos(self._rig_rot()), math.sin(self._rig_rot())
        px = m.size[0] * m.pivot[0] - m.size[0] / 2.0
        py = m.size[1] * m.pivot[1] - m.size[1] / 2.0
        return (self.flat_view["cx"] - px * c + py * s,
                self.flat_view["cy"] - px * s - py * c)

    def _world_of(self, part, t=None):
        """Where a part's centre sits, in viewport-local pixels."""
        w = self._part_world(part, t)
        rot = self._rig_rot()
        c, s = math.cos(rot), math.sin(rot)
        ox, oy = self._rig_origin()
        lx = ox + self.flat_view["zoom"] * (w[0] * c - w[1] * s)
        ly = oy + self.flat_view["zoom"] * (w[0] * s + w[1] * c)
        return (lx, ly, rot + self._part_eff_rot(part, t if t is not None
                                                 else self.play_t))

    def _corner_local(self, w, h, u, v, centre, prot):
        """One uv corner of a part, in viewport-local pixels."""
        lx = (u - 0.5) * w
        ly = (v - 0.5) * h
        c, s = math.cos(prot), math.sin(prot)
        return (centre[0] + lx * c - ly * s, centre[1] + lx * s + ly * c)

    def _pick_part(self, pos):
        """The index of the topmost part under a viewport pixel."""
        if self.model2d is None:
            return None
        local = self._to_local(*pos)
        m = self.model2d
        t = self.play_t
        for i in range(len(m.parts) - 1, -1, -1):
            part = m.parts[i]
            if not self._part_shown(part):
                continue
            w, h = (m.size[0] * self._part_scale(part)[0],
                    m.size[1] * self._part_scale(part)[1])
            if w <= 0.0 or h <= 0.0:
                continue
            x, y, prot = self._world_of(part, t)
            dx, dy = local[0] - x, local[1] - y
            c, s = math.cos(-prot), math.sin(-prot)
            ux = dx * c - dy * s
            uy = dx * s + dy * c
            if abs(ux) <= w / 2.0 and abs(uy) <= h / 2.0:
                return i
        return None

    def _playhead_hit(self, pos):
        line = self.inner.bottom - 14
        return (self.inner.x + 8 < pos[0] < self.inner.right - 8
                and abs(pos[1] - line) <= 6)

    def _scrub(self, pos):
        x = max(0.0, min(1.0, (pos[0] - self.inner.x - 8) /
                         max(1.0, self.inner.width - 16)))
        self.play_t = x * self._track_len()

    def _pointer_world(self, pos):
        """A viewport pixel read in the rig's own unturned axes."""
        local = self._to_local(*pos)
        ox, oy = self._rig_origin()
        dx, dy = local[0] - ox, local[1] - oy
        rot = self._rig_rot()
        c, s = math.cos(-rot), math.sin(-rot)
        z = self.flat_view["zoom"]
        return ((dx * c - dy * s) / z, (dx * s + dy * c) / z)

    def _start_parts_drag(self, pos, at=None):
        """Drag every picked part by one offset."""
        self._push_undo()
        parts = self.model2d.parts
        self.drag = {"kind": "parts",
                     "at": (self._pointer_world(pos) if at is None else at),
                     "base": {i: list(parts[i].get("pos") or POS_DEFAULT)
                              for i in self.sel_parts
                              if 0 <= i < len(parts)}}

    def _move_parts_drag(self, pos):
        now = self._pointer_world(pos)
        at = self.drag["at"]
        dx, dy = now[0] - at[0], now[1] - at[1]
        if not self.drag["base"]:
            return
        parts = self._clone_parts()
        for i, base in self.drag["base"].items():
            nx, ny = base[0] + dx, base[1] + dy
            if self.snap:
                nx = round(nx / self.snap_step) * self.snap_step
                ny = round(ny / self.snap_step) * self.snap_step
            if (float((parts[i].get("pos") or POS_DEFAULT)[0]),
                    float((parts[i].get("pos") or POS_DEFAULT)[1])) \
                    == (nx, ny):
                continue
            parts[i]["pos"] = [nx, ny]
            self.dirty = True

    def _flat_wheel(self, pos, step):
        old = self.flat_view["zoom"]
        new = max(FLAT_MIN, min(FLAT_MAX, old * (1.25 if step > 0 else 0.8)))
        if new == old:
            return
        lx, ly = self._to_local(*pos)
        self.flat_view["zoom"] = new
        # keep the point under the pointer exactly where it was
        wx, wy = self._to_world(lx, ly)
        self.flat_view["cx"] += lx - wx
        self.flat_view["cy"] += ly - wy

    def _flat_pan(self, rel):
        z = self.flat_view["zoom"]
        self.flat_view["cx"] -= rel[0] / z
        self.flat_view["cy"] -= rel[1] / z

    def frame_flat(self):
        m = self.model2d
        if m is None or not self.inner.width or not self.inner.height:
            return
        self.flat_view["cx"] = self.flat_view["cy"] = 0.0
        z = min(self.inner.width * 0.8 / max(1.0, m.size[0]),
                self.inner.height * 0.8 / max(1.0, m.size[1]))
        self.flat_view["zoom"] = max(FLAT_MIN, min(FLAT_MAX, z))

    def track_len(self):
        """When the longest track ends: the playhead's span."""
        if self.model2d is None:
            return 0.0
        top = 0.0
        for tr in self.model2d.tracks:
            for k in tr.get("keys") or ():
                if k and float(k[0]) > top:
                    top = float(k[0])
        return top

    def _advance_anim(self):
        now = pygame.time.get_ticks()
        if not self.playing:
            self._play_at = now
            return
        dt = max(0.0, (now - self._play_at) / 1000.0)
        self._play_at = now
        self.play_t += dt
        length = self.track_len()
        if length > 0.0 and self.play_t > length:
            self.play_t = 0.0

    def _select_part(self, index):
        if index != self.sel_part:
            self.grip = self.popup = None
        self.sel_part = index
        self.sel_parts = [index] if index is not None else []

    def toggle_part(self, index):
        """Shift-click joins or drops a part from the set."""
        if index is None:
            return
        if index in self.sel_parts:
            self.sel_parts.remove(index)
        else:
            self.sel_parts.append(index)
        self.sel_part = self.sel_parts[-1] if self.sel_parts else None
        self.grip = self.popup = None

    def _track_keys(self, name):
        """One part's rot track, or None when it has none."""
        for tr in self.model2d.tracks:
            if tr.get("part") == name and tr.get("prop") == "rot":
                return tr.setdefault("keys", [])
        return None

    def _track_offset(self, part_name, t):
        """Sprite2D's sampling: clamp before the first key and after the"""
        keys = []
        for tr in self.model2d.tracks:
            if tr.get("part") == part_name and tr.get("prop") == "rot":
                keys = sorted(tr.get("keys") or (), key=lambda k: k[0])
                break
        if not keys or t <= float(keys[0][0]):
            return float(keys[0][1]) if keys else 0.0
        for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
            if t <= float(t1):
                span = float(t1) - float(t0)
                k = 0.0 if span <= 0.0 else (t - float(t0)) / span
                return float(v0) + (float(v1) - float(v0)) * k
        return float(keys[-1][1])

    def _part_eff_rot(self, part, t):
        name = part.get("name")
        base = float(part.get("rot") or 0.0)
        return base + self._track_offset(name, t)

    # a snapshot is a deep copy of plain data
    def _flat_snap(self):
        m = self.model2d
        return {"size": list(m.size), "pivot": list(m.pivot),
                "texture": m.texture,
                "parts": copy.deepcopy(m.parts),
                "tracks": copy.deepcopy(m.tracks)}

    def _flat_restore(self, snap):
        m = self.model2d
        m.size = list(snap["size"])
        m.pivot = list(snap["pivot"])
        m.texture = snap["texture"]
        m.parts = copy.deepcopy(snap["parts"])
        m.tracks = copy.deepcopy(snap["tracks"])
        names = [p.get("name") for p in m.parts]
        if self.sel_part is None or self.sel_part >= len(names):
            self.sel_part = 0 if names else None
        self.sel_parts = [i for i in self.sel_parts if i < len(names)]
        if self.sel_part is not None and self.sel_part not in self.sel_parts:
            self.sel_parts.insert(0, self.sel_part)

    def _clone_parts(self):
        """Copy the parts into the document before editing."""
        self.model2d.parts = copy.deepcopy(self.model2d.parts)
        return self.model2d.parts

    def _clone_tracks(self):
        self.model2d.tracks = copy.deepcopy(self.model2d.tracks)
        return self.model2d.tracks

    # --- flat edits
    def add_part(self):
        if self.model2d is None:
            self.new_model2d()
            return
        self._push_undo()
        parts = self._clone_parts()
        base = self.get_part()
        names = {p.get("name") for p in parts}
        i = 1
        while f"part{i}" in names:
            i += 1
        fresh = {"name": f"part{i}", "texture": base.get("texture"),
                 "uv": list(base.get("uv") or UV_DEFAULT),
                 "pos": [float((base.get("pos") or POS_DEFAULT)[0]) + 4.0,
                         float((base.get("pos") or POS_DEFAULT)[1]) + 4.0],
                 "rot": float(base.get("rot") or 0.0),
                 "scale": list(self._part_scale(base)),
                 "parent": base.get("name") if base else None}
        parts.append(fresh)
        self.sel_part = len(parts) - 1
        self.sel_parts = [self.sel_part]
        self.dirty = True
        self.message = f"added {fresh['name']}"

    def duplicate_part(self, step=False):
        if self.model2d is None or self.sel_part is None:
            self.message = "pick a part first"
            return
        if step:
            self.key_part()
            return
        self._push_undo()
        parts = self._clone_parts()
        src = copy.deepcopy(parts[self.sel_part])
        names = {p.get("name") for p in parts}
        base = str(src.get("name") or "part")
        stem = ("copy" if base not in names
                else next(f"copy{i}" for i in range(2, 9999)
                          if f"copy{i}" not in names))
        src["name"] = stem
        p = src.get("pos") or POS_DEFAULT
        src["pos"] = [float(p[0]) + 8.0, float(p[1]) + 8.0]
        parts.insert(self.sel_part + 1, src)
        self.sel_part += 1
        self.sel_parts = [self.sel_part]
        self.dirty = True
        self.message = f"copied as {stem}"

    def delete_part(self):
        """Take the picked part out, layers and tracks too."""
        if self.model2d is None or self.sel_part is None:
            self.message = "pick a part to delete"
            return
        self._push_undo()
        parts = self._clone_parts()
        name = parts[self.sel_part].get("name")
        del parts[self.sel_part]
        self.model2d.tracks = [t for t in self._clone_tracks()
                               if t.get("part") != name]
        self.sel_part = 0 if parts else None
        self.sel_parts = [0] if parts else []
        self.dirty = True
        self.message = f"deleted {name}"

    def rename_part(self, old, new):
        """File a part's new name; its tracks follow."""
        parts = self._clone_parts()
        i = next((j for j, p in enumerate(parts)
                  if p.get("name") == old), None)
        if i is None:
            return
        parts[i]["name"] = new
        for tr in self._clone_tracks():
            if tr.get("part") == old:
                tr["part"] = new
            if tr.get("parent") == old:
                tr["parent"] = new
        self.sel_part = i
        self.dirty = True
        self.message = f"renamed {old} -> {new}"

    def set_parent(self, name):
        if self.sel_part is None:
            return
        if name == self.get_part().get("name"):
            self.message = "a part cannot parent itself"
            return
        self._push_undo()
        self._clone_parts()[self.sel_part]["parent"] = name
        self.dirty = True
        self.message = f"parent {'(none)' if name is None else name}"

    def set_part_texture(self, key, scope="part"):
        """Give a part its sheet or colour, or the default."""
        self._push_undo()
        if scope == "rig" or self.sel_part is None:
            self.model2d.texture = key
            self.message = f"rig texture {key or 'white'}"
        else:
            self._clone_parts()[self.sel_part]["texture"] = key
            self.message = (f"{self.get_part().get('name')} -> "
                            f"{key or 'rig texture'}")
        self.dirty = True

    def _pick_texture(self, field, current, pos):
        """The texture picker: a sheet or a colour."""
        items = [("color", "(a colour...)")] + [(k, k) for k
                                                in self.texture_keys()]
        self.popup = {"x": pos[0], "y": pos[1], "items": items,
                      "target": ("texfield", field)}

    def _pick_color(self, scope="part"):
        def answer(value):
            key = colors.key(value or "")
            if value and key is None:
                self.app.log(f"not a colour: {value}", "warn")
                return
            if self.model2d is None:
                return
            self.set_part_texture(key, scope)

        self.app.pick_color("Surface colour", "", answer,
                            hint="Hex, rgb(...), a name like torch, or "
                                 "None for the rig's own sheet.")

    def set_rot(self, index, value):
        self._push_undo()
        self._clone_parts()[index]["rot"] = float(value)
        self.dirty = True

    def set_visible(self, index):
        self._push_undo()
        parts = self._clone_parts()
        was = parts[index].get("visible", True)
        parts[index]["visible"] = not was
        self.dirty = True
        self.message = ("hidden" if was else "shown") + " " + \
                       str(parts[index].get("name"))

    def reorder_part(self, delta):
        """One part up or down the layer order."""
        if self.model2d is None or self.sel_part is None:
            return
        i = self.sel_part
        j = i + delta
        parts = self.model2d.parts
        if not (0 <= j < len(parts)):
            return
        self._push_undo()
        parts = self._clone_parts()
        parts.insert(j, parts.pop(i))
        self.sel_part = j
        self.sel_parts = [j]
        self.dirty = True

    def key_part(self):
        """Key the picked part's rot at the playhead."""
        if self.model2d is None or self.sel_part is None:
            self.message = "pick a part to key"
            return
        name = self.get_part().get("name")
        self._push_undo()
        tracks = self._clone_tracks()
        tr = next((t for t in tracks if t.get("part") == name
                   and t.get("prop") == "rot"), None)
        if tr is None:
            tr = {"part": name, "prop": "rot", "keys": []}
            tracks.append(tr)
        keys = tr.setdefault("keys", [])
        value = float(self.get_part().get("rot") or 0.0)
        for k in keys:
            if abs(float(k[0]) - self.play_t) < 1e-4:
                k[1] = value
                break
        else:
            keys.append([self.play_t, value])
        keys.sort(key=lambda k: k[0])
        self.dirty = True
        self.message = f"key at {self.play_t:.2f}s -> {value:.3f}"

    def next_key(self, delta):
        """Jump the playhead to the next or previous key."""
        times = sorted({float(k[0]) for tr in (self.model2d.tracks
                                               if self.model2d else [])
                        for k in (tr.get("keys") or ()) if k})
        if not times:
            self.message = "no keys yet - press Key to write one"
            return
        want = next((t for t in (times if delta > 0 else reversed(times))
                     if (t > self.play_t + 1e-6 if delta > 0
                         else t < self.play_t - 1e-6)), self.play_t)
        self.play_t = want

    def key_next(self):
        self.next_key(1)

    def key_prev(self):
        self.next_key(-1)

    def layer_back(self):
        self.reorder_part(-1)

    def layer_fwd(self):
        self.reorder_part(1)

    def delete_key(self):
        """Drop the key under the playhead for the picked part."""
        if self.model2d is None or self.sel_part is None:
            return
        name = self.get_part().get("name")
        removed = False
        for tr in self.model2d.tracks:
            if tr.get("part") != name or tr.get("prop") != "rot":
                continue
            keys = [k for k in (tr.get("keys") or ())
                    if abs(float(k[0]) - self.play_t) > 1e-4]
            if len(keys) != len(tr.get("keys") or ()):
                removed = True
        if not removed:
            self.message = "no key at the playhead"
            return
        self._push_undo()
        tracks = self._clone_tracks()
        for tr in tracks:
            if tr.get("part") == name and tr.get("prop") == "rot":
                tr["keys"] = [k for k in (tr.get("keys") or ())
                              if abs(float(k[0]) - self.play_t) > 1e-4]
        self.dirty = True
        self.message = "key removed"

    # flat fields: the same grip/picker pattern the Document tab uses
    def _field_value(self, spec):
        prop, label, kind, scope, index = spec
        if scope == "sheet":
            return self._sheet_value(prop)
        if scope == "gen":
            return self._gen_value(prop)
        if scope == "tiling":
            return self._tiling_value(prop, index)
        if scope == "rig":
            m = self.model2d
            if m is None:
                return ""
            if prop == "name":
                return m.name
            if prop == "size":
                return " ".join(f"{c:g}" for c in m.size)
            if prop == "pivot":
                return " ".join(f"{c:g}" for c in m.pivot)
            return m.texture or ""
        part = self.get_part()
        if not part:
            return ""
        if prop == "name":
            return str(part.get("name") or "")
        if prop == "visible":
            return "true" if self._part_shown(part) else "false"
        if prop == "texture":
            return str(part.get("texture") or "")
        if prop == "parent":
            return str(part.get("parent") or "")
        if prop == "rot":
            return f"{float(part.get('rot') or 0.0):g}"
        if prop in ("pos", "scale"):
            vals = (self._part_scale(part) if prop == "scale"
                    else tuple(part.get("pos") or POS_DEFAULT))
            while len(vals) < 2:
                vals = vals + (0.0,)
            return f"{float(vals[index or 0]):g}"
        if prop == "uv":
            return " ".join(f"{float(c):g}" for c in
                            (part.get("uv") or UV_DEFAULT))
        return ""

    def _field_def(self, spec):
        """The registry row behind a field: kind, index, writer."""
        prop, label, kind, scope, index = spec
        if scope == "gen":
            if kind == "num":
                return ("num", None, None, self._write_gen_num)
            return ("enum", None, None, self._write_choice)
        if scope == "sheet":
            if kind == "num":
                return ("num", None, None, self._write_sheet_num)
            return ("enum", None, None, self._write_choice)
        if scope == "tiling":
            return (kind, index, None, self._write_tiling)
        if scope == "rig":
            if prop == "size":
                return ("vec", None, None, self._write_size)
            if prop == "pivot":
                return ("vec", None, None, self._write_pivot)
            if prop == "texture":
                return ("enum", None, None, self._write_text)
            return ("ro", None, None, self._write_text)
        if prop == "pos":
            return ("vec", index, POS_DEFAULT, self._write_pos)
        if prop == "scale":
            return ("vec", index, SCALE_DEFAULT, self._write_scale)
        if prop == "uv":
            return ("vec", None, UV_DEFAULT, self._write_uv)
        return (kind, None, None,
                self._write_rot if prop == "rot" else self._write_text)

    def _commit_grip(self):
        spec, field = self.grip
        self.grip = None
        if isinstance(spec, tuple) and spec[0] == "objpos":
            try:
                self._set_object_position(spec[1], float(field.text.strip()))
            except ValueError:
                self.message = "position must be a number"
            return
        if isinstance(spec, tuple) and spec[0] == "paint_size":
            try:
                self.uvpaint.brush = max(
                    1, min(256, int(field.text.strip())))
            except ValueError:
                self.message = "brush size must be a number"
            return
        self._write_field(spec, field.text)

    def _write_field(self, spec, text):
        kind, index, _default, sink = self._field_def(spec)
        if kind == "bool":
            sink(spec)
            return
        if kind == "enum":
            return                       # an enum answers through its menu
        if kind == "text":
            sink(spec, str(text).strip())
            return
        if kind == "num":
            try:
                sink(spec, [float(str(text).strip())])
            except ValueError:
                self.message = "that is not a number"
            return
        try:
            nums = [float(p) for p in
                    str(text).replace(",", " ").split()]
        except ValueError:
            self.message = "numbers only, with spaces"
            return
        sink(spec, nums)

    def _write_text(self, spec, values):
        prop, label, kind, scope, index = spec
        text = str(values[0] if isinstance(values, list) else values)
        if not text:
            return
        if prop == "name":
            if self.model2d.part(text) is not None:
                self.message = f"{text} already names a part"
                return
            self.rename_part(self.get_part().get("name"), text)
            return
        if prop == "texture":
            self.set_part_texture(text, scope)
            return
        if prop == "parent":
            self.set_parent(None if text in ("none", "") else text)
            return
        if prop == "rot":
            self._write_rot(spec, [float(text or 0.0)])
            return
        self.model2d.size = [float(text), float(text)]
        self.dirty = True

    def _write_pos(self, spec, nums):
        if self.sel_part is None or not nums:
            return
        i = spec[4]
        self._push_undo()
        parts = self._clone_parts()
        p = list(parts[self.sel_part].get("pos") or POS_DEFAULT)
        while len(p) < 2:
            p.append(0.0)
        p[i] = nums[0]
        parts[self.sel_part]["pos"] = p
        self.dirty = True

    def _write_scale(self, spec, nums):
        if self.sel_part is None or not nums:
            return
        self._push_undo()
        parts = self._clone_parts()
        s = list(self._part_scale(parts[self.sel_part]))
        s[spec[4]] = nums[0]
        parts[self.sel_part]["scale"] = s
        self.dirty = True

    def _write_uv(self, spec, nums):
        if self.sel_part is None or len(nums) < 4:
            self.message = "uv wants four numbers: x0 y0 x1 y1"
            return
        self._push_undo()
        self._clone_parts()[self.sel_part]["uv"] = nums[:4]
        self.dirty = True

    def _write_rot(self, spec, nums):
        if self.sel_part is None or not nums:
            return
        self.set_rot(self.sel_part, nums[0])

    def _write_size(self, spec, nums):
        if len(nums) == 1:
            nums = [nums[0], nums[0]]
        if len(nums) < 2 or min(nums) < 1.0:
            self.message = "size wants pixels at least 1 across"
            return
        self._push_undo()
        self.model2d.size = [nums[0], nums[1]]
        self.dirty = True

    def _write_pivot(self, spec, nums):
        if len(nums) == 1:
            nums = [nums[0], nums[0]]
        if len(nums) < 2:
            return
        self._push_undo()
        self.model2d.pivot = [nums[0], nums[1]]
        self.dirty = True

    def _grip_field(self, spec, pos):
        self.popup = None
        self.grip = (spec, widgets.TextField(self._field_value(spec), 64))

    def _open_prop(self, spec, pos):
        prop, label, kind, scope, index = spec
        if kind == "ro":
            return
        if scope == "sheet" and kind == "enum":
            # an image option picks a name, not a file
            self.popup = {"x": pos[0], "y": pos[1],
                          "items": [(v, v) for v in SHEET_CHOICE[prop]],
                          "target": ("choice", spec)}
            return
        if scope == "gen" and kind == "enum":
            self.popup = {"x": pos[0], "y": pos[1],
                          "items": [("on", "on"), ("off", "off")],
                          "target": ("choice", spec)}
            return
        if kind == "enum":
            if prop == "parent":
                m = self.model2d
                items = [(None, "(none)")] + [
                    (p.get("name"), str(p.get("name")))
                    for i, p in enumerate(m.parts) if i != self.sel_part]
                self.popup = {"x": pos[0], "y": pos[1], "items": items,
                              "target": ("parent", None)}
            else:
                self._pick_texture(spec, self._field_value(spec), pos)
            return
        if kind == "bool":
            self.set_visible(self.sel_part)
            return
        self._grip_field(spec, pos)

    def _popup_click(self, pos):
        for action, rect in self.popup_rows:
            if rect.collidepoint(pos):
                target = self.popup["target"]
                if target[0] == "choice":
                    self._write_choice(target[1], action)
                    self.popup = None
                    return True
                if target[0] == "uvtex":
                    target[1].add_sheet_layer(
                        action, self._texture_path(action))
                    self.popup = None
                    return True
                if target[0] == "parent":
                    self.set_parent(action)
                elif action == "color":
                    self._pick_color(target[1][3])
                    return True
                else:
                    self.set_part_texture(action, target[1][3])
                self.popup = None
                return True
        self.popup = None
        return True

    def _panel_click(self, pos, e):
        """One click inside the parts/properties panel."""
        if self.popup is not None:
            return self._popup_click(pos)
        if not self.panel_rect.collidepoint(pos):
            return False
        if self.part_add_rect.collidepoint(pos):
            self.add_part()
            return True
        if self.part_duplicate_rect.collidepoint(pos):
            self.duplicate_part()
            return True
        if self.part_delete_rect.collidepoint(pos):
            self.delete_part()
            return True
        if self.grip is not None:
            field = next((r for spec, r in self.prop_fields
                          if spec == self.grip[0]), None)
            self._commit_grip()
            if field is not None and field.collidepoint(pos):
                return True
        for index, rect in self.part_rows:
            if rect.collidepoint(pos):
                if widgets.shift_held(e):
                    self.toggle_part(index)   # the tree picks like the view
                else:
                    self._select_part(index)
                return True
        for spec, rect in self.prop_fields:
            if rect.collidepoint(pos):
                self._open_prop(spec, pos)
                return True
        self.grip = None
        return True

    def _panel_wheel(self, pos, dy):
        if self.props_body.collidepoint(pos):
            self.props_scroll = max(
                0, min(self._props_max(), self.props_scroll + dy))
        elif self.parts_body.collidepoint(pos):
            self.parts_scroll = max(
                0, min(self._parts_max(), self.parts_scroll + dy))

    def _parts_max(self):
        if self.model2d is None:
            return 0
        n = len(self.model2d.parts)
        return max(0, n * PART_ROW + 4 - self.parts_body.height)

    def _props_max(self):
        n = len(self._flat_prop_rows())
        return max(0, n * FLAT_PROP_ROW + 6 - self.props_body.height)

    def _flat_prop_rows(self):
        """(label, value, spec, kind): the rig's fields, then the part's."""
        rows = ["-", ("rig", None, None, None)]
        for prop, label, kind in (("name", "name", "ro"),
                                  ("size", "size", "vec"),
                                  ("pivot", "pivot", "vec"),
                                  ("texture", "texture", "enum")):
            spec = (prop, label, kind, "rig", None)
            rows.append((label, self._field_value(spec), spec, kind))
        part = self.get_part()
        if not part:
            return rows
        rows.append("-")
        rows.append(("part", None, None, None))
        for prop, label, kind in FLAT_PROPS:
            idx = None
            if prop in ("pos", "scale"):
                idx = 0 if label.endswith("x") else 1
            spec = (prop, label, kind, "part", idx)
            rows.append((label, self._field_value(spec), spec, kind))
        return rows

    # shelf fields: the picked sheet's image options, and the tiling
    def shelf_sheet(self):
        """The file behind the picked sheet, if any."""
        if not self.paint_key or colors.is_spelling(self.paint_key):
            return None
        return self._texture_path(self.paint_key)

    def is_builtin(self, key):
        """True for a sheet the engine draws itself, no file needed."""
        return bool(key) and key in proctex.names()

    def _sheet_overrides(self, key=None):
        """What this project files about one sheet, globals aside."""
        project = self.app.project
        key = self.paint_key if key is None else key
        if project is None or not key:
            return {}
        try:
            return dict(project.sheet_overrides(key) or {})
        except (AttributeError, OSError, TypeError, ValueError):
            return {}

    def _sheet_words(self):
        """The image settings the picked sheet is kept to, engine first."""
        key = self.paint_key
        if not key or colors.is_spelling(key):
            return {}
        words = {}
        if self.is_builtin(key):
            opts = proctex.options(key)
            words = {"filter": "linear", "mipmaps": True,
                     "wrap": "repeat" if opts.get("repeat", True) else "clamp",
                     "tile": float(opts.get("tile", 0.0) or 0.0)}
        elif self.shelf_sheet() is not None and self.app.project is not None:
            try:
                words = dict(self.app.project.texture_settings(key))
            except (OSError, TypeError, ValueError):
                words = {}
        words.update({k: v for k, v in self._sheet_overrides().items()
                      if k in SHEET_WORDS})
        return words

    def _gen_rows(self):
        """One row per knob the picked built-in turns, as it stands filed."""
        if not self.is_builtin(self.paint_key):
            return []
        over = self._sheet_overrides()
        out = []
        for name, value in proctex.knobs(self.paint_key).items():
            got = over.get(name, value)
            if isinstance(got, bool):
                kind, shown = "enum", "on" if got else "off"
            elif isinstance(got, (int, float)):
                kind, shown = "num", f"{float(got):g}"
            else:
                continue        # a colour or a word is not a field here
            out.append((name, shown, (name, name, kind, "gen", None), kind))
        return out

    def _tex_prop_rows(self):
        """(label, value, spec, kind): everything the Settings block shows."""
        rows = ["-", ("image", None, None, None)]
        if not self.paint_key:
            rows.append(("note", "pick a sheet from the shelf first",
                         None, None))
        elif self.shelf_sheet() is None and not self.is_builtin(
                self.paint_key):
            rows.append(("note", "a blank or a plain colour keeps no "
                         "settings", None, None))
        else:
            for prop, label in SHEET_PROPS:
                spec = (prop, label, "enum", "sheet", None)
                rows.append((label, self._field_value(spec), spec, "enum"))
            for prop, label in SHEET_NUM_PROPS:
                spec = (prop, label, "num", "sheet", None)
                rows.append((label, self._field_value(spec), spec, "num"))
            gen = self._gen_rows()
            if gen:
                # a built-in is a picture made on request, so it has knobs
                rows.append("-")
                rows.append(("generator", None, None, None))
                rows += gen
        rows.append("-")
        rows.append(("tiling", None, None, None))
        if self.model is None:
            rows.append(("note", "no model open", None, None))
            return rows
        if self._sheet_material():
            # the block edits the document, not the picture
            rows.append(("note", "overridden by this sheet's tile size",
                         None, None))
        for prop, label, index in TILING_PROPS:
            spec = (prop, label, "num", "tiling", index)
            rows.append((label, self._field_value(spec), spec, "num"))
        return rows

    def _sheet_material(self):
        """Metres one repeat of the picked sheet covers; 0 else."""
        try:
            return float(self._sheet_words().get("tile") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _tex_rows_max(self, body):
        """How far the Settings block scrolls."""
        n = 0
        for row in self._tex_prop_rows():
            if row[0] == "-":
                n += 7
            elif row[2] is None:
                n += 14
            else:
                n += SHELF_ROW
        return max(0, n + 6 - body.height)

    def _sheet_value(self, prop):
        """The word this sheet is kept to, as field text."""
        got = self._sheet_words().get(prop)
        if prop == "mipmaps":
            return "off" if got in (False, "off", 0, "0") else "on"
        if prop == "tile":
            # 0 is real: the sheet pictures one particular thing
            try:
                return f"{float(got or 0.0):g}"
            except (TypeError, ValueError):
                return "0"
        return str(got or "-")

    def _gen_value(self, prop):
        """One built-in knob as field text, the filed value over the default."""
        got = self._sheet_overrides().get(
            prop, proctex.knobs(self.paint_key or "").get(prop))
        if isinstance(got, bool):
            return "on" if got else "off"
        if isinstance(got, (int, float)):
            return f"{float(got):g}"
        return str(got if got is not None else "-")

    def _tiling_value(self, prop, index):
        """One uv number on the model; rotation in degrees."""
        if self.model is None:
            return ""
        if prop == "uv_rot":
            return f"{math.degrees(self.model.uv_rot):g}"
        vals = (self.model.uv_scale if prop == "uv_scale"
                else self.model.uv_offset)
        return f"{float(vals[index or 0]):g}"

    def _write_choice(self, spec, value):
        """File a named image option and show it now."""
        prop = spec[0]
        if spec[3] == "gen":
            return self._apply_gen(prop, value == "on")
        got = (value == "on") if prop == "mipmaps" else str(value)
        return self._apply_sheet(spec, got)

    def _write_sheet_num(self, spec, nums):
        """File the world metres one sheet repeat covers."""
        if not nums:
            return
        value = max(0.0, float(nums[0]))
        return self._apply_sheet(spec, value,
                                 shown="picture" if not value
                                 else f"{value:g}")

    def _write_gen_num(self, spec, nums):
        """Turn one built-in knob that reads as a number."""
        if not nums:
            return
        value = nums[0]
        base = proctex.knobs(self.paint_key or "").get(spec[0])
        if isinstance(base, int) and not isinstance(base, bool):
            value = int(round(value))
        return self._apply_gen(spec[0], value)

    def _apply_gen(self, prop, got):
        """Turn one built-in's knob, file it, and redraw the sheet."""
        project = self.app.project
        if not self.paint_key or project is None:
            self.message = "open a project to file a sheet change"
            return False
        try:
            project.set_texture_settings(self.paint_key, keep_all=True,
                                         **{prop: got})
        except Exception as exc:
            self.app.log(f"sheet knob: {exc}", "warn")
            return False
        self._reload_sheet(self.paint_key)
        self.message = f"{self.paint_key} {prop} -> {got}"
        return True

    def _reload_sheet(self, key):
        """Rebuild a built-in from the values filed for it, and show it."""
        if self.renderer is not None:
            try:
                arr, kwargs = builtin_sheet(key, self.app.project)
            except Exception as exc:
                self.app.log(f"sheet: {exc}", "warn")
                arr = None
            if arr is not None:
                self.renderer.texture(key, arr, **kwargs)
        for stamp in [k for k in self._thumbs if k[0] == key]:
            self._thumbs.pop(stamp)
        self._sheet.pop(key, None)
        self._refresh_mesh()

    def _apply_sheet(self, spec, got, shown=None):
        """Write one sheet setting to assets.json and re-show the sheet."""
        project = self.app.project
        built = self.is_builtin(self.paint_key)
        if project is None:
            self.message = "open a project to file a sheet change"
            return False
        if not self.paint_key:
            self.message = "pick a sheet from the shelf first"
            return False
        try:
            project.set_texture_settings(self.paint_key, keep_all=built,
                                         **{spec[0]: got})
        except Exception as exc:
            self.app.log(f"texture settings: {exc}", "warn")
            return False
        if built:
            # a built-in inherits nothing, so it is drawn again from file
            self._reload_sheet(self.paint_key)
        else:
            self.refresh_textures()
            self._sheet.clear()
            self._refresh_mesh()
        self.message = (f"{self.paint_key} {spec[1]} -> "
                        f"{got if shown is None else shown}")
        return True

    def _write_tiling(self, spec, nums):
        """Write one model `uv` number and preview it."""
        if self.model is None or not nums:
            return
        prop, label, _kind, _scope, index = spec
        value = float(nums[0])
        if prop == "uv_scale" and abs(value) < 0.01:
            self.message = "scale wants at least 0.01"
            return
        self._push_undo()
        model = self.model
        if prop == "uv_rot":
            model.uv_rot = math.radians(value)
        elif prop == "uv_scale":
            got = list(model.uv_scale)
            got[index or 0] = value
            model.uv_scale = got
        else:
            got = list(model.uv_offset)
            got[index or 0] = value
            model.uv_offset = got
        self.dirty = True
        self._refresh_mesh()
        self.message = f"{label} -> {value:g}"

    def target_faces(self):
        """Faces a surface edit writes; None means all."""
        if self.model is None:
            return None
        if self.ui_mode == "texture":
            if self.sel_face is not None and not self.paint_all:
                return [self.sel_face]
            return None
        if self.mode == "face" and self.sel_face is not None:
            return [self.sel_face]
        if self.mode == "vertex" and self.sel_verts:
            faces = self.model.faces_using(self.sel_verts)
            if faces:
                return faces
        return None

    def surface_color(self):
        """The target's colour, or "" while drawing a sheet."""
        if self.model is None:
            return ""
        faces = self.target_faces()
        if faces is None and self._obj_write_target():
            for o in self.model.objects:
                if o["name"] == str(self.sel_obj):
                    got = o.get("texture")
                    return colors.key(got) if colors.is_spelling(got) else ""
        got = self.model.face_texture(faces[0]) if faces \
            else self.model.texture
        return colors.key(got) if colors.is_spelling(got) else ""

    def _sel_obj_faces(self):
        """The picked object's face list, or None."""
        if (self.model is None or not self.model.has_objects
                or not self.sel_obj):
            return None
        for o in self.model.objects:
            if o["name"] == str(self.sel_obj):
                return list(o["faces"])
        return None

    def _obj_write_target(self):
        """The object a whole-target write lands on, or None."""
        if self.paint_all or self._sel_obj_faces() is None:
            return None
        return self.sel_obj

    def _sync_obj_pick(self):
        """Keep the object pick pointing at a real part."""
        if self.model is not None and self.model.has_objects:
            names = self.model.object_names()
            if self.sel_obj not in names:
                self.sel_obj = names[0] if names else None
            self.sel_objs = [n for n in names if n == self.sel_obj]
        else:
            self.sel_obj = None
            self.sel_objs = []
        if self.uvpaint is not None and self.ui_mode == "uv":
            self.uvpaint = self._uvpaint_for(self.sel_obj)

    def select_object(self, name, toggle=False):
        """Make one object the pick; Shift adds or drops it."""
        if self.model is None or not self.model.has_objects:
            return
        names = self.model.object_names()
        if name not in names:
            return
        if toggle:
            if name in self.sel_objs:
                self.sel_objs.remove(name)
            else:
                self.sel_objs.append(name)
            self.sel_obj = self.sel_objs[-1] if self.sel_objs else None
        else:
            self.sel_objs = [name]
            self.sel_obj = name
        if self.uvpaint is not None and self.ui_mode == "uv":
            self.uvpaint = self._uvpaint_for(self.sel_obj)

    def cycle_paint_object(self, step):
        """Switch the combined UV/surface paint session to another object."""
        if self.model is None or not self.model.has_objects:
            return
        names = self.model.object_names()
        if not names:
            return
        current = self.uvpaint.objname if self.uvpaint is not None else \
            self.sel_obj
        index = names.index(current) if current in names else 0
        self.select_object(names[(index + step) % len(names)])
        self.uvpaint = self._uvpaint_for(self.sel_obj)
        if not self.uvpaint.ensure_unwrapped():
            self.message = self.uvpaint.message or "nothing to unwrap"

    def _object_drag_verts(self):
        """Which vertices an object-mode drag moves: every picked object's"""
        if self.model is None:
            return []
        if self.model.has_objects:
            got = set()
            for name in self.sel_objs:
                got.update(self.model.object_verts(name))
            return sorted(got)
        return list(range(len(self.model.verts)))

    def _object_position(self):
        indices = self._object_drag_verts()
        if not indices:
            return None
        points = [self.model.verts[i] for i in indices]
        return tuple((min(p[axis] for p in points) +
                      max(p[axis] for p in points)) / 2.0
                     for axis in range(3))

    def _set_object_position(self, axis, value):
        indices = self._object_drag_verts()
        if not indices:
            self.message = "select an object before setting its position"
            return
        i = "xyz".index(axis)
        current = self._object_position()[i]
        target = value
        delta = target - current
        if abs(delta) < 1e-9:
            return
        self._push_undo()
        for index in indices:
            self.model.verts[index][i] += delta
        self.dirty = True
        self._refresh_mesh()
        self.message = f"position {axis.upper()} -> {target:g}"

    def _can_merge(self):
        """True when two picked objects' bounds meet."""
        if self.model is None:
            return False
        names = [n for n in self.sel_objs
                 if n in self.model.object_names()]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if _bounds_hit(self.model.obj_bounds(names[i]),
                               self.model.obj_bounds(names[j])):
                    return True
        return False

    def _act_merge(self):
        """Fold the picked objects into their first one, dropping faces"""
        if not self._can_merge():
            self.message = "pick two objects whose bounds meet"
            return
        owners = self.model.object_names()
        keep = next(n for n in owners if n in set(self.sel_objs))
        self._push_undo()
        if not self.model.merge_objects(list(self.sel_objs)):
            self.message = "merge needs two real objects"
            return
        self.sel_verts.clear()
        self.sel_face = None
        self.sel_faces.clear()
        self.sel_obj = keep if keep in self.model.object_names() else None
        self.sel_objs = [self.sel_obj] if self.sel_obj else []
        self._sync_obj_pick()
        self.dirty = True
        self._refresh_mesh()
        self.message = f"merged into {self.sel_obj}"

    def _act_add_obj(self):
        """Create a named object from the pick, or add a new box object."""
        if self.model is None:
            return
        faces = self.target_faces()
        faces = list(faces) if faces else []
        self._push_undo()
        n = 1
        cand = f"object{n}"
        while cand in self.model.object_names():
            n += 1
            cand = f"object{n}"
        if faces:
            entry = self.model.make_object(cand, faces)
        elif self.model.tris and not self.model.has_objects:
            entry = {"name": cand, "faces": list(range(
                len(self.model.tris))), "texture": None,
                     "painted": False, "lightmap": None}
            self.model.objects = [entry]
        else:
            bounds = self.model.bounds()
            offset = ((bounds[1][0] + 0.5, 0.0, 0.0)
                      if bounds else (0.0, 0.0, 0.0))
            first_face = len(self.model.tris)
            self.model.add_primitive("box", 0.75, offset=offset)
            new_faces = list(range(first_face, len(self.model.tris)))
            if self.model.has_objects:
                entry = self.model.make_object(cand, new_faces)
            else:
                entry = {"name": cand, "faces": new_faces, "texture": None,
                         "painted": False, "lightmap": None}
                self.model.objects = [entry]
        if entry is None:
            self.message = "could not make that object"
            return
        self.sel_verts.clear()
        self.sel_face = None
        self.sel_faces.clear()
        self.select_object(entry["name"])
        self.dirty = True
        self._refresh_mesh()
        self.message = f"added {entry['name']} ({len(entry['faces'])} faces)"

    def _begin_rename(self, name):
        """Drop an inline text field over one object's row."""
        self.rename_obj = name
        self.obj_field.set(str(name))
        self.obj_focus = True

    def _commit_rename(self):
        """Move the retyped name, refusing a taken one."""
        if self.rename_obj is None or self.model is None:
            self.rename_obj = None
            self.obj_focus = False
            return
        old = self.rename_obj
        new = str(self.obj_field.text).strip()
        self.rename_obj = None
        self.obj_focus = False
        if not new or new == old:
            return
        if not self.model.rename_object(old, new):
            self.message = f"{new} is taken"
            return
        if self.sel_obj == old:
            self.sel_obj = new
        self.sel_objs = [new if n == old else n for n in self.sel_objs]
        if self.uvpaint is not None:
            self.uvpaint.objname = self.sel_obj
        self.dirty = True
        self.message = f"renamed {old} -> {new}"

    def apply_color(self, value):
        """Write the picker's answer onto the target as its surface."""
        if self.model is None:
            return False
        key = colors.key(value or "")
        faces = self.target_faces()
        if faces is None:
            obj = self._obj_write_target()
            if obj is not None:
                self._push_undo()
                self.model.set_object_texture(obj, key or None)
                self.dirty = True
                self._refresh_mesh()
                self.message = f"{obj} -> {key or 'default'}"
                return True
            return self.fill_all(key or "white")
        self._push_undo()
        for fi in faces:
            self.model.set_face_texture(fi, key)
        self.message = f"{len(faces)} face(s) -> {key or 'default'}"
        self.dirty = True
        self._refresh_mesh()
        return True

    def fill_all(self, key):
        """Paint the whole model with one surface, tags too."""
        if self.model is None or not key:
            return False
        base = colors.key(key) or str(key)
        self._push_undo()
        self.model.texture = base
        for fi in range(len(self.model.tris)):
            self.model.set_face_texture(fi, None)
        self.paint_key = base
        self.sel_face = None
        self.dirty = True
        self._refresh_mesh()
        self.message = f"whole model -> {base}"
        return True

    def _paint_face(self, face):
        """Give one face the picked sheet and show it now."""
        if self.model is None or not self.paint_key:
            return False
        if not 0 <= face < len(self.model.tris):
            return False
        self.model.set_face_texture(face, self.paint_key)
        self.sel_face = face
        self.sel_verts = set(self.model.tris[face])
        self.dirty = True
        self._refresh_mesh()
        self.message = f"face {face} -> {self.model.face_texture(face)}"
        return True

    def _ensure_renderer(self, size):
        size = (max(64, int(size[0])), max(64, int(size[1])))
        if self.renderer is None:
            self.renderer = Renderer(*size, render_scale=1.0)
            r = self.renderer
            project = self.app.project
            r.project = project
            # the sheets a game registers by name, from `proctex`'s table
            register_builtin_textures(r, project)
            try:
                self.app.project.register_textures(r)
            except Exception as exc:
                self.app.log(f"textures: {exc}", "warn")
            r.add(meshes.plane(size=(24, 24), seg=24), texture="grid")
            r.build()
            self.meshes = []
            self.render_size = size
            self._refresh_mesh()
            return
        if size != self.render_size:
            self.renderer.resize(*size)
            self.render_size = size

    def _drop_meshes(self):
        if self.model is None and not self.meshes:
            return
        for mesh in self.meshes:
            mesh.dispose()
        self.meshes = []

    def _refresh_mesh(self):
        """Rebuild the preview as one mesh per surface."""
        if self.renderer is None or self.model is None:
            return
        if self.model.empty:
            self._drop_meshes()
            return
        groups = self.model.mesh_groups()
        while len(self.meshes) < len(groups):
            key, data = groups[len(self.meshes)]
            self.meshes.append(self.renderer.new_dynamic(
                data, texture=key, blend="opaque"))
        while len(self.meshes) > len(groups):
            self.meshes.pop().dispose()
        for mesh, (key, data) in zip(self.meshes, groups):
            mesh.texture = key
            mesh.update(data)

    def resize(self, size):
        if self.renderer is not None:
            self._ensure_renderer(size)

    def _groups(self):
        """The 3D toolbar as captioned bands of (label, action, on, tip)."""
        # the same document is a map or a model, and the button says which
        # way round it is about to file it
        kind_label = "To model" if self.is_map else "To map"
        kind_tip = ("File this under models/ as a .model3d" if self.is_map
                    else "File this under maps/ as a .map3d, its faces one "
                        "object, so each can light and hide on its own")
        out = [("Mode", [(label, ("ui", mode), self.ui_mode == mode,
                          f"the {label.lower()} half of this tab")
                         for mode, label in UI_MODES])]
        if self.ui_mode == "texture":
            out.append(("Paint", [
                ("Paint", ("toggle", "paint"), self.paint_on,
                 "Click or drag across faces to fill them"),
                ("All", ("toggle", "paintall"), self.paint_all,
                 "Every write lands on the whole model"),
                ("Colour", ("action", "color"), False,
                 "Colour the picked faces (C) - nothing picked = all"),
                ("Clear", ("action", "clear"), False,
                 "Hand the faces back to the model's own sheet")]))
        elif self.ui_mode == "edit":
            out.append(("Shape", [(label, ("mode", mode), self.mode == mode,
                                   f"edit {label.lower()}s (1/2/3)")
                                  for mode, label in MODES]))
            out.append(("New", [
                ("New", ("action", "new"), False,
                 "Start a new model, replacing the open one"),
                ("New Map", ("action", "newmap"), False,
                 "Start a new map (saves to maps/ as .map3d)")]))
            out.append(("Add", [(label, ("prim", kind), False,
                                 f"Add a {label.lower()} to the open model")
                                for kind, label in PRIMITIVES]))
            out.append(("Edit", [
                ("Delete", ("action", "delete"), False,
                 "Delete the picked faces or vertices (Del)"),
                ("Extrude", ("action", "extrude"), False,
                 "Pull the picked faces out (E)"),
                ("Face", ("action", "makeface"), False,
                 "Fill the picked vertices with a face (F)"),
                ("Flip", ("action", "flip"), False,
                 "Turn the picked faces over"),
                ("Weld", ("action", "weld"), False,
                 "Merge vertices sitting on each other")]))
            move = [("Snap", ("toggle", "snap"), self.snap,
                     f"drags land on {self.snap_step} m (G)")]
            if self.mode == "object":
                point = self._object_position()
                if point is not None:
                    move.extend(
                        (f"{axis.upper()} {point[i]:.2f}",
                         ("objpos", axis), False,
                         f"Set the selected object(s)' {axis.upper()} "
                         "position")
                        for i, axis in enumerate("xyz"))
            move.extend((axis.upper(), ("axis", axis), self.axis == axis,
                         f"drag along {axis.upper()} only")
                        for axis in "xyz")
            move.append(("Free", ("axis", None), self.axis is None,
                         "drag on the view plane instead"))
            out.append(("Move", move))
        out.append(("File", [
            ("Save", ("action", "save"), False, "Save the model (Ctrl+S)"),
            ("Reload", ("action", "reload"), False,
             "Rebuild from the file on disk"),
            (kind_label, ("action", "askind"), False, kind_tip),
            ("Undo", ("action", "undo"), False, "Undo (Ctrl+Z)"),
            ("Redo", ("action", "redo"), False, "Redo (Ctrl+Y)")]))
        out.append(("View", [
            ("Wire", ("toggle", "wire"), self.wire,
             "Draw the edges over the faces"),
            ("Frame", ("action", "frame"), False, "Fit the model"),
            ("AutoUV", ("action", "autouv"), False,
             "Planar-unwrap the picked faces, or all of them")]))
        return out

    def _name_row(self, rect, top, tip):
        """The row under the bands: the name, its sheet, and the colour.

        A narrow tab drops the sheet cycler and then the colour before it
        lets the name field shrink past the point of being typeable.
        """
        out = []
        right = rect.right - 6
        chip = pygame.Rect(rect.x + 6, top + 3, 34, TOOL_H - 6)
        out.append({"rect": chip, "label": "Name", "action": ("none", None),
                    "active": False, "tip": "model name"})
        wide = max(64, min(160, int((right - chip.right) * 0.44)))
        self.name_rect = pygame.Rect(chip.right + 4, top + 2, wide,
                                     TOOL_H - 4)
        out.append({"rect": self.name_rect, "label": "",
                    "action": ("focus_name", None), "active": self.name_focus,
                    "tip": tip})
        self.color_rect = pygame.Rect(0, 0, 0, 0)
        self.hint_x = self.name_rect.right + 12
        x = self.name_rect.right + 10
        # the sheet cycler goes first, then the colour keeps its button
        col_w = self.small.size("Colour")[0] + 14
        tex = self.model.texture if self.model else "-"
        sheet_w = max(70, self.small.size(str(tex))[0] + 16)
        block = 24 + 3 + sheet_w + 3 + 24 + 12
        if x + block + col_w + 26 <= right:
            prev = pygame.Rect(x, top + 2, 24, TOOL_H - 4)
            shown = pygame.Rect(prev.right + 3, top + 2, sheet_w, TOOL_H - 4)
            nxt = pygame.Rect(shown.right + 3, top + 2, 24, TOOL_H - 4)
            out.append({"rect": prev, "label": "<", "action": ("tex", -1),
                        "active": False, "tip": "previous texture"})
            out.append({"rect": shown, "label": str(tex),
                        "action": ("none", None), "active": True,
                        "tip": "the sheet this model draws with"})
            out.append({"rect": nxt, "label": ">", "action": ("tex", 1),
                        "active": False, "tip": "next texture"})
            x += block
        # the chip is the colour about to be written
        swatch = pygame.Rect(x, top + 5, 14, TOOL_H - 10)
        button = pygame.Rect(swatch.right + 4, top + 2, col_w, TOOL_H - 4)
        if button.right > right:
            button = pygame.Rect(x, top + 2, col_w, TOOL_H - 4)
            swatch = pygame.Rect(0, 0, 0, 0)
        if button.right <= right and self.model is not None:
            if swatch.width:
                self.color_rect = swatch
                out.append({"rect": swatch, "label": "",
                            "action": ("action", "color"), "active": False,
                            "tip": "surface colour of the selection / "
                                   "model"})
            self.hint_x = button.x
            out.append({"rect": button, "label": "Colour",
                        "action": ("action", "color"), "active": False,
                        "tip": "Colour the picked faces (C) - nothing "
                               "picked = the model"})
            self.hint_x = button.right + 12
        return out

    def _fit_bands(self, rect, bands, used):
        """Cap a tall strip of bands to a share of the tab, scrolled if needed.

        A narrow window wraps eight sections into eight rows, which would
        leave no viewport at all. The strip keeps the top rows and scrolls
        for the rest, and every button stays reachable one way or another.
        Rows are measured as laid out, since a band too wide for the strip
        turns its own buttons onto extra lines.
        """
        rows = []
        for line in bands:
            while len(rows) <= line["row"]:
                rows.append(0)
            rows[line["row"]] = max(rows[line["row"]], line["row_h"])
        if not rows:
            rows = [self.small.get_height() + widgets.BAND_H]
        self.band_rows = rows
        budget = rect.height * 0.45 - TOOL_H - 8
        shown, tall = 0, 0
        for hgt in rows:
            if shown and tall + hgt + 10 > budget:
                break
            tall += hgt + 10
            shown += 1
        shown = max(1, shown)
        visible = sum(rows[:shown]) + 10 * (shown - 1)
        self.band_max = max(0, sum(rows) + 10 * (len(rows) - 1) - visible)
        self.band_scroll = max(0, min(self.band_scroll, self.band_max))
        for line in bands:
            line["frame"].y -= self.band_scroll
            for _item, box in line["buttons"]:
                box.y -= self.band_scroll
        return 8 + visible

    def _band_wheel(self, step):
        """Scroll the bands; True when there was anything to scroll."""
        if self.band_max <= 0:
            return False
        # one turn moves the tallest row clean off the strip
        unit = max(self.band_rows or [0]) + 10
        self.band_scroll = max(0, min(self.band_max,
                                      self.band_scroll - step * unit))
        return True

    def _layout_buttons(self, rect):
        """The 3D toolbar: captioned bands, then the name and sheet row."""
        bands, used = widgets.bands(
            pygame.Rect(rect.x, rect.y, rect.width, rect.height),
            self.small, self._groups())
        self.bands = bands
        self.bands_h = self._fit_bands(rect, bands, used)
        self.toolbar_h = self.bands_h + TOOL_H
        out = [{"rect": r, "label": item[0], "action": item[1],
                "active": item[2], "tip": item[3]}
               for row in bands for item, r in row["buttons"]]
        self.name_from = len(out)    # everything past here is the name row
        out += self._name_row(rect, rect.y + self.bands_h,
                              "the model's name - Enter saves it")
        return out

    def _draw_toolbar(self, surface, rect):
        self.bar_rect = pygame.Rect(rect)
        old_clip = surface.get_clip()
        surface.set_clip(rect)
        self.buttons = self._layout_buttons(rect) if self.model2d is None \
            else self._layout_flat_buttons(rect)
        top = rect.y + self.bands_h
        surface.fill(xp.FACE, (rect.x, rect.y, rect.width, self.toolbar_h))
        pygame.draw.line(surface, xp.SHADOW, (rect.x, top - 1),
                         (rect.right, top - 1))
        # the bands live in their own window: a scroll may hang one above it
        surface.set_clip(pygame.Rect(rect.x, rect.y, rect.width,
                                     self.bands_h))
        for row in self.bands:
            widgets.band(surface, row["frame"], row["caption"], self.small)
        self._draw_buttons(surface, self.buttons[:self.name_from])
        if self.band_max:
            # a thumb on the strip's edge says there is more of it
            frac = self.band_scroll / self.band_max
            page = self.bands_h / (self.bands_h + self.band_max)
            xp.scrollbar(surface, pygame.Rect(rect.right - 8, rect.y + 2, 6,
                                              self.bands_h - 4), frac, page)
        surface.set_clip(rect)
        self._draw_buttons(surface, self.buttons[self.name_from:])
        if self._document() is not None:
            # flat mode has no chip; the name field serves both
            self._draw_surface_chip(surface)
            self.name_field.draw(surface, self.name_rect, self.small,
                                 self.name_focus)
        img = widgets.cached_text(self.small, self._hint_text(),
                                  xp.TEXT_MUTED)
        if img is not None and \
                rect.right - 8 - img.get_width() > self.hint_x:
            surface.blit(img, (rect.right - 8 - img.get_width(),
                               top + TOOL_H // 2 - img.get_height() // 2))
        surface.set_clip(old_clip)
        self._draw_tip(surface)

    def _draw_buttons(self, surface, items):
        """Draw one run of toolbar buttons, the lit ones pressed in."""
        mouse = pygame.mouse.get_pos()
        for b in items:
            label = b["label"]
            if not label:
                continue
            if b["action"][0] == "objpos":
                rect = b["rect"]
                if self.grip is not None and \
                        self.grip[0] == b["action"]:
                    self.grip[1].draw(surface, rect, self.small)
                else:
                    xp.button(surface, rect, label, self.small,
                              hovered=rect.collidepoint(mouse))
                continue
            if b["action"] == ("paint", "size") and self.grip is not None \
                    and self.grip[0] == ("paint_size", None):
                self.grip[1].draw(surface, b["rect"], self.small)
                continue
            if b["action"] == ("none", None):
                img = widgets.cached_text(self.small, label, xp.TEXT_MUTED)
                if img:
                    surface.blit(img, (b["rect"].x + 4,
                                       b["rect"].centery -
                                       img.get_height() // 2))
                continue
            xp.button(surface, b["rect"], label, self.small,
                      default=b["active"],
                      hovered=b["rect"].collidepoint(mouse))

    def _draw_tip(self, surface):
        """One XP bubble for the toolbar button under the pointer."""
        mouse = pygame.mouse.get_pos()
        for b in self.buttons:
            if b.get("tip") and b["rect"].collidepoint(mouse):
                xp.tooltip(surface, mouse, [b["tip"]], self.small)
                return

    def _draw_surface_chip(self, surface):
        """The Colour chip: the target's tint, or a chequer."""
        if self.model2d is not None:
            return
        rect = self.color_rect
        got = colors.rgba(self.surface_color())
        if got is None:
            for j in range(0, rect.height, 4):
                for i in range(0, rect.width, 4):
                    shade = (150, 154, 164) if (i + j) % 8 else (90, 94, 104)
                    pygame.draw.rect(surface, shade,
                                     (rect.x + i, rect.y + j,
                                      min(4, rect.right - (rect.x + i)),
                                      min(4, rect.bottom - (rect.y + j))))
        else:
            pygame.draw.rect(surface, colors.bytes_rgb(got), rect)
        pygame.draw.rect(surface, xp.OUTLINE, rect, 1)

    def _hint_text(self):
        if self.model2d is not None:
            return (f"{len(self.model2d.parts)} parts  "
                    f"{len(self.model2d.tracks)} tracks")
        if self.model is None:
            return "pick a primitive to start"
        return (f"{len(self.model.verts)} v  {len(self.model.tris)} f  "
                f"mode {self.mode}" + (f"  axis {self.axis.upper()}"
                                       if self.axis else "  axis free"))

    def _viewport_inner(self):
        return self.inner

    def _local(self, pos):
        return (pos[0] - self.inner.x, pos[1] - self.inner.y)

    def _pick_vertex(self, cam, size, pos, radius=9.0):
        best = None
        for i, v in enumerate(self.model.verts):
            p = cam.project(v, size)
            if p is None:
                continue
            d = math.hypot(p[0] - pos[0], p[1] - pos[1])
            if d <= radius and (best is None or p[2] < best[0]):
                best = (p[2], i)
        return best[1] if best else None

    def _pick_face(self, cam, size, pos):
        hit = self._ray_face(cam, size, pos)
        return hit[1] if hit is not None else None

    def _ray_face(self, cam, size, pos):
        """Nearest visible triangle and its barycentric hit coordinates."""
        origin, direction = cam.ray(size, pos)
        best = None
        for fi, tri in enumerate(self.model.tris):
            a, b, c = (np.asarray(self.model.verts[i], np.float64)
                       for i in tri)
            edge1, edge2 = b - a, c - a
            pvec = np.cross(direction, edge2)
            det = float(np.dot(edge1, pvec))
            if abs(det) < 1e-8:
                continue
            inv_det = 1.0 / det
            tvec = origin - a
            u = float(np.dot(tvec, pvec)) * inv_det
            if u < 0.0 or u > 1.0:
                continue
            qvec = np.cross(tvec, edge1)
            v = float(np.dot(direction, qvec)) * inv_det
            if v < 0.0 or u + v > 1.0:
                continue
            distance = float(np.dot(edge2, qvec)) * inv_det
            if distance <= 0.0 or (best is not None and
                                   distance >= best[0]):
                continue
            point = origin + direction * distance
            best = (distance, fi, (1.0 - u - v, u, v), point)
        return best

    def _paint_uv_at(self, cam, size, pos):
        hit = self._ray_face(cam, size, pos)
        if hit is None or self.uvpaint is None:
            return None
        _distance, face, bary, _point = hit
        if self.uvpaint.objname:
            faces = self.uvpaint._object_faces()
            if faces is None or face not in faces:
                return None
        uv2 = getattr(self.model, "uv2", None)
        if not uv2:
            return None
        tri = self.model.tris[face]
        if any(index >= len(uv2) for index in tri):
            return None
        return tuple(sum(bary[i] * uv2[tri[i]][axis]
                         for i in range(3)) for axis in range(2))

    def _update_paint_preview(self):
        if self.renderer is None or self.model is None or self.uvpaint is None:
            return False
        session = self.uvpaint
        stamp = (id(session), session.revision, session.objname)
        if self._paint_preview_revision == stamp:
            return True
        key = self._paint_preview_key
        if session.objname:
            key = f"{key}:{session.objname}"
        try:
            self.renderer.texture(key, session.commit(),
                                  rgba=True, repeat=False, mipmaps=False)
        except Exception as exc:
            session.message = f"paint preview failed: {exc}"
            return False
        if session.objname and self.model.has_objects:
            for entry in self.model.objects:
                if entry["name"] == session.objname:
                    entry["texture"] = key
                    entry["painted"] = True
                    break
        else:
            self.model.texture = key
            self.model.painted = True
        self._paint_preview_revision = stamp
        self._refresh_mesh()
        return True

    def _selection_verts(self):
        if self.mode == "object":
            return list(range(len(self.model.verts)))
        if self.sel_face is not None and self.mode == "face":
            return list(self.model.tris[self.sel_face])
        return sorted(self.sel_verts)

    def _selection_centre(self, indices):
        if not indices:
            return (0.0, 0.0, 0.0)
        pts = [self.model.verts[i] for i in indices]
        return tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))

    def handle_event(self, e):
        for b in self.buttons:
            if b["action"] == ("none", None):
                continue
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and \
                    b["rect"].collidepoint(e.pos):
                self._run_action(b["action"])
                return True
        if self.grip is not None:
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    self.grip = None
                    return True
                result = self.grip[1].handle(e)
                if result in ("changed", "submit"):
                    if result == "submit":
                        self._commit_grip()
                    return True
            if e.type == pygame.KEYUP:
                return True
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and \
                    self.palette_rect.collidepoint(
                        getattr(e, "pos", pygame.mouse.get_pos())):
                # a shelf click lands the field it leaves
                self._commit_grip()
            else:
                return False
        pos = getattr(e, "pos", pygame.mouse.get_pos())
        if self.popup is not None:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                return self._popup_click(pos)
            if e.type == pygame.MOUSEBUTTONDOWN:
                self.popup = None
            return False
        if self.name_focus:
            result = self.name_field.handle(e)
            if result in ("changed", "submit"):
                if self.model is not None:
                    self.model.name = self.name_field.text.strip() or \
                        self.model.name
                    self.dirty = True
                elif self.model2d is not None:
                    self.model2d.name = self.name_field.text.strip() or \
                        self.model2d.name
                    self.dirty = True
                if result == "submit":
                    self.name_focus = False
                    self.save()
                return True
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                self.name_focus = False
                return True
        if self.obj_focus:
            # a retyped row owns keys until Enter or Escape
            result = self.obj_field.handle(e)
            if result in ("changed", "submit"):
                if result == "submit":
                    self._commit_rename()
                return True
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                self.rename_obj = None
                self.obj_focus = False
                return True
        if self.model2d is not None and e.type == pygame.KEYDOWN \
                and e.key == pygame.K_SPACE:
            self.toggle_play()
            return True

        if e.type == pygame.KEYDOWN:
            if self._key_down(e):
                return True

        if self.ui_mode == "uv" and self.uvpaint is not None:
            # the paint half owns its canvas, toolbar and keys
            return self.uvpaint.handle_event(e)

        if e.type == pygame.MOUSEWHEEL and self.bar_rect.width and \
                self.bar_rect.collidepoint(pos):
            # a strip taller than its window scrolls under the pointer
            if self._band_wheel(-e.y):
                return True
        if self.palette_rect.width and self.palette_rect.collidepoint(pos):
            # the shelf owns its clicks; they never reach the viewport
            if e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    return self._palette_click(pos)
                return True
            if e.type == pygame.MOUSEWHEEL:
                self._scroll_palette(-e.y * SWATCH_ROW)
                return True
            return e.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION)
        if self.obj_rect.width and self.obj_rect.collidepoint(pos):
            # the objects rail owns its clicks, exactly like the shelf
            if e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    return self._obj_click(pos, e)
                return True
            if e.type == pygame.MOUSEWHEEL:
                self._obj_wheel(-e.y * OBJ_ROW)
                return True
            return e.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION)
        if self.panel_rect.width and self.panel_rect.collidepoint(pos):
            # the parts panel owns its clicks, exactly like the shelf
            if e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    return self._panel_click(pos, e)
                return True
            if e.type == pygame.MOUSEWHEEL:
                self._panel_wheel(pos, -e.y * PART_ROW)
                return True
            return e.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION)
        if self.model2d is not None and e.type == pygame.MOUSEWHEEL:
            self._flat_wheel(pos, e.y)
            return True
        if self._document() is None or not self.viewport.collidepoint(pos):
            if e.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                return self._mouse_global(e)
            return False

        if e.type == pygame.MOUSEBUTTONDOWN:
            return self._mouse_down(e)
        if e.type == pygame.MOUSEMOTION:
            return self._mouse_move(e)
        if e.type == pygame.MOUSEBUTTONUP:
            if e.button in (1, 2, 3) and self.drag is not None:
                self.drag = None
                return True
        if e.type == pygame.MOUSEWHEEL:
            self.orbit.zoom(e.y)
            return True
        return False

    def _mouse_global(self, e):
        if e.type == pygame.MOUSEMOTION and self.drag is not None:
            return self._mouse_move(e)
        if e.type == pygame.MOUSEBUTTONUP and self.drag is not None:
            # every drag ends where it was dropped, in either mode
            self.drag = None
            return True
        return False

    def _key_down(self, e):
        if self.model2d is not None:
            # flat keys, apart from 3D so a rig cannot shape
            if e.key == pygame.K_DELETE:
                self.delete_part()
                return True
            if e.key == pygame.K_HOME:
                self.frame_flat()
                return True
            if e.key == pygame.K_g:
                self.snap = not self.snap
                self.message = f"snap {'on' if self.snap else 'off'}"
                return True
            return False
        mod = getattr(e, "mod", 0)
        ctrl = bool(mod & pygame.KMOD_CTRL)
        if self.ui_mode == "uv":
            # the paint half reads its keys; only Ctrl+S is ours
            if ctrl and e.key == pygame.K_s:
                self.save()
                return True
            return False
        if ctrl and e.key == pygame.K_s:
            self.save()
            return True
        if ctrl and e.key == pygame.K_z:
            self.undo_last()
            return True
        if ctrl and e.key == pygame.K_y:
            self.redo_last()
            return True
        if e.key in (pygame.K_1, pygame.K_KP1):
            self.mode = "object"
            return True
        if e.key in (pygame.K_2, pygame.K_KP2):
            self.mode = "vertex"
            return True
        if e.key in (pygame.K_3, pygame.K_KP3):
            self.mode = "face"
            return True
        for axis in ("x", "y", "z"):
            if e.key == getattr(pygame, "K_" + axis):
                self.axis = None if self.axis == axis else axis
                return True
        if e.key == pygame.K_ESCAPE:
            if self.sel_verts or self.sel_face is not None \
                    or self.sel_faces:
                self.sel_verts.clear()
                self.sel_face = None
                self.sel_faces.clear()
                return True
            return False
        if e.key == pygame.K_DELETE:
            self.delete_selection()
            return True
        if e.key == pygame.K_e:
            self.extrude()
            return True
        if e.key == pygame.K_f:
            self.make_face()
            return True
        if e.key == pygame.K_g:
            self.snap = not self.snap
            return True
        if e.key == pygame.K_w and not ctrl:
            self.wire = not self.wire
            return True
        if e.key == pygame.K_t and not ctrl:
            self.set_ui_mode("edit" if self.ui_mode == "texture"
                             else "texture")
            return True
        if e.key == pygame.K_HOME:
            self.frame_view()
            return True
        if e.key == pygame.K_c and not ctrl:
            self._act_color()
            return True
        return False

    def _flat_mouse_down(self, e):
        """One flat-viewport click: pick, drag, pan or scrub."""
        if self.playing:
            self.toggle_play()
        if e.button in (2, 3):
            self.drag = {"kind": "fpan", "origin": e.pos}
            return True
        if e.button != 1:
            return False
        if self._playhead_hit(e.pos):
            self._scrub(e.pos)
            self.drag = {"kind": "scrub"}
            return True
        shift = widgets.shift_held(e)
        index = self._pick_part(e.pos)
        if index is None:
            # an empty Shift click orbits and keeps the pick
            if not shift:
                self._select_part(None)
            self.drag = {"kind": "fpan", "origin": e.pos}
            return True
        if shift:
            self.toggle_part(index)
        else:
            self._select_part(index)
        # remember where the pointer grabbed, so the first move counts
        self.drag = {"kind": "none", "at": self._pointer_world(e.pos)}
        return True

    def _mouse_down(self, e):
        self.name_focus = False
        if self.rename_obj is not None:
            self._commit_rename()
        if self.model2d is not None:
            return self._flat_mouse_down(e)
        local = self._local(e.pos)
        size = self.inner.size
        cam = self.orbit.camera()
        if self.model is None:
            return False
        if e.button == 2:
            self.drag = {"kind": "orbit", "origin": e.pos}
            return True
        if e.button == 3:
            self.drag = {"kind": "pan", "origin": e.pos}
            return True
        if e.button != 1:
            return False
        shift = widgets.shift_held(e)

        if self.ui_mode == "texture":
            # the brush needs a face: click fills, drag paints
            fi = self._pick_face(cam, size, local)
            if fi is None:
                self.drag = {"kind": "orbit", "origin": e.pos}
                return True
            if not self.paint_on or not self.paint_key:
                self.sel_face = fi
                self.sel_verts = set(self.model.tris[fi])
                self.message = ("pick a sheet on the right" if not
                                self.paint_key else
                                "Paint is off - turn it on, or use the "
                                "palette")
                return True
            if self.paint_all:
                self.fill_all(self.paint_key)
                return True
            self._push_undo()
            self.drag = {"kind": "paint", "origin": e.pos, "face": fi}
            self._paint_face(fi)
            return True

        if self.mode == "vertex":
            grab = self._gizmo_axis_at(cam, size, local) if self.sel_verts \
                else None
            if grab is not None:
                # an arm press locks an axis and drags picked verts
                self.axis = grab
                self._start_drag(local, size, cam,
                                 indices=sorted(self.sel_verts))
                return True
            vi = self._pick_vertex(cam, size, local)
            if vi is not None:
                if shift:
                    if vi in self.sel_verts:
                        self.sel_verts.discard(vi)
                    else:
                        self.sel_verts.add(vi)
                elif vi not in self.sel_verts:
                    self.sel_verts = {vi}
                self.sel_face = None
                self.sel_faces.clear()
                if vi in self.sel_verts:
                    self._start_drag(local, size, cam,
                                     indices=sorted(self.sel_verts))
                return True
        elif self.mode == "face":
            fi = self._pick_face(cam, size, local)
            if fi is not None:
                if shift:
                    # Shift grows the face set; the drag moves its union
                    if fi in self.sel_faces:
                        self.sel_faces.discard(fi)
                    else:
                        self.sel_faces.add(fi)
                    self.sel_face = (fi if fi in self.sel_faces
                                     else (max(self.sel_faces)
                                           if self.sel_faces else None))
                    self.sel_verts = {v for f in self.sel_faces
                                      for v in self.model.tris[f]}
                    if fi in self.sel_faces:
                        self._start_drag(local, size, cam,
                                         indices=sorted(self.sel_verts))
                    return True
                self.sel_faces = {fi}
                self.sel_face = fi
                self.sel_verts = set(self.model.tris[fi])
                self._start_drag(local, size, cam,
                                 indices=list(self.model.tris[fi]))
                return True
        elif self.mode == "object":
            indices = self._object_drag_verts()
            grab = self._gizmo_axis_at(cam, size, local) if indices else None
            if grab is not None:
                self.axis = grab
                self._start_drag(local, size, cam, indices=indices)
                return True
            hit = self._ray_face(cam, size, local)
            if hit is None:
                self.drag = {"kind": "orbit", "origin": e.pos}
                return True
            face = hit[1]
            if self.model.has_objects:
                owner = next((o["name"] for o in self.model.objects
                              if face in o["faces"]), None)
                if owner is None:
                    self.drag = {"kind": "orbit", "origin": e.pos}
                    return True
                self.select_object(owner, toggle=shift)
                if shift and owner not in self.sel_objs:
                    return True
            else:
                self.sel_verts = set(range(len(self.model.verts)))
            indices = self._object_drag_verts()
            if indices:
                self._start_drag(local, size, cam, indices=indices)
            else:
                self.drag = {"kind": "orbit", "origin": e.pos}
            return True

        # empty space: orbit and clear, unless Shift holds the set
        if not (shift and self.mode == "face"):
            self.sel_verts.clear()
            self.sel_face = None
            self.sel_faces.clear()
        self.drag = {"kind": "orbit", "origin": e.pos}
        return True

    def _start_drag(self, local, size, cam, indices):
        anchor = self._selection_centre(indices)
        start_hit = cam.plane_hit(size, local, anchor, cam.forward())
        if start_hit is None:
            return
        self._push_undo()
        self.drag = {
            "kind": "verts",
            "indices": list(indices),
            "anchor": anchor,
            "normal": tuple(cam.forward()),
            "start_hit": tuple(start_hit),
            "start_pos": {i: tuple(self.model.verts[i]) for i in indices},
            "origin": None,
        }

    def _mouse_move(self, e):
        if self.drag is None:
            return False
        kind = self.drag["kind"]
        if kind == "parts":
            self._move_parts_drag(e.pos)
            return True
        if kind == "fpan":
            self._flat_pan(e.rel)
            return True
        if kind == "scrub":
            self._scrub(e.pos)
            return True
        if kind == "none":
            # a dragged flat pick becomes a parts move
            if self.model2d is not None and self.sel_parts:
                self._start_parts_drag(e.pos, at=self.drag.get("at"))
                self._move_parts_drag(e.pos)
            return True
        if kind == "orbit":
            self.orbit.orbit(e.rel[0], e.rel[1])
            return True
        if kind == "pan":
            self.orbit.pan(e.rel[0], e.rel[1], self.inner.size)
            return True
        if kind == "paint":
            local = self._local(e.pos)
            fi = self._pick_face(self.orbit.camera(), self.inner.size, local)
            if fi is None or fi == self.drag.get("face"):
                return True
            self.drag["face"] = fi
            self._paint_face(fi)
            return True
        local = (e.pos[0] - self.inner.x, e.pos[1] - self.inner.y)
        cam = self.orbit.camera()
        hit = cam.plane_hit(self.inner.size, local, self.drag["anchor"],
                            self.drag["normal"])
        if hit is None:
            return True
        start = np.asarray(self.drag["start_hit"], np.float64)
        delta = np.asarray(hit, np.float64) - start
        if self.axis:
            axis = np.asarray(AXIS_VECTORS[self.axis], np.float64)
            delta = axis * float(delta @ axis)
        object_move = self.mode == "object"
        if self.snap and object_move:
            delta = np.round(delta / self.snap_step) * self.snap_step
        for i, base in self.drag["start_pos"].items():
            v = np.asarray(base, np.float64) + delta
            if self.snap and not object_move:
                v = np.round(v / self.snap_step) * self.snap_step
            self.model.verts[i] = [float(v[0]), float(v[1]), float(v[2])]
        self.dirty = True
        self._refresh_mesh()
        return True

    def _run_action(self, action):
        kind, value = action
        if self.model2d is not None and kind in ("mode", "prim", "axis",
                                                 "tex"):
            self.message = "this is a 2D rig - the shape tools do not fit"
            return
        if kind == "ui":
            self.set_ui_mode(value)
        elif kind == "mode":
            self.mode = value
            self.sel_face = None if value != "face" else self.sel_face
            if value != "face":
                self.sel_faces.clear()
            if value == "object":
                self.sel_verts.clear()
        elif kind == "prim":
            # a shape click joins the open model, else starts one
            self.add_primitive(value)
        elif kind == "toggle":
            if value == "snap":
                self.snap = not self.snap
            elif value == "wire":
                self.wire = not self.wire
            elif value == "paint":
                self.paint_on = not self.paint_on
            elif value == "paintall":
                self.paint_all = not self.paint_all
            elif value == "play":
                self.toggle_play()
        elif kind == "flat":
            getattr(self, value)()
        elif kind == "axis":
            self.axis = value
        elif kind == "objpos":
            point = self._object_position()
            if point is None:
                self.message = "select an object before setting its position"
                return
            self.grip = (("objpos", value),
                         widgets.TextField(f"{point['xyz'.index(value)]:g}",
                                           20))
        elif kind == "paint":
            if self.uvpaint is None:
                self.message = "enter paint mode first"
            elif value == "color":
                self.pick_paint_color(self.uvpaint)
            elif value == "size":
                self.grip = (("paint_size", None),
                             widgets.TextField(str(self.uvpaint.brush), 12))
            elif value == "smaller":
                self.uvpaint.brush = max(1, self.uvpaint.brush - 2)
            elif value == "larger":
                self.uvpaint.brush = min(256, self.uvpaint.brush + 2)
            else:
                self.uvpaint.tool = value
        elif kind == "tex":
            self.cycle_texture(value)
        elif kind == "focus_name":
            self.name_focus = True
        elif kind == "action":
            getattr(self, "_act_" + value, lambda: None)()

    def _act_save(self):
        self.save()

    def _act_new(self):
        """Start a fresh model, replacing whatever tab is open."""
        self.new_model("box")

    def _act_newmap(self):
        """Start a fresh map, saved into maps/."""
        self.new_map("box")

    def _act_askind(self):
        """Turn the open document into a map, or back into a plain model.

        A map is a model filed under maps/ and carved into objects, since
        an object is what carries its own sheet, its own lightmap and its
        own hiding. The way round this document goes is the next Save.
        """
        if self.model is None:
            self.message = "pick a model or a map first"
            return
        self.is_map = not self.is_map
        if self.is_map:
            if not self.model.objects:
                self._wrap_object(self.model.name or "main")
            self.message = "a map now - Save files it under maps/"
        else:
            self.message = "a model now - Save files it under models/"
        self.dirty = True

    def _act_reload(self):
        if self.path:
            self.open(self.path)
        else:
            self.app.log("unsaved model has no file to reload", "warn")

    def _act_delete(self):
        self.delete_selection()

    def _act_extrude(self):
        self.extrude()

    def _act_makeface(self):
        self.make_face()

    def _act_flip(self):
        self.flip_faces()

    def _act_weld(self):
        self.weld()

    def _act_autouv(self):
        self.auto_uv()

    def _act_frame(self):
        self.frame_view()

    def _act_undo(self):
        self.undo_last()

    def _act_redo(self):
        self.redo_last()

    def _act_clear(self):
        """Hand every face back to the model's own sheet."""
        if self.model is None:
            return
        self._push_undo()
        for fi in range(len(self.model.tris)):
            self.model.set_face_texture(fi, None)
        self.sel_face = None
        self.sel_verts.clear()
        self.dirty = True
        self._refresh_mesh()
        self.message = f"faces back to {self.model.texture}"

    def _act_color(self):
        """Open the picker for whatever the current selection means."""
        if self.model is None:
            self.message = "pick a primitive first"
            return
        faces = self.target_faces()
        where = f"{len(faces)} face(s)" if faces is not None \
            else "whole model"
        self.app.pick_color(
            f"Surface colour - {where}", self.surface_color(),
            self.apply_color,
            hint="Hex, rgb(...), a name like torch, or None for the default.")

    def _push_undo(self):
        if self.model2d is not None:
            self.undo.append((self._flat_snap(), self.sel_part,
                              list(self.sel_parts)))
            if len(self.undo) > 80:
                self.undo.pop(0)
            self.redo.clear()
            return
        if self.model is None:
            return
        self.undo.append((self.model.snapshot(), set(self.sel_verts),
                          self.sel_face, set(self.sel_faces)))
        if len(self.undo) > 80:
            self.undo.pop(0)
        self.redo.clear()

    def undo_last(self):
        if not self.undo:
            return
        if self.model2d is not None:
            self.redo.append((self._flat_snap(), self.sel_part,
                              list(self.sel_parts)))
            snap, sel, parts = self.undo.pop()
            self._flat_restore(snap)
            self.sel_part = sel
            self.sel_parts = parts
            self.dirty = True
            return
        if self.model is None:
            return
        self.redo.append((self.model.snapshot(), set(self.sel_verts),
                          self.sel_face, set(self.sel_faces)))
        snap, sel, face, faces = self.undo.pop()
        self.model.restore(snap)
        self.sel_verts = set(sel)
        self.sel_face = face
        self.sel_faces = set(faces)
        self.dirty = True
        self._refresh_mesh()

    def redo_last(self):
        if not self.redo:
            return
        if self.model2d is not None:
            self.undo.append((self._flat_snap(), self.sel_part,
                              list(self.sel_parts)))
            snap, sel, parts = self.redo.pop()
            self._flat_restore(snap)
            self.sel_part = sel
            self.sel_parts = parts
            self.dirty = True
            return
        if self.model is None:
            return
        self.undo.append((self.model.snapshot(), set(self.sel_verts),
                          self.sel_face, set(self.sel_faces)))
        snap, sel, face, faces = self.redo.pop()
        self.model.restore(snap)
        self.sel_verts = set(sel)
        self.sel_face = face
        self.sel_faces = set(faces)
        self.dirty = True
        self._refresh_mesh()

    def delete_selection(self):
        if self.model2d is not None:
            self.delete_part()
            return
        if self.model is None:
            return
        self._push_undo()
        if self.mode == "face" and self.sel_face is not None:
            self.model.delete_faces([self.sel_face])
            self.sel_face = None
        elif self.sel_verts:
            self.model.delete_vertices(self.sel_verts)
            self.sel_verts.clear()
        else:
            self.message = "nothing selected"
        self.dirty = True
        self._refresh_mesh()

    def extrude(self):
        if self.model2d is not None:
            return
        if self.model is None:
            return
        face = self.sel_face
        if face is None and self.mode == "vertex" and self.sel_verts:
            faces = self.model.faces_using(self.sel_verts)
            face = faces[0] if faces else None
        if face is None:
            self.message = "select a face to extrude"
            return
        self._push_undo()
        self.model.extrude(face, 0.25)
        self.sel_face = None
        self.dirty = True
        self._refresh_mesh()
        self.message = "extruded"

    def make_face(self):
        if self.model2d is not None:
            return
        if self.model is None or len(self.sel_verts) < 3:
            self.message = "shift-click 3+ vertices, then Face"
            return
        order = sorted(self.sel_verts)
        self._push_undo()
        created = 0
        for i in range(1, len(order) - 1):
            if self.model.add_face(order[0], order[i], order[i + 1]):
                created += 1
        self.dirty = True
        self._refresh_mesh()
        self.message = f"added {created} face(s)"

    def flip_faces(self):
        if self.model is None:
            return
        self._push_undo()
        if self.sel_face is not None:
            self.model.flip_face(self.sel_face)
        elif self.sel_verts:
            for fi in self.model.faces_using(self.sel_verts):
                self.model.flip_face(fi)
        else:
            for fi in range(len(self.model.tris)):
                self.model.flip_face(fi)
        self.dirty = True
        self._refresh_mesh()

    def weld(self):
        if self.model is None:
            return
        before = len(self.model.verts)
        self._push_undo()
        self.model.weld()
        self.sel_verts.clear()
        self.sel_face = None
        self.dirty = True
        self._refresh_mesh()
        self.message = f"welded {before - len(self.model.verts)} vertices"

    def auto_uv(self):
        if self.model is None:
            return
        self._push_undo()
        faces = self._sel_obj_faces()
        self.model.auto_uv(faces=faces)
        self.dirty = True
        self._refresh_mesh()
        self.message = "uvs reprojected" + (f" ({self.sel_obj})"
                                            if faces else "")

    def frame_view(self):
        if self.model2d is not None:
            self.frame_flat()
            return
        if self.model is not None:
            self.orbit.frame(self.model.bounds())

    def draw(self, surface, rect):
        rect = pygame.Rect(rect)
        pygame.draw.rect(surface, xp.FACE, rect)
        if self.model2d is not None:
            self._draw_flat(surface, rect)
            return
        if self.ui_mode == "uv" and self.uvpaint is not None \
                and self.uvpaint.has_edits:
            if not self._update_paint_preview():
                self.message = self.uvpaint.message
        self._draw_toolbar(surface, rect)
        top = rect.y + self.toolbar_h
        body = pygame.Rect(rect.x, top, rect.width,
                           max(10, rect.bottom - top))
        if self.ui_mode == "uv" and self.uvpaint is not None:
            # the paint half fills the body with canvas and preview
            self.palette_rect = pygame.Rect(0, 0, 0, 0)
            self.palette_rows = []
            self.viewport = body
            self.uvpaint.draw(surface, body)
            if self.popup is not None:
                self._draw_flat_popup(surface)
            return
        # the shelf only earns its width if a viewport fits
        shelf = self.ui_mode == "texture" and body.width > PALETTE_W + 160
        rail = (self.ui_mode == "edit" and self.model is not None
                and body.width > OBJ_W + 200)
        self.palette_rect = pygame.Rect(0, 0, 0, 0)
        self.palette_rows = []
        self.obj_rect = pygame.Rect(0, 0, 0, 0)
        inset = 0
        if shelf:
            inset = PALETTE_W
            self.palette_rect = pygame.Rect(body.right - PALETTE_W, body.y,
                                            PALETTE_W, body.height)
        elif rail:
            inset = OBJ_W
            self.obj_rect = pygame.Rect(body.right - OBJ_W, body.y,
                                        OBJ_W, body.height)
        self.viewport = pygame.Rect(body.x, body.y,
                                    body.width - inset, body.height)
        self._draw_viewport(surface, self.viewport)
        if shelf:
            self._draw_palette(surface)
        elif rail:
            self._draw_objects(surface)
        if self.popup is not None:
            # the shelf's fields open their menus over everything else
            self._draw_flat_popup(surface)

    def _draw_flat(self, surface, rect):
        """The whole flat tab: three toolbar rows, the rig viewport,"""
        self._advance_anim()
        # clear the 3D shelf, or its stale rect claims clicks
        self.palette_rect = pygame.Rect(0, 0, 0, 0)
        self.palette_rows = []
        self._draw_toolbar(surface, rect)
        top = rect.y + self.toolbar_h
        body = pygame.Rect(rect.x, top, rect.width,
                           max(10, rect.bottom - top))
        if body.width > PART_W + 160:
            self.panel_rect = pygame.Rect(body.right - PART_W, body.y,
                                          PART_W, body.height)
            self.viewport = pygame.Rect(body.x, body.y,
                                        body.width - PART_W, body.height)
        else:
            # too narrow for a panel: the viewport takes the tab
            self.panel_rect = pygame.Rect(0, 0, 0, 0)
            self.part_add_rect = pygame.Rect(0, 0, 0, 0)
            self.part_duplicate_rect = pygame.Rect(0, 0, 0, 0)
            self.part_delete_rect = pygame.Rect(0, 0, 0, 0)
            self.viewport = body
        self._draw_flat_viewport(surface, self.viewport)
        if self.panel_rect.width:
            self._draw_flat_panel(surface)
        if self.popup is not None:
            self._draw_flat_popup(surface)

    def _flat_groups(self):
        """The 2D rig toolbar as captioned bands, same shape as `_groups`."""
        return [
            ("Rig", [("2D cutout", ("none", None), False,
                      "a flat cutout rig, edited in this tab")]),
            ("Objects", [
                ("Add", ("flat", "add_part"), False,
                 "a new 2D object part, on top of the picked one"),
                ("Duplicate", ("flat", "duplicate_part"), False,
                 "copy the picked part (Ctrl+D)"),
                ("Delete", ("flat", "delete_part"), False,
                 "remove the picked part and its keys (Del)"),
                ("Back", ("flat", "layer_back"), False, "one layer down"),
                ("Forward", ("flat", "layer_fwd"), False,
                 "one layer up")]),
            ("Anim", [
                ("Play", ("toggle", "play"), self.playing,
                 "run the tracks (Space)"),
                ("Key", ("flat", "key_part"), False,
                 "write the part's rot as a key at the playhead"),
                ("Prev", ("flat", "key_prev"), False, "previous key"),
                ("Next", ("flat", "key_next"), False, "next key"),
                ("Del key", ("flat", "delete_key"), False,
                 "remove the key at the playhead")]),
            ("File", [
                ("Save", ("action", "save"), False, "Save the rig (Ctrl+S)"),
                ("Reload", ("action", "reload"), False,
                 "Rebuild from the file on disk"),
                ("Undo", ("action", "undo"), False, "Undo (Ctrl+Z)"),
                ("Redo", ("action", "redo"), False, "Redo (Ctrl+Y)")]),
            ("Move", [
                ("Snap", ("toggle", "snap"), self.snap,
                 f"drag snaps to {self.snap_step} rig pixels (G)")]),
            ("View", [
                ("Frame", ("action", "frame"), False, "fit the rig (Home)")]),
        ]

    def _layout_flat_buttons(self, rect):
        """The flat toolbar: the same bands, then the name row."""
        bands, used = widgets.bands(
            pygame.Rect(rect.x, rect.y, rect.width, rect.height),
            self.small, self._flat_groups())
        self.bands = bands
        self.bands_h = self._fit_bands(rect, bands, used)
        used = self.bands_h
        self.toolbar_h = used + TOOL_H
        out = [{"rect": r, "label": item[0], "action": item[1],
                "active": item[2], "tip": item[3]}
               for row in bands for item, r in row["buttons"]]
        self.name_from = len(out)
        chip = pygame.Rect(rect.x + 6, rect.y + used + 3, 34, TOOL_H - 6)
        out.append({"rect": chip, "label": "Name", "action": ("none", None),
                    "active": False, "tip": "rig name"})
        wide = max(64, min(160, rect.width - 120))
        self.name_rect = pygame.Rect(chip.right + 4, rect.y + used + 2, wide,
                                     TOOL_H - 4)
        out.append({"rect": self.name_rect, "label": "",
                    "action": ("focus_name", None), "active": self.name_focus,
                    "tip": "the rig's name, and its degrees of turn - "
                           "what a Sprite2D node would carry"})
        self.hint_x = self.name_rect.right + 12
        out.append({"rect": pygame.Rect(self.hint_x, rect.y + used + 2,
                                        14, TOOL_H - 4),
                    "label": "", "action": ("none", None), "active": False,
                    "tip": "drag a part  shift-drag = no snap  wheel zooms  "
                           "middle-drag pans  Space plays"})
        return out

    def toggle_play(self):
        if self.model2d is None:
            return
        self.playing = not self.playing
        if self.playing:
            self._play_at = pygame.time.get_ticks()
            self.drag = None
        self.message = ("playing" if self.playing else "stopped") + \
                       f" at {self.play_t:.2f}s"

    def _draw_flat_viewport(self, surface, viewport):
        pygame.draw.rect(surface, (26, 30, 36), viewport)
        xp.sunken(surface, viewport)
        self.inner = viewport.inflate(-2, -2)
        self.part_rows = []
        self.prop_fields = []
        if self.inner.width < 4 or self.inner.height < 4:
            return
        old_clip = surface.get_clip()
        surface.set_clip(self.inner)
        self._draw_flat_grid(surface)
        self._draw_flat_parts(surface)
        self._draw_playhead(surface)
        self._draw_flat_hud(surface)
        surface.set_clip(old_clip)

    def _draw_flat_grid(self, surface):
        """The rig box in rig pixels, with a checker behind."""
        m = self.model2d
        z = self.flat_view["zoom"]
        ox, oy = self._rig_origin()
        step = max(16, int(40 / z) * 16)
        span = max(m.size[0], m.size[1])
        colour = (38, 43, 51)
        x = -span
        while x <= span:
            a = self._corner_local(0, 0, 0, 0, (ox + z * x, oy),
                                   self._rig_rot())
            b = self._corner_local(0, 0, 0, 0, (ox + z * x, oy + z * span),
                                   self._rig_rot())
            if a[0] > self.inner.x - 2 and a[0] < self.inner.right + 2:
                pygame.draw.line(surface, colour, a, b)
            x += step
        y = -span
        while y <= span:
            a = self._corner_local(0, 0, 0, 0, (ox, oy + z * y),
                                   self._rig_rot())
            b = self._corner_local(0, 0, 0, 0, (ox + z * span, oy + z * y),
                                   self._rig_rot())
            if a[1] > self.inner.y - 2 and a[1] < self.inner.bottom + 2:
                pygame.draw.line(surface, colour, a, b)
            y += step
        # the checker scrolls with the world, not the screen
        tile = max(8, int(round(z * 8)))
        k0 = int((self.inner.x - ox) // tile) - 1
        r0 = int((self.inner.y - oy) // tile) - 1
        k = k0
        while ox + k * tile < self.inner.right:
            x = ox + k * tile
            r = r0
            while oy + r * tile < self.inner.bottom:
                y = oy + r * tile
                if (k + r) % 2:
                    pygame.draw.rect(surface, (31, 35, 42),
                                     (int(x), int(y), tile, tile))
                r += 1
            k += 1
        corners = [self._corner_local(z * m.size[0], z * m.size[1],
                                      u, v, (ox, oy), self._rig_rot())
                   for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
        pygame.draw.polygon(surface, (120, 132, 150), corners, 1)

    def _draw_flat_parts(self, surface):
        """Every part in file order: first back, last top."""
        m = self.model2d
        t = self.play_t
        for i, part in enumerate(m.parts):
            if not self._part_shown(part):
                continue
            sx, sy = self._part_scale(part)
            w, h = m.size[0] * sx, m.size[1] * sy
            if w <= 0.0 or h <= 0.0:
                continue
            uv = [float(c) for c in (part.get("uv") or UV_DEFAULT)]
            while len(uv) < 4:
                uv.append(1.0)
            x, y, prot = self._world_of(part, t)
            key = part.get("texture") or m.texture or "white"
            tint = colors.rgba(key)
            size = (max(1, int(round(w * self.flat_view["zoom"]))),
                    max(1, int(round(h * self.flat_view["zoom"]))))
            sheet = self._sheet_surf(key)
            if sheet is not None:
                sw, sh = sheet.get_size()
                crop = pygame.Rect(int(uv[0] * sw), int(uv[1] * sh),
                                   max(1, int((uv[2] - uv[0]) * sw)),
                                   max(1, int((uv[3] - uv[1]) * sh)))
                crop = crop.clip(sheet.get_rect()) or \
                    pygame.Rect(0, 0, 1, 1)
            else:
                crop = pygame.Surface((1, 1), 0, surface)
                crop.fill(colors.bytes_rgb(tint) if tint
                          else (236, 236, 236))
            piece = pygame.transform.smoothscale(
                sheet.subsurface(crop) if sheet is not None else crop, size)
            angle = -math.degrees(prot)
            if abs(angle % 360) > 1e-6:
                piece = pygame.transform.rotate(piece, angle)
            rect = piece.get_rect(center=(int(round(x)), int(round(y))))
            surface.blit(piece, rect)
            self._draw_uv_corners(surface, part, w, h, uv, (x, y), prot)
            if i == self.sel_part or i in self.sel_parts:
                outline = [self._corner_local(w, h, u, v, (x, y), prot)
                           for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
                pygame.draw.polygon(surface, (12, 14, 18), outline, 4)
                pygame.draw.polygon(surface, (255, 196, 64), outline, 1)
            label = widgets.cached_text(self.small, str(
                part.get("name") or i), (226, 230, 238))
            if label is not None:
                surface.blit(label, (rect.x + 2, rect.y - 1))

    def _draw_uv_corners(self, surface, part, w, h, uv, centre, prot):
        """The crop's own corners, so a uv edit shows."""
        if self.model2d is None:
            return
        spec = ("uv", "uv", "vec", self.sel_part, 0)
        if self.grip is None or self.grip[0] != spec:
            return
        pts = [self._corner_local(w, h, uv[0] if u == 0 else uv[2],
                                  uv[1] if v == 0 else uv[3], centre, prot)
               for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))]
        for p in pts:
            box = pygame.Rect(0, 0, 5, 5)
            box.center = (int(p[0]), int(p[1]))
            pygame.draw.rect(surface, (110, 225, 255), box, 1)

    def _draw_playhead(self, surface):
        """The thin time line; drag it to pose the rig."""
        m = self.model2d
        length = self.track_len()
        line = self.inner.bottom - 14
        pygame.draw.line(surface, (58, 64, 74),
                         (self.inner.x + 8, line),
                         (self.inner.right - 8, line), 2)
        name = self.get_part().get("name")
        for tr in m.tracks:
            for k in tr.get("keys") or ():
                if not k or length <= 0.0:
                    continue
                x = self.inner.x + 8 + (float(k[0]) / length) * \
                    (self.inner.width - 16)
                mine = tr.get("part") == name
                top = line - (6 if mine else 3)
                colour = (255, 196, 64) if mine else (140, 148, 160)
                pygame.draw.line(surface, colour, (x, top), (x, line + 3))
        if length > 0.0:
            x = self.inner.x + 8 + (self.play_t / length) * \
                (self.inner.width - 16)
            pygame.draw.line(surface, (235, 240, 250),
                             (x, self.inner.top + 4), (x, line + 6))
            box = pygame.Rect(0, 0, 9, 9)
            box.center = (int(x), line)
            pygame.draw.rect(surface, (235, 240, 250), box, 1)
        img = widgets.cached_text(self.small, f"{self.play_t:.2f}s",
                                  (196, 200, 208))
        if img is not None:
            surface.blit(img, (self.inner.x + 10,
                               line - img.get_height() - 2))

    def _draw_flat_hud(self, surface):
        strip = pygame.Rect(self.inner.x, self.inner.bottom - 17,
                           self.inner.width, 17)
        pygame.draw.rect(surface, (24, 28, 34), strip)
        hint = self.message or ("drag a part  Shift picks more  "
                                "wheel zooms  Space plays  "
                                "click a value to edit it")
        img = widgets.cached_text(self.small, hint, (214, 218, 226))
        if img is not None:
            surface.blit(img, (strip.x + 6,
                               strip.centery - img.get_height() // 2))
        m = self.model2d
        info = (f"{m.size[0]:g}x{m.size[1]:g}  "
                f"{(self.flat_view['zoom'] * 100 / 3):.0f}%  "
                f"{m.texture or 'white'}")
        part = self.get_part()
        if part:
            p = part.get("pos") or POS_DEFAULT
            info += (f"  [{part.get('name')} "
                     f"{float(p[0]):g},{float(p[1]):g}]")
        img = widgets.cached_text(self.small, info, (196, 200, 208))
        if img is not None:
            surface.blit(img, (strip.right - img.get_width() - 6,
                               strip.centery - img.get_height() // 2))

    def _draw_flat_panel(self, surface):
        """The right-hand object dock: list and controls above properties."""
        area = self.panel_rect
        pygame.draw.rect(surface, xp.FACE, area)
        pygame.draw.line(surface, xp.SHADOW, (area.x, area.y),
                         (area.x, area.bottom))
        n = len(self.model2d.parts)
        head = pygame.Rect(area.x + 1, area.y, area.width - 1, 22)
        widgets.header(surface, head, "Objects", self.small, right=str(n))
        buttons_y = head.bottom + 3
        buttons = pygame.Rect(area.x + 4, buttons_y, area.width - 8, 22)
        gap = 3
        button_w = max(1, (buttons.width - gap * 2) // 3)
        self.part_add_rect = pygame.Rect(buttons.x, buttons.y, button_w, 22)
        self.part_duplicate_rect = pygame.Rect(
            self.part_add_rect.right + gap, buttons.y, button_w, 22)
        self.part_delete_rect = pygame.Rect(
            self.part_duplicate_rect.right + gap, buttons.y,
            buttons.right - self.part_duplicate_rect.right - gap, 22)
        mouse = pygame.mouse.get_pos()
        for box, label, enabled, tip in (
                (self.part_add_rect, "Add", True, "Add a new 2D object part"),
                (self.part_duplicate_rect, "Duplicate",
                 self.sel_part is not None, "Duplicate the selected part"),
                (self.part_delete_rect, "Delete",
                 self.sel_part is not None, "Delete the selected part")):
            xp.button(surface, box, label, self.small,
                      hovered=box.collidepoint(mouse) and enabled,
                      enabled=enabled)
            if box.collidepoint(mouse):
                xp.tooltip(surface, mouse, [tip], self.small)
        list_top = buttons.bottom + 3
        parts_h = min(max(PART_ROW * 4, n * PART_ROW + 6),
                      max(0, area.bottom - list_top - 140))
        body = pygame.Rect(area.x + 4, list_top, area.width - 8, parts_h)
        pygame.draw.rect(surface, xp.FIELD, body)
        xp.sunken(surface, body)
        self.parts_body = body
        self.parts_scroll = max(0, min(self._parts_max(),
                                       self.parts_scroll))
        old = widgets.clip(surface, body.inflate(-2, -2))
        if old is not None:
            mouse = pygame.mouse.get_pos()
            y = body.y + 2 - self.parts_scroll
            for i in range(n - 1, -1, -1):
                row = pygame.Rect(body.x + 2, y, body.width - 6, PART_ROW)
                if row.bottom > body.y and row.y < body.bottom:
                    self._draw_part_row(surface, row, i, mouse)
                self.part_rows.append((i, row))
                y += PART_ROW
            surface.set_clip(old)
        if self._parts_max() > 0:
            page = body.height / max(1.0, n * PART_ROW)
            xp.scrollbar(surface, pygame.Rect(body.right - 11, body.y + 2,
                                              9, body.height - 4),
                         self.parts_scroll / self._parts_max(), page)
        phead = pygame.Rect(area.x + 1, body.bottom + 5, area.width - 1, 22)
        widgets.header(surface, phead, "Properties", self.small,
                       right=widgets.elide(self.small, str(
                           self.get_part().get("name") or ""), 70))
        pbody = pygame.Rect(area.x + 4, phead.bottom + 3, area.width - 8,
                            max(20, area.bottom - phead.bottom - 8))
        pygame.draw.rect(surface, xp.FIELD_ALT, pbody)
        xp.sunken(surface, pbody)
        self.props_body = pbody
        self.props_scroll = max(0, min(self._props_max(),
                                       self.props_scroll))
        old = widgets.clip(surface, pbody.inflate(-2, -2))
        if old is None:
            return
        small = self.small
        mouse = pygame.mouse.get_pos()
        y = pbody.y + 3 - self.props_scroll
        for row in self._flat_prop_rows():
            label = row[0]
            if label == "-":
                y += 2
                pygame.draw.line(surface, xp.SHADOW, (pbody.x + 4, y),
                                 (pbody.right - 4, y))
                y += 5
                continue
            if label == "part" or (label == "rig" and row[2] is None):
                img = widgets.cached_text(small, str(row[0]) + ":",
                                          xp.TEXT_MUTED)
                if img is not None and y + 14 <= pbody.bottom:
                    surface.blit(img, (pbody.x + 4, y))
                y += 14
                continue
            if y + FLAT_PROP_ROW > pbody.bottom:
                break
            self._draw_flat_prop(surface, pbody, row, y, small, mouse)
            y += FLAT_PROP_ROW
        surface.set_clip(old)

    def _draw_part_row(self, surface, row, index, mouse):
        """One part: its sheet's picture, its name, its layer marks."""
        part = self.model2d.parts[index]
        picked = index == self.sel_part or index in self.sel_parts
        if picked:
            surface.fill(xp.SELECTION, row)
        elif row.collidepoint(mouse):
            surface.fill(xp.BTN_HOVER_BG, row)
        key = part.get("texture") or self.model2d.texture or "white"
        box = pygame.Rect(row.x + 2, row.y + 2, PART_ROW - 6, PART_ROW - 6)
        img = self._thumb(key, box.width) if \
            not colors.is_spelling(key) else None
        if img is not None:
            surface.blit(img, box.topleft)
        else:
            got = colors.rgba(key)
            surface.fill(colors.bytes_rgb(got) if got else xp.THUMB_BG, box)
        pygame.draw.rect(surface, xp.THUMB_LINE, box, 1)
        colour = (255, 255, 255) if picked else xp.TEXT
        label = widgets.elide(self.small, str(part.get("name") or index),
                              row.right - box.right - 18)
        text = widgets.cached_text(self.small, label, colour)
        if text is not None:
            surface.blit(text, (box.right + 5,
                                row.centery - text.get_height() // 2))
        if not self._part_shown(part):
            pygame.draw.line(surface, colour, (row.x + 3, row.centery),
                             (box.right + 4, row.centery))
        if part.get("parent"):
            pygame.draw.circle(surface, colour,
                               (row.right - 6, row.centery), 2)

    def _draw_flat_prop(self, surface, body, row, y, small, mouse):
        label, value, spec, kind = row
        prow = pygame.Rect(body.x + 4, y, body.width - 8, FLAT_PROP_ROW)
        img = widgets.cached_text(small, label, xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (prow.x, prow.centery -
                               img.get_height() // 2))
        field = pygame.Rect(prow.x + 58, prow.y + 1,
                            max(16, prow.width - 62), FLAT_PROP_ROW - 3)
        if kind is None:
            return
        self.prop_fields.append((spec, field))
        if kind == "enum":
            xp.combo(surface, field, widgets.elide(small, value or "-",
                                                   field.width - 12),
                     small, hovered=field.collidepoint(mouse))
            return
        if self.grip is not None and self.grip[0] == spec:
            self.grip[1].draw(surface, field, small)
            return
        xp.field(surface, field)
        text = widgets.cached_text(small, widgets.elide(
            small, value, field.width - 6), xp.TEXT)
        if text is not None:
            surface.blit(text, (field.x + 3,
                                field.centery - text.get_height() // 2))

    def _draw_flat_popup(self, surface):
        rows = self.popup["items"]
        wide = 176
        x = max(0, min(self.popup["x"], surface.get_width() - wide - 6))
        y = max(0, min(self.popup["y"], surface.get_height() - 30))
        panel, rects = xp.menu_items(surface, (x, y),
                                     [(label or "-", bool(label))
                                      for _action, label in rows],
                                     self.small, width=wide)
        self.popup_rows = [(action, rect)
                           for (action, _label), rect in zip(rows, rects)
                           if rect is not None and action is not None]

    def _draw_palette(self, surface):
        """The texture shelf: its sheets or the picked settings."""
        area = self.palette_rect
        pygame.draw.rect(surface, xp.FACE, area)
        pygame.draw.line(surface, xp.SHADOW, (area.x, area.y),
                         (area.x, area.bottom))
        head = pygame.Rect(area.x + 1, area.y, area.width - 1, 22)
        keys = self.texture_keys()
        use = self._sheet_use()
        worn = sum(1 for key in keys if use.get(key))
        widgets.header(surface, head, "Textures", self.small,
                       right=f"{worn}/{len(keys)}")
        mouse = pygame.mouse.get_pos()
        self.tex_fields = []
        # the two ways to spend the picked sheet
        foot = pygame.Rect(area.x + 6, area.bottom - 30, area.width - 12, 24)
        half = (foot.width - 4) // 2
        self.apply_rect = pygame.Rect(foot.x, foot.y, half, foot.height)
        self.paint_rect = pygame.Rect(self.apply_rect.right + 4, foot.y,
                                      foot.width - half - 4, foot.height)
        ready = bool(self.paint_key)
        xp.button(surface, self.apply_rect, "Apply all", self.small,
                  hovered=ready and self.apply_rect.collidepoint(mouse),
                  enabled=ready)
        xp.button(surface, self.paint_rect, "Paint", self.small,
                  default=self.paint_on and ready,
                  hovered=ready and self.paint_rect.collidepoint(mouse),
                  enabled=ready)
        # which half the shelf shows: sheets, or the sheet's settings
        strip = pygame.Rect(area.x + 6, head.bottom + 4, area.width - 12,
                            SHELF_TAB)
        wide = (strip.width - 4) // 2
        self.sheets_tab = pygame.Rect(strip.x, strip.y, wide, strip.height)
        self.settings_tab = pygame.Rect(self.sheets_tab.right + 4, strip.y,
                                        strip.width - wide - 4,
                                        strip.height)
        for rect, name, label in ((self.sheets_tab, "sheets", "Sheets"),
                                  (self.settings_tab, "settings",
                                   "Settings")):
            xp.button(surface, rect, label, self.small,
                      default=self.palette_tab == name,
                      hovered=rect.collidepoint(mouse))
        body = pygame.Rect(area.x + 4, strip.bottom + 4, area.width - 8,
                           max(10, foot.y - strip.bottom - 8))
        pygame.draw.rect(surface, xp.FIELD, body)
        xp.sunken(surface, body)
        self.palette_body = body
        if self.palette_tab == "settings":
            self._draw_shelf_settings(surface, body, mouse)
            return
        self.palette_max = max(0, len(keys) * SWATCH_ROW + 4
                               + self._shelf_caps(keys) * SHELF_CAP
                               - body.height)
        self.palette_scroll = max(0, min(self.palette_max,
                                         self.palette_scroll))
        wide = body.width - (24 if self.palette_max else 10)
        old_clip = surface.get_clip()
        surface.set_clip(body.inflate(-2, -2))
        self.palette_rows = []
        y = body.y + 2 - self.palette_scroll
        engine = self._shelf_engine(keys)
        group = None
        for key in keys:
            want = ("engine sheets" if key in engine
                    else "project sheets")
            if want != group:
                group = want
                cap = pygame.Rect(body.x + 3, y, wide, SHELF_CAP)
                if cap.bottom > body.y and cap.y < body.bottom:
                    self._draw_shelf_caption(surface, body, want, None, y,
                                             self.small)
                self.palette_rows.append((None, cap))
                y += SHELF_CAP
            row = pygame.Rect(body.x + 3, y, wide, SWATCH_ROW)
            if row.bottom > body.y and row.y < body.bottom:
                self._draw_swatch(surface, row, key, use.get(key, 0))
            self.palette_rows.append((key, row))
            y += SWATCH_ROW
        surface.set_clip(old_clip)
        if self.palette_max > 0:
            frac = self.palette_scroll / self.palette_max
            page = body.height / max(1.0, len(keys) * SWATCH_ROW +
                                     self._shelf_caps(keys) * SHELF_CAP)
            xp.scrollbar(surface, pygame.Rect(body.right - 12, body.y + 2,
                                              10, body.height - 4), frac,
                         page)

    def _draw_shelf_settings(self, surface, body, mouse):
        """The Settings block: the sheet's image options, the model's tiling."""
        small = self.small
        self.palette_max = self._tex_rows_max(body)
        self.palette_scroll = max(0, min(self.palette_max,
                                         self.palette_scroll))
        old = widgets.clip(surface, body.inflate(-2, -2))
        if old is None:
            return
        y = body.y + 3 - self.palette_scroll
        for row in self._tex_prop_rows():
            # a divider is "-"; other rows carry label and spec
            if row[0] == "-":
                y += 2
                pygame.draw.line(surface, xp.SHADOW, (body.x + 4, y),
                                 (body.right - 4, y))
                y += 5
                continue
            label, value, spec, kind = row
            if spec is None:
                self._draw_shelf_caption(surface, body, label, value, y,
                                         small)
                y += 14
                continue
            if y + SHELF_ROW > body.bottom:
                break
            self._draw_shelf_prop(surface, body, label, value, spec, kind,
                                  y, small, mouse)
            y += SHELF_ROW
        surface.set_clip(old)
        if self.palette_max > 0:
            page = body.height / max(1.0, y + self.palette_scroll - body.y)
            xp.scrollbar(surface, pygame.Rect(body.right - 12, body.y + 2,
                                              10, body.height - 4),
                         self.palette_scroll / self.palette_max, page)

    def _draw_shelf_caption(self, surface, body, label, value, y, small):
        """One section name, or a muted note instead."""
        text = str(value) if label == "note" else str(label)
        img = widgets.cached_text(small, widgets.elide(
            small, text, body.width - 10), xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (body.x + 5, y))

    def _draw_shelf_prop(self, surface, body, label, value, spec, kind, y,
                         small, mouse):
        """One Settings field: a picked name or a number."""
        prow = pygame.Rect(body.x + 4, y, body.width - 8, SHELF_ROW)
        img = widgets.cached_text(small, label, xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (prow.x, prow.centery - img.get_height() // 2))
        field = pygame.Rect(prow.x + 54, prow.y + 1, max(16, prow.width - 58),
                            SHELF_ROW - 3)
        self.tex_fields.append((spec, field))
        if kind == "enum":
            xp.combo(surface, field, widgets.elide(small, value or "-",
                                                   field.width - 12),
                     small, hovered=field.collidepoint(mouse))
            return
        if self.grip is not None and self.grip[0] == spec:
            self.grip[1].draw(surface, field, small)
            return
        xp.field(surface, field)
        text = widgets.cached_text(small, widgets.elide(
            small, value, field.width - 6), xp.TEXT)
        if text is not None:
            surface.blit(text, (field.x + 3,
                                field.centery - text.get_height() // 2))

    def _shelf_engine(self, keys):
        """The shelf's own set: the blank and the built-in sheets."""
        return {key for key in keys
                if key == "white" or self.is_builtin(key)}

    def _shelf_caps(self, keys):
        """How many section lines the shelf's list is cut into."""
        engine = self._shelf_engine(keys)
        if not keys:
            return 0
        return 1 + (1 if any(key not in engine for key in keys) else 0)

    def _draw_swatch(self, surface, row, key, worn=0):
        """One sheet in the shelf: its picture, its name, its wear."""
        picked = key == self.paint_key
        if picked:
            surface.fill(xp.SELECTION, row)
        elif row.collidepoint(pygame.mouse.get_pos()):
            surface.fill(xp.BTN_HOVER_BG, row)
        box = pygame.Rect(row.x + 2, row.y + (row.height - SWATCH) // 2,
                          SWATCH, SWATCH)
        img = self._thumb(key, SWATCH)
        if img is not None:
            surface.blit(img, box.topleft)
        else:
            surface.fill(xp.THUMB_BG, box)
        pygame.draw.rect(surface, xp.THUMB_LINE, box, 1)
        if picked:
            # the picked row is the brush both halves use
            pygame.draw.rect(surface, xp.SELECT_BORDER, box.inflate(2, 2), 1)
        colour = (255, 255, 255) if picked else xp.TEXT
        room = row.right - box.right - 10 - (16 if worn else 0)
        name = widgets.elide(self.small, key, max(10, room))
        img = widgets.cached_text(self.small, name, colour)
        if img is not None:
            surface.blit(img, (box.right + 5,
                               row.centery - img.get_height() // 2))
        if worn:
            # a sheet already worn is the one worth looking at first
            img = widgets.cached_text(self.small, str(worn), xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (row.right - img.get_width() - 4,
                                   row.centery - img.get_height() // 2))

    def _palette_click(self, pos):
        """A shelf click: tab, sheet, field or use."""
        for rect, name in ((self.sheets_tab, "sheets"),
                           (self.settings_tab, "settings")):
            if rect.collidepoint(pos):
                self._set_palette_tab(name)
                return True
        if self.apply_rect.collidepoint(pos):
            if self.paint_key:
                self.fill_all(self.paint_key)
            else:
                self.message = "pick a texture first"
            return True
        if self.paint_rect.collidepoint(pos):
            if not self.paint_key:
                self.message = "pick a texture first"
                return True
            self.paint_on = True
            self.paint_all = False
            self.message = f"paint {self.paint_key} - click or drag faces"
            return True
        if self.palette_tab == "settings":
            # the fields own this block; elsewhere closes them
            for spec, rect in self.tex_fields:
                if rect.collidepoint(pos):
                    self._open_prop(spec, pos)
                    return True
            self.grip = None
            return True
        if self.palette_body.collidepoint(pos):
            for key, row in self.palette_rows:
                if key is None:
                    continue        # a section line picks nothing
                if not row.collidepoint(pos):
                    continue
                self.paint_key = key
                self.paint_on = True
                if self.paint_all:
                    self.fill_all(key)
                else:
                    self.message = f"picked {key} - click a face to fill it"
                return True
        return True

    def _set_palette_tab(self, tab):
        """Swap the shelf between its sheets and its settings."""
        if tab == self.palette_tab:
            return
        self.grip = None
        self.popup = None
        self.palette_tab = tab
        self.palette_scroll = 0

    def _scroll_palette(self, dy):
        self.palette_scroll = max(0, min(self.palette_max,
                                         self.palette_scroll + dy))

    def _draw_viewport(self, surface, viewport):
        pygame.draw.rect(surface, (26, 30, 36), viewport)
        xp.sunken(surface, viewport)
        self.inner = viewport.inflate(-2, -2)
        if self.model is None:
            img = widgets.cached_text(self.font,
                                      "New primitive, or double-click a "
                                      ".model3d in the tree.",
                                      xp.TEXT_MUTED)
            surface.blit(img, (self.inner.centerx - img.get_width() // 2,
                               self.inner.centery - img.get_height() // 2))
            return
        size = self.inner.size
        if size[0] < 4 or size[1] < 4:
            return
        self._ensure_renderer(size)
        cam = self.orbit.camera()
        frame = self.renderer.render(cam, self.studio)
        if frame.get_size() != size:
            frame = pygame.transform.smoothscale(frame, size)
        surface.blit(frame, self.inner.topleft)

        old_clip = surface.get_clip()
        surface.set_clip(self.inner)
        self._draw_axes(surface, cam, size)
        if self.wire:
            self._draw_wire(surface, cam, size)
        if self.ui_mode == "texture":
            self._draw_face_mark(surface, cam, size)
        else:
            self._draw_vertices(surface, cam, size)
            self.hover_face = None
        self._draw_hud(surface, size)
        surface.set_clip(old_clip)

    def _project(self, cam, size, point):
        p = cam.project(point, size)
        if p is None:
            return None
        return (self.inner.x + p[0], self.inner.y + p[1])

    def _draw_axes(self, surface, cam, size):
        origin = self._project(cam, size, (0.0, 0.0, 0.0))
        if origin is None:
            return
        for axis, color in (("x", (210, 70, 60)), ("y", (70, 190, 90)),
                            ("z", (70, 120, 220))):
            tip = self._project(cam, size,
                                tuple(c * 1.6 for c in
                                      AXIS_VECTORS[axis]))
            if tip is None:
                continue
            pygame.draw.line(surface, color, origin, tip, 2)
            label = widgets.cached_text(self.small, axis.upper(), color)
            surface.blit(label, (tip[0] + 2, tip[1] - 6))

    def _draw_wire(self, surface, cam, size):
        for fi, t in enumerate(self.model.tris):
            pts = [self._project(cam, size, self.model.verts[vi])
                   for vi in t]
            if any(p is None for p in pts):
                continue
            selected = fi == self.sel_face or fi in self.sel_faces
            color = (255, 168, 52) if selected else (168, 196, 226)
            width = 2 if selected else 1
            pygame.draw.lines(surface, (10, 12, 16), True, pts, width + 2)
            pygame.draw.lines(surface, color, True, pts, width)

    def _draw_face_mark(self, surface, cam, size):
        """Outline the face the brush would fill."""
        mouse = pygame.mouse.get_pos()
        face = self.sel_face
        if self.inner.collidepoint(mouse):
            found = self._pick_face(cam, size, self._local(mouse))
            if found is not None:
                face = found
        self.hover_face = face
        if face is None or face >= len(self.model.tris):
            return
        pts = [self._project(cam, size, self.model.verts[vi])
               for vi in self.model.tris[face]]
        if any(p is None for p in pts):
            return
        armed = self.paint_on and bool(self.paint_key)
        colour = (255, 210, 60) if armed else (150, 156, 168)
        pygame.draw.lines(surface, (12, 14, 18), True, pts, 5)
        pygame.draw.lines(surface, colour, True, pts, 2)

    def _draw_paint_cursor(self, surface, cam, size):
        mouse = pygame.mouse.get_pos()
        if not self.inner.collidepoint(mouse):
            return
        local = self._local(mouse)
        hit = self._ray_face(cam, size, local)
        self.hover_face = hit[1] if hit is not None else None
        radius = 8
        if hit is not None:
            tri = self.model.tris[hit[1]]
            pts = [self._project(cam, size, self.model.verts[i])
                   for i in tri]
            if not any(point is None for point in pts):
                pygame.draw.lines(surface, (255, 210, 60), True, pts, 2)
            uv2 = getattr(self.model, "uv2", None)
            if uv2 and not any(i >= len(uv2) for i in tri) and \
                    not any(point is None for point in pts):
                screen_basis = np.column_stack(
                    (np.asarray(pts[1]) - pts[0],
                     np.asarray(pts[2]) - pts[0]))
                uv_basis = np.column_stack(
                    (np.asarray(uv2[tri[1]]) - uv2[tri[0]],
                     np.asarray(uv2[tri[2]]) - uv2[tri[0]]))
                try:
                    duv_per_pixel = uv_basis @ np.linalg.inv(screen_basis)
                except np.linalg.LinAlgError:
                    duv_per_pixel = None
                if duv_per_pixel is not None:
                    du = float(np.linalg.norm(
                        duv_per_pixel[:, 0] * uvpaint.CANVAS))
                    dv = float(np.linalg.norm(
                        duv_per_pixel[:, 1] * uvpaint.CANVAS))
                    per_pixel = (du + dv) / 2.0
                    if per_pixel > 1e-5 and self.uvpaint is not None:
                        radius = max(2, min(
                            70, round(self.uvpaint.brush /
                                      (2 * per_pixel))))
        color = (255, 210, 60) if hit is not None else (150, 156, 168)
        pygame.draw.circle(surface, (12, 14, 18), mouse, radius, 3)
        pygame.draw.circle(surface, color, mouse, radius, 1)

    def _draw_vertices(self, surface, cam, size):
        selected_verts = (set(self._object_drag_verts())
                          if self.mode == "object" else self.sel_verts)
        if self.mode == "object" and not selected_verts:
            return
        mouse = pygame.mouse.get_pos()
        local = self._local(mouse) if self.inner.collidepoint(mouse) \
            else None
        self.hover_vert = self._pick_vertex(cam, size, local) \
            if local is not None else None
        face_verts = set()
        for f in (self.sel_faces |
                  ({self.sel_face} if self.sel_face is not None else set())):
            if 0 <= f < len(self.model.tris):
                face_verts.update(self.model.tris[f])
        for i, v in enumerate(self.model.verts):
            p = cam.project(v, size)
            if p is None:
                continue
            x, y = self.inner.x + p[0], self.inner.y + p[1]
            selected = i in selected_verts or (
                self.mode == "face" and i in face_verts)
            if selected:
                pygame.draw.circle(surface, (255, 246, 214), (x, y), 5)
                pygame.draw.circle(surface, (210, 110, 20), (x, y), 5, 1)
            elif i == self.hover_vert:
                pygame.draw.circle(surface, (110, 225, 255), (x, y), 5, 2)
            else:
                pygame.draw.circle(surface, (18, 20, 26), (x, y), 3)
                pygame.draw.circle(surface, (235, 240, 250), (x, y), 3, 1)
        if self.mode in ("vertex", "object") and selected_verts:
            self._draw_vertex_gizmo(surface, cam, size)

    def _vertex_handles(self, cam, size):
        """The three move arms over the picked vertices."""
        indices = self._object_drag_verts() if self.mode == "object" \
            else sorted(self.sel_verts)
        if not indices:
            return []
        ctr = self._selection_centre(indices)
        got = cam.project(ctr, size)
        if got is None:
            return []
        origin = (got[0], got[1])
        out = []
        for axis in ("x", "y", "z"):
            v = AXIS_VECTORS[axis]
            tip = cam.project((ctr[0] + v[0], ctr[1] + v[1],
                               ctr[2] + v[2]), size)
            if tip is None:
                continue
            dx, dy = tip[0] - origin[0], tip[1] - origin[1]
            length = math.hypot(dx, dy)
            if length < 1e-3:
                continue
            out.append((axis, origin,
                        (origin[0] + dx / length * GIZ_PX,
                         origin[1] + dy / length * GIZ_PX)))
        return out

    def _gizmo_axis_at(self, cam, size, local):
        """Which arm a viewport pixel would grab, or None."""
        for axis, a, b in self._vertex_handles(cam, size):
            if _seg_distance(local[0], local[1], a, b) <= GRAB_PX:
                return axis
        return None

    def _draw_vertex_gizmo(self, surface, cam, size):
        for axis, a, b in self._vertex_handles(cam, size):
            p1 = (self.inner.x + a[0], self.inner.y + a[1])
            p2 = (self.inner.x + b[0], self.inner.y + b[1])
            pygame.draw.line(surface, (10, 12, 16), p1, p2, 5)
            pygame.draw.line(surface, AXES[axis], p1, p2, 2)

    def _objs_max(self):
        if self.model is None:
            return 0
        return max(0, len(self.model.objects) * OBJ_ROW + 4 -
                   self.obj_body.height)

    def _draw_objects(self, surface):
        """The right rail of named parts, plus + Obj."""
        area = self.obj_rect
        pygame.draw.rect(surface, xp.FACE, area)
        pygame.draw.line(surface, xp.SHADOW, (area.x, area.y),
                         (area.x, area.bottom))
        objs = self.model.objects
        head = pygame.Rect(area.x + 1, area.y, area.width - 1, 22)
        widgets.header(surface, head, "Objects", self.small,
                       right=str(len(objs)))
        mouse = pygame.mouse.get_pos()
        foot = pygame.Rect(area.x + 6, area.bottom - 30, area.width - 12, 24)
        half = (foot.width - 4) // 2
        self.obj_add_rect = pygame.Rect(foot.x, foot.y, half, foot.height)
        self.obj_merge_rect = pygame.Rect(self.obj_add_rect.right + 4,
                                          foot.y, foot.width - half - 4,
                                          foot.height)
        xp.button(surface, self.obj_add_rect, "+ Obj", self.small,
                  hovered=self.obj_add_rect.collidepoint(mouse))
        can = self._can_merge()
        xp.button(surface, self.obj_merge_rect, "Merge", self.small,
                  hovered=can and self.obj_merge_rect.collidepoint(mouse),
                  enabled=can)
        body = pygame.Rect(area.x + 4, head.bottom + 3, area.width - 8,
                           max(20, foot.y - head.bottom - 8))
        pygame.draw.rect(surface, xp.FIELD, body)
        xp.sunken(surface, body)
        self.obj_body = body
        self.obj_rows = []
        self.obj_scroll = max(0, min(self._objs_max(), self.obj_scroll))
        old = widgets.clip(surface, body.inflate(-2, -2))
        if old is not None:
            y = body.y + 2 - self.obj_scroll
            for o in objs:
                row = pygame.Rect(body.x + 2, y, body.width - 6, OBJ_ROW)
                if row.bottom > body.y and row.y < body.bottom:
                    self._draw_obj_row(surface, row, o, mouse)
                self.obj_rows.append((o["name"], row))
                y += OBJ_ROW
            surface.set_clip(old)
        if self._objs_max() > 0:
            page = body.height / max(1.0, len(objs) * OBJ_ROW)
            xp.scrollbar(surface, pygame.Rect(body.right - 11, body.y + 2,
                                              9, body.height - 4),
                         self.obj_scroll / self._objs_max(), page)
        if self.rename_obj is not None:
            self._draw_rename_field(surface)

    def _draw_obj_row(self, surface, row, o, mouse):
        """One object: a colour dot, name and face count."""
        name = o["name"]
        picked = name == self.sel_obj or name in self.sel_objs
        if picked:
            surface.fill(xp.SELECTION, row)
        elif row.collidepoint(mouse):
            surface.fill(xp.BTN_HOVER_BG, row)
        dot = (200, 160, 60) if o.get("painted") else (
            (90, 170, 90) if o.get("lightmap") else (120, 128, 140))
        pygame.draw.circle(surface, dot, (row.x + 11, row.centery), 4)
        if name == self.rename_obj:
            return
        colour = (255, 255, 255) if picked else xp.TEXT
        label = widgets.elide(self.small, str(name), row.width - 54)
        text = widgets.cached_text(self.small, label, colour)
        if text is not None:
            surface.blit(text, (row.x + 20,
                                row.centery - text.get_height() // 2))
        cnt = widgets.cached_text(self.small, f"{len(o['faces'])}f",
                                  xp.TEXT_MUTED)
        if cnt is not None:
            surface.blit(cnt, (row.right - cnt.get_width() - 6,
                               row.centery - cnt.get_height() // 2))

    def _draw_rename_field(self, surface):
        """The inline text box over the row being retyped."""
        for name, row in self.obj_rows:
            if name != self.rename_obj:
                continue
            field = pygame.Rect(row.x + 18, row.y + 1,
                                max(16, row.width - 24), row.height - 2)
            self.obj_field.draw(surface, field, self.small, True)
            return

    def _obj_click(self, pos, e):
        """One click inside the objects rail."""
        if self.rename_obj is not None:
            self._commit_rename()
        if self.obj_add_rect.collidepoint(pos):
            self._act_add_obj()
            return True
        if (self.obj_merge_rect.collidepoint(pos) and self._can_merge()):
            self._act_merge()
            return True
        ticks = pygame.time.get_ticks()
        for name, row in self.obj_rows:
            if not row.collidepoint(pos):
                continue
            if widgets.shift_held(e):
                self.select_object(name, toggle=True)
                self._last_obj = (None, 0)
                return True
            last, then = self._last_obj
            if last == name and ticks - then < 400:
                self._begin_rename(name)
                self._last_obj = (None, 0)
            else:
                self.select_object(name)
                self._last_obj = (name, ticks)
            return True
        self._last_obj = (None, 0)
        return True

    def _obj_wheel(self, dy):
        self.obj_scroll = max(0, min(self._objs_max(),
                                     self.obj_scroll + dy))

    def _draw_hud(self, surface, size):
        if self.ui_mode == "texture":
            hint = self.message or ("click a face to fill it with "
                                    + (self.paint_key or "a picked sheet"))
        else:
            hint = self.message or ("drag to move  X/Y/Z axis  E extrude  "
                                    "Shift-click picks more  Ctrl+S save")
        strip = pygame.Rect(self.inner.x, self.inner.bottom - 17,
                            self.inner.width, 17)
        pygame.draw.rect(surface, (24, 28, 34), strip)
        img = widgets.cached_text(self.small, hint, (214, 218, 226))
        surface.blit(img, (strip.x + 6, strip.centery - img.get_height() // 2))
        if self.ui_mode == "texture":
            info = (f"{len(self.model.verts)}v {len(self.model.tris)}f  "
                    f"{self.model.texture}  brush {self.paint_key or '-'}")
        else:
            info = (f"{len(self.model.verts)}v {len(self.model.tris)}f  "
                    f"{self.model.texture}  snap "
                    f"{self.snap_step if self.snap else 'off'}")
        faces = self.target_faces()
        if faces:
            got = self.model.face_texture(faces[0])
            info += f"  [{len(faces)}f: {got}]"
        img = widgets.cached_text(self.small, info, (196, 200, 208))
        surface.blit(img, (strip.right - img.get_width() - 6,
                           strip.centery - img.get_height() // 2))

    def info(self):
        if self.model2d is not None:
            m = self.model2d
            sel = (m.parts[self.sel_part].get("name")
                   if self.sel_part is not None
                   and 0 <= self.sel_part < len(m.parts) else "-")
            return [
                ("Rig", m.name),
                ("File", self.app.project.relative(self.path)
                 if self.path else "unsaved"),
                ("Parts", str(len(m.parts))),
                ("Tracks", str(len(m.tracks))),
                ("Size", f"{m.size[0]} x {m.size[1]}"),
                ("Texture", m.texture or "-"),
                ("Selected", sel or "-"),
                ("Playing", "yes" if self.playing else "no"),
                ("Time", f"{self.play_t:.2f}s"),
                ("Snap", f"{self.snap_step}" if self.snap else "off"),
                ("State", "modified" if self.dirty else "saved"),
            ]
        if self.model is None:
            return [("Model", "-"), ("Verts", "0"), ("Faces", "0"),
                    ("Hint", "pick a primitive")]
        b = self.model.bounds()
        size = "%.2f x %.2f x %.2f" % (b[1][0] - b[0][0],
                                       b[1][1] - b[0][1],
                                       b[1][2] - b[0][2]) if b else "-"
        sel = len(self.sel_verts) if self.mode != "object" else \
            len(self.model.verts)
        faces = self.target_faces()
        surface = (f"{self.model.face_texture(faces[0])} x{len(faces)}"
                   if faces else self.model.texture)
        return [
            ("Model", self.model.name),
            ("File", self.app.project.relative(self.path) if self.path
             else "unsaved"),
            ("Verts", str(len(self.model.verts))),
            ("Faces", str(len(self.model.tris))),
            ("Size", size),
            ("Texture", self.model.texture),
            ("Surface", surface),
            ("Mode", self.mode),
            ("Tab", self.ui_mode),
            ("Brush", self.paint_key or "-"),
            ("Selected", str(sel) + (" v" if self.mode == "vertex" else "")),
            ("Snap", f"{self.snap_step}" if self.snap else "off"),
            ("State", "modified" if self.dirty else "saved"),
        ]
