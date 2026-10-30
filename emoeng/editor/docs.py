"""The engine's documentation catalog."""

import ast
from pathlib import Path

# package root: parents[1] is the `emoeng` folder
ROOT = Path(__file__).resolve().parents[1]
PKG = "emoeng"

# files that build the scripting API, in listed order
_API_FILES = [ROOT / "__init__.py", ROOT / "const.py"]
_ENGINE_DIR = ROOT / "engine"
if _ENGINE_DIR.is_dir():
    _API_FILES += sorted(_ENGINE_DIR.glob("*.py"))

_KIND_BADGE = {
    "module": "module",
    "class": "class",
    "function": "def",
    "method": "def",
}


# signature helpers
def _unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _args_str(args):
    """Rebuild a readable signature from an arguments node."""
    parts = []
    posonly = list(getattr(args, "posonlyargs", []) or [])
    regular = list(args.args or [])
    all_pos = posonly + regular
    defaults = list(args.defaults or [])
    pad = len(all_pos) - len(defaults)
    for i, arg in enumerate(all_pos):
        text = arg.arg
        if arg.annotation is not None:
            text += ": " + _unparse(arg.annotation)
        d = defaults[i - pad] if i >= pad else None
        if d is not None:
            text += "=" + _unparse(d)
        parts.append(text)
        if posonly and i == len(posonly) - 1:
            parts.append("/")
    if args.vararg is not None:
        v = "*" + args.vararg.arg
        if args.vararg.annotation is not None:
            v += ": " + _unparse(args.vararg.annotation)
        parts.append(v)
    for arg, d in zip(args.kwonlyargs or [], args.kw_defaults or []):
        text = arg.arg
        if arg.annotation is not None:
            text += ": " + _unparse(arg.annotation)
        if d is not None:
            text += "=" + _unparse(d)
        parts.append(text)
    if args.kwarg is not None:
        k = "**" + args.kwarg.arg
        if args.kwarg.annotation is not None:
            k += ": " + _unparse(args.kwarg.annotation)
        parts.append(k)
    return "(" + ", ".join(p for p in parts if p) + ")"


def _class_sig(node):
    bases = [_unparse(b) for b in node.bases]
    bases = [b for b in bases if b and b != "object"]
    return "class " + node.name + ("(" + ", ".join(bases) + ")" if bases else "")


