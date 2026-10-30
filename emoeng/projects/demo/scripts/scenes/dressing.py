"""What a room wears, and the only thing its switches talk to.

Every room is one map file - `maps/hall.map3d`, `maps/echo.map2d` - carved
into named *parts*: floor, walls, arches, portals, props, lectern. Nothing
here builds a room; the map owns the geometry, so one dresser can dress a
hall, then the vault it is swapped for, and a part is re-dressed by giving
its faces another sheet.

Two more levers sit beside the parts, because a whole picture is more than
its surfaces:

  wash   the shader chain the room's own frame runs through
  screen the shader chain the lectern's panel runs through

`Dresser.set_level()` is what ties it to a map: it reads the parts the map
carved and puts back whatever each one was wearing before the swap.
"""

# the surfaces a switch may re-dress, in the order a board lists them
PARTS = ("floor", "walls", "arches", "portals", "props", "lectern")

# what one surface may wear: `None` gives the map's own carved sheet back
LOOKS = (None, "stone", "bark", "rust", "cloth", "grid")

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


def look_word(look):
    """One word for a look: a sheet's name, or `plain`."""
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
        self.level = None      # the loaded map, once there is one
        self.parts = tuple(PARTS)
        self.looks = {}        # part -> the sheet it wears, or None
        self.wash = 0          # index into WASHES
        self.screen = 0        # index into SCREENS
        self.panel = None      # the lectern's Screen, once it exists

    # -- the map ----------------------------------------------------------
    def set_level(self, level):
        """Take over a freshly loaded map and dress it as it was left.

        A swap hands back the same part names in another room, so what a
        switch chose survives it: only the map behind the sheets changes.
        """
        self.level = level
        self.parts = tuple(level.parts() or PARTS) if level else tuple(PARTS)
        for part in self.parts:
            self.set_look(part, self.looks.get(part))
        return self

    def set_panel(self, panel):
        """Name the screen whose picture these switches dress."""
        self.panel = panel
        return panel

    # -- the levers -------------------------------------------------------
    def set_look(self, part, key):
        """Dress one part in one sheet, or in the map's own material."""
        key = key or None
        self.looks[str(part)] = key
        if self.level is not None:
            self.level.set_part_texture(part, key)
        return key

    def cycle_look(self, part):
        """The next sheet this part has not worn yet, wrapping round."""
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
        for part in self.parts:
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
