"""Readout: words standing in the world that repeat what the bus said.

The arch's `enter` and `exit` knobs broadcast with no script at all, so
this is the other half of that story: a node that answers a broadcast on
its own. `Scene.broadcast` calls the scene first and every object with an
`on_trigger` after, so the room's line is already written when these
words are painted.
"""

import emoeng as fe


class Readout(fe.Text3D):
    name = "readout"

    def build(self):
        super().build()
        note = str(getattr(self.scene, "note", "") or "")
        if note:
            self.set_text(note)
        return self

    def on_trigger(self, name, value=None):
        """Say whatever the room just said, or the bare name if it said
        nothing."""
        note = str(getattr(self.scene, "note", "") or "")
        return self.set_text(note or str(name))
