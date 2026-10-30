"""Build pruning: what one project needs before bundling."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

from . import paths
from .. import const

PKG = const.NAME
PROJECTS = const.PROJECTS_DIRNAME

# two build shapes: GAME bundles one project, APP the IDE
GAME = "game"
APP = "app"

# authoring code: IDE, planner, PyInstaller front end
TOOLING = (f"{PKG}.editor", f"{PKG}.engine.build", f"{PKG}.engine.prune",
           f"{PKG}.__main__")

# installed weight a game never imports; measured, with reasons
DEAD = (
    ("PIL.AvifImagePlugin", "AVIF codec - 7.5 MB of plugin, loader reads "
                            "png/jpg only"),
    ("PIL.MpegImagePlugin", "MPEG stills - never opened by the engine"),
    ("PIL.MicImagePlugin", "TIFF/EXIF thumbnails - unused"),
    ("PIL.FpxImagePlugin", "FileMaker snapshots - unused"),
    ("numpy.f2py", "Fortran-to-Python generator, and the only thing that "
                   "pulls charset_normalizer"),
    ("numpy.testing", "numpy's own test harness"),
    ("numpy.distutils", "build-time helpers"),
    ("pygame.tests", "pygame's test suite"),
    ("pygame.examples", "sample scripts"),
    ("OpenGL.GLU", "the old fixed-function utility library; moderngl "
                   "does not use it"),
    ("tkinter", "no dialog is drawn with it"),
    ("unittest", "test runner, only reached by the modules above"),
    ("pydoc_data", "the interpreter's help database"),
    ("setuptools", "packaging tooling"),
    ("pkg_resources", "legacy entry-point scanner"),
    ("ssl", "TLS sockets - the engine opens no URL; drops _ssl and "
            "libssl (libcrypto stays, hashlib links it)"),
)

# authoring junk: caches, dev saves, editor sources
SKIP_DIRS = frozenset({
    "__pycache__", "saves", ".git", ".idea", ".vscode",
    "dist", "build", ".raw_assets", ".import_cache", "backup", "_backup",
})
SKIP_SUFFIX = frozenset({".pyc", ".pyo", ".ase", ".psd", ".xcf", ".blend",
                         ".tmp", ".bak", ".orig", ".swp", ".log", ".drain",
                         ".thumb"})
SKIP_NAMES = frozenset({"Thumbs.db", "desktop.ini", ".DS_Store",
                        "ehthumbs.db"})

# project roots the loader resolves at runtime, not hidden imports
LOCAL = frozenset(const.PACKAGES)

# binaries PyInstaller writes twice; the top-level copies win
DUPLICATE_DIRS = ("pygame",)
DUPLICATE_SUFFIX = (".dll",)


def scan_source(text):
    """Every import name in one module, plus `emoeng.<module>` attribute use."""
    names, aliases = set(), {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                if alias.asname:
                    aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if not node.level and node.module:
                names.add(node.module)
                for alias in node.names:
                    names.add(f"{node.module}.{alias.name}")
                aliases.setdefault(node.module.split(".")[0], node.module)
    engine = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        if not isinstance(base, ast.Name):
            continue
        bound = aliases.get(base.id)
        if not bound:
            continue
        if bound == PKG:
            engine.add(f"{PKG}.engine.{node.attr}")
        elif bound.startswith(f"{PKG}.engine"):
            engine.add(f"{bound}.{node.attr}")
    return names, engine


def scan_folder(folder, pattern="**/*.py"):
    """Union of `scan_source` over a folder; junk files are skipped."""
    names, engine = set(), set()
    folder = Path(folder)
    if not folder.is_dir():
        return names, engine
    for path in sorted(folder.glob(pattern)):
        if skipped(path.relative_to(folder)):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        got, reached = scan_source(text)
        names |= got
        engine |= reached
    return names, engine


def scan_project(project):
    """(import names, engine names) for a project's own sources."""
    names, engine = set(), set()
    for kind in const.PACKAGES:
        got, reached = scan_folder(project.dir(kind))
        names |= got
        engine |= reached
    return names, engine


