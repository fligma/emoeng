"""The Model tab: a turntable viewport where `.model` files are built and
edited vertex by vertex.

    left drag on a vertex/face   select and move (object mode moves all)
    left drag on empty space     orbit the camera
    middle drag / right drag     orbit / pan
    wheel                        zoom
    1 / 2 / 3                    Object / Vertex / Face mode
    X / Y / Z                    constrain movement to an axis, again = free
    E  F  Del                    extrude face / make face / delete
    Ctrl+Z / Ctrl+Y / Ctrl+S     undo / redo / save

The geometry lives in engine.model.Model; this tab only projects it for
picking (Camera.project), previews it on its own Renderer and writes it
back through Project.store_model. Overlays (grid, wireframe, vertex dots)
are drawn with pygame on top of the returned frame, so the shared
renderer needs no editor-specific code.
"""

import math
from pathlib import Path

import numpy as np
import pygame

from ..engine import meshes, model as modelmod, proctex, xp
from ..engine.camera import OrbitCamera
from ..engine.renderer import Renderer
from . import widgets

TOOL_H = 25
AXIS_VECTORS = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0),
                "z": (0.0, 0.0, 1.0)}
MODES = (("object", "Object"), ("vertex", "Vertex"), ("face", "Face"))
PRIMITIVES = (("box", "Box"), ("wedge", "Wedge"), ("cylinder", "Cyl"),
              ("cone", "Cone"), ("plane", "Plane"), ("sphere", "Sphere"))


class _Studio:
    """Render settings for the model viewport (same knobs a scene has)."""

    clear_color = (0.075, 0.082, 0.10)
    fog_color = (0.085, 0.092, 0.115)
    fog_near = 35.0
    fog_far = 160.0
    ambient = (0.58, 0.58, 0.62)
    sun_dir = (0.45, 0.85, 0.30)
    sun_col = (0.72, 0.68, 0.60)
    fov = 55.0
    lights = [{"pos": (3.2, 5.0, 2.4), "color": (0.50, 0.46, 0.40)}]


def _point_in_tri(p, tri):
    def sign(a, b, c):
        return ((a[0] - c[0]) * (b[1] - c[1]) -
                (b[0] - c[0]) * (a[1] - c[1]))
    d1 = sign(p, tri[0], tri[1])
    d2 = sign(p, tri[1], tri[2])
    d3 = sign(p, tri[2], tri[0])
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


