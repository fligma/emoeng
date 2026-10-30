"""Walk the 3D hall; Tab opens its flat twin, M swaps the map.

The hall is a map file - `maps/hall.map3d` - carved into named parts, so
this script spawns only what rides on it: the lectern's screen, the player,
the readout and three particle emitters. A switch on the lectern, or its
key, puts a different sheet on one part while you stand in the room. M swaps
the whole map for the vault behind it: the geometry and the map's own lights
leave, the screen you were reading stays, whatever each part was wearing is
put back for you, and the swap itself throws a handful of sparks off the
lectern.
"""

import emoeng as fe
from scripts.scenes.dressing import Dresser, pull

EYE = 1.72

# the maps this scene swaps between, in the order M walks them
MAPS = ("hall", "vault")

# where the room's effects stand: a plinth's top, the air over the lectern,
# and the middle of the hall, read off the map's own nodes
BRAZIER = (-5.8, 1.05, -5.3)
FLARE = (0.0, 2.3, 0.4)
MIDDLE = (0.0, 3.0, -2.0)


class Main(fe.Scene3D):
    """Walk the 3D hall; Tab opens its 2D companion room."""

    name = "main"
    map_name = "hall"            # the level this scene opens on
    # a room's bindings stay after it is left, so the hall reclaims the two
    # the flat room borrows for walking: W and S steer there, not here
    actions = {"other_room": ["tab"], "up": ["space"],
               "down": ["q", "lctrl"]}
    controls = ("forward", "back", "left", "right", "run", "other_room")
    post = ()                    # the hall starts undressed
    world_radius = 0.0
    clear_color = (0.025, 0.035, 0.06)
    ambient = (0.32, 0.34, 0.42)
    sun_dir = (-0.3, 0.88, -0.5)
    sun_col = (0.35, 0.4, 0.62)
    fog_color = (0.025, 0.035, 0.06)
    fog_near = 18.0
    fog_far = 42.0

    def setup(self):
        self.dress = Dresser(self)
        self.state = {}          # trigger -> the one word its switch shows
        self.note = ""           # what the room last said over the bus
        self._panel()
        self._fx()
        start, yaw = self.spawn_point()
        self.player = self.spawn(
            fe.Player3D, pos=start, yaw=yaw, eye_height=EYE,
            move_speed=(3.6, 6.0), world_radius=0.0)
        # the map is already loaded: read its parts, dress them as it was
        self.dress.set_level(self.map)

    def _fx(self):
        """Three emitters: a plinth's embers, dust in the air, a swap's flare.

        Each is a plain `fe.Particle3D` with its knobs said here rather than
        in a document, and each shows a different thing an emitter can do:
        embers drip for ever along a narrow cone, dust hangs because its
        `emitting` is only switched on in the vault, and the flare waits for
        a `burst_particles` from the same word that swaps the map.
        """
        self.embers = self.spawn(
            fe.Particle3D, pos=BRAZIER, tag="embers", texture="spark",
            amount=64, rate=26.0, lifetime=2.4, speed=1.1, spread=0.3,
            dir=(0.0, 1.0, 0.0), gravity=(0.0, -0.5, 0.0), drag=0.5,
            size=0.14, end_size=0.02, color=(1.0, 0.6, 0.2),
            end_color=(0.35, 0.05, 0.02))
        self.dust = self.spawn(
            fe.Particle3D, pos=MIDDLE, tag="dust", texture="smoke",
            amount=90, rate=9.0, lifetime=6.0, speed=0.25, spread=1.2,
            dir=(0.0, 1.0, 0.0), gravity=(0.0, -0.02, 0.0), drag=0.9,
            size=0.06, color=(0.75, 0.78, 0.9), end_color=(0.2, 0.22, 0.3),
            blend="alpha", emitting=False, local_space=True)
        self.flare = self.spawn(
            fe.Particle3D, pos=FLARE, tag="flare", texture="spark",
            amount=48, rate=0.0, lifetime=0.9, speed=3.2, spread=1.1,
            gravity=(0.0, -2.4, 0.0), drag=1.2, size=0.16, end_size=0.0,
            color=(0.6, 0.9, 1.0), end_color=(0.1, 0.3, 0.6),
            emitting=False)

    def _panel(self):
        """The screen standing on the map's lectern, framed by the map."""
        panel = self.spawn(
            fe.Screen3D, pos=(0.0, 1.75, 0.42), yaw=0.0, size=(2.0, 1.125),
            tag="lectern_panel", name="lectern", pixels=(512, 288),
            brightness=1.08, input=True, audio_mode="global")
        self.dress.set_panel(panel)
        self.lectern = panel
        return panel

    # -- the map behind the room ------------------------------------------
    def map_index(self):
        """Which of this scene's maps is loaded, as an index."""
        name = getattr(self.map, "name", None) or self.map_name
        return MAPS.index(name) if name in MAPS else 0

    def next_map(self):
        """Swap to the next map, and stand where it says to start."""
        name = MAPS[(self.map_index() + 1) % len(MAPS)]
        # the swap says so out loud: the flare is fired by this same word
        self.flare.burst_particles(48)
        self.change_map(name)
        self.note = f"the room is now {name}"
        return name

    def on_map_loaded(self, level):
        """A map arrived: dress its parts, then stand at its own start."""
        dress = getattr(self, "dress", None)
        if dress is None:
            return               # the first load runs before setup()
        dress.set_level(level)
        # dust is only worth seeing in the vault's darker air
        self.dust.emitting = (getattr(level, "name", "") == "vault")
        start, yaw = self.spawn_point()
        if self.player is not None and start is not None:
            self.player.teleport(start, yaw)

    def on_map_unloaded(self, level):
        """The map is gone, so nothing may go on dressing it."""
        dress = getattr(self, "dress", None)
        if dress is not None and dress.level is level:
            dress.set_level(None)

    # -- the bus -----------------------------------------------------------
    def on_trigger(self, name, value=None):
        """One switch, or its key: re-dress a part, or swap the room."""
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
            self.play_scene("arcade")

    def overlay(self, screen):
        area = self.hud.area
        self.hud.panel((area.x + 14, area.y + 12, 380, 66),
                       color=(13, 17, 29), alpha=195)
        self.hud.text("DEMO  /  THE PRISM HALL",
                      (area.x + 26, area.y + 20),
                      color=(0.72, 0.9, 1.0))
        self.hud.text("WASD to walk  -  M swaps the map  -  Tab for 2D",
                      (area.x + 26, area.y + 45))
        # the crosshair is the pointer: the lectern answers a look and a click
        self.hud.crosshair()
        if self.note:
            self.hud.text(self.note, (area.x + 14, area.y + area.h - 34),
                          color=(0.85, 0.9, 1.0))

    def status(self):
        name = getattr(self.map, "name", self.map_name)
        return [self.name, f"Prism Hall / {name}",
                f"{len(self.lights)} lights",
                f"{self.embers.count() + self.dust.count()} points"]