def engine_graph():
    """Dotted names the engine's runtime modules import statically."""
    root = paths.package_root() / "engine"
    names = set()
    for path in sorted(root.glob("*.py")):
        if path.name in ("build.py", "prune.py", "__main__.py"):
            continue                  # authoring tools, not runtime
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    # a relative engine import needs no name here
                    if node.module:
                        names.add(f"{PKG}.engine.{node.module}")
                    for alias in node.names:
                        names.add(f"{PKG}.engine.{alias.name}")
                elif node.module:
                    names.add(node.module)
                    for alias in node.names:
                        names.add(f"{node.module}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)
    return names


def external_roots(names, base):
    """Import targets outside `base` (the engine), ready for --hidden-import."""
    out = set()
    for dotted in names:
        head = dotted.split(".")[0]
        if head in LOCAL or head == base or head == "__future__":
            continue
        out.add(dotted.strip())
    return {n for n in out if "." in n
            or not any(m.startswith(f"{n}.") for m in out)}


def skipped(rel):
    """True for a project file that never ships."""
    parts = rel.parts if hasattr(rel, "parts") else Path(rel).parts
    for part in parts[:-1]:
        if part in SKIP_DIRS or part.startswith("."):
            return True
    name = parts[-1]
    return (name in SKIP_NAMES or Path(name).suffix.lower() in SKIP_SUFFIX
            or name.startswith("~$"))


def size_of(path):
    """Bytes under a folder (0 when it is missing)."""
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def count_of(path):
    """Files under a folder, for a size report."""
    path = Path(path)
    if not path.is_dir():
        return 0
    return sum(1 for p in path.rglob("*") if p.is_file())


def dedupe(folder):
    """Delete a binary the bundle already carries."""
    folder = Path(folder)
    if not folder.is_dir():
        return [], 0
    top = {p.name.lower(): p for p in folder.iterdir() if p.is_file()}
    gone, freed = [], 0
    for name in DUPLICATE_DIRS:
        sub = folder / name
        if not sub.is_dir():
            continue
        for path in sorted(sub.iterdir()):
            if not path.is_file() or path.suffix.lower() not in DUPLICATE_SUFFIX:
                continue
            other = top.get(path.name.lower())
            if other is None or other.stat().st_size != path.stat().st_size:
                continue
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:
                continue
            gone.append(path)
            freed += size
    return gone, freed


def human(num):
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} GB"


