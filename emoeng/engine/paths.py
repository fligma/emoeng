"""Where files live, from source or a frozen build."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from .. import const

PROJECTS = const.PROJECTS_DIRNAME


def _xdg_home(variable, fallback):
    """Use an XDG base directory only when it is an absolute path."""
    raw = os.environ.get(variable, "")
    path = Path(raw).expanduser() if raw else Path(fallback).expanduser()
    return path if path.is_absolute() else Path(fallback).expanduser()


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
    """Folder holding this package (…/emoeng)."""
    return Path(__file__).resolve().parents[1]


def app_dir():
    """Writable folder the game was launched from."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return package_root().parent


def legacy_user_dir():
    """The pre-XDG per-user folder, retained as a migration source."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / const.USER_DIR_NAME
    return Path.home() / f".{const.USER_DIR_NAME.lower()}"


def config_dir():
    """Per-user configuration folder."""
    override = os.environ.get("EMOTION_ENGINE_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("linux"):
        base = _xdg_home("XDG_CONFIG_HOME", "~/.config")
        return base / const.USER_DIR_NAME
    return user_dir()


def user_dir():
    """Per-user data folder, migrating files from the legacy location."""
    override = os.environ.get("EMOTION_ENGINE_HOME")
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / const.USER_DIR_NAME
    elif sys.platform.startswith("linux"):
        base = _xdg_home("XDG_DATA_HOME", "~/.local/share")
        path = base / const.USER_DIR_NAME
    else:
        path = legacy_user_dir()
    legacy = legacy_user_dir()
    path.mkdir(parents=True, exist_ok=True)
    marker = path / ".legacy_data_migrated"
    if not override and path != legacy and legacy.is_dir() \
            and not marker.exists():
        def copy_missing(source, target):
            target = Path(target)
            if target.exists():
                return str(target)
            return shutil.copy2(source, target)

        shutil.copytree(legacy, path, dirs_exist_ok=True, symlinks=True,
                        copy_function=copy_missing)
        marker.touch()
    return path


def bundled_projects():
    """Projects shipped inside the package / build."""
    for base in (package_root(), bundle_dir() / const.NAME):
        candidate = base / PROJECTS
        if candidate.is_dir():
            return candidate
    return package_root() / PROJECTS


def bundled_docs():
    """Documentation shipped inside the package / build."""
    for base in (package_root(), bundle_dir() / const.NAME):
        candidate = base / "docs"
        if candidate.is_dir():
            return candidate
    return package_root() / "docs"


def bundled_fonts():
    """Fonts shipped inside the package / build."""
    for base in (package_root(), bundle_dir() / const.NAME):
        candidate = base / "fonts"
        if candidate.is_dir():
            return candidate
    return package_root() / "fonts"


def projects_dir():
    """The projects folder to use right now."""
    override = os.environ.get("EMOTION_PROJECTS")
    if override:
        path = Path(override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    if not frozen():
        return bundled_projects()
    local = app_dir() / PROJECTS
    if not writable(local):
        local = user_dir() / PROJECTS
        if not writable(local):
            raise OSError(f"no writable projects directory: {local}")
    if not local.is_dir() or not any(local.iterdir()):
        source = bundled_projects()
        if source.is_dir() and source != local:
            for item in source.iterdir():
                target = local / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
    return local


def writable(folder):
    """Best-effort check before writing into a possibly read-only root."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".write_test_"):
            pass
        return True
    except OSError:
        return False
