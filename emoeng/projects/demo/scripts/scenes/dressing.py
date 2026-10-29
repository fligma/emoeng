"""The dress both demo rooms wear: parts, looks, and how they get swapped.

Each room is built out of named *parts* - floor, walls, arches, portals,
props, lectern - and every part is drawn as one live mesh rather than
batched statics, so a switch can change what one part is made of while the
room still stands. A part wears at most one `uv` shader at a time.

Two more levers sit beside the parts, because a whole picture is more than
its surfaces:

  wash   the shader chain the room's own frame runs through
  screen the shader chain the lectern's panel runs through

`Scene.dynamic()` is what makes a part re-shadable, and `merge()` is what
makes it cheap: several `MeshData` become one, so a wall of ten boxes still
costs a single draw call.
"""


# the surfaces a switch may re-dress, in the order a board lists them
PARTS = ("floor", "walls", "arches", "portals", "props", "lectern")

# what one surface may wear: `None` is the plain, unshadered material
LOOKS = (None, "uvscroll", "tintpulse", "kaleido", "portal")

# the room's whole frame, as (name shown on a switch, shader chain)
WASHES = (
    ("plain", ()),
    ("trippy", ("trippy",)),
    ("glitch", ("glitch",)),
    ("tube", ("scanlines",)),
    ("dusk", ("scanlines", "trippy")),
    ("storm", ("glitch", "trippy")),
)

# ... and the lectern panel's, which is a screen of its own
SCREENS = (
    ("plain", ()),
    ("tube", ("scanlines",)),
    ("trippy", ("trippy",)),
    ("broken", ("glitch", "scanlines")),
)

# what one switch asks for, as (lever, part): the same nine names a board
# shows and the keys 1..9 are bound to
ACTS = {
    "look_floor": ("look", "floor"),
    "look_walls": ("look", "walls"),
    "look_arches": ("look", "arches"),
    "look_portals": ("look", "portals"),
    "look_props": ("look", "props"),
    "look_lectern": ("look", "lectern"),
    "look_screen": ("screen", None),
    "look_room": ("wash", None),
    "look_clear": ("clear", None),
}


def merge(*parts):
    """Several meshes as one, so a part costs a single draw call.

    `MeshData.append` keeps each piece's own vertices and re-bases its
    indices, so pieces need no shared origin - they are merged where they
    already stand.
    """
    first = parts[0]
    for other in parts[1:]:
        first.append(other)
    return first


def by_sheet(pieces):
    """`(mesh, texture)` pieces bucketed by sheet, each bucket merged.

    One mesh wears one texture, so only pieces of the same sheet may be
    merged; what comes back is `[(mesh, texture)]`, which is what
    `Dresser.add_part` takes for one part.
    """
    order, bucket = [], {}
    for data, texture in pieces:
        key = str(texture)
        if key not in bucket:
            order.append(key)
            bucket[key] = ([], texture)
        bucket[key][0].append(data)
    return [(merge(*bucket[key][0]), bucket[key][1]) for key in order]


def look_word(look):
    """One word for a look: a shader class or name, or `plain`."""
    if look is None:
        return "plain"
    return str(getattr(look, "name", look) or "plain")


# the parts whose name is plural, so a sentence about one reads right
PLURAL = ("walls", "arches", "portals", "props")


def wears(part):
    """'wear' or 'wears', so the room can talk about itself in one voice."""
    return "wear" if str(part) in PLURAL else "wears"


def pull(dress, name):
    """Do what one switch asks, as (the word it answers, a sentence).

    None comes back for a name no switch owns, so a room can pass the rest
    down to whatever else is listening.
    """
    act = ACTS.get(str(name))
    if act is None:
        return None
    kind, part = act
    if kind == "look":
        word = look_word(dress.cycle_look(part))
        return word, f"the {part} {wears(part)} {word}"
    if kind == "screen":
        word = dress.cycle_screen()
        return word, f"the screen runs {word}"
    if kind == "wash":
        word = dress.cycle_wash()
        return word, f"the whole room runs {word}"
    return dress.clear(), "the room is plain again"


class Dresser:
    """What a room wears, and the only thing its switches talk to."""

    def __init__(self, scene):
        self.scene = scene
        self.parts = {}        # part -> [DynamicMesh]
        self.looks = {}        # part -> the uv shader it wears, or None
        self.wash = 0          # index into WASHES
        self.screen = 0        # index into SCREENS
        self.panel = None      # the lectern's Screen, once it exists

    # -- building ---------------------------------------------------------
    def add(self, part, data, texture="white", blend="opaque", uv=None,
            owner=None):
        """One live mesh of one part; `owner` is what disposes it."""
        kw = {"texture": texture, "blend": blend}
        if uv is not None:
            kw["uv"] = uv
        draw = owner.dynamic if owner is not None else self.scene.dynamic
        mesh = draw(data, **kw)
        self.parts.setdefault(part, []).append(mesh)
        self.looks.setdefault(part, None)
        return mesh

    def add_part(self, part, pieces, blend="opaque", uv=None, owner=None):
        """Every sheet of one part, as merged by `by_sheet`; returns count."""
        for data, texture in pieces:
            self.add(part, data, texture=texture, blend=blend, uv=uv,
                     owner=owner)
        return len(pieces)

    def set_panel(self, panel):
        """Name the screen whose picture these switches dress."""
        self.panel = panel
        return panel

    # -- the levers -------------------------------------------------------
    def set_look(self, part, look):
        """Dress one part in one uv shader, or in plain material."""
        for mesh in self.parts.get(part, ()):
            mesh.set_shader(look)
        self.looks[part] = look
        return look

    def cycle_look(self, part):
        """The next look this part has not worn yet, wrapping round."""
        try:
            here = LOOKS.index(self.looks.get(part))
        except ValueError:
            here = 0
        return self.set_look(part, LOOKS[(here + 1) % len(LOOKS)])

    def set_wash(self, index):
        """Run the room's frame through one chain of screen shaders."""
        self.wash = int(index) % len(WASHES)
        name, passes = WASHES[self.wash]
        self.scene.set_post(*passes)
        return name

    def cycle_wash(self):
        """The next look for the room as a whole."""
        return self.set_wash(self.wash + 1)

    def set_screen(self, index):
        """Put a new chain through the lectern's picture."""
        self.screen = int(index) % len(SCREENS)
        name, passes = SCREENS[self.screen]
        if self.panel is not None:
            self.panel.set_post(*passes)
        return name

    def cycle_screen(self):
        """The next look for the lectern's picture."""
        return self.set_screen(self.screen + 1)

    def clear(self):
        """Nothing worn anywhere: every part plain, no wash, plain screen."""
        for part in list(self.parts):
            self.set_look(part, None)
        self.set_wash(0)
        self.set_screen(0)
        return "plain"

    # -- what a board shows -----------------------------------------------
    def words(self):
        """Every switch's answer as one dict, for a readout to pick from."""
        got = {part: look_word(self.looks.get(part)) for part in self.parts}
        got["room"] = WASHES[self.wash][0]
        got["screen"] = SCREENS[self.screen][0]
        got["clear"] = "plain"
        return got
