"""Poster: the second picture - a print, and one quad that moves by itself.

Swapping `panel` for `poster` and back is the point: a screen shows any
scene in the project, and the scene it shows need not know it is small.
"""

import math

import emoeng as fe
from emoeng.engine import meshes


class Poster(fe.SceneUI):
    name = "poster"
    clear_color = (0.10, 0.06, 0.12)
    post = ()                      # a print on paper, not a screen

    def setup(self):
        w, h = self.window_size
        cx, cy = w / 2.0, h / 2.0
        self.add(meshes.rect2d((cx, cy), (w, h), col=(0.17, 0.10, 0.18)),
                 texture="white", blend="alpha")
        self.head = self.spawn(fe.UIObject, (cx, h * 0.28),
                               size=(w - 30.0, 26.0), text="second picture",
                               font_size=16, color="#2a1b31",
                               text_color=(0.96, 0.88, 0.94))
        self.bar = self.spawn(fe.UIObject, (cx, h * 0.56),
                              size=(w * 0.58, 12.0), text="",
                              color=(0.82, 0.46, 0.28))
        self.foot = self.spawn(fe.UIObject, (cx, h * 0.80),
                               size=(w - 30.0, 18.0),
                               text="a scene inside a screen inside a room",
                               font_size=10, color="#241a2b",
                               text_color=(0.80, 0.72, 0.84))
        self._left = cx - w * 0.29
        self._span = w * 0.58

    def update(self, dt):
        super().update(dt)
        # one quad slides on its own, so the picture is plainly live
        k = 0.5 + 0.5 * math.sin(self.t * 0.9)
        self.bar.set(pos=(self._left + self._span * k, self.bar.pos[1]))
