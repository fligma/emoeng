"""Window behaviour"""

import ctypes
import ctypes.util
import sys
from pathlib import Path

import pygame

IS_LINUX = sys.platform.startswith("linux")
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# SDL2 video module for custom window chrome (Windows/macOS)
if IS_LINUX:
    _sdl2 = None
else:
    try:
        from pygame._sdl2 import video as _sdl2
    except ImportError:
        _sdl2 = None

MARGIN = 6          # px near a borderless window edge that grabs a resize
BTN = 16            # caption button size, mirrors xp.titlebar
PAD = 3
MIN_W, MIN_H = 640, 420
RECONNECT_MS = 500      # how often a missing X11 window is probed again

PROP_REPLACE = 0
MWM_HINTS = 1 << 1          # the decorations field counts
MWM_DECOR_ALL = 1
MWM_DECOR_NONE = 0


# ------------------------------------------------------------------ X11 wire
# Linux has no SDL wrapper that can drop decorations, so the borderless
# trick goes straight to X11. Every call is typed on purpose: an untyped
# ctypes call hands back a 32-bit int, which truncates the display pointer
# and the 64-bit window id, and the next call then faults the process.
class XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int),
                ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int),
                ("visual", ctypes.c_void_p), ("root", ctypes.c_ulong),
                ("wclass", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int),
                ("backing_store", ctypes.c_int),
                ("backing_planes", ctypes.c_ulong),
                ("backing_pixel", ctypes.c_ulong),
                ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
                ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int),
                ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long),
                ("do_not_propagate_mask", ctypes.c_short)]


class XineramaScreenInfo(ctypes.Structure):
    _fields_ = [("screen_number", ctypes.c_int),
                ("x_origin", ctypes.c_short), ("y_origin", ctypes.c_short),
                ("width", ctypes.c_short), ("height", ctypes.c_short)]


class XrrScreenSize(ctypes.Structure):
    _fields_ = [("id", ctypes.c_ulong),
                ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("mwidth", ctypes.c_int), ("mheight", ctypes.c_int)]


class XrrScreenResources(ctypes.Structure):
    _fields_ = [("config_timestamp", ctypes.c_ulong),
                ("timestamp", ctypes.c_ulong),
                ("root", ctypes.c_ulong),
                ("ncrtc", ctypes.c_int),
                ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("noutput", ctypes.c_int),
                ("outputs", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int),
                ("modes", ctypes.POINTER(XrrScreenSize)),
                ("output_class_count", ctypes.c_int),
                ("output_class", ctypes.c_char_p)]


class XrrCrtcInfo(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("mode", ctypes.c_ulong), ("rotation", ctypes.c_int),
                ("noutput", ctypes.c_int),
                ("outputs", ctypes.POINTER(ctypes.c_ulong)),
                ("rotations", ctypes.c_ushort),
                ("possible_rotations", ctypes.c_uint)]


class XrrOutputInfo(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong),
                ("crtc", ctypes.c_ulong),
                ("name", ctypes.c_char_p), ("name_len", ctypes.c_ulong),
                ("connection", ctypes.c_ushort),
                ("subpixel_order", ctypes.c_ushort),
                ("ncrtc", ctypes.c_int),
                ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("nclone", ctypes.c_int),
                ("clones", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int),
                ("modes", ctypes.POINTER(ctypes.c_ulong))]


VOIDP = ctypes.c_void_p
ULONG = ctypes.c_ulong
UINT = ctypes.c_uint
INT = ctypes.c_int
CHARP = ctypes.c_char_p


def _sign(lib, names):
    """Pin down argument and return types, one call site at a time."""
    for name, restype, argtypes in names:
        try:
            fn = getattr(lib, name)
        except AttributeError:
            continue
        fn.restype = restype
        fn.argtypes = argtypes


