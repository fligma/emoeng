"""Real window behaviour for the drawn XP frame.

The OS titlebar is removed (borderless) and the Luna caption the engine
paints *is* the titlebar: drag it to move the window, drag its edges to
resize, click min / max / close. Games and the editor share this, so every
window fligengine opens behaves like an XP program.

Everything goes through pygame._sdl2's Window wrapper plus a ctypes peek at
SDL's global mouse state: while a borderless window slides underneath the
cursor, the desktop-wide cursor position is the only stable drag reference.

Copied from the app's src/winchrome.py so fligengine stays self-contained.
"""

import ctypes
import sys
from pathlib import Path

import pygame

try:
    from pygame._sdl2 import video as _sdl2
except ImportError:
    _sdl2 = None

MARGIN = 6          # px near a borderless window edge that grabs a resize
BTN = 16            # caption button size, mirrors xp.titlebar
PAD = 3
MIN_W, MIN_H = 640, 420


def _load_sdl_dll():
    """The SDL2 library pygame links against, for SDL_GetGlobalMouseState."""
    if sys.platform == "win32":
        names = ["SDL2.dll"]
    elif sys.platform == "darwin":
        names = ["libSDL2.dylib", "libSDL2-2.0.0.dylib"]
    else:
        names = ["libSDL2-2.0.so.0", "libSDL2-2.0.so", "libSDL2.so"]
    pkg = Path(pygame.__file__).resolve().parent
    for name in names:
        path = pkg / name
        if path.exists():
            try:
                return ctypes.CDLL(str(path))
            except OSError:
                pass
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            pass
    return None


def caption_buttons(cap):
    """(minimize, maximize, close) rects mirroring xp.titlebar's geometry."""
    top = cap.y + (cap.height - BTN) // 2
    close = pygame.Rect(cap.right - BTN - 3, top, BTN, BTN)
    maximize = close.move(-(BTN + PAD), 0)
    minimize = close.move(-2 * (BTN + PAD), 0)
    return minimize, maximize, close


def work_area():
    """The primary monitor minus the taskbar, so maximize behaves."""
    if sys.platform == "win32":
        try:
            r = (ctypes.c_long * 4)()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, r, 0):
                return (r[0], r[1], r[2] - r[0], r[3] - r[1])
        except Exception:
            pass
    w, h = pygame.display.get_desktop_sizes()[0]
    return 0, 0, w, h


