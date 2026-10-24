"""Emotion Engine (fligengine) command line entry points.

    python -m fligengine                   open the project manager
    python -m fligengine editor [path]     open the editor on a project
    python -m fligengine run [path]        play a project in its own window
    python -m fligengine build [path]      freeze a project with PyInstaller
    python -m fligengine new <path> [title]  scaffold a new project

`path` is a project folder (the one containing project.flig).
The file also runs directly: `python fligengine/__main__.py`.
"""

import sys
from pathlib import Path

# Running this file directly gives no package context; put the folder that
# contains `fligengine` on sys.path so the absolute imports below resolve.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        from fligengine.editor.app import main as editor_main
        editor_main(None)
        return 0
    cmd = args[0]
    if cmd == "run":
        from fligengine.engine.game import main as game_main
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
        from fligengine.editor.app import main as editor_main
        editor_main(args[1] if len(args) > 1 else None)
        return 0
    if cmd == "build":
        from fligengine.engine.build import main as build_main
        return build_main(args[1:])
    if cmd == "new":
        from fligengine.engine.loader import Project
        path = args[1] if len(args) > 1 else "fligengine/projects/new_game"
        title = args[2] if len(args) > 2 else None
        Project.create(path, title=title)
        print(f"created project: {path}")
        return 0
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    from fligengine.editor.app import main as editor_main
    editor_main(cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