class TrimPlan:
    """What a build needs, and what to leave out."""

    def __init__(self, project=None, mode=GAME):
        self.project = project
        self.mode = mode
        self.name = project.path.name if project is not None else "game"
        self.imports = set()          # names the project's scripts import
        self.engine = set()
        self.base_engine = set()      # names the engine's runtime imports
        self.extra = set()
        self.uses = set()             # everything the bundle has to keep
        self.hidden = []
        self.excludes = []
        self.staged = None
        self.files_kept = 0
        self.files_skipped = 0
        self.bytes_kept = 0
        self.bytes_skipped = 0
        self.source_bytes = 0
        self._scan()

    def _scan(self):
        """Read the sources with `ast`, then derive hidden imports/excludes."""
        if self.project is not None:
            self.imports, self.engine = scan_project(self.project)
            self.source_bytes = size_of(self.project.path)
        self.base_engine = engine_graph()
        self.extra = {n for n in self.engine if n not in self.base_engine}
        self.uses = self.imports | self.base_engine | self.extra
        if self.mode == GAME:
            # project .py files ride as data, so name their imports
            seen = {n.split(".")[0]
                    for n in external_roots(self.base_engine, PKG)}
            self.hidden = sorted(
                n for n in external_roots(self.imports | self.engine, PKG)
                if n.split(".")[0] not in seen)
        self.excludes = [m for m, _why in DEAD if not self._asked(m)]
        if self.mode == GAME:
            self.excludes = list(TOOLING) + self.excludes
        if self.project is not None:
            self.stage(dry=True)
        return self

    def _asked(self, module):
        """True when a scan named `module` or a submodule."""
        prefix = f"{module}."
        return any(name == module or name.startswith(prefix)
                   for name in self.uses)

    def data_dest(self):
        """Where the data lands inside the bundle."""
        if self.mode == APP:
            return f"{PKG}/{PROJECTS}"
        return f"{PKG}/{PROJECTS}/{self.name}"

    def data_pair(self, sep=";"):
        """The --add-data value, from the staged mirror."""
        if self.mode == APP:
            source = paths.package_root() / PROJECTS
        elif self.staged is not None:
            source = self.staged
        elif self.project is not None:
            source = Path(self.project.path).resolve()
        else:
            source = None
        if source is None or not Path(source).is_dir():
            return ""
        return f"{source}{sep}{self.data_dest()}"

    def stage(self, workroot=None, dry=False):
        """Mirror the project into the work dir, minus junk."""
        if self.project is None or self.mode != GAME:
            return None
        src = Path(self.project.path)
        dst = None
        if not dry and workroot is not None:
            # absolute: PyInstaller resolves --add-data from its own cwd
            dst = (Path(workroot) / "bundle" / PROJECTS / self.name).resolve()
            dst.mkdir(parents=True, exist_ok=True)
        want = set()
        self.files_kept = self.files_skipped = 0
        self.bytes_kept = self.bytes_skipped = 0
        for path in sorted(src.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(src)
            if skipped(rel):
                self.files_skipped += 1
                self.bytes_skipped += path.stat().st_size
                continue
            self.files_kept += 1
            self.bytes_kept += path.stat().st_size
            if dst is None:
                continue
            target = dst / rel
            want.add(target)
            stat = path.stat()
            if target.exists():
                twin = target.stat()
                if twin.st_size == stat.st_size and twin.st_mtime >= stat.st_mtime:
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        if dst is None:
            return None
        for stale in [p for p in dst.rglob("*") if p.is_file() and p not in want]:
            stale.unlink()
        self.staged = dst
        return dst

    def lines(self):
        out = [f"mode       {self.mode}",
               f"project    {self.name}  {self.files_kept} files "
               f"{human(self.bytes_kept)}"
               + (f", skipped {self.files_skipped} "
                  f"({human(self.bytes_skipped)})"
                  if self.files_skipped else "")]
        out.append(f"engine     {len(self.base_engine)} modules reachable "
                   f"from the engine"
                   + (f", +{len(self.extra)} used by the project"
                      if self.extra else ""))
        if self.hidden:
            out.append(f"hidden     {', '.join(self.hidden)}")
        out.append(f"excluded   {len(self.excludes)} modules "
                   f"({', '.join(self.excludes[:5])}"
                   f"{' ...' if len(self.excludes) > 5 else ''})")
        return out

    def reason(self, module):
        for name, why in DEAD:
            if name == module:
                return why
        return "authoring tooling, not game code"

    def __repr__(self):
        return (f"<TrimPlan {self.name} hidden={len(self.hidden)} "
                f"excluded={len(self.excludes)}>")


def plan(project=None, mode=None):
    """The bundle plan for a project; APP when nothing trims."""
    if mode is None:
        mode = GAME if project is not None else APP
    return TrimPlan(project, mode)


def full_plan(project=None):
    """The plan for the app bundle, where the IDE ships."""
    return TrimPlan(project, APP)


def untrimmed(project=None, mode=None):
    """No pruning: the pre-trim layout, for debugging excludes."""
    p = TrimPlan(project, mode or (GAME if project is not None else APP))
    p.excludes = []
    p.hidden = []
    p.staged = None
    return p