class WindowChrome:
    """Owns the borderless trick and the drag/resize state machine.
    Falls back to doing nothing (OS decorations stay) when SDL2 details
    are unavailable, so the app still runs."""

    def __init__(self):
        self.win = None
        if _sdl2 is not None:
            try:
                self.win = _sdl2.Window.from_display_module()
                self.win.borderless = True
            except Exception:
                self.win = None
        self.dll = _load_sdl_dll()
        self.drag = None              # ("move"|"resize", anchor, origin)
        self.maximized = False
        self.fullscreen = False
        self._restore_rect = None

    def supported(self):
        return self.win is not None

    # ------------------------------------------------------------- facts
    def global_mouse(self):
        if self.dll is None:
            return None
        try:
            fn = self.dll.SDL_GetGlobalMouseState
            fn.argtypes = [ctypes.POINTER(ctypes.c_int),
                           ctypes.POINTER(ctypes.c_int)]
            x, y = ctypes.c_int(), ctypes.c_int()
            if fn(ctypes.byref(x), ctypes.byref(y)) < 0:
                return None
            return (x.value, y.value)
        except Exception:
            return None

    def _rect(self):
        px, py = self.win.position
        w, h = self.win.size
        return pygame.Rect(px, py, w, h)

    def display_bounds(self):
        """Per-monitor (x, y, w, h) boxes from SDL; [] when unavailable.
        Coordinates are virtual-desktop, so secondary monitors appear
        with offsets (possibly negative)."""
        if self.dll is None:
            return []
        try:
            count = self.dll.SDL_GetNumVideoDisplays()
            fn = self.dll.SDL_GetDisplayBounds
            fn.argtypes = [ctypes.c_int, ctypes.c_void_p]
            rect = (ctypes.c_int * 4)()
            out = []
            for i in range(max(0, count)):
                if fn(i, ctypes.byref(rect)) == 0:
                    out.append(tuple(rect))
            return out
        except Exception:
            return []

    def _monitor_under_window(self):
        """Bounds of the monitor the window's centre currently sits on;
        this is what fullscreen should cover, not always the primary."""
        r = self._rect()
        for b in self.display_bounds():
            x, y, w, h = b
            if x <= r.centerx < x + w and y <= r.centery < y + h:
                return b
        b = self.display_bounds()
        if b:
            return b[0]
        w, h = pygame.display.get_desktop_sizes()[0]
        return (0, 0, w, h)

    # ------------------------------------------------------------ drag
    def begin_move(self, win_pos):
        """win_pos: cursor position inside the window on the caption.
        Grabbing the caption of a maximized window un-maximizes first,
        keeping the cursor at the same spot of the restored bar."""
        if self.win is None:
            return
        if self.maximized:
            self._unmaximize_at(win_pos)
        gm = self.global_mouse()
        if gm is None:
            gm = (self.win.position[0] + win_pos[0],
                  self.win.position[1] + win_pos[1])
        self.drag = ("move", gm, self.win.position)

    def _unmaximize_at(self, win_pos):
        gm = self.global_mouse()
        r = self._rect()
        x, y, w, h = self._restore_rect or (r.x, r.y, 1152, 700)
        if gm:
            ratio = win_pos[0] / max(1, r.w)
            px, py = gm[0] - ratio * w, gm[1] - win_pos[1]
        else:
            px, py = x, y
        self.win.size = (w, h)
        self.win.position = (int(px), int(py))
        self.maximized = False

    def resize_edges(self, pos, size):
        """Which border(s) a press at `pos` grabs, or None."""
        x, y = pos
        w, h = size
        s = ""
        if self.maximized or self.fullscreen:
            return None
        if x < MARGIN:
            s += "l"
        elif x >= w - MARGIN:
            s += "r"
        if y < MARGIN:
            s += "t"
        elif y >= h - MARGIN:
            s += "b"
        return s or None

    def begin_resize(self, edges, win_pos):
        if self.win is None:
            return
        gm = self.global_mouse()
        if gm is None:
            gm = (self.win.position[0] + win_pos[0],
                  self.win.position[1] + win_pos[1])
        self.drag = ("resize", edges, gm, self._rect())

    def update(self):
        """Call every frame while the left button is held."""
        if self.drag is None or self.win is None:
            return
        gm = self.global_mouse()
        if gm is None:
            return
        if self.drag[0] == "move":
            _, g0, p0 = self.drag
            pos = (p0[0] + gm[0] - g0[0], p0[1] + gm[1] - g0[1])
            if pos != self.win.position:
                self.win.position = pos
        else:
            _, edges, g0, r0 = self.drag
            dx, dy = gm[0] - g0[0], gm[1] - g0[1]
            l, t, r, b = r0.x, r0.y, r0.right, r0.bottom
            if "l" in edges:
                l = min(l + dx, r - MIN_W)
            if "r" in edges:
                r = max(r + dx, l + MIN_W)
            if "t" in edges:
                t = min(t + dy, b - MIN_H)
            if "b" in edges:
                b = max(b + dy, t + MIN_H)
            size, pos = (r - l, b - t), (l, t)
            if size != self.win.size:
                self.win.size = size
            if pos != self.win.position:
                self.win.position = pos

    # -------------------------------------------------------- caption ops
    def minimize(self):
        if self.win is not None:
            self.win.minimize()

    def _work_area(self, cx, cy):
        """Taskbar-free area of the monitor containing the point
        (cx, cy). Windows gives an exact answer via GetMonitorInfoW;
        elsewhere we fall back to the raw SDL monitor box."""
        if sys.platform == "win32":
            try:
                import ctypes.wintypes as wt

                class MI(ctypes.Structure):
                    _fields_ = [("cbSize", wt.DWORD),
                                ("rcMonitor", wt.RECT),
                                ("rcWork", wt.RECT),
                                ("dwFlags", wt.DWORD)]
                user32 = ctypes.windll.user32
                fn = user32.MonitorFromPoint
                fn.argtypes = [wt.POINT, wt.DWORD]
                fn.restype = wt.HANDLE
                gi = user32.GetMonitorInfoW
                gi.argtypes = [wt.HANDLE, ctypes.POINTER(MI)]
                gi.restype = wt.BOOL
                h = fn(wt.POINT(int(cx), int(cy)), 2)  # TONEAREST
                mi = MI()
                mi.cbSize = ctypes.sizeof(MI)
                if h and gi(h, ctypes.byref(mi)):
                    rc = mi.rcWork
                    return (rc.left, rc.top,
                            rc.right - rc.left, rc.bottom - rc.top)
            except Exception:
                pass
        for b in self.display_bounds():
            x, y, w, h = b
            if x <= cx < x + w and y <= cy < y + h:
                return b
        return work_area()

    def toggle_maximize(self):
        if self.win is None or self.fullscreen:
            return
        if self.maximized:
            x, y, w, h = self._restore_rect
            self.win.position = (x, y)
            self.win.size = (w, h)
            self.maximized = False
        else:
            r = self._rect()
            self._restore_rect = (r.x, r.y, r.w, r.h)
            ax, ay, aw, ah = self._work_area(r.centerx, r.centery)
            self.win.position = (ax, ay)
            self.win.size = (aw, ah)
            self.maximized = True

    def toggle_fullscreen(self, on=None):
        """Manual borderless fullscreen: the window is grown to exactly
        cover the monitor it currently sits on. SDL's own
        set_fullscreen is avoided because it snaps the window onto the
        primary display instead of following it to other monitors."""
        if self.win is None:
            return
        target = (not self.fullscreen) if on is None else on
        if target == self.fullscreen:
            return
        if target:
            r = self._rect()
            self._restore_rect = (r.x, r.y, r.w, r.h)
            x, y, w, h = self._monitor_under_window()
            self.win.position = (x, y)
            self.win.size = (w, h)
            self.fullscreen = True
            self.maximized = False
        else:
            self.fullscreen = False
            if self._restore_rect:
                x, y, w, h = self._restore_rect
                self.win.position = (x, y)
                self.win.size = (w, h)
        self.drag = None