def _load_x11_lib():
    """X11, typed and ready; None when there is no X server to talk to."""
    if not IS_LINUX:
        return None
    found = ctypes.util.find_library("X11")
    if not found:
        return None
    try:
        lib = ctypes.CDLL(found)
    except OSError:
        return None
    _sign(lib, [
        ("XOpenDisplay", VOIDP, [CHARP]),
        ("XCloseDisplay", INT, [VOIDP]),
        ("XDefaultScreen", INT, [VOIDP]),
        ("XDefaultRootWindow", ULONG, [VOIDP]),
        ("XSync", INT, [VOIDP, ctypes.c_int]),
        ("XFlush", INT, [VOIDP]),
        ("XGetWindowAttributes", INT,
         [VOIDP, ULONG, ctypes.POINTER(XWindowAttributes)]),
        ("XGetGeometry", INT,
         [VOIDP, ULONG, ctypes.POINTER(ULONG), ctypes.POINTER(INT),
          ctypes.POINTER(INT), ctypes.POINTER(UINT), ctypes.POINTER(UINT),
          ctypes.POINTER(UINT), ctypes.POINTER(UINT)]),
        ("XTranslateCoordinates", INT,
         [VOIDP, ULONG, ULONG, INT, INT, ctypes.POINTER(INT),
          ctypes.POINTER(INT), ctypes.POINTER(ULONG)]),
        ("XMoveResizeWindow", INT, [VOIDP, ULONG, INT, INT, UINT, UINT]),
        ("XResizeWindow", INT, [VOIDP, ULONG, UINT, UINT]),
        ("XMoveWindow", INT, [VOIDP, ULONG, INT, INT]),
        ("XIconifyWindow", INT, [VOIDP, ULONG, INT]),
        ("XInternAtom", ULONG, [VOIDP, CHARP, ctypes.c_int]),
        ("XChangeProperty", INT,
         [VOIDP, ULONG, ULONG, ULONG, INT, INT, VOIDP, INT]),
        ("XQueryPointer", INT,
         [VOIDP, ULONG, ctypes.POINTER(ULONG), ctypes.POINTER(ULONG),
          ctypes.POINTER(INT), ctypes.POINTER(INT), ctypes.POINTER(INT),
          ctypes.POINTER(INT), ctypes.POINTER(UINT)]),
    ])
    return lib


def _load_xrandr_lib():
    """Xrandr for monitor boxes; None when the extension is absent."""
    if not IS_LINUX:
        return None
    found = ctypes.util.find_library("Xrandr")
    if not found:
        return None
    try:
        lib = ctypes.CDLL(found)
    except OSError:
        return None
    res = ctypes.POINTER(XrrScreenResources)
    _sign(lib, [
        ("XRRGetScreenResourcesCurrent", res, [VOIDP, ULONG]),
        ("XRRFreeScreenResources", None, [res]),
        ("XRRGetOutputInfo", ctypes.POINTER(XrrOutputInfo),
         [VOIDP, res, ULONG]),
        ("XRRFreeOutputInfo", None, [ctypes.POINTER(XrrOutputInfo)]),
        ("XRRGetCrtcInfo", ctypes.POINTER(XrrCrtcInfo), [VOIDP, res, ULONG]),
        ("XRRFreeCrtcInfo", None, [ctypes.POINTER(XrrCrtcInfo)]),
    ])
    return lib


def _load_xext_lib():
    """Xext, for the Xinerama monitor boxes Xrandr did not answer with."""
    if not IS_LINUX:
        return None
    found = ctypes.util.find_library("Xext")
    if not found:
        return None
    try:
        lib = ctypes.CDLL(found)
    except OSError:
        return None
    _sign(lib, [
        ("XineramaQueryScreens",
         ctypes.POINTER(XineramaScreenInfo), [VOIDP, ctypes.POINTER(INT)]),
        ("XineramaIsActive", INT, [VOIDP]),
        ("XFree", None, [VOIDP]),
    ])
    return lib


_x11 = _load_x11_lib()
_xrandr = _load_xrandr_lib()
_xext = _load_xext_lib()


def _load_sdl_dll():
    """Load SDL2 for global pointer queries on custom-chrome platforms."""
    if IS_LINUX:
        return None
    if IS_WIN:
        names = ["SDL2.dll"]
    elif IS_MAC:
        names = ["libSDL2.dylib", "libSDL2-2.0.0.dylib"]
    else:
        return None
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
    if IS_WIN:
        try:
            r = (ctypes.c_long * 4)()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, r, 0):
                return (r[0], r[1], r[2] - r[0], r[3] - r[1])
        except Exception:
            pass
    try:
        w, h = pygame.display.get_desktop_sizes()[0]
    except (pygame.error, IndexError):
        return 0, 0, 1280, 720
    return 0, 0, w, h


