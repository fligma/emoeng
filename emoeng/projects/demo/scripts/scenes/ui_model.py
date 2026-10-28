"""Models: switches over the sigil - spin, tint, scale, sheet and tile."""

from scripts.scenes.switchboard import Switchboard


class UiModel(Switchboard):
    name = "ui_model"
    title = "3D MODELS"
    hint = "Change one model's transform and material at runtime."
    rows = (("spin", "model_spin"), ("tint", "model_tint"),
            ("scale", "model_scale"), ("sheet", "model_sheet"),
            ("tile", "model_tile"))
