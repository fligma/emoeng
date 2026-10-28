"""Screens: switches over the plinth that shows one scene inside a panel."""

from scripts.scenes.switchboard import Switchboard


class UiScreen(Switchboard):
    name = "ui_screen"
    title = "SCENES ON SCREENS"
    hint = "The panel runs another scene as a live picture."
    rows = (("picture", "panel_swap"), ("bezel", "panel_bezel"),
            ("pixels", "panel_pixels"), ("crosshair", "panel_cross"))
