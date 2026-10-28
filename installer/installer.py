"""Motion Engine installer.

A standalone app that searches GitHub for the newest `engineV<version>`
tag and installs the build made for this PC. It wears the engine's own
XP chrome: `xp.py` and `winchrome.py` are loaded straight from the
source tree beside this file - or, frozen, from the copy the build packs
under `_MEIPASS` - so the installer runs on pygame plus the standard
library alone. No engine dependencies: that is the point of a thing that
installs the engine.

    python installer/installer.py

The gear (top right) opens a settings dropdown with the repository,
the install folder and a Git token field. Anonymous GitHub search is
capped at 60 calls an hour per IP; the token is what keeps the search
working after that.

Nothing leaves the two folders it is told about: settings (token
included) live in `installer.json` beside this file, and every
downloaded and extracted file lands inside the install folder chosen
in the dropdown. No per-user app data, no hidden caches.
"""

import argparse
import ctypes
import importlib.util
import json
import os
import queue
import re
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pygame

# The engine's drawing primitives by file path: importing `emoeng.engine`
# would drag in the renderer and its third-party stack, which an
# installer must not need. xp.py and winchrome.py only ask for pygame
# and the standard library, so they load clean on their own.

HERE = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # a PyInstaller build unpacks its bundled data into a temporary
    # folder; `__file__` is no longer a usable home, so read the data
    # from `_MEIPASS`, where the CI build files it under the same
    # names the source tree uses. The app's own folder (settings,
    # default install destination) stays beside the real exe.
    APP_DIR = Path(sys.executable).resolve().parent
    HERE = Path(getattr(sys, "_MEIPASS", HERE))
    ENGINE_DIR = HERE / "emoeng" / "engine"
else:
    APP_DIR = HERE
    ENGINE_DIR = HERE.parent / "emoeng" / "engine"
ASSETS = HERE / "assets"


def _load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _engine_modules():
    """(xp, winchrome, const) from the source tree, or from the engine
    package when the installer has been shipped beside an installed
    engine. None when neither is there - the app says so and closes."""
    try:
        xp = _load_by_path("installer_xp", ENGINE_DIR / "xp.py")
        winchrome = _load_by_path("installer_winchrome",
                                  ENGINE_DIR / "winchrome.py")
    except Exception:                       # bare source tree may be absent
        try:
            from emoeng.engine import xp, winchrome    # installed engine
        except ImportError:
            return None, None, None
    try:
        const = _load_by_path("installer_const",
                              ENGINE_DIR.parent / "const.py")
    except Exception:
        const = None
    return xp, winchrome, const


xp, winchrome, const = _engine_modules()

CODENAME = getattr(const, "CODENAME", "Motion Engine")
VERSION = getattr(const, "VERSION", "0.0.0")
USER_DIR = getattr(const, "USER_DIR_NAME", "MotionEngine")
# the repository is the package name, not the engine exe name
DEFAULT_REPO = (f"{getattr(const, 'AUTHOR', 'fligma')}/"
                f"{getattr(const, 'NAME', 'emoeng')}")

CAP_H, TOOL_H, STATUS_H = 26, 36, 22
ROW_H = 20
TAG_PREFIX = "engineV"
API = "https://api.github.com"
UA = f"{USER_DIR}-installer/{VERSION}"

# Words a release asset name must carry to count as this PC's build,
# and the file endings that can actually be installed, best first.
OS_TOKENS = {
    "win32": ("win", "windows", "pc"),
    "darwin": ("mac", "osx", "darwin"),
}
OS_EXT = {
    "win32": (".exe", ".msi", ".zip"),
    "darwin": (".dmg", ".pkg", ".zip", ".tar.gz"),
    "linux": (".appimage", ".tar.gz", ".tgz", ".zip"),
}
OS_LABEL = {"win32": "Windows", "darwin": "macOS"}

TOKEN_TIP = (
    "GitHub counts anonymous searches per IP - 60 an hour.",
    "When they run out the search answers 'rate limited' and",
    "the blocked symbol shows until the hour resets. A",
    "personal access token sends calls authenticated against",
    "its own 5,000 an hour instead, and the search keeps",
    "working. A read-only token is enough; it is stored in",
    "installer.json beside this file.",
)

# ------------------------------------------------------------------ icons
_ICONS = {}


def icon(name, px=16):
    """The named PNG from installer/assets, nearest-scaled and cached.

    The symbols are 16x16 pixel art, so `transform.scale` (nearest) is
    right and smoothscale would only blur them.
    """
    if not name:
        return None
    key = (name, int(px))
    if key in _ICONS:
        return _ICONS[key]
    img = None
    try:
        raw = pygame.image.load(str(ASSETS / f"{name}.png"))
        try:
            raw = raw.convert_alpha()
        except pygame.error:
            pass
        size = (max(1, int(px)), max(1, int(px)))
        img = raw if raw.get_size() == size else pygame.transform.scale(
            raw, size)
    except (OSError, ValueError, pygame.error):
        img = None
    _ICONS[key] = img
    return img


_TEXTS = {}


def text(font, s, color):
    if not s:
        return None
    key = (id(font), s, color)
    img = _TEXTS.get(key)
    if img is None:
        if len(_TEXTS) > 6000:
            _TEXTS.clear()
        img = font.render(s, True, color)
        _TEXTS[key] = img
    return img


