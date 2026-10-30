"""Blocks: read a .py as blocks and write it back."""

import ast
import io
import itertools
import tokenize

from . import api

STACK = "stack"          # a command: something can follow it
CAP = "cap"              # ends a stack: return, break, continue, raise
BRANCH = "branch"        # wraps one or more nested stacks
HAT = "hat"              # an engine hook: nothing belongs above it
RAW = "raw"              # verbatim Python the model does not structure

# drawers the palette files under, in tab order
CATEGORIES = ("events", "trigger", "scene", "object", "entity", "light",
              "audio", "ui", "shader", "input", "save", "control", "data",
              "functions", "modules", "code")

# what a block's nested stack means when it is empty
REQUIRED = "required"    # must hold something: renders `pass`
OPTIONAL = "optional"    # disappears with its keyword when empty
CHAIN = "chain"          # `elif` brings its own keyword, at this level
SAME = "same"            # sits beside its parent: the `except` clauses

# slot kinds: how the tab edits and `check()` reads
SLOT_VALUE = "value"     # one expression
SLOT_TARGET = "target"   # an assignment or loop target
SLOT_LIST = "list"       # comma separated names
SLOT_NAME = "name"       # a single identifier
SLOT_TEXT = "text"       # free words (a keyword, an operator)
SLOT_CODE = "code"       # free Python text

# slot name to contents; unlisted slots are free text
SLOT_KIND = {
    "test": SLOT_VALUE, "value": SLOT_VALUE, "seq": SLOT_VALUE,
    "items": SLOT_VALUE, "expr": SLOT_VALUE, "types": SLOT_VALUE,
    "cause": SLOT_VALUE, "message": SLOT_VALUE, "bases": SLOT_LIST,
    "target": SLOT_TARGET, "targets": SLOT_TARGET, "names": SLOT_LIST,
    "args": SLOT_LIST, "name": SLOT_NAME, "type": SLOT_NAME,
    "op": SLOT_TEXT, "word": SLOT_TEXT, "src": SLOT_TEXT,
    "decorators": SLOT_CODE, "code": SLOT_CODE,
}

# engine-called methods; a `def` of one is an event
HOOKS = ("setup", "build", "update", "overlay", "draw", "handle_event",
         "on_enter", "on_exit", "on_timeout", "on_save", "on_load",
         "on_map_loaded", "on_map_unloaded", "on_trigger", "status", "place",
         "spawn_point", "ground_height", "interact", "use", "trigger",
         "collide", "dispose", "attach", "set", "set_camera", "clone_kwargs",
         "poll_look", "poll_move", "apply_look", "apply_move",
         "publish_camera", "teleport", "face", "look_at", "forward",
         "is_moving", "look", "move", "frag", "__init__", "__call__",
         "__str__", "__repr__", "__enter__", "__exit__")

# AugAssign operator -> the two characters that spell it
OPS = {"Add": "+", "Sub": "-", "Mult": "*", "Div": "/", "Mod": "%",
       "Pow": "**", "FloorDiv": "//", "LShift": "<<", "RShift": ">>",
       "BitOr": "|", "BitXor": "^", "BitAnd": "&", "MatMult": "@"}

# the keyword a block's `word` slot may hold
WORDS = {"if": ("if", "elif"), "each": ("for", "async for"),
         "guard": ("with", "async with"), "def": ("def", "async def"),
         "global": ("global", "nonlocal"),
         "grab": ("True", "False"),
         # the light shapes add_light() builds, 3D and 2D together
         "lamp": ("point", "spot", "sun", "tube", "radial", "cone",
                  "rect", "strip", "ring", "poly", "world")}


def _f(block, name):
    """One slot's words, trimmed; an empty slot stays empty."""
    return str(block.fields.get(name, "")).strip()


def _optional_slot(block, name, glue=" "):
    """A space and value when the slot is filled."""
    text = _f(block, name)
    return f"{glue}{text}" if text else ""


def _mk_set(block):
    target = _f(block, "target")
    ann = _f(block, "type")
    value = _f(block, "value")
    head = f"{target}: {ann}" if ann else target
    return f"{head} = {value}" if value else head


def _mk_bump(block):
    return f"{_f(block, 'target')} {_f(block, 'op') or '+='} " \
           f"{_f(block, 'value')}"


def _mk_raise(block):
    text = f"raise {_f(block, 'types')}".rstrip()
    cause = _f(block, "cause")
    return f"{text} from {cause}" if cause else text


def _mk_assert(block):
    return f"assert {_f(block, 'test')}" + _optional_slot(block, "message",
                                                          ", ")


def _mk_except(block):
    text = "except" + _optional_slot(block, "types")
    return text + _optional_slot(block, "name", " as ") + ":"


def _mk_def(block):
    word = _f(block, "word") or "def"
    text = f"{word} {_f(block, 'name')}({_f(block, 'args')})"
    return text + _optional_slot(block, "type", " -> ") + ":"


def _mk_class(block):
    return f"class {_f(block, 'name')}({_f(block, 'bases')}):"


def _mk_if(block):
    return f"{_f(block, 'word') or 'if'} {_f(block, 'test')}:"


def _mk_each(block):
    return f"{_f(block, 'word') or 'for'} {_f(block, 'target')} in " \
           f"{_f(block, 'seq')}:"


def _mk_guard(block):
    return f"{_f(block, 'word') or 'with'} {_f(block, 'items')}:"


def _one(text):
    """A builder for blocks that always spell the same."""
    return lambda block: text


def _mk_call(block):
    """`name(args)`; an empty argument slot calls the function bare."""
    return f"{_f(block, 'fn')}({_f(block, 'args')})"


def _mk_method(block):
    """`who.name(args)`: one object's function run from here."""
    return f"{_f(block, 'who')}.{_f(block, 'fn')}({_f(block, 'args')})"


def _colon(template):
    """A builder for compound headers ending in a colon."""
    def make(block):
        head = template(block).strip()
        return head if head.endswith(":") else f"{head}:"
    return make


def _head_dedent(text):
    """Lift a block's first column off its lines."""
    lines = text.split("\n")
    head = lines[0] or ""
    base = head[:len(head) - len(head.lstrip())]
    if not base:
        return text
    return "\n".join(line[len(base):] if line.startswith(base)
                     else line.lstrip() for line in lines)


class Spec:
    """How a block kind reads, lives and holds."""

    __slots__ = ("kind", "label", "category", "shape", "slots", "bodies",
                 "make", "doc", "node", "kinds", "defaults")

    def __init__(self, kind, label, category, shape, slots=(), bodies=(),
                 make=None, doc="", node="", kinds=(), defaults=None):
        self.kind = kind
        self.label = label                # `%slot%` marks a hole in the words
        self.category = category
        self.shape = shape
        self.slots = tuple(slots)         # (name, placeholder) the label uses
        self.bodies = tuple(bodies)       # (name, keyword, mode)
        self.make = make or _one(kind)
        self.doc = doc                    # what the drawer says about it
        self.node = node                  # the title bar; blank: the label
        self.kinds = tuple(kinds)         # the files it runs in; empty: all
        self.defaults = defaults          # the words it is dropped with

    @property
    def compound(self):
        return bool(self.bodies)

    def holes(self):
        """The label split into ('text', words) and ('hole', slot) runs."""
        return _template(self.label)

    def title(self, fields=None):
        """The short name a node's title bar shows."""
        fields = fields or {}
        if self.node:
            out = []
            for kind, payload in _template(self.node):
                if kind == "text":
                    out.append(payload)
                else:
                    shown = str(fields.get(payload) or "").strip()
                    out.append(shown or self.placeholder(payload))
            words = " ".join(" ".join(out).split())
            return words[:1].upper() + words[1:]
        for kind, payload in self.holes():
            words = " ".join(str(payload).split())
            if kind == "text" and words:
                return words[:1].upper() + words[1:]
        return self.kind.title()

    def placeholder(self, name):
        """What an empty slot shows and a block starts with."""
        for slot, words in self.slots:
            if slot == name:
                return words
        return ""

    def words_for(self, name):
        """The choices a `word` slot offers, when it has them."""
        return WORDS.get(self.kind, ())

    def __repr__(self):
        return f"<Spec {self.kind} {self.shape}>"


def _template(text):
    """A label split into text and hole parts."""
    out = []
    rest = str(text)
    while "%" in rest:
        before, _, rest = rest.partition("%")
        name, _, rest = rest.partition("%")
        if before:
            out.append(("text", before))
        out.append(("hole", name))
    if rest:
        out.append(("text", rest))
    return out


SPEC = {}


