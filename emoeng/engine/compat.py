"""What this machine's graphics really offers, written down to be read.

The engine draws through ModernGL and every shader is GLSL 330, so a
machine that cannot offer OpenGL 3.3 opens onto a black window. That is
impossible to see from the outside, so this module probes the stack at
startup, keeps a `gpureport.txt` in the user's folder as a trace, and
sorts the findings into plain warnings. `python -m emoeng check` runs
the same probe without opening any window at all.
"""

import os
import platform
import sys
import time
from pathlib import Path

import pygame

from .. import __version__
from . import paths

REPORT_NAME = "gpureport.txt"
GL_NEEDED = (3, 3)
SOFTWARE_WORDS = ("llvmpipe", "softpipe", "svpipe", "swiftshader",
                  "gallium", "software", "basic render", "gdi generic")


def standalone():
    """A fresh offscreen GL context; EGL first on Linux, where GLX
    takes seconds and can stall a window that is waiting for it."""
    import moderngl
    tries = ["egl", None] if sys.platform.startswith("linux") else [None]
    last = None
    for backend in tries:
        try:
            if backend is None:
                return moderngl.create_standalone_context()
            return moderngl.create_standalone_context(backend=backend)
        except Exception as exc:
            last = exc
    raise last


def probe():
    """Every fact worth knowing about this machine, errors included."""
    try:
        driver = pygame.display.get_driver()
    except pygame.error:
        driver = ""            # the video system is not open, and that
                               # is itself a fact worth reporting
    rep = {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
           "os": platform.platform(),
           "python": sys.version.split()[0],
           "engine": __version__,
           "frozen": str(paths.frozen()),
           "pygame": getattr(getattr(pygame, "version", None), "ver",
                             "?"),
           "sdl_video": os.environ.get("SDL_VIDEODRIVER")
                        or driver or "not started",
           "moderngl": "missing",
           "gl_error": "",
           "gl_version": "",
           "gl_vendor": "",
           "gl_renderer": "",
           "glsl": "",
           "max_texture": ""}
    try:
        import moderngl
    except Exception as exc:
        rep["gl_error"] = f"moderngl cannot be imported: {exc!r}"
        return rep
    try:
        rep["moderngl"] = getattr(moderngl, "__version__", "?")
    except Exception:
        pass
    ctx = None
    try:
        ctx = standalone()
        rep["gl_version"] = str(ctx.info.get("GL_VERSION", ""))
        rep["gl_vendor"] = str(ctx.info.get("GL_VENDOR", ""))
        rep["gl_renderer"] = str(ctx.info.get("GL_RENDERER", ""))
        # the info block often lacks the GLSL string; on a modern core
        # profile the GL version code is the GLSL version number too
        rep["glsl"] = (str(ctx.info.get("GL_SHADING_LANGUAGE_VERSION", ""))
                       or str(ctx.version_code))
        rep["max_texture"] = str(ctx.info.get("GL_MAX_TEXTURE_SIZE", ""))
        rep["gl_api"] = "%d.%d" % (ctx.version_code // 100,
                                   ctx.version_code % 100)
    except Exception as exc:
        rep["gl_error"] = " ".join(str(exc).split())[:300] or repr(exc)
    finally:
        try:
            if ctx is not None:
                ctx.release()
        except Exception:
            pass
    return rep


def version_pair(rep):
    """(major, minor) of the reported GL, or None when there is none."""
    got = rep.get("gl_api")
    if got:
        try:
            return tuple(int(part) for part in str(got).split(".")[:2])
        except ValueError:
            pass
    for source in (rep.get("gl_version"), rep.get("glsl")):
        for word in str(source or "").replace("OpenGL", " ").split():
            if word[:1].isdigit() and "." in word:
                try:
                    major, minor = word.split(".")[:2]
                    return int(major), int(minor)
                except ValueError:
                    continue
    return None


def is_software(rep):
    """True when no real GPU is doing the drawing."""
    needle = str(rep.get("gl_renderer", "")).lower()
    return any(word in needle for word in SOFTWARE_WORDS)


def verdict(rep):
    """What these facts mean for this engine, worst first."""
    out = []
    if rep.get("gl_error"):
        out.append(f"no OpenGL context could be made ({rep['gl_error']}); "
                   "update or enable the graphics driver")
        return out
    pair = version_pair(rep)
    if pair is None:
        out.append("the OpenGL version could not be read")
    elif pair < GL_NEEDED:
        out.append(f"OpenGL {'.'.join(map(str, pair))} found; the engine "
                   "needs 3.3 or newer, so the window will stay black")
    if is_software(rep):
        out.append(f"software rendering ({rep.get('gl_renderer')}); "
                   "it works, but expect low frame rates")
    try:
        big = int(rep.get("max_texture") or 0)
    except ValueError:
        big = 0
    if 0 < big < 2048:
        out.append(f"the largest texture is only {big}px; large sheets "
                   "will fail to upload")
    return out


def summary(rep):
    """One honest line about the machine, for a log or a status bar."""
    warns = verdict(rep)
    pair = version_pair(rep)
    head = (f"OpenGL {pair[0]}.{pair[1]} on {rep.get('gl_renderer') or '?'}"
            if pair else "graphics: no OpenGL context")
    return head + (" - " + warns[0] if warns else "")


def lines(rep=None):
    """The full report, one line at a time."""
    rep = rep or probe()
    rows = [
        f"{k:<12}: {rep.get(k, '')}" for k in
        ("time", "os", "python", "engine", "frozen", "pygame", "sdl_video",
         "moderngl", "gl_version", "gl_vendor", "gl_renderer", "glsl",
         "max_texture", "gl_error")
    ]
    warns = verdict(rep)
    rows.append("verdict     : " + (warns[0] if warns else "looks fine"))
    for extra in warns[1:]:
        rows.append("            : " + extra)
    return rows


def text(rep=None):
    return "\n".join(lines(rep))


def write(folder=None, rep=None):
    """Leave the report on disk; where it lands matters more than speed."""
    try:
        folder = Path(folder) if folder else paths.user_dir()
        folder.mkdir(parents=True, exist_ok=True)
        made = folder / REPORT_NAME
        made.write_text(text(rep or probe()) + "\n", encoding="utf-8")
        return made
    except OSError:
        return None
