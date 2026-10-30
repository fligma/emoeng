"""The engine's calls, one block field per parameter."""

import ast
import inspect
import re
from pathlib import Path

from emoeng.engine import audio as audiomod
from emoeng.engine import colors as colorsmod
from emoeng.engine import components as compmod
from emoeng.engine import game as gamemod
from emoeng.engine import input as inputmod
from emoeng.engine import inputmap as inputmapmod
from emoeng.engine import model as modelmod
from emoeng.engine import objects as objmod
from emoeng.engine import proctex as proctexmod
from emoeng.engine import renderer as rendermod
from emoeng.engine import save as savemod
from emoeng.engine import scene as scenemod
from emoeng.engine import shaders as shadermod
from emoeng.engine import templates as templatemod
from emoeng.engine import ui as uimod


# classes a signature reads: one per written name
OWNERS = {
    "Scene": scenemod.Scene,
    "Scene3D": scenemod.Scene3D,
    "Scene2D": scenemod.Scene2D,
    "SceneUI": scenemod.SceneUI,
    "Hud": scenemod.Hud,
    "GameObject": objmod.GameObject,
    "Object3D": objmod.Object3D,
    "Object2D": objmod.Object2D,
    "Entity3D": objmod.Entity3D,
    "Entity2D": objmod.Entity2D,
    "UIObject": objmod.UIObject,
    "Audio": audiomod.Audio,
    "Input": inputmod.Input,
    "SaveStore": savemod.SaveStore,
    "Game": gamemod.Game,
    "Text3D": compmod.Text3D,
    "Text2D": compmod.Text2D,
    "AudioEmitter3D": compmod.AudioEmitter3D,
    "AudioEmitter2D": compmod.AudioEmitter2D,
    "Timer3D": compmod.Timer3D,
    "Timer2D": compmod.Timer2D,
    "Particle3D": compmod.Particle3D,
    "Particle2D": compmod.Particle2D,
    # what `frag(self, g)` is handed: the drawer's blocks
    "Builder": shadermod.Builder,
}

# placeholders show examples; they are read like code
WORDS = {
    "pos": "(0.0, 0.0, 0.0)", "color": "(1.0, 1.0, 1.0)",
    "text": "ready", "key": "pickup", "label": "pick up", "scene": "menu",
    "model": "crate", "obj": "spark", "expr": "mesh", "amount": "0.6",
    "rect": "(12, 12, 200, 40)", "pairs": '[("wasd", "move")]',
    "lines": "it begins", "shape": "point", "light": "torch",
    "who": "self.player", "camera": "main", "dir": "(0.4, 0.8, 0.3)",
    "level": "1.0", "texture": "stone", "name": "main",
    "map": "hall",
    "size": "(180.0, 44.0)", "action": "None", "tag": "prop",
    "yaw": "0.0", "scale": "1.0", "tint": "None", "fade": "0.35",
    "freq": "None", "duration": "0.35", "roll": "None", "damping": "None",
    "offset": "None", "blend": "opaque",
    "grid": "(1, 1)", "font_size": "18", "align": "left", "alpha": "255",
    "border": "None", "centre": "None", "bottom": "None", "dim": "None",
    "loops": "0", "kind": "sine", "volume": "0.4", "decay": "True",
    "ms": "180.0", "hz": "440.0", "to": "880.0", "smooth": "0.5",
    "seed": "1", "energy": "None", "hour": "None", "flicker": "0.2",
    "pulse": "None", "radius": "None", "angle": "None", "inner": "None",
    "follow": "False", "path": "theme.ogg", "fade_ms": "500",
    "loop": "True", "sound": "ui_click",
    # an entity's own rows: health, behaviour, the tree, signals
    "health": "100.0", "ai_type": "follow", "config": "{}",
    "target": "self.player", "team": "enemy", "distance": "15.0",
    "range": "2.0", "damage": "15.0", "cooldown": "1.5",
    "walk": "3.0", "run": "8.0", "half": "(0.5, 1.0, 0.5)",
    "hitshape": "box", "extent": "(32.0, 48.0)", "height": "None",
    "deaggro": "None", "child": "Door", "signal": "door", "fn": "on_door",
    # a shader's rows: `g` call words plus the look name
    "uv": "g.uv", "a": "g.color", "b": "g.color", "t": "0.5",
    "x": "g.grey(g.color)", "h": "g.time", "lo": "0.0", "hi": "1.0",
    "scale": "1.0", "direction": "(1.0, 0.0)", "speed": "1.0",
    "shader": "scanlines", "knob": "amount", "value": "0.5",
    # an emitter's rows: how many points, and which knob
    "count": "12",
}

