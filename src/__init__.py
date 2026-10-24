"""fligengine, codename Emotion Engine: a PS2-style Python game engine
with its own XP-themed IDE.

A game is a project folder:

    project.flig        manifest (title, start scene, render scale, post)
    scenes/*.py         SceneBase subclasses - the game logic
    entities/*.py       Entity subclasses - the props a scene spawns
    scripts/*.py        shared python modules
    models/*.model      vertex/face meshes, built in the Model tab
    textures/*.png      uploaded to the renderer by file stem
    audio/*.wav|ogg     loaded into the audio bank by file stem

The engine renders every frame with the vertex batcher in `renderer`,
shows it in the Luna-chrome window from `game`, and the editor in
`editor.app` edits the same files the runtime loads.

    import fligengine as fe

    class Main(fe.SceneBase):
        uses = ("bonfire",)

        def setup(self):
            self.fire = self.spawn("bonfire", (0, 0, 0))
            self.fire.clone((3.0, 0.0, 0.0))
"""

__version__ = "1.1.0"
CODENAME = "Emotion Engine"

from .engine import (anim, audio, camera, collision, entity, fx, input,  # noqa
                     loader, meshes, model, paths, proctex, renderer, save,
                     scene, theme, timers, ui, winchrome, xp)
from .engine.camera import Camera, OrbitCamera
from .engine.entity import Entity, ModelObject
from .engine.game import Game
from .engine.input import Input
from .engine.loader import Project
from .engine.model import Model, new_model
from .engine.renderer import Renderer
from .engine.save import SaveStore
from .engine.scene import SceneBase
from .engine.timers import Timer, Timers


def main(argv=None):
    from .__main__ import main as run
    return run(argv)


__all__ = [
    "anim", "audio", "camera", "collision", "entity", "fx", "input",
    "loader", "meshes", "model", "paths", "proctex", "renderer", "save",
    "scene", "theme", "timers", "ui", "winchrome", "xp", "Camera",
    "OrbitCamera", "Game", "Input", "Project", "Model", "new_model",
    "Renderer", "SaveStore", "Entity", "ModelObject", "SceneBase",
    "Timer", "Timers", "main", "CODENAME",
]
