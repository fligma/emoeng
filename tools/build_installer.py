"""Freeze installer/installer.py into a stand-alone installer app.

    python tools/build_installer.py            # build only
    python tools/build_installer.py --run      # build, then launch it
    python tools/build_installer.py --console  # keep a console

The installer is its own PyInstaller target: pygame plus the standard
library and nothing else from the engine, so it stays small while the
engine app is a hundred MB. What it does need is the engine's chrome
by file path, exactly where a frozen installer.py looks for it:

    emoeng/engine/xp.py + winchrome.py   _MEIPASS/emoeng/engine/
    emoeng/const.py                      _MEIPASS/emoeng/
    emoeng/fonts                         _MEIPASS/emoeng/fonts/
    installer/assets                     _MEIPASS/assets/

The finished binaries are what the release carries beside the app, as
plain executables - no wrapping archive:

    MotionEngine-installer.exe   Windows
    MotionEngine-installer       Linux (chmod +x after download: GitHub
                                 strips the exec bit off bare uploads)

The word `installer` in every name is load-bearing: the installer
scores a release's asset list to pick this PC's engine archive, and
files carrying it can never be chosen - the installer must not
install itself.

Size is the point of this one: it ships the smallest PyInstaller can
make - optimised bytecode, `strip` on non-Windows, and UPX on the
bundled SDL/Python binaries where PyInstaller applies it (Windows
only: version 6 deliberately ignores UPX on *nix, so an installed
`upx` simply goes unused there and the build is never broken).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from emoeng import const                      # noqa: E402
from emoeng.engine import build               # noqa: E402
from emoeng.engine.build import BuildConfig   # noqa: E402

SRC = REPO / const.NAME
INSTALLER_DIR = REPO / "installer"
ENTRY = INSTALLER_DIR / "installer.py"

APP_NAME = f"{const.ENGINE_NAME}-installer"

BUILD = TOOLS / ".build" / "installer"
DIST = TOOLS / "dist"

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"
SEP = ";" if IS_WINDOWS else ":"


def log(msg, kind="info"):
    tag = {"info": "  ", "ok": " + ", "error": " ! "}.get(kind, "  ")
    print(f"{tag}{msg}", flush=True)


def exe_path():
    name = f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME
    return DIST / name


def make_config(console: bool) -> BuildConfig:
    """The smallest freeze this platform can produce."""
    cfg = BuildConfig(mode=None, trim=False)
    cfg.reset()
    cfg.set("name", APP_NAME)
    cfg.set("distpath", str(DIST))
    cfg.set("workpath", str(BUILD))
    cfg.set("specpath", str(BUILD))
    cfg.set("onefile", True)
    cfg.set("windowed", not console)
    cfg.set("clean", True)
    cfg.set("noconfirm", True)
    cfg.set("log_level", "INFO")
    # -OO bytecode: docstrings the installer never reads stay out
    cfg.set("optimize", 2)
    # UPX is most of the win: the bulk here is SDL and the Python
    # library, and those compress by roughly half
    cfg.set("noupx", shutil.which("upx") is None)
    cfg.set("strip", not IS_WINDOWS and shutil.which("strip") is not None)
    cfg.set("paths", [str(REPO), str(INSTALLER_DIR)])
    cfg.set("add_data", [
        f"{SRC / 'engine' / 'xp.py'}{SEP}emoeng/engine",
        f"{SRC / 'engine' / 'winchrome.py'}{SEP}emoeng/engine",
        f"{SRC / 'const.py'}{SEP}emoeng",
        f"{SRC / 'fonts'}{SEP}emoeng/fonts",
        f"{INSTALLER_DIR / 'assets'}{SEP}assets",
    ])
    return cfg


def run_build(cfg: BuildConfig) -> int:
    """Spawn PyInstaller on the installer and stream its output live."""
    if not cfg.available():
        log(build.missing_reason(), "error")
        return 2
    cmd = cfg.command(ENTRY)
    try:
        proc = subprocess.Popen(cmd, cwd=str(TOOLS),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
    except OSError as exc:
        log(f"cannot start PyInstaller: {exc}", "error")
        return 1
    log(f"> {cfg.text(ENTRY)}")
    for line in proc.stdout:
        log(line.rstrip())
    proc.stdout.close()
    code = proc.wait()
    if code != 0:
        log(f"PyInstaller exited {code}", "error")
    return code


def ensure_executable(exe: Path):
    """Keep the exec bit on POSIX so the shipped installer stays runnable."""
    if IS_WINDOWS:
        return
    try:
        exe.chmod(exe.stat().st_mode | 0o111)
    except OSError:
        pass


def launch(exe: Path) -> int:
    """Run the freshly built installer on this desktop."""
    ensure_executable(exe)
    log(f"launching: {exe}")
    try:
        return subprocess.Popen([str(exe)], cwd=str(exe.parent)).wait()
    except OSError as exc:
        log(f"could not start the installer: {exc}", "error")
        return 5


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    console = "--console" in args
    run = "--run" in args
    t0 = time.time()

    if not ENTRY.is_file():
        log(f"no installer to freeze: {ENTRY}", "error")
        return 2

    log(f"platform {'windows' if IS_WINDOWS else ('macos' if IS_MACOS else 'linux')}")
    log(f"source   {ENTRY}")
    log(f"output   {exe_path()}")
    log(f"mode     {'console' if console else 'windowed'}")

    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    cfg = make_config(console)
    code = run_build(cfg)
    if code != 0:
        return code

    exe = exe_path()
    if not exe.is_file():
        log(f"expected exe missing: {exe}", "error")
        return 3
    size_mb = exe.stat().st_size / (1024 * 1024)
    upx = "" if shutil.which("upx") is None else ", upx"
    log(f"built    {exe} ({size_mb:.1f} MB{upx}) in "
        f"{time.time() - t0:.1f}s", "ok")

    ensure_executable(exe)
    if run:
        return launch(exe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
