"""Engine modules: rendering, scenes, objects, models, audio, input and"""

from . import (anim, audio, camera, collision, colors, components, config,
               input, inputmap, lights, loader, meshes, model, objects,
               paths, player, proctex, renderer, save, scene, scenedoc,
               sfx, shaders, templates, theme, timers, ui, winchrome, xp)
from .camera import Camera, Camera2D, OrbitCamera
from .components import (AudioEmitter2D, AudioEmitter3D, Collision2D,
                         Collision3D, ConeLight2D, DirectionalLight3D,
                         Hitbox2D, Hitbox3D, LightNode2D, LightNode3D,
                         Marker2D, Marker3D, Model3D, OmniLight3D,
                         PointLight2D, RectLight2D, Sprite2D, SpotLight3D,
                         Text2D, Text3D, Timer2D, Timer3D, Trigger2D,
                         Trigger3D)
from .input import Input
from .inputmap import InputMap
from .lights import Light, Light2D, Light3D
from .loader import Project
from .model import Model, new_model
from .objects import (Entity2D, Entity3D, GameObject, ModelObject, Object2D,
                      Object3D, UIObject)
from .player import Player, Player2D, Player3D
from .renderer import DynamicMesh, Renderer
from .save import SaveStore
from .scene import Scene, Scene2D, Scene3D, SceneUI
from .timers import Timer, Timers

# tooling names, imported on first attribute access
_TOOLS = {"build": "BuildConfig", "prune": None}
_TOOL_OF = {name: module for module, name in _TOOLS.items() if name}

__all__ = [
    "anim", "audio", "build", "camera", "collision", "colors", "components",
    "config",
    "input", "inputmap", "lights", "loader", "meshes", "model", "objects",
    "paths",
    "player",
    "prune", "proctex", "renderer", "save", "scene", "scenedoc", "sfx",
    "shaders", "templates", "theme", "timers",
    "ui", "winchrome", "xp", "BuildConfig", "Camera", "Camera2D",
    "OrbitCamera", "Input", "InputMap",
    "Project", "Model", "new_model", "DynamicMesh", "Renderer", "SaveStore",
    "GameObject", "Object2D", "Object3D", "Entity2D", "Entity3D",
    "UIObject", "ModelObject",
    "Collision2D", "Collision3D", "Hitbox2D", "Hitbox3D", "LightNode2D",
    "LightNode3D", "Model3D", "Sprite2D",
    "OmniLight3D", "SpotLight3D", "DirectionalLight3D", "PointLight2D",
    "ConeLight2D", "RectLight2D", "AudioEmitter3D", "AudioEmitter2D",
    "Text3D", "Text2D", "Timer3D", "Timer2D", "Trigger3D", "Trigger2D",
    "Marker3D", "Marker2D",
    "Light", "Light2D", "Light3D",
    "Player", "Player2D", "Player3D", "Scene", "Scene2D", "Scene3D",
    "SceneUI", "Timer", "Timers",
]


def _tool(name):
    """Import a tooling submodule and cache it as an attribute."""
    import importlib
    module = importlib.import_module(f".{name}", __name__)
    globals()[name] = module
    return module


def __getattr__(name):
    """PEP 562: serve the authoring tools without importing them eagerly."""
    if name in _TOOLS:
        return _tool(name)
    module = _TOOL_OF.get(name)
    if module is not None:
        return getattr(_tool(module), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
