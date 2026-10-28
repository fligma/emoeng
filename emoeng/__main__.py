"""Motion Engine entry points."""

import sys
from pathlib import Path

# contains `emoeng` on sys.path so the absolute imports below resolve.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
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
        from emoeng.editor.app import main as editor_main
        editor_main(args[1] if len(args) > 1 else None)
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