# a palette block's defaults; all are valid Python
DEFAULTS = {
    "do": {"expr": "None"},
    "set": {"target": "name", "value": "None"},
    "bump": {"target": "name", "op": "+=", "value": "1"},
    "forget": {"targets": "name"},
    "global": {"word": "global", "names": "name"},
    "import": {"names": "emoeng"},
    "from": {"src": "emoeng.engine", "names": "name"},
    "if": {"test": "True", "word": "if"},
    "each": {"target": "item", "seq": "[]", "word": "for"},
    "while": {"test": "True"},
    "guard": {"items": "None", "word": "with"},
    "raise": {"types": "RuntimeError"},
    "assert": {"test": "True"},
    "def": {"word": "def", "name": "action", "args": "self"},
    "class": {"name": "Thing", "bases": "object"},
    "note": {"code": "# note"},
    "raw": {"code": "pass"},
    # object
    "remove": {"who": "None"},
    "move": {"who": "self.player", "pos": "(0.0, 0.0, 0.0)"},
    "face": {"who": "self.player", "yaw": "0.0"},
    "clone": {"who": "self.player", "pos": "None"},
    # entity: the who-forms never name self, because an entity's own block
    # writes `self.<call>` and reads back as that block, not as this one
    "set_health": {"who": "self.player", "value": "100.0"},
    "heal": {"who": "self.player", "amount": "10.0"},
    "damage": {"who": "self.player", "amount": "10.0", "source": "None"},
    "kill": {"who": "self.player", "source": "None"},
    "leave": {"who": "self.player"},
    "set_ai": {"who": "self.player", "ai_type": '"follow"',
               "config": "{}"},
    "set_ai_target": {"who": "self.player",
                      "target": "self.scene.player"},
    "set_team": {"who": "self.player", "team": '"enemy"'},
    "set_aggro_range": {"who": "self.player", "distance": "15.0",
                        "deaggro": "None"},
    "set_attack": {"who": "self.player", "range": "2.0", "dmg": "15.0",
                   "cd": "1.5"},
    "set_move_speed": {"who": "self.player", "walk": "3.0", "run": "8.0"},
    "set_hitbox": {"who": "self.player", "shape": '"box"',
                   "params": "(0.5, 1.0, 0.5)"},
    "set_hitbox2d": {"who": "self.player", "shape": '"rect"',
                     "params": "(32.0, 48.0)"},
    # light
    "lighton": {"who": "lamp"},
    "lightoff": {"who": "lamp"},
    "flash": {"who": "lamp", "amount": "2.0", "seconds": "0.14"},
    "fade": {"who": "lamp", "amount": "0.0", "seconds": "1.0"},
    # input
    "held": {"action": '"forward"'},
    "pressed": {"action": '"use"'},
    "released": {"action": '"use"'},
    "bind": {"action": '"dash"', "key": '"lshift"'},
    "unbind": {"action": '"dash"'},
    "grab": {"word": "True"},
    # trigger
    "broadcast": {"name": '"door"', "value": ""},
    "listen": {"name": '"door"', "who": "self"},
    "unlisten": {"name": '"door"', "who": "self"},
    # save
    "remember": {"key": '"seen_intro"', "value": "True"},
    "count": {"key": '"solved"', "amount": "1"},
    "mark": {"key": '"seen_intro"'},
    "unmark": {"key": '"seen_intro"'},
    # functions that run other functions
    "call": {"fn": "action", "args": ""},
    "callon": {"who": "self", "fn": "action", "args": ""},
    "after": {"seconds": "1.0", "fn": "action"},
    "every": {"seconds": "1.0", "fn": "action"},
}


def _s(kind, label, category, shape, slots=(), bodies=(), make=None, doc="",
       node="", kinds=()):
    spec = Spec(kind, label, category, shape, slots, bodies, make, doc, node,
                kinds)
    SPEC[kind] = spec
    return spec


# commands
_s("do", "run %expr%", "data", STACK, (("expr", "expression"),),
   make=lambda b: _f(b, "expr"),
   doc="Any statement: a call, an attribute write, anything that runs.")
_s("set", "set %target% to %value%", "data", STACK,
   (("target", "name"), ("value", "nothing"), ("type", "")),
   make=_mk_set,
   doc="Give a name a value. Leave type empty unless the file annotates.")
_s("bump", "change %target% by %op% %value%", "data", STACK,
   (("target", "name"), ("op", "+="), ("value", "1")),
   make=_mk_bump,
   doc="Update a value in place: +=, -=, *=, //=, |= and the rest.")
_s("forget", "forget %targets%", "data", STACK, (("targets", "name"),),
   make=lambda b: f"del {_f(b, 'targets')}",
   doc="Drop a name, or an item from a dict or list.")
_s("global", "%word% %names%", "data", STACK,
   (("word", "global"), ("names", "name")),
   make=lambda b: f"{_f(b, 'word') or 'global'} {_f(b, 'names')}",
   doc="Say a name lives in the module (global) or in the outer function "
       "(nonlocal).")

# control
_s("pass", "do nothing", "control", STACK, make=_one("pass"),
   doc="A block that is deliberately empty.")
_s("if", "if %test% then", "control", BRANCH,
   (("test", "true"), ("word", "if")),
   bodies=(("then", None, REQUIRED), ("alt", "else", CHAIN)),
   make=_colon(_mk_if),
   doc="Run a stack when a test holds, with optional elif / else stacks.")
_s("each", "for each %target% in %seq%", "control", BRANCH,
   (("target", "item"), ("seq", "list"), ("word", "for")),
   bodies=(("body", None, REQUIRED), ("alt", "else", OPTIONAL)),
   make=_colon(_mk_each),
   doc="Walk anything iterable. The else stack runs when the loop finishes "
       "without a break.")
_s("while", "repeat while %test%", "control", BRANCH, (("test", "true"),),
   bodies=(("body", None, REQUIRED), ("alt", "else", OPTIONAL)),
   make=lambda b: f"while {_f(b, 'test')}:",
   doc="Loop until a test stops holding.")
_s("guard", "use %items% as a stack", "control", BRANCH,
   (("items", "resource"), ("word", "with")),
   bodies=(("body", None, REQUIRED),),
   make=_colon(_mk_guard),
   doc="Keep something open for the stack inside it: files, locks, a "
       "pushed matrix.", node="with %items%")
_s("try", "try", "control", BRANCH, (),
   bodies=(("body", None, REQUIRED), ("handlers", None, SAME),
           ("else", "else", OPTIONAL), ("final", "finally", OPTIONAL)),
   make=_one("try:"),
   doc="Run a stack and catch whatever it raises.")
_s("except", "except %types% as %name%", "control", BRANCH,
   (("types", ""), ("name", "")),
   bodies=(("body", None, REQUIRED),),
   make=_mk_except,
   doc="One catch clause; lives inside a try block.")
_s("break", "break out", "control", CAP, make=_one("break"),
   doc="Leave the loop this block sits in.")
_s("continue", "skip to next", "control", CAP, make=_one("continue"),
   doc="Start the next round of the loop.")
_s("assert", "assert %test% else %message%", "control", STACK,
   (("test", "true"), ("message", "")),
   make=_mk_assert,
   doc="A check that stops the game when it is false.")
_s("raise", "raise %types% from %cause%", "control", CAP,
   (("types", "RuntimeError"), ("cause", "")),
   make=_mk_raise,
   doc="Throw. Re-raise the current error by leaving both slots empty.")

# functions
_s("def", "when %name% is called with %args%", "functions", BRANCH,
   (("word", "def"), ("name", "name"), ("args", ""),
    ("type", ""), ("decorators", "")),
   bodies=(("body", None, REQUIRED),),
   make=_colon(_mk_def),
   doc="A function. One whose name the engine calls (setup, update) is drawn "
       "with a hat top, because nothing runs above it.",
   node="when %name% runs")
_s("class", "make a %name% that is a %bases%", "functions", BRANCH,
   (("name", "name"), ("bases", "object"), ("decorators", "")),
   bodies=(("body", None, REQUIRED),),
   make=_colon(_mk_class),
   doc="A scene, an object, or any other type of your own.",
   node="new %name%")
_s("return", "give back %value%", "functions", CAP, (("value", ""),),
   make=lambda b: "return" + _optional_slot(b, "value"),
   doc="Leave the slot empty to give back nothing.")

# running a file's own functions: the name is the slot
_s("call", "call %fn% with %args%", "functions", STACK,
   (("fn", "action"), ("args", "")),
   make=_mk_call,
   doc="Run a function by name; an empty argument slot calls it bare.",
   node="call %fn%")
_s("callon", "call %fn% on %who% with %args%", "functions", STACK,
   (("who", "self"), ("fn", "action"), ("args", "")),
   make=_mk_method,
   doc="Run one object's function from here: a component, a sibling, self.",
   node="call %fn% on %who%")
_s("after", "delay %seconds% s then call %fn%", "functions", STACK,
   (("seconds", "1.0"), ("fn", "action")),
   make=lambda b: f"self.after({_f(b, 'seconds')}, {_f(b, 'fn')})",
   doc="A one-shot timer on this scene or object: a delay, then a call.",
   node="after %seconds% s")
_s("every", "every %seconds% s call %fn%", "functions", STACK,
   (("seconds", "1.0"), ("fn", "action")),
   make=lambda b: f"self.every({_f(b, 'seconds')}, {_f(b, 'fn')})",
   doc="A repeating timer; it stops when the scene or object goes away.",
   node="every %seconds% s")

# module
_s("import", "bring in %names%", "modules", STACK,
   (("names", "module"),),
   make=lambda b: f"import {_f(b, 'names')}",
   doc="Load a module under its own name; `a.b as c` is allowed.")
_s("from", "from %src% import %names%", "modules", STACK,
   (("src", "module"), ("names", "name")),
   make=lambda b: f"from {_f(b, 'src')} import {_f(b, 'names') or '*'}",
   doc="Pull names out of a module. A leading dot finds it next to this file.",
   node="import from %src%")

# one drawer per kind; most blocks are generated from signatures

# scene: the flow between screens, and the one restart
_s("restart", "start this scene again", "scene", STACK,
   make=_one("self.game.restart_scene()"),
   doc="Tear the scene down and load it fresh, keeping the save file.")
