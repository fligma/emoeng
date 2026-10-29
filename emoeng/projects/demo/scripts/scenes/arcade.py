"""The flat companion room: walk it, and stand on a switch to pull it.

Everything the hall wears, this room wears too, and from the same table of
parts and looks. What differs is how it is asked for. A picture in 2D takes
no mouse, so the switches are plates on the floor: walk up to one and a
dialog opens over it saying what it activates, what the room answered last,
and which key does the same thing. Press E, or click the plate.

The lectern in the middle holds a screen that lists what every part is
currently wearing, so the room can be read as well as dressed.
"""

import emoeng as fe
from emoeng.engine import meshes
from scripts.scenes.dressing import Dresser, by_sheet, merge, pull

WORLD = (1280.0, 720.0)
WALL = 64.0                # pixels the room's four bands are thick
TILE = 128.0               # pixels one sheet repeat covers
PAD = (150.0, 52.0)        # a floor plate, and its button
CARD = (392.0, 46.0)       # the dialog that names what a plate does
CARD_GAP = 52.0            # how far a dialog floats above its plate
EDGE = (CARD[0] / 2.0 + 8.0, WORLD[0] - CARD[0] / 2.0 - 8.0)

# the room's nine switches: (label, trigger, part, what it activates, x)
SWITCHES = (
    (("floor", "look_floor", "floor", "what the floor is made of", 130.0),
     ("walls", "look_walls", "walls", "what the walls are made of", 330.0),
     ("arches", "look_arches", "arches", "what the arch stones are", 530.0),
     ("portals", "look_portals", "portals", "what the portals run on", 750.0),
     ("plinths", "look_props", "props", "what the props are made of", 950.0),
     ("lectern", "look_lectern", "lectern", "what the stand is made of",
      1150.0)),
    (("screen", "look_screen", "screen", "the lectern's own picture", 435.0),
     ("room", "look_room", "room", "the whole room's picture", 640.0),
     ("clear", "look_clear", "clear", "everything, back to plain", 845.0)),
)
ROW_Y = (500.0, 612.0)    # the two rows of plates
SPAWN = (640.0, 556.0)    # the walker starts between them, on no plate


def flat(pos, size, col, tile=TILE, rot=0.0):
    """One flat piece, its sheet repeats baked into its own uv.

    An unlit layer never gets a metre sheet handed to it, so a 2D part has
    to carry the repeats it wants in its corners rather than as a uv fit.
    """
    w, h = float(size[0]), float(size[1])
    if tile:
        return meshes.quad2d(pos, size, col=col, rot=rot,
                             uv=(0.0, 0.0, w / float(tile), h / float(tile)))
    return meshes.rect2d(pos, size, col=col, rot=rot)


class Pad(fe.Hitbox2D):
    """A floor switch: a plate, and a dialog saying what it activates."""

    name = "pad"

    def __init__(self, scene, pos, size=PAD, label="", trigger="", part="",
                 says="", card_at=None, tag=None, **knobs):
        super().__init__(scene, pos=pos, size=size,
                         tag=tag or f"pad_{trigger}", **knobs)
        self.label = str(label)
        self.trigger = str(trigger)
        self.part = str(part or label)
        self.says = str(says)
        self.card_at = (float(card_at[0]), float(card_at[1])) \
            if card_at else (float(pos[0]), float(pos[1]) - CARD_GAP)
        self.shown = False
        self._text = None

    def build(self):
        super().build()
        self.button = self.scene.spawn(
            fe.UIObject, pos=self.pos, parent=self, size=self.size,
            text=self.label, font_size=14, color="#2b3a4d",
            hover_color="#4a647f", press_color="#7fb2dc",
            action=self.press, tag=f"plate_{self.trigger}")
        self.card = self.scene.spawn(
            fe.UIObject, pos=self.card_at, parent=self, size=CARD,
            text=self.note(), font_size=12, color="#10151f",
            text_color=(0.92, 0.96, 1.0), tag=f"card_{self.trigger}")
        # made solid so its label keeps its own picture, then put away
        self._text = self.card.text
        self.card.set_opacity(0.0)
        self.card.enabled = False
        return self

    # -- what it says -----------------------------------------------------
    def note(self):
        """The dialog's line: what this does, how, and what it answered."""
        dress = getattr(self.scene, "dress", None)
        word = str((dress.words() if dress is not None else {})
                   .get(self.part, "plain"))
        key = ""
        tell = getattr(getattr(self.scene, "game", None), "key_text", None)
        if callable(tell):
            key = str(tell(self.trigger) or "")
        return "  |  ".join((self.says, f"{key} or click" if key else "click",
                             f"now {word}"))

    def show(self, on):
        """Open the dialog over the plate, or put it away."""
        on = bool(on)
        if on:
            text = self.note()
            if text != self._text:
                self._text = text
                self.card.set_text(text)
        if on == self.shown:
            return on
        self.shown = on
        # a faded card must also stop taking clicks, or it hides the plate
        self.card.set_opacity(1.0 if on else 0.0)
        self.card.enabled = on
        return on

    # -- what it does -----------------------------------------------------
    def press(self):
        """Ask the room for this switch, exactly as its key would."""
        return self.broadcast(self.trigger)

    def update(self, dt):
        super().update(dt)
        # `inside` is what the hitbox keeps of its own
        here = self.show(bool(self.inside))
        # a plate answers the walk-up key as readily as a click on it
        if here and self.input.pressed("use"):
            self.press()
        return here


