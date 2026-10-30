"""Global constants for the Motion Engine."""

NAME = "emoeng"

CODENAME = "Motion Engine"

VERSION = "1.0.1"
__version__ = VERSION

TITLE = CODENAME

SUBTITLE = "Game engine and editor"

DESCRIPTION = (
    "Python game engine with editor."
)

ABOUT_LINES = (
    f"{CODENAME} ({NAME} {VERSION})",
    "Python game engine and editor.",
    "",
    "Vertex renderer (moderngl), .model files with an",
    "inbuilt model editor, Python scenes with syntax",
    "highlighting, assets browser, audio media player.",
)

AUTHOR = "fligma"
LICENSE = ""
WEBSITE = "https://github.com/fligma"
COPYRIGHT = "fligma 2026"

# the executable's name; imports stay `emoeng`
ENGINE_NAME = "MotionEngine"

USER_DIR_NAME = "MotionEngine"

PROJECTS_DIRNAME = "projects"

MANIFEST_NAME = "project.flig"

# optional project picture: badge, window icon, exe icon
ICON_NAME = "icon.png"

# bumped when the manifest layout changes
PROJECT_FORMAT = 2

# a project's own keymap and asset import settings
INPUT_MAP_NAME = "input.map.json"
ASSET_MAP_NAME = "assets.json"

GITIGNORE_NAME = ".gitignore"
README_NAME = "README.md"

DEFAULT_PROJECT = "demo"

SAVE_SLOT = "autosave"

# asset folder kinds; drives the Project View tree
KINDS = ("scenes", "objects", "entities", "scripts", "models", "maps",
         "textures", "audio")

# kinds that are importable Python packages
PACKAGES = ("scenes", "objects", "scripts")

BUILDER = "PyInstaller"

BUILD_META_KEY = "build"
