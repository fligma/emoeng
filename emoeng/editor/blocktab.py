"""The Blocks tab: a file as a Blueprint graph."""

import time
from pathlib import Path

import pygame

from ..engine import inputmap
from ..engine import xp
from . import api
from . import blocks
from . import widgets

BAR_H = 28            # one palette row, before zoom and font scaling
NODE_PAD = 11         # inside a node, left and right
NODE_GAP = 30         # air the auto layout leaves under a node
PIN_ROOM = 13         # the pin and the air beside it
GUTTER = 15           # how far the exec pins sit from the left edge
PILL_PAD = 8          # inside padding of a value field
PILL_MIN = 44         # an empty value is still worth clicking
VALUE_MAX = 250       # a value field never grows past this, before zoom
RAW_MAX = 430         # ...and a raw node's code is cut off here
DRAWER_W = 176        # the palette column
TOOL_H = 30           # the toolbar row above canvas and drawer
CAT_W = 10            # the colour strip on every drawer row
MIN_ZOOM, MAX_ZOOM = 0.05, 2.0   # a whole board, or a few words of one
DRAG_AFTER = 4          # pixels the mouse moves before a click is a drag
SCROLL_STEP = 28        # one wheel notch, before zoom
MAX_TYPE = 4000         # how much may be typed into one slot

# a fixed dark board; category colours need dark
CANVAS_BG = (30, 33, 40)
CANVAS_DOT = (49, 54, 64)
DOT_STEP = 26
PIN = (238, 236, 228)           # the exec diamond on every node
NODE_BG = (41, 45, 55)          # a node's body, top
NODE_BG_BOT = (34, 37, 46)      # ...and bottom
WIRE_DARK = (15, 17, 22)        # the shadow under an exec wire
TYPE_COLORS = {                 # what a value pin is coloured by
    "num": (146, 202, 96),
    "text": (226, 116, 156),
    "object": (86, 160, 226),
    "bool": (206, 84, 78),
    "any": (196, 200, 210),
}

# a slot's row words, else its name unspaced
SLOT_NAMES = {"fn": "function", "who": "object", "expr": "value",
              "cond": "condition", "args": "arguments", "pos": "position",
              "color": "colour", "col": "colour", "word": "mode",
              "op": "operator", "amount": "amount", "seconds": "seconds",
              "texture": "texture", "scene": "scene", "model": "model",
              # a `g` call's arguments in painting words, not letters
              "uv": "coords", "a": "from", "b": "to", "t": "blend",
              "x": "value", "h": "hue", "lo": "low", "hi": "high",
              "direction": "direction", "speed": "speed",
              "scale": "scale", "shader": "shader", "knob": "knob"}

# the strip above the canvas; "-" is a gap
TOOL_BUTTONS = (("text", "Text"), ("reload", "Reload"), ("-", None),
                ("undo", "Undo"), ("redo", "Redo"), ("-", None),
                ("tidy", "Tidy"), ("out", "-"), ("fit", "Fit"),
                ("in", "+"), ("-", None), ("save", "Save"))

# one colour per drawer, so stacks read as categories
CATEGORY_COLORS = {
    "events": (255, 173, 31),
    "trigger": (232, 96, 140),
    "scene": (72, 145, 190),
    "object": (62, 172, 150),
    "entity": (170, 90, 60),
    "light": (238, 128, 74),
    "audio": (202, 104, 176),
    "ui": (150, 188, 74),
    "shader": (176, 106, 200),
    "input": (206, 84, 78),
    "save": (176, 148, 96),
    "control": (255, 200, 60),
    "data": (66, 163, 237),
    "functions": (150, 110, 220),
    "modules": (90, 175, 110),
    "code": (130, 130, 140),
}

# the short word a two-column strip shows, not a title
CATEGORY_TITLES = {"audio": "Sound", "ui": "Hud", "shader": "Look",
                   "functions": "Funcs"}

# three labelled palette bands; `blocks.CATEGORIES` keeps the order
CATEGORY_GROUPS = (("world", ("events", "trigger", "scene", "object",
                              "entity", "light", "audio", "ui", "shader")),
                   ("engine", ("input", "save")),
                   ("language", ("control", "data", "functions",
                                 "modules", "code")))


# `events` is built here; a hook is a plain def
_SCENE_KINDS = ("scene3d", "scene2d", "sceneui")
# a shader script hears none of the world's hooks
_SHADER_KINDS = ("shader",)
# preset node scripts are objects, so they hear object hooks
_NODE_KINDS = tuple(k for k in blocks.TYPE_CATEGORIES
                    if k not in _SHADER_KINDS)
_ANY_KINDS = _SCENE_KINDS + ("object3d", "object2d", "ui",
                             "player3d", "player2d") + _NODE_KINDS
# a hitbox hears movement, a timer its timeout
_HITBOX_KINDS = ("hitbox3d", "trigger3d", "hitbox2d", "trigger2d")
_TIMER_KINDS = ("timer3d", "timer2d")
HOOK_ROWS = (
    ("setup", "self", "once, when a scene or object comes in", _ANY_KINDS),
    ("build", "self", "once, right after setup, to make the geometry",
     _ANY_KINDS),
    ("update", "self, dt", "every frame", _ANY_KINDS),
    ("handle_event", "self, e", "for each key, button or quit event",
     _ANY_KINDS),
    ("draw", "self", "when this object is asked to paint itself",
     _ANY_KINDS),
    ("overlay", "self, screen", "after the world, straight on the screen",
     _ANY_KINDS),
    ("on_enter", "self", "when the player arrives here", _SCENE_KINDS),
    ("on_exit", "self", "when the player leaves", _SCENE_KINDS),
    ("on_timeout", "self", "when this timer's wait is up", _TIMER_KINDS),
    ("on_save", "self, save", "before a save is written", _SCENE_KINDS),
    ("on_load", "self, save", "after a save is read", _SCENE_KINDS),
    ("dispose", "self", "last, when the object is going away", _ANY_KINDS),
    ("frag", "self, g", "describes the picture this shader paints",
     _SHADER_KINDS),
)

# what a trigger hook is written with; one hook hears every name
TRIGGER_ARGS = "self, name, value"

# the volume hooks, moved out of `events` into the trigger drawer
TRIGGER_ROWS = (
    ("on_enter", "self, other", "when something moves into this shape",
     _HITBOX_KINDS),
    ("on_exit", "self, other", "when something leaves this shape",
     _HITBOX_KINDS),
)


def color_of(category):
    """A block category's fill, readable in both themes."""
    base = CATEGORY_COLORS.get(category, CATEGORY_COLORS["code"])
    if xp.FACE[0] > 200:               # light theme: deepen every fill
        return tuple(int(c * 0.82) for c in base)
    return base


def lighten(rgb, amount):
    """A gradient's top edge: the category colour toward white."""
    return tuple(int(c + (255 - c) * amount) for c in rgb[:3])


def text_on(rgb):
    """Black or white words, whichever the block colour allows."""
    red, green, blue = rgb[:3]
    return (255, 255, 255) if (red * 299 + green * 587 + blue * 114) < 420 \
        else (20, 20, 20)


def rounded_body(size, radius, top, bottom):
    """A rounded rect with a vertical gradient, blittable."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    body = pygame.Surface((w, h), pygame.SRCALPHA)
    xp.gradient_v(body, body.get_rect(), top, bottom)
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                     border_radius=max(0, int(radius)))
    body.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return body


def diamond(surface, cx, cy, r, fill, edge):
    """A Blueprint exec pin: a diamond with a dark rim."""
    pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    pygame.draw.polygon(surface, fill, pts)
    pygame.draw.polygon(surface, edge, pts, 1)


def pin_type(name, value):
    """A value pin's colour, guessed from name and words."""
    words = str(value or "").strip()
    if words in ("True", "False", "None"):
        return "bool"
    if words[:1] in ("\"", "'") or words.startswith("f\"") or \
            words.startswith("f'"):
        return "text"
    if name in ("pos", "color", "col", "amount", "seconds", "fade",
                "size", "speed", "angle", "scale", "at", "rate",
                "health", "distance", "walk", "run", "range", "damage",
                "cooldown", "half", "extent"):
        return "num"
    if name in ("who", "target", "scene", "model", "texture", "obj",
                "child"):
        return "object"
    if name in ("fn", "text", "label", "name", "title", "code", "args",
                "key", "action", "path", "expr", "shader", "knob",
                "ai_type", "team", "signal", "hitshape"):
        return "text"
    try:
        float(words)
    except (TypeError, ValueError):
        return "any"
    return "num"


def _dedent(code):
    """Plain code back to column zero for the parser."""
    lines = str(code).split("\n")
    leads = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    cut = min(leads) if leads else 0
    return "\n".join(line if not line.strip() else line[cut:] for line in lines)


# the drawer each file kind opens on
DRAWER_FOR = {"scene3d": "scene", "scene2d": "scene", "sceneui": "ui",
              "object3d": "object", "object2d": "object", "ui": "ui",
              "player3d": "object", "player2d": "object",
              "entity3d": "entity", "entity2d": "entity",
              "camera3d": "object", "camera2d": "object",
              "screen3d": "object", "screen2d": "object",
              "model3d": "object", "sprite2d": "object",
              "collision3d": "object", "hitbox3d": "object",
              "trigger3d": "object", "marker3d": "object",
              "collision2d": "object", "hitbox2d": "object",
              "trigger2d": "object", "marker2d": "object",
              "light3d": "light", "omnilight3d": "light",
              "spotlight3d": "light", "directionallight3d": "light",
              "light2d": "light", "pointlight2d": "light",
              "conelight2d": "light", "rectlight2d": "light",
              "audio3d": "audio", "audio2d": "audio",
              "text3d": "object", "text2d": "object",
              "timer3d": "functions", "timer2d": "functions",
              "shader": "shader",
              "script": "data"}