# a new block holds valid code for every required row
START = {
    "pos": "(0.0, 0.0, 0.0)", "color": "(1.0, 1.0, 1.0)",
    "text": '"ready"', "key": '"pickup"', "label": '"pick up"',
    "scene": '"menu"', "model": '"crate"', "obj": '"spark"', "expr": "mesh",
    "amount": "0.6", "rect": "(12, 12, 200, 40)",
    "pairs": '[("wasd", "move")]', "lines": '"it begins"',
    "shape": "point", "light": '"torch"', "who": "self.player",
    "camera": '"main"', "dir": "(0.4, 0.8, 0.3)", "level": "1.0",
    "texture": '"stone"', "name": '"main"', "size": "(180.0, 44.0)",
    "map": '"hall"',
    "action": "None", "target": "self.player", "s": '"ready"',
    "path": '"theme.ogg"', "sound": '"ui_click"',
    # dropping a block leaves the line compiled
    "uv": "g.uv", "a": "g.color", "b": "g.color", "t": "0.5",
    "x": "g.grey(g.color)", "h": "g.time",
    "direction": "(1.0, 0.0)", "shader": '"scanlines"',
    "knob": '"amount"', "value": "0.5", "count": "12",
    # an entity's own rows, quoted where the engine wants words
    "health": "100.0", "ai_type": '"follow"', "config": "{}",
    "team": '"enemy"', "distance": "15.0", "range": "2.0",
    "damage": "15.0", "cooldown": "1.5", "walk": "3.0", "run": "8.0",
    "half": "(0.5, 1.0, 0.5)", "hitshape": '"box"',
    "extent": "(32.0, 48.0)", "child": '"Door"', "signal": '"door"',
    "fn": "self.on_door",
}


def _src(node):
    """A call argument as source text, ready for a row."""
    try:
        text = ast.unparse(node)
    except Exception:               # a half-built node must not lose a file
        return ""
    # unparse uses ', so double-quote only lines with no quotes
    if '"' not in text and "\\" not in text and text.count("'") % 2 == 0:
        text = text.replace("'", '"')
    return text


class Param:
    """One block row: engine name, row name, its words."""

    __slots__ = ("arg", "slot", "words", "required", "keyword", "picks")

    def __init__(self, arg, slot=None, words="", required=False, keyword=False,
                 picks=None):
        self.arg = arg                  # the name in the rendered call
        self.slot = slot or arg         # the name the block's row shows
        self.words = words              # what an empty row displays
        self.required = required        # fills a seat with no default
        self.keyword = keyword          # only ever passed by name
        # a row with no asset gets None, meaning no list
        self.picks = tuple(picks or ())

    def __repr__(self):
        return f"<Param {self.arg} as {self.slot}>"


# the calls an entity is told, the tree it stands in and the signals it hears
_ENTITY_CALLS = ("self.set_health", "self.set_max_health", "self.set_ai",
                 "self.set_ai_target", "self.set_team",
                 "self.set_aggro_range", "self.set_attack",
                 "self.set_move_speed", "self.set_hitbox",
                 "self.set_hitbox2d")
_TREE_CALLS = ("self.get_node", "self.queue_free")
_SIGNAL_CALLS = ("self.connect", "self.disconnect", "self.emit")


def _category(target):
    """Which drawer a call hangs in, from its expression."""
    if target.startswith("self.hud."):
        return "ui"
    if target.startswith("self.audio."):
        return "audio"
    if target in _ENTITY_CALLS:
        return "entity"
    if target in _TREE_CALLS:
        return "object"
    if target in _SIGNAL_CALLS:
        return "trigger"
    if target in ("self.add_light", "self.add_preset", "self.remove_light",
                  "self.light"):
        return "light"
    if target in ("self.spawn", "self.place_model", "self.model_object",
                  "self.add", "self.dynamic", "self.despawn"):
        return "object"
    return "scene"


def _signature(owner):
    """[(name, required, default, keyword_only)] from the engine itself."""
    head, _, name = str(owner).rpartition(".")
    cls = OWNERS.get(head)
    fn = getattr(cls, name, None) if cls is not None else None
    if fn is None:
        return ()
    try:
        found = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return ()
    out = []
    for p in found:
        if p.name in ("self", "cls"):
            continue
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            break
        default = None if p.default is p.empty else p.default
        out.append((p.name, p.default is p.empty, default,
                    p.kind is p.KEYWORD_ONLY))
    return tuple(out)


