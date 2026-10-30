"""Motion Engine entry points."""

import os
import sys
from pathlib import Path

# contains `emoeng` on sys.path so the absolute imports below resolve.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAULT_LOG = "faults.log"


def _scratch_dir():
    """The per-user folder, found without importing the engine."""
    # the point of this is to work when the engine import is exactly the
    # thing that has gone wrong, so it cannot lean on engine.paths
    got = os.environ.get("EMOTION_ENGINE_HOME")
    if got:
        return Path(got).expanduser()
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "MotionEngine"
    return Path.home() / ".motionengine"


def arm_faults():
    """Make a crash or a hang leave a trace behind.

    A windowed build has no console, so a freeze is silent. The Python stack
    of every thread is written to a log instead: on a real crash, on SIGUSR1
    (`kill -USR1 <pid>`), and after EMOTION_ENGINE_WATCHDOG seconds of a
    hang, repeated while it stays hung.
    """
    try:
        import faulthandler
    except ImportError:
        return None
    sink = sys.stderr
    if sink is None:
        try:
            folder = _scratch_dir()
            folder.mkdir(parents=True, exist_ok=True)
            sink = open(folder / FAULT_LOG, "a", buffering=1)
        except OSError:
            sink = None
    for arm in (lambda: faulthandler.enable(file=sink, all_threads=True),
                lambda: faulthandler.enable(all_threads=True)):
        try:
            arm()
            break
        except (ValueError, OSError):
            continue
    try:
        import signal
        usr1 = getattr(signal, "SIGUSR1", None)
        if usr1 is not None and sink is not None:
            faulthandler.register(usr1, file=sink, all_threads=True)
    except (ValueError, OSError):
        pass
    try:
        secs = int(os.environ.get("EMOTION_ENGINE_WATCHDOG", "0"))
        if secs > 0 and sink is not None:
            faulthandler.dump_traceback_later(secs, repeat=True,
                                              file=sink, exit=False)
    except (ValueError, OSError):
        pass
    return sink


def main(argv=None):
    arm_faults()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--run":
        args = ["run"] + args[1:]
    if not args:
        from emoeng.editor.app import main as editor_main
        editor_main(None)
        return 0
    cmd = args[0]
    if cmd == "run":
        from emoeng.engine.game import main as game_main
        rest = args[1:]
        frames = None
        if "--frames" in rest:
            i = rest.index("--frames")
            try:
                frames = int(rest[i + 1])
            except (IndexError, ValueError):
                print("usage: --frames <count>")
                return 2
            rest = rest[:i] + rest[i + 2:]
        game_main(rest[0] if rest else None, frames=frames)
        return 0
    if cmd == "editor":
        rest = args[1:]
        frames = None
        if "--frames" in rest:
            i = rest.index("--frames")
            try:
                frames = int(rest[i + 1])
            except (IndexError, ValueError):
                print("usage: --frames <count>")
                return 2
            rest = rest[:i] + rest[i + 2:]
        from emoeng.editor.app import main as editor_main
        editor_main(rest[0] if rest else None, frames=frames)
        return 0
    if cmd == "build":
        from emoeng.engine.build import main as build_main
        return build_main(args[1:])
    if cmd == "new":
        from emoeng.engine.loader import Project
        path = args[1] if len(args) > 1 else "emoeng/projects/new_game"
        title = args[2] if len(args) > 2 else None
        Project.create(path, title=title)
        print(f"created project: {path}")
        return 0
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    from emoeng.editor.app import main as editor_main
    editor_main(cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