class BlockTab:
    """The node graph view of one `.py` file."""

    # path to {key: (x, y)}: where the player placed nodes
    _layouts = {}

    def __init__(self, app):
        self.app = app
        self.path = None
        self.module = blocks.Module()
        self.zoom = 1.0
        self.scroll = 0
        self.hscroll = 0             # how far the board is panned to the right
        self.drawer = blocks.CATEGORIES[0]
        self.palette_rows = []       # (row, rect) off the drawer
        self.cat_rects = []          # (category, rect) down the side
        self.buttons = {}            # action -> rect, the toolbar
        self.place = {}              # pid -> the node's rects, ports, words
        self.pos = {}                # pid -> where the node sits on the board
        self.auto = set()            # pids `layout` placed, not the player
        self.wires = []              # (from pid, port, to pid, port)
        self.ports = []              # (block, port, centre) for the hit tests
        self.node = None             # the node a drag is carrying
        self.wire = None             # a wire being drawn out of a pin
        self.canvas = pygame.Rect(0, 0, 0, 0)
        self.drawer_rect = pygame.Rect(0, 0, 0, 0)
        self.tool_rect = pygame.Rect(0, 0, 0, 0)
        self.canvas_bar = pygame.Rect(0, 0, 0, 0)
        self.hbar = pygame.Rect(0, 0, 0, 0)   # the bottom (horizontal) strip
        self.canvas_h = 0
        self.canvas_w = 0
        self.drawer_scroll = 0
        self.drawer_max = 0            # how far the palette column can scroll
        self.hover_kind = None       # palette row under the mouse
        self.hover_row = None        # ...and all of it, for the doc strip
        self.baseline = ""           # the text the file holds right now
        self.selected = None         # pid of the block the player last touched
        self.drag = None             # a block in flight; see `_mouse_move`
        self.snap = None             # the node a carried block would land on
        self.editing = None          # {"pid", "slot", "text", "caret"}
        self.problems = {}           # pid -> why its words do not parse
        self.file_error = None       # why the whole file will not compile
        self.err_line = 0            # the line the compiler pointed at
        self.err_rect = pygame.Rect(0, 0, 0, 0)   # the strip under the nodes
        self.menu = None             # {"pid", "rect"} for the open context menu
        self.menu_rows = []          # (action, label, rect)
        self.picks = None            # the asset list under a slot being typed
        self.history = []            # rendered text, newest last
        self.future = []
        self.dirty = False
        self._press = None           # where a click went down, for hit tests
        self._pan = None             # a middle-drag panning the board both ways
        self._scaled = {}            # text images at the current zoom
        self._metrics()

    def use_fonts(self, fonts):
        """Keep the metrics honest when the editor font changes size."""
        self.fonts = fonts
        self._metrics()

    def _metrics(self):
        fonts = getattr(self, "fonts", None) or self.app.fonts or {}
        self.font = fonts.get("normal")
        self.small = fonts.get("small")
        self.mono = fonts.get("mono")
        self.bold = fonts.get("bold") or self.font
        # board text shrinks with zoom; drawer and toolbar stay chrome
        self._scaled = {}
        tall = self.font or self.small
        unit = (tall.get_height() + 12 if tall else BAR_H) * 10 // 9
        self.bar_h = unit
        self.edit_h = (self.font.get_height() + 6) if self.font else 20
        self.text_h = max(4, int(round(self.edit_h * self.zoom)))
        self.row_h = max(3, int(round(((self.small.get_height() if self.small
                                       else 12) + 4) * self.zoom)))
        self.pill_h = self.text_h + self.scale(4)
        self.head_h = max(5, self.text_h + self.scale(12))   # title bar
        self.param_h = max(5, self.text_h + self.scale(7))   # one value row
        self.pin_r = max(2, self.scale(4))

    def scale(self, value):
        """A layout number at the current zoom."""
        return int(round(value * self.zoom))

    def _text(self, font, text, colour):
        """Words at this zoom: the cached render, scaled."""
        img = widgets.cached_text(font, text, colour)
        if img is None or self.zoom >= 0.995:
            return img
        key = (id(img), img.get_width(), img.get_height())
        got = self._scaled.get(key)
        if got is None:
            wide = max(1, int(round(img.get_width() * self.zoom)))
            tall = max(1, int(round(img.get_height() * self.zoom)))
            got = pygame.transform.smoothscale(img, (wide, tall))
            if len(self._scaled) > 4000:
                self._scaled.clear()
            self._scaled[key] = got
        return got

    def set_project(self, project):
        """A different project means a different file: start clean."""
        self.close()

    def close(self):
        self.path = None
        self.module = blocks.Module()
        self.baseline = ""
        self.dirty = False
        self.history.clear()
        self.future.clear()
        self.selected = None
        self.editing = None
        self.drag = None
        self.snap = None
        self.menu = None
        self.menu_rows = []
        self.picks = None
        self.problems.clear()
        self.file_error = None
        self.err_line = 0
        self.place.clear()
        self.pos.clear()
        self.auto.clear()
        self.wires.clear()
        self.ports.clear()
        self.node = None
        self.wire = None
        self.palette_rows.clear()
        self.cat_rects.clear()
        self.buttons.clear()
        self.scroll = 0
        self.hscroll = 0

    def open(self, path, text=None):
        """Read a file as blocks; odd files stay read-only."""
        p = str(path)
        if not p:
            return False
        if text is None:
            code = self.app.code
            if code is not None and code.path == p and code.dirty:
                text = code.text
            else:
                try:
                    text = open(p, encoding="utf-8",
                                errors="replace").read()
                except OSError as exc:
                    self.app.log(f"cannot open {p}: {exc}", "error")
                    return False
        # re-reading a file must not reset the drawer's scroll
        same = self.path == p and self.module is not None
        self.path = p
        self.module = blocks.parse(text)
        self.baseline = self.module.render()
        self.dirty = False
        self.history.clear()
        self.future.clear()
        self.problems.clear()
        self.selected = None
        self.editing = None
        self.drag = None
        self.snap = None
        self.menu = None
        self.menu_rows = []
        self.picks = None
        self.file_error = None
        self.err_line = 0
        self.scroll = 0
        self.hscroll = 0
        self.drawer_scroll = 0
        if not same:
            self._open_drawer()
        self._load_layout()
        # Load .block file for layout if it exists
        self._load_block_file()
        if self.module.readonly:
            self.app.log(f"blocks: view only - {self.module.readonly}", "warn")
        return True

    def _load_block_file(self):
        """Load block layout from {scriptname}.block file."""
        if not self.path:
            return
        block_path = Path(self.path).with_suffix(".block")
        if block_path.exists():
            try:
                import json
                data = json.loads(block_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "layout" in data:
                    # Restore node positions from .block file
                    for pid, pos in data["layout"].items():
                        self.pos[pid] = tuple(pos)
            except Exception:
                pass  # Ignore corrupt .block files

    def _save_block_file(self):
        """Save block layout to {scriptname}.block file."""
        if not self.path:
            return
        block_path = Path(self.path).with_suffix(".block")
        # Only save layout for blocks that were manually placed
        layout = {}
        for pid, pos in self.pos.items():
            if pid not in self.auto:
                layout[pid] = [int(pos[0]), int(pos[1])]
        if layout:
            import json
            data = {"layout": layout}
            try:
                block_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
            except OSError:
                pass

    def sync(self, force=False):
        """Follow the file the rest of the editor has open."""
        want = self.app.code.path
        if not want:
            if self.path:
                self.close()
            return False
        if want != self.path or force:
            return self.open(want)
        if self.app.code.dirty and not self.dirty:
            # words were typed in Text since this view was filled
            return self.open(want, text=self.app.code.text)
        return True

    def text(self):
        """What the file would look like on disk right now."""
        return self.module.render()

    def save(self):
        """Write blocks back as Python, then show Text."""
        if self.module.readonly:
            self.app.log("blocks: nothing to save, the file cannot be read",
                         "warn")
            return False
        if not self.path:
            return False
        if self.errors():
            for pid, why in self.errors():
                self.app.log(f"blocks: {why}", "warn")
            return self._write(strict=False)
        return self._write(strict=True)

    def _write(self, strict):
        try:
            text = self.module.render(strict=strict)
        except ValueError as exc:
            self.app.log(f"blocks: {exc}", "error")
            return False
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            self.app.log(f"blocks: save failed: {exc}", "error")
            return False
        self.baseline = text
        # an unparsed slot is still unsaved work
        self.dirty = bool(self.problems)
        # Save block layout
        self._save_block_file()
        code = self.app.code
        code.parked.pop(str(self.path), None)
        if code.path == str(self.path):
            code.open(self.path)         # both views now read the same file
        self.app.log(f"saved {self.app.relative(self.path)}", "ok")
        return True

    def reload(self):
        """Throw the blocks away and read the file again."""
        if self.path:
            return self.open(self.path)
        return False

    def revert(self):
        """Back to the words on disk: blocks become branches."""
        return self.reload()

    def errors(self):
        """[(pid, why)] for slots that do not parse."""
        return self.module.errors

    def push(self):
        """Remember the file as it is, before a change lands."""
        self.history.append(self.module.render())
        if len(self.history) > 80:
            self.history.pop(0)
        self.future.clear()
        self.dirty = True

    def undo(self):
        if not self.history:
            self.app.status = "blocks: nothing to undo"
            return False
        self.future.append(self.module.render())
        self._install(self.history.pop())
        self.app.status = "blocks: undone"
        return True

    def redo(self):
        if not self.future:
            self.app.status = "blocks: nothing to redo"
            return False
        self.history.append(self.module.render())
        self._install(self.future.pop())
        self.app.status = "blocks: redone"
        return True

    def _install(self, text):
        """Restore a remembered file, keeping the view."""
        keep = {block.pid: block for block in self.module.all()}
        places = {key: self.pos[pid] for pid, key in self._keys().items()
                  if pid in self.pos and pid not in self.auto}
        self.module = blocks.parse(text)
        self.problems.clear()
        for block in self.module.all():
            if keep.get(block.pid) is not None:
                self.selected = block.pid
                break
        # undo re-reads: restore places by tree path
        self.pos = {pid: places[key] for pid, key in self._keys().items()
                    if key in places}
        self.auto = set()
        self._refresh()

    def readonly(self):
        return bool(self.module.readonly)

    def kind(self):
        """The open file's kind: scene, object or script."""
        return blocks.file_kind(self.module)

    def kind_label(self):
        """The file kind as toolbar and hint words."""
        return blocks.KINDS.get(self.kind(), "script")

    def summary(self):
        counts = self.module.counts()
        return f"{sum(counts.values())} blocks"

    def _open_drawer(self):
        """Open the drawer this kind of file is made from."""
        kind = self.kind()
        want = DRAWER_FOR.get(kind, "data")
        if not blocks.palette(want, kind):
            for name in blocks.CATEGORIES:
                if blocks.palette(name, kind):
                    want = name
                    break
        self.drawer = want
        self.drawer_scroll = 0

    def info(self):
        rows = [("File", self.path or "no file open"),
                ("Kind", self.kind_label()),
                ("View", "read only" if self.readonly() else "blocks"),
                ("Blocks", self.summary()),
                ("Raw", f"{self.count_kind('raw')} block(s) of plain code"),
                ("Zoom", f"{int(self.zoom * 100)}%"),
                ("Changed", "yes" if self.dirty else "no")]
        if self.selected is not None:
            block = self.module.find(self.selected)
            if block is not None:
                rows += [("-", ""),
                         ("Kind", block.kind),
                         ("Says", block.label()[:70]),
                         ("Python", block.statement().strip()[:70]),
                         ("Drawer", block.spec.category),
                         ("Slots", ", ".join(name for name, _p
                                             in block.spec.slots) or "none")]
        if self.problems:
            rows += [("Broken", f"{len(self.problems)} slot(s)")]
        return rows

    def count_kind(self, kind):
        return sum(1 for block in self.module.all() if block.kind == kind)

    def _friendly(self, name):
        """A slot's name as its row words."""
        return SLOT_NAMES.get(name, str(name).replace("_", " "))

    def _title(self, block):
        """A node's title bar words: the short name."""
        return block.spec.title(block.fields)

    def layout(self):
        """Measure each node, place it and note the wires."""
        self.place = {}
        self.wires = []
        self.ports = []
        self._forget_gone()
        ox = self.canvas.x - self.hscroll
        oy = self.canvas.y - self.scroll
        top = self.scale(26)
        gap = self.scale(NODE_GAP)
        entries = []
        wide_at = {}                    # depth -> the widest node in it
        for block in self.module.all():
            entry = self._measure(block)
            depth = block.depth()
            wide_at[depth] = max(wide_at.get(depth, 0), entry["size"][0])
            entries.append((block, depth, entry))
        # one column per level, offset by the widest card
        left = {}
        x = self.scale(24)
        for depth in range(max(wide_at) + 1 if wide_at else 0):
            left[depth] = x
            x += wide_at.get(depth, 0) + gap
        cursors = {}                    # depth -> the y the next node takes
        for block, depth, entry in entries:
            pos = self.pos.get(block.pid)
            if pos is None:
                # a column's first node starts level with its owner block
                y = cursors.get(depth)
                if y is None:
                    holder = block.parent
                    y = self.pos.get(holder.pid, (0, top))[1] \
                        if isinstance(holder, blocks.Block) else top
                pos = (left[depth], y)
                self.pos[block.pid] = pos
                # automatic places are zoom-specific; hand places stay
                self.auto.add(block.pid)
            cursors[depth] = max(cursors.get(depth, top),
                                 pos[1] + entry["size"][1] + gap)
            self._place(block, ox + pos[0], oy + pos[1], entry)
            self.place[block.pid] = entry
        self._wire_up()
        right = self.canvas.x + self.scale(60)
        bottom = self.canvas.y + self.scale(60)
        for entry in self.place.values():
            box = entry["full"]
            right = max(right, box.right + self.hscroll)
            bottom = max(bottom, box.bottom + self.scroll)
        self.canvas_w = int(right - self.canvas.x + self.scale(30))
        self.canvas_h = int(bottom - self.canvas.y + self.scale(60))

    def _forget_gone(self):
        """Drop the places of nodes the file no longer holds."""
        live = {block.pid for block in self.module.all()}
        for pid in [pid for pid in self.pos if pid not in live]:
            self.pos.pop(pid, None)
        self.auto &= live

    def _keys(self, module=None):
        """A name per block that survives a re-read."""
        module = module or self.module
        out = {}

        def walk(stack, prefix):
            for index, block in enumerate(stack):
                key = f"{prefix}{index}"
                out[block.pid] = key
                for name in block.body_names():
                    walk(block.stack(name), f"{key}.{name}.")

        walk(module.blocks, "")
        return out

    def _save_layout(self):
        """Remember node places per file, for this session."""
        if not self.path:
            return
        keys = self._keys()
        # only player-chosen places persist; automatic ones are re-measured
        self._layouts[str(self.path)] = {
            keys[pid]: tuple(pos) for pid, pos in self.pos.items()
            if pid in keys and pid not in self.auto}

    def _load_layout(self):
        """Restore where the nodes sat last time."""
        self.pos = {}
        self.auto = set()
        saved = self._layouts.get(str(self.path)) or {}
        if not saved:
            return
        for pid, key in self._keys().items():
            if key in saved:
                self.pos[pid] = tuple(saved[key])

    def _board_origin(self):
        """Where the board's own space starts on screen."""
        return (self.canvas.x - self.hscroll, self.canvas.y - self.scroll)

    def tidy(self):
        """Forget every hand-placed node: back to the automatic board."""
        self.pos = {}
        self.auto = set()
        if self.path:
            self._layouts.pop(str(self.path), None)
        self.app.status = "blocks: the board is tidy again"
        return True

    def _free_spot(self, block, spot):
        """The nearest free board place to `spot`."""
        wide, tall = self._measure(block)["size"]
        ox, oy = self._board_origin()
        x, y = int(spot[0]), int(spot[1])
        gap = self.scale(NODE_GAP)
        for _step in range(64):
            box = pygame.Rect(x + ox, y + oy, wide, tall)
            under = [entry["rect"] for entry in self.place.values()
                     if entry["rect"].colliderect(box)]
            if not under:
                break
            y = max(other.bottom for other in under) + gap - oy
        return (x, y)

    def _wire_up(self):
        """The exec wires, read straight off the tree."""
        def chain(stack):
            for before, after in zip(stack, stack[1:]):
                self.wires.append((before.pid, "out", after.pid, "in"))

        chain(self.module.blocks)
        for block in self.module.all():
            for name in block.body_names():
                stack = block.stack(name)
                if not stack:
                    continue
                self.wires.append((block.pid, "body:" + name,
                                   stack[0].pid, "in"))
                chain(stack)

    def _measure(self, block):
        """A node's size and words, before placement."""
        pad = self.scale(NODE_PAD)
        air = self.scale(8)
        room = self.scale(PIN_ROOM)
        entry = {"block": block, "title": self._title(block),
                 "slots": {}, "words": {}, "rows": {}, "rowrects": {},
                 "bodyrects": {}, "bodies": [], "ports": {}, "notes": [],
                 "lines": [], "raw": block.kind in ("raw", "note")}
        for line in block.pre:
            if line.strip():
                entry["notes"].append(line)
        if entry["raw"]:
            lines = [line.rstrip() or " " for line in str(
                block.fields.get("code", "")).split("\n")]
            font = self.mono or self.font
            wide = self.scale(220)
            if font and lines:
                # longest line at this zoom, so code cards shrink
                longest = max(font.size(line)[0] for line in lines)
                wide = min(int(round(longest * self.zoom)),
                           self.scale(RAW_MAX))
            entry["lines"] = lines
            # the card holds title bar and code together
            entry["size"] = (int(max(wide + self.scale(26),
                                      self.scale(170))),
                             int(self.head_h + self.text_h * len(lines)
                                 + self.scale(12)))
            return entry
        widest = 0
        names_w = 0
        values_w = 0
        for kind, payload in block.spec.holes():
            if kind != "hole":
                continue
            shown = str(block.fields.get(payload) or "").strip()
            text = shown or block.spec.placeholder(payload)
            value_w = max(self.scale(PILL_MIN),
                          min(self.scale(VALUE_MAX),
                              self._width(text) + self.scale(2 * PILL_PAD)))
            name_w = self._width(self._friendly(payload))
            entry["rowrects"][payload] = (name_w, value_w)
            entry["words"][payload] = (text, bool(shown))
            names_w = max(names_w, name_w)
            values_w = max(values_w, value_w)
        if entry["rowrects"]:
            # one field column keeps rows aligned and wide enough
            widest = names_w + air + values_w
        for name, lead, _mode in block.spec.bodies:
            if name == "handlers" and block.kind != "try":
                continue
            label = lead or name
            entry["bodies"].append((name, label))
            widest = max(widest, self._width(label) + self.scale(18))
        title_w = self._width(entry["title"])
        wide = max(title_w, widest) + pad * 2 + room * 2
        tall = self.head_h + len(entry["rowrects"]) * self.param_h
        tall += len(entry["bodies"]) * self.param_h
        tall += len(entry["notes"]) * self.row_h
        entry["size"] = (int(max(wide, self.scale(160))), int(tall))
        return entry

    def _place(self, block, x, y, entry):
        """Give a measured node its rects: rows, fields, pins."""
        x, y = int(x), int(y)
        y += len(entry["notes"]) * self.row_h
        w, h = entry["size"]
        pad = self.scale(NODE_PAD)
        room = self.scale(PIN_ROOM)
        rect = pygame.Rect(x, y, w, h)
        entry["rect"] = entry["full"] = rect
        entry["head"] = pygame.Rect(x, y, w, self.head_h)
        # wires run down the gutter, top edge to bottom
        self._port(block, entry, "in", x + self.scale(GUTTER), y)
        self._port(block, entry, "out", x + self.scale(GUTTER), y + h)
        cursor = y + self.head_h
        if entry["raw"]:
            entry["slots"]["code"] = pygame.Rect(
                x + self.scale(6), cursor, w - self.scale(12),
                entry["size"][1] - (cursor - y) - self.scale(6))
            return
        widest = max([name_w for name_w, _v in entry["rowrects"].values()]
                     or [0])
        left = x + pad + room + widest + self.scale(10)
        field_w = max(self.scale(PILL_MIN), x + w - pad - left)
        for name, (_name_w, _value_w) in entry["rowrects"].items():
            entry["rows"][name] = pygame.Rect(x, cursor, w, self.param_h)
            entry["slots"][name] = pygame.Rect(
                left, cursor + self.scale(3), field_w,
                self.param_h - self.scale(6))
            cursor += self.param_h
        for name, _label in entry["bodies"]:
            row = pygame.Rect(x, cursor, w, self.param_h)
            entry["bodyrects"][name] = row
            self._port(block, entry, "body:" + name, x + w, row.centery)
            cursor += self.param_h

    def _port(self, block, entry, name, x, y):
        """Note a pin in the entry and the hit list."""
        entry["ports"][name] = (int(x), int(y))
        self.ports.append((block, name, (int(x), int(y))))

    def _width(self, text):
        """How wide words are in the block font."""
        text = str(text)
        if not text:
            return 0
        font = self.bold or self.font or self.small
        if font is None:
            return max(1, int(len(text) * 7 * self.zoom))
        return max(1, int(round(font.size(text)[0] * self.zoom)))

    def can_drop(self, parent, slot):
        """Whether this stack takes blocks at all."""
        if slot == "handlers":
            return isinstance(parent, blocks.Block) and parent.kind == "try"
        return not self.readonly()

    def accepts(self, block, parent, slot):
        """Whether this block may land in this stack."""
        if self.readonly():
            return False
        if block.kind == "except":
            return isinstance(parent, blocks.Block) and \
                parent.kind == "try" and slot == "handlers"
        if slot == "handlers":
            return block.kind == "except"
        if block.shape is blocks.HAT:
            # an event hook sits top level, never inside a statement
            return parent is None or (isinstance(parent, blocks.Block)
                                      and parent.kind == "class")
        if isinstance(parent, blocks.Block) and \
                parent.find(block.pid) is not None:
            return False                # a block cannot hold itself
        return True

    def _hook_row(self, name, args, when, category):
        """One engine hook as a drawer row: a hat, nothing above it."""
        return {"kind": "def", "category": category,
                "fields": {"name": name, "args": args},
                "label": f"when {name} is called",
                "doc": f"The engine calls {name}({args}) {when}. Nothing "
                       f"you write runs above it."}

    def _has_hook(self, name):
        """Whether this file already defines one engine hook."""
        return any(block.kind == "def" and block.fields.get("name") == name
                   for block in self.module.all())

    def _broadcast_rows(self, kind):
        """A hat per trigger the project binds, then one for all of them."""
        if self._has_hook("on_trigger"):
            return []               # the file already owns the one hook
        if not blocks.fits(blocks.spec("broadcast"), kind):
            return []
        project = getattr(self.app, "project", None)
        names = inputmap.load(project).names(trigger=True)
        hook = f"on_trigger({TRIGGER_ARGS})"
        out = []
        for name in list(names) + [None]:
            if name is None:
                label = "when any trigger is broadcast"
                doc = f"The engine calls {hook} for every trigger this " \
                      f"scene broadcasts."
            else:
                label = f"when {name} is broadcast"
                doc = f"The engine calls {hook}, so pick the name inside: " \
                      f"if name == '{name}'."
            out.append({"kind": "def", "category": "trigger",
                        "fields": {"name": "on_trigger",
                                   "args": TRIGGER_ARGS},
                        "label": label, "doc": doc})
        return out

    def _rows(self):
        """What the open drawer offers this file."""
        kind = self.kind()
        if self.drawer == "events":
            return [self._hook_row(name, args, when, "events")
                    for name, args, when, kinds in HOOK_ROWS
                    if kind in kinds]
        if self.drawer == "trigger":
            return ([self._hook_row(name, args, when, "trigger")
                     for name, args, when, kinds in TRIGGER_ROWS
                     if kind in kinds]
                    + self._broadcast_rows(kind)
                    + blocks.palette("trigger", kind))
        return blocks.palette(self.drawer, kind)

    def draw(self, surface, rect, dt=None):
        """Fill `rect` with the file as blocks."""
        # toolbar and drawer are chrome; size ignores zoom
        tool_h = TOOL_H
        self.tool_rect = pygame.Rect(rect.x, rect.y, rect.width, tool_h)
        self.drawer_rect = pygame.Rect(rect.x, rect.y + tool_h, DRAWER_W,
                                       max(0, rect.height - tool_h))
        self.canvas = pygame.Rect(
            self.drawer_rect.right + 1, self.drawer_rect.y,
            max(0, rect.right - self.drawer_rect.right - 1),
            self.drawer_rect.height)
        self.canvas_bar = pygame.Rect(
            self.canvas.right - 15, self.canvas.y + 2,
            13, max(0, self.canvas.height - 4))
        self.hbar = pygame.Rect(
            self.canvas.x + 2, self.canvas.bottom - 15,
            max(0, self.canvas.width - 17), 13)
        surface.fill(xp.PANEL, rect)
        self.sync()                     # follow whatever file is current
        self.layout()
        self._clamp_scroll()
        self._draw_tool(surface)
        self._draw_canvas(surface)
        self._draw_drawer(surface)
        if self.drag is not None:
            self._draw_ghost(surface)
        self._draw_menu(surface)
        self._draw_picks(surface)

    def _draw_picks(self, surface):
        """The asset list for the slot being typed."""
        if self.picks is None:
            return
        self.picks.draw(surface, self.font or self.small)

    def _draw_tool(self, surface):
        """The button strip, with the file's name and state."""
        bar = self.tool_rect
        font = self.font or self.small
        pygame.draw.rect(surface, xp.FACE, bar)
        pygame.draw.line(surface, xp.SHADOW, (bar.x, bar.bottom - 1),
                         (bar.right - 1, bar.bottom - 1))
        mouse = pygame.mouse.get_pos()
        self.buttons = {}
        x = bar.x + 4
        for key, label in TOOL_BUTTONS:
            if label is None:
                x += 6
                continue
            if key == "fit":
                label = f"{int(self.zoom * 100)}%"
            wide = ((font.size(label)[0] if font else 40) + 18)
            rect = pygame.Rect(x, bar.y + 3, wide, max(14, bar.height - 7))
            self.buttons[key] = rect
            live = self._enabled(key)
            xp.button(surface, rect, label, font or self.small,
                      hovered=live and rect.collidepoint(mouse),
                      default=key == "save", enabled=live)
            x = rect.right + 4
        if not self.path:
            return
        note = self.summary()
        colour = xp.TEXT_MUTED
        if self.problems:
            note += f" - {len(self.problems)} block(s) not valid yet"
            colour = xp.LOG_WARN
        elif self.file_error:
            note += f" - {self.file_error}"
            colour = xp.LOG_ERROR
        elif self.readonly():
            note = "view only"
            colour = xp.LOG_WARN
        name = str(self.path).replace("\\", "/").rsplit("/", 1)[-1]
        if self.dirty:
            name += " *"
        # name and state line split the bar, both clipped
        left = x + 6
        # a chip names the file kind before the state line
        left = self._draw_kind(surface, left)
        room = max(0, bar.right - 10 - left)
        name_w = min(room // 2 if room > 120 else room,
                     (font.size(name)[0] if font else 40))
        name_img = widgets.cached_text(
            font, widgets.elide(font, name, name_w), xp.LINK)
        if name_img is not None:
            name_x = bar.right - name_img.get_width() - 10
            surface.blit(name_img, (name_x,
                                    bar.centery - name_img.get_height() // 2))
            room = max(0, name_x - left - 8)
        img = widgets.cached_text(self.small or font,
                                  widgets.elide(self.small or font, note, room),
                                  colour)
        if img is not None and room > 0:
            surface.blit(img, (left, bar.centery - img.get_height() // 2))

    def _draw_kind(self, surface, left):
        """The file-kind chip, drawn from `left`; returns where it ends."""
        label = self.kind_label()
        font = self.small or self.font
        bar = self.tool_rect
        # the name holds the right end; the chip stops short
        limit = bar.right - 90
        wide = (font.size(label)[0] if font else 40) + 12
        if left + 18 > limit:
            return left
        chip = pygame.Rect(left, bar.y + 4, min(wide, limit - left),
                           max(12, bar.height - 9))
        xp.button(surface, chip,
                  widgets.elide(font, label, chip.width - 10), font,
                  enabled=False)
        return chip.right + 8

    def _enabled(self, key):
        """Whether a toolbar button has something to do right now."""
        if key in ("undo",):
            return bool(self.history)
        if key in ("redo",):
            return bool(self.future)
        if key == "save":
            return self.dirty and not self.readonly()
        return self.path is not None

    def _draw_canvas(self, surface):
        rect = self.canvas
        if rect.width <= 0 or rect.height <= 0:
            return
        pygame.draw.rect(surface, CANVAS_BG, rect)
        old = surface.get_clip()
        surface.set_clip(rect)
        self._draw_grid(surface, rect)
        self._draw_wires(surface)
        for block in self.module.all():
            self._draw_block(surface, block)
        if self.drag is not None:
            self._draw_drop_hint(surface)
        if self.node is not None:
            self._draw_body_hint(surface)
        self._draw_wire_drag(surface)
        self._draw_editor(surface)
        if not self.path:
            self._draw_hint(surface, "open a .py in the Project View to see "
                                     "it as blocks")
        elif not self.module.blocks:
            self._draw_hint(surface, f"an empty {self.kind_label().lower()} "
                                     f"- drag a block out of the drawer")
        self._draw_errors(surface)
        surface.set_clip(old)
        pygame.draw.rect(surface, CANVAS_DOT, rect, 1)
        if self.canvas_h > rect.height:
            xp.scrollbar(surface, self.canvas_bar,
                         self.scroll / max(1, self.canvas_h - rect.height),
                         rect.height / max(1, self.canvas_h))
        if self.canvas_w > rect.width:
            xp.scrollbar(surface, self.hbar,
                         self.hscroll / max(1, self.canvas_w - rect.width),
                         rect.width / max(1, self.canvas_w), vertical=False)

    def _draw_grid(self, surface, rect):
        """A faint dot lattice that scrolls with the file."""
        step = max(18, self.scale(DOT_STEP))
        top = rect.y - (self.scroll % step) + step // 2
        for gy in range(top, rect.bottom, step):
            for gx in range(rect.x + step // 2, rect.right, step):
                pygame.draw.rect(surface, CANVAS_DOT, (gx, gy, 2, 2))

    def _draw_hint(self, surface, text):
        font = self.small or self.font
        img = widgets.cached_text(
            font, widgets.elide(font, text, self.canvas.width - 40),
            xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (self.canvas.x + 18,
                               self.canvas.y + 14))

    def _draw_wires(self, surface):
        """Every exec wire: shadowed line under the nodes."""
        for from_pid, port, to_pid, to_port in self.wires:
            start = self._port_of(from_pid, port)
            end = self._port_of(to_pid, to_port)
            if start is None or end is None:
                continue
            if not self._near(start, end):
                continue
            self._curve(surface, start, end, WIRE_DARK, self.scale(4))
            self._curve(surface, start, end, PIN, self.scale(2))

    def _port_of(self, pid, name):
        """Where a pin sits now, or None."""
        entry = self.place.get(pid)
        if entry is None:
            return None
        return entry["ports"].get(name)

    def _near(self, a, b):
        """Whether a wire between two pins could be visible."""
        box = pygame.Rect(min(a[0], b[0]), min(a[1], b[1]),
                          abs(a[0] - b[0]) + 1, abs(a[1] - b[1]) + 1)
        return self.canvas.colliderect(box.inflate(max(48, self.scale(90)),
                                                  max(24, self.scale(20))))

    def _curve(self, surface, a, b, colour, width):
        """One wire: an S leaving each pin along its angle."""
        if abs(b[1] - a[1]) >= abs(b[0] - a[0]):
            reach = max(self.scale(16),
                        min(abs(b[1] - a[1]) * 0.5, self.scale(90)))
            c1 = (a[0], a[1] + reach)
            c2 = (b[0], b[1] - reach)
        else:
            reach = max(self.scale(30),
                        min(abs(b[0] - a[0]) * 0.5, self.scale(130)))
            c1 = (a[0] + reach, a[1])
            c2 = (b[0] - reach, b[1])
        pts = []
        for step in range(13):
            t = step / 12.0
            u = 1.0 - t
            pts.append((int(u * u * u * a[0] + 3 * u * u * t * c1[0] +
                            3 * u * t * t * c2[0] + t * t * t * b[0]),
                        int(u * u * u * a[1] + 3 * u * u * t * c1[1] +
                            3 * u * t * t * c2[1] + t * t * t * b[1])))
        pygame.draw.lines(surface, colour, False, pts, max(1, int(width)))

    def _draw_block(self, surface, block):
        """One node: title bar, value rows and pins."""
        entry = self.place.get(block.pid)
        if entry is None:
            return
        rect = entry["full"]
        if rect.bottom < self.canvas.y or rect.top > self.canvas.bottom or \
                rect.right < self.canvas.x or rect.left > self.canvas.right:
            return                        # out of sight, so out of the paint
        for index, line in enumerate(entry["notes"]):
            img = self._text(self.small or self.font, line, xp.SYN_COMMENT)
            if img is not None:
                lift = (len(entry["notes"]) - index) * self.row_h
                surface.blit(img, (rect.x + self.scale(2), rect.y - lift))
        fill = color_of(block.spec.category)
        edge = tuple(max(0, c - 60) for c in fill[:3])
        radius = self.scale(6)
        shadow = pygame.Surface((rect.width + 8, rect.height + 8),
                                pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 80),
                         shadow.get_rect().inflate(-8, -8),
                         border_radius=radius)
        surface.blit(shadow, (rect.x - 4, rect.y + 3))
        surface.blit(rounded_body(rect.size, radius, NODE_BG, NODE_BG_BOT),
                     rect.topleft)
        pygame.draw.rect(surface, (20, 22, 28), rect, 1, border_radius=radius)
        head = entry["head"]
        surface.blit(rounded_body(head.size, radius,
                                  lighten(fill, 0.12), fill), head.topleft)
        pygame.draw.rect(surface, fill, (head.x, head.y + head.height - radius,
                                        head.width, radius))
        pygame.draw.line(surface, edge, (head.x + radius, head.bottom - 1),
                         (head.right - radius - 1, head.bottom - 1))
        title = self._text(self.bold or self.font, entry["title"],
                           text_on(fill))
        if title is not None:
            surface.blit(title, (head.x + self.scale(PIN_ROOM),
                                head.centery - title.get_height() // 2))
        if entry["raw"]:
            self._draw_raw(surface, entry)
        else:
            self._draw_rows(surface, block, entry)
        for name, point in entry["ports"].items():
            # each pin straddles the node edge, grabbable when alone
            diamond(surface, point[0], point[1], self.pin_r + 1, PIN,
                    (16, 18, 24))
        if block.pid == self.selected:
            pygame.draw.rect(surface, xp.SELECT_BORDER, rect.inflate(6, 6), 2,
                             border_radius=radius + 2)
        if block.pid in self.problems:
            dot = pygame.Rect(head.right - self.scale(15), head.y + 3,
                              self.scale(11), self.scale(11))
            pygame.draw.circle(surface, xp.LOG_ERROR, dot.center,
                               dot.width // 2)
            img = self._text(self.small or self.font, "!", (255, 255, 255))
            if img is not None:
                surface.blit(img, (dot.centerx - img.get_width() // 2,
                                   dot.centery - img.get_height() // 2))

    def _draw_rows(self, surface, block, entry):
        """Value rows and body pins: pin, name, field."""
        small = self.small or self.font
        for name, row in entry["rows"].items():
            text, filled = entry["words"].get(name) or ("", False)
            kind = pin_type(name, text) if filled else "any"
            tone = TYPE_COLORS.get(kind, TYPE_COLORS["any"]) if filled \
                else (118, 124, 136)
            centre = (row.x, row.centery)
            pygame.draw.circle(surface, tone, centre, self.pin_r)
            pygame.draw.circle(surface, (16, 18, 24), centre, self.pin_r, 1)
            img = self._text(small, self._friendly(name),
                             (176, 182, 196))
            if img is not None:
                surface.blit(img, (row.x + self.scale(PIN_ROOM),
                                   row.centery - img.get_height() // 2))
            field = entry["slots"].get(name)
            if field is not None:
                self._field(surface, block, name, field, text, filled)
        for name, label in entry["bodies"]:
            row = entry["bodyrects"].get(name)
            if row is None:
                continue
            taken = bool(block.stack(name))
            img = self._text(small, label,
                             (214, 220, 232) if taken
                             else (132, 138, 150))
            if img is not None:
                surface.blit(img, (row.x + self.scale(PIN_ROOM),
                                   row.centery - img.get_height() // 2))
            if not taken:
                hint = self._text(small, "drop a wire here",
                                  (104, 110, 122))
                if hint is not None:
                    surface.blit(hint, (row.right - hint.get_width() -
                                        self.scale(PIN_ROOM + 8),
                                        row.centery - hint.get_height() // 2))

    def _field(self, surface, block, name, rect, text, filled):
        """One value: a dark field, ringed when invalid."""
        radius = self.scale(4)
        pygame.draw.rect(surface, (25, 28, 35), rect, border_radius=radius)
        pygame.draw.rect(surface, (60, 66, 78) if filled else (46, 50, 60),
                         rect, 1, border_radius=radius)
        font = self.bold or self.font or self.small
        img = self._text(font, text, xp.TEXT if filled
                         else (126, 132, 144))
        if img is not None:
            # a long value clips; clicking opens a wider box
            old = widgets.clip(surface, rect.inflate(-3, -2))
            if old is not None:
                surface.blit(img, (rect.x + self.scale(PILL_PAD),
                                   rect.centery - img.get_height() // 2))
                surface.set_clip(old)
        if name in ("word", "op") and len(block.words(name)) > 1:
            cx = rect.right - self.scale(7)
            pygame.draw.polygon(surface, xp.TEXT_MUTED,
                                [(cx - 3, rect.centery - 2),
                                 (cx + 3, rect.centery - 2),
                                 (cx, rect.centery + 2)])
        if name in self._bad_slots(block):
            pygame.draw.rect(surface, xp.LOG_ERROR, rect.inflate(3, 3), 2,
                             border_radius=radius + 1)

    def _bad_slots(self, block):
        """Which slots to ring: the changed ones, or all."""
        if block.pid not in self.problems:
            return set()
        suspect = {name for name in block.fields
                   if str(block.fields.get(name)) !=
                   str(block.good.get(name))}
        return suspect or set(block.fields)

    def _draw_raw(self, surface, entry):
        """A raw node: its own lines in the mono face."""
        rect = entry["slots"].get("code")
        if rect is None:
            return
        font = self.mono or self.font
        pygame.draw.rect(surface, (24, 27, 33), rect,
                         border_radius=self.scale(4))
        pygame.draw.rect(surface, (52, 57, 68), rect, 1,
                         border_radius=self.scale(4))
        y = rect.y + self.scale(3)
        old = widgets.clip(surface, rect.inflate(-2, 0))
        if old is None:
            return
        for line in entry["lines"]:
            if font is not None:
                img = self._text(font, line, xp.CODE_TEXT)
                if img is not None:
                    surface.blit(img, (rect.x + self.scale(8), y))
            y += self.text_h
        surface.set_clip(old)

    def _draw_errors(self, surface):
        """The red strip: what is not Python, plus a jump."""
        self.err_rect = pygame.Rect(0, 0, 0, 0)
        if not self.problems and not self.file_error:
            return
        font = self.small or self.font
        if self.problems:
            pid = next(iter(self.problems))
            words = (f"{len(self.problems)} slot(s) are not python yet"
                     f"  -  click to jump: {self.problems[pid]}")
        else:
            words = (f"the file does not compile: {self.file_error}"
                     "  -  click to jump")
        wide = (font.size(words)[0] if font else 240) + 16
        lift = 15 if self.canvas_w > self.canvas.width else 0
        rect = pygame.Rect(self.canvas.x + 2,
                           self.canvas.bottom - self.edit_h - 8 - lift,
                           min(max(1, wide), max(1, self.canvas.width - 4)),
                           self.edit_h + 6)
        pygame.draw.rect(surface, xp.FIELD, rect)
        pygame.draw.rect(surface, xp.LOG_ERROR, rect, 1)
        self.err_rect = rect
        img = widgets.cached_text(
            font, widgets.elide(font, words, rect.width - 16), xp.LOG_ERROR)
        if img is not None:
            surface.blit(img, (rect.x + 8,
                               rect.centery - img.get_height() // 2))

    def _draw_menu(self, surface):
        """The context menu, above every other part."""
        if self.menu is None:
            return
        rect = self.menu["rect"]
        font = self.font or self.small
        pygame.draw.rect(surface, xp.FACE, rect)
        pygame.draw.rect(surface, xp.OUTLINE, rect, 1)
        mouse = pygame.mouse.get_pos()
        for _key, label, row in self.menu_rows:
            if row.collidepoint(mouse):
                pygame.draw.rect(surface, xp.SELECTION, row, border_radius=2)
            img = widgets.cached_text(font, label, xp.TEXT)
            if img is not None:
                surface.blit(img, (row.x + 8,
                                   row.centery - img.get_height() // 2))

    def _draw_drop_hint(self, surface):
        """Where a carried block would land, in its colour."""
        target = self.snap
        if target is None:
            img = self._text(self.small or self.font,
                             "drop it on a node, or on the board",
                             xp.LOG_WARN)
            if img is not None:
                mouse = pygame.mouse.get_pos()
                surface.blit(img, (mouse[0] + self.scale(12), mouse[1]))
            return
        entry = self.place.get(target["block"].pid)
        if entry is None:
            return
        box = entry["full"]
        if target.get("slot"):
            row = entry["bodyrects"].get(target["slot"])
            if row is not None:
                box = row
        pygame.draw.rect(surface, color_of(target["block"].spec.category),
                         box.inflate(6, 6), 2, border_radius=self.scale(8))

    def _draw_body_hint(self, surface):
        """The body row a dragged node would slide into."""
        row = self._body_row_at(pygame.mouse.get_pos())
        if row is None:
            return
        node = self.module.find(self.node["pid"])
        if node is None or not self.accepts(node, row[0], row[1]):
            return
        entry = self.place.get(row[0].pid)
        rect = entry["bodyrects"].get(row[1]) if entry else None
        if rect is None:
            return
        pygame.draw.rect(surface, PIN, rect.inflate(4, 2), 2,
                         border_radius=self.scale(4))

    def _draw_wire_drag(self, surface):
        """The wire being drawn and its target node."""
        wire = self.wire
        if wire is None:
            return
        entry = self.place.get(wire["block"].pid)
        start = entry["ports"].get(wire["port"]) if entry else None
        if start is None:
            return
        end = tuple(wire["pos"])
        over = wire.get("over")
        if over is not None:
            target = self.place.get(over.pid)
            if target is not None:
                end = target["ports"].get("in") or target["head"].midleft
                pygame.draw.rect(surface, PIN, target["full"].inflate(6, 6), 2,
                                 border_radius=self.scale(8))
        self._curve(surface, start, end, WIRE_DARK, self.scale(4))
        self._curve(surface, start, end, (255, 214, 120), self.scale(2))

    def _draw_ghost(self, surface):
        """The block being carried, drawn as its node."""
        block = self.drag["block"]
        font = self.bold or self.font or self.small
        title = self._title(block)
        inside = len(block.all()) - 1
        if inside > 0:
            title += f"  (+{inside})"
        tall = self.edit_h + 12
        wide = (font.size(title)[0] if font else 80) + PIN_ROOM * 2
        rect = pygame.Rect(0, 0, wide, tall)
        rect.center = pygame.mouse.get_pos()
        fill = color_of(block.spec.category)
        shadow = pygame.Surface((rect.width + 8, rect.height + 8),
                                pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 90),
                         shadow.get_rect().inflate(-8, -8),
                         border_radius=6)
        surface.blit(shadow, (rect.x - 4, rect.y + 3))
        surface.blit(rounded_body(rect.size, 6,
                                  lighten(fill, 0.12), fill), rect.topleft)
        img = widgets.cached_text(font, title, text_on(fill))
        if img is not None:
            surface.blit(img, (rect.centerx - img.get_width() // 2,
                               rect.centery - img.get_height() // 2))

    def _cat_bands(self):
        """The drawers as the labelled bands of `CATEGORY_GROUPS`, each"""
        out, placed = [], set()
        for title, names in CATEGORY_GROUPS:
            members = [n for n in blocks.CATEGORIES if n in names]
            if members:
                out.append((title, members))
                placed.update(members)
        left = [n for n in blocks.CATEGORIES if n not in placed]
        if left:
            out.append((None, left))
        return out

    def _draw_cat(self, surface, name, row, mouse):
        """One drawer chip: colour bar, short word, hover and selection."""
        small = self.small or self.font
        ink = xp.TEXT
        if row.collidepoint(mouse):
            xp.gradient_v(surface, row, xp.TAB_HOVER_TOP, xp.TAB_HOVER_BOT)
        if name == self.drawer:
            pygame.draw.rect(surface, xp.SELECTION, row, border_radius=2)
            ink = xp.SELECT_TEXT
        pygame.draw.rect(surface, color_of(name),
                         pygame.Rect(row.x + 3, row.y + 3, CAT_W,
                                     row.height - 6), border_radius=2)
        img = widgets.cached_text(small,
                                  CATEGORY_TITLES.get(name, name.title()),
                                  ink)
        room = row.width - CAT_W - 7
        if img is not None and 0 < room < img.get_width():
            img = pygame.transform.smoothscale(img, (room,
                                                     img.get_height()))
        if img is not None:
            surface.blit(img, (row.x + CAT_W + 5,
                               row.centery - img.get_height() // 2))

    def _draw_drawer(self, surface):
        """The palette: categories, then the blocks of the open one."""
        rect = self.drawer_rect
        if rect.width <= 0 or rect.height <= 0:
            return
        font = self.font or self.small
        small = self.small or font
        pygame.draw.rect(surface, xp.FACE, rect)
        xp.sunken(surface, rect)
        old = surface.get_clip()
        surface.set_clip(rect)
        mouse = pygame.mouse.get_pos()
        self.hover_kind = None
        self.hover_row = None
        # drawers sit in labelled bands, two chips to a row
        cols = 2
        gap = 2
        wide = (rect.width - gap * 3) // cols
        tall = 18
        top = rect.y + 3 - self.drawer_scroll
        self.cat_rects = []
        y = top
        for title, members in self._cat_bands():
            if title:
                img = widgets.cached_text(small, title, xp.TEXT_MUTED)
                if img is not None:
                    surface.blit(img, (rect.x + gap + 2, y))
                y += 14
            for index, name in enumerate(members):
                cx = rect.x + gap + (index % cols) * (wide + gap)
                row = pygame.Rect(cx, y + (index // cols) * (tall + 1),
                                  wide, tall)
                self.cat_rects.append((name, row))
                self._draw_cat(surface, name, row, mouse)
            y += ((len(members) + cols - 1) // cols) * (tall + 1) + 4
        y += 2
        self.palette_rows = []
        for info in self._rows():
            kind = info["kind"]
            row = pygame.Rect(rect.x + 6, y,
                              rect.width - 10,
                              self.edit_h + 8)
            self.palette_rows.append((info, row))
            fill = color_of(info["category"])
            pygame.draw.rect(surface, fill, row, border_radius=4)
            pygame.draw.rect(surface, tuple(max(0, c - 55) for c in fill[:3]),
                             row, 1, border_radius=4)
            label = info["label"].replace("%", "")
            img = widgets.cached_text(small, label, text_on(fill))
            if img is not None:
                if img.get_width() > row.width - 10:
                    img = pygame.transform.smoothscale(
                        img, (row.width - 10, img.get_height()))
                surface.blit(img, (row.x + 6,
                                   row.centery - img.get_height() // 2))
            if row.collidepoint(mouse):
                self.hover_kind = kind
                self.hover_row = info
            y += row.height + 5
        self.drawer_max = max(0, y + self.drawer_scroll - rect.bottom)
        if not self.palette_rows:
            # an empty drawer says so rather than looking broken
            note = widgets.elide(small, f"nothing here for a "
                                        f"{self.kind_label().lower()}",
                                 rect.width - 16)
            img = widgets.cached_text(small, note, xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (rect.x + 8, y))
        self._draw_doc(surface, rect)
        surface.set_clip(old)

    def _draw_doc(self, surface, rect):
        """What the block under the mouse does, in the strip."""
        info = self.hover_row
        if info is None or not info.get("doc"):
            return
        font = self.small or self.font
        box = pygame.Rect(rect.x + 3, rect.bottom - 70,
                          rect.width - 6, 67)
        xp.field(surface, box, xp.FIELD_ALT)
        y = box.y + 3
        for line in widgets.wrap(font, info["doc"], box.width - 10)[:4]:
            img = widgets.cached_text(font, line, xp.TEXT)
            if img is None:
                continue
            surface.blit(img, (box.x + 5, y))
            y += img.get_height() + 1

    def _draw_editor(self, surface):
        """The slot being typed, drawn over its pill."""
        edit = self.editing
        if edit is None:
            return
        entry = self.place.get(edit["pid"])
        if entry is None:
            self.editing = None
            return
        font = self.mono if edit["multiline"] else (self.font or self.small)
        text = str(edit["text"])
        lines = text.split("\n") if edit["multiline"] else [text]
        slot = entry["slots"].get(edit["slot"]) or entry["head"]
        # the slot editor opens at its own size
        wide = max(slot.width, 140)
        if font is not None:
            wide = max(wide, font.size(max(lines, key=len))[0] + 12)
        tall = self.edit_h * len(lines)
        box = pygame.Rect(slot.x, slot.y,
                          min(wide, max(1, self.canvas.width - 8)), tall)
        xp.field(surface, box)
        pygame.draw.rect(surface, xp.SELECT_BORDER, box, 1)
        y = box.y
        row, col = 0, max(0, min(edit["caret"], len(text)))
        for index, line in enumerate(lines):
            if col <= len(line):
                row, col = index, col
                break
            col -= len(line) + 1
        for line in lines:
            img = widgets.cached_text(font, line, xp.TEXT)
            if img is not None:
                surface.blit(img, (box.x + 5,
                                   y + (self.edit_h - img.get_height()) // 2))
            y += self.edit_h
        if (time.time() * 2) % 1 < 0.6:
            x = box.x + 5 + (font.size(lines[row][:col])[0] if font
                             else col * 7)
            pygame.draw.line(surface, xp.CARET, (x, box.y + 2),
                             (x, box.y + self.edit_h - 2))

    def handle_event(self, e):
        """One event; True when the block view used it."""
        if self.path is None:
            return False
        if self.menu is not None:
            return self._menu_event(e)
        if self.editing is not None and e.type in (
                pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL):
            return self._edit_event(e)
        if e.type == pygame.MOUSEBUTTONDOWN:
            return self._mouse_down(e.pos, e.button)
        if e.type == pygame.MOUSEMOTION:
            return self._mouse_move(e.pos)
        if e.type == pygame.MOUSEBUTTONUP:
            return self._mouse_up(e.pos, e.button)
        if e.type == pygame.MOUSEWHEEL:
            return self._wheel(e)
        if e.type == pygame.KEYDOWN:
            return self._key(e)
        return False

    def _mouse_down(self, pos, button):
        if button == 3:
            return self._right_down(pos)
        if button == 2:
            # the middle button grabs and pans the board
            if self.canvas.collidepoint(pos):
                self._pan = {"pos": pos, "scroll": self.scroll,
                             "hscroll": self.hscroll}
                return True
            return False
        if button != 1:
            return False
        for key, rect in self.buttons.items():
            if rect.collidepoint(pos):
                self._tool(key)
                return True
        if self.drag is not None:
            self.drag = None                  # a second click puts it back
            self.snap = None
            self.app.status = "blocks: drag cancelled"
            return True
        if self.err_rect.width and self.err_rect.collidepoint(pos):
            self.next_problem()
            return True
        if self.canvas_bar.collidepoint(pos) and self.canvas_h > \
                self.canvas.height:
            self._jump(pos[1])
            return True
        if self.hbar.collidepoint(pos) and self.canvas_w > self.canvas.width:
            self._hjump(pos[0])
            return True
        if self.drawer_rect.collidepoint(pos):
            return self._drawer_down(pos)
        if self.canvas.collidepoint(pos):
            return self._canvas_down(pos)
        return False

    def _drawer_down(self, pos):
        for name, rect in self.cat_rects:
            if rect.collidepoint(pos):
                if name != self.drawer:
                    self.drawer = name
                    self.drawer_scroll = 0
                    self.app.status = f"blocks: {name} blocks"
                return True
        for info, rect in self.palette_rows:
            if rect.collidepoint(pos):
                if self.readonly():
                    self.app.status = "blocks: this file is view only"
                    return True
                fresh = blocks.new_block(info["kind"], info.get("fields"))
                self.drag = {"block": fresh, "from": "drawer"}
                self.snap = None
                self.app.status = (f"blocks: carrying a {info['kind']} block "
                                   f"- drop it on a node or on the board")
                return True
        return True

    def _canvas_down(self, pos):
        block, name = self._hit_slot(pos)
        if block is not None:
            self.selected = block.pid
            if name in ("word", "op") and len(block.words(name)) > 1:
                self._cycle(block, name)      # a choice slot is clicked round
            elif self.readonly():
                self.app.status = "blocks: view only - edit it as Text"
            else:
                self._begin_edit(block, name)
            return True
        block, port = self._hit_port(pos)
        if block is not None:
            self.selected = block.pid
            if self.readonly():
                self.app.status = "blocks: view only - edit it as Text"
                return True
            self.wire = {"block": block, "port": port, "pos": pos,
                         "over": None}
            self.app.status = ("blocks: drop the wire on the node that "
                               "should run after this one")
            return True
        found = self._hit_block(pos)
        if found is None:
            self.selected = None
            return True
        self.selected = found.pid
        entry = self.place.get(found.pid) or {}
        head = entry.get("head")
        if not self.readonly() and head is not None and head.collidepoint(pos):
            self._press = {"pid": found.pid, "pos": pos,
                           "offset": (pos[0] - head.x, pos[1] - head.y)}
        return True

    def _mouse_move(self, pos):
        if self._pan is not None:
            # the board follows the mouse when dragged
            ox, oy = self._pan["pos"]
            self.scroll = self._pan["scroll"] - (pos[1] - oy)
            self.hscroll = self._pan["hscroll"] - (pos[0] - ox)
            self._clamp_scroll()
            return True
        if self.wire is not None:
            self.wire["pos"] = pos
            over = self._hit_block(pos)
            self.wire["over"] = None if over is self.wire["block"] else over
            return True
        if self.drag is not None:
            self.snap = self._drop_at(pos)
            return True
        if self.node is not None:
            self._move_node(pos)
            return True
        if self._press is not None:
            start = self._press["pos"]
            if abs(pos[0] - start[0]) + abs(pos[1] - start[1]) < \
                    self.scale(DRAG_AFTER):
                return True
            block = self.module.find(self._press["pid"])
            self._press_done()
            if block is None:
                return True
            self._move_node(pos)
            self.app.status = f"blocks: moving the {block.kind} node"
            return True
        return False

    def _press_done(self):
        """A press turned into drag: keep the offset."""
        press, self._press = self._press, None
        if press is not None:
            self.node = {"pid": press["pid"],
                         "offset": press["offset"]}

    def _move_node(self, pos):
        """Put the dragged node under the mouse."""
        node = self.node
        if node is None:
            return
        ox, oy = self._board_origin()
        offset = node.get("offset") or (0, 0)
        self.pos[node["pid"]] = (int(pos[0] - ox - offset[0]),
                                  int(pos[1] - oy - offset[1]))
        self.auto.discard(node["pid"])      # this is the player's place now

    def _mouse_up(self, pos, button):
        if button == 2:
            self._pan = None
            return True
        if button != 1:
            return False
        if self.wire is not None:
            self._connect()
            self.wire = None
            return True
        if self.node is not None:
            self._settle_node(pos)
            return True
        if self.drag is not None:
            self._drop(self.drag, self._drop_at(pos), pos)
            self.drag = None
            self.snap = None
            self._press = None
            return True
        self._press = None
        return self.selected is not None

    def _connect(self):
        """Plug a wire in, ordering the source before the target."""
        wire = self.wire
        source = wire["block"]
        target = wire.get("over")
        if target is None or target is source:
            self.app.status = "blocks: the wire went nowhere"
            return False
        port = wire["port"]
        if port.startswith("body:"):
            slot = port[5:]
            if not self.accepts(target, source, slot):
                self.app.status = (f"blocks: a {target.kind} block does not "
                                   f"go in there")
                return False
            self._apply(lambda: self.module.move(target, source, slot, None))
        else:
            slot = source.slot
            if not self.accepts(target, source.parent, slot):
                self.app.status = (f"blocks: a {target.kind} block does not "
                                   f"run there")
                return False
            index = source.index()
            self._apply(lambda: self.module.move(
                target, source.parent, slot,
                (index + 1) if index >= 0 else None))
        self.selected = target.pid
        self._save_layout()
        self.app.log(f"blocks: the {target.kind} block plugs in after the "
                     f"{source.kind}", "ok")
        return True

    def _settle_node(self, pos):
        """Let go: the node stays or joins a body."""
        node, self.node = self.node, None
        self._press = None
        block = self.module.find(node["pid"])
        if block is None:
            return
        stored = self._layouts.get(str(self.path)) or {}
        key = self._keys().get(block.pid)
        if key is not None and block.pid in self.pos:
            stored[key] = tuple(self.pos[block.pid])
        self._layouts[str(self.path)] = stored
        row = self._body_row_at(pos)
        if row is not None and row[0] is not block and \
                self.accepts(block, row[0], row[1]):
            self._apply(lambda: self.module.move(block, row[0], row[1], None))
            self.app.log(f"blocks: the {block.kind} block moved into "
                         f"{row[1]}", "ok")
            return
        self.app.status = f"blocks: the {block.kind} node moved"

    def _wheel(self, e):
        mouse = pygame.mouse.get_pos()
        if pygame.key.get_mods() & pygame.KMOD_CTRL:
            return self.set_zoom(self.zoom * (1.15 if e.y > 0
                                              else 1 / 1.15))
        if self.drawer_rect.collidepoint(mouse):
            step = self.edit_h + 6
            self.drawer_scroll = max(0, min(self.drawer_max,
                                            self.drawer_scroll - e.y * step))
            return True
        if self.canvas.collidepoint(mouse):
            # a plain notch scrolls; sideways or shift pans across
            dx = getattr(e, "x", 0)
            if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                dx, dy = e.y, 0
            else:
                dy = e.y
            if dx:
                self.hscroll -= dx * self.scale(SCROLL_STEP)
            if dy:
                self.scroll -= dy * self.scale(SCROLL_STEP)
            if dx or dy:
                self._clamp_scroll()
            return True
        return False

    def _key(self, e):
        ctrl = bool(e.mod & pygame.KMOD_CTRL)
        if e.key == pygame.K_ESCAPE:
            if self.wire is not None:
                self.wire = None
                self.app.status = "blocks: the wire was let go"
                return True
            if self.node is not None:
                self.node = None
                self.app.status = "blocks: the node stays put"
                return True
            if self.drag is not None:
                self.drag = None
                self.snap = None
                self.app.status = "blocks: put it back"
                return True
            if self.selected is not None:
                self.selected = None
                return True
            return False
        if ctrl and e.key == pygame.K_z:
            return self.undo()
        if ctrl and e.key == pygame.K_y:
            return self.redo()
        if e.key in (pygame.K_DELETE, pygame.K_BACKSPACE) and \
                self.selected is not None:
            return self._remove_selected()
        if e.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            return self.set_zoom(self.zoom * 1.15)
        if e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            return self.set_zoom(self.zoom / 1.15)
        if e.key == pygame.K_0:
            return self.set_zoom(1.0)
        return False

    def _remove_selected(self):
        block = self.module.find(self.selected)
        if block is None or self.readonly():
            return True
        kind = block.kind
        self._apply(lambda: self.module.remove(block))
        self.selected = None
        self.app.status = f"blocks: took out the {kind} block"
        return True

    def _tool(self, key):
        """A toolbar button."""
        if key == "text":
            self.app.show_code()
        elif key == "reload":
            if self.reload():
                self.app.log("blocks: re-read from the file", "ok")
        elif key == "undo":
            self.undo()
        elif key == "redo":
            self.redo()
        elif key == "tidy":
            self.tidy()
        elif key == "save":
            self.save()
        elif key == "in":
            self.set_zoom(self.zoom * 1.15)
        elif key == "out":
            self.set_zoom(self.zoom / 1.15)
        elif key == "fit":
            self.fit_board()

    def _right_down(self, pos):
        """A right click asks the block under the mouse."""
        self._close_menu()
        if self.editing is not None or not self.canvas.collidepoint(pos):
            return False
        block = self._hit_block(pos)
        if block is None:
            return False
        self.selected = block.pid
        rows = []
        if block.pid in self.problems:
            rows.append(("fix", "Undo the words typed into it"))
        elif not self.readonly():
            if block.kind == "raw":
                rows.append(("unraw", "Turn it back into blocks"))
            else:
                rows.append(("raw", "Collapse it to plain code"))
                rows.append(("dup", "Duplicate it"))
                rows.append(("out", "Take it out"))
        rows.append(("text", "Edit it as Text"))
        font = self.font or self.small
        # the menu is chrome: its size ignores the board's zoom
        wide = 200
        if font:
            wide = max(wide, max(font.size(label)[0] for _k, label in rows)
                       + 26)
        tall = self.edit_h + 6
        x = max(self.canvas.x + 2,
                min(pos[0], self.canvas.right - wide - 4))
        y = max(self.canvas.y + 2,
                min(pos[1], self.canvas.bottom - tall * len(rows) - 2))
        panel = pygame.Rect(x, y, wide, tall * len(rows) + 8)
        self.menu = {"pid": block.pid, "rect": panel}
        ry = panel.y + 4
        for key, label in rows:
            self.menu_rows.append((key, label,
                                   pygame.Rect(panel.x + 2, ry,
                                               panel.width - 4, tall)))
            ry += tall
        self.app.status = f"blocks: the {block.kind} block menu"
        return True

    def _close_menu(self):
        self.menu = None
        self.menu_rows = []

    def _menu_event(self, e):
        """An open menu takes the next click; elsewhere closes."""
        if e.type == pygame.MOUSEBUTTONDOWN:
            for key, _label, rect in self.menu_rows:
                if rect.collidepoint(e.pos):
                    pid = self.menu["pid"]
                    self._close_menu()
                    self._menu_action(key, pid)
                    return True
            self._close_menu()
            return True
        if e.type == pygame.MOUSEBUTTONUP:
            return True                     # the release of the same click
        if e.type == pygame.KEYDOWN:
            self._close_menu()
            return True
        if e.type == pygame.MOUSEWHEEL:
            self._close_menu()
            return self._wheel(e)
        return False

    def _menu_action(self, key, pid):
        block = self.module.find(pid)
        if block is None:
            return
        if key == "text":
            self.app.show_code()
            return
        if self.readonly():
            self.app.status = "blocks: view only - edit it as Text"
            return
        if key == "fix":
            self._apply(lambda: self.module.revert(block))
            self.app.status = "blocks: the words typed into it are gone"
        elif key == "dup":
            self._duplicate(block)
        elif key == "out":
            kind = block.kind
            self._apply(lambda: self.module.remove(block))
            self.selected = None
            self.app.status = f"blocks: took out the {kind} block"
        elif key == "raw":
            code = blocks.block_source(block, self.module.unit)
            self._apply(lambda: self.module.replace(block, "raw",
                                                    {"code": code}))
            self.app.status = "blocks: plain code now - click it to type"
        elif key == "unraw":
            self._unraw(block)

    def _duplicate(self, block):
        """A copy of the block and everything it wraps."""

        def clone(source):
            fresh = blocks.new_block(source.kind, dict(source.fields))
            for name, stack in source.bodies.items():
                if stack:
                    fresh.attach([clone(child) for child in stack], name)
            return fresh

        twin = clone(block)
        parent, slot = block.parent, block.slot
        if isinstance(parent, blocks.Block):
            index = block.index() + 1
        else:
            parent, slot = None, "body"
            index = (self.module.blocks.index(block) + 1
                     if block in self.module.blocks else None)
        # the copy lands just below the original
        here = self.pos.get(block.pid)
        if here is not None:
            self.pos[twin.pid] = self._free_spot(
                twin, (here[0], here[1] + self.scale(NODE_GAP)))
            self.auto.discard(twin.pid)
        self._apply(lambda: self.module.insert(twin, parent, slot, index))
        self._save_layout()
        self.selected = twin.pid
        self._reveal(twin.pid)
        self.app.status = f"blocks: a copy of the {block.kind} block"

    def _unraw(self, block):
        """Plain code back into blocks for one statement."""
        tree = blocks.parse(_dedent(str(block.fields.get("code") or "")))
        if len(tree.blocks) != 1 or tree.blocks[0].kind == "raw" or tree.errors:
            self.app.status = "blocks: that code is not one known block"
            return
        fresh = tree.blocks[0]
        parent, slot = block.parent, block.slot
        if isinstance(parent, blocks.Block):
            index = block.index()
        else:
            parent, slot = None, "body"
            index = self.module.blocks.index(block) \
                if block in self.module.blocks else None

        def swap():
            block.remove()
            self.module.insert(fresh, parent, slot, index)
        self._apply(swap)
        self.selected = fresh.pid
        self.app.status = f"blocks: it is a {fresh.kind} block again"

    def next_problem(self):
        """Reveal the next block with a slot that fails."""
        pids = list(self.problems)
        if pids:
            try:
                step = pids.index(self.selected) + 1
            except ValueError:
                step = 0
            pid = pids[step % len(pids)]
            self.selected = pid
            self.scroll_to(pid)
            self.app.status = f"blocks: {self.problems[pid]}"
            self.app.log(f"blocks: {self.problems[pid]}", "warn")
            return True
        if self.file_error:
            block = self._block_at_line(self.err_line)
            if block is not None:
                self.selected = block.pid
                self.scroll_to(block.pid)
            self.app.status = f"blocks: {self.file_error}"
            return True
        return False

    def _block_at_line(self, line):
        best = None
        for entry in self.module.all():
            if entry.lineno and entry.lineno <= line and \
                    (best is None or entry.lineno >= best.lineno):
                best = entry
        return best

    def _hit_slot(self, pos):
        """(block, slot) whose value field is under the point."""
        for entry in reversed(list(self.place.values())):
            for name, rect in entry["slots"].items():
                if rect.collidepoint(pos):
                    return entry["block"], name
        return None, None

    def _hit_port(self, pos):
        """(block, port) a wire can leave from, under the point."""
        reach = max(self.scale(10), self.pin_r * 2 + 4)
        best = None
        for block, name, point in reversed(self.ports):
            if name == "in":
                continue
            dx = pos[0] - point[0]
            dy = pos[1] - point[1]
            if dx * dx + dy * dy > reach * reach:
                continue
            if best is None or abs(dx) + abs(dy) < best[0]:
                best = (abs(dx) + abs(dy), block, name)
        if best is None:
            return None, None
        return best[1], best[2]

    def _hit_block(self, pos):
        """The node under the point; the smallest wins."""
        found = None
        for entry in self.place.values():
            box = entry["full"]
            if not box.collidepoint(pos):
                continue
            if found is None or box.width * box.height < \
                    found[0].width * found[0].height:
                found = (box, entry["block"])
        return found[1] if found else None

    def _body_row_at(self, pos):
        """(block, body) for the body row under the point."""
        for entry in reversed(list(self.place.values())):
            for name, row in entry["bodyrects"].items():
                if row.collidepoint(pos):
                    return entry["block"], name
        return None

    def _drop_at(self, pos):
        """What a carried block lands on: body row, node."""
        row = self._body_row_at(pos)
        if row is not None:
            return {"block": row[0], "slot": row[1]}
        found = self._hit_block(pos)
        if found is None:
            return None
        return {"block": found}

    def _before(self, block):
        """Where a block goes to run just before this one."""
        if isinstance(block.parent, blocks.Block):
            return block.parent, block.slot, block.index()
        if block in self.module.blocks:
            return None, "body", self.module.blocks.index(block)
        return None, "body", None

    def _drop(self, drag, target, pos):
        """Put a drawer block where the player let go."""
        block = drag["block"]
        parent = slot = None
        index = None
        if target is not None:
            parent = target["block"]
            slot = target.get("slot")
            if slot is None:
                parent, slot, index = self._before(parent)
        if not self.accepts(block, parent, slot):
            self.app.log(f"blocks: a {block.kind} block does not go there",
                         "warn")
            self.app.status = f"blocks: a {block.kind} does not go there"
            return False
        ox, oy = self._board_origin()
        gap = self.scale(NODE_GAP)
        spot = (int(pos[0] - ox), int(pos[1] - oy))
        if parent is not None and target is not None and target.get("slot"):
            # a new body block lands level with the parent
            entry = self.place.get(parent.pid)
            row = entry["bodyrects"].get(slot) if entry else None
            if row is not None:
                spot = (entry["rect"].right - ox + gap, row.centery - oy)
        self.pos[block.pid] = self._free_spot(block, spot)
        self.auto.discard(block.pid)
        self._apply(lambda: self.module.insert(block, parent, slot, index))
        self.selected = block.pid
        self._save_layout()
        self._reveal(block.pid)
        self.app.log(f"blocks: placed a {block.kind} block", "ok")
        self.app.status = f"blocks: {block.kind} placed - Ctrl+S to write it"
        return True

    def _begin_edit(self, block, name):
        text = str(block.fields.get(name) or "")
        self.editing = {"pid": block.pid, "slot": name, "text": text,
                        "caret": len(text), "multiline": name == "code"}
        self.picks = self._open_picks(block, name)
        if self.picks is not None:
            self.app.status = (f"blocks: {name} - pick one, or type it; "
                               f"Enter keeps it")
            return
        self.app.status = ("blocks: Ctrl+Enter keeps the code, Esc drops it"
                           if self.editing["multiline"] else
                           "blocks: Enter keeps it, Esc drops it")

    def _open_picks(self, block, name):
        """The names a slot can be filled with."""
        row = api.slot_picks(block.kind, name)
        if not row or self.editing.get("multiline"):
            return None
        entry = self.place.get(block.pid) or {}
        anchor = entry.get("slots", {}).get(name) or entry.get("head")
        if anchor is None or not self.canvas.width:
            return None
        words = api.options(row, getattr(self.app, "project", None))
        if not words:
            return None
        return widgets.Choices(words, anchor, self.canvas).filter("")

    def _slot_quoted(self, block, name):
        """Whether the engine reads this row as a string."""
        entry = api.by_kind(block.kind) if block is not None else None
        return entry is not None and name in entry.quoted

    def _pick_word(self, word):
        """Put the picked name in, keeping the block."""
        edit = self.editing
        self.picks = None
        if edit is None or word is None:
            return False
        block = self.module.find(edit["pid"])
        if block is None:
            self.editing = None
            return False
        if not self._slot_quoted(block, edit["slot"]):
            word = f'"{word}"'
        edit["text"] = word
        edit["caret"] = len(word)
        self.app.status = f"blocks: {edit['slot']} is now {word}"
        self._commit_edit()
        return True

    def _picks_event(self, e):
        """The asset list takes row clicks and arrows."""
        picks = self.picks
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if picks.holds(e.pos):
                word = picks.click(e.pos)
                if word is None:
                    return True       # the panel's own air: nothing to do
                return self._pick_word(word)
            self.picks = None             # typing it by hand is still allowed
            return None
        if e.type != pygame.KEYDOWN or self.editing["multiline"]:
            return None
        if e.key in (pygame.K_UP, pygame.K_DOWN):
            picks.step(-1 if e.key == pygame.K_UP else 1)
            word = picks.current()
            if word:
                self.app.status = f"blocks: {word}"
            return True
        if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
            if picks.current() is None:
                return None           # nothing matches: keep the typed words
            return self._pick_word(picks.current())
        if e.key == pygame.K_ESCAPE:
            self.picks = None      # the panel goes; the slot stays open
            return True
        return None

    def _edit_event(self, e):
        """Keys while a slot is open; words stay unkept."""
        edit = self.editing
        if self.picks is not None:
            got = self._picks_event(e)
            if got is not None:
                return got
        if e.type == pygame.MOUSEWHEEL:
            self.picks = None             # the board moves under the panel
            return self._wheel(e)
        if e.type == pygame.MOUSEBUTTONDOWN:
            self._commit_edit()
            return True
        if e.type != pygame.KEYDOWN:
            return False
        ctrl = bool(e.mod & pygame.KMOD_CTRL)
        key = e.key
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if edit["multiline"] and not ctrl:
                self._type("\n")
            else:
                self._commit_edit()
            return True
        if key == pygame.K_ESCAPE:
            self.editing = None
            self.picks = None
            self.app.status = "blocks: the words were not kept"
            return True
        if key == pygame.K_TAB:
            self._commit_edit()
            return True
        if key == pygame.K_BACKSPACE:
            i = edit["caret"]
            if i > 0:
                edit["text"] = edit["text"][:i - 1] + edit["text"][i:]
                edit["caret"] = i - 1
            return True
        if key == pygame.K_DELETE:
            i = edit["caret"]
            edit["text"] = edit["text"][:i] + edit["text"][i + 1:]
            return True
        if key == pygame.K_LEFT:
            edit["caret"] = max(0, edit["caret"] - 1)
            return True
        if key == pygame.K_RIGHT:
            edit["caret"] = min(len(edit["text"]), edit["caret"] + 1)
            return True
        if key == pygame.K_HOME:
            edit["caret"] = 0
            return True
        if key == pygame.K_END:
            edit["caret"] = len(edit["text"])
            return True
        if key in (pygame.K_UP, pygame.K_DOWN) and edit["multiline"]:
            self._move_line(-1 if key == pygame.K_UP else 1)
            return True
        if e.unicode and e.unicode.isprintable() and \
                len(edit["text"]) < MAX_TYPE:
            self._type(e.unicode)
        return True

    def _type(self, words):
        edit = self.editing
        i = edit["caret"]
        edit["text"] = edit["text"][:i] + words + edit["text"][i:]
        edit["caret"] = i + len(words)
        if self.picks is not None:
            # the list follows the letters: forty sheets answer to three
            self.picks.filter(edit["text"])

    def _move_line(self, step):
        edit = self.editing
        lines = str(edit["text"]).split("\n")
        row, col = 0, edit["caret"]
        for index, line in enumerate(lines):
            if col <= len(line):
                row, col = index, col
                break
            col -= len(line) + 1
        row = max(0, min(len(lines) - 1, row + step))
        col = min(col, len(lines[row]))
        edit["caret"] = sum(len(line) + 1 for line in lines[:row]) + col

    def _commit_edit(self):
        edit, self.editing = self.editing, None
        self.picks = None
        if edit is None:
            return True
        block = self.module.find(edit["pid"])
        text = edit["text"]
        if block is None:
            return True
        if text == str(block.fields.get(edit["slot"]) or ""):
            return True                 # nothing was typed, nothing to do
        name = edit["slot"]

        def write():
            why = block.set_field(name, text)
            if why:
                self.app.log(f"blocks: {why} - the block keeps the last "
                             f"words that made sense", "warn")
                self.app.status = f"blocks: {why}"
        self._apply(write)
        return True

    def _cycle(self, block, name):
        """Click a keyword or operator slot to step choices."""
        choices = block.words(name)
        if len(choices) < 2:
            return False
        now = str(block.fields.get(name) or "")
        try:
            nxt = choices[(choices.index(now) + 1) % len(choices)]
        except ValueError:
            nxt = choices[0]
        self._apply(lambda: block.set_field(name, nxt))
        self.app.status = f"blocks: {name} is now {nxt}"
        return True

    def _apply(self, action):
        """Run a change behind an undo step."""
        before = self.module.render()
        self.push()
        action()
        if self.module.render() == before:
            self.history.pop()
        self._refresh()
        return self.module.render() != before

    def _refresh(self):
        """Re-mark broken slots and compile the file."""
        self.problems = dict(self.module.errors)
        self.file_error = None
        self.err_line = 0
        if self.path and not self.module.readonly:
            # a block can parse and still break the file
            try:
                compile(self.module.render(), str(self.path), "exec")
            except SyntaxError as exc:
                self.file_error = exc.msg or "this is not python yet"
                self.err_line = exc.lineno or 0
            except (ValueError, RecursionError, MemoryError) as exc:
                self.file_error = str(exc)
        self.dirty = bool(self.path) and self.module.render() != self.baseline

    def set_zoom(self, value):
        """Zoom the canvas, keeping the metrics and the layout honest."""
        value = max(MIN_ZOOM, min(MAX_ZOOM, float(value)))
        if abs(value - self.zoom) < 0.001:
            return False
        self.zoom = value
        self._metrics()
        # automatic columns are zoom-measured, so a new zoom re-measures
        for pid in self.auto:
            self.pos.pop(pid, None)
        self.auto.clear()
        self.app.status = f"blocks: {int(self.zoom * 100)}%"
        return True

    def fit_board(self):
        """Zoom out to the whole board, then its corner."""
        self.set_zoom(1.0)
        self.scroll = 0
        self.hscroll = 0
        if not self.canvas.width or not self.canvas.height:
            return False
        # text rounds to pixels, so a few passes settle it
        for _step in range(4):
            self.layout()
            room = min(self.canvas.width / max(1, self.canvas_w),
                       self.canvas.height / max(1, self.canvas_h))
            if room >= 1.0:
                break
            if not self.set_zoom(self.zoom * room * 0.99):
                break
        self.scroll = 0
        self.hscroll = 0
        self.app.status = f"blocks: the whole board at {int(self.zoom * 100)}%"
        return True

    def _clamp_scroll(self):
        """Keep the canvas inside the file on both axes."""
        limit = max(0, self.canvas_h - self.canvas.height)
        self.scroll = max(0, min(limit, self.scroll))
        wlimit = max(0, self.canvas_w - self.canvas.width)
        self.hscroll = max(0, min(wlimit, self.hscroll))

    def _jump(self, y):
        """A scroll-strip click goes to that part."""
        span = max(1, self.canvas_bar.height)
        frac = max(0.0, min(1.0, (y - self.canvas_bar.y) / span))
        self.scroll = int(frac * max(0, self.canvas_h - self.canvas.height))

    def _hjump(self, x):
        """A bottom-strip click pans across to that part."""
        span = max(1, self.hbar.width)
        frac = max(0.0, min(1.0, (x - self.hbar.x) / span))
        self.hscroll = int(frac * max(0, self.canvas_w - self.canvas.width))
        self._clamp_scroll()

    def scroll_to(self, pid):
        """Bring a block into view, from outline or search."""
        entry = self.place.get(pid)
        if entry is None:
            return False
        box = entry.get("full") or entry["head"]
        if box.top < self.canvas.y + self.scale(8):
            self.scroll -= self.canvas.y + self.scale(8) - box.top
        elif box.bottom > self.canvas.bottom - self.scale(8):
            self.scroll += box.bottom - (self.canvas.bottom - self.scale(8))
        if box.left < self.canvas.x + self.scale(8):
            self.hscroll -= self.canvas.x + self.scale(8) - box.left
        elif box.right > self.canvas.right - self.scale(8):
            self.hscroll += box.right - (self.canvas.right - self.scale(8))
        self._clamp_scroll()
        return True

    def _reveal(self, pid):
        """Lay the board out, then scroll to a new node."""
        self.layout()
        return self.scroll_to(pid)