class WindowChrome:
    """Owns the borderless trick and the drag/resize state machine."""

    def __init__(self):
        self.win = None
        self.display = None
        self.screen = 0
        self.root = 0
        self.window = 0
        self._parent_off = (0, 0)    # window origin's offset inside its parent
        self._ready = False
        self._retry_at = 0
        self.dll = _load_sdl_dll()
        self.drag = None              # ("move"|"resize", anchor, origin)
        self.maximized = False
        self.fullscreen = False
        self._restore_rect = None

    # ------------------------------------------------------------------ boot
    def _ensure(self):
        """Bind to the live window; the caller must have made one first."""
        if not IS_LINUX:
            if _sdl2 is not None and self.win is None:
                try:
                    self.win = _sdl2.Window.from_display_module()
                    self.win.borderless = True
                except Exception:
                    self.win = None
            return self.win is not None
        if _x11 is None:
            return False
        if self.display is None:
            return self._connect()
        if self._ready and self._alive():
            return True
        return self._rebind()

    def _live_window(self):
        """The X id SDL gave this window, or 0 while there is none."""
        try:
            if not pygame.display.get_init():
                return 0
            info = pygame.display.get_wm_info() or {}
        except Exception:
            return 0
        try:
            return int(info.get("window") or 0)
        except (TypeError, ValueError):
            return 0

    def _connect(self):
        """Open the server once; a miss is retried slowly, not per frame."""
        now = pygame.time.get_ticks()
        if now < self._retry_at:
            return False
        self._retry_at = now + RECONNECT_MS
        try:
            self.display = _x11.XOpenDisplay(None)
            if not self.display:
                return False
            self.screen = _x11.XDefaultScreen(self.display)
            self.root = _x11.XDefaultRootWindow(self.display)
            self.window = self._live_window()
            if not self.window or not self._alive():
                self.window = 0
                _x11.XCloseDisplay(self.display)
                self.display = None
                return False
            self._motif(MWM_DECOR_NONE)
            _x11.XSync(self.display, 0)
            self._ready = True
            return True
        except Exception:
            self._teardown()
            return False

    def _alive(self):
        """Is the cached window id still a window this server knows?"""
        if not (self.display and self.window):
            return False
        attrs = XWindowAttributes()
        try:
            return bool(_x11.XGetWindowAttributes(self.display, self.window,
                                                  ctypes.byref(attrs)))
        except Exception:
            return False

    def _rebind(self):
        """A rebuilt window has a new id; follow it rather than give up."""
        got = self._live_window()
        try:
            if got and got != self.window:
                self.window = got
                if self._alive():
                    self._motif(MWM_DECOR_NONE)
                    _x11.XSync(self.display, 0)
                    self._ready = True
                    return True
            elif not self.window:
                self._ready = False
                return False
        except Exception:
            pass
        self.window = got
        self._ready = False
        return False

    def _teardown(self):
        if self.display:
            try:
                _x11.XCloseDisplay(self.display)
            except Exception:
                pass
        self.display = None
        self.window = 0
        self.root = 0
        self._parent_off = (0, 0)
        self._ready = False

    def _to_parent(self, x, y):
        """Screen position -> position inside the reparenting window frame."""
        return x - self._parent_off[0], y - self._parent_off[1]

    def _motif(self, decorations):
        """Ask the window manager for no frame, or the frame back."""
        if not (self.display and self.window):
            return
        hints = (ctypes.c_ulong * 5)(MWM_HINTS, 0, decorations, 0, 0)
        atom = _x11.XInternAtom(self.display, b"_MOTIF_WM_HINTS", 0)
        _x11.XChangeProperty(self.display, self.window, atom, atom, 32,
                             PROP_REPLACE, ctypes.byref(hints), 5)

    def supported(self):
        return self._ensure()

    # -------------------------------------------------------------- geometry
    def global_mouse(self):
        if IS_LINUX:
            if not self._ensure():
                return None
            x = INT()
            y = INT()
            wx = INT()
            wy = INT()
            mask = UINT()
            child = ULONG()
            dummy = ULONG()
            try:
                ok = _x11.XQueryPointer(self.display, self.root,
                                        ctypes.byref(dummy),
                                        ctypes.byref(child),
                                        ctypes.byref(x), ctypes.byref(y),
                                        ctypes.byref(wx), ctypes.byref(wy),
                                        ctypes.byref(mask))
            except Exception:
                return None
            return (x.value, y.value) if ok else None
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
        """The window's box in screen coordinates, or None."""
        if IS_LINUX:
            if not self._ensure():
                return None
            try:
                drawable = ULONG()
                x = INT()
                y = INT()
                w = UINT()
                h = UINT()
                bw = UINT()
                depth = UINT()
                if not _x11.XGetGeometry(self.display, self.window,
                                         ctypes.byref(drawable),
                                         ctypes.byref(x), ctypes.byref(y),
                                         ctypes.byref(w), ctypes.byref(h),
                                         ctypes.byref(bw),
                                         ctypes.byref(depth)):
                    return None
                # geometry is parent-relative; a frame window may be offset
                rx = INT()
                ry = INT()
                child = ULONG()
                if not _x11.XTranslateCoordinates(self.display, self.window,
                                                  self.root, 0, 0,
                                                  ctypes.byref(rx),
                                                  ctypes.byref(ry),
                                                  ctypes.byref(child)):
                    return None
                # a window manager that reparented us keeps its own frame at
                # an offset; moves are given in the parent's space instead
                self._parent_off = (rx.value - x.value, ry.value - y.value)
                return pygame.Rect(rx.value, ry.value, w.value, h.value)
            except Exception:
                return None
        if self.win is None:
            return None
        px, py = self.win.position
        sw, sh = self.win.size
        return pygame.Rect(px, py, sw, sh)

    def frame_size(self):
        """The window's current size, whichever backend is driving it."""
        if IS_LINUX:
            r = self._rect()
            return (r.w, r.h) if r else None
        if self.win is None:
            return None
        return tuple(self.win.size)

    def _desktop_boxes(self):
        try:
            return [box for box in pygame.display.get_desktop_sizes()]
        except (pygame.error, IndexError):
            return []

    def display_bounds(self):
        """Per-monitor (x, y, w, h) boxes from X11/SDL, else []."""
        if IS_LINUX:
            if not self._ensure():
                return []
            boxes = self._xrandr_boxes()
            if not boxes:
                boxes = self._xinerama_boxes()
            if boxes:
                return boxes
            return [(0, 0, w, h) for w, h in self._desktop_boxes()] or \
                [work_area()]
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

    def _xrandr_boxes(self):
        if _xrandr is None:
            return []
        try:
            res = _xrandr.XRRGetScreenResourcesCurrent(self.display,
                                                       self.root)
            if not res:
                return []
            out = []
            rr = res.contents
            for i in range(max(0, rr.noutput)):
                output = rr.outputs[i]
                info = _xrandr.XRRGetOutputInfo(self.display, res, output)
                if not info:
                    continue
                crtc = info.contents.crtc
                if crtc:
                    ci = _xrandr.XRRGetCrtcInfo(self.display, res, crtc)
                    if ci:
                        c = ci.contents
                        if c.width and c.height:
                            out.append((c.x, c.y, c.width, c.height))
                        _xrandr.XRRFreeCrtcInfo(ci)
                _xrandr.XRRFreeOutputInfo(info)
            _xrandr.XRRFreeScreenResources(res)
            return out
        except Exception:
            return []

    def _xinerama_boxes(self):
        if _xext is None:
            return []
        count = INT()
        try:
            ptr = _xext.XineramaQueryScreens(self.display, ctypes.byref(count))
        except Exception:
            return []
        if not ptr:
            return []
        try:
            return [(ptr[i].x_origin, ptr[i].y_origin,
                     ptr[i].width, ptr[i].height)
                    for i in range(max(0, count.value))]
        except Exception:
            return []
        finally:
            try:
                _xext.XFree(ptr)
            except Exception:
                pass

    def _monitor_under_window(self):
        """Bounds of the monitor the window's centre currently sits on."""
        boxes = self.display_bounds()
        r = self._rect()
        if r is not None:
            for b in boxes:
                x, y, w, h = b
                if x <= r.centerx < x + w and y <= r.centery < y + h:
                    return b
        if boxes:
            return boxes[0]
        return work_area()

    # ---------------------------------------------------------------- motion
    def begin_move(self, win_pos):
        """win_pos: cursor position inside the window on the caption."""
        if IS_LINUX:
            if not self._ensure():
                return
            if self.maximized:
                self._unmaximize_at(win_pos)
            r = self._rect()
            if r is None:
                return
            gm = self.global_mouse() or (r.x + win_pos[0], r.y + win_pos[1])
            self.drag = ("move", gm, (r.x, r.y, r.w, r.h))
            return
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
        if IS_LINUX:
            r = self._rect()
            if r is None:
                return
            x, y, w, h = self._restore_rect or (r.x, r.y, 1152, 700)
            gm = self.global_mouse()
            if gm:
                ratio = win_pos[0] / max(1, r.w)
                px, py = gm[0] - ratio * w, gm[1] - win_pos[1]
            else:
                px, py = x, y
            self._move_resize(px, py, w, h)
            self.maximized = False
            return
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

    def _move_resize(self, x, y, w, h):
        """Drive the window through X11; a no-op anywhere else."""
        if not IS_LINUX:
            return
        if not self._ensure():
            return
        if self.window and not self._alive():
            if not self._rebind():
                return
        w = max(MIN_W, int(w))
        h = max(MIN_H, int(h))
        px, py = self._to_parent(int(x), int(y))
        try:
            _x11.XMoveResizeWindow(self.display, self.window, px, py, w, h)
            _x11.XFlush(self.display)
        except Exception:
            pass

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
        if IS_LINUX:
            if not self._ensure():
                return
            r = self._rect()
            if r is None:
                return
            gm = self.global_mouse() or (r.x + win_pos[0],
                                         r.y + win_pos[1])
            self.drag = ("resize", edges, gm, (r.x, r.y, r.w, r.h))
            return
        if self.win is None:
            return
        gm = self.global_mouse()
        if gm is None:
            gm = (self.win.position[0] + win_pos[0],
                  self.win.position[1] + win_pos[1])
        self.drag = ("resize", edges, gm, self._rect())

    def update(self):
        """Call every frame while the left button is held."""
        if self.drag is None:
            return
        gm = self.global_mouse()
        if gm is None:
            return
        if self.drag[0] == "move":
            _, g0, base = self.drag
            self._place(base[0] + gm[0] - g0[0],
                        base[1] + gm[1] - g0[1],
                        base[2] if len(base) > 2 else None,
                        base[3] if len(base) > 3 else None)
            return
        _, edges, g0, base = self.drag
        base = self._box(base)
        l, t, r, b = self._grow(base, edges, g0, gm)
        self._place(l, t, r - l, b - t)

    def _place(self, x, y, w, h):
        """Move, and resize too when a size came with the position."""
        if IS_LINUX:
            if w is None or h is None:
                if not self._ensure():
                    return
                px, py = self._to_parent(int(x), int(y))
                _x11.XMoveWindow(self.display, self.window, px, py)
                _x11.XFlush(self.display)
            else:
                self._move_resize(x, y, w, h)
            return
        if self.win is None:
            return
        if w is not None and h is not None and (w, h) != self.win.size:
            self.win.size = (w, h)
        if (x, y) != self.win.position:
            self.win.position = (int(x), int(y))

    @staticmethod
    def _box(base):
        """Either backend's resize anchor as one (left, top, right, bottom)."""
        if isinstance(base, pygame.Rect):
            return base.x, base.y, base.right, base.bottom
        return base[0], base[1], base[0] + base[2], base[1] + base[3]

    @staticmethod
    def _grow(base, edges, g0, gm):
        """The pressed box, dragged out by the pointer from its grab point."""
        l, t, r, b = base
        dx, dy = gm[0] - g0[0], gm[1] - g0[1]
        if "l" in edges:
            l = min(l + dx, r - MIN_W)
        if "r" in edges:
            r = max(r + dx, l + MIN_W)
        if "t" in edges:
            t = min(t + dy, b - MIN_H)
        if "b" in edges:
            b = max(b + dy, t + MIN_H)
        return l, t, r, b

    def minimize(self):
        if IS_LINUX:
            if not self._ensure():
                return
            try:
                _x11.XIconifyWindow(self.display, self.window, self.screen)
                _x11.XFlush(self.display)
            except Exception:
                pass
            return
        if self.win is not None:
            self.win.minimize()

    def _work_area(self, cx, cy):
        """Taskbar-free area of the monitor containing the point"""
        if IS_WIN:
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
        if IS_LINUX:
            if not self._ensure():
                return
            if self.maximized:
                if self._restore_rect:
                    x, y, w, h = self._restore_rect
                    self._move_resize(x, y, w, h)
                self.maximized = False
            else:
                r = self._rect()
                if r:
                    self._restore_rect = (r.x, r.y, r.w, r.h)
                    ax, ay, aw, ah = self._work_area(r.centerx, r.centery)
                    self._move_resize(ax, ay, aw, ah)
                    self.maximized = True
            return
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
        """Manual borderless fullscreen: the window is grown to exactly"""
        if IS_LINUX:
            if not self._ensure():
                return
            target = (not self.fullscreen) if on is None else on
            if target == self.fullscreen:
                return
            if target:
                r = self._rect()
                if r:
                    self._restore_rect = (r.x, r.y, r.w, r.h)
                    x, y, w, h = self._monitor_under_window()
                    self._move_resize(x, y, w, h)
                    self.fullscreen = True
                    self.maximized = False
            else:
                self.fullscreen = False
                if self._restore_rect:
                    x, y, w, h = self._restore_rect
                    self._move_resize(x, y, w, h)
            self.drag = None
            return
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
