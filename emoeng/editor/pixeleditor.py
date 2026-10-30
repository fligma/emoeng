"""The Pixel tab: paint a picture on layers, save it as one PNG.

The layers live in this tab only; saving flattens them and says so.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame
from PIL import Image

from ..engine import xp
from . import widgets
from .uvpaint import LayerStack, UVPaint

DEFAULT_SIZE = (64, 64)     # a new sprite starts small: pixels are the point
MAX_NEW = 1024              # the largest blank canvas New will make
CHECKER = 4                 # image pixels per transparency square
PREVIEW_H = 150             # the right column's look at the saved PNG


class _Host:
    """The owner fields UVPaint borrows from the Model tab."""

    def __init__(self, tab):
        self.tab = tab
        self.small = tab.app.fonts["small"]
        self.dirty = False


class PixelEditor(UVPaint):
    """Paint one image on layers; Save flattens them into a PNG."""

    # nearest-neighbour: a pixel keeps its square corners
    SMOOTH = False

    def __init__(self, app):
        self.app = app
        super().__init__(_Host(self), None)
        self.path = None            # the PNG on disk, or None for a new one
        self.dirty = False          # layers the file does not have yet
        self.grid = True            # the one-pixel grid, once zoomed enough
        self._checkers = {}         # size -> checkerboard, last few asked for
        self.reset(DEFAULT_SIZE)

    def use_fonts(self, fonts):
        """The app rebuilt its fonts; the toolbar reads this one."""
        self.owner.small = fonts["small"]
        self._checkers.clear()

    # -- the picture ---------------------------------------------------

    def reset(self, size, name=None, arr=None):
        """Start over on a blank canvas of `size`."""
        w, h = max(1, int(size[0])), max(1, int(size[1]))
        self.size = (w, h)
        self.stack = LayerStack(self.size)
        if arr is not None:
            self.stack.layers[0].arr = arr
        if name:
            self.stack.layers[0].name = str(name)
        self.undo.clear()
        self.redo.clear()
        self._surf = None
        self._layer_thumbs.clear()
        self._checkers.clear()
        self.revision += 1
        self.view = {"zoom": 1.0, "x": 0.0, "y": 0.0}
        self._auto_fit = True
        self._fit_size = None
        self.drag = None
        self.has_edits = False
        self.dirty = False
        self.message = ""
        return self.size

    def commit(self):
        """The flattening, keeping the layers' own alpha."""
        return self.stack.composite(base=None)

    def _after_stroke(self):
        super()._after_stroke()
        self.dirty = True

    # -- files ---------------------------------------------------------

    def set_project(self, project):
        """A project switch starts on an empty canvas."""
        if self.dirty:
            self.app.log("pixel: the unsaved layers went with the old "
                         "project", "muted")
        self.path = None
        self.reset(DEFAULT_SIZE)

    def create(self, path, size=DEFAULT_SIZE):
        """Write a blank PNG at `path`, then open it."""
        width = max(1, min(MAX_NEW, int(size[0])))
        height = max(1, min(MAX_NEW, int(size[1])))
        data = np.zeros((height, width, 4), np.uint8)
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(data, "RGBA").save(path)
        except (OSError, ValueError) as exc:
            self.app.log(f"pixel: cannot make {path.name}: {exc}", "error")
            return False
        return self.open(path, force=True)

    def open(self, path, force=False):
        """Load a PNG or JPG as one layer named after the file."""
        path = Path(path)
        if self.dirty and not force:
            self.message = "save this image before opening another"
            self.app.log("pixel: save this image before opening another",
                         "warn")
            return False
        try:
            with Image.open(path) as im:
                arr = np.array(im.convert("RGBA"), np.uint8)
        except (OSError, ValueError) as exc:
            self.app.log(f"pixel: cannot open {path.name}: {exc}", "error")
            return False
        self.path = path
        self.reset((arr.shape[1], arr.shape[0]), name=path.stem, arr=arr)
        self.message = f"{path.name}  {self.size[0]}x{self.size[1]}"
        return True

    def save(self, force=False):
        """Flatten the layers into the PNG on disk."""
        if self.path is None:
            self.message = "this image has no file yet"
            self.app.log("pixel: this image has no file yet; use New",
                         "warn")
            return False
        layers = len(self.stack.layers)
        if layers > 1 and not force:
            # a PNG cannot carry the stack, so say so before writing
            self.app.dialog_kind = "pixel_save"
            self.app.dialog = widgets.ChoiceDialog(
                "Save PNG",
                f"{self.path.name} will hold these {layers} layers as one "
                "flattened image.",
                ("Save PNG", "Cancel"),
                hint="The PNG cannot keep the layers: opening the file again "
                     "gives you one layer, so save once the picture is "
                     "ready.", default=0)
            return False
        project = self.app.project
        try:
            inside = project is not None and \
                self.path.suffix.lower() == ".png" and \
                self.path.parent.resolve() == project.textures_dir.resolve()
            if inside:
                # the project owns the sheet: write it the way every other
                # texture is written, so the preview wears it at once
                self.path = Path(project.store_texture(
                    self.path.stem, self.commit(), self._renderer()))
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(self.commit(), "RGBA").save(self.path)
        except (OSError, ValueError) as exc:
            self.message = f"save failed: {exc}"
            self.app.log(f"pixel: save failed: {exc}", "error")
            return False
        self.dirty = False
        self.has_edits = False
        self.message = f"saved {self.path.name}, {layers} flattened"
        self.app.log(f"saved {self.path.name}: {layers} layer(s) flattened "
                     "into the PNG", "ok")
        self.app.status = f"saved {self.path.name}"
        self.app.refresh_tree()
        return True

    def _renderer(self):
        """The preview's renderer, when the sheet has to be worn."""
        return getattr(getattr(self.app, "preview", None), "renderer", None)

    def next_image(self):
        """Open the next texture the project carries, wrapping around."""
        project = self.app.project
        if project is None:
            self.message = "open a project first"
            return False
        if self.dirty:
            self.message = "save this image before switching"
            self.app.log("pixel: save this image before switching", "warn")
            return False
        files = list(project.texture_files())
        if not files:
            self.message = "this project has no textures yet"
            self.app.log("pixel: this project has no textures; use New",
                         "muted")
            return False
        here = next((i for i, p in enumerate(files)
                     if self.path is not None and
                     p.resolve() == self.path.resolve()), -1)
        return self.open(files[(here + 1) % len(files)])

    # -- tools ---------------------------------------------------------

    def _toolbar_items(self):
        """The paint buttons, with the file actions where Sheet was."""
        items = [item for item in super()._toolbar_items()
                 if item[2][0] not in ("sheet", "target")]
        small = self.owner.small
        made = [(small.size(label)[0] + 12, label, (kind, None), active)
                for kind, label, active in (("save", "Save", False),
                                            ("next", "Next", False),
                                            ("new", "New", False),
                                            ("resize", "Size", False),
                                            ("zoomin", "+", False),
                                            ("zoomout", "-", False),
                                            ("grid", "Grid", self.grid))]
        # the palette swatches close the row, so the file buttons go first
        at = next((i for i, item in enumerate(items)
                   if item[2][0] == "colour"), len(items))
        return items[:at] + made + items[at:]

    def _run(self, action):
        kind = action[0]
        if kind == "save":
            return self.save()
        if kind == "next":
            return self.next_image()
        if kind == "new":
            self.app._prompt("new_image")
            return True
        if kind == "resize":
            return self.prompt_resize()
        if kind in ("zoomin", "zoomout"):
            self.zoom(1.25 if kind == "zoomin" else 0.8)
            return True
        if kind == "grid":
            self.grid = not self.grid
            return True
        if kind == "pickcolor":
            self.app.pick_color("Paint colour", self.color_hex(),
                                self.set_color)
            return True
        return super()._run(action)

    @staticmethod
    def _toolbar_tip(action):
        kind = action[0]
        if kind == "save":
            return "Write the flattened image as a PNG (Ctrl+S)"
        if kind == "next":
            return "Open the next texture this project carries"
        if kind == "new":
            return "Make a blank PNG in the project's textures"
        if kind == "resize":
            return "Scale every layer to a new canvas size"
        if kind == "zoomin":
            return "Zoom in on the canvas"
        if kind == "zoomout":
            return "Zoom out of the canvas"
        if kind == "grid":
            return "Show or hide the one-pixel grid"
        return UVPaint._toolbar_tip(action)

    def prompt_resize(self):
        """Ask for a new canvas size, in pixels."""
        self.app.dialog_kind = "pixel_resize"
        self.app.dialog = widgets.PromptDialog(
            "Canvas Size", "New size (W x H)",
            f"{self.size[0]}x{self.size[1]}",
            hint="Every layer is stretched to the new size, nearest pixel "
                 "to nearest, so the picture keeps its hard edges.",
            width=400)
        return True

    def zoom(self, factor):
        """Scale the canvas view about its centre."""
        self._auto_fit = False
        self.view["zoom"] = max(0.1, min(48.0, self.view["zoom"] * factor))
        self._surf = None
        self.message = f"zoom {self.view['zoom']:.1f}x"
        return True

    def color_hex(self):
        return "#%02x%02x%02x" % tuple(int(c) for c in self.color[:3])

    def set_color(self, text):
        """Take the colour dialog's answer as the paint colour."""
        raw = str(text or "").strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        if len(raw) < 6:
            return
        try:
            rgb = tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return
        self.color = [rgb[0], rgb[1], rgb[2], 255]
        self.message = "colour " + self.color_hex()

    def handle_event(self, e):
        """The right column only shows the PNG; it takes no strokes."""
        pos = getattr(e, "pos", None)
        if pos is not None and e.type == pygame.MOUSEBUTTONDOWN and \
                self.preview_viewport.collidepoint(pos):
            return False
        if pos is not None and e.type == pygame.MOUSEWHEEL and \
                self.preview_viewport.collidepoint(pos):
            # wheeling over the little picture zooms the canvas under it
            self._auto_fit = False
            self.view["zoom"] = max(0.1, min(6.0, self.view["zoom"] *
                                              (1.15 if e.y else 0.87)))
            self._surf = None
            return True
        return super().handle_event(e)

    # -- drawing -------------------------------------------------------

    def draw(self, surface, rect):
        """The paint canvas and its layers, without the 3D half."""
        rect = pygame.Rect(rect)
        self._layout(rect)
        self._draw_toolbar(surface)
        self._draw_canvas(surface)
        self._draw_preview(surface)
        self._draw_layers(surface)
        self._draw_status(surface, rect)

    def _layout(self, rect):
        """The canvas on the left; the PNG preview over the layers."""
        super()._layout(rect)
        split = min(max(60, self.preview_rect.height // 3), PREVIEW_H)
        self.preview_viewport = pygame.Rect(
            self.preview_rect.x + 2, self.preview_rect.y + 2,
            max(1, self.preview_rect.width - 4), max(1, split - 4))
        self.layers_rect = pygame.Rect(
            self.preview_rect.x, self.preview_rect.y + split,
            self.preview_rect.width,
            max(1, self.preview_rect.height - split))

    def _checker_surface(self):
        """The transparency squares, one cell per few image pixels.

        The cells are measured in pixels of the picture rather than of the
        screen, so they scale with the zoom and never fight the grid.
        """
        size = self.size
        surf = self._checkers.get(size)
        if surf is not None:
            return surf
        surf = pygame.Surface(size)
        surf.fill((150, 150, 150))
        light = pygame.Surface((CHECKER, CHECKER))
        light.fill((196, 196, 196))
        for y in range(0, size[1], CHECKER * 2):
            for x in range(0, size[0], CHECKER * 2):
                surf.blit(light, (x, y))
                surf.blit(light, (x + CHECKER, y + CHECKER))
        if len(self._checkers) > 6:
            self._checkers.clear()
        self._checkers[size] = surf
        return surf

    def _checker_view(self, size):
        """The checker run out to a screen box; nearest keeps it crisp."""
        return pygame.transform.scale(self._checker_surface(), size)

    def _draw_canvas(self, surface):
        """The picture at its zoom, on the grey that means transparent."""
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
        surface.blit(self._checker_view(box.size), box.topleft)
        view = pygame.transform.scale(self._canvas_surface(), box.size)
        surface.blit(view, box.topleft)
        if self.grid and z >= 6.0:
            self._draw_grid_lines(surface, box, z)
        pygame.draw.rect(surface, (70, 76, 90), box, 1)
        self._box = box
        surface.set_clip(old_clip)

    def _draw_grid_lines(self, surface, box, z):
        """One faint line per pixel, once a pixel is big enough to see."""
        for i in range(1, self.size[0]):
            x = box.x + int(i * z)
            if box.x < x < box.right:
                pygame.draw.line(surface, (52, 57, 66), (x, box.y),
                                 (x, box.bottom - 1))
        for j in range(1, self.size[1]):
            y = box.y + int(j * z)
            if box.y < y < box.bottom:
                pygame.draw.line(surface, (52, 57, 66), (box.x, y),
                                 (box.right - 1, y))

    def _draw_preview(self, surface):
        """The picture as the PNG will hold it, over the checker."""
        rect = self.preview_rect
        pygame.draw.rect(surface, (26, 30, 36), rect)
        xp.sunken(surface, rect)
        inner = self.preview_viewport.inflate(-6, -6)
        if inner.width < 4 or inner.height < 4:
            return
        w, h = self.size
        k = min(inner.width / w, inner.height / h)
        box = pygame.Rect(0, 0, max(1, int(w * k)), max(1, int(h * k)))
        box.center = inner.center
        old_clip = surface.get_clip()
        surface.set_clip(inner.inflate(2, 2))
        surface.blit(self._checker_view(box.size), box.topleft)
        view = pygame.transform.smoothscale(self._canvas_surface(), box.size)
        surface.blit(view, box.topleft)
        pygame.draw.rect(surface, xp.OUTLINE, box, 1)
        surface.set_clip(old_clip)

    def info(self):
        """Rows for the Inspector, as (label, value) pairs."""
        rows = [("Image", self.path.name if self.path else "(unsaved)")]
        if self.path is not None:
            rows.append(("Folder", self.app.relative(self.path)))
        rows += [("Size", f"{self.size[0]} x {self.size[1]}"),
                 ("Zoom", f"{self.view['zoom']:.1f}x"),
                 ("Layers", str(len(self.stack.layers))),
                 ("Painting", self.stack.current().name),
                 ("Opacity", f"{self.stack.current().opacity * 100:.0f}%"),
                 ("Shapes", "solid" if self.filled else "outline"),
                 ("Tool", f"{self.tool}, {self.brush}px"),
                 ("Grid", "on" if self.grid else "off"),
                 ("Save", "PNG, flattened")]
        if self.dirty:
            rows.append(("Unsaved", "the layers live in this tab"))
        return rows