class ModelEditor:
    """Vertex/face editor for one .model file at a time."""

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
        self.mesh = None
        self.dirty = False
        self.name_field = widgets.TextField("model", 32)
        self.name_focus = False
        self.mode = "vertex"
        self.axis = None
        self.snap = True
        self.snap_step = 0.25
        self.wire = True
        self.append_mode = False
        self.sel_verts = set()
        self.sel_face = None
        self.hover_vert = None
        self.undo = []
        self.redo = []
        self.buttons = []
        self.viewport = pygame.Rect(0, 0, 0, 0)
        self.inner = pygame.Rect(0, 0, 0, 0)
        self.name_rect = pygame.Rect(0, 0, 0, 0)
        self.drag = None
        self.message = ""

    # --------------------------------------------------------------- files
    def open(self, path):
        try:
            model = modelmod.Model.load(path)
        except Exception as exc:
            self.app.log(f"cannot open {Path(path).name}: {exc}", "error")
            return False
        self.model = model
        self.path = str(model.path)
        self.name_field.set(model.name)
        self.name_focus = False
        self.sel_verts.clear()
        self.sel_face = None
        self.hover_vert = None
        self.undo.clear()
        self.redo.clear()
        self.dirty = False
        self.orbit.frame(model.bounds())
        self._refresh_mesh()
        self.message = f"opened {self.app.project.relative(self.path)}"
        return True

    def save(self):
        if self.model is None:
            return False
        name = (self.name_field.text or self.model.name or "model").strip()
        stem = Path(name).stem or "model"
        try:
            path = self.app.project.store_model(self.model, stem)
        except Exception as exc:
            self.app.log(f"save failed: {exc}", "error")
            return False
        self.model.name = stem
        self.path = str(path)
        self.name_field.set(stem)
        self.dirty = False
        self.app.log(f"saved {self.app.project.relative(path)}", "ok")
        self.app.refresh_tree()
        return True

    def autosave(self):
        if self.model is not None and self.dirty:
            self.save()

    def close_model(self):
        if self.mesh is not None:
            self.mesh.dispose()
            self.mesh = None
        self.model = None
        self.path = None
        self.sel_verts.clear()
        self.sel_face = None
        self.dirty = False

    def refresh_textures(self):
        if self.renderer is not None and self.app.project is not None:
            try:
                self.app.project.register_textures(self.renderer)
            except Exception as exc:
                self.app.log(f"textures: {exc}", "warn")

    # ----------------------------------------------------------- primitives
    def new_model(self, kind="box"):
        size = 1.0
        model = modelmod.new_model(kind, size, texture="grid", name=kind)
        self._adopt(model, append=False)
        self.message = f"new {kind} - edit it, then Save"
        return model

    def _adopt(self, model, append=False):
        self._push_undo()
        if append and self.model is not None:
            self.model.add_primitive(model.name, 1.0)
            self.model.auto_uv()
        else:
            self.model = model
            self.path = None
            self.undo.clear()
            self.redo.clear()
            self.orbit.frame(model.bounds())
        self.sel_verts.clear()
        self.sel_face = None
        self.dirty = True
        self.name_field.set(self.model.name)
        self._refresh_mesh()

    def add_primitive(self, kind):
        if self.model is None:
            self.new_model(kind)
            return
        self._push_undo()
        self.model.add_primitive(kind, 1.0)
        self.model.auto_uv()
        self.dirty = True
        self._refresh_mesh()
        self.message = f"added {kind}"

    def cycle_texture(self, step):
        if self.model is None:
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
        if self.renderer is None:
            return ["white"]
        names = sorted(k for k in self.renderer.textures if k != "white")
        return ["white"] + names

    # ------------------------------------------------------------ viewport
    def _ensure_renderer(self, size):
        size = (max(64, int(size[0])), max(64, int(size[1])))
        if self.renderer is None:
            self.renderer = Renderer(*size, render_scale=1.0)
            r = self.renderer
            r.texture("grid", proctex.grid(256, 8))
            r.texture("checker", proctex.checker(128, 4))
            r.texture("stone", proctex.stone(128))
            r.texture("rust", proctex.rust(128))
            r.texture("bark", proctex.bark(64))
            try:
                self.app.project.register_textures(r)
            except Exception as exc:
                self.app.log(f"textures: {exc}", "warn")
            r.add(meshes.plane(size=(24, 24), seg=24), texture="grid")
            r.build()
            self.mesh = None
            self.render_size = size
            self._refresh_mesh()
            return
        if size != self.render_size:
            self.renderer.resize(*size)
            self.render_size = size

    def _refresh_mesh(self):
        if self.renderer is None or self.model is None:
            return
        if self.model.empty:
            if self.mesh is not None:
                self.mesh.dispose()
                self.mesh = None
            return
        data = self.model.meshdata()
        if self.mesh is None:
            self.mesh = self.renderer.new_dynamic(
                data, texture=self.model.texture, blend="opaque")
        else:
            self.mesh.texture = self.model.texture
            self.mesh.update(data)

    def resize(self, size):
        if self.renderer is not None:
            self._ensure_renderer(size)

    # -------------------------------------------------------------- toolbar
    def _toolbar_rows(self, rect):
        rows = [pygame.Rect(rect.x, rect.y + i * TOOL_H, rect.width, TOOL_H)
                for i in range(3)]
        return rows

    def _layout_buttons(self, rect):
        """Compute the button rects for all three strips (drawn + clickable)."""
        row1, row2, row3 = self._toolbar_rows(rect)
        out = []
        x = row1.x + 4

        def add(row, label, action, active=False, width=None, tooltip=None):
            nonlocal x
            w = width or (self.small.size(label)[0] + 14)
            r = pygame.Rect(x, row.y + 2, w, row.height - 4)
            out.append({"rect": r, "label": label, "action": action,
                        "active": active, "tip": tooltip})
            x = r.right + 3

        for mode, label in MODES:
            add(row1, label, ("mode", mode), self.mode == mode)
        x += 10
        for kind, label in PRIMITIVES:
            add(row1, label, ("prim", kind))
        x += 10
        add(row1, "Append", ("toggle", "append"), self.append_mode,
            tooltip="Primitives add to the current model")

        x = row2.x + 4
        add(row2, "Save", ("action", "save"))
        add(row2, "Reload", ("action", "reload"))
        add(row2, "Delete", ("action", "delete"))
        add(row2, "Extrude", ("action", "extrude"))
        add(row2, "Face", ("action", "makeface"))
        add(row2, "Flip", ("action", "flip"))
        add(row2, "Weld", ("action", "weld"))
        add(row2, "AutoUV", ("action", "autouv"))
        x += 10
        add(row2, "Snap", ("toggle", "snap"), self.snap)
        add(row2, "Wire", ("toggle", "wire"), self.wire)
        x += 10
        for axis in ("x", "y", "z"):
            add(row2, axis.upper(), ("axis", axis), self.axis == axis)
        add(row2, "Free", ("axis", None), self.axis is None)
        add(row2, "Frame", ("action", "frame"))

        x = row3.x + 4
        r = pygame.Rect(x, row3.y + 3, 34, row3.height - 6)
        out.append({"rect": r, "label": "Name", "action": ("none", None),
                    "active": False, "tip": "model name"})
        self.name_rect = pygame.Rect(r.right + 4, row3.y + 2, 160,
                                     row3.height - 4)
        out.append({"rect": self.name_rect, "label": "", "action":
                    ("focus_name", None), "active": self.name_focus,
                    "tip": None})
        x = self.name_rect.right + 10
        r = pygame.Rect(x, row3.y + 2, 24, row3.height - 4)
        out.append({"rect": r, "label": "<", "action": ("tex", -1),
                    "active": False, "tip": "previous texture"})
        x = r.right + 3
        tex = self.model.texture if self.model else "-"
        w = max(70, self.small.size(tex)[0] + 16)
        r = pygame.Rect(x, row3.y + 2, w, row3.height - 4)
        out.append({"rect": r, "label": tex, "action": ("none", None),
                    "active": True, "tip": "texture name"})
        x = r.right + 3
        r = pygame.Rect(x, row3.y + 2, 24, row3.height - 4)
        out.append({"rect": r, "label": ">", "action": ("tex", 1),
                    "active": False, "tip": "next texture"})
        x = r.right + 14
        hint = "drag=select/move  wheel=zoom  X/Y/Z axis  1/2/3 mode"
        out.append({"rect": pygame.Rect(x, row3.y + 2, row3.width, 20),
                    "label": "", "action": ("none", None), "active": False,
                    "tip": hint})
        return out

    def _draw_toolbar(self, surface, rect):
        old_clip = surface.get_clip()
        surface.set_clip(rect)
        rows = self._toolbar_rows(rect)
        for row in rows:
            surface.fill(xp.MODEL_ROW_BG, row)
            pygame.draw.line(surface, xp.SHADOW, (row.x, row.bottom - 1),
                             (row.right, row.bottom - 1))
            pygame.draw.line(surface, xp.HILITE, (row.x, row.y),
                             (row.right, row.y))
        mouse = pygame.mouse.get_pos()
        self.buttons = self._layout_buttons(rect)
        for b in self.buttons:
            label = b["label"]
            if not label:
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
        if self.model is not None:
            self.name_field.draw(surface, self.name_rect, self.small,
                                 self.name_focus)
        # strip-level hints
        row3 = rows[2]
        hint = self._hint_text()
        img = widgets.cached_text(self.small, hint, xp.TEXT_MUTED)
        if img:
            surface.blit(img, (row3.right - 6 - img.get_width(),
                               row3.centery - img.get_height() // 2))
        surface.set_clip(old_clip)

    def _hint_text(self):
        if self.model is None:
            return "pick a primitive to start"
        return (f"{len(self.model.verts)} v  {len(self.model.tris)} f  "
                f"mode {self.mode}" + (f"  axis {self.axis.upper()}"
                                       if self.axis else "  axis free"))

    # ------------------------------------------------------------ click box
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
        best = None
        for fi, t in enumerate(self.model.tris):
            pts = []
            ok = True
            for vi in t:
                p = cam.project(self.model.verts[vi], size)
                if p is None:
                    ok = False
                    break
                pts.append(p)
            if not ok or not _point_in_tri(pos, pts):
                continue
            depth = sum(p[2] for p in pts) / 3.0
            if best is None or depth < best[0]:
                best = (depth, fi)
        return best[1] if best else None

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

    # -------------------------------------------------------------- events
    def handle_event(self, e):
        for b in self.buttons:
            if b["action"] == ("none", None):
                continue
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and \
                    b["rect"].collidepoint(e.pos):
                self._run_action(b["action"])
                return True
        if self.name_focus:
            result = self.name_field.handle(e)
            if result in ("changed", "submit"):
                if self.model is not None:
                    self.model.name = self.name_field.text.strip() or \
                        self.model.name
                    self.dirty = True
                if result == "submit":
                    self.name_focus = False
                    self.save()
                return True
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                self.name_focus = False
                return True

        if e.type == pygame.KEYDOWN:
            if self._key_down(e):
                return True

        pos = getattr(e, "pos", pygame.mouse.get_pos())
        if self.model is None or not self.viewport.collidepoint(pos):
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
            self.drag = None
            return True
        return False

    def _key_down(self, e):
        mod = getattr(e, "mod", 0)
        ctrl = bool(mod & pygame.KMOD_CTRL)
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
            if self.sel_verts or self.sel_face is not None:
                self.sel_verts.clear()
                self.sel_face = None
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
        if e.key == pygame.K_HOME:
            self.frame_view()
            return True
        return False

    def _mouse_down(self, e):
        self.name_focus = False
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
        shift = bool(getattr(e, "mod", 0) & pygame.KMOD_SHIFT)

        if self.mode == "vertex":
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
                if vi in self.sel_verts:
                    self._start_drag(local, size, cam,
                                     indices=sorted(self.sel_verts))
                return True
        elif self.mode == "face":
            fi = self._pick_face(cam, size, local)
            if fi is not None:
                self.sel_face = fi
                self.sel_verts = set(self.model.tris[fi])
                self._start_drag(local, size, cam,
                                 indices=list(self.model.tris[fi]))
                return True
        else:
            self._start_drag(local, size, cam,
                             indices=list(range(len(self.model.verts))))
            return True

        # clicked empty space: orbit and clear the selection
        self.sel_verts.clear()
        self.sel_face = None
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
        if kind == "orbit":
            self.orbit.orbit(e.rel[0], e.rel[1])
            return True
        if kind == "pan":
            self.orbit.pan(e.rel[0], e.rel[1], self.inner.size)
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
        for i, base in self.drag["start_pos"].items():
            v = np.asarray(base, np.float64) + delta
            if self.snap:
                v = np.round(v / self.snap_step) * self.snap_step
            self.model.verts[i] = [float(v[0]), float(v[1]), float(v[2])]
        self.dirty = True
        self._refresh_mesh()
        return True

    # ------------------------------------------------------------- actions
    def _run_action(self, action):
        kind, value = action
        if kind == "mode":
            self.mode = value
            self.sel_face = None if value != "face" else self.sel_face
            if value == "object":
                self.sel_verts.clear()
        elif kind == "prim":
            if self.append_mode:
                self.add_primitive(value)
            else:
                self.new_model(value)
        elif kind == "toggle":
            if value == "append":
                self.append_mode = not self.append_mode
            elif value == "snap":
                self.snap = not self.snap
            elif value == "wire":
                self.wire = not self.wire
        elif kind == "axis":
            self.axis = value
        elif kind == "tex":
            self.cycle_texture(value)
        elif kind == "focus_name":
            self.name_focus = True
        elif kind == "action":
            getattr(self, "_act_" + value, lambda: None)()

    def _act_save(self):
        self.save()

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

    def _push_undo(self):
        if self.model is None:
            return
        self.undo.append((self.model.snapshot(), set(self.sel_verts),
                          self.sel_face))
        if len(self.undo) > 80:
            self.undo.pop(0)
        self.redo.clear()

    def undo_last(self):
        if not self.undo or self.model is None:
            return
        self.redo.append((self.model.snapshot(), set(self.sel_verts),
                          self.sel_face))
        snap, sel, face = self.undo.pop()
        self.model.restore(snap)
        self.sel_verts = set(sel)
        self.sel_face = face
        self.dirty = True
        self._refresh_mesh()

    def redo_last(self):
        if not self.redo or self.model is None:
            return
        self.undo.append((self.model.snapshot(), set(self.sel_verts),
                          self.sel_face))
        snap, sel, face = self.redo.pop()
        self.model.restore(snap)
        self.sel_verts = set(sel)
        self.sel_face = face
        self.dirty = True
        self._refresh_mesh()

    def delete_selection(self):
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
        self.model.auto_uv()
        self.dirty = True
        self.message = "uvs reprojected"

    def frame_view(self):
        if self.model is not None:
            self.orbit.frame(self.model.bounds())

    # ---------------------------------------------------------------- draw
    def draw(self, surface, rect):
        rect = pygame.Rect(rect)
        pygame.draw.rect(surface, xp.FACE, rect)
        self._draw_toolbar(surface, rect)
        top = rect.y + 3 * TOOL_H
        self.viewport = pygame.Rect(rect.x, top, rect.width,
                                    max(10, rect.bottom - top))
        self._draw_viewport(surface, self.viewport)

    def _draw_viewport(self, surface, viewport):
        pygame.draw.rect(surface, (26, 30, 36), viewport)
        xp.sunken(surface, viewport)
        self.inner = viewport.inflate(-2, -2)
        if self.model is None:
            img = widgets.cached_text(self.font,
                                      "New primitive, or double-click a "
                                      ".model in the tree.",
                                      xp.TEXT_MUTED)
            surface.blit(img, (self.inner.centerx - img.get_width() // 2,
                               self.inner.centery - img.get_height() // 2))
            return
        size = self.inner.size
        if size[0] < 4 or size[1] < 4:
            return
        self._ensure_renderer(size)
        cam = self.orbit.camera()
        frame = self.renderer.render(cam.eye, cam.yaw, cam.pitch,
                                     self.studio)
        if frame.get_size() != size:
            frame = pygame.transform.smoothscale(frame, size)
        surface.blit(frame, self.inner.topleft)

        old_clip = surface.get_clip()
        surface.set_clip(self.inner)
        self._draw_axes(surface, cam, size)
        if self.wire:
            self._draw_wire(surface, cam, size)
        self._draw_vertices(surface, cam, size)
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
            selected = (fi == self.sel_face)
            color = (255, 168, 52) if selected else (168, 196, 226)
            width = 2 if selected else 1
            pygame.draw.lines(surface, (10, 12, 16), True, pts, width + 2)
            pygame.draw.lines(surface, color, True, pts, width)

    def _draw_vertices(self, surface, cam, size):
        if self.mode == "object" and not self.sel_verts:
            return
        mouse = pygame.mouse.get_pos()
        local = self._local(mouse) if self.inner.collidepoint(mouse) \
            else None
        self.hover_vert = self._pick_vertex(cam, size, local) \
            if local is not None else None
        for i, v in enumerate(self.model.verts):
            p = cam.project(v, size)
            if p is None:
                continue
            x, y = self.inner.x + p[0], self.inner.y + p[1]
            selected = i in self.sel_verts or (
                self.sel_face is not None and
                self.mode == "face" and i in self.model.tris[self.sel_face])
            if selected:
                pygame.draw.circle(surface, (255, 246, 214), (x, y), 5)
                pygame.draw.circle(surface, (210, 110, 20), (x, y), 5, 1)
            elif i == self.hover_vert:
                pygame.draw.circle(surface, (110, 225, 255), (x, y), 5, 2)
            else:
                pygame.draw.circle(surface, (18, 20, 26), (x, y), 3)
                pygame.draw.circle(surface, (235, 240, 250), (x, y), 3, 1)

    def _draw_hud(self, surface, size):
        hint = self.message or ("drag to move  X/Y/Z axis  E extrude  "
                               "Ctrl+S save")
        strip = pygame.Rect(self.inner.x, self.inner.bottom - 17,
                            self.inner.width, 17)
        pygame.draw.rect(surface, (24, 28, 34), strip)
        img = widgets.cached_text(self.small, hint, (214, 218, 226))
        surface.blit(img, (strip.x + 6, strip.centery - img.get_height() // 2))
        info = (f"{len(self.model.verts)}v {len(self.model.tris)}f  "
                f"{self.model.texture}  snap {self.snap_step if self.snap else 'off'}")
        img = widgets.cached_text(self.small, info, (196, 200, 208))
        surface.blit(img, (strip.right - img.get_width() - 6,
                           strip.centery - img.get_height() // 2))

    # ---------------------------------------------------------------- info
    def info(self):
        if self.model is None:
            return [("Model", "-"), ("Verts", "0"), ("Faces", "0"),
                    ("Hint", "pick a primitive")]
        b = self.model.bounds()
        size = "%.2f x %.2f x %.2f" % (b[1][0] - b[0][0],
                                       b[1][1] - b[0][1],
                                       b[1][2] - b[0][2]) if b else "-"
        sel = len(self.sel_verts) if self.mode != "object" else \
            len(self.model.verts)
        return [
            ("Model", self.model.name),
            ("File", self.app.project.relative(self.path) if self.path
             else "unsaved"),
            ("Verts", str(len(self.model.verts))),
            ("Faces", str(len(self.model.tris))),
            ("Size", size),
            ("Texture", self.model.texture),
            ("Mode", self.mode),
            ("Selected", str(sel) + (" v" if self.mode == "vertex" else "")),
            ("Snap", f"{self.snap_step}" if self.snap else "off"),
            ("State", "modified" if self.dirty else "saved"),
        ]
