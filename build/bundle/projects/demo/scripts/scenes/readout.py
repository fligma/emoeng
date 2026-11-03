"""The 2D room's lectern: a display of what the room is wearing.

The flat room cannot host clickable switches inside a picture - a 2D panel
takes no mouse - so its lectern tells rather than asks: two lines listing
every part and the look it currently wears. The switches themselves are the
plates on the floor, and what the room last answered is written under the
HUD's title, where a walker is already looking.
"""

from scripts.scenes.panel import Panel

# the parts, in the order a walker reads the plates, as the two lines the
# picture has room for: four surfaces, then the rest and the two levers
# that dress a whole picture
ROWS = (("floor", "walls", "arches", "portals"),
        ("props", "lectern", "screen", "room"))


def row(words, parts):
    """`part:word` for each part, in one line of the picture."""
    return "   ".join(f"{part}:{words.get(part, 'plain')}" for part in parts)


class Readout(Panel):
    name = "readout"
    # the picture starts plain: no screen shader until one is switched on
    post = ()

    def lines(self):
        room = self.room()
        dress = getattr(room, "dress", None)
        if room is None or dress is None:
            return ("echo room", "no room above this panel", "")
        words = dress.words()
        # what the room last said is on the HUD, so the picture spends all
        # three lines on what the room is wearing
        return (f"{room.name.upper()}  /  what the room wears",
                row(words, ROWS[0]),
                row(words, ROWS[1]))
