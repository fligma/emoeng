"""Baked light: switches for a block whose light the sun froze in."""

from scripts.scenes.switchboard import Switchboard


class UiBake(Switchboard):
    name = "ui_bake"
    title = "BAKED VS LIVE"
    rows = (("shift", "bake_move"), ("back", "bake_back"),
            ("re-bake", "bake_again"), ("twin", "bake_twin"))

    hint = "Move the model: its baked shade stays where it was."

    def status(self):
        """Say what the frozen map costs: the block moves, its shade does."""
        room = self.room()
        maps = getattr(room, "bakes", 0)
        return f"{maps} lightmap(s) frozen, nothing re-lit"
