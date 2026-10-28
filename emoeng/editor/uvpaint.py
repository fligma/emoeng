"""UV Paint half of the Model tab: a layered canvas."""

import math

import numpy as np
import pygame

from ..engine import unwrap, xp
from . import widgets

# square canvas, defaulting to the lightmap bake size
CANVAS = 1024
# click colours, before a custom one is picked
PALETTE = ((0, 0, 0, 255), (255, 255, 255, 255), (200, 50, 40, 255),
           (60, 170, 70, 255), (50, 100, 210, 255), (230, 200, 60, 255),
           (180, 90, 200, 255), (120, 70, 30, 255))
# one row of buttons across the top of the half
TOOL_LABELS = (("brush", "Brush"), ("eraser", "Erase"), ("fill", "Fill"),
               ("line", "Line"), ("rect", "Rect"), ("ellipse", "Oval"),
               ("pick", "Pick"))
SPLIT = 0.64           # the canvas gets most of the paint workspace


class Layer:
    """One RGBA sheet in the stack, with a placement offset."""

    def __init__(self, name, size, arr=None, off=(0, 0), visible=True):
        self.name = name
        if arr is None:
            arr = np.zeros((size[1], size[0], 4), np.uint8)
        self.arr = arr
        self.off = (int(off[0]), int(off[1]))
        self.visible = visible


class LayerStack:
    """A bottom-to-top list of layers with an active one."""

    def __init__(self, size):
        self.size = (int(size[0]), int(size[1]))
        self.layers = [Layer("Layer 1", self.size)]
        self.active = 0

    def add(self, name, arr=None, off=(0, 0)):
        self.layers.append(Layer(name, self.size, arr=arr, off=off))
        self.active = len(self.layers) - 1
        return self.layers[-1]

    def current(self):
        return self.layers[self.active]

    def drop_active(self):
        """Remove the active layer, never leaving the stack empty."""
        if len(self.layers) > 1:
            self.layers.pop(self.active)
            self.active = max(0, self.active - 1)

    def composite(self, base=(255, 255, 255, 255)):
        """Flatten visible layers over an opaque base, as RGBA uint8."""
        w, h = self.size
        out = np.empty((h, w, 4), np.float32)
        out[..., 0], out[..., 1], out[..., 2] = base[0], base[1], base[2]
        out[..., 3] = 255.0
        for layer in self.layers:
            if not layer.visible:
                continue
            out = _over(out, _shifted(layer, w, h))
        return np.clip(out, 0, 255).astype(np.uint8)


def _shifted(layer, w, h):
    """A layer slid by its offset, cropped to canvas."""
    ox, oy = layer.off
    src = layer.arr
    out = np.zeros((h, w, 4), np.float32)
    sx0, sy0 = max(0, -ox), max(0, -oy)
    dx0, dy0 = max(0, ox), max(0, oy)
    cw, ch = min(w - dx0, src.shape[1] - sx0), min(h - dy0,
                                                   src.shape[0] - sy0)
    if cw > 0 and ch > 0:
        out[dy0:dy0 + ch, dx0:dx0 + cw] = \
            src[sy0:sy0 + ch, sx0:sx0 + cw].astype(np.float32)
    return out


def _over(dst, src):
    """`src` (float RGBA) composited over `dst`, straight alpha."""
    sa = src[..., 3:4] / 255.0
    da = dst[..., 3:4] / 255.0
    oa = sa + da * (1.0 - sa)
    rgb = (src[..., :3] * sa + dst[..., :3] * da * (1.0 - sa))
    out = np.empty_like(dst)
    nz = oa[..., 0] > 1e-6
    out[..., :3][nz] = (rgb / np.clip(oa, 1e-6, None))[nz]
    out[..., :3][~nz] = 0.0
    out[..., 3:4] = oa * 255.0
    return out


