"""The hall's lectern: nine switches for the nine things a room can wear.

Six of them re-dress one surface - the floor, the walls, the arches, the
portals, the plinths, the lectern itself. Two dress the picture rather than
a surface: the hall's whole frame, and the panel's own. The last puts
everything back to plain. Each switch broadcasts a trigger, so the same
thing happens when you click it as when you press its key, and the board
shows both the key and what the room answered.
"""

from scripts.scenes.switchboard import Switchboard


class Lectern(Switchboard):
    name = "lectern"
    # the panel starts with no screen shader of its own: a plain picture
    post = ()
    title = "PRISM LECTERN"
    hint = "click a switch, or press its key"
    rows = (("floor", "look_floor"),
            ("walls", "look_walls"),
            ("arches", "look_arches"),
            ("portals", "look_portals"),
            ("plinths", "look_props"),
            ("lectern", "look_lectern"),
            ("screen", "look_screen"),
            ("room", "look_room"),
            ("clear", "look_clear"))