class Arcade(fe.Scene2D):
    """Walk the flat room; every switch is a plate underfoot."""

    name = "arcade"
    world_size = WORLD
    scale_mode = "fit"
    post = ()                    # the room starts undressed
    clear_color = (0.025, 0.03, 0.065)
    ambient2d = (0.23, 0.2, 0.32)
    # here W and S walk, so this room says so; Tab is the way out
    actions = {"other_room": ["tab"], "up": ["w", "up"],
               "down": ["s", "down"]}
    controls = ("other_room",)

    def setup(self):
        self.dress = Dresser(self)
        self.state = {}          # trigger -> the one word it shows
        self.note = ""           # what the room last said over the bus
        self.pads = []
        self._room()
        self._lectern()
        self._pads()
        self._lights()
        self.player = self.spawn(
            fe.Player2D, pos=SPAWN, size=(44.0, 44.0),
            texture="glow", col=(1.0, 0.92, 0.72), move_speed=300.0,
            body_radius=18.0, follows_view=False, wheel_zoom=False,
            tag="walker")

    # -- the room, as parts -----------------------------------------------
    def _room(self):
        # the floor first: alpha has no depth, so what is laid is what shows
        self.dress.add("floor", flat((640.0, 360.0), (1152.0, 592.0),
                                     (0.30, 0.25, 0.38)),
                       texture="stone", blend="alpha")
        self.dress.add("floor", flat((640.0, 420.0), (300.0, 440.0),
                                     (0.34, 0.24, 0.42)),
                       texture="cloth", blend="alpha")

        shell = [flat((640.0, WALL / 2.0), WORLD[:1] + (WALL,),
                      (0.56, 0.58, 0.68)),
                 flat((640.0, WORLD[1] - WALL / 2.0), WORLD[:1] + (WALL,),
                      (0.56, 0.58, 0.68)),
                 flat((WALL / 2.0, 360.0), (WALL, WORLD[1]),
                      (0.60, 0.62, 0.70)),
                 flat((WORLD[0] - WALL / 2.0, 360.0), (WALL, WORLD[1]),
                      (0.60, 0.62, 0.70))]
        self.dress.add("walls", merge(*shell), texture="stone",
                       blend="alpha")

        # the back of the room: a cornice, and three block-built arches
        stones = []
        for cx in (340.0, 640.0, 940.0):
            for side in (-1, 1):
                stones.append(flat((cx + side * 96.0, 150.0), (26.0, 140.0),
                                   (0.66, 0.67, 0.71)))
            stones.append(flat((cx, 92.0), (218.0, 24.0),
                               (0.72, 0.70, 0.65)))
        arches = [(flat((640.0, 222.0), (1152.0, 22.0), (0.57, 0.35, 0.23)),
                   "bark")]
        arches += [(piece, "stone") for piece in stones]
        self.dress.add_part("arches", by_sheet(arches), blend="alpha")

        # the energy in the arches is its own part, so it can be re-dressed
        portals = [(flat((cx, 158.0), (164.0, 108.0), (0.86, 0.96, 1.0),
                         tile=0.0), "glow")
                   for cx in (340.0, 640.0, 940.0)]
        self.dress.add_part("portals", by_sheet(portals), blend="alpha")

        props = [(flat((x, y), (92.0, 92.0), (0.45, 0.48, 0.53)), "stone")
                 for x, y in ((250.0, 300.0), (1030.0, 300.0),
                              (250.0, 610.0), (1030.0, 610.0))]
        props += [(flat((x, y - 6.0), (44.0, 44.0), (1.0, 0.86, 0.62),
                        tile=0.0), "glow")
                  for x, y in ((250.0, 300.0), (1030.0, 300.0))]
        self.dress.add_part("props", by_sheet(props), blend="alpha")

        self._colliders()

    def _colliders(self):
        """The flat room stops you where its picture says it would."""
        for pos, size in (((640.0, WALL / 2.0), (WORLD[0], WALL)),
                          ((640.0, WORLD[1] - WALL / 2.0),
                            (WORLD[0], WALL)),
                          ((WALL / 2.0, 360.0), (WALL, WORLD[1])),
                          ((WORLD[0] - WALL / 2.0, 360.0), (WALL, WORLD[1]))):
            self.spawn(fe.Collision2D, pos=pos, size=size, tag="wall")
        # the arches are windows, not doors: the walk stops at the cornice
        self.spawn(fe.Collision2D, pos=(640.0, 135.0), size=(1152.0, 142.0),
                   tag="back")
        for pos in ((250.0, 300.0), (1030.0, 300.0),
                    (250.0, 610.0), (1030.0, 610.0)):
            self.spawn(fe.Collision2D, pos=pos, size=(92.0, 92.0),
                       tag="plinth")

    # -- the lectern, and the screen standing on it ----------------------
    def _lectern(self):
        """A stand in the room's middle, holding the readout."""
        body = [flat((640.0, 438.0), (240.0, 30.0), (0.45, 0.42, 0.52)),
                flat((640.0, 410.0), (110.0, 28.0), (0.50, 0.47, 0.58))]
        self.dress.add("lectern", merge(*body), texture="stone",
                       blend="alpha")
        # the bezel behind the glass, and the glass itself, one part
        self.dress.add("lectern",
                       flat((640.0, 292.0), (352.0, 212.0),
                            (0.28, 0.30, 0.37)),
                       texture=None, blend="alpha")
        self.readout = self.spawn(
            fe.Screen2D, pos=(640.0, 292.0), size=(320.0, 180.0),
            name="readout", pixels=(480, 270), brightness=1.05,
            tag="lectern_screen")
        self.dress.set_panel(self.readout)
        # one stop for the whole stand, so no plate sits behind it
        self.spawn(fe.Collision2D, pos=(640.0, 312.0), size=(352.0, 252.0),
                   tag="lectern")

    # -- the switches ----------------------------------------------------
    def _pads(self):
        for row, y in enumerate(ROW_Y):
            for label, trigger, part, says, x in SWITCHES[row]:
                card = (min(max(x, EDGE[0]), EDGE[1]), y - CARD_GAP)
                self.pads.append(
                    self.spawn(Pad, pos=(x, y), label=label,
                               trigger=trigger, part=part, says=says,
                               card_at=card, tag=f"pad_{trigger}"))

    def _lights(self):
        for cx in (340.0, 640.0, 940.0):
            self.add_light(pos=(cx, 170.0), color="#66dfff", energy=1.25,
                           radius=230.0, shape="radial", pulse=0.14,
                           pulse_rate=0.4)
        self.add_light(pos=(640.0, 330.0), color="#ed7cff", energy=1.1,
                       radius=320.0, shape="radial", pulse=0.1,
                       pulse_rate=0.28)
        for x, color in ((250.0, "#ffaf76"), (1030.0, "#69dbff")):
            self.add_light(pos=(x, 300.0), color=color, energy=0.85,
                           radius=260.0, shape="radial", flicker=0.05,
                           flicker_rate=1.9)

    # -- the bus ---------------------------------------------------------
    def on_trigger(self, name, value=None):
        """One plate, or its key: re-dress one part of the room."""
        got = pull(self.dress, name)
        if got is None:
            return super().on_trigger(name, value)
        word, self.note = got
        self.state[str(name)] = word
        return word

    def update(self, dt):
        super().update(dt)
        if self.input.pressed("other_room"):
            self.play_scene("main")

    def overlay(self, screen):
        area = self.hud.area
        self.hud.panel((area.x + 14, area.y + 12, 380, 66),
                       color=(13, 17, 29), alpha=195)
        self.hud.text("DEMO  /  THE ECHO ROOM",
                      (area.x + 26, area.y + 20),
                      color=(0.84, 0.7, 1.0))
        self.hud.text("WASD to walk  -  E for a switch  -  Tab for the hall",
                      (area.x + 26, area.y + 45))
        if self.note:
            self.hud.text(self.note, (area.x + 14, area.y + area.h - 34),
                          color=(0.85, 0.9, 1.0))

    def status(self):
        return [self.name, "Echo Room", f"{len(self.lights)} lights",
                f"{len(self.pads)} switches"]