def _module_key(path):
    """Dotted package path for a source file under ROOT."""
    rel = path.relative_to(ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join([PKG] + parts)


# the catalog
class Entry:
    """One documented thing: a module, class, function or method."""

    __slots__ = ("full", "name", "kind", "parent", "module", "signature",
                 "doc", "methods")

    def __init__(self, full, name, kind, parent, module, signature, doc):
        self.full = full
        self.name = name
        self.kind = kind
        self.parent = parent
        self.module = module
        self.signature = signature
        self.doc = doc or ""
        self.methods = []

    @property
    def badge(self):
        return _KIND_BADGE.get(self.kind, self.kind)


class Docs:
    """The API reference, written guides and lookup helpers."""

    def __init__(self):
        self.entries = []
        self.by_full = {}
        self.by_key = {}
        self.by_name = {}
        self.modules = []
        self._build()

    # -- building --------------------------------------------------------
    def _add(self, entry):
        self.entries.append(entry)
        self.by_full[entry.full] = entry
        keys = {entry.full}
        if entry.full.startswith(PKG + "."):
            tail = entry.full[len(PKG) + 1:]
            keys.add(tail)
            if tail.startswith("engine."):
                rest = tail[len("engine."):]
                keys.add(rest)
                keys.add("engine." + rest)
        last_mod = entry.module.rsplit(".", 1)[-1] if entry.module else ""
        if last_mod and entry.kind in ("class", "function"):
            keys.add(f"{last_mod}.{entry.name}")
        if entry.kind == "method" and entry.parent:
            keys.add(f"{entry.parent}.{entry.name}")
        for k in keys:
            # dotted keys win; never overwrite one with a shorter alias
            self.by_key.setdefault(k, entry)
        self.by_name.setdefault(entry.name, []).append(entry)

    def _build(self):
        for path in _API_FILES:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            mod = _module_key(path)
            mod_doc = ast.get_docstring(tree) or ""
            short = mod.split(".")[-1]
            self._add(Entry(mod, short, "module", None, mod, mod, mod_doc))
            module_entry = self.by_full[mod]
            self.modules.append(module_entry)
            for node in tree.body:
                self._top_level(module_entry, node)

    def _top_level(self, module_entry, node):
        mod = module_entry.full
        if isinstance(node, ast.ClassDef):
            entry = Entry(f"{mod}.{node.name}", node.name, "class", None,
                          mod, _class_sig(node), ast.get_docstring(node) or "")
            self._add(entry)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m = Entry(f"{mod}.{node.name}.{sub.name}", sub.name,
                              "method", node.name, mod,
                              sub.name + _args_str(sub.args),
                              ast.get_docstring(sub) or "")
                    self._add(m)
                    entry.methods.append(m)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entry = Entry(f"{mod}.{node.name}", node.name, "function", None,
                          mod, node.name + _args_str(node.args),
                          ast.get_docstring(node) or "")
            self._add(entry)

    # -- lookup ----------------------------------------------------------
    @staticmethod
    def _clean(expr):
        s = str(expr).strip().strip(".")
        while ".." in s:
            s = s.replace("..", ".")
        return s

    def lookup(self, expr):
        """Resolve a dotted path or word to an Entry."""
        budget = [300]

        def step():
            budget[0] -= 1
            if budget[0] < 0:
                raise RuntimeError("docs lookup step budget exhausted")

        try:
            return self._lookup(expr, step)
        except RuntimeError:
            return None

    def _lookup(self, expr, step):
        expr = self._clean(expr)
        if not expr:
            return None
        step()
        comps = [c for c in expr.split(".") if c]
        # drop aliases so `fe.engine.anim` and `self.spawn` resolve
        while len(comps) > 1 and comps[0] in ("fe", PKG, "self", "cls"):
            comps = comps[1:]
        if len(comps) == 1 and comps[0] in ("fe", PKG, "self", "cls"):
            return None
        dotted = ".".join(comps)
        hit = self.by_key.get(dotted)
        if hit is not None:
            return hit
        # try progressively shorter suffixes: engine.anim.spin -> spin
        for n in range(len(comps), 0, -1):
            sub = ".".join(comps[-n:])
            hit = self.by_key.get(sub)
            if hit is not None:
                return hit
        named = self.by_name.get(comps[-1])
        if named:
            # prefer a method/attr on the class named just before it
            if len(comps) >= 2:
                owner = comps[-2]
                for e in named:
                    if e.parent == owner:
                        return e
            return named[0]
        return None

    def tip(self, expr, max_lines=7):
        """Short hover text for `expr`, or None when nothing matches."""
        cached = _TIP_CACHE.get(expr)
        if cached is not None or expr in _TIP_CACHE:
            return cached
        lines = self._tip(expr, max_lines)
        if len(_TIP_CACHE) > 3000:   # bounded, reset on reload
            _TIP_CACHE.clear()
        _TIP_CACHE[expr] = lines
        return lines

    def _tip(self, expr, max_lines=7):
        e = self.lookup(expr)
        if e is None:
            return None
        head = e.signature if e.kind in ("function", "method") \
            else (e.signature if e.kind == "class" else e.full)
        if e.kind == "class":
            lines = [head]
        else:
            lines = [f"{e.badge} {head}"]
        doc = e.doc.strip()
        if doc:
            first = doc.split("\n\n")[0].strip()
            for ln in wrap_lines(first, 60):
                if len(lines) > max_lines:
                    break
                lines.append(ln)
        if e.kind == "module" and e.full != PKG:
            lines.append("")
            lines.append("see the Docs tab for the full listing")
        return lines

    def content(self, key):
        """Reading-pane body for a nav key: (title, badge, [(style, text)])."""
        if key.startswith("guide:"):
            g = GUIDES_BY_KEY.get(key)
            if g is not None:
                return g["title"], "guide", [("text", ln) for ln in g["lines"]]
            return key, "guide", [("text", "")]
        e = self.by_full.get(key) or self.by_key.get(key)
        if e is None:
            return key, "", [("text", "")]
        blocks = []
        if e.kind in ("function", "method", "class"):
            blocks.append(("sig", e.signature))
        blocks.append(("loc", e.full))
        if e.doc.strip():
            for ln in e.doc.strip().splitlines():
                blocks.append(("text", ln))
        if e.methods:
            blocks.append(("text", ""))
            blocks.append(("head", "Methods"))
            for m in e.methods:
                blocks.append(("sig", m.signature))
                first = m.doc.strip().split("\n\n")[0].strip() if m.doc else ""
                if first:
                    for ln in wrap_lines(first, 68):
                        blocks.append(("sub", ln))
        return e.name, e.badge, blocks

    def nav(self):
        """Flat navigation rows: [(label, key, depth, kind)] for the tab."""
        rows = [("Guides", "", 0, "group")]
        for g in GUIDES:
            rows.append((g["title"], g["key"], 1, "topic"))
        rows.append(("API Reference", "", 0, "group"))
        for mod in self.modules:
            rows.append((mod.name if mod.full != PKG else PKG + " (root)",
                         mod.full, 0, "module"))
            for e in self.entries:
                if e.parent is None and e.module == mod.full and \
                        e.kind in ("class", "function") and e.full != mod.full:
                    rows.append((e.name, e.full, 1, e.kind))
        return rows


def wrap_lines(text, width):
    out = []
    for para in str(text).splitlines() or [""]:
        words = para.split()
        if not words:
            out.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            if len(cur) + 1 + len(w) <= width:
                cur += " " + w
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return out


# written guides - "how the engine functions"
GUIDES = [
    {"key": "guide:start", "title": "Getting Started", "lines": [
        "A game is a project folder, not a build step. Open one in the",
        "editor and F5 runs it; the same folder is what the Build tab",
        "packages into an .exe.",
        "",
        "  project.flig      manifest: title, window, render, save",
        "  input.map.json    optional: the project's own keymap",
        "  assets.json       optional: how assets are imported",
        "  scenes/*.scene    documents: what is placed, and where",
        "  objects/*.obj3d   documents: one node tree per object",
        "  objects/*.obj2d     (the flat half)",
        "  scripts/scenes    Scene3D / Scene2D / SceneUI - the game logic",
        "  scripts/objects   the classes an object document names",
        "  scripts/shaders   the fe.Shader classes a look is built from",
        "  scripts/*.py      shared python modules",
        "  shaders/*.shader  documents: mode + knobs for one look",
        "  models/*.model3d  vertex/face meshes, made in the Model tab",
        "  models/*.model2d  flat cutout rigs, one quad per part",
        "  maps/*.map3d      one whole level: carved parts, placed",
        "  maps/*.map2d        nodes, a spawn, a collision mode",
        "  textures/*.png    uploaded by file stem",
        "  audio/*.wav|.ogg  loaded into the audio bank by stem",
        "",
        "Scenes and objects import the engine as `import emoeng as fe`",
        "and subclass fe.Scene3D / fe.Scene2D / fe.SceneUI and fe.Object3D",
        "/ fe.Object2D / fe.UIObject. The engine calls your",
        "hooks; you never write the window or the frame loop yourself.",
        "",
        "What every file in the folder holds - and how the manifest is",
        "laid out - is the next page, \"The Project Folder\".",
    ]},
    {"key": "guide:project", "title": "The Project Folder", "lines": [
        "project.flig is plain JSON with a `format` number and one",
        "section per concern, so the file stays readable and two people",
        "editing the same game rarely collide in it:",
        "",
        "  format, name, title, start, version, description, seed",
        "  window   size, fullscreen",
        "  render   scale, post, clear_color",
        "  save     slot, autosave",
        "  input    actions",
        "  assets   textures, audio",
        "  config   the project's own settings overrides",
        "  build    the Build tab's non-default options",
        "",
        "A key the engine does not know is left exactly where it is, so",
        "a project can keep its own notes in its manifest. An older flat",
        "manifest still opens: its keys move into sections in memory and",
        "are written back in the new shape the first time it is saved.",
        "",
        "    project.get(\"render\", \"post\")        one value",
        "    project.set(\"window\", \"size\", (1280, 720))",
        "    project.save_meta()                atomic write",
        "    loader.read_meta(folder)           peek without opening",
        "",
        "Beside the manifest sit two optional files, both hand-editable",
        "and both written atomically: input.map.json maps an action to",
        "binding names, and assets.json says how textures (filter, wrap,",
        "mipmaps, and the metre size that makes a sheet a material) and",
        "audio (gain) are imported. project.input_map() and",
        "project.asset_settings() read them; the folder also gets a",
        ".gitignore and a README.md when it is created.",
        "",
        "A hot reload needs to know what changed: snapshot() remembers",
        "the mtime and size of every file in scenes/, objects/,",
        "entities/, shaders/, maps/ and scripts/, and changed_since(snap)",
        "reports the edited, added and removed ones next to a fresh",
        "snapshot. Saving a map in the Model tab takes the same route,",
        "so a carved wall appears in the Scene tab without a restart.",
        "",
        "A new project is scaffolded by Project.create(path, title,",
        "template=...), which writes one of seven starters - Game 3D,",
        "Fly 3D, Game 2D, Platformer 2D, Menu, Empty 3D, Empty 2D -",
        "each with its scene script and document, one spawnable object,",
        "the colour-only primitive models, a shaders/ folder and a",
        "`render.post` of `[]`. The two game starters also write a",
        "level: maps/room.map3d or maps/arena.map2d, which their start",
        "scene names in its document. Stock shader looks live in",
        "engine.templates.SHADERS; nothing writes a PNG or a WAV, so a",
        "fresh project ships zero binary files.",
    ]},
    {"key": "guide:loop", "title": "The Game Loop", "lines": [
        "engine.game.Game owns the window, the borderless XP chrome, the",
        "moderngl renderer, the audio bank and the active scene. Each",
        "frame it: pumps pygame events, ticks timers, calls",
        "scene.update(dt), renders the scene's merged geometry through the",
        "camera rig, then lets scene.draw(surface) paint the 2D HUD.",
        "",
        "You do not touch this loop. You put your work in a scene's",
        "on_enter/setup/update/draw hooks and in each object's",
        "build/update/dispose. dt is seconds since the last frame.",
    ]},
    {"key": "guide:scene", "title": "Scenes", "lines": [
        "A scene is one playable screen (engine.scene.Scene). Three kinds",
        "share one API and differ only in how they draw and what they",
        "spawn: Scene3D (a perspective world of Object3D props), Scene2D",
        "(sprites on an orthographic pixel plane, Object2D) and SceneUI",
        "(widgets in window pixels, UIObject). Declare the object files a",
        "3D scene places in `uses`, spawn them in setup, drive the world",
        "from update, and manage the stack with play/push/pop_scene:",
        "",
        "  class Main(fe.Scene3D):",
        "      uses = (\"bonfire\", \"gem\")",
        "",
        "      def setup(self):",
        "          self.fire = self.spawn(\"bonfire\", (0, 0, 0))",
        "",
        "      def update(self, dt):",
        "          self.fire.yaw += dt",
        "",
        "A scene opens on a level rather than building one in code: its",
        "document names a `map`, a maps/<stem>.map3d or .map2d, which is",
        "loaded before setup(), and self.change_map(\"vault\") swaps to",
        "another mid play - the old level and every node it placed leave,",
        "while the player, the HUD and the scene's own objects stay put.",
        "The older `maps` list of a 3D document still places one Map3D",
        "per name, after setup(). The Maps guide is the whole format.",
        "",
        "Hooks (all optional): on_enter, setup, update(dt), draw(surface,",
        "dt), on_exit. Helpers: spawn/despawn objects, schedule calls with",
        "after()/every(), play audio by name, switch/push/pop scenes, read",
        "input, and move the eye with camera helpers. scene.render(camera)",
        "draws every kind; only 3D scenes pilot a grabbed mouse.",
    ]},
    {"key": "guide:maps", "title": "Maps", "lines": [
        "A map is one whole level in one file: maps/<stem>.map3d, or",
        ".map2d for a flat one. Its geometry half is spelled exactly as",
        "a model file spells it - verts, uvs, tris, named parts - and",
        "six keys are added on top:",
        "",
        "  kind       \"map3d\" or \"map2d\"; the extension says the same",
        "  nodes      what the level places, in a scene document's own",
        "             entry shape: collisions, lights, props, scripts",
        "  spawn      the player start, [x, y, z] or [x, y] when flat",
        "  spawn_yaw  which way that start faces, in radians",
        "  collision  how the map's own faces stop a body: \"mesh\"",
        "             sweeps its triangles, \"boxes\" files one solid",
        "             shape per part, \"none\" leaves it to the nodes",
        "  overrides  per-node tweaks - the plan a drag writes",
        "",
        "engine.level.MapLevel builds one: it spawns the Map3D or",
        "Map2D node that draws the parts, then places every node the",
        "file names through the router a scene uses. The lights,",
        "children and colliders a level brought all leave with it, so",
        "changing the room is one call and needs no second scene:",
        "",
        "  self.load_map(\"hall\")          build one and put it in",
        "  self.change_map(\"vault\")       old level out, new one in",
        "  self.unload_map()              leave with no level at all",
        "  self.map.parts()               the carved part names",
        "  self.map.set_part_texture(\"floor\", \"moss\")",
        "  self.map.node_named(\"front_door\")   by its document id",
        "",
        "on_map_loaded(level) runs after each build and",
        "on_map_unloaded(level) after each removal. spawn_point()",
        "follows the live map, so a scene that declares a level needs",
        "no override of its own. A legacy .map3d that holds only",
        "geometry still loads: no nodes, no spawn, collision \"mesh\".",
        "",
        "In the editor maps/ is a Project View folder and an Assets",
        "rail row whose cards are drawn from the file. New 3D Map...",
        "and New 2D Map... start one; a map opens in the Model tab,",
        "where the Objects rail carves its parts; a scene document has",
        "a map pick, and right-clicking a map plays it alone.",
    ]},
    {"key": "guide:objects", "title": "Objects", "lines": [
        "A GameObject (engine.objects) is a placeable thing a scene owns.",
        "Three kinds match the three scenes: Object3D (a 3D prop), Object2D",
        "(a sprite quad) and UIObject (a clickable widget). The scene owns",
        "the lifecycle: build() once for geometry, update(dt) every frame,",
        "dispose() when it leaves. Common attributes: pos, tag, and the",
        "self.t clock that already counts elapsed time.",
        "",
        "Geometry: self.add(MeshData,...) merges into the scene batch",
        "(static, never removed); self.dynamic(...) is a DynamicMesh you",
        "reshape each frame; Object3D also has model_object() and light().",
        "dynamic/model/light are released for you in dispose().",
        "",
        "Any of them can be made less solid: `ent.set_opacity(0.35)` thins",
        "a whole object and its children, a `ModelObject` fades itself, and",
        "the number rides on the vertices so nothing is rebuilt.",
        "",
        "Objects can spawn others (self.spawn) or copy themselves",
        "(self.clone). A clone is a fresh instance that re-runs build();",
        "clone_attrs lists which attributes are copied. Track the tree",
        "with is_clone, clone_of, root, depth and lineage.",
        "",
        "A look can ride on one object: ent.set_shader(name) wears a",
        "`uv` shader (its own live mesh runs it) or a `texture` one (its",
        "sheet is baked once), resolved through the project's shaders/;",
        "None clears it. scene.add/dynamic/place_model take the same",
        "`shader=` and a placed node keeps it through a drag - it is one",
        "of scenedoc.LOOK_KEYS beside pos, yaw, texture and the rest.",
    ]},
    {"key": "guide:nodes", "title": "Nodes & The Tree", "lines": [
        "A scene is a tree, Godot-style: any object can hold others with",
        "add_child()/set_parent(), and a node keeps the offset it was",
        "placed at, so it rides its parent's move, turn and scale. Read",
        "the branch back with parent, children, descendants(), ancestors()",
        "and tree_path() (`Crate#0/Collision3D#0`).",
        "",
        "engine.components holds the nodes that need no script at all - a",
        "document naming one of these types just works:",
        "",
        "  Model3D      a model file hung on a parent (or stamped at it)",
        "  Sprite2D     a .model2d rig, part quads and keyframes included",
        "  Collision3D  a solid box / sphere / capsule the scene stops at",
        "  Hitbox3D     the same shape, non-solid: it only reports entries",
        "  Collision2D / Hitbox2D   the flat pair, as rectangles",
        "  LightNode3D / LightNode2D  a light that moves with its parent",
        "  Map3D / Map2D  one maps/ level - its parts, the nodes it",
        "                 places, and its own collision mode",
        "",
        "A player is a body: Player3D sweeps its own move through",
        "scene.move_body(pos, delta, half, group), so a Collision3D placed",
        "anywhere in the scene is a wall with no code written, and",
        "scene.hits_at(point) reports the Hitbox3D nodes covering a spot.",
        "",
        "What a document may set on a node is listed in its doc_knobs;",
        "those arrive as `knobs` before build(), which is how a collision's",
        "shape, size, group and offset are edited from the tree view.",
        "scenedoc.NODE_TYPES is the one table the Add Node picker, the",
        "file extension and the loader's class lookup all read.",
        "",
        "An object document can own children too, in a `nodes` list beside",
        "its knobs, so a prefab's collision and its Text3D label show",
        "nested under every placement. scenedoc.walk(doc) yields the branch",
        "and the editor draws it twice over: as the Scene tab's placed-node",
        "tree and as the Project View's scene -> node -> child rows, which",
        "select the same node when clicked.",
    ]},
    {"key": "guide:player", "title": "Player & Input", "lines": [
        "Input (engine.input) is action-based: bind keys once, then ask",
        "for the action by name. pressed() is the edge, down() the held",
        "state, axis()/move_axis() a -1..1 value, mouse_rel() the",
        "captured look delta and grabbed() the mouse-lock state. A",
        "binding name can be a key, a mouse button, a wheel notch or a",
        "pad control - see Bindings & Gamepad.",
        "",
        "The player is an object you spawn, in two flavours",
        "(engine.player): Player3D is a Godot-style first-person",
        "controller - it polls Input itself, owns its pos/yaw/pitch and",
        "publishes them onto the camera it drives - and Player2D is a",
        "pixel-plane sprite that steers with the same actions, keeps the",
        "ortho view centred on itself and wheel-zooms. Spawning a class",
        "flagged is_player attaches it; scene.attach_player(ent) does",
        "it by hand, so any object - yours included - can BE the",
        "player: give it eyes with ent.give_camera() and drive it",
        "yourself. 3D knobs: movement \"walk\"/\"fly\", eye_height,",
        "world_radius, aim_damping, fov; Player3D.first_person=False",
        "plus give_camera(follow=True, offset=..., damping=...) turns",
        "it into a chase cam. Scenes that never spawn a player keep",
        "the legacy path where the engine drives camera and movement",
        "from Scene3D knobs (camera, move_speed, world_radius, ...).",
        "`nudge(dx, dy)` feeds a look delta in from somewhere other",
        "than the grabbed mouse (the editor preview).",
    ]},
    {"key": "guide:input", "title": "Bindings & Gamepad", "lines": [
        "A binding is one *token*, spelled the same way in code, in",
        "config.json, in a project's input.map.json and on the Settings",
        "page:",
        "",
        "  w  up  space  f1      a key name (a pygame constant works too)",
        "  mouse:left  mouse:2   a mouse button (1 left, 3 right, 4/5 X)",
        "  wheel:up  wheel:down  one notch of the wheel",
        "  joy0:button0          a gamepad button, by pad index",
        "  joy0:axis+1           a gamepad axis, towards its + end",
        "",
        "Names rather than key codes, so a keymap typed on one keyboard",
        "still reads on another. Input.parse_binding takes a token,",
        "binding_text writes it back, and anything unreadable is dropped",
        "instead of guessed at, so a typo leaves the default in place.",
        "",
        "    game.input.bind('jump', 'space', 'joy0:button0')",
        "    game.input.down('jump')  pressed()  released()",
        "    game.input.bind_map({'jump': ['space']})    a whole map",
        "    game.input.bindings_of('jump')              the names",
        "    game.input.bound_by('mouse:right')          who owns it",
        "    game.input.conflicts()                      shared tokens",
        "",
        "A wheel notch is a click: it holds for the frame it arrived in",
        "and is gone in the next, so an action bound to it never sticks",
        "on. A stick past the deadzone presses and returning to centre",
        "releases, so an axis action needs no polling. The parts no",
        "binding can express stay analog: stick() for the left stick,",
        "trigger() for a shoulder, and rescan() picks up a pad plugged",
        "in after launch (JOYDEVICEADDED does it too).",
        "",
        "Four layers write the keymap, each over the last:",
        "",
        "  1. Input.bind_defaults()    the WASD-arrows set",
        "  2. config input.* keys      the Settings page",
        "  3. project.input_map()      input.map.json or the manifest",
        "  4. scene.actions            a scene's own, bound on load",
        "",
        "So a project can rebind forward and a scene can add a spell",
        "without either touching the other's code:",
        "",
        "  class Main(fe.Scene3D):",
        "      actions = {'cast': ['mouse:right', 'joy0:button2']}",
        "",
        "      def setup(self):",
        "          self.bind('wipe', 'wheel:down')     same vocabulary",
        "",
        "Two actions on one control is legal but usually a mistake, so",
        "Game prints every conflict its input.conflicts() finds when a",
        "scene loads, and the Settings page marks a clashing binding in",
        "a warn colour and names the key it shares it with.",
    ]},
    {"key": "guide:model", "title": "Models & Meshes", "lines": [
        "Three ways geometry reaches the screen:",
        "",
        "  .model3d files plain-text vertex/face meshes edited in the Model",
        "                 tab (engine.model.Model). Loaded by stem; a scene",
        "                 draws one through a Model3D node, an ModelObject",
        "                 or add().",
        "  .map3d    files a whole level in maps/: that same schema",
        "                 plus the nodes it places, a spawn point and a",
        "                 collision mode - `\"mesh\"` sweeps its real",
        "                 faces, so you walk into a wall and up a ramp.",
        "  .map2d files its flat twin: the same keys drawn in world",
        "                 pixels, filing one solid rect per part.",
        "  .model2d files a flat rig: cutout parts on a sprite sheet plus",
        "                 keyframe tracks, played by a Sprite2D node.",
        "  meshes.py      runtime builders - box, cylinder, cone, plane,",
        "                 tile_plane, billboards, face_auto - that emit a",
        "                 MeshData (pos, normal, uv, colour) ready to add.",
        "",
        "The renderer keys MeshData by texture/blend and merges the static",
        "ones into a few big batches, so a whole level draws in handfuls",
        "of calls. DynamicMesh reshapes a per-frame buffer live (flames,",
        "flags). proctex synthesises textures from noise at runtime when",
        "you would rather not ship an image file.",
        "",
        "A file can hold several named objects - floor, walls, roof -",
        "each owning some faces and carrying its own texture, paint",
        "sheet, uv2 and lightmap. A file with no `objects` key is one",
        "implicit object wearing the model's name, so old files load",
        "unchanged.",
        "",
        "A model can carry a second uv (`uv2`), unwrapped on demand",
        "by engine.unwrap. Two features use it: a UV Painted sheet",
        "the Model tab's third mode writes to a per-object PNG, and",
        "a lightmap a `bake`-flagged light freezes into a PNG - one",
        "per model, or per object once there are - the built game",
        "samples with no shader cost.",
    ]},
    {"key": "guide:render", "title": "Camera & Rendering", "lines": [
        "engine.camera holds the rig the renderer, the editor and games",
        "all look through: a Camera with eye/yaw/pitch plus fov, near,",
        "far, roll and viewport. Yaw 0 looks down +Z, positive pitch",
        "looks up, positive roll lifts the right of the horizon. wish()",
        "turns WASD into a world direction and OrbitCamera is the model",
        "editor's turntable.",
        "",
        "Game and the editor preview mix in CameraHost, so `game.eye`",
        "still works while a real Camera sits behind it. Once a frame",
        "the loop copies the scene's knobs (fov, near, far, roll,",
        "viewport) onto the camera and ticks its effects:",
        "",
        "    scene.shake(1.0, 0.4)          # 3D rattle, fades itself out",
        "    scene.follow(self.player)      # damped chase, every frame",
        "    scene.look_at(target, 6.0)     # aim, eased when damping > 0",
        "    scene.view.roll = 0.15         # the Camera itself",
        "",
        "A scene holds any number of cameras: add_camera(name=...) (or",
        "any object's give_camera()) registers one, and",
        "scene.set_active_camera(name) cuts the render to it - swap",
        "angles at runtime, park the unused ones (they keep ticking",
        "their shake) and set_active_camera(None) hands the view back",
        "to the default the player drives.",
        "",
        "Effects never rewrite the transform: eye/yaw/pitch stay what",
        "you set and view_eye()/view_roll() are the numbers actually",
        "rendered, so an impact can rattle the view without moving the",
        "player. Player.aim_damping smooths the mouse the same way.",
        "",
        "The render scale (project.flig's render.scale) trades",
        "resolution for large pixels; the renderer draws offscreen and",
        "blits into the window, letterboxing when a scene asks for a",
        "smaller viewport (a 0..1 or pixel rect), which is also how",
        "split screen is made. Materials",
        "carry colour/tint, texture, alpha and an emissive flag; how a",
        "project's textures are sampled (filter, wrap, mipmaps) comes",
        "from assets.json, along with the metre size that lets a sheet",
        "tile across a whole wall instead of stretching over it.",
        "",
        "The old built-in full-screen grades are gone; a look is now a",
        "`screen` shader the project owns. A scene names a chain in",
        "`post` (or set_post(*names)), and the loop resolves it to",
        "compiled passes through shaders.resolve(project, names) and arms",
        "them on the renderer, which runs them in order ping-ponging two",
        "scratch targets. A name that is not a screen shader is logged and",
        "skipped; scene.set_shader_knob(name, knob, value) retunes one",
        "uniform per frame. See the Shaders guide for the three modes.",
    ]},
    {"key": "guide:shaders", "title": "Shaders", "lines": [
        "A shader is one look a project owns as a file: a",
        "shaders/<name>.shader document (format, name, mode, script,",
        "knobs) paired with the fe.Shader class in scripts/shaders/. The",
        "built-in grades and CPU washes are gone - the same stock looks",
        "ship as templates in engine.templates.SHADERS.",
        "",
        "Three modes decide where a look runs:",
        "",
        "  screen   one full-frame pass after the scene drew; named in a",
        "           scene's `post`; reads the frame as g.color",
        "  uv       per fragment on one object's own live mesh; it is",
        "           never welded into a static batch, so it can animate",
        "  texture  the object's sheet rendered once into a new sheet",
        "",
        "The maths is ordinary-looking Python against a recorder called",
        "`g`. frag(self, g) runs once at compile time and only records",
        "GLSL text - no Python per pixel. Knobs and the built-in clock",
        "become uniforms (a knob reads as self.<name>), so a look retunes",
        "per frame without recompiling. g reads uv/pixel/size/time/seed/",
        "color/alpha (and world/normal/view in uv mode) and offers tex/",
        "noise/mix/ramp/hue/wmuv/smoothstep/clamp and the plain maths;",
        "the finished colour is written to g.out.",
        "",
        "  scene.post = ('scanlines',)         a screen chain",
        "  scene.set_post('grey', 'vignette')",
        "  scene.set_shader_knob('vignette', 'amount', 0.4)",
        "  ent.set_shader('uvscroll')           uv or texture on one mesh",
        "  scene.add(mesh, shader='tintpulse')",
        "",
        "Compile failure is never fatal: a bad shader logs the GL error to",
        "the Output panel and the pass or object is skipped, so a mesh",
        "draws with its plain sheet and nothing white-screens. A uv shader",
        "asked of batched or placed geometry is baked as texture instead,",
        "and the caller is told.",
        "",
        "In the editor, New Shader (the shaders/ folder's +) writes both",
        "files from a chosen template; a .shader opens as JSON in the Code",
        "tab and its .py in Code or Blocks, where a `shader` drawer offers",
        "the g.* calls and the frag hook. The whole set is watched, so any",
        "edit hot-reloads.",
    ]},
    {"key": "guide:ui", "title": "UI & HUD", "lines": [
        "engine.ui draws the 2D layer that sits on top of the 3D frame:",
        "text (left/centre/right), translucent panels, value bars,",
        "crosshairs, '[E] pick up' prompts, key-prompt hints, simple",
        "vertical menus, subtitles, dim overlays for pause screens and",
        "standalone keycaps for tutorials.",
        "",
        "Draw them from scene.draw(surface, dt). The XP widget set in",
        "engine.xp is the same palette the editor uses, so game UI and IDE",
        "chrome stay visually identical.",
    ]},
    {"key": "guide:audio", "title": "Audio", "lines": [
        "engine.audio.Audio opens the mixer once and keeps a name->sound",
        "bank, so you play by stem: project audio/*.wav are loaded for you",
        "(at the gain assets.json gives them) and a scene calls its",
        "play/sfx helpers by name. When a project has no files,",
        "build_starter_kit()/synth() generate tones, sweeps and",
        "noise on the fly, so pickup/done/etc. always work.",
    ]},
    {"key": "guide:save", "title": "Save, Paths & Theme", "lines": [
        "engine.save.SaveStore keeps one JSON slot (default",
        "saves/autosave.json in the project): read self.data, mutate it,",
        "call save(). engine.paths resolves the three roots - the read-only",
        "bundle, the folder the game launched from, and a per-user scratch",
        "directory for saves and settings - and knows whether it is running",
        "from source or frozen inside a build. Scene hooks on_save(save)/",
        "on_load(save) are called around a slot write/read, and Game."
        "save_game()/load_game() own the file.",
    ]},
    {"key": "guide:config", "title": "Config & Settings", "lines": [
        "engine.config is one flat dotted key space declared in SCHEMA:",
        "editor.*, runtime.*, input.*, build.*, docs.*. Values merge from",
        "defaults < portable config.json < user config.json < project",
        "< EMOTION_CONFIG_* env < pinned CLI, and only the keys that",
        "differ from a default are ever written.",
        "",
        "    config.get(\"runtime.fps_cap\")     read the merged value",
        "    config.set(\"editor.theme\", \"light\")   stage a change",
        "    config.save()                     write the user layer",
        "    config.bind_defaults(game.input)  apply the keymap",
        "",
        "The game window reads fps_cap, vsync, render scale, volumes,",
        "mouse sensitivity and every key binding from here, so a project",
        "changes its feel without code.",
        "",
        "Ctrl+, opens the Settings tab - one page per group, one control",
        "per key: a switch, a cycling choice, a slider or a binding",
        "capture that takes a key, a mouse button, a wheel notch or a pad",
        "control. A change reaches the running editor as it lands. Save",
        "writes the user layer, Revert re-reads the files, Reset Group",
        "clears a page, right-click resets one key, and Copy to Project",
        "stores the runtime/input keys inside project.flig.",
    ]},
    {"key": "guide:build", "title": "Building a Release", "lines": [
        "The Build tab (and `python -m emoeng build`) drive",
        "engine.build.BuildConfig: a declarative option table of PyInstaller",
        "switches. It stages the package and bundled projects, writes the",
        "launcher entry script, then runs PyInstaller to produce a one-file",
        "or one-folder bundle. Open Dist reveals the output; Run launches",
        "the built exe. Frozen builds still find their projects through",
        "engine.paths, so a released game loads exactly like a source one.",
        "",
        "Trimming (engine.prune) is what makes a game bundle small: it",
        "reads the project's own imports, ships that one project's data,",
        "drops the IDE modules and codecs nothing asks for, and prints the",
        "exclusion list with a reason for each. --full builds the editor",
        "app instead, where every project is wanted.",
        "",
        "When a project has any `bake`-flagged light, the build's",
        "`post_stage` hook runs `Project.bake_for_build(plan)`: it",
        "writes `textures/{name}-lm.png` for each affected model,",
        "points the staged `.model3d`'s `lightmap` at it, and drops",
        "the bake nodes from the staged scene docs. Only the staged",
        "copy is touched, so the source project keeps its lights on",
        "for the next bake pass.",
    ]},
    {"key": "guide:editor", "title": "The Editor", "lines": [
        "The IDE is one window of tabs - Scene, Code, Blocks, Document,",
        "Model, Media, Settings, Build, Docs - over a left dock and an",
        "Output panel at the bottom. F5 runs the project; Ctrl+S saves the",
        "open file; Ctrl+R hot-reloads whatever changed under scenes/,",
        "objects/, shaders/ or scripts/.",
        "",
        "The Project View and the Scene list are real node trees, not just",
        "file rows: a scene expands into its placed nodes and each node",
        "into its children, and an object document expands into its own",
        "`nodes`. Clicking a node row selects it in the Scene tab; the two",
        "trees show the one structure. Folder rows carry a + that opens",
        "the matching create dialog.",
        "",
        "Creating is templated. New Project picks one of seven starters",
        "in four groups - 3D, 2D, UI and Empty; New Shader picks a",
        "stock look and writes both the .shader and its script. Slots",
        "that name an asset - a texture, model, shader, sound, scene or",
        "map - open a picker in the Code, Blocks and shelf views that",
        "lists the project's files first, then the engine's built-ins,",
        "narrowing as you type.",
        "",
        "The Blocks tab reads a .py as a graph and writes it back; a",
        "shader script gets a `shader` drawer of g.* rows and the frag",
        "hook. The Output panel logs project, document, scene-build,",
        "shader-compile and hot-reload events, and its Copy button puts",
        "the lines (without time stamps) on the clipboard, Clear empties",
        "it; widgets.OutputLog.text() and .count back the same view.",
        "",
        "The Model tab has three modes: Edit for geometry, Texture to",
        "tag each face with a sheet or a colour, and UV Paint for a",
        "layered 2D canvas over the unwrapped uv2 atlas - all three",
        "target the object picked on the objects rail when the file",
        "has parts. Shift extends any selection, a vertex gizmo drags",
        "along a world axis, Merge folds parts whose bounds meet, and",
        "a .map3d or .map2d opens exactly like a .model3d - New 3D",
        "Map... / New 2D Map... write one, and Save hot-reloads the",
        "preview behind you.",
    ]},
]

GUIDES_BY_KEY = {g["key"]: g for g in GUIDES}


# lazy singleton
_CACHE = {}
_TIP_CACHE = {}


def get():
    """The shared Docs catalog, built on first use."""
    doc = _CACHE.get("docs")
    if doc is None:
        doc = Docs()
        _CACHE["docs"] = doc
    return doc


def reload():
    """Rebuild the catalog (after engine files change) and drop hints."""
    _CACHE.clear()
    _TIP_CACHE.clear()
    return get()