def elide(font, s, width):
    s = str(s)
    if font is None or width <= 0 or font.size(s)[0] <= width:
        return s
    room = width - font.size("...")[0]
    cut = s
    while cut and font.size(cut)[0] > room:
        cut = cut[:-1]
    return cut.rstrip() + "..."


# ------------------------------------------------------------- settings
# Everything the app itself remembers lives beside the executable:
# one small json next to this file. There is no per-user data folder -
# the app keeps its data only in the directory it is installed in.

SETTINGS_PATH = APP_DIR / "installer.json"
DEFAULT_DEST = str(APP_DIR)


def load_settings():
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {"repo": str(raw.get("repo") or DEFAULT_REPO),
                    "token": str(raw.get("token") or ""),
                    "dest": str(raw.get("dest") or DEFAULT_DEST)}
    except (OSError, ValueError):
        pass
    return {"repo": DEFAULT_REPO, "token": "", "dest": DEFAULT_DEST}


def save_settings(settings):
    try:
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2),
                                 encoding="utf-8")
        return True
    except OSError:
        return False


def _browse_windows():
    """The shell's Browse For Folder dialog; the typed path or None."""

    class BI(ctypes.Structure):
        _fields_ = [("hwndOwner", ctypes.c_void_p),
                    ("pidlRoot", ctypes.c_void_p),
                    ("pszDisplayName", ctypes.c_wchar_p),
                    ("lpszTitle", ctypes.c_wchar_p),
                    ("ulFlags", ctypes.c_uint),
                    ("lpfn", ctypes.c_void_p),
                    ("lParam", ctypes.c_long),
                    ("pidl", ctypes.c_void_p)]

    buf = ctypes.create_unicode_buffer(260)
    # BIF_NEWDIALOGSTYLE | BIF_EDITBOX | BIF_RETURNONLYFSDIRS: a resize
    # able tree with a type-in row, and shares rather than oddities
    bi = BI(None, None, None, "Choose the install folder",
            0x0040 | 0x0010 | 0x0001, None, 0, None)
    pidl = ctypes.windll.shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return None
    ok = ctypes.windll.shell32.SHGetPathFromIDListW(pidl, buf)
    try:
        ctypes.windll.ole32.CoTaskMemFree(pidl)
    except OSError:
        pass
    return buf.value if ok else None


def browse_folder():
    """The OS's own folder picker. None when the user cancelled or no
    picker exists - the field can always be typed into instead, so a
    headless or odd desktop never traps the flow."""
    try:
        if sys.platform == "win32":
            return _browse_windows()
        if sys.platform == "darwin":
            out = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose folder with prompt '
                 '"Install Motion Engine")'],
                capture_output=True, text=True)
            return out.stdout.strip().rstrip("/") or None
        out = subprocess.run(["zenity", "--file-selection", "--directory",
                              "--title=Install folder"],
                             capture_output=True, text=True)
        return out.stdout.strip() or None
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------ github api
class GitHubError(Exception):
    pass


class RateLimited(GitHubError):
    """The anonymous quota ran out; the token field is the answer."""


