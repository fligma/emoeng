"""Panel: the first picture the screen showcase shows - the room's numbers."""

import emoeng as fe
from emoeng.engine import meshes


class Panel(fe.SceneUI):
    name = "panel"
    clear_color = (0.06, 0.075, 0.10)
    post = ("scanlines",)          # the picture wears a screen shader

    def setup(self):
        w, h = self.window_size
        cx = w / 2.0
        self.add(meshes.rect2d((cx, h / 2.0), (w, h),
                               col=(0.10, 0.13, 0.18)),
                 texture="white", blend="alpha")
        self.head = self._line(cx, h * 0.18, 13, (0.95, 0.92, 0.82),
                               "#1b2431")
        self.body = self._line(cx, h * 0.50, 11, (0.80, 0.86, 0.94),
                               "#16202c")
        self.foot = self._line(cx, h * 0.82, 10, (0.62, 0.72, 0.84),
                               "#141c26")
        self._shown = None

    def _line(self, x, y, size, text_color, color):
        w, _h = self.window_size
        return self.spawn(fe.UIObject, (x, y), size=(w - 28.0, 20.0),
                          text="", font_size=size, color=color,
                          text_color=text_color)

    def room(self):
        """The 3D scene this picture hangs in, or None."""
        panel = getattr(self.game, "owner", None)
        return getattr(panel, "scene", None)

    def lines(self):
        """What the room is made of, and what it last said over the bus."""
        room = self.room()
        if room is None:
            return ("motion engine", "no room above this panel", "")
        return (f"{room.name}: what the room keeps",
                f"{len(room.objects)} objects, {len(room.lights)} lights",
                str(getattr(room, "note", "") or "nothing pressed yet"))

    def update(self, dt):
        super().update(dt)
        lines = self.lines()
        # a label uploads a texture only when its line changes
        if lines == self._shown:
            return
        self._shown = lines
        for box, line in zip((self.head, self.body, self.foot), lines):
            box.set_text(line)
