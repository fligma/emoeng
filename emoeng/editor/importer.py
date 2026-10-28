"""Bring files that live outside the project into it."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..engine import scenedoc

# a folder beside the project for unconverted files
RAW_SUBDIR = Path(".ignored") / "raw"

IMAGE_EXTS = (".png", ".jpg", ".jpeg")
AUDIO_EXTS = (".wav", ".ogg", ".mp3", ".flac", ".opus")
MODEL_EXTS = (scenedoc.MODEL3D_EXT, scenedoc.MODEL2D_EXT,
              scenedoc.MODEL_EXT)


def categorise(path):
    """'textures', 'models', 'audio' or 'raw', by suffix."""
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "textures"
    if suffix in AUDIO_EXTS:
        return "audio"
    if suffix in MODEL_EXTS:
        return "models"
    return "raw"


def _unique(dest):
    """`name.ext`, then `name_2.ext`, `name_3.ext`... a free slot."""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    for i in range(2, 1000):
        guess = dest.with_name(f"{stem}_{i}{suffix}")
        if not guess.exists():
            return guess
    return dest


def import_files(project, src_paths):
    """Copy each file into the folder its kind lives in."""
    made, staged = [], []
    for src in src_paths:
        src = Path(src)
        if not src.is_file():
            continue
        kind = categorise(src)
        folder = project.path / RAW_SUBDIR if kind == "raw" \
            else project.dir(kind)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            dest = _unique(folder / src.name)
            shutil.copy2(src, dest)
        except OSError:
            continue
        (staged if kind == "raw" else made).append(dest)
    return made, staged


# the OS chooser's filters, engine extensions included
FILETYPES = (
    ("All files", "*.*"),
    ("Images", "*.png;*.jpg;*.jpeg"),
    ("Sounds", "*.wav;*.ogg;*.mp3;*.flac;*.opus"),
    ("Models", "*.model3d;*.model2d;*.model"),
)


def browse(title="Import asset", filetypes=None, multiple=True):
    """Open the native file chooser; hand back the chosen paths."""
    try:
        import tkinter
        from tkinter import filedialog
    except Exception:
        return []
    root = None
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        kinds = filetypes or FILETYPES
        if multiple:
            picked = filedialog.askopenfilenames(parent=root, title=title,
                                                 filetypes=kinds)
        else:
            one = filedialog.askopenfilename(parent=root, title=title,
                                             filetypes=kinds)
            picked = (one,) if one else ()
    except Exception:
        return []
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
    return [Path(p) for p in picked if p]