_s("shot", "take a screenshot", "scene", STACK,
   make=_one("self.game.screenshot()"),
   doc="Write the frame into the project's screenshots folder.")

# object: moving scene parts; three reach `self.player`
WORLD_KINDS = ("scene3d", "scene2d", "object3d", "object2d", "player3d",
               "player2d",
               "model3d", "collision3d", "hitbox3d", "trigger3d",
               "marker3d", "light3d", "omnilight3d", "spotlight3d",
               "directionallight3d", "audio3d", "text3d", "timer3d",
               "particle3d",
               "sprite2d", "collision2d", "hitbox2d", "trigger2d",
               "marker2d", "light2d", "pointlight2d", "conelight2d",
               "rectlight2d", "audio2d", "text2d", "timer2d",
               "particle2d",
               "entity3d", "entity2d")
ENTITY_KINDS = ("entity3d", "entity2d", "object3d", "object2d", "player3d", "player2d")
_s("remove", "take %who% out of the scene", "object", STACK,
   (("who", "None"),),
   make=lambda b: f"self.despawn({_f(b, 'who')})",
   doc="Gone for good, with anything it spawned and its own lights.",
   node="take %who% out")
_s("move", "move %who% to %pos%", "object", STACK,
   (("who", "self.player"), ("pos", "(0.0, 0.0, 0.0)")),
   make=lambda b: f"{_f(b, 'who')}.set(pos={_f(b, 'pos')})",
   doc="Teleport an object or a model object; its turn and size stay.",
   kinds=WORLD_KINDS)
_s("face", "turn %who% to %yaw% radians", "object", STACK,
   (("who", "self.player"), ("yaw", "0.0")),
   make=lambda b: f"{_f(b, 'who')}.set(yaw={_f(b, 'yaw')})",
   doc="Set its facing outright, in radians; 0 looks along +z.",
   kinds=WORLD_KINDS)
_s("clone", "clone %who% at %pos%", "object", STACK,
   (("who", "self.player"), ("pos", "None")),
   make=lambda b: f"{_f(b, 'who')}.clone({_f(b, 'pos')})",
   doc="A live copy on the same scene, built and attached straight away.",
   kinds=WORLD_KINDS)

# entity: health, AI, hitboxes. Each block is one engine call, so a saved
# file reads back as the blocks it was built from. `who` forms tell another
# actor what to do; an actor's own blocks are the generated `self.` ones.
ACTOR_KINDS = ENTITY_KINDS + ("scene3d", "scene2d", "sceneui")
ENT3D_KINDS = ("entity3d", "object3d", "player3d", "scene3d")
ENT2D_KINDS = ("entity2d", "object2d", "player2d", "scene2d")
_s("set_health", "set %who% health to %value%", "entity", STACK,
   (("who", "self.player"), ("value", "100.0")),
   make=lambda b: f"{_f(b, 'who')}.set_health({_f(b, 'value') or '0.0'})",
   doc="How much damage it can still take. Zero ends it, exactly as the "
       "last of its health does in a fight.",
   kinds=ACTOR_KINDS, node="set %who% health")
_s("heal", "heal %who% by %amount%", "entity", STACK,
   (("who", "self.player"), ("amount", "10.0")),
   make=lambda b: f"{_f(b, 'who')}.heal({_f(b, 'amount') or '0.0'})",
   doc="Health back, up to the maximum it carries.",
   kinds=ACTOR_KINDS)
_s("damage", "damage %who% by %amount% from %source%", "entity", STACK,
   (("who", "self.player"), ("amount", "10.0"), ("source", "None")),
   make=lambda b: (f"{_f(b, 'who')}.take_damage({_f(b, 'amount') or '0.0'}, "
                   f"{_f(b, 'source') or 'None'})"),
   doc="Apply damage and run its hit or death hook. The source is the "
       "attacker, or nothing.",
   kinds=ACTOR_KINDS)
_s("kill", "kill %who% from %source%", "entity", STACK,
   (("who", "self.player"), ("source", "None")),
   make=lambda b: f"{_f(b, 'who')}.kill({_f(b, 'source') or 'None'})",
   doc="Its health to zero at once: the death hook runs, then it is gone.",
   kinds=ACTOR_KINDS, node="kill %who%")
_s("leave", "take %who% out at the end of the frame", "entity", STACK,
   (("who", "self.player"),),
   make=lambda b: f"{_f(b, 'who')}.queue_free()",
   doc="Godot's removal: it leaves when this frame's work is done, so "
       "dropping it inside a loop over children is safe.",
   kinds=ACTOR_KINDS, node="take %who% out later")
_s("set_ai", "set %who% AI to %ai_type% with %config%", "entity", STACK,
   (("who", "self.player"), ("ai_type", '"follow"'), ("config", "{}")),
   make=lambda b: (f"{_f(b, 'who')}.set_ai({_f(b, 'ai_type') or '\"none\"'}, "
                   f"{_f(b, 'config') or '{}'})"),
   doc="One of none, follow, patrol, wander, aggro. The dict carries what "
       "that needs: `waypoints`, a `wander_interval`.",
   kinds=ACTOR_KINDS, node="set %who% AI")
_s("set_ai_target", "set %who% AI target to %target%", "entity", STACK,
   (("who", "self.player"), ("target", "self.scene.player")),
   make=lambda b: (f"{_f(b, 'who')}.set_ai_target("
                   f"{_f(b, 'target') or 'None'})"),
   doc="Who it follows, chases or attacks; None until told.",
   kinds=ACTOR_KINDS, node="set AI target")
_s("set_team", "set %who% team to %team%", "entity", STACK,
   (("who", "self.player"), ("team", '"enemy"')),
   make=lambda b: f"{_f(b, 'who')}.set_team({_f(b, 'team') or '\"neutral\"'})",
   doc="player, enemy, neutral or friendly: what aggro looks at before it "
       "picks a target.",
   kinds=ACTOR_KINDS, node="set %who% team")
_s("set_aggro_range", "set %who% aggro range to %distance% and off at "
   "%deaggro%", "entity", STACK,
   (("who", "self.player"), ("distance", "15.0"), ("deaggro", "None")),
   make=lambda b: (f"{_f(b, 'who')}.set_aggro_range("
                   f"{_f(b, 'distance') or '0.0'}, "
                   f"{_f(b, 'deaggro') or 'None'})"),
   doc="How far off it takes notice. Leave the second row empty and it "
       "loses interest at twice the distance.",
   kinds=ACTOR_KINDS, node="set aggro range")
_s("set_attack", "set %who% attack: reach %range%, damage %dmg%, "
   "cooldown %cd%", "entity", STACK,
   (("who", "self.player"), ("range", "2.0"), ("dmg", "15.0"),
    ("cd", "1.5")),
   make=lambda b: (f"{_f(b, 'who')}.set_attack({_f(b, 'range') or 'None'}, "
                   f"{_f(b, 'dmg') or 'None'}, {_f(b, 'cd') or 'None'})"),
   doc="How near it must be, how hard it hits and the seconds between "
       "swings. An empty row keeps what it had.",
   kinds=ACTOR_KINDS, node="set attack")
_s("set_move_speed", "set %who% move speed to %walk% (run %run%)",
   "entity", STACK,
   (("who", "self.player"), ("walk", "3.0"), ("run", "8.0")),
   make=lambda b: (f"{_f(b, 'who')}.set_move_speed("
                   f"{_f(b, 'walk') or '0.0'}, {_f(b, 'run') or 'None'})"),
   doc="Cruising speed and chasing speed, in the world's units a second.",
   kinds=ACTOR_KINDS, node="set move speed")
_s("set_hitbox", "set %who% hitbox: %shape% %params%", "entity", STACK,
   (("who", "self.player"), ("shape", '"box"'),
    ("params", "(0.5, 1.0, 0.5)")),
   make=lambda b: (f"{_f(b, 'who')}.set_hitbox({_f(b, 'shape') or '\"box\"'}, "
                   f"{_f(b, 'params') or 'None'})"),
   doc="A box of half extents, a sphere of a radius or a capsule of a "
       "radius and a height.",
   kinds=ENT3D_KINDS, node="set hitbox")
# the flat body a 2D entity collides with
_s("set_hitbox2d", "set %who% 2D hitbox: %shape% %params%", "entity", STACK,
   (("who", "self.player"), ("shape", '"rect"'), ("params", "(32.0, 48.0)")),
   make=lambda b: (f"{_f(b, 'who')}.set_hitbox2d("
                   f"{_f(b, 'shape') or '\"rect\"'}, "
                   f"{_f(b, 'params') or 'None'})"),
   doc="A rect of (width, height) or a circle of a radius.",
   kinds=ENT2D_KINDS, node="set 2D hitbox")

# light: one drawer; the shape picks the kind
LIGHT_KINDS = ("scene3d", "scene2d", "object3d", "player3d",
               "light3d", "omnilight3d", "spotlight3d",
               "directionallight3d", "light2d", "pointlight2d",
               "conelight2d", "rectlight2d")
_s("lighton", "switch the light %who% on", "light", STACK,
   (("who", "lamp"),),
   make=lambda b: f"{_f(b, 'who')}.on()",
   doc="Back on at the energy it had before it was switched off.",
   kinds=LIGHT_KINDS)
_s("lightoff", "switch the light %who% off", "light", STACK,
   (("who", "lamp"),),
   make=lambda b: f"{_f(b, 'who')}.off()",
   doc="Dark, but still in the scene; it costs no shader slot while off.",
   kinds=LIGHT_KINDS)
