"""The flat twin: walk it, and stand on a switch to pull it.

The room is a map file - `maps/echo.map2d` - carved into the same parts the
hall is, so this script spawns only what rides on it: the floor plates,
their dialogs, the readout, the walker and one sparkler. What differs from
the hall is how a switch is asked for. A picture in 2D takes no mouse, so
the switches are plates on the floor: walk up to one and a dialog opens over
it saying what it activates, what the room answered last, and which key does
the same thing. Press E, or click the plate - and the room's one emitter
bursts sparks over the plate that answered. M swaps the room for the court
next door, and the plates stay where they were.
"""

import emoeng as fe
from scripts.scenes.dressing import Dresser, pull

WORLD = (1280.0, 720.0)
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

# the flat maps this scene swaps between, in the order M walks them
MAPS = ("echo", "court")


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
        self.scene.spark_at(self.pos)
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
    map_name = "echo"            # the level this scene opens on
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
        self._readout()
        self._sparkler()
        self._pads()
        start, yaw = self.spawn_point()
        self.player = self.spawn(
            fe.Player2D, pos=start[:2], size=(44.0, 44.0),
            texture="glow", col=(1.0, 0.92, 0.72), move_speed=300.0,
            body_radius=18.0, follows_view=False, wheel_zoom=False,
            tag="walker")
        # the map is already loaded: read its parts, dress them as it was
        self.dress.set_level(self.map)

    def _sparkler(self):
        """One emitter for the whole room, moved to whichever plate answered.

        A `Particle2D` draws in the scene's world pixels, so `size` here is
        pixels and `gravity` pulls down the screen: the same node, told in
        the flat world's own units.
        """
        self.sparks = self.spawn(
            fe.Particle2D, pos=(640.0, ROW_Y[0]), tag="sparks",
            texture="spark", amount=48, rate=0.0, lifetime=0.7,
            speed=180.0, spread=1.05, dir=(0.0, -1.0, 0.0),
            gravity=(0.0, 240.0, 0.0), drag=1.2, size=5.0, end_size=1.0,
            color=(1.0, 0.82, 0.45), end_color=(0.4, 0.1, 0.05),
            emitting=False)
        return self.sparks

    def spark_at(self, spot):
        """Burst the sparkler over a plate; returns how many sparks flew."""
        self.sparks.pos = [float(spot[0]), float(spot[1])]
        self.sparks.burst_particles(36)
        return self.sparks.count()

    def _readout(self):
        """The screen standing on the map's lectern."""
        panel = self.spawn(
            fe.Screen2D, pos=(640.0, 292.0), size=(320.0, 180.0),
            name="readout", pixels=(480, 270), brightness=1.05,
            tag="lectern_screen")
        self.dress.set_panel(panel)
        self.readout = panel
        return panel

    # -- the switches ----------------------------------------------------
    def _pads(self):
        for row, y in enumerate(ROW_Y):
            for label, trigger, part, says, x in SWITCHES[row]:
                card = (min(max(x, EDGE[0]), EDGE[1]), y - CARD_GAP)
                self.pads.append(
                    self.spawn(Pad, pos=(x, y), label=label,
                               trigger=trigger, part=part, says=says,
                               card_at=card, tag=f"pad_{trigger}"))

    # -- the map behind the room ------------------------------------------
    def map_index(self):
        """Which of this scene's maps is loaded, as an index."""
        name = getattr(self.map, "name", None) or self.map_name
        return MAPS.index(name) if name in MAPS else 0

    def next_map(self):
        """Swap to the next map, and stand where it says to start."""
        name = MAPS[(self.map_index() + 1) % len(MAPS)]
        self.change_map(name)
        self.note = f"the room is now {name}"
        return name

    def on_map_loaded(self, level):
        """A map arrived: dress its parts, then stand at its own start."""
        dress = getattr(self, "dress", None)
        if dress is None:
            return               # the first load runs before setup()
        dress.set_level(level)
        start, yaw = self.spawn_point()
        if self.player is not None and start is not None:
            self.player.teleport(start[:2], yaw)

    def on_map_unloaded(self, level):
        """The map is gone, so nothing may go on dressing it."""
        dress = getattr(self, "dress", None)
        if dress is not None and dress.level is level:
            dress.set_level(None)

    # -- the bus -----------------------------------------------------------
    def on_trigger(self, name, value=None):
        """One plate, or its key: re-dress a part, or swap the room."""
        if str(name) == "swap_map":
            self.next_map()
            return self.note
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
        self.hud.panel((area.x + 14, area.y + 12, 430, 66),
                       color=(13, 17, 29), alpha=195)
        self.hud.text("DEMO  /  THE ECHO ROOM",
                      (area.x + 26, area.y + 20),
                      color=(0.84, 0.7, 1.0))
        self.hud.text("WASD to walk  -  E for a switch  -  M swaps  -  Tab",
                      (area.x + 26, area.y + 45))
        if self.note:
            self.hud.text(self.note, (area.x + 14, area.y + area.h - 34),
                          color=(0.85, 0.9, 1.0))

    def status(self):
        name = getattr(self.map, "name", self.map_name)
        return [self.name, f"Echo Room / {name}", f"{len(self.lights)} lights",
                f"{len(self.pads)} switches", f"{self.sparks.count()} sparks"]
