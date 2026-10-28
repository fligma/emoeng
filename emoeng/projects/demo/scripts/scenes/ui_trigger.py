"""Triggers: switches over the arch that broadcasts by itself."""

from scripts.scenes.switchboard import Switchboard


class UiTrigger(Switchboard):
    name = "ui_trigger"
    title = "TRIGGERS & SAVES"
    hint = "Walk through the arch to fire a scene trigger."
    rows = (("remember", "arch_remember"), ("mark", "arch_mark"),
            ("write", "arch_write"), ("read", "arch_read"),
            ("list", "arch_list"), ("leave", "arch_out"))