_s("flash", "flash %who% by %amount% for %seconds% s", "light",
   STACK, (("who", "lamp"), ("amount", "2.0"), ("seconds", "0.14")),
   make=lambda b: (f"{_f(b, 'who')}.flash({_f(b, 'amount')}, "
                   f"{_f(b, 'seconds')})"),
   doc="One bright kick that decays back: a muzzle flash, a pickup.",
   kinds=LIGHT_KINDS)
_s("fade", "fade %who% to %amount% over %seconds% s", "light",
   STACK, (("who", "lamp"), ("amount", "0.0"), ("seconds", "1.0")),
   make=lambda b: (f"{_f(b, 'who')}.fade_to({_f(b, 'amount')}, "
                   f"{_f(b, 'seconds')})"),
   doc="Ease the energy; a fade to 0 is a lamp dying out.",
   kinds=LIGHT_KINDS)

# audio: the one-shots stop; starting sounds is generated
_s("nomusic", "stop the music", "audio", STACK,
   make=_one("self.audio.stop_music()"),
   doc="Fade the track out; sounds already playing carry on.")
_s("silence", "stop every sound", "audio", STACK,
   make=_one("self.audio.stop_all()"),
   doc="Cut every channel dead, for a hard scene change.")

# ui: the HUD overlay; rows are Hud arguments it takes
_s("crosshair", "draw the crosshair", "ui", STACK,
   make=_one("self.hud.crosshair()"),
   doc="The engine's crosshair, in the middle of the screen.")

# trigger: the scene's broadcast bus; a bound key fires a name
_s("broadcast", "broadcast %name% with %value%", "trigger", STACK,
   (("name", '"door"'), ("value", "nothing")),
   make=lambda b: (f"self.broadcast({_f(b, 'name')})"
                   if not _f(b, "value") else
                   f"self.broadcast({_f(b, 'name')}, {_f(b, 'value')})"),
   doc="Say a trigger fired. Leave the value empty to carry nothing.",
   kinds=WORLD_KINDS)
_s("listen", "listen for %name% on %who%", "trigger", STACK,
   (("name", '"door"'), ("who", "self")),
   make=lambda b: f"self.listen({_f(b, 'name')}, {_f(b, 'who') or 'self'})",
   doc="Ask one object to hear a trigger: its on_trigger runs when it lands.",
   kinds=WORLD_KINDS)
_s("unlisten", "stop listening for %name% on %who%", "trigger", STACK,
   (("name", '"door"'), ("who", "self")),
   make=lambda b: (f"self.unlisten({_f(b, 'name')})"
                   if not _f(b, "who") else
                   f"self.unlisten({_f(b, 'name')}, {_f(b, 'who')})"),
   doc="Drop one listener, or every one of that name with an empty who.",
   kinds=WORLD_KINDS)

# input: polling the keymap the game handed the scene
_s("held", "while %action% is held", "input", BRANCH,
   (("action", '"forward"'),),
   bodies=(("body", None, REQUIRED),),
   make=_colon(lambda b: f"if self.input.down({_f(b, 'action')})"),
   doc="A stack that runs every frame the action is down.")
_s("pressed", "if %action% was pressed", "input", BRANCH,
   (("action", '"use"'),),
   bodies=(("body", None, REQUIRED),),
   make=_colon(lambda b: f"if self.input.pressed({_f(b, 'action')})"),
   doc="True for the one frame the action went down.")
_s("released", "if %action% was let go", "input", BRANCH,
   (("action", '"use"'),),
   bodies=(("body", None, REQUIRED),),
   make=_colon(lambda b: f"if self.input.released({_f(b, 'action')})"),
   doc="True for the one frame the action came back up.")
_s("bind", "bind %action% to %key%", "input", STACK,
   (("action", '"dash"'), ("key", '"lshift"')),
   make=lambda b: f"self.bind({_f(b, 'action')}, {_f(b, 'key')})",
   doc="A token: a key name, mouse:left, wheel:up, joy0:button0, "
       "joy0:axis+1.", kinds=("scene3d", "scene2d", "sceneui"))
_s("unbind", "stop listening for %action%", "input", STACK,
   (("action", '"dash"'),),
   make=lambda b: f"self.input.unbind({_f(b, 'action')})",
   doc="Drop every binding of an action until it is bound again.")
_s("grab", "capture the mouse: %word%", "input", STACK,
   (("word", "True"),),
   make=lambda b: f"self.input.grab_mouse({_f(b, 'word') or 'True'})",
   doc="Click to swap. True hides the pointer for mouse-look, False "
       "gives it back.")

# save: the values that outlive a scene
_s("remember", "remember %key% as %value%", "save", STACK,
   (("key", '"seen_intro"'), ("value", "True")),
   make=lambda b: f"self.save.set({_f(b, 'key')}, {_f(b, 'value')})",
   doc="A value that survives a reload; the autosave writes it out.")
_s("count", "add %amount% to %key%", "save", STACK,
   (("key", '"solved"'), ("amount", "1")),
   make=lambda b: f"self.save.add({_f(b, 'key')}, {_f(b, 'amount')})",
   doc="A running total, made on the first call and kept from then on.")
_s("mark", "mark %key% done", "save", STACK,
   (("key", '"seen_intro"'),),
   make=lambda b: f"self.save.flag({_f(b, 'key')})",
   doc="A flag set to True; ask for it with save.has(key).")
_s("unmark", "unmark %key%", "save", STACK,
   (("key", '"seen_intro"'),),
   make=lambda b: f"self.save.unflag({_f(b, 'key')})",
   doc="Back to no flag at all - not False, gone.")
_s("savenow", "write the save now", "save", STACK,
   make=_one("self.game.save_game()"),
   doc="Save at once rather than waiting for the next autosave.")
_s("loadnow", "read the save now", "save", STACK,
   make=_one("self.game.load_game()"),
   doc="Re-read the save file; the scene's on_load runs after it.")


# anything else
_s("note", "%code%", "code", STACK, (("code", "# note"),),
   make=lambda b: _f(b, "code"),
   doc="A comment, kept exactly as it is written.")
_s("raw", "%code%", "code", RAW, (("code", "pass"),),
   make=lambda b: _f(b, "code"),
   doc="Python the block view shows but never restructures: match "
       "statements, one-line blocks, anything unusual.")


# authoring calls come from `api.CALLS` and its signatures
for _entry in api.CALLS:
    SPEC[_entry.kind] = Spec(
        _entry.kind, _entry.label, _entry.category, STACK, _entry.slots(), (),
        _entry.make, _entry.doc, _entry.node, _entry.kinds, _entry.start())