class UVPaint:
    """The paint session the Model tab hosts in 'uv' mode."""

    def __init__(self, owner, model):
        self.owner = owner
        self.model = model
        self.objname = None         # the object being painted, or None
        self.size = (CANVAS, CANVAS)
        self.stack = LayerStack(self.size)
        self.tool = "brush"
        self.color = list(PALETTE[1])
        self.brush = 8
        self.view = {"zoom": 0.6, "x": 0.0, "y": 0.0}
        self._auto_fit = True
        self._fit_size = None
        self.canvas_rect = pygame.Rect(0, 0, 0, 0)
        self.preview_rect = pygame.Rect(0, 0, 0, 0)
        self.preview_viewport = pygame.Rect(0, 0, 0, 0)
        self.layers_rect = pygame.Rect(0, 0, 0, 0)
        self.layer_rows = []
        self.layer_scroll = 0
        self.buttons = []
        self.drag = None
        self.undo = []
        self.redo = []
        self.message = ""
        self._surf = None
        self._surf_stamp = 0
        self._layer_thumbs = {}
        self.revision = 0
        self.has_edits = False

    def _object_faces(self):
        """The selected object's face list, or None."""
        m = self.model
        if m is None or not m.has_objects or not self.objname:
            return None
        for o in m.objects:
            if o["name"] == str(self.objname):
                return list(o["faces"])
        return None

    def _laid_out(self, faces):
        """True when every given face's corners already carry a packed"""
        m = self.model
        uv2 = m.uv2
        if not uv2:
            return False
        for f in faces:
            if f >= len(m.tris):
                continue
            for v in m.tris[f]:
                if v >= len(uv2) or (uv2[v][0] == 0.0 and uv2[v][1] == 0.0):
                    return False
        return True

    def ensure_unwrapped(self):
        """Give the target its uv2 once, so revisits reuse it."""
        if self.model is None:
            return False
        faces = self._object_faces()
        if faces is None:
            if getattr(self.model, "uv2", None):
                return True
            made = unwrap.split_and_unwrap(self.model)
        else:
            if not faces:
                self.message = "that object has no faces"
                return False
            if self._laid_out(faces):
                return True
            made = unwrap.split_and_unwrap(self.model, faces=faces)
        verts, uvs, uv2, tris, tex = made
        if not uv2:
            self.message = "nothing to unwrap"
            return False
        self.model.verts, self.model.uvs, self.model.uv2 = \
            verts, uvs, uv2
        self.model.tris, self.model.tex = tris, tex
        self.owner.dirty = True
        self.owner._refresh_mesh()
        return True

    def _to_canvas(self, pos):
        """Screen point -> canvas pixel, or None outside the sheet."""
        z = self.view["zoom"]
        box = getattr(self, "_box", self.canvas_rect)
        cx = (pos[0] - box.x) / z
        cy = (pos[1] - box.y) / z
        if not (0 <= cx < self.size[0] and 0 <= cy < self.size[1]):
            return None
        return cx, cy

    def _cell(self, rect):
        return pygame.Rect(rect.x, rect.y, rect.width, 22)

    def handle_event(self, e):
        for b in self.buttons:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and \
                    b["rect"].collidepoint(e.pos):
                self._run(b["action"])
                return True
        if e.type == pygame.KEYDOWN and self._key(e):
            return True
        pos = getattr(e, "pos", pygame.mouse.get_pos())
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for layer, row, eye in self.layer_rows:
                if eye.collidepoint(pos):
                    layer.visible = not layer.visible
                    self._after_stroke()
                    return True
                if row.collidepoint(pos):
                    self.stack.active = self.stack.layers.index(layer)
                    self._surf = None
                    return True
        if e.type == pygame.MOUSEWHEEL and self.layers_rect.collidepoint(pos):
            self.layer_scroll = max(
                0, min(max(0, len(self.stack.layers) - 1),
                       self.layer_scroll - e.y))
            return True
        if e.type == pygame.MOUSEBUTTONDOWN and \
                self.preview_viewport.collidepoint(pos):
            if e.button in (2, 3):
                self.drag = {"kind": "preview_pan"}
                return True
            if e.button == 1 and self.owner.model is not None:
                local = (pos[0] - self.preview_viewport.x,
                         pos[1] - self.preview_viewport.y)
                uv = self.owner._paint_uv_at(
                    self.owner.orbit.camera(),
                    self.preview_viewport.size, local)
                if uv is not None and self.begin_surface_stroke(uv):
                    self.drag["surface"] = True
                return True
        if e.type == pygame.MOUSEMOTION and self.drag is not None:
            if self.drag.get("surface"):
                if self.owner.model is not None and \
                        self.preview_viewport.width:
                    local = (pos[0] - self.preview_viewport.x,
                             pos[1] - self.preview_viewport.y)
                    uv = self.owner._paint_uv_at(
                        self.owner.orbit.camera(),
                        self.preview_viewport.size, local)
                    if uv is not None:
                        self.continue_surface_stroke(uv)
                return True
            if self.drag.get("kind") == "preview_pan":
                self.owner.orbit.orbit(*getattr(e, "rel", (0, 0)))
                return True
            if self.drag.get("kind") == "pan":
                z = self.view["zoom"]
                self.view["x"] = self.drag["view"][0] - \
                    (pos[0] - self.drag["origin"][0]) / z
                self.view["y"] = self.drag["view"][1] - \
                    (pos[1] - self.drag["origin"][1]) / z
                return True
            if self.drag.get("kind") in ("brush", "eraser", "fill",
                                          "rect", "ellipse", "line"):
                self._move(e)
                return True
        if e.type == pygame.MOUSEBUTTONUP and self.drag is not None and \
                (self.drag.get("surface") or
                 self.drag.get("kind") == "preview_pan"):
            if self.drag.get("surface"):
                self.end_surface_stroke()
            self.drag = None
            return True
        inside = self.canvas_rect.collidepoint(
            pos)
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and inside:
            self._down(e)
            return True
        if e.type == pygame.MOUSEBUTTONUP and self.drag is not None:
            self._up(e)
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button in (2, 3):
            self.drag = None
            return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button in (2, 3) and inside:
            self._auto_fit = False
            self.drag = {"kind": "pan", "origin": pos,
                         "view": (self.view["x"], self.view["y"])}
            return True
        if e.type == pygame.MOUSEWHEEL and inside:
            if getattr(e, "mod", 0) & pygame.KMOD_SHIFT:
                self.brush = max(1, min(
                    256, self.brush + (2 if e.y > 0 else -2)))
                return True
            self._auto_fit = False
            self.view["zoom"] = max(0.1, min(6.0,
                                      self.view["zoom"] * (1.15 if e.y
                                      else 0.87)))
            self._surf = None
            return True
        if e.type == pygame.MOUSEWHEEL and \
                self.preview_viewport.collidepoint(pos):
            if getattr(e, "mod", 0) & pygame.KMOD_SHIFT:
                self.brush = max(1, min(
                    256, self.brush + (2 if e.y > 0 else -2)))
            else:
                self.owner.orbit.zoom(e.y)
            return True
        return inside

    def _key(self, e):
        mod = getattr(e, "mod", 0)
        ctrl = bool(mod & pygame.KMOD_CTRL)
        if ctrl and e.key == pygame.K_z:
            self.undo_stroke()
            return True
        if ctrl and e.key == pygame.K_y:
            self.redo_stroke()
            return True
        keys = {pygame.K_b: "brush", pygame.K_e: "eraser",
                pygame.K_f: "fill", pygame.K_l: "line", pygame.K_r: "rect",
                pygame.K_o: "ellipse", pygame.K_k: "pick"}
        if not ctrl and e.key in keys:
            self.tool = keys[e.key]
            self.message = f"tool: {self.tool}"
            return True
        return False

    def _run(self, action):
        kind, value = action
        if kind == "tool":
            self.tool = value
        elif kind == "colour":
            self.color = list(value)
        elif kind == "brush":
            self.brush = max(1, min(256, self.brush + value))
        elif kind == "pickcolor":
            self.owner.pick_paint_color(self)
        elif kind == "undo":
            self.undo_stroke()
        elif kind == "redo":
            self.redo_stroke()
        elif kind == "newlayer":
            self.stack.add(f"Layer {len(self.stack.layers) + 1}")
            self._after_stroke()
        elif kind == "dellayer":
            self.stack.drop_active()
            self.undo.clear()
            self.redo.clear()
            self._after_stroke()
        elif kind == "layerstep":
            self.stack.active = (self.stack.active + value) % \
                len(self.stack.layers)
            self._surf = None
        elif kind == "layervis":
            layer = self.stack.current()
            layer.visible = not layer.visible
            self._after_stroke()
        elif kind == "clip":
            self.paste_clipboard()
        elif kind == "sheet":
            self._pick_sheet()
        elif kind == "fit":
            self._auto_fit = True
            self._fit_canvas()
        elif kind == "target":
            self.owner.cycle_paint_object(value)

    def _pick_sheet(self):
        """Ask the Model tab to add a texture layer."""
        pick = getattr(self.owner, "uv_pick_texture", None)
        if pick is not None:
            pick(self)

    def _down(self, e):
        p = self._to_canvas(e.pos)
        if p is None:
            return
        if self.tool == "pick":
            self._eyedrop(p)
            return
        self._push_undo()
        self.drag = {"kind": self.tool, "last": p, "start": p}
        if self.tool == "brush":
            self._stamp(p)
        elif self.tool == "eraser":
            self._stamp(p, erase=True)
        elif self.tool == "fill":
            self._fill(p)
            self._after_stroke()

    def begin_surface_stroke(self, uv):
        """Start a 3D brush stroke at a normalized model UV."""
        p = self._from_uv(uv)
        if self.tool == "pick":
            self._eyedrop(p)
            return False
        if self.tool not in ("brush", "eraser"):
            self.message = "use Brush or Erase on the model surface"
            return False
        self._push_undo()
        kind = self.tool
        self.drag = {"kind": kind, "last": p, "start": p}
        self._stamp(p, erase=kind == "eraser")
        self._after_stroke()
        return True

    def continue_surface_stroke(self, uv):
        """Continue a 3D brush stroke at a normalized model UV."""
        if not self.drag or self.drag.get("kind") not in ("brush", "eraser"):
            return
        p = self._from_uv(uv)
        kind = self.drag["kind"]
        if max(abs(p[0] - self.drag["last"][0]),
               abs(p[1] - self.drag["last"][1])) > self.size[0] * 0.2:
            self.drag["last"] = p
            self._stamp(p, erase=kind == "eraser")
            self._after_stroke()
            return
        self._stroke_to(self.drag["last"], p, erase=kind == "eraser")
        self.drag["last"] = p
        self._after_stroke()

    def end_surface_stroke(self):
        if self.drag and self.drag.get("kind") in ("brush", "eraser"):
            self._after_stroke()
        self.drag = None

    def _from_uv(self, uv):
        u = max(0.0, min(1.0, float(uv[0])))
        v = max(0.0, min(1.0, float(uv[1])))
        return (u * (self.size[0] - 1),
                (1.0 - v) * (self.size[1] - 1))

    def _move(self, e):
        if not self.drag or self.drag.get("kind") == "pan":
            return
        p = self._to_canvas(e.pos)
        if p is None:
            return
        kind = self.drag["kind"]
        if kind in ("brush", "eraser"):
            self._stroke_to(self.drag["last"], p,
                           erase=kind == "eraser")
            self.drag["last"] = p
            self._after_stroke()
        elif kind == "rect":
            self._shape_to(p, "rect")
        elif kind == "ellipse":
            self._shape_to(p, "ellipse")
        elif kind == "line":
            self._shape_to(p, "line")

    def _up(self, e):
        kind = self.drag.get("kind") if self.drag else None
        if kind in ("brush", "eraser", "fill"):
            self._after_stroke()
        elif kind in ("rect", "ellipse", "line"):
            self._shape_commit()
        self.drag = None

    def _layer(self):
        return self.stack.current().arr

    def _stroke_to(self, a, b, erase=False):
        steps = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
        for k in range(steps + 1):
            t = k / steps
            self._stamp((a[0] + (b[0] - a[0]) * t,
                         a[1] + (b[1] - a[1]) * t), erase=erase)

    def _stamp(self, p, erase=False):
        arr = self._layer()
        r = float(self.brush) / 2.0
        x0 = int(max(0, p[0] - r - 1))
        x1 = int(min(self.size[0], p[0] + r + 2))
        y0 = int(max(0, p[1] - r - 1))
        y1 = int(min(self.size[1], p[1] + r + 2))
        if x1 <= x0 or y1 <= y0:
            return
        ys, xs = np.mgrid[y0:y1, x0:x1]
        distance = np.sqrt((xs - p[0]) ** 2 + (ys - p[1]) ** 2)
        coverage = np.clip(r + 0.75 - distance, 0.0, 1.0)
        win = arr[y0:y1, x0:x1]
        touched = coverage > 0.0
        if erase:
            alpha = win[..., 3].astype(np.float32)
            alpha[touched] *= 1.0 - coverage[touched]
            win[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)
            win[win[..., 3] == 0, :3] = 0
            return
        source_alpha = coverage * (int(self.color[3]) / 255.0)
        dest_alpha = win[..., 3].astype(np.float32) / 255.0
        out_alpha = source_alpha + dest_alpha * (1.0 - source_alpha)
        rgb = win[..., :3].astype(np.float32)
        numerator = (np.asarray(self.color[:3], np.float32) *
                     source_alpha[..., None] +
                     rgb * dest_alpha[..., None] *
                     (1.0 - source_alpha[..., None]))
        nonzero = touched & (out_alpha > 1e-6)
        rgb[nonzero] = numerator[nonzero] / out_alpha[nonzero, None]
        win[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        win[..., 3] = np.clip(out_alpha * 255.0, 0, 255).astype(np.uint8)

    def _eyedrop(self, p):
        comp = self.stack.composite()
        col = comp[int(p[1]), int(p[0])]
        if col[3] > 0:
            self.color = [int(c) for c in col]
            self.message = "picked colour"

    def _fill(self, p):
        """Flood the active layer's contiguous region under the point."""
        arr = self._layer()
        h, w = arr.shape[0], arr.shape[1]
        sx, sy = int(p[0]), int(p[1])
        if not (0 <= sx < w and 0 <= sy < h):
            return
        target = arr[sy, sx].copy()
        repl = np.array(self.color, np.uint8)
        if bool((target == repl).all()):
            return
        # a tolerance keeps a fill from crawling through near-matches
        diff = (np.abs(arr.astype(np.int16) - target.astype(np.int16))
                .sum(axis=2) <= 12)
        seen = np.zeros((h, w), bool)
        stack = [(sy, sx)]
        while stack:
            y, x = stack.pop()
            if x < 0 or y < 0 or x >= w or y >= h:
                continue
            if seen[y, x] or not diff[y, x]:
                continue
            seen[y, x] = True
            arr[y, x] = repl
            stack.append((y + 1, x))
            stack.append((y - 1, x))
            stack.append((y, x + 1))
            stack.append((y, x - 1))

    def _shape_to(self, p, kind):
        self.drag["end"] = p

    def _shape_preview_surface(self):
        return None

    def _shape_commit(self):
        d = self.drag
        if "end" not in d:
            return
        a, b = d["start"], d["end"]
        arr = self._layer()
        col = tuple(int(c) for c in self.color)
        if d["kind"] == "line":
            self._draw_line(arr, a, b, col)
        elif d["kind"] == "rect":
            self._draw_rect(arr, a, b, col)
        elif d["kind"] == "ellipse":
            self._draw_ellipse(arr, a, b, col)
        self._after_stroke()

    def _draw_line(self, arr, a, b, col, width=None):
        w = width or max(1, self.brush // 2)
        x0, y0 = int(a[0]), int(a[1])
        x1, y1 = int(b[0]), int(b[1])
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self._dot(arr, x0, y0, w, col)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def _dot(self, arr, x, y, w, col):
        h, wd = arr.shape[0], arr.shape[1]
        for yy in range(y - w, y + w + 1):
            for xx in range(x - w, x + w + 1):
                if 0 <= xx < wd and 0 <= yy < h:
                    arr[yy, xx] = col

    def _draw_rect(self, arr, a, b, col):
        x0, x1 = sorted((int(a[0]), int(b[0])))
        y0, y1 = sorted((int(a[1]), int(b[1])))
        w = max(1, self.brush // 3)
        self._draw_line(arr, (x0, y0), (x1, y0), col, w)
        self._draw_line(arr, (x1, y0), (x1, y1), col, w)
        self._draw_line(arr, (x1, y1), (x0, y1), col, w)
        self._draw_line(arr, (x0, y1), (x0, y0), col, w)

    def _draw_ellipse(self, arr, a, b, col):
        cx = (a[0] + b[0]) / 2.0
        cy = (a[1] + b[1]) / 2.0
        rx = max(1.0, abs(b[0] - a[0]) / 2.0)
        ry = max(1.0, abs(b[1] - a[1]) / 2.0)
        steps = int(max(rx, ry) * 4) + 16
        pts = []
        for k in range(steps + 1):
            ang = 2 * math.pi * k / steps
            pts.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
        w = max(1, self.brush // 3)
        for p0, p1 in zip(pts, pts[1:]):
            self._draw_line(arr, p0, p1, col, w)

    def _push_undo(self):
        self.undo.append((self.stack.current(), self._layer().copy()))
        if len(self.undo) > 40:
            self.undo.pop(0)
        self.redo.clear()

    def undo_stroke(self):
        if not self.undo:
            return
        layer, before = self.undo.pop()
        if layer not in self.stack.layers:
            return
        self.redo.append((layer, layer.arr.copy()))
        layer.arr = before
        self.stack.active = self.stack.layers.index(layer)
        self._after_stroke()

    def redo_stroke(self):
        if not self.redo:
            return
        layer, after = self.redo.pop()
        if layer not in self.stack.layers:
            return
        self.undo.append((layer, layer.arr.copy()))
        layer.arr = after
        self.stack.active = self.stack.layers.index(layer)
        self._after_stroke()

    def _after_stroke(self):
        self._surf = None
        self._layer_thumbs.clear()
        self.revision += 1
        self.has_edits = True
        self.owner.dirty = True

    def add_image_layer(self, arr, name):
        """Drop a full-canvas RGBA array in as a layer."""
        self.stack.add(name, arr=arr)
        self._after_stroke()

    def paste_clipboard(self):
        """Add the clipboard's image (if any) as a new layer."""
        try:
            from PIL import ImageGrab
        except Exception:
            self.message = "clipboard images need Pillow"
            return False
        img = ImageGrab.grabclipboard()
        if img is None:
            self.message = "clipboard has no image"
            return False
        self.add_image_layer(_fit_rgba(img, self.size), "Clipboard")
        self.message = "pasted clipboard image"
        return True

    def add_sheet_layer(self, key, path):
        """Add one of the project's textures as a layer."""
        try:
            from PIL import Image
            with Image.open(path) as im:
                self.add_image_layer(_fit_rgba(im, self.size), str(key))
        except Exception as exc:
            self.message = f"cannot add {key}: {exc}"
            return False
        self.message = f"added sheet {key}"
        return True

    def commit(self):
        """The flattening, as a uint8 (H, W, 4) array."""
        return self.stack.composite()

    def commit_to_model(self, stem):
        """Write the atlas and wear it, per picked object."""
        surface = self.commit()
        obj = None
        if self.model is not None and self.model.has_objects \
                and self._object_faces() is not None:
            obj = str(self.objname)
        tex_key = f"{stem}-{obj}-uv-tex" if obj else f"{stem}-uv-tex"
        project = self.owner.app.project
        renderer = self.owner.renderer
        try:
            project.store_texture(tex_key, surface, renderer)
        except Exception as exc:
            self.message = f"texture save failed: {exc}"
            return False
        if obj is not None:
            for o in self.model.objects:
                if o["name"] == obj:
                    o["texture"] = tex_key
                    o["painted"] = True
        else:
            self.model.painted = True
            self.model.texture = tex_key
        self.has_edits = False
        self.owner._refresh_mesh()
        self.message = f"painted {tex_key}.png"
        return True

    def draw(self, surface, rect):
        rect = pygame.Rect(rect)
        self._layout(rect)
        self._draw_toolbar(surface)
        self._draw_canvas(surface)
        self._draw_wire(surface)
        self._draw_preview(surface)
        self._draw_layers(surface)
        self._draw_status(surface, rect)

    def _layout(self, rect):
        items = self._toolbar_items()
        x, y = rect.x + 4, rect.y + 1
        rows = 1
        for item in items:
            if x + item[0] > rect.right - 4:
                x, y = rect.x + 4, y + 24
                rows += 1
            x += item[0] + 3
        self.toolbar_h = rows * 24
        self.bar = pygame.Rect(rect.x, rect.y, rect.width, self.toolbar_h)
        top = rect.y + self.toolbar_h + 2
        body = pygame.Rect(rect.x, top, rect.width,
                           max(10, rect.bottom - top - 20))
        cw = int(body.width * SPLIT)
        if body.width - cw < 120:
            cw = body.width
        self.canvas_rect = pygame.Rect(body.x, body.y, cw, body.height)
        self.preview_rect = pygame.Rect(body.right - (body.width - cw),
                                        body.y, body.width - cw, body.height)
        split = int(self.preview_rect.height * 0.58)
        self.preview_viewport = pygame.Rect(
            self.preview_rect.x + 2, self.preview_rect.y + 2,
            max(1, self.preview_rect.width - 4), max(1, split - 4))
        self.layers_rect = pygame.Rect(
            self.preview_rect.x, self.preview_rect.y + split,
            self.preview_rect.width,
            max(1, self.preview_rect.height - split))
        fit_size = self.canvas_rect.size
        if self._auto_fit and fit_size != self._fit_size:
            self._fit_canvas()
            self._fit_size = fit_size

    def _fit_canvas(self):
        """Fit and centre the whole UV sheet in the available canvas area."""
        w, h = self.canvas_rect.size
        if w < 1 or h < 1:
            return
        self.view["zoom"] = max(
            0.05, min(6.0, (w - 24) / self.size[0],
                     (h - 24) / self.size[1]))
        self.view["x"] = self.view["y"] = 0.0
        self._surf = None

    def _toolbar_items(self):
        """Button labels and actions used by the wrapping paint toolbar."""
        items = [(self.owner.small.size(label)[0] + 12,
                  label, ("tool", value), self.tool == value)
                 for value, label in TOOL_LABELS]
        items.extend([
            (18, "-", ("brush", -2), False),
            (self.owner.small.size(f"{self.brush}px")[0] + 12,
             f"{self.brush}px", ("none", None), False),
            (18, "+", ("brush", 2), False),
            (self.owner.small.size("Color")[0] + 12,
             "Color", ("pickcolor", None), False),
            (self.owner.small.size("Undo")[0] + 12,
             "Undo", ("undo", None), False),
            (self.owner.small.size("Redo")[0] + 12,
             "Redo", ("redo", None), False),
            (18, "<", ("layerstep", -1), False),
            (self.owner.small.size(f"L{self.stack.active + 1}")[0] + 12,
             f"L{self.stack.active + 1}",
             ("none", None), True),
            (18, ">", ("layerstep", 1), False),
            (self.owner.small.size("Vis")[0] + 12,
             "Vis", ("layervis", None), self.stack.current().visible),
            (self.owner.small.size("+ layer")[0] + 12,
             "+ layer", ("newlayer", None), False),
            (self.owner.small.size("- layer")[0] + 12,
             "- layer", ("dellayer", None), False),
            (self.owner.small.size("Paste")[0] + 12,
             "Paste", ("clip", None), False),
            (self.owner.small.size("Sheet")[0] + 12,
             "Sheet", ("sheet", None), False),
            (self.owner.small.size("Fit")[0] + 12,
             "Fit", ("fit", None), False)])
        if self.model is not None and self.model.has_objects:
            objects = self.model.object_names()
            selected = next((i for i, o in enumerate(objects)
                             if o == self.objname), 0)
            target = objects[selected] if objects else "all objects"
            items.extend([
                (self.owner.small.size("‹")[0] + 12, "‹",
                 ("target", -1), False),
                (self.owner.small.size(target)[0] + 12, target,
                 ("none", None), True),
                (self.owner.small.size("›")[0] + 12, "›",
                 ("target", 1), False)])
        items.extend((20, "", ("colour", c), False) for c in PALETTE)
        return items

    def _draw_toolbar(self, surface):
        self.buttons = []
        x = self.bar.x + 4
        y = self.bar.y + 1
        for w, label, action, active in self._toolbar_items():
            if x + w > self.bar.right - 4:
                x, y = self.bar.x + 4, y + 24
            r = pygame.Rect(x, y, w, 20)
            self.buttons.append({"rect": r, "action": action,
                                 "label": label, "active": active})
            x = r.right + 3
        mouse = pygame.mouse.get_pos()
        for b in self.buttons:
            if b["action"][0] == "colour":
                color = b["action"][1]
                pygame.draw.rect(surface, tuple(color[:3]), b["rect"])
                if list(color) == self.color:
                    pygame.draw.rect(surface, (255, 255, 0), b["rect"], 2)
                else:
                    pygame.draw.rect(surface, xp.OUTLINE, b["rect"], 1)
                continue
            xp.button(surface, b["rect"], b["label"], self.owner.small,
                      default=b["active"],
                      hovered=b["rect"].collidepoint(mouse))
        for b in self.buttons:
            if b["rect"].collidepoint(mouse):
                tip = self._toolbar_tip(b["action"])
                if tip:
                    xp.tooltip(surface, mouse, [tip], self.owner.small)
                break

    @staticmethod
    def _toolbar_tip(action):
        kind, value = action
        if kind == "tool":
            return {
                "brush": "Paint on the active layer (B)",
                "eraser": "Erase on the active layer (E)",
                "fill": "Fill the connected area under the pointer (F)",
                "line": "Draw a line between two points (L)",
                "rect": "Draw a rectangle outline (R)",
                "ellipse": "Draw an oval outline (O)",
                "pick": "Pick a colour from the canvas (K)",
            }.get(value)
        if kind == "brush":
            return "Decrease or increase the brush size"
        if kind == "colour":
            return "Use this paint colour"
        if kind == "pickcolor":
            return "Choose a custom paint colour"
        if kind == "undo":
            return "Undo the last brush stroke (Ctrl+Z)"
        if kind == "redo":
            return "Redo the last brush stroke (Ctrl+Y)"
        if kind == "newlayer":
            return "Add a transparent layer above the active layer"
        if kind == "dellayer":
            return "Delete the active layer"
        if kind == "layerstep":
            return "Select the previous or next layer"
        if kind == "layervis":
            return "Show or hide the active layer"
        if kind == "clip":
            return "Paste an image from the clipboard as a layer"
        if kind == "sheet":
            return "Add a project texture as a paint layer"
        if kind == "fit":
            return "Fit the complete UV atlas in the canvas"
        if kind == "target":
            return "Switch the active object UV atlas"
        return None

    def _draw_status(self, surface, rect):
        status = pygame.Rect(rect.x + 4, rect.bottom - 18,
                             rect.width - 8, 16)
        pygame.draw.rect(surface, xp.FACE, status)
        text = self.message or (
            f"{self.size[0]}x{self.size[1]}  "
            f"{self.stack.current().name}  "
            f"{self.tool}  {self.brush}px")
        img = widgets.cached_text(self.owner.small, text, (214, 218, 226))
        if img:
            old_clip = surface.get_clip()
            surface.set_clip(status.inflate(-4, 0))
            surface.blit(img, (status.x + 4,
                               status.centery - img.get_height() // 2))
            surface.set_clip(old_clip)

    def color_index(self):
        for i, c in enumerate(PALETTE):
            if list(c) == self.color:
                return i
        return -1

    def _canvas_surface(self):
        """The composite as a surface, rebuilt when stale."""
        stamp = self._stamp_key()
        if self._surf is None or self._surf_stamp != stamp:
            comp = self.commit()
            self._surf = pygame.image.frombuffer(
                comp.tobytes(), self.size, "RGBA")
            self._surf_stamp = stamp
        return self._surf

    def _stamp_key(self):
        layer = self.stack.current()
        return (id(layer.arr), layer.arr.__array_interface__["data"][0],
                self.stack.active, len(self.stack.layers), self.revision)

    def _draw_canvas(self, surface):
        rect = self.canvas_rect
        pygame.draw.rect(surface, (30, 33, 40), rect)
        if rect.width < 4 or rect.height < 4:
            return
        old_clip = surface.get_clip()
        surface.set_clip(rect)
        z = self.view["zoom"]
        w, h = max(1, int(self.size[0] * z)), \
            max(1, int(self.size[1] * z))
        ox = rect.centerx - w // 2 - int(self.view["x"] * z)
        oy = rect.centery - h // 2 - int(self.view["y"] * z)
        box = pygame.Rect(ox, oy, max(1, w), max(1, h))
        view = pygame.transform.smoothscale(self._canvas_surface(), (w, h))
        surface.blit(view, box.topleft)
        pygame.draw.rect(surface, (70, 76, 90), box, 1)
        self._box = box
        surface.set_clip(old_clip)

    def _draw_wire(self, surface):
        """Outline the unwrapped uv2 patches over the canvas, of the"""
        if self.model is None or not getattr(self.model, "uv2", None):
            return
        box = getattr(self, "_box", None)
        if box is None:
            return
        faces = self._object_faces()
        only = set(faces) if faces is not None else None
        old_clip = surface.get_clip()
        surface.set_clip(self.canvas_rect)
        uv2 = self.model.uv2
        for ti, t in enumerate(self.model.tris):
            if only is not None and ti not in only:
                continue
            pts = []
            for vi in t:
                if vi >= len(uv2):
                    pts = None
                    break
                u, v = uv2[vi]
                pts.append((box.x + u * box.width,
                            box.y + (1.0 - v) * box.height))
            if pts:
                points = [(int(p[0]), int(p[1])) for p in pts]
                pygame.draw.lines(surface, (28, 34, 46), True, points, 3)
                pygame.draw.lines(surface, (95, 169, 236), True, points, 1)
        surface.set_clip(old_clip)

    def _draw_preview(self, surface):
        """Live model viewport for painting directly on the surface."""
        rect = self.preview_rect
        if rect.width < 4 or rect.height < 4:
            return
        owner = self.owner
        pygame.draw.rect(surface, (26, 30, 36), rect)
        xp.sunken(surface, rect)
        if owner.model is None:
            return
        inner = self.preview_viewport
        owner._ensure_renderer(inner.size)
        cam = owner.orbit.camera()
        frame = owner.renderer.render(cam, owner.studio)
        if frame.get_size() != inner.size:
            frame = pygame.transform.smoothscale(frame, inner.size)
        surface.blit(frame, inner.topleft)
        mouse = pygame.mouse.get_pos()
        if inner.collidepoint(mouse) and owner._paint_uv_at(
                cam, inner.size, (mouse[0] - inner.x, mouse[1] - inner.y)):
            radius = max(3, min(24, int(self.brush * self.view["zoom"] / 2)))
            pygame.draw.circle(surface, tuple(self.color[:3]), mouse, radius, 1)
            pygame.draw.circle(surface, (245, 245, 245), mouse, 2)

    def _draw_layers(self, surface):
        area = self.layers_rect
        self.layer_rows = []
        pygame.draw.rect(surface, (35, 39, 47), area)
        header = pygame.Rect(area.x, area.y, area.width, 22)
        widgets.header(surface, header, "Layers",
                       self.owner.small, right=str(len(self.stack.layers)))
        body = pygame.Rect(area.x + 4, header.bottom + 2,
                           max(1, area.width - 8),
                           max(1, area.bottom - header.bottom - 4))
        pygame.draw.rect(surface, xp.FIELD, body)
        xp.sunken(surface, body)
        row_h = 26
        page = max(1, body.height // row_h)
        self.layer_scroll = max(
            0, min(self.layer_scroll, max(0, len(self.stack.layers) - page)))
        visible = list(reversed(range(len(self.stack.layers))))
        old = surface.get_clip()
        surface.set_clip(body.inflate(-2, -2))
        y = body.y + 2
        for i in visible[self.layer_scroll:self.layer_scroll + page]:
            layer = self.stack.layers[i]
            row = pygame.Rect(body.x + 2, y, body.width - 6, row_h)
            eye = pygame.Rect(row.right - 24, row.y + 3, 20, row.height - 6)
            if i == self.stack.active:
                surface.fill(xp.SELECTION, row)
            elif row.collidepoint(pygame.mouse.get_pos()):
                surface.fill(xp.BTN_HOVER_BG, row)
            thumb = pygame.Rect(row.x + 4, row.y + 4, 24, row.height - 8)
            pygame.draw.rect(surface, (52, 56, 64), thumb)
            stamp = (id(layer), layer.arr.__array_interface__["data"][0],
                     thumb.size)
            preview = self._layer_thumbs.get(stamp)
            if preview is None:
                image = pygame.image.frombuffer(
                    layer.arr.tobytes(), self.size, "RGBA")
                preview = pygame.transform.smoothscale(image, thumb.size)
                self._layer_thumbs[stamp] = preview
            surface.blit(preview, thumb.topleft)
            pygame.draw.rect(surface, xp.OUTLINE, thumb, 1)
            label = widgets.elide(self.owner.small, layer.name,
                                  max(8, eye.x - thumb.right - 8))
            image = widgets.cached_text(
                self.owner.small, label,
                (255, 255, 255) if i == self.stack.active else
                (xp.TEXT if layer.visible else xp.TEXT_MUTED))
            if image is not None:
                surface.blit(image, (thumb.right + 5,
                                     row.centery - image.get_height() // 2))
            pygame.draw.ellipse(surface, (194, 204, 218), eye.inflate(-5, -8),
                                1)
            pupil = (194, 204, 218) if layer.visible else xp.TEXT_MUTED
            pygame.draw.circle(surface, pupil, eye.center, 2)
            self.layer_rows.append((layer, row, eye))
            y += row_h
        surface.set_clip(old)


def _fit_rgba(img, size):
    """A PIL image as a canvas-sized RGBA array."""
    rgba = img.convert("RGBA")
    w, h = size
    arr = np.zeros((h, w, 4), np.uint8)
    tw, th = min(w, rgba.width), min(h, rgba.height)
    if (tw, th) != (rgba.width, rgba.height):
        rgba = rgba.crop((0, 0, tw, th))
    src = np.asarray(rgba, np.uint8)
    arr[:src.shape[0], :src.shape[1]] = src
    return arr