class Call:
    """One engine call a drawer offers and its field rules."""

    __slots__ = ("kind", "label", "category", "target", "owner", "params",
                 "head", "fixed", "node", "doc", "kinds", "quoted", "seeds",
                 "by_name", "writes")

    def __init__(self, kind, label, target, owner, category=None, skip=(),
                 names=None, extra=(), head=(), fixed=(), node="", doc="",
                 kinds=(), quoted=(), seeds=(), by_name=(), writes=""):
        self.kind = kind
        self.label = label
        self.category = category or _category(target)
        self.target = target            # e.g. "self.spawn"
        self.owner = owner
        self.head = tuple(head)         # constant positional arguments
        self.fixed = tuple(fixed)       # (name, source) constant keywords
        self.node = node
        self.doc = doc
        self.kinds = tuple(kinds)
        # string rows get quotes: `shape="spot"`, not `shape=spot`
        self.quoted = tuple(quoted)
        # rows with defaults still show an example that acts
        self.seeds = tuple(seeds)
        # positional rows only where the engine orders them so
        self.by_name = tuple(by_name)
        self.writes = str(writes or "")
        names = names or {}
        params = []
        for arg, required, default, keyword in _signature(owner):
            if arg in skip:
                continue
            slot = names.get(arg, arg)
            params.append(Param(arg, slot, WORDS.get(slot, _plain(default)),
                                required, keyword, PICKERS.get(slot)))
        for row in extra:
            arg, slot = row[0], row[1] if len(row) > 1 else row[0]
            required = bool(row[2]) if len(row) > 2 else False
            params.append(Param(arg, slot, WORDS.get(slot, ""), required,
                                False, PICKERS.get(slot)))
        self.params = tuple(params)

    def start(self):
        """The words a block off the palette is dropped with."""
        out = {}
        for p in self.params:
            if p.required or p.slot in self.seeds:
                out[p.slot] = START.get(p.slot) or _plain(p.words) or "None"
        return out

    def slots(self):
        return tuple((p.slot, p.words) for p in self.params)

    def make(self, block):
        """The call: required rows first, the rest by name."""
        lead, named, seen = [], [], set()
        for p in self.params:
            text = str(block.fields.get(p.slot, "")).strip()
            if text and p.slot in self.quoted:
                text = _quote(text)
            if p.required and not p.keyword and p.slot not in self.by_name:
                lead.append(text or START.get(p.slot) or '""')
            elif text:
                named.append(f"{p.arg}={text}")
                seen.add(p.arg)
        for arg, text in self.fixed:
            if arg not in seen:
                named.append(f"{arg}={text}")
        call = f"{self.target}({', '.join(list(self.head) + lead + named)})"
        return f"{self.writes} = {call}" if self.writes else call

    def read(self, node):
        """{slot: words} when this call is this block, else None."""
        args = node.args
        if len(args) < len(self.head) or len(args) > len(self.head) + \
                len(self.params):
            return None
        for want, got in zip(self.head, args):
            if isinstance(got, ast.Starred) or _src(got) != want:
                return None
        fields = {p.slot: "" for p in self.params}
        rest = args[len(self.head):]
        by_arg = {p.arg: p for p in self.params}
        const = dict(self.fixed)
        seen_const = set()

        def note(p, got):
            text = _src(got)
            if p.slot in self.quoted:
                text = _unquote(text)
            fields[p.slot] = text

        for p, got in zip(self.params, rest):
            if isinstance(got, ast.Starred):
                return None
            note(p, got)
        for kw in node.keywords:
            if not kw.arg:
                return None         # **kwargs: a word the block cannot show
            if kw.arg in const and by_arg.get(kw.arg) is None:
                if _src(kw.value) != const[kw.arg]:
                    return None     # the constant a block always writes
                seen_const.add(kw.arg)
                continue
            p = by_arg.get(kw.arg)
            if p is None or fields[p.slot]:
                return None         # a keyword the block cannot show
            note(p, kw.value)
        for arg, want in const.items():
            if by_arg.get(arg) is None and arg not in seen_const:
                return None         # the word that tells two blocks apart
            p = by_arg.get(arg)
            if p is not None and fields[p.slot] != want:
                return None
        for p in self.params:
            if p.required and not fields[p.slot]:
                return None         # a row the call left out
        return fields


def _quote(text):
    """A row read as a string, quoted unless already quoted."""
    text = str(text).strip()
    if not text:
        return '""'
    if len(text) > 1 and text[0] == text[-1] and text[0] in "'\"":
        return text
    return f'"{text}"'


def _unquote(text):
    """A quoted row back to bare words."""
    text = str(text)
    if len(text) > 1 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _plain(default):
    """A default as short words for an empty row."""
    if default is None:
        return ""
    text = repr(default)
    return text[1:-1] if text[:1] in "'\"" and text[-1:] == text[:1] else text


# built-in names every asset row may use: `white` first
BUILTIN_TEXTURES = (("white", "grid") +
                    tuple(name for name, _make, _opts in proctexmod.BUILTIN
                          if name != "grid") +
                    tuple(sorted(set(templatemod.PALETTE.values()))))
BUILTIN_MODELS = tuple(modelmod.PRIMITIVES)
BUILTIN_TONES = audiomod.starter_names()

# the calls a project's own scripts make to name a camera
_CAMERA_CALL = re.compile(r"(?:add_camera|set_active_camera)\(\s*"
                          r"(?:name\s*=\s*)?[\"']([\w .#-]+)[\"']")


def _scripts(project):
    """The `.py` files a project keeps under `scripts/`."""
    root = getattr(project, "path", None)
    if root is None:
        return ()
    try:
        return sorted((Path(root) / "scripts").rglob("*.py"))
    except OSError:
        return ()


def action_words(project):
    """Every action and trigger a row can name, the project's own first."""
    out = []
    for table in (getattr(project, "input_map", dict)(),
                  getattr(project, "trigger_map", dict)(),
                  inputmapmod.config_table()):
        out += [str(name) for name in table]
    return tuple(dict.fromkeys(out))


def camera_words(project):
    """Camera names a project's scripts write, then the engine's own."""
    out = []
    for path in _scripts(project):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out += _CAMERA_CALL.findall(text)
    # `add_camera()` numbers what it builds: cam1, cam2, ...
    out += [f"cam{i}" for i in range(1, 5)]
    return tuple(dict.fromkeys(out))


def font_words(_project=None):
    """The faces this build ships, as a document stores them."""
    return uimod.font_names()


# folder plus built-ins, keyed by row name; built-ins may be a callable
PICKERS = {
    "texture": ("textures", BUILTIN_TEXTURES),
    "model": ("models", BUILTIN_MODELS),
    "sprite": ("models", BUILTIN_MODELS),
    "shader": ("shaders", ()),
    "sound": ("audio", BUILTIN_TONES),
    "path": ("audio", ()),
    "scene": ("scenes", ()),
    # a spawned name is looked for in either folder
    "obj": ("objects", ()),
    "map": ("maps", ()),
    # words only this project, or this build, can say
    "action": ("", action_words),
    "camera": ("", camera_words),
    "font": ("", font_words),
    "font_name": ("", font_words),
}