class Block:
    """One block: kind, slot words and wrapped stacks."""

    __slots__ = ("pid", "kind", "fields", "original", "good", "bodies",
                 "pre", "text", "indent", "leads", "gaps", "lineno", "end",
                 "parent", "slot", "moved", "node")

    def __init__(self, kind, fields=None, text="", indent="", pre=()):
        self.pid = next(_PIDS)
        self.kind = kind
        self.fields = dict(fields or {})
        self.original = dict(self.fields)   # the words the file was read with
        self.good = dict(self.fields)       # the last words that parsed
        self.bodies = {}
        self.pre = list(pre)              # untouched lines above this block
        self.text = text                  # this block's own source, dedented
        self.indent = indent              # the indent that source was read at
        self.leads = {}                   # `else:` style lines, verbatim
        self.gaps = {}                    # comments just before those lines
        self.lineno = 0
        self.end = 0
        self.parent = None
        self.slot = None
        self.moved = False
        self.node = None

    @property
    def spec(self):
        return SPEC.get(self.kind) or SPEC["raw"]

    @property
    def shape(self):
        """How the tab draws it: a hat or a branch."""
        if self.kind == "def":
            return HAT if _f(self, "name") in HOOKS else BRANCH
        if self.spec.compound:
            return BRANCH
        if self.kind in ("raw", "note"):
            return RAW
        return self.spec.shape

    @property
    def edited(self):
        """True once a slot holds words other than read."""
        return any(self.fields.get(name) != self.original.get(name)
                   for name in self.fields)

    def label(self):
        """The block's words with its slots filled."""
        parts = []
        for kind, payload in self.spec.holes():
            if kind == "text":
                parts.append(payload)
            elif self.fields.get(payload):
                parts.append(_f(self, payload))
            else:
                parts.append(self.spec.placeholder(payload))
        text = " ".join(parts)
        if self.kind in ("raw", "note"):
            text = " ".join(str(self.fields.get("code", "")).split("\n"))[:200]
        return " ".join(text.split()) or self.kind

    def statement(self):
        """The source line(s) this block owns, without its nested stacks."""
        if self.kind in ("raw", "note"):
            return str(self.fields.get("code", ""))
        if self.text and not self.edited:
            return self.text
        return self.spec.make(self).strip()

    def draft(self):
        """The words the slots hold right now, however half-typed."""
        if self.kind in ("raw", "note"):
            return _head_dedent(str(self.fields.get("code", "")))
        return self.spec.make(self).strip()

    def is_source(self):
        """True when the block still holds its read words."""
        return bool(self.text) and not self.edited

    def sample(self, text=None):
        """Enough code around the block to parse alone."""
        text = self.statement() if text is None else text
        if self.kind == "except":
            return f"try:\n    pass\n{text}\n    pass"
        if self.kind == "if" and _f(self, "word") == "elif":
            return f"if True:\n    pass\n{text}\n    pass"
        if self.kind == "try":
            return f"{text}\n    pass\nexcept Exception:\n    pass"
        if self.spec.compound:
            return f"{text}\n    pass"
        return text

    def check(self):
        """Why the block's words are not valid Python."""
        if self.kind == "note" or self.fields == self.good:
            return None
        text = self.draft()
        if not text.strip():
            return "nothing in the block"
        try:
            ast.parse(self.sample(text))
        except SyntaxError as exc:
            return str(exc.msg)
        except (RecursionError, ValueError) as exc:
            return str(exc)
        return None

    def set_field(self, name, value):
        """Edit a slot; returns the problem, or None."""
        self.fields[name] = value
        why = self.check()
        if why is None:
            self.good = dict(self.fields)
        return why

    def revert(self, to_file=False):
        """Drop the edits, back to the last parsed words."""
        self.fields = dict(self.original if to_file else self.good)
        if to_file:
            self.good = dict(self.fields)
        return self

    def read_word(self, name, value):
        """Record a keyword the source spells itself."""
        self.fields[name] = value
        self.original[name] = value
        self.good[name] = value
        return self

    def words(self, name):
        """The choices offered for a `word` slot, current one first."""
        choices = list(self.spec.words_for(name))
        if name == "op":
            choices = [f"{op}=" for op in OPS.values()]
        now = _f(self, name)
        if now and now not in choices:
            choices.insert(0, now)
        return choices

    def stack(self, name):
        return self.bodies.get(name) or ()

    def body_names(self):
        return [name for name, _lead, _mode in self.spec.bodies]

    def attach(self, blocks, name):
        for block in blocks:
            block.parent = self
            block.slot = name
        self.bodies[name] = list(blocks)
        return self.bodies[name]

    def all(self):
        """This block and everything it wraps, outermost first."""
        out = [self]
        for stack in self.bodies.values():
            for child in stack:
                out.extend(child.all())
        return out

    def __iter__(self):
        return iter(self.all())

    def find(self, pid):
        for block in self.all():
            if block.pid == pid:
                return block
        return None

    def mark_moved(self):
        """This block and stack no longer sit where read."""
        for block in self.all():
            block.moved = True
        return self

    def remove(self):
        """Take this block out of the stack that holds it."""
        holder = self.parent
        stack = None
        if holder is None:
            return self
        stack = holder.bodies.get(self.slot)
        if stack is not None and self in stack:
            stack.remove(self)
        self.parent = None
        self.slot = None
        return self

    def index(self):
        """The block's place in its stack, or -1."""
        holder = self.parent
        if holder is None:
            return -1
        stack = holder.bodies.get(self.slot) or ()
        return stack.index(self) if self in stack else -1

    def depth(self):
        level = 0
        holder = self.parent
        while isinstance(holder, Block):
            level += 1
            holder = holder.parent
        return level

    def pad_for(self, outer):
        """The indent this block's lines are written at."""
        return outer if self.moved else self.indent

    def shift(self, line, pad):
        """Carry a captured line from its column to `pad`."""
        if pad == self.indent or not line.strip():
            return line
        delta = len(pad) - len(self.indent)
        if delta > 0:
            return pad[:delta] + line
        lead = -delta
        if line[:lead] == self.indent[:lead] or not line[:lead].strip():
            return line[lead:]
        return line

    def own_lines(self, pad):
        lines = self.statement().split("\n")
        if self.is_source():
            return [self.shift(line, pad) for line in lines]
        out = []
        if self.kind in ("def", "class"):
            for deco in str(self.fields.get("decorators", "")).splitlines():
                words = deco.strip()
                if words:
                    out.append(pad + (words if words.startswith("@")
                                      else f"@{words}"))
        # block text measures from its first column, keeping shape
        head = lines[0] if lines else ""
        base = head[:len(head) - len(head.lstrip())]
        for index, line in enumerate(lines):
            if not line.strip():
                out.append(line)
            elif line.startswith(base):
                out.append(pad + line[len(base):])
            else:
                out.append(pad + line.lstrip())
        return out

    def lines(self, unit="    ", outer="", level=0):
        """Physical source lines, else the last parsed words."""
        if self.check():
            keep = self.fields
            self.fields = dict(self.good)
            try:
                return self._lines(unit, outer, level)
            finally:
                self.fields = keep
        return self._lines(unit, outer, level)

    def _lines(self, unit="    ", level_pad="", level=0):
        pad = self.pad_for(level_pad)
        out = [self.shift(line, pad) for line in self.pre]
        out.extend(self.own_lines(pad))
        inner = pad + unit
        for name, lead, mode in self.spec.bodies:
            stack = self.bodies.get(name) or ()
            if mode is SAME:
                child_pad, child_level = pad, level
            elif mode is CHAIN and _is_elif(stack):
                child_pad, child_level = pad, level
            else:
                child_pad, child_level = inner, level + 1
            if not stack:
                if mode is REQUIRED:
                    if lead:
                        out.append(pad + f"{lead}:")
                    out.append(child_pad + "pass")
                continue
            for line in self.gaps.get(name) or ():
                out.append(self.shift(line, pad))
            if lead and not (mode is CHAIN and _is_elif(stack)):
                stored = self.leads.get(name)
                out.append(pad + (stored if stored else f"{lead}:"))
            for child in stack:
                out.extend(child.lines(unit, child_pad, child_level))
        return out

    lines.__defaults__ = ("    ", "", 0)

    def source(self, unit="    "):
        """This block alone as Python, for tooltips and diffs."""
        return "\n".join(self.lines(unit, "", 0))

    def __repr__(self):
        return f"<Block {self.kind} {self.label()[:48]!r}>"


_PIDS = itertools.count(1)


def _is_elif(stack):
    """True when a stack starts with `elif`, not `else:`."""
    return bool(stack) and len(stack) == 1 and stack[0].kind == "if" and \
        stack[0].original.get("word") == "elif"


def new_block(kind, fields=None, pre=()):
    """A palette block: defaults filled, stacks empty."""
    entry = SPEC.get(kind) or SPEC["raw"]
    # generated blocks carry required rows; hand-written use DEFAULTS
    out = dict(DEFAULTS.get(kind, {}))
    out.update(entry.defaults or {})
    for name in dict(fields or {}):
        out[name] = fields[name]
    block = Block(kind, out, text="", indent="", pre=list(pre or ()))
    block.moved = True
    for name, _lead, _mode in entry.bodies:
        block.bodies[name] = []
    if kind == "try":
        # a `try` needs a catch, so both drop together
        block.attach([new_block("except", {"types": "Exception"})],
                     "handlers")
    return block


def spec(kind):
    return SPEC.get(kind)


class Module:
    """A whole file as blocks, ready to write back."""

    def __init__(self, blocks=(), source="", unit="    ", newline="\n",
                 final=True, tail=()):
        self.blocks = list(blocks)
        self.source = source
        self.unit = unit
        self.newline = newline
        self.final_newline = final
        self.tail = list(tail)            # lines after the last block
        self.readonly = None              # why the view cannot structure it
        self.error = None
        self.attach(self.blocks)

    def attach(self, blocks, parent=None):
        for block in blocks:
            block.parent = parent
            block.slot = "body"
        return blocks

    def all(self):
        out = []
        for block in self.blocks:
            out.extend(block.all())
        return out

    def find(self, pid):
        for block in self.all():
            if block.pid == pid:
                return block
        return None

    def __len__(self):
        return len(self.blocks)

    def __iter__(self):
        return iter(self.blocks)

    def counts(self):
        out = {}
        for block in self.all():
            out[block.kind] = out.get(block.kind, 0) + 1
        return out

    @property
    def errors(self):
        """[(pid, why)] for every block that is not valid Python."""
        out = []
        for block in self.all():
            why = block.check()
            if why:
                out.append((block.pid, why))
        return out

    def is_clean(self):
        return self.readonly is None and not self.errors

    def summary(self):
        if self.readonly:
            return f"view only: {self.readonly}"
        total = sum(self.counts().values())
        return f"{total} blocks"

    def holder(self, parent=None, slot=None):
        """The stack `insert` and `move` write into."""
        if isinstance(parent, Block):
            return parent.bodies.setdefault(self.slot_for(parent, slot), [])
        return self.blocks

    def slot_for(self, parent, slot):
        """The stack named `slot`, else the parent's first."""
        if isinstance(parent, Block):
            names = parent.body_names()
            if slot in names:
                return slot
            if names:
                return names[0]
        return "body"

    def _landing(self, parent, slot):
        """Where a block really goes: (holder, slot, index)."""
        if isinstance(parent, Block) and not parent.body_names():
            if isinstance(parent.parent, Block):
                return parent.parent, parent.slot, parent.index() + 1
            if parent in self.blocks:
                return None, "body", self.blocks.index(parent) + 1
        return parent, slot, None

    def insert(self, block, parent=None, slot=None, index=None):
        """Put `block` in a stack; returns the block."""
        if isinstance(parent, Block) and parent.find(block.pid) is not None:
            return block                      # a stack cannot hold itself
        parent, slot, after = self._landing(parent, slot)
        if index is None:
            index = after
        stack = self.holder(parent, slot)
        block.parent = parent if isinstance(parent, Block) else None
        block.slot = self.slot_for(parent, slot)
        block.mark_moved()
        if index is None or index < 0 or index > len(stack):
            stack.append(block)
        else:
            stack.insert(int(index), block)
        return block

    def move(self, block, parent=None, slot=None, index=None):
        """Re-home `block`, dropping the source text it read."""
        block.remove()
        # landing is worked out after the move
        parent, slot, after = self._landing(parent, slot)
        block.pre = []
        block.text = ""
        block.indent = ""
        block.leads = {}
        block.gaps = {}
        if index is None:
            index = after
        return self.insert(block, parent, slot, index)

    def replace(self, block, kind, fields=None):
        """Turn a block into another kind, keeping its words."""
        out = new_block(kind, fields)
        parent, index, slot = block.parent, block.index(), block.slot
        out.bodies.update({name: list(st) for name, st in block.bodies.items()
                           if name in out.bodies})
        for stack in out.bodies.values():
            self.attach(stack, out)
        block.remove()
        return self.insert(out, parent, slot, index if index >= 0 else None)

    def remove(self, block):
        return block.remove()

    def lines(self):
        out = []
        for block in self.blocks:
            out.extend(block.lines(self.unit, "", 0))
        out.extend(self.tail)
        return out

    def render(self, strict=False):
        """The file as text."""
        if strict:
            problems = self.errors
            if problems:
                raise ValueError(f"{len(problems)} block(s) are not valid "
                                 f"python ({problems[0][1]})")
        text = "\n".join(self.lines())
        if self.final_newline:
            text += "\n"
        if self.newline != "\n":
            text = text.replace("\n", self.newline)
        return text

    def revert(self, block=None, to_file=False):
        """Undo typed words on one block, or the file."""
        for entry in (block,) if block is not None else self.all():
            entry.revert(to_file)
        return self

    def diff(self, text=None):
        """First line where the render and `text` disagree."""
        other = (self.source if text is None else text).replace(
            "\r\n", "\n").split("\n")
        mine = self.render().replace("\r\n", "\n").split("\n")
        for index in range(max(len(other), len(mine))):
            a = other[index] if index < len(other) else None
            b = mine[index] if index < len(mine) else None
            if a != b:
                return index + 1, a, b
        return 0, None, None

    def __repr__(self):
        return f"<Module {self.summary()}>"


