"""Shaders: switches over the cube that slides its own sheet."""

from scripts.scenes.switchboard import Switchboard


class UiShader(Switchboard):
    name = "ui_shader"
    title = "SHADERS"
    hint = "Compare a mesh shader with a full-screen post effect."
    rows = (("post", "shader_post"), ("speed", "shader_speed"),
            ("hue", "shader_hue"), ("anchor", "shader_anchor"))
