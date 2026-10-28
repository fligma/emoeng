"""Headless harness: run a project's scenes for a few frames."""
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from emoeng.engine.loader import Project          # noqa: E402
from emoeng.engine.game import Game               # noqa: E402
from emoeng.editor import blocks                  # noqa: E402


def run_scene(project_path, scene, frames=6):
    project = Project(project_path)
    if scene:
        project.start = scene
    game = Game(project)
    game.run(limit=frames)
    return game


def _statement(block):
    """One palette block as a standalone statement."""
    text = block.sample()
    if block.kind in ("break", "continue"):
        text = f"for _x in ():\n    {text}"
    elif block.kind == "return":
        text = f"def _f():\n    {text}"
    return text


def check_blocks():
    """The whole palette: compiles, keeps its words, reads back."""
    wrote = {entry[0] for entry in blocks.CALLS.values()}
    ok = True
    for kind in blocks.SPEC:
        block = blocks.new_block(kind)
        text = _statement(block)
        try:
            compile(text, f"<{kind}>", "exec")
        except SyntaxError as exc:
            ok = False
            print(f"FAIL block {kind}: {exc.msg}")
            continue
        if kind not in wrote:
            continue
        back = blocks.parse(text)
        got = back.blocks[0].kind if back.blocks else None
        if got != kind or back.render() != text:
            ok = False
            print(f"FAIL block {kind}: reads back as {got}")
    print("blocks ok" if ok else "blocks FAILED")
    return ok


def main():
    project_path = ROOT / "emoeng" / "projects" / "demo"
    wanted = sys.argv[1:]
    want_blocks = "blocks" in wanted
    scenes = [name for name in wanted if name != "blocks"]
    ok = True
    if want_blocks:
        ok = check_blocks() and ok
    if not scenes and not want_blocks:
        scenes = [None]
    for scene in scenes:
        try:
            run_scene(project_path, scene)
            print(f"PASS {scene or 'start'}")
        except Exception as exc:
            ok = False
            print(f"FAIL {scene or 'start'}: {exc!r}")
            traceback.print_exc()
    print("smoke ok" if ok else "smoke FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