def _split(text):
    """Physical lines without their endings, plus the newline style."""
    newline = "\r\n" if "\r\n" in text else "\n"
    body = text.replace("\r\n", "\n")
    final = body.endswith("\n")
    lines = body[:-1].split("\n") if final else body.split("\n")
    return lines, newline, final


def _join(lines):
    """Captured source lines, kept exactly as the file spells them."""
    return "\n".join(lines)


def _logical(text):
    """First and last row of every logical line, 1-based."""
    out = {}
    try:
        rows = io.StringIO(text.replace("\r\n", "\n"))
        start = None
        for tok in tokenize.generate_tokens(rows.readline):
            if tok.type == tokenize.NEWLINE:
                if start is not None:
                    out.setdefault(start, tok.start[0])
                start = None
            elif tok.type in (tokenize.NL, tokenize.COMMENT, tokenize.INDENT,
                              tokenize.DEDENT, tokenize.ENDMARKER,
                              tokenize.ENCODING):
                continue
            elif start is None:
                start = tok.start[0]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}
    return out


def _detect_unit(lines):
    """The indent step new blocks line up to."""
    counts = {}
    for line in lines:
        if line.strip() and line[0] in " \t":
            step = line[:len(line) - len(line.lstrip())]
            counts[step] = counts.get(step, 0) + 1
    if not counts:
        return "    "
    narrow = min(len(step) for step in counts)
    for step, hits in sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0]))):
        if len(step) == narrow and hits > 1:
            return step
    return min(counts, key=len)


_COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
             ast.AsyncWith, ast.Try, ast.FunctionDef, ast.AsyncFunctionDef,
             ast.ClassDef, ast.ExceptHandler)


def _shared_rows(tree):
    """Lines that hold two statements at once."""
    counts = {}

    def visit(nodes):
        for node in nodes:
            if isinstance(node, ast.stmt):
                counts[node.lineno] = counts.get(node.lineno, 0) + 1
            for _name, value in ast.iter_fields(node):
                if isinstance(value, list):
                    visit([item for item in value
                           if isinstance(item, (ast.stmt,
                                                 ast.excepthandler))])

    visit(tree.body)
    return {row for row, hits in counts.items() if hits > 1}


class _Read:
    """Turn a parsed AST into blocks, keeping the rest."""

    def __init__(self, lines, logical, shared=()):
        self.lines = lines
        self.logical = logical
        self.shared = set(shared)
        self.row = 0                  # last physical line handed to a block

    def indent_of(self, row):
        line = self.lines[row - 1] if 0 < row <= len(self.lines) else ""
        return line[:len(line) - len(line.lstrip())]

    def take(self, start):
        """The lines between the cursor and the next block, verbatim."""
        out = self.lines[self.row:start - 1] if start - 1 > self.row else []
        self.row = start - 1
        return out

    def first_line(self, node):
        """The line a block starts on, decorators included."""
        start = node.lineno
        for deco in getattr(node, "decorator_list", None) or ():
            row = deco.lineno
            for probe, end in self.logical.items():
                if probe <= row <= end:
                    row = probe
                    break
            start = min(start, row)
        return start

    def header_end(self, row, node):
        """The header's last line, before its first stack."""
        anchor = getattr(node, "lineno", row) or row
        end = self.logical.get(anchor)
        if end is None:
            body = getattr(node, "body", None) or [node]
            return max(anchor, body[0].lineno - 1)
        return max(end, row)

    def statement(self, node):
        start = self.first_line(node)
        if start <= self.row:
            return None               # a twin on a line a block already owns
        if start in self.shared:
            pre = self.take(start)
            return self.raw(start, self.logical.get(start, start), pre,
                            self.indent_of(start))
        pre = self.take(start)
        indent = self.indent_of(start)
        last = getattr(node, "end_lineno", None) or start
        compound = isinstance(node, _COMPOUND)
        head_end = last
        if compound:
            head_end = self.header_end(start, node)
            body = getattr(node, "body", None) or []
            if body and body[0].lineno <= head_end:
                return self.raw(start, last, pre, indent)   # `if x: return`
            if head_end >= last:
                return self.raw(start, last, pre, indent)
        kind, fields = _classify(node)
        if kind is None:
            return self.raw(start, last, pre, indent)
        text = _join(self.lines[start - 1:head_end])
        block = Block(kind, fields, text=text, indent=indent, pre=pre)
        block.lineno, block.end, block.node = start, last, node
        if compound:
            # the header is spoken for: its stacks start below it
            self.row = head_end
            self.branches(block, node, head_end)
        self.row = last
        return block

    def raw(self, start, last, pre, indent):
        """A block for source the model has no shape for."""
        text = _join(self.lines[start - 1:last])
        block = Block("raw", {"code": text}, text=text, indent=indent, pre=pre)
        block.original["code"] = text
        block.lineno, block.end = start, last
        self.row = last
        return block

    def branches(self, block, node, head_end):
        if isinstance(node, ast.If):
            # an input branch holds one stack and has no else
            name = "body" if block.kind in ("held", "pressed",
                                            "released") else "then"
            self.fill(block, name, node.body)
            self.otherwise(block, node.orelse, "alt", "else")
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            self.fill(block, "body", node.body)
            self.otherwise(block, node.orelse, "alt", "else")
        elif isinstance(node, ast.Try):
            self.fill(block, "body", node.body)
            handlers = []
            for handler in node.handlers:
                clause = self.statement(handler)
                if clause is None:
                    continue
                clause.parent, clause.slot = block, "handlers"
                handlers.append(clause)
            block.bodies["handlers"] = handlers
            self.otherwise(block, node.orelse, "else", "else")
            self.otherwise(block, node.finalbody, "final", "finally")
        else:                                   # with, def, class
            self.fill(block, "body", node.body)
        return block

    def fill(self, block, name, nodes):
        """Read one stack of nested statements into a body slot."""
        out = []
        for child in nodes:
            sub = self.statement(child)
            if sub is None:
                continue
            sub.parent, sub.slot = block, name
            out.append(sub)
        block.bodies[name] = out
        return out

    def otherwise(self, block, nodes, name, lead):
        """Claim the line opening a second stack, then read it."""
        if not nodes:
            return
        row = self.first_line(nodes[0])
        probe = self.row + 1
        while probe < row:
            text = self.lines[probe - 1].strip() if \
                probe <= len(self.lines) else ""
            if text and not text.startswith("#"):
                break
            probe += 1
        key = self.lines[probe - 1] if 0 < probe <= len(self.lines) else ""
        word = key.strip()
        if word.startswith("elif"):
            pass
        elif word.startswith(lead) or word.startswith(("else", "finally")):
            block.gaps[name] = self.lines[self.row:probe - 1]
            # keep the keyword line as written, comments included
            if key.startswith(block.indent):
                block.leads[name] = key[len(block.indent):]
            else:
                block.leads[name] = word
            self.row = probe
        for child in self.fill(block, name, nodes):
            if name == "alt" and child.kind == "if":
                child.read_word("word", "elif" if word.startswith("elif")
                                else "if")


def _name(node):
    try:
        return ast.unparse(node)
    except Exception:                 # a half-built node must not lose a file
        return ""


def _target(node):
    return _name(node)


def _alias(node):
    return f"{node.name} as {node.asname}" if node.asname else node.name


def _with_item(item):
    text = _name(item.context_expr)
    if item.optional_vars is not None:
        text += f" as {_target(item.optional_vars)}"
    return text


