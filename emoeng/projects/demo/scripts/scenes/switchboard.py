"""Switchboard: the base every plinth's control panel is cut from.

A board of labelled switches that all do the same one thing: broadcast a
trigger into the room it hangs in. A click on a panel and a press of a
key therefore travel the same road, which is the point of the showcase -
the demo drives its own features through the trigger bus, not through a
bespoke call per switch.

A subclass declares `rows`, `title` and `hint` and is done; it overrides
`lines()` or `status()` only when a switch needs more than one word.
"""

import emoeng as fe
from emoeng.engine import meshes

PER_ROW = 3                    # switches across a row
BUTTON_H = 26.0                # a switch's height, in panel pixels
WIDE = 34.0                    # row pitch when a board has few switches
TIGHT = 28.0                   # ... and when it has many


class Switchboard(fe.SceneUI):
    """Rows of switches, one title, one line of readout."""

    name = "switchboard"
    clear_color = (0.05, 0.065, 0.09)
    post = ("scanlines",)          # the picture wears a screen shader

    title = "switchboard"
    hint = "click a switch"
    rows = ()                      # ((label, trigger name), ...) per board

    def setup(self):
        w, h = self.window_size
        cx = w / 2.0
        self.add(meshes.rect2d((cx, h / 2.0), (w, h),
                               col=(0.10, 0.13, 0.18)),
                 texture="white", blend="alpha")
        self.spawn(fe.UIObject, (cx, h * 0.13), size=(w - 28.0, 20.0),
                   text=self.title, font_size=12, color="#1b2431",
                   text_color=(0.95, 0.92, 0.82))
        self._pitch = WIDE if len(self.rows) <= PER_ROW else TIGHT
        self._top = h * 0.32
        self.buttons = [self._slot(i, label, trigger)
                        for i, (label, trigger) in enumerate(self.rows)]
        self.readout = self.spawn(fe.UIObject, (cx, h * 0.83),
                                  size=(w - 20.0, 18.0), font_size=10,
                                  color="#16202c",
                                  text_color=(0.80, 0.86, 0.94))
        self._lines = None
        self._status = None

    def _slot(self, index, label, trigger):
        """One switch, placed in the grid and bound to one trigger."""
        w, _h = self.window_size
        gap = w / (PER_ROW + 1.0)
        row, col = divmod(index, PER_ROW)
        count = min(PER_ROW, len(self.rows) - row * PER_ROW)
        first = w / 2.0 - gap * (count - 1) / 2.0
        return self.spawn(fe.UIObject, (first + col * gap,
                                        self._top + row * self._pitch),
                          size=(gap * 0.92, BUTTON_H), text=label,
                          font_size=11, color="#22303f",
                          hover_color="#4a5f78", press_color="#7fb2dc",
                          action=lambda trip=trigger: self.press(trip))

    # -- the room this board talks to ---------------------------------------
    def room(self):
        """The 3D scene this panel hangs in, or None."""
        panel = getattr(self.game, "owner", None)
        return getattr(panel, "scene", None)

    def press(self, trigger):
        """A click is a press: ask the room to broadcast that trigger."""
        room = self.room()
        return None if room is None else room.broadcast(trigger)

    # -- what the board shows ------------------------------------------------
    def line(self, label, trigger):
        room = self.room()
        game = getattr(room, "game", None)
        key_text = getattr(game, "key_text", None)
        binding = str(key_text(trigger) or "") if callable(key_text) else ""
        state = (getattr(room, "state", None) or {}).get(trigger, "")
        parts = (label, f"[{binding}]" if binding else "", str(state or ""))
        return " ".join(part for part in parts if part)

    def lines(self):
        """One line per switch, in reading order."""
        return tuple(self.line(label, trigger)
                     for label, trigger in self.rows)

    def status(self):
        """What the room last said over the bus, else this board's hint."""
        return str(getattr(self.room(), "note", "") or "") or self.hint

    def update(self, dt):
        super().update(dt)
        lines = self.lines()
        # a label uploads a texture only when its own line changes
        if lines != self._lines:
            self._lines = lines
            for btn, line in zip(self.buttons, lines):
                btn.set_text(line)
        status = self.status()
        if status != self._status:
            self._status = status
            self.readout.set_text(status)
