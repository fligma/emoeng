"""Sound: every synthesised voice the demo owns, and the two volumes."""

from scripts.scenes.switchboard import Switchboard


class UiSound(Switchboard):
    name = "ui_sound"
    title = "SOUND BOOTH"
    hint = "Hear generated tones and distance-based 3D audio."
    rows = (("tone", "sound_blip"), ("sweep", "sound_sweep"),
            ("noise", "sound_noise"), ("loop", "sound_loop"),
            ("master", "sound_master"), ("music", "sound_music"),
            ("stop", "sound_stop"))