def api_json(path, token):
    """One GitHub REST call as parsed JSON, with the token header when
    there is one. Rate-limit replies become RateLimited so the UI can
    point at the settings dropdown instead of just failing."""
    headers = {"User-Agent": UA,
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as fh:
            return json.loads(fh.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        remaining = None
        if exc.headers is not None:
            raw = exc.headers.get("x-ratelimit-remaining")
            remaining = None if raw is None else raw.strip()
        if exc.code in (403, 429) and remaining == "0":
            raise RateLimited(
                "the anonymous GitHub API is exhausted (60 calls an "
                "hour per IP). Put a personal access token in the "
                "settings dropdown and try again.") from exc
        try:
            note = json.loads(exc.read().decode("utf-8")).get("message")
        except (ValueError, OSError):
            note = ""
        raise GitHubError(f"github said {exc.code}: {note or exc.reason}")
    except OSError as exc:
        raise GitHubError(f"cannot reach github: {exc}") from exc


def tag_version(name):
    name = str(name or "")
    if name.lower().startswith(TAG_PREFIX.lower()):
        return name[len(TAG_PREFIX):]
    return None


def version_key(text_):
    """Sorts version words the way numbers mean them: 1.10.0 above
    1.9.0, which string order gets backwards."""
    parts = []
    for chunk in re.split(r"[.\-+]", str(text_ or "")):
        m = re.match(r"(\d+)(.*)", chunk)
        parts.append((int(m.group(1)), m.group(2)) if m else (-1, chunk))
    return parts


def platform_key():
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def latest_engine(repo, token):
    """The newest `engineV*` on GitHub.

    Releases come first, because a release carries the built files per
    OS; a repository tagged but never released falls back to the tag's
    source archive, which installs the same folder of python anyway.
    """
    self = f"/repos/{repo}/releases?per_page=100"
    try:
        rows = api_json(self, token)
    except GitHubError:
        rows = []
    tagged = [r for r in rows if isinstance(r, dict)
              and tag_version(r.get("tag_name"))
              and not r.get("draft")]
    if tagged:
        best = max(tagged, key=lambda r: (
            version_key(tag_version(r.get("tag_name"))),
            str(r.get("published_at") or "")))
        return {
            "tag": str(best.get("tag_name")),
            "version": tag_version(best.get("tag_name")),
            "name": str(best.get("name") or best.get("tag_name")),
            "published": str(best.get("published_at") or "")[:10],
            "assets": [{"name": str(a.get("name")),
                        "url": str(a.get("browser_download_url")),
                        "size": int(a.get("size") or 0), "source": False}
                       for a in best.get("assets") or []],
        }
    rows = api_json(f"/repos/{repo}/tags?per_page=100", token)
    names = [str(t.get("name")) for t in rows if isinstance(t, dict)
             and tag_version(t.get("name"))]
    if not names:
        raise GitHubError(f"no {TAG_PREFIX}*-tagged build found in {repo}")
    tag = max(names, key=version_key)
    return {
        "tag": tag, "version": tag_version(tag), "name": tag,
        "published": "",
        "assets": [{"name": f"source ({tag})",
                    "url": f"{API}/repos/{repo}/zipball/refs/tags/{tag}",
                    "size": 0, "source": True}],
    }


def score_asset(asset, key):
    """How well an asset serves this PC: matching words in the name and
    an ending this OS can install. The best score is picked, and a
    tie goes to the earlier word - `windows` before `portable`.

    Installer programs published beside the release bundles are never
    a download candidate: this app IS the installer, and grabbing a
    copy of itself would loop, so any name carrying the word
    `installer` scores zero."""
    name = asset["name"].lower()
    if "installer" in name:
        return 0
    tokens = OS_TOKENS.get(key, ("linux", "ubuntu"))
    exts = OS_EXT.get(key, (".zip", ".tar.gz", ".tgz"))
    score = 0
    for i, word in enumerate(tokens):
        if word in name:
            score = max(score, 40 - i)
    for i, ext in enumerate(exts):
        if name.endswith(ext):
            score = max(score, 20 - i)
    if asset.get("source"):
        score = max(score, 5)
    return score


def pick_asset(assets):
    key = platform_key()
    best, top = None, 0
    for asset in assets:
        s = score_asset(asset, key)
        if s > top:
            best, top = asset, s
    return best if top >= 5 else None


def human(size):
    if size >= 1 << 20:
        return f"{size / (1 << 20):.1f} MB"
    if size >= 1 << 10:
        return f"{size / (1 << 10):.0f} KB"
    return f"{size} B" if size else "-"


def download(url, name, token, report, into):
    """Fetch one asset into the chosen install folder, feeding `report`
    the 0..1 fraction as chunks land; the bar reads that each frame.
    The part-file trick keeps a killed download from leaving a broken
    archive looking complete."""
    headers = {"User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    dest = Path(into)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / re.sub(r"[^\w.\-+]", "_", name)
    tmp = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    report(min(1.0, done / total))
    tmp.replace(path)
    report(1.0)
    return path


def unpack(path, into):
    """Put the downloaded file where it becomes usable: archives are
    opened into the chosen install folder, and a real installer program
    is launched - its own wizard knows best where the engine should
    go."""
    into.mkdir(parents=True, exist_ok=True)
    name = path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            zf.extractall(into)
        return f"extracted into {into}"
    if name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path) as tf:
            tf.extractall(into)
        return f"extracted into {into}"
    if name.endswith(".appimage"):
        path.chmod(path.stat().st_mode | 0o111)
        return f"made executable: {path}"
    if name.endswith((".exe", ".msi", ".dmg", ".pkg")):
        try:
            if sys.platform == "win32":
                os.startfile(str(path))          # noqa: windows-only
            else:
                subprocess.Popen(["open", str(path)])
            return f"launched the installer ({path.name})"
        except OSError as exc:
            return f"could not launch {path.name}: {exc}"
    return f"kept the file as {path}"


# ------------------------------------------------------------- text box
class TextBox:
    """One line of typed text: caret, typing, arrows, backspace. The
    value scrolls around the caret so a long token stays editable in a
    short field."""

    def __init__(self, value=""):
        self.text = str(value)
        self.caret = len(self.text)
        self.active = False

    def set(self, value):
        self.text = str(value)
        self.caret = len(self.text)

    def focus(self, on):
        self.active = bool(on)
        self.caret = len(self.text)

    def handle(self, e):
        if not self.active:
            return False
        if e.type == pygame.TEXTINPUT:
            ch = e.text.replace("\r", "").replace("\n", "").replace("\t", "")
            if ch:
                self.text = (self.text[:self.caret] + ch
                             + self.text[self.caret:])
                self.caret += len(ch)
            return True
        if e.type != pygame.KEYDOWN:
            return False
        if e.key == pygame.K_BACKSPACE:
            if self.caret:
                self.text = self.text[:self.caret - 1] + self.text[
                    self.caret:]
                self.caret -= 1
            return True
        if e.key == pygame.K_DELETE:
            self.text = self.text[:self.caret] + self.text[self.caret + 1:]
            return True
        if e.key == pygame.K_LEFT:
            self.caret = max(0, self.caret - 1)
            return True
        if e.key == pygame.K_RIGHT:
            self.caret = min(len(self.text), self.caret + 1)
            return True
        if e.key == pygame.K_HOME:
            self.caret = 0
            return True
        if e.key == pygame.K_END:
            self.caret = len(self.text)
            return True
        return False

    def draw(self, surf, rect, font, mask=False, color=None):
        shown = ("*" * len(self.text)) if mask else self.text
        xp.field(surf, rect)
        pad = 4
        avail = max(10, rect.width - 2 * pad - 2)
        before = font.size(shown[:self.caret])[0]
        scroll = 0
        if font.size(shown)[0] > avail:
            scroll = max(0, min(before - avail + 8,
                                font.size(shown)[0] - avail))
        old = surf.get_clip()
        surf.set_clip(rect.inflate(-2, -2))
        img = text(font, shown, xp.TEXT if color is None else color)
        if img is not None:
            surf.blit(img, (rect.x + pad - scroll,
                             rect.centery - img.get_height() // 2))
        if self.active:
            cx = rect.x + pad + before - scroll
            pygame.draw.line(surf, xp.CARET, (cx, rect.y + 3),
                             (cx, rect.bottom - 4), 1)
        surf.set_clip(old)


# ------------------------------------------------------------------ app
class Installer:
    """The window: toolbar, search result, asset pick, progress, log."""

    def __init__(self, repo=None, dest=None):
        if xp is None or winchrome is None:
            sys.exit("the installer needs emoeng/engine beside it "
                     "(xp.py, winchrome.py)")
        pygame.init()
        self.vsync = True
        self.screen = self._make_window(760, 560)
        pygame.display.set_caption(f"{CODENAME} installer")
        self.clock = pygame.time.Clock()
        self.fonts = {
            "small": pygame.font.SysFont("tahoma", 12),
            "normal": pygame.font.SysFont("tahoma", 14),
            "big": pygame.font.SysFont("tahoma", 17, bold=True),
        }
        self.chrome = winchrome.WindowChrome()
        self.settings = load_settings()
        if repo:
            self.settings["repo"] = repo
        if dest:
            self.settings["dest"] = str(dest)
        self.messages = queue.Queue()
        self.state = "idle"
        self.info = None               # the release found, or None
        self.asset = None              # the asset chosen for this PC
        self.match = None              # the best asset by OS score
        self.progress = 0.0
        self.log_rows = []
        self.asset_rows = []
        self.scroll = 0
        self.running = True
        # settings dropdown
        self.panel_open = False
        self.repo_box = TextBox(self.settings.get("repo", DEFAULT_REPO))
        self.dest_box = TextBox(self.settings.get("dest", DEFAULT_DEST))
        self.token_box = TextBox(self.settings.get("token", ""))
        self.token_shown = False
        self.hover_tip_at = None
        self.panel_rect = pygame.Rect(0, 0, 0, 0)
        self.rows = {}                 # rects recomputed by layout()
        self.log("installer ready - press Check for updates", "ok")

    # ------------------------------------------------------------- setup
    def _make_window(self, w, h):
        flags = pygame.RESIZABLE
        try:
            surf = pygame.display.set_mode((int(w), int(h)), flags,
                                           vsync=1 if self.vsync else 0)
        except pygame.error:
            surf = pygame.display.set_mode((int(w), int(h)), flags)
        art = icon("icon", 32)
        if art is not None:
            try:
                pygame.display.set_icon(art)
            except pygame.error:
                pass
        return surf

    def log(self, message, kind="info"):
        self.log_rows.append((str(message), kind))
        del self.log_rows[:-60]

    # ------------------------------------------------------------- work
    def _start(self, job, *args):
        """Run one network job off the UI thread; the worker only ever
        talks through the queue, so all state lands between frames."""
        if self.busy():
            self.log("still working - wait for the current job", "warn")
            return False
        threading.Thread(target=job, args=args, daemon=True).start()
        return True

    def busy(self):
        return self.state in ("searching", "downloading", "installing")

    def check(self):
        repo = self.settings.get("repo") or DEFAULT_REPO
        token = self.settings.get("token", "")
        self.state = "searching"
        self.progress = 0.0
        self._start(self._job_search, repo, token)

    def _job_search(self, repo, token):
        try:
            self.messages.put(("log", f"searching {repo} for "
                               f"{TAG_PREFIX}*", "muted"))
            info = latest_engine(repo, token)
            self.messages.put(("found", info))
        except RateLimited as exc:
            self.messages.put(("limited", str(exc)))
        except GitHubError as exc:
            self.messages.put(("error", str(exc)))
        except Exception as exc:                    # never kill a worker
            self.messages.put(("error", f"unexpected: {exc}"))

    def install(self):
        if self.asset is None:
            self.log("nothing chosen - search first", "warn")
            return
        token = self.settings.get("token", "")
        into = Path(self.settings.get("dest") or DEFAULT_DEST)
        self.state = "downloading"
        self.progress = 0.0
        self._start(self._job_install, self.asset, self.info, token, into)

    def _job_install(self, asset, info, token, into):
        try:
            self.messages.put(("log", f"downloading {asset['name']} "
                               f"into {into}", "muted"))
            path = download(asset["url"], asset["name"], token,
                            lambda frac: self.messages.put(
                                ("progress", frac)), into)
            self.state_put("installing")
            note = unpack(path, into)
            self.messages.put(("installed",
                               f"{CODENAME} {info['version']}: {note}"))
        except RateLimited as exc:
            self.messages.put(("limited", str(exc)))
        except (GitHubError, OSError, zipfile.BadZipFile,
                tarfile.TarError) as exc:
            self.messages.put(("error", str(exc)))
        except Exception as exc:
            self.messages.put(("error", f"unexpected: {exc}"))

    def state_put(self, state):
        self.messages.put(("state", state))

    def _poll(self):
        """Move everything the worker said into the app's own state."""
        try:
            while True:
                kind, *rest = self.messages.get_nowait()
                if kind == "log":
                    self.log(rest[0], rest[1] if len(rest) > 1 else "info")
                elif kind == "state":
                    self.state = rest[0]
                elif kind == "progress":
                    self.state = "downloading"
                    self.progress = rest[0]
                elif kind == "found":
                    self.info = rest[0]
                    self.match = pick_asset(self.info["assets"])
                    self.asset = self.match
                    self.progress = 0.0
                    self.scroll = 0
                    self.state = "found"
                    tag, ver = self.info["tag"], self.info["version"]
                    if ver == VERSION:
                        self.log(f"newest tag is {tag} - this source "
                                 "tree already matches", "ok")
                    else:
                        self.log(f"newest tag: {tag} "
                                 f"(this source: {VERSION})", "ok")
                    if self.match is None:
                        self.log(f"no build named for this PC among "
                                 f"{len(self.info['assets'])} asset(s) - "
                                 "pick one from the list", "warn")
                    else:
                        self.log(f"this PC will install: "
                                 f"{self.match['name']}", "ok")
                elif kind == "limited":
                    self.state = "limited"
                    self.progress = 0.0
                    self.log(rest[0], "blocked")
                    self.panel_open = True
                    self.token_box.focus(True)
                    self.repo_box.focus(False)
                elif kind == "error":
                    self.state = "error"
                    self.progress = 0.0
                    self.log(rest[0], "error")
                elif kind == "installed":
                    self.state = "done"
                    self.progress = 1.0
                    self.log(rest[0], "ok")
        except queue.Empty:
            pass

    # ------------------------------------------------------------ layout
    def layout(self):
        w, h = self.screen.get_size()
        cap = pygame.Rect(0, 0, w, CAP_H)
        bar = pygame.Rect(0, cap.bottom, w, TOOL_H)
        status = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
        controls = pygame.Rect(12, status.y - 34, w - 24, 30)
        rows = {
            "cap": cap, "bar": bar, "status": status, "controls": controls,
            "check": pygame.Rect(12, bar.y + 6, 168, bar.height - 12),
            "open": pygame.Rect(186, bar.y + 6, 96, bar.height - 12),
            "gear": pygame.Rect(bar.right - 40, bar.y + 6, 28,
                                bar.height - 12),
            "info": pygame.Rect(12, bar.bottom + 8, w - 24, 128),
            "assets": pygame.Rect(12, bar.bottom + 144, w - 24, 0),
            "log": pygame.Rect(12, 0, w - 24, 0),
            "progress": pygame.Rect(12, controls.y + 8,
                                    controls.width - 170, 16),
            "install": pygame.Rect(controls.right - 150, controls.y,
                                   150, 30),
        }
        rows["assets"].height = max(60, (h // 2) - rows["assets"].y)
        rows["log"].y = rows["assets"].bottom + 8
        rows["log"].height = max(40, controls.y - 10 - rows["log"].y)
        self.rows = rows
        return rows

    # ------------------------------------------------------------ events
    def _caption_press(self, pos):
        if not self.chrome.supported():
            return False
        cap = self.rows["cap"]
        b_min, b_max, b_close = winchrome.caption_buttons(cap)
        if b_close.collidepoint(pos):
            self.running = False
            return True
        if not cap.collidepoint(pos):
            return False
        if b_min.collidepoint(pos):
            self.chrome.minimize()
        elif b_max.collidepoint(pos):
            self.chrome.toggle_maximize()
        else:
            self.chrome.begin_move(pos)
        return True

    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        if self.panel_open:
            if self._panel_event(e):
                return
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.chrome.drag = None
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self._caption_press(e.pos):
                return
            edges = self.chrome.resize_edges(e.pos, self.screen.get_size())
            if edges:
                self.chrome.begin_resize(edges, e.pos)
                return
            if self.rows["check"].collidepoint(e.pos):
                self.check()
                return
            if self.rows["open"].collidepoint(e.pos):
                self._open_dest()
                return
            if self.rows["gear"].collidepoint(e.pos):
                self.panel_open = not self.panel_open
                self.repo_box.set(self.settings.get("repo", DEFAULT_REPO))
                self.dest_box.set(self.settings.get("dest", DEFAULT_DEST))
                self.token_box.set(self.settings.get("token", ""))
                return
            if self.rows["install"].collidepoint(e.pos):
                self.install()
                return
            for asset, rect in getattr(self, "asset_rows", ()):
                if rect.collidepoint(e.pos):
                    self.asset = asset
                    self.log(f"will install: {asset['name']}", "muted")
                    return
        if e.type == pygame.MOUSEWHEEL:
            if self.rows["assets"].collidepoint(e.pos):
                self.scroll = max(0, self.scroll - e.y)
                return
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE and self.panel_open:
                self._close_panel()
                return
            if e.key == pygame.K_RETURN and self.state not in (
                    "searching", "downloading", "installing"):
                self.check()
                return
        if e.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            # focus follows the click, so typing only lands when a field
            # was picked; the panel stays open either way
            box = (self.token_box if self.token_box.active else
                   self.repo_box if self.repo_box.active else None)
            if box is not None and box.handle(e):
                return

    def _panel_event(self, e):
        """Clicks and keys while the settings dropdown owns the window."""
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.panel_rect.collidepoint(e.pos):
                if self.rows.get("tip_eye",
                                 pygame.Rect(0, 0, 0, 0)).collidepoint(
                                        e.pos):
                    self.token_shown = not self.token_shown
                elif self.rows.get("tip_browse",
                                   pygame.Rect(0, 0, 0, 0)).collidepoint(
                                           e.pos):
                    picked = browse_folder()
                    if picked:
                        self.dest_box.set(picked)
                        self.dest_box.focus(True)
                elif self.rows.get("tip_ok",
                                   pygame.Rect(0, 0, 0, 0)).collidepoint(
                                           e.pos):
                    self._save_panel()
                elif self.rows.get("tip_repo",
                                   pygame.Rect(0, 0, 0, 0)).collidepoint(
                                           e.pos):
                    self.repo_box.focus(True)
                    self.token_box.focus(False)
                    self.dest_box.focus(False)
                elif self.rows.get("tip_dest",
                                   pygame.Rect(0, 0, 0, 0)).collidepoint(
                                            e.pos):
                    self.dest_box.focus(True)
                    self.token_box.focus(False)
                    self.repo_box.focus(False)
                elif self.rows.get("tip_token",
                                   pygame.Rect(0, 0, 0, 0)).collidepoint(
                                            e.pos):
                    self.token_box.focus(True)
                    self.repo_box.focus(False)
                    self.dest_box.focus(False)
                return True
            self._close_panel()
            return True
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._save_panel()
                return True
            if e.key == pygame.K_ESCAPE:
                self._close_panel()
                return True
        if e.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
            box = (self.token_box if self.token_box.active else
                   self.dest_box if self.dest_box.active else
                   self.repo_box if self.repo_box.active else None)
            if box is not None and box.handle(e):
                return True
        return False

    def _save_panel(self):
        self.settings["repo"] = self.repo_box.text.strip() or DEFAULT_REPO
        self.settings["token"] = self.token_box.text.strip()
        dest = self.dest_box.text.strip().strip('"') or DEFAULT_DEST
        try:
            Path(dest).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.log(f"cannot use {dest}: {exc}", "error")
            return
        self.settings["dest"] = dest
        if save_settings(self.settings):
            self.log(f"settings saved to {SETTINGS_PATH.name}", "ok")
        else:
            self.log("could not write the settings file", "error")
        self._close_panel()

    def _close_panel(self):
        self.panel_open = False
        self.repo_box.focus(False)
        self.dest_box.focus(False)
        self.token_box.focus(False)
        self.hover_tip_at = None

    def _open_dest(self):
        """Show the chosen install folder in the OS's own file window."""
        dest = Path(self.settings.get("dest") or DEFAULT_DEST)
        try:
            dest.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(dest))             # noqa: windows-only
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(dest)])
            else:
                subprocess.Popen(["xdg-open", str(dest)])
        except OSError as exc:
            self.log(f"cannot open {dest}: {exc}", "warn")

    # ------------------------------------------------------------ states
    LOGKINDS = {
        # colour + symbol per log kind; the kinds are the ones the
        # supplied symbols spell out (warning, error, fatal, blocked)
        "info": ("LOG_INFO", None),
        "ok": ("LOG_OK", None),
        "muted": ("LOG_MUTED", None),
        "warn": ("LOG_WARN", "warning-sym"),
        "error": ("LOG_ERROR", "error-sym"),
        "fatal": ("LOG_ERROR", "fatal-sym"),
        "blocked": ("LOG_WARN", "blocked-sym"),
    }

    def state_line(self):
        return {
            "idle": "idle - press Check for updates (or Enter)",
            "searching": "searching GitHub...",
            "found": "found a build - press Install",
            "limited": "rate limited - a token in Settings fixes this",
            "error": "the search failed - see the log",
            "downloading": "downloading...",
            "installing": "installing...",
            "done": "installed",
        }.get(self.state, self.state)

    # -------------------------------------------------------------- draw
    def draw(self):
        surface = self.screen
        rows = self.layout()
        surface.fill(xp.FACE)
        mouse = pygame.mouse.get_pos()

        xp.titlebar(surface, rows["cap"], f"{CODENAME} installer",
                    self.fonts["normal"], icon=icon("icon", 16),
                    controls=self.chrome.supported())

        bar = rows["bar"]
        surface.fill(xp.FACE, bar)
        pygame.draw.line(surface, xp.SHADOW, (bar.x, bar.bottom - 1),
                         (bar.right, bar.bottom - 1))
        searching = self.state == "searching"
        xp.button(surface, rows["check"],
                  "Searching..." if searching else "Check for updates",
                  self.fonts["small"], icon=icon("git-sym", 14),
                  pressed=searching,
                  hovered=rows["check"].collidepoint(mouse))
        xp.button(surface, rows["open"], "Open", self.fonts["small"],
                  hovered=rows["open"].collidepoint(mouse))
        if self.state == "limited":
            art = icon("blocked-sym", 16)
            if art is not None:
                surface.blit(art, (rows["open"].right + 8,
                                   bar.centery - 8))
        xp.button(surface, rows["gear"], "", self.fonts["small"],
                  icon=icon("settings-sym", 16), pressed=self.panel_open,
                  hovered=rows["gear"].collidepoint(mouse))

        self._draw_info(surface, rows["info"], mouse)
        self._draw_assets(surface, rows["assets"], mouse)
        self._draw_log(surface, rows["log"])

        ctl = rows["controls"]
        frac = self.progress if self.state in ("downloading",
                                               "installing", "done") else 0
        pygame.draw.rect(surface, xp.FIELD, rows["progress"])
        xp.sunken(surface, rows["progress"])
        fillw = int((rows["progress"].width - 2) * max(0.0, min(1.0, frac)))
        if fillw > 0:
            pygame.draw.rect(
                surface, (72, 158, 74),
                pygame.Rect(rows["progress"].x + 1, rows["progress"].y + 1,
                            fillw, rows["progress"].height - 2))
        img = text(self.fonts["small"], f"{int(frac * 100)}%",
                   xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (rows["progress"].right + 8,
                               ctl.centery - img.get_height() // 2))
        can = (self.asset is not None and not self.busy()
               and self.state != "installing")
        xp.button(surface, rows["install"],
                  "Installing..." if self.state == "installing"
                  else "Install", self.fonts["small"], default=can,
                  enabled=can,
                  hovered=rows["install"].collidepoint(mouse))

        xp.statusbar(surface, rows["status"],
                     [self.state_line(),
                      f"repo {self.settings.get('repo', DEFAULT_REPO)}",
                      f"installs to "
                      f"{self.settings.get('dest', DEFAULT_DEST)}",
                      f"this source {VERSION}"],
                     self.fonts["small"])

        if self.panel_open:
            self._draw_panel(surface, mouse)

    def _draw_info(self, surface, box, mouse):
        xp.field(surface, box)
        small, normal = self.fonts["small"], self.fonts["normal"]
        x, y = box.x + 12, box.y + 10
        lh = small.get_height() + 6
        found = self.info is not None
        art = icon("git-sym" if found else "no-git-sym", 32)
        if art is not None:
            surface.blit(art, (box.right - 44, box.y + 10))
        pairs = [
            ("This PC", OS_LABEL.get(platform_key(), platform_key())),
            ("This source", f"{CODENAME} {VERSION}"),
            ("Install folder",
             elide(normal, self.settings.get("dest", DEFAULT_DEST),
                   box.width - 220)),
        ]
        if self.state == "searching":
            pairs.append(("Newest tag", "searching..."))
        elif found:
            pairs.append(("Newest tag", f"{self.info['tag']}  "
                          f"(published {self.info['published'] or '-'})"))
            pairs.append(("Assets", f"{len(self.info['assets'])} file(s)"
                          " - click one to change the pick"))
        elif self.state == "limited":
            pairs.append(("Newest tag", "blocked: anonymous limit spent - "
                          "set a token (gear)"))
        else:
            pairs.append(("Newest tag",
                          "press Check for updates (Enter)"))
        for label, value in pairs:
            img = text(small, label, xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (x, y))
            img = text(normal, elide(normal, value,
                                     box.width - 220), xp.TEXT)
            if img is not None:
                surface.blit(img, (x + 96, y - 2))
            y += lh

    def _draw_assets(self, surface, box, mouse):
        xp.field(surface, box)
        small = self.fonts["small"]
        self.asset_rows = []
        assets = list(self.info["assets"]) if self.info else []
        top = box.y + 3 - self.scroll * ROW_H
        for asset in assets:
            row = pygame.Rect(box.x + 2, top + 2, box.width - 4, ROW_H)
            if row.bottom > box.y + 2 and row.y < box.bottom - 2:
                picked = asset is self.asset
                if picked:
                    surface.fill(xp.SELECTION, row)
                elif row.collidepoint(mouse):
                    surface.fill(xp.BTN_HOVER_BG, row)
                label = asset["name"]
                if self.match is not None and asset is self.match:
                    label += "   - for this PC"
                colour = xp.SELECT_TEXT if picked else xp.TEXT
                img = text(small, elide(small, label, box.width - 120),
                           colour)
                if img is not None:
                    surface.blit(img, (row.x + 8,
                                       row.centery - img.get_height() // 2))
                img = text(small, human(asset["size"]),
                           xp.SELECT_SUBTEXT if picked else xp.TEXT_MUTED)
                if img is not None:
                    surface.blit(img, (row.right - 12 - img.get_width(),
                                       row.centery - img.get_height() // 2))
            top += ROW_H
            self.asset_rows.append((asset, row))
        if not assets:
            img = text(small, "nothing found yet", xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (box.x + 8, box.y + 6))

    def _draw_log(self, surface, box):
        surface.fill(xp.LOG_BG, box)
        xp.sunken(surface, box)
        small = self.fonts["small"]
        old = surface.get_clip()
        surface.set_clip(box.inflate(-2, -2))
        y = box.bottom - 4
        for message, kind in reversed(self.log_rows[-64:]):
            colour_name, art = self.LOGKINDS.get(kind, ("LOG_INFO", None))
            row = pygame.Rect(box.x + 4, y - small.get_height() - 2,
                              box.width - 8, small.get_height() + 2)
            x = row.x + 2
            if art is not None:
                img = icon(art, 12)
                if img is not None:
                    surface.blit(img, (x, row.centery - 6))
                    x += 16
            img = text(small, elide(small, message, row.right - x),
                       getattr(xp, colour_name))
            if img is not None:
                surface.blit(img, (x, row.y))
            y = row.y - 1
            if y < box.y + 2:
                break
        surface.set_clip(old)

    def _draw_panel(self, surface, mouse):
        """The settings dropdown: repository, install folder (typed or
        picked with the native browse dialog), and the Git token -
        masked, with a reveal eye and a tooltip. OK stores all three.
        It hangs off the gear."""
        small, normal = self.fonts["small"], self.fonts["normal"]
        gear = self.rows["gear"]
        panel = pygame.Rect(0, 0, 330, 216)
        panel.topright = (min(surface.get_width(), gear.right + 6),
                          gear.bottom + 2)
        panel.x = max(4, panel.x)
        self.panel_rect = panel
        pygame.draw.rect(surface, xp.DK_SHADOW, panel.inflate(2, 2))
        surface.fill(xp.FACE, panel)
        xp.sunken(surface, panel)
        head = pygame.Rect(panel.x, panel.y, panel.width, 22)
        surface.fill(xp.FIELD_ALT, head)
        pygame.draw.line(surface, xp.SHADOW, (head.x, head.bottom - 1),
                         (head.right, head.bottom - 1))
        img = text(normal, "Settings", xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (head.x + 10,
                               head.centery - img.get_height() // 2))
        x = panel.x + 12
        width = panel.width - 24
        rows = self.rows
        y = head.bottom + 8

        def labelled(caption, box_field, y, extra=None):
            """One settings row: its name, a text field as wide as the
            panel (minus a button when `extra` gives one), returned y
            step for the next row."""
            img = text(small, caption, xp.TEXT_MUTED)
            if img is not None:
                surface.blit(img, (x, y))
            rect = pygame.Rect(x, y + 15, width - (extra or 0), 22)
            box_field.draw(surface, rect, small)
            return rect

        rows["tip_repo"] = labelled("GitHub repository", self.repo_box, y)
        y += 42
        rows["tip_dest"] = labelled("Install folder", self.dest_box, y,
                                    extra=28)
        browse = pygame.Rect(rows["tip_dest"].right + 6, y + 15, 22, 22)
        rows["tip_browse"] = browse
        xp.button(surface, browse, "…", small,
                  hovered=browse.collidepoint(mouse))
        y += 42
        img = text(small, "Git token", xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (x, y))
        eye = pygame.Rect(rows["tip_repo"].right - 22, y + 15, 20, 20)
        rows["tip_token"] = pygame.Rect(x, y + 15, width - 28, 22)
        self.token_box.draw(surface, rows["tip_token"], small,
                            mask=not self.token_shown)
        xp.button(surface, eye, "", small,
                  icon=icon("visable-sym" if self.token_shown
                            else "hidden-sym", 14),
                  hovered=eye.collidepoint(mouse))
        rows["tip_ok"] = pygame.Rect(panel.right - 84, panel.bottom - 32,
                                     72, 24)
        xp.button(surface, rows["tip_ok"], "OK", small, default=True,
                  hovered=rows["tip_ok"].collidepoint(mouse))
        note = text(small, "read-only token is enough", xp.TEXT_MUTED)
        if note is not None:
            surface.blit(note, (x, panel.bottom - 34))
        # the tooltip is why the field is not self-explanatory: hovering
        # the token field (or its name) says what the token is for
        hot = (rows["tip_token"].collidepoint(mouse)
               or pygame.Rect(x, y, 90, 14).collidepoint(mouse))
        if hot:
            if self.hover_tip_at is None:
                self.hover_tip_at = time.time()
            if time.time() - self.hover_tip_at > 0.4:
                xp.tooltip(surface, mouse, TOKEN_TIP, small)
        else:
            self.hover_tip_at = None

    # -------------------------------------------------------------- loop
    def _sync_surface(self):
        if not self.chrome.supported():
            return
        want = tuple(self.chrome.win.size)
        if not want or want == self.screen.get_size():
            return
        self.screen = self._make_window(want[0], want[1])

    def run(self):
        try:
            while self.running:
                self.clock.tick(60)
                for e in pygame.event.get():
                    self.handle_event(e)
                if self.chrome.drag and pygame.mouse.get_pressed()[0]:
                    self.chrome.update()
                self._poll()
                self._sync_surface()
                self.draw()
                pygame.display.flip()
        finally:
            pygame.quit()


def main():
    ap = argparse.ArgumentParser(description=f"{CODENAME} installer")
    ap.add_argument("--repo", default=None,
                    help="owner/name to search (default "
                         f"{DEFAULT_REPO})")
    ap.add_argument("--dest", default=None,
                    help="install folder (default the installer's own "
                         "folder); everything lands inside it")
    args = ap.parse_args()
    Installer(repo=args.repo, dest=args.dest).run()


if __name__ == "__main__":
    main()
