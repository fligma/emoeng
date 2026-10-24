"""Where files live, both from source and from a frozen PyInstaller build.

Three roots matter:

    package_root()  the fligengine package itself (read-only once frozen)
    app_dir()       the exe's folder when frozen, the repo root in source
    user_dir()      a writable per-user folder for saves and settings

Projects are the interesting case: in source they sit in
`fligengine/projects`, but a frozen build cannot write next to its
read-only bundle, so the first run copies the bundled projects into a
`projects` folder beside the executable and uses that from then on.
"""

import os
import shutil
import sys
from pathlib import Path

PROJECTS = "projects"


def frozen():
    """True inside a PyInstaller one-file / one-dir build."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir():
    """The read-only root the build was unpacked into."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return package_root().parent


def package_root():
    """Folder holding this package (…/fligengine)."""
    return Path(__file__).resolve().parents[1]


def app_dir():
    """Writable folder the game was launched from."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return package_root().parent


def user_dir():
    """Per-user scratch space for saves and settings."""
    override = os.environ.get("EMOTION_ENGINE_HOME")
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / "EmotionEngine"
    else:
        path = Path.home() / ".emotion_engine"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_projects():
    """Projects shipped inside the package / build."""
    for base in (package_root(), bundle_dir() / "fligengine"):
        candidate = base / PROJECTS
        if candidate.is_dir():
            return candidate
    return package_root() / PROJECTS


def projects_dir():
    """The projects folder to use right now.

    In source this is the package folder. Frozen, it is a writable copy
    beside the exe, seeded from the bundle on first run.
    """
    override = os.environ.get("EMOTION_PROJECTS")
    if override:
        path = Path(override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    if not frozen():
        return bundled_projects()
    local = app_dir() / PROJECTS
    if not local.is_dir() or not any(local.iterdir()):
        source = bundled_projects()
        try:
            local.mkdir(parents=True, exist_ok=True)
            if source.is_dir() and source != local:
                for item in source.iterdir():
                    target = local / item.name
                    if item.is_dir():
                        shutil.copytree(item, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, target)
        except OSError:
            pass
    local.mkdir(parents=True, exist_ok=True)
    return local


def writable(folder):
    """Best-effort check before writing into a possibly read-only root."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
