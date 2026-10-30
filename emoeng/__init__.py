"""emoeng - the Motion Engine game engine."""

from . import const
from .const import (NAME, CODENAME, VERSION, TITLE, SUBTITLE,  # noqa: F401
                     DESCRIPTION, ABOUT_LINES, AUTHOR, LICENSE,
                     WEBSITE, COPYRIGHT, ENGINE_NAME, USER_DIR_NAME,
                     PROJECTS_DIRNAME, MANIFEST_NAME, DEFAULT_PROJECT,
                     SAVE_SLOT, BUILDER, BUILD_META_KEY)

# the one source of truth is `const.VERSION`
__version__ = const.VERSION

from .engine import (anim, audio, camera, collision, colors, components,
                     config,  # noqa
                     input, inputmap, level, lights, loader, mapdoc, meshes,
                     model, objects, particles, paths, placement, player,
                     proctex, renderer, save, scene, scenedoc, sfx, shaders,
                     screen, templates, theme, timers, ui, winchrome, xp)
from .engine.camera import Camera, Camera2D, CameraHost, OrbitCamera
from .engine.components import (AudioEmitter2D, AudioEmitter3D,
                                Collision2D, Collision3D, ConeLight2D,
                                DirectionalLight3D, Hitbox2D, Hitbox3D,
                                LightNode2D, LightNode3D, Map2D, Map3D,
                                Marker2D, Marker3D, Model3D, OmniLight3D,
                                Particle2D, Particle3D, PointLight2D,
                                RectLight2D, SpotLight3D, Sprite2D, Text2D,
                                Text3D, Timer2D, Timer3D, Trigger2D,
                                Trigger3D)
from .engine.game import Game
from .engine.input import Input
from .engine.inputmap import InputMap
from .engine.level import MapLevel
from .engine.lights import Light, Light2D, Light3D
from .engine.loader import Project
from .engine.model import Model, new_model
from .engine.objects import (Entity2D, Entity3D, GameObject, ModelObject,
                             Object2D, Object3D, UIObject)
from .engine.player import Player, Player2D, Player3D
from .engine.renderer import Renderer
from .engine.save import SaveStore
from .engine.screen import Screen2D, Screen3D
from .engine.scene import Scene, Scene2D, Scene3D, SceneUI
from .engine.shaders import Shader
from .engine.timers import Timer, Timers


def main(argv=None):
    from .__main__ import main as run
    return run(argv)


__all__ = [
    "anim", "audio", "camera", "collision", "colors", "components",
    "config",
    "input", "inputmap", "level", "lights", "loader", "mapdoc", "meshes",
    "model", "objects", "particles", "paths", "placement", "player",
    "proctex", "renderer", "save", "scene", "sfx", "screen",
    "scenedoc", "shaders", "templates", "theme",
    "timers", "ui", "winchrome",
    "xp", "Camera", "Camera2D", "CameraHost",
    "OrbitCamera", "Game", "Input", "Project", "Model", "new_model",
    "Renderer", "SaveStore", "GameObject", "Object2D", "Object3D",
    "Entity2D", "Entity3D", "UIObject", "ModelObject", "Light", "Light2D",
    "Light3D",
    "Shader",
    "Player", "Player2D", "Player3D", "Screen2D", "Screen3D",
    "Collision2D", "Collision3D", "Hitbox2D", "Hitbox3D", "LightNode2D",
    "LightNode3D", "Model3D", "Sprite2D", "OmniLight3D", "SpotLight3D",
    "DirectionalLight3D", "PointLight2D", "ConeLight2D", "RectLight2D",
    "AudioEmitter3D", "AudioEmitter2D", "Text3D", "Text2D", "Timer3D",
    "Timer2D", "Trigger3D", "Trigger2D", "Marker3D", "Marker2D",
    "Particle3D", "Particle2D", "Map2D", "Map3D", "MapLevel",
    "InputMap",
    "Scene", "Scene2D", "Scene3D",
    "SceneUI", "Timer", "Timers", "main", "const",
    "NAME", "CODENAME", "VERSION", "TITLE", "SUBTITLE", "DESCRIPTION",
    "ABOUT_LINES", "AUTHOR", "LICENSE", "WEBSITE", "COPYRIGHT",
    "ENGINE_NAME", "USER_DIR_NAME", "PROJECTS_DIRNAME", "MANIFEST_NAME",
    "DEFAULT_PROJECT", "SAVE_SLOT", "BUILDER", "BUILD_META_KEY",
    "__version__",
]
