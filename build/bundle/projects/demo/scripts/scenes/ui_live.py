"""Live lights: the switches over the three lamps that light in real time."""

from scripts.scenes.switchboard import Switchboard


class UiLive(Switchboard):
    name = "ui_live"
    title = "3D LIGHT LAB"
    hint = "Live lights change the room immediately."
    rows = (("warm", "live_warm"), ("cool", "live_cool"),
            ("spot", "toggle_spot"), ("sweep", "live_sweep"),
            ("dim", "live_dim"))