def _args_text(args):
    """A parameter list as one line, defaults kept."""
    return _name(args) if args is not None else ""


# calls the palette writes, so a file reads back in
CALLS = {
    ("self.game.restart_scene", 0): ("restart", (), {}),
    ("self.game.screenshot", 0): ("shot", (), {}),
    ("self.despawn", 1): ("remove", ("who",), {}),
    ("self.audio.stop_music", 0): ("nomusic", (), {}),
    ("self.audio.stop_all", 0): ("silence", (), {}),
    ("self.hud.crosshair", 0): ("crosshair", (), {}),
    ("self.bind", 2): ("bind", ("action", "key"), {}),
    ("self.input.unbind", 1): ("unbind", ("action",), {}),
    ("self.input.grab_mouse", 1): ("grab", ("word",), {}),
    ("self.broadcast", 1): ("broadcast", ("name",), {}),
    ("self.broadcast", 2): ("broadcast", ("name", "value"), {}),
    ("self.listen", 1): ("listen", ("name",), {}),
    ("self.listen", 2): ("listen", ("name", "who"), {}),
    ("self.unlisten", 1): ("unlisten", ("name",), {}),
    ("self.unlisten", 2): ("unlisten", ("name", "who"), {}),
    ("self.save.set", 2): ("remember", ("key", "value"), {}),
    ("self.save.add", 2): ("count", ("key", "amount"), {}),
    ("self.save.flag", 1): ("mark", ("key",), {}),
    ("self.save.unflag", 1): ("unmark", ("key",), {}),
    ("self.game.save_game", 0): ("savenow", (), {}),
    ("self.game.load_game", 0): ("loadnow", (), {}),
    ("self.after", 2): ("after", ("seconds", "fn"), {}),
    ("self.every", 2): ("every", ("seconds", "fn"), {}),
}

# a method on another object: `who`, then keyword or positionals
METHODS = (
    ("set", "pos", "move", ()),
    ("set", "yaw", "face", ()),
    ("clone", None, "clone", ("pos",)),
    ("on", None, "lighton", ()),
    ("off", None, "lightoff", ()),
    ("flash", None, "flash", ("amount", "seconds")),
    ("fade_to", None, "fade", ("amount", "seconds")),
    # entity: one call on whoever the block names
    ("set_health", None, "set_health", ("value",)),
    ("heal", None, "heal", ("amount",)),
    ("take_damage", None, "damage", ("amount", "source")),
    ("kill", None, "kill", ("source",)),
    ("queue_free", None, "leave", ()),
    ("set_ai", None, "set_ai", ("ai_type", "config")),
    ("set_ai_target", None, "set_ai_target", ("target",)),
    ("set_team", None, "set_team", ("team",)),
    ("set_aggro_range", None, "set_aggro_range", ("distance", "deaggro")),
    ("set_attack", None, "set_attack", ("range", "dmg", "cd")),
    ("set_move_speed", None, "set_move_speed", ("walk", "run")),
    ("set_hitbox", None, "set_hitbox", ("shape", "params")),
    ("set_hitbox2d", None, "set_hitbox2d", ("shape", "params")),
)

# a branch testing one input call: the block it wrote
INPUT_TESTS = {"self.input.down": "held",
               "self.input.pressed": "pressed",
               "self.input.released": "released"}

# a slot the palette writes only when it holds words
DROPPABLE = (("broadcast", "value"), ("listen", "who"),
             ("unlisten", "who"))