# words a row may only take from a fixed set, not from a folder
ENUMS = {
    "blend": tuple(rendermod.BLENDS),
}

# loader methods ask each folder, skipping unloadable `.py`
NAMERS = {
    "scenes": ("scene_names",),
    "objects": ("object_names", "entity_names"),
    "shaders": ("shader_names",),
    "models": ("model_names", "model2d_names"),
    "maps": ("map_names", "map2d_names"),
    "textures": ("texture_files",),
    "audio": ("audio_files",),
}


def _folder(project, folder):
    """One folder's names by stem; empty with no project."""
    out = []
    if project is None:
        return out
    for name in NAMERS.get(folder, ()):
        found = getattr(project, name, None)
        if found is None:
            continue
        try:
            out += [Path(str(p)).stem for p in found()]
        except OSError:
            continue                # a folder that cannot be read is empty
    return out


def options(row, project):
    """The words a picker shows: the folder's files first."""
    if not row:
        return ()
    folder, builtins = row
    if callable(builtins):
        builtins = builtins(project) or ()
    out = []
    for word in _folder(project, folder) + list(builtins):
        if word and word not in out:
            out.append(word)
    return tuple(out)


def enum_for(slot, cls=None):
    """The fixed words a knob takes: its class's own set, or the engine's.

    A class spells the words it accepts by pluralising the knob, the way
    `hitbox_shape` is joined by `hitbox_shapes`: one list beside the
    default, instead of a table the editor has to keep in step.
    """
    if cls is not None:
        got = getattr(cls, f"{slot}s", None)
        if isinstance(got, (list, tuple)) and got:
            return tuple(str(word) for word in got)
    got = ENUMS.get(str(slot))
    return tuple(got) if got else None


def choices(project, slot, cls=None):
    """What a row named `slot` can be filled with."""
    words = enum_for(slot, cls)
    if words is not None:
        return words
    return options(PICKERS.get(slot), project)


def enumerable(slot, cls=None):
    """True when a row's words are a fixed set rather than files."""
    return enum_for(slot, cls) is not None


def known(project, slot, word):
    """True when a word is something this row can hold."""
    text = str(word or "").strip()
    if not text:
        return False
    if slot in ("texture", "sprite") and colorsmod.is_spelling(text):
        return True
    return text in set(choices(project, slot))


# rows when a signature cannot say; `spawn(**kw)` differs per kind
_PROP3D = (("yaw", "yaw"), ("scale", "scale"))
_PROP2D = (("size", "size"), ("texture", "texture"), ("grid", "grid"))
_PANEL = (("text", "text", True), ("size", "size"), ("color", "color"),
          ("hover_color", "hover_color"), ("press_color", "press_color"),
          ("font_size", "font_size"), ("action", "action"))
# UIObject rows that read better on the class
_SKIP_UI = ("scene", "text_color", "font_name", "texture", "anchor",
            "blend")
# `enabled` tells a label from a button, as a constant
_SKIP_BTN = _SKIP_UI + ("enabled",)


_SCENES = ("scene3d", "scene2d", "sceneui")

# files whose `self` owns a mesh a look can wear
_OBJECTS = ("object3d", "object2d", "ui", "player3d", "player2d",
            "model3d", "sprite2d")

# bodies that carry behaviour: health, an AI, a team, a collider
_BEHAVIOUR = ("entity3d", "entity2d", "object3d", "object2d",
              "player3d", "player2d")
_BODY3D = ("entity3d", "object3d", "player3d")
_BODY2D = ("entity2d", "object2d", "player2d")
# files whose `self` is a node in a tree: it can look around and leave
_TREE = _SCENES + _OBJECTS + ("entity3d", "entity2d")
# the two emitters, and any object that has one as a node
_PARTICLES = ("particle3d", "particle2d")


