"""Headless frame-time harness: what a frame costs."""
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from pathlib import Path                                        # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pygame                                                   # noqa: E402

from emoeng.engine.loader import Project                        # noqa: E402
from emoeng.engine.game import Game                             # noqa: E402

DEMO = ROOT / "emoeng" / "projects" / "demo"


def _time(fn, frames):
    t0 = time.perf_counter()
    for _ in range(frames):
        fn()
    return (time.perf_counter() - t0) / frames


def bench(scene_name, frames=100, parts=False, save=None):
    """Run one scene and print what a frame costs."""
    project = Project(DEMO)
    if scene_name:
        project.start = scene_name
    game = Game(project)
    dt = 1.0 / 60.0
    for _ in range(3):                       # warm up, then time
        game.input.begin_frame()
        game.scene.update(dt)
        game.draw()

    def step():
        game.input.begin_frame()
        game.scene.update(dt)

    up = _time(step, frames)
    draw = _time(game.draw, frames)
    total = up + draw
    print(f"{scene_name or 'start':8s}  update {up * 1e3:6.2f} ms   "
          f"draw {draw * 1e3:6.2f} ms   frame {total * 1e3:6.2f} ms   "
          f"({1.0 / total:6.1f} fps)")
    if save:
        out = Path(save)
        out.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(game.screen, str(out))
        print(f"  saved {out}")
    if parts:
        _parts(game, scene_name)
    pygame.quit()


def _parts(game, scene_name):
    """Where the draw goes: renderer, shader chain, blit, HUD."""
    from emoeng.engine import shaders

    frames = 20
    reno = game.renderer
    scene = game.scene
    frame = scene.render(game.camera)
    names = tuple(getattr(scene, "post", ())) or tuple(game.project.post)
    passes = shaders.resolve(game.project, names)
    rect = game._view_rect()

    def make(chain):
        """A `scene.render` timed with this exact chain armed on it."""

        def run():
            # the chain runs inside render(), reading the target it drew
            reno.set_post(chain)
            scene.render(game.camera)

        return run

    def scale_only():
        pygame.transform.scale(frame, rect.size)

    def blit_only():
        game.screen.blit(frame, rect.topleft)

    def overlay():
        scene.overlay(game.screen)

    plain = _time(make(()), frames)
    rows = [("scene.render", plain),
            ("chain " + "+".join(p.name for p in passes),
             _time(make(passes), frames)),
            ("scale", _time(scale_only, frames)),
            ("blit", _time(blit_only, frames)),
            ("scene.overlay", _time(overlay, frames))]
    print("  --- parts (ms) ---")
    for label, got in rows:
        print(f"  {label:22s} {got * 1e3:6.2f}")
    for pas in passes:
        # what this pass adds over a bare frame
        got = _time(make((pas,)), frames) - plain
        print(f"  {'  .' + pas.name:22s} {max(got, 0.0) * 1e3:6.2f}")
    st = reno.stats()
    print(f"  batches {st['batches']}  draws {st['draw_calls']}  "
          f"tris {st['triangles']}  tex {st['textures']}")


def profile(scene_name, frames=40):
    """cProfile the same loop: where the frame time really goes."""
    import cProfile
    import pstats

    project = Project(DEMO)
    if scene_name:
        project.start = scene_name
    game = Game(project)
    dt = 1.0 / 60.0

    def step():
        game.input.begin_frame()
        game.scene.update(dt)
        game.draw()

    for _ in range(3):
        step()
    prof = cProfile.Profile()
    prof.enable()
    for _ in range(frames):
        step()
    prof.disable()
    print(f"{scene_name or 'start':8s}  --- profile, tottime ---")
    pstats.Stats(prof).sort_stats("tottime").print_stats(16)
    pygame.quit()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    frames = 100
    if "--frames" in sys.argv:
        frames = int(sys.argv[sys.argv.index("--frames") + 1])
        args = [a for a in args if a != str(frames)]
    for name in args or ["menu", "maze3d", "maze2d"]:
        if "--prof" in sys.argv:
            profile(name, min(frames, 40))
            continue
        save = f"emoeng/tools/_smoke/bench_{name or 'start'}.png" \
            if "--save" in sys.argv else None
        bench(name, frames, parts="--parts" in sys.argv, save=save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