def _unquote(text):
    """A string literal's words, without its quotes."""
    if len(text) > 1 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _chain(node):
    """The source of a plain `a.b.c` path, or None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _chain(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _recognise_method(node):
    """A call on another object, read as its block."""
    if not isinstance(node.func, ast.Attribute):
        return None
    who = _chain(node.func.value)
    if who is None:
        return None
    for method, keyword, kind, slots in METHODS:
        if node.func.attr != method:
            continue
        if keyword is not None:
            got = [kw for kw in node.keywords if kw.arg == keyword]
            if node.args or len(got) != 1 or len(node.keywords) != 1:
                continue
            fields = {"who": who, keyword: _name(got[0].value)}
        else:
            if node.keywords or len(node.args) != len(slots):
                continue
            fields = {"who": who}
            for slot, arg in zip(slots, node.args):
                fields[slot] = _name(arg)
        if all(name in fields for name, _words in SPEC[kind].slots):
            return kind, fields
    return None


def _recognise_generic(node):
    """Any other bare call: `call` or `callon`."""
    if node.keywords:
        return None
    args = ", ".join(_name(arg) for arg in node.args)
    if isinstance(node.func, ast.Name):
        return "call", {"fn": node.func.id, "args": args}
    if not isinstance(node.func, ast.Attribute):
        return None
    who = _chain(node.func.value)
    if who is None:
        return None
    return "callon", {"who": who, "fn": node.func.attr, "args": args}


def _recognise(node):
    """(kind, fields) when the palette writes this call."""
    if not isinstance(node, ast.Call):
        return None
    found = api.read(node)
    if found is not None:
        return found
    got = CALLS.get((_name(node.func), len(node.args)))
    if got is None:
        return _recognise_method(node) or _recognise_generic(node)
    kind, slots, keywords = got
    if len(node.keywords) != len(keywords):
        return None
    fields = {name: _name(arg) for name, arg in zip(slots, node.args)}
    for kw in node.keywords:
        name = keywords.get(kw.arg)
        if name is None:
            return None          # **kwargs, or a keyword the block lacks
        fields[name] = _name(kw.value)
    for name, _words in SPEC[kind].slots:
        if name not in fields:
            if (kind, name) in DROPPABLE:
                fields[name] = ""   # the call dropped a slot left empty
            else:
                return None          # a slot the call never filled
    if kind == "lamp":
        fields["shape"] = _unquote(fields["shape"])
    return kind, fields


def _recognise_test(node):
    """The block that wrote an `if` on one input call."""
    test = node.test
    if node.orelse or not isinstance(test, ast.Call):
        return None
    kind = INPUT_TESTS.get(_name(test.func))
    if kind is None or test.keywords or len(test.args) != 1:
        return None
    return kind, {"action": _name(test.args[0])}


def _classify(node):
    """(kind, slot words) for a statement, else raw."""
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            return None, {}
        target = _target(node.targets[0])
        got = api.read_assign(target, node.value)
        if got is not None:
            return got            # a shader line names what it writes
        return "set", {"target": target,
                       "value": _name(node.value), "type": ""}
    if isinstance(node, ast.AnnAssign):
        return "set", {"target": _target(node.target),
                       "type": _name(node.annotation),
                       "value": _name(node.value) if node.value else ""}
    if isinstance(node, ast.AugAssign):
        return "bump", {"target": _target(node.target),
                        "op": f"{OPS.get(type(node.op).__name__, '+')}=",
                        "value": _name(node.value)}
    if isinstance(node, ast.Expr):
        if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str):
            return None, {}               # a docstring: leave its quotes be
        found = _recognise(node.value)
        if found is not None:
            return found
        return "do", {"expr": _name(node.value)}
    if isinstance(node, ast.Return):
        return "return", {"value": _name(node.value) if node.value else ""}
    if isinstance(node, ast.Pass):
        return "pass", {}
    if isinstance(node, ast.Break):
        return "break", {}
    if isinstance(node, ast.Continue):
        return "continue", {}
    if isinstance(node, ast.Raise):
        return "raise", {"types": _name(node.exc) if node.exc else "",
                         "cause": _name(node.cause) if node.cause else ""}
    if isinstance(node, ast.Assert):
        return "assert", {"test": _name(node.test),
                          "message": _name(node.msg) if node.msg else ""}
    if isinstance(node, ast.Delete):
        return "forget", {"targets": ", ".join(_target(t) for t in
                                               node.targets)}
    if isinstance(node, ast.Global):
        return "global", {"word": "global", "names": ", ".join(node.names)}
    if isinstance(node, ast.Nonlocal):
        return "global", {"word": "nonlocal", "names": ", ".join(node.names)}
    if isinstance(node, ast.Import):
        return "import", {"names": ", ".join(_alias(a) for a in node.names)}
    if isinstance(node, ast.ImportFrom):
        stem = "." * node.level + (node.module or "")
        return "from", {"src": stem,
                        "names": ", ".join(_alias(a) for a in node.names)}
    if isinstance(node, ast.If):
        held = _recognise_test(node)
        if held is not None:
            return held
        return "if", {"test": _name(node.test), "word": "if"}
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return "each", {"word": "async for" if isinstance(node, ast.AsyncFor)
                        else "for", "target": _target(node.target),
                        "seq": _name(node.iter)}
    if isinstance(node, ast.While):
        return "while", {"test": _name(node.test)}
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return "guard", {"word": "async with" if isinstance(node, ast.AsyncWith)
                         else "with",
                         "items": ", ".join(_with_item(i) for i in node.items)}
    if isinstance(node, ast.Try):
        return "try", {}
    if isinstance(node, ast.ExceptHandler):
        return "except", {"types": _name(node.type) if node.type else "",
                          "name": node.name or ""}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "def", {"word": "async def" if isinstance(node,
                                                         ast.AsyncFunctionDef)
                       else "def", "name": node.name,
                       "args": _args_text(node.args),
                       "type": _name(node.returns) if node.returns else "",
                       "decorators": "\n".join(_name(d) for d in
                                               node.decorator_list)}
    if isinstance(node, ast.ClassDef):
        parts = [_name(b) for b in node.bases]
        parts += [f"{k.arg}={_name(k.value)}" for k in node.keywords]
        return "class", {"name": node.name, "bases": ", ".join(parts),
                         "decorators": "\n".join(_name(d) for d in
                                                 node.decorator_list)}
    return None, {}


def parse(text):
    """Read Python source into a Module of blocks."""
    text = str(text)
    lines, newline, final = _split(text)
    module = Module(source=text, newline=newline, final=final)
    if not text.strip():
        module.tail = lines
        return module
    logical = _logical(text)
    module.unit = _detect_unit(lines)
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError) as exc:
        block = _whole_file(lines)
        module.blocks = module.attach([block])
        reason = getattr(exc, "msg", None) or str(exc)
        module.readonly = f"{reason} (line {getattr(exc, 'lineno', '?')})"
        module.error = exc
        return module
    read = _Read(lines, logical, _shared_rows(tree))
    for node in tree.body:
        block = read.statement(node)
        if block is not None:
            module.blocks.append(block)
    module.tail = lines[read.row:]
    return module


def _whole_file(lines):
    """One raw block holding an unparseable file: nothing is hidden."""
    text = "\n".join(lines)
    block = Block("raw", {"code": text}, text=text, indent="", pre=[])
    block.original["code"] = text
    block.moved = False
    return block


# file kinds the tab tells apart, and their names
KINDS = {
    "scene3d": "3D scene",
    "scene2d": "2D scene",
    "sceneui": "UI scene",
    "object3d": "3D object",
    "object2d": "2D object",
    "ui": "UI object",
    "player3d": "3D player",
    "player2d": "2D player",
    "entity3d": "3D entity",
    "entity2d": "2D entity",
    "camera3d": "3D camera",
    "camera2d": "2D camera",
    "screen3d": "3D screen",
    "screen2d": "2D screen",
    "model3d": "3D model",
    "sprite2d": "sprite",
    "collision3d": "3D collision",
    "hitbox3d": "3D hitbox",
    "trigger3d": "3D trigger",
    "marker3d": "3D marker",
    "collision2d": "2D collision",
    "hitbox2d": "2D hitbox",
    "trigger2d": "2D trigger",
    "marker2d": "2D marker",
    "light3d": "3D light",
    "omnilight3d": "omni light",
    "spotlight3d": "spot light",
    "directionallight3d": "sun light",
    "light2d": "2D light",
    "pointlight2d": "point light",
    "conelight2d": "cone light",
    "rectlight2d": "rect light",
    "audio3d": "3D emitter",
    "audio2d": "2D emitter",
    "text3d": "3D text",
    "text2d": "2D text",
    "timer3d": "3D timer",
    "timer2d": "2D timer",
    "particle3d": "3D particles",
    "particle2d": "2D particles",
    "shader": "shader",
    "script": "script",
}

# engine base class to the file kind declaring it
BASES = {"Scene3D": "scene3d", "Scene2D": "scene2d", "SceneUI": "sceneui",
         "Object3D": "object3d", "Object2D": "object2d",
         "UIObject": "ui", "Player3D": "player3d", "Player2D": "player2d",
         "Entity3D": "entity3d", "Entity2D": "entity2d",
         "Screen3D": "screen3d", "Screen2D": "screen2d",
         "Model3D": "model3d", "Sprite2D": "sprite2d",
         "Collider3D": "collision3d", "Collision3D": "collision3d",
         "Hitbox3D": "hitbox3d", "Trigger3D": "trigger3d",
         "Marker3D": "marker3d",
         "Collision2D": "collision2d", "Hitbox2D": "hitbox2d",
         "Trigger2D": "trigger2d", "Marker2D": "marker2d",
         "LightNode3D": "light3d", "OmniLight3D": "omnilight3d",
         "SpotLight3D": "spotlight3d",
         "DirectionalLight3D": "directionallight3d",
         "LightNode2D": "light2d", "PointLight2D": "pointlight2d",
         "ConeLight2D": "conelight2d", "RectLight2D": "rectlight2d",
         "AudioEmitter3D": "audio3d", "AudioEmitter2D": "audio2d",
         "Text3D": "text3d", "Text2D": "text2d",
         "Timer3D": "timer3d", "Timer2D": "timer2d",
         "Particle3D": "particle3d", "Particle2D": "particle2d",
         "Shader": "shader"}

# a kind borrowing another's blocks: screens share objects
ALIAS = {"screen3d": "object3d", "screen2d": "object2d"}

# a plain script gets no scene, object or hook drawers
SCRIPT_CATEGORIES = ("control", "data", "functions", "modules", "code")

# strict per-node palettes: own drawer plus language, nothing else
_LANG = SCRIPT_CATEGORIES
TYPE_CATEGORIES = {
    # an entity's own script: its body, its behaviour, its triggers, its light
    "entity3d": ("object", "entity", "trigger", "light") + _LANG,
    "entity2d": ("object", "entity", "trigger", "light") + _LANG,
    "model3d": ("object", "light") + _LANG,
    "sprite2d": ("object",) + _LANG,
    "collision3d": ("object",) + _LANG,
    "hitbox3d": ("object",) + _LANG,
    "trigger3d": ("object",) + _LANG,
    "marker3d": ("object",) + _LANG,
    "collision2d": ("object",) + _LANG,
    "hitbox2d": ("object",) + _LANG,
    "trigger2d": ("object",) + _LANG,
    "marker2d": ("object",) + _LANG,
    "light3d": ("light",) + _LANG,
    "omnilight3d": ("light",) + _LANG,
    "spotlight3d": ("light",) + _LANG,
    "directionallight3d": ("light",) + _LANG,
    "light2d": ("light",) + _LANG,
    "pointlight2d": ("light",) + _LANG,
    "conelight2d": ("light",) + _LANG,
    "rectlight2d": ("light",) + _LANG,
    "audio3d": ("audio",) + _LANG,
    "audio2d": ("audio",) + _LANG,
    "text3d": ("object",) + _LANG,
    "text2d": ("object",) + _LANG,
    "timer3d": ("functions",) + _LANG,
    "timer2d": ("functions",) + _LANG,
    # an emitter's script: its own points, and the object's place in the world
    "particle3d": ("object", "light") + _LANG,
    "particle2d": ("object", "light") + _LANG,
    # a shader script sees the shader and language drawers only
    "shader": ("shader",) + _LANG,
}


def file_kind(module):
    """The file kind, from the base class it declares."""
    found = []
    for block in module.blocks:
        if block.kind != "class":
            continue
        for base in str(block.fields.get("bases", "")).split(","):
            name = base.strip().rsplit(".", 1)[-1].split("(")[0].strip()
            kind = BASES.get(name)
            if kind and kind not in found:
                found.append(kind)
    for kind in found:
        if kind.startswith("scene"):
            return kind
    return found[0] if found else "script"


def fits(entry, kind):
    """Whether a block fits a file of that kind."""
    if not kind:
        return True
    kind = ALIAS.get(kind, kind)
    if kind == "script":
        return entry.category in SCRIPT_CATEGORIES
    allow = TYPE_CATEGORIES.get(kind)
    if allow is not None and entry.category not in allow:
        return False                    # the strict palette cuts it out
    return not entry.kinds or kind in entry.kinds


def _row_label(entry):
    """A drawer row's label, its holes showing examples."""
    out = []
    for kind, payload in _template(entry.label):
        if kind == "text":
            out.append(payload)
            continue
        words = entry.placeholder(payload) or payload
        out.append(words if len(words) <= 12 else payload)
    return " ".join(" ".join(out).split())


def palette(category=None, kind=None):
    """The block kinds a drawer offers, in tab order."""
    out = []
    for name, entry in SPEC.items():
        if category and entry.category != category:
            continue
        if not fits(entry, kind):
            continue
        out.append({"kind": name, "label": _row_label(entry),
                    "shape": entry.shape, "doc": entry.doc,
                    "category": entry.category})
    order = {name: row for row, name in enumerate(CATEGORIES)}
    out.sort(key=lambda row: (order.get(row["category"], 99), row["label"]))
    return out


def drawers(kind=None):
    """[(category, [palette row, ...])], one group per drawer."""
    return [(name, palette(name, kind)) for name in CATEGORIES]


def search(module, needle):
    """Blocks whose own words contain `needle`."""
    needle = str(needle).lower()
    return [block for block in module.all() if needle in block.label().lower()]


def outline(module):
    """[(pid, words, kind, depth)] for every block: the tab's minimap."""
    return [(block.pid, block.label(), block.kind, block.depth())
            for block in module.all()]


def block_source(block, unit="    "):
    """One block back to Python on its own."""
    return block.source(unit)


def tree_of(text):
    """The AST dump of a file, or None."""
    try:
        return ast.dump(ast.parse(text))
    except (SyntaxError, ValueError):
        return None


def same_tree(a, b):
    """Do two files mean the same program, spelling aside?"""
    tree = tree_of(a)
    return tree is not None and tree == tree_of(b)


def can_view(text):
    """Whether the block view has anything to show."""
    return bool(str(text).strip()) and tree_of(text) is not None


def round_trip(text):
    """Does parse then render give the file back exactly?"""
    module = parse(text)
    back = module.render()
    if back == text:
        return True, None
    row, was, now = module.diff(text)
    note = f"line {row}: was {was!r} now {now!r}"
    if same_tree(back, text):
        note += " (same program, different text)"
    return False, note