CALLS = (
    # scene: the flow between screens, the world's light, the camera
    Call("goto", "go to the scene %scene%",
         "self.play_scene", "Scene.play_scene", kinds=_SCENES,
         names={"name": "scene"}, doc="Fade to another scene by name; "
         "on_exit then on_enter run."),
    Call("push", "put the scene %scene% on top",
         "self.push_scene", "Scene.push_scene", kinds=_SCENES,
         names={"name": "scene"}, doc="Stack a scene over this one - a pause "
         "card, a shop - and come back with pop."),
    Call("pop", "back to the scene below",
         "self.pop_scene", "Scene.pop_scene", kinds=_SCENES,
         doc="Unwind the last push_scene(); this scene is where you left it."),
    Call("loadmap", "load the map %map%",
         "self.load_map", "Scene.load_map", kinds=_SCENES,
         names={"name": "map"}, skip=("doc",), quoted=("map",),
         node="load %map%",
         doc="Build one maps/ file into this scene - its carved geometry, "
             "its nodes and its spawn - and keep whatever the scene "
             "spawned itself."),
    Call("changemap", "swap to the map %map%",
         "self.change_map", "Scene.change_map", kinds=_SCENES,
         names={"name": "map"}, skip=("doc",), quoted=("map",),
         node="swap to %map%",
         doc="The old level goes out, the new one comes in, mid play: the "
             "player, the HUD and this scene's own objects stay put. "
             "`on_map_loaded` runs once it stands."),
    Call("unloadmap", "take the map out",
         "self.unload_map", "Scene.unload_map", kinds=_SCENES,
         node="unload the map",
         doc="Every node the map placed leaves with it, so an empty "
             "stage can be redraw by the next load_map()."),
    Call("ambient", "set the ambient light to %color% at %level%",
         "self.set_ambient", "Scene.set_ambient", kinds=("scene3d",),
         seeds=("level",),
         doc="What every unlit surface falls back to; dim it for night."),
    Call("sun", "aim the sun %dir% in %color%",
         "self.set_sun", "Scene.set_sun", kinds=("scene3d",),
         seeds=("dir", "color"),
         doc="The one directional light of a 3D scene, made on the first "
             "call."),
    Call("camera", "look through the camera %camera%",
         "self.set_active_camera", "Scene.set_active_camera",
         names={"cam": "camera"}, kinds=("scene3d",), seeds=("camera",),
         doc="One of the cameras this scene registered with add_camera()."),
    Call("newcam", "add a camera called %name%", "self.add_camera",
         "Scene.add_camera", kinds=("scene3d",), seeds=("name",),
         doc="A second view a scene can switch to; the name is what "
             "`camera` picks."),
    Call("shake", "shake the camera by %amount%",
         "self.shake", "Scene3D.shake", kinds=("scene3d",), seeds=("amount",),
         doc="A footstep, a thump, an explosion: one call, a bigger number."),
    Call("follow", "make the camera follow %who%",
         "self.follow", "Scene3D.follow", names={"target": "who"},
         kinds=("scene3d",), seeds=("who",),
         doc="Ease the view toward an object every frame; follow(None) lets "
             "go."),
    Call("lookat", "aim the camera at %pos%", "self.look_at",
         "Scene3D.look_at", names={"target": "pos"}, kinds=("scene3d",),
         seeds=("pos",),
         doc="Point the view at a world position in a 3D scene."),
    Call("post", "paint the whole frame through %shader%",
         "self.set_post", "Scene.set_post", kinds=_SCENES,
         extra=(("shader", "shader", True),), quoted=("shader",),
         node="paint through %shader%",
         doc="One screen-mode look from shaders/ run over this scene's "
             "frame; a chain of them is set with `set self.post to (...)`, "
             "which the game re-reads every frame."),
    Call("retune", "set the knob %knob% of %shader% to %value%",
         "self.set_shader_knob", "Scene.set_shader_knob", kinds=_SCENES,
         names={"name": "shader"}, quoted=("shader", "knob"),
         node="retune %shader%",
         doc="Drive one knob of a look this scene can draw with. Written "
             "in update it animates: a swell, a dying flicker."),

    # object: creating one, and stamping the world it stands in
    Call("spawn", "spawn %obj% at %pos%", "self.spawn",
         "Scene.spawn", skip=("parent", "clone_of"), seeds=("pos",),
         doc="An objects/ or entities/ stem, or a class; the object builds "
             "as it lands."),
    Call("spawn3d", "spawn the 3D prop %obj% at %pos% yawed %yaw% "
                  "scaled %scale%",
         "self.spawn", "Scene.spawn", skip=("parent", "clone_of"),
         extra=_PROP3D, kinds=("scene3d", "object3d"),
         seeds=("pos", "yaw", "scale"), node="spawn %obj%",
         doc="A 3D object with the two words every Object3D takes: its "
             "facing in radians, and how big it is built."),
    Call("spawn2d", "spawn the sprite %obj% at %pos%",
         "self.spawn", "Scene.spawn", skip=("parent", "clone_of"),
         extra=_PROP2D, kinds=("scene2d", "object2d"),
         seeds=("pos", "texture"), node="spawn %obj%",
         doc="A 2D object with the words an Object2D takes: box size, sheet "
             "name, and the grid of cells that sheet holds."),
    Call("spawnui", "spawn the widget %obj% at %pos% saying %text%",
         "self.spawn", "Scene.spawn", skip=("parent", "clone_of"),
         extra=_PANEL, kinds=("scene2d", "sceneui"), seeds=("pos",),
         by_name=("text",), node="spawn %obj%",
         doc="A UIObject or a subclass of one, with the words a panel takes."),
    Call("place", "place the model %model% at %pos%",
         "self.place_model", "Scene3D.place_model", kinds=("scene3d",),
         names={"name": "model"}, seeds=("pos",),
         doc="Stamped into the static batch: free to draw, and it never "
             "moves."),
    Call("modelobj", "make a moving %model% at %pos% scaled %scale%",
         "self.model_object", "Scene3D.model_object", kinds=("scene3d",),
         names={"name": "model"}, seeds=("pos",), node="moving %model%",
         doc="A ModelObject you can move, turn and tint every frame."),
    Call("addmesh", "add the mesh %expr% in %texture%",
         "self.add", "Scene.add", names={"data": "expr"},
         kinds=("scene3d", "object3d"),
         seeds=("texture",),
         doc="Batched world geometry: meshes.box(...), meshes.plane(...)."),
    Call("livemesh", "add the live mesh %expr% in %texture%",
         "self.dynamic", "Scene.dynamic", names={"data": "expr"},
         kinds=("scene3d", "object3d"),
         seeds=("texture",),
         doc="A mesh you refill every frame; live meshes are never batched."),
    Call("wear", "wear the shader %shader%", "self.set_shader",
         "GameObject.set_shader", kinds=_OBJECTS,
         names={"name": "shader"}, quoted=("shader",),
         node="wear %shader%",
         doc="A uv or texture look from shaders/ run over this object's own "
              "mesh. Decide it before build(); `set self.shader to None` "
              "takes the look off again."),

    # tree: Godot's names for where a node stands and when it goes
    Call("node", "read the node at %child%", "self.get_node",
         "GameObject.get_node", names={"path": "child"},
         quoted=("child",), writes="node", kinds=_TREE,
         node="the node %child%",
         doc="Find a node by the name the outline shows: `Enemy`, `Gate#0`, "
             "`Entrance/Gate`, or `.` and `..` for where I stand."),
    Call("free", "leave the scene at the end of the frame",
         "self.queue_free", "GameObject.queue_free", kinds=_TREE,
         doc="Godot's removal, and it is safe inside a loop: everything "
             "marked goes once this frame's update is done."),

    # signals: the same bus as broadcast and listen, spelled Godot's way
    Call("connect", "connect %signal% to %fn%", "self.connect",
         "GameObject.connect", names={"name": "signal"},
         quoted=("signal",), seeds=("fn",), kinds=_TREE,
         node="connect %signal%",
         doc="Ask a callable to hear one signal. The second row is any "
             "function; `self.on_trigger` is what an object already has."),
    Call("emit", "emit %signal% with %value%", "self.emit",
         "GameObject.emit", names={"name": "signal"},
         quoted=("signal",), kinds=_TREE, node="emit %signal%",
         doc="Say this signal fired, with or without a value. Everything "
             "connected to it, and every listener, hears it this frame."),

    # entity: what an actor is told about itself, one call each
    Call("health", "set my health to %health%", "self.set_health",
         "Entity3D.set_health", names={"value": "health"}, kinds=_BEHAVIOUR,
         node="my health",
         doc="How much damage I can still take. Reaching zero ends me, "
             "exactly as the last of my health does in a fight."),
    Call("maxhealth", "set my full health to %health%",
         "self.set_max_health", "Entity3D.set_max_health",
         names={"value": "health"}, kinds=_BEHAVIOUR, node="my full health",
         doc="My maximum. What I have now is kept, or trimmed to fit under "
             "a ceiling that came down."),
    Call("ai", "switch my AI to %ai_type% with %config%", "self.set_ai",
         "Entity3D.set_ai", quoted=("ai_type",), seeds=("config",),
         kinds=_BEHAVIOUR, node="my AI is %ai_type%",
         doc="One of `none`, `follow`, `patrol`, `wander`, `aggro`. The dict "
             "is what that behaviour needs: `waypoints` to patrol, a "
             "`wander_interval` in seconds."),
    Call("aitarget", "follow %target%", "self.set_ai_target",
         "Entity3D.set_ai_target", kinds=_BEHAVIOUR, node="follow %target%",
         doc="Who I chase or walk with. None means nobody until I am told."),
    Call("team", "join the %team% team", "self.set_team",
         "Entity3D.set_team", quoted=("team",), kinds=_BEHAVIOUR,
         node="my team", doc="`player`, `enemy`, `neutral` or `friendly`: "
         "what an aggro body looks at before it picks a target."),
    Call("aggro", "notice a target %distance% away", "self.set_aggro_range",
         "Entity3D.set_aggro_range", seeds=("distance",), kinds=_BEHAVIOUR,
         node="my aggro range",
         doc="How far off I take notice. Leave the second row empty and I "
             "lose interest at twice that distance."),
    Call("attack", "attack with reach %range% for %damage% every %cooldown%s",
         "self.set_attack", "Entity3D.set_attack",
         seeds=("range", "damage", "cooldown"), kinds=_BEHAVIOUR,
         node="my attack",
         doc="How near I must be, how hard I hit, and the seconds between "
             "swings. An empty row keeps what I had."),
    Call("speed", "walk at %walk% and run at %run%", "self.set_move_speed",
         "Entity3D.set_move_speed", seeds=("walk", "run"), kinds=_BEHAVIOUR,
         node="my speed",
         doc="Cruising speed and chasing speed, in the world's units a "
             "second: metres in a 3D body, pixels in a flat one."),
    Call("hitbox", "set my hitbox to %hitshape%", "self.set_hitbox",
         "Entity3D.set_hitbox", names={"shape": "hitshape"},
         quoted=("hitshape",), seeds=("half",), kinds=_BODY3D,
         node="my hitbox",
         doc="My 3D collider: a `box` of half extents, a `sphere` of a "
             "radius, or a `capsule` of a radius and a height."),
    Call("hitbox2d", "set my flat hitbox to %hitshape%",
         "self.set_hitbox2d", "Entity2D.set_hitbox2d",
         names={"shape": "hitshape", "size": "extent"},
         quoted=("hitshape",), seeds=("extent",), kinds=_BODY2D,
         node="my flat hitbox",
         doc="My flat collider: a `rect` of (width, height) or a `circle` of "
             "a radius."),

    # light: one drawer; the shape picks the kind
    Call("lamp", "add a %shape% light at %pos% in %color%",
         "self.add_light", "Scene.add_light", quoted=("shape",),
         kinds=("scene3d",),
         seeds=("pos", "color", "shape"),
         extra=(("energy", "energy"), ("radius", "radius"),
                ("angle", "angle"), ("flicker", "flicker"),
                ("pulse", "pulse"), ("tag", "tag")),
         doc="Click the shape to cycle it. Keep the light it answers with to "
             "move or switch it later.", node="add a %shape% light"),
    Call("preset", "add the %light% light preset at %pos%",
         "self.add_preset", "Scene.add_preset", names={"name": "light"},
         kinds=("scene3d",), seeds=("pos",),
         node="add the %light% light"),
    Call("unlight", "take the light %who% out", "self.remove_light",
         "Scene.remove_light", names={"light": "who"},
         kinds=("scene3d",), node="take the %who% light out"),
    Call("olight", "make a %shape% light here", "self.light", "Object3D.light",
         quoted=("shape",), seeds=("pos", "color", "shape"),
         extra=(("radius", "radius"), ("energy", "energy"),
                ("flicker", "flicker")),
         kinds=("object3d", "player3d"), node="a %shape% light here",
         doc="A light that goes out with the object: dispose() removes it."),

    # audio: files by stem or tone; the row is `sound`
    Call("sound", "play the sound %sound% at %amount% volume",
         "self.audio.play", "Audio.play",
         names={"key": "sound", "volume": "amount"},
         seeds=("amount",),
         doc="A file in audio/ by stem, or one of the six tones the game "
             "always has, on its free channel."),
    Call("tone", "play the tone %key% at %hz% hertz for %ms% ms",
         "self.audio.tone", "Audio.tone", names={"freq": "hz"},
         quoted=("kind",), seeds=("hz", "ms"),
         doc="A synthesised note, cached under that key: no sound file "
             "needed."),
    Call("sweep", "sweep the tone %key% from %hz% to %to% hertz",
         "self.audio.sweep", "Audio.sweep",
         names={"f0": "hz", "f1": "to"}, quoted=("kind",),
         seeds=("hz", "to"),
         doc="A note that slides in pitch - a win chime, a fall."),
    Call("music", "play the music %path%",
         "self.audio.music", "Audio.music",
         doc="A file in audio/ streamed as the soundtrack; one track at a "
             "time, and it fades itself out when another starts."),
    Call("noise", "play the noise %key%", "self.audio.noise",
         "Audio.noise",
         doc="Synthesised noise: wind, a hiss, a steam vent."),
    Call("volume", "set the master volume to %amount%",
         "self.audio.set_master", "Audio.set_master",
         names={"volume": "amount"}, doc="Everything at once, sounds and "
         "music."),

    # ui: the HUD, drawn over the world as a stack
    Call("say", "draw the words %text% at %pos%",
         "self.hud.text", "Hud.text", names={"s": "text"},
         seeds=("pos",),
         doc="One HUD line in the game's normal font; see self.hud."),
    Call("hudpanel", "draw a HUD panel %rect%", "self.hud.panel", "Hud.panel",
         doc="A translucent backing panel, for words to sit on."),
    Call("hudbar", "draw a HUD bar %rect% filled to %amount%",
         "self.hud.bar", "Hud.bar", names={"frac": "amount"},
         doc="A value bar; the fill is clamped to 0..1 for you."),
    Call("prompt", "prompt %key% to %label%", "self.hud.prompt",
         "Hud.prompt", doc="A keycap and its words, low on the screen unless "
         "told where."),
    Call("hints", "list the hints %pairs%", "self.hud.hints", "Hud.hints",
         doc="A column of 'key  action' lines, bottom left unless told "
             "where."),
    Call("caption", "caption %lines%", "self.hud.subtitle", "Hud.subtitle",
         doc="Centred subtitles just above the bottom edge."),

    # widgets: a classless panel, for menus or inventories
    Call("button", "button %text% at %pos%", "self.spawn",
         "UIObject.__init__", head=("fe.UIObject",), skip=_SKIP_BTN,
         seeds=("pos", "text"), by_name=("text",),
         kinds=("scene2d", "sceneui"), node="button %text%",
         doc="A UIObject built on the spot - no class needed. Leave action "
             "as None and override on_click later."),
    Call("label", "label %text% at %pos%", "self.spawn",
         "UIObject.__init__", head=("fe.UIObject",), skip=_SKIP_BTN,
         fixed=(("enabled", "False"),), seeds=("pos", "text"),
         by_name=("text",),
         kinds=("scene2d", "sceneui"), node="label %text%",
         doc="A panel that never takes the mouse: words on a screen."),

    # components: methods the preset nodes really have, one per type
    Call("settext", "set the words to %text%", "self.set_text",
         "Text3D.set_text", category="object", kinds=("text3d", "text2d"),
         node="set the words",
         doc="Repaint this text node; empty words draw nothing."),
    Call("emitplay", "play the emitter sound %sound% at %amount% volume",
         "self.play", "AudioEmitter3D.play", category="audio",
         names={"gain": "amount"}, quoted=("sound",), seeds=("sound",),
         kinds=("audio3d", "audio2d"), node="play %sound%",
         doc="Start this emitter; leave the name empty to play the sound "
             "its knobs already say, at its own volume."),
    Call("emitstop", "stop the emitter", "self.stop",
         "AudioEmitter3D.stop", category="audio",
         kinds=("audio3d", "audio2d"),
         doc="Silence this emitter until the next play."),
    Call("timerstart", "start the timer", "self.start", "Timer3D.start",
         category="functions", kinds=("timer3d", "timer2d"),
         doc="Begin counting again from a fresh interval."),
    Call("timerstop", "stop the timer", "self.stop", "Timer3D.stop",
         category="functions", kinds=("timer3d", "timer2d"),
         doc="Stop counting; a later start begins from the top again."),

    # particles: `emit` is the signal block's, so these keep their own names
    Call("particlemit", "drip %count% points", "self.emit_particles",
         "Particle3D.emit_particles", category="object",
         names={"n": "count"}, kinds=_PARTICLES, node="drip %count% points",
         doc="Put points in the air from here, whether or not the emitter "
             "is dripping: one, or as many as you ask for."),
    Call("particleburst", "burst %count% points", "self.burst_particles",
         "Particle3D.burst_particles", category="object",
         names={"n": "count"}, kinds=_PARTICLES, node="burst %count% points",
         doc="All at once, from one point: an impact, a torch lit, a door "
             "forced. Leave the row empty for the emitter's whole pool."),
    Call("particlestop", "stop the particles", "self.stop_particles",
         "Particle3D.stop_particles", category="object", kinds=_PARTICLES,
         node="stop the particles",
         doc="Stop dripping. What is already in the air still lives out "
             "its life; `self.clear()` drops that too."),
    Call("particleset", "set the knob %knob% to %value%",
         "self.set_particles", "Particle3D.set_particles", category="object",
         quoted=("knob",), kinds=_PARTICLES, node="set %knob%",
         doc="One of the emitter's own knobs at run time: `rate`, `color`, "
             "`gravity`, `lifetime`. `blend` is decided at build() instead."),

    # shader: each block owns its written line; reads need none
    Call("paint", "paint the sheet as it is seen at %uv%", "g.tex",
         "Builder.tex", category="shader", kinds=("shader",),
         writes="g.out", node="paint %uv%",
         doc="The picture this look is running, sampled at its own spot. "
             "The row takes any coordinates: g.uv, g.pixel, g.wmuv(...)."),
    Call("grain", "paint the noise over %uv% at %scale%", "g.noise",
         "Builder.noise", category="shader", kinds=("shader",),
         seeds=("scale",), writes="g.out", node="paint the noise at %uv%",
         doc="One hash per spot: film grain, speckle, a bad tape line. A "
             "bigger scale is finer grain."),
    Call("wash", "paint between %a% and %b% by %t%", "g.mix",
         "Builder.mix", category="shader", kinds=("shader",),
         writes="g.out", node="paint between %a%",
         doc="Two colours and the number that walks between them: walk in "
             "a knob, walk in g.time, and the look breathes."),
    Call("ramp", "paint up from %a% to %b% as %t% climbs", "g.ramp",
         "Builder.ramp", category="shader", kinds=("shader",),
         writes="g.out", node="ramp from %a%", doc="The same blend "
         "written as a ramp, which reads better when the third row is the "
         "thing being measured rather than a mix amount."),
    Call("hue", "paint the hue of %h%", "g.hue", "Builder.hue",
         category="shader", kinds=("shader",), writes="g.out",
         node="paint the hue of %h%",
         doc="A whole rainbow from one number, 0..1: a tint nobody has to "
             "pick out by hand."),
    Call("soft", "paint %x% eased between %a% and %b%", "g.smoothstep",
         "Builder.smoothstep", category="shader", kinds=("shader",),
         writes="g.out", node="ease %x%",
         doc="A curved edge instead of a hard one: nothing below the first "
             "number, all above the second, easing in between."),
    Call("safe", "paint %x% kept between %lo% and %hi%", "g.clamp",
         "Builder.clamp", category="shader", kinds=("shader",),
         seeds=("lo", "hi"), writes="g.out", node="keep %x% inside",
         doc="Stop a look painting outside the picture. The bounds are 0..1 "
             "for a colour, a mask or a mix amount."),
    Call("slide", "slide %uv% along %direction% at %speed%", "g.wmuv",
         "Builder.wmuv", category="shader", kinds=("shader",),
         seeds=("direction", "speed"), writes="g.uv", node="slide %uv%",
         doc="The one row here that paints nothing: it moves the "
             "coordinates every later row reads, so the sheet scrolls."),
)


