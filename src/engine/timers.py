"""Frame-driven timers for scenes: delayed calls and repeating ticks.

    self.after(2.0, self.open_gate)          # once, two seconds from now
    self.every(0.5, self.blink)              # forever, every half second
    handle = self.every(1.0, self.tick, 3)   # extra args are forwarded
    self.timers.cancel(handle)

Time only advances while the game is unpaused, and everything dies with
the scene, so a scene switch never leaves a stray callback behind.
"""


class Timer:
    """A single scheduled call. `left` counts down in seconds."""

    __slots__ = ("func", "delay", "left", "repeat", "args", "kwargs", "dead")

    def __init__(self, delay, func, repeat=False, args=(), kwargs=None):
        self.func = func
        self.delay = max(0.0, float(delay))
        self.left = self.delay
        self.repeat = bool(repeat)
        self.args = args
        self.kwargs = kwargs or {}
        self.dead = False

    def cancel(self):
        self.dead = True

    def reset(self, delay=None):
        self.left = self.delay if delay is None else max(0.0, float(delay))
        self.dead = False
        return self

    def __repr__(self):
        return (f"<Timer {getattr(self.func, '__name__', self.func)} "
                f"{self.left:.2f}/{self.delay:.2f}"
                f"{' repeat' if self.repeat else ''}>")


class Timers:
    """A tiny scheduler owned by every scene."""

    def __init__(self):
        self.items = []

    # -- scheduling
    def after(self, delay, func, *args, **kwargs):
        timer = Timer(delay, func, repeat=False, args=args, kwargs=kwargs)
        self.items.append(timer)
        return timer

    def every(self, delay, func, *args, **kwargs):
        timer = Timer(delay, func, repeat=True, args=args, kwargs=kwargs)
        self.items.append(timer)
        return timer

    def cancel(self, timer):
        if isinstance(timer, Timer):
            timer.dead = True
        return timer

    def clear(self):
        for timer in self.items:
            timer.dead = True
        self.items.clear()

    # -- frame
    def update(self, dt):
        """Advance every timer and fire the ones that came due."""
        if not self.items:
            return 0
        dt = max(0.0, float(dt))
        fired = []
        for timer in self.items:
            if timer.dead:
                continue
            timer.left -= dt
            if timer.left <= 0.0:
                fired.append(timer)
        count = 0
        for timer in fired:
            if timer.dead:
                continue
            if timer.repeat:
                timer.left += timer.delay or dt
            else:
                timer.dead = True
            try:
                timer.func(*timer.args, **timer.kwargs)
            except Exception as exc:            # a bad callback never
                print(f"timer {timer!r} failed: {exc!r}")   # kills the loop
            count += 1
        if any(t.dead for t in self.items):
            self.items = [t for t in self.items if not t.dead]
        return count

    def __len__(self):
        return len([t for t in self.items if not t.dead])

    def __bool__(self):
        return self.__len__() > 0