# target expression to its calls: constant head, then fewest rows
BY_TARGET = {}
for _call in CALLS:
    BY_TARGET.setdefault(_call.target, []).append(_call)
for _list in BY_TARGET.values():
    _list.sort(key=lambda c: (-len(c.head), len(c.params)))

# kinds file blocks in `blocks.SPEC`; a duplicate silently drops
_seen, _dupes = set(), []
for _call in CALLS:
    if _call.kind in _seen and _call.kind not in _dupes:
        _dupes.append(_call.kind)
    _seen.add(_call.kind)
if _dupes:
    raise ValueError(f"api.CALLS gives one kind to two calls: {_dupes}")


def read(node):
    """(kind, fields) when the call matches a block."""
    if not isinstance(node, ast.Call):
        return None
    for call in BY_TARGET.get(_src(node.func), ()):
        fields = call.read(node)
        if fields is not None:
            return call.kind, fields
    return None


def read_assign(target, node):
    """(kind, fields) when `target = <call>` matches."""
    if not isinstance(node, ast.Call):
        return None
    for call in BY_TARGET.get(_src(node.func), ()):
        if call.writes and call.writes == target:
            fields = call.read(node)
            if fields is not None:
                return call.kind, fields
    return None


def by_kind(kind):
    for call in CALLS:
        if call.kind == kind:
            return call
    return None


def slot_picks(kind, slot):
    """The picker a block row shows, or None."""
    entry = by_kind(kind)
    if entry is None:
        return None
    for p in entry.params:
        if p.slot == slot and p.picks:
            return p.picks
    return None
