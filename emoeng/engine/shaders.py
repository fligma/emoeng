"""GPU shaders a project owns."""

import weakref

MODES = ("screen", "uv", "texture")

# which mode a scene's `post` chain may name
POST_MODE = "screen"


class ShaderError(Exception):
    """A shader that cannot become GLSL, with the reason."""


def report(text, kind="info"):
    """Send one line of shader news to whoever is listening."""
    hook = _HOOKS.get("log")
    if hook is not None:
        hook(str(text), kind)


_HOOKS = {}
_WARNED = set()           # lines already said, so a retry stays quiet


def warn_once(text):
    """Report a warning once, never again."""
    line = str(text)
    if line in _WARNED:
        return
    _WARNED.add(line)
    report(line, "warn")


def set_logger(fn):
    """Install the callback `report` writes through (None removes it)."""
    if fn is None:
        _HOOKS.pop("log", None)
    else:
        _HOOKS["log"] = fn
    _WARNED.clear()


def lit(value):
    """A Python number, colour or vector as GLSL text."""
    if isinstance(value, Expr):
        return value.text
    if isinstance(value, bool):
        return "1.0" if value else "0.0"
    if isinstance(value, (int, float)):
        text = f"{float(value):.6g}"
        return f"{text}.0" if "." not in text and "e" not in text else text
    if isinstance(value, (tuple, list)):
        parts = [lit(v) for v in value]
        if len(parts) == 2:
            return f"vec2({parts[0]}, {parts[1]})"
        if len(parts) == 3:
            return f"vec3({parts[0]}, {parts[1]}, {parts[2]})"
        if len(parts) == 4:
            return f"vec4({parts[0]}, {parts[1]}, {parts[2]}, {parts[3]})"
        raise ShaderError(f"no GLSL for a {len(parts)}-part value")
    if isinstance(value, str):
        return value           # already GLSL, written by hand
    raise ShaderError(f"no GLSL for {value!r}")


class Expr:
    """One GLSL expression, with roughly what it returns."""

    __slots__ = ("text", "kind")

    def __init__(self, text, kind="float"):
        self.text = str(text)
        self.kind = kind

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"<Expr {self.kind} {self.text}>"

    def cast(self, kind):
        """The same text read as another type."""
        return Expr(self.text, kind)

    # arithmetic: every form parenthesised, so precedence never lies
    def _both(self, other, flip=False):
        a, b = (lit(other), self.text) if flip else (self.text, lit(other))
        return a, b

    def __add__(self, other):
        a, b = self._both(other)
        return Expr(f"({a} + {b})", self.kind)

    def __radd__(self, other):
        a, b = self._both(other, True)
        return Expr(f"({a} + {b})", self.kind)

    def __sub__(self, other):
        a, b = self._both(other)
        return Expr(f"({a} - {b})", self.kind)

    def __rsub__(self, other):
        a, b = self._both(other, True)
        return Expr(f"({a} - {b})", self.kind)

    def __mul__(self, other):
        a, b = self._both(other)
        return Expr(f"({a} * {b})", self.kind)

    def __rmul__(self, other):
        a, b = self._both(other, True)
        return Expr(f"({a} * {b})", self.kind)

    def __truediv__(self, other):
        a, b = self._both(other)
        return Expr(f"({a} / {b})", self.kind)

    def __rtruediv__(self, other):
        a, b = self._both(other, True)
        return Expr(f"({a} / {b})", self.kind)

    def __pow__(self, other):
        a, b = self._both(other)
        return Expr(f"pow({a}, {b})", self.kind)

    def __neg__(self):
        return Expr(f"(-{self.text})", self.kind)


class Builder:
    """What `g` exposes to a fragment."""

    # the names every mode may read, as (GLSL text, type)
    SHARED = {
        "uv": ("v_uv", "vec2"),
        "pixel": ("gl_FragCoord.xy", "vec2"),
        "size": ("u_size", "vec2"),
        "time": ("u_time", "float"),
        "seed": ("u_seed", "float"),
        "color": ("src.rgb", "vec3"),
        "alpha": ("src.a", "float"),
        "source": ("src", "vec4"),
    }

    # what only a mesh pass has: a `uv` object shader
    MESH = {
        "world": ("v_world", "vec3"),
        "normal": ("v_nrm", "vec3"),
        "view": ("u_eye", "vec3"),
        "tint": ("v_col", "vec4"),
    }

    def __init__(self, mode="screen"):
        if mode not in MODES:
            raise ShaderError(f"no shader mode {mode!r}")
        self.mode = mode
        self.out = None
        self.raw = None
        self._names = dict(self.SHARED)
        if mode == "uv":
            self._names.update(self.MESH)

    # -- reads
    def __getattr__(self, name):
        # only reached when the instance lacks the name
        got = self.__dict__.get("_names", {})
        if name in got:
            text, kind = got[name]
            return Expr(text, kind)
        if name in self.MESH:
            raise ShaderError(
                f"{name} belongs to a uv shader, not a {self.mode} one")
        raise ShaderError(f"nothing in a shader is called {name!r}")

    def knob(self, name):
        """One named knob, as a uniform."""
        return Expr(f"k_{name}", "float")

    # every one of these is an expression, not a statement
    def tex(self, uv):
        """The sheet's colour at `uv`."""
        return Expr(f"texture(u_tex, {lit(uv)}).rgb", "vec3")

    def alpha_at(self, uv):
        """The sheet's coverage at `uv`."""
        return Expr(f"texture(u_tex, {lit(uv)}).a", "float")

    def noise(self, uv, scale=1.0):
        """One hash of `uv`: grain, speckle, a bad tape line."""
        return Expr(f"fract(sin(dot({lit(uv)} * {lit(scale)}, "
                    f"vec2(12.9898, 78.233))) * 43758.5453)", "float")

    def wmuv(self, uv, direction=(1.0, 0.0), speed=1.0):
        """`uv` slid at its own pace - a scrolling sheet."""
        return Expr(f"({lit(uv)} + {lit(direction)} * (u_time * "
                    f"{lit(speed)}))", "vec2")

    def sin(self, x):
        return Expr(f"sin({lit(x)})", "float")

    def cos(self, x):
        return Expr(f"cos({lit(x)})", "float")

    def fract(self, x):
        return Expr(f"fract({lit(x)})", "float")

    def floor(self, x):
        return Expr(f"floor({lit(x)})", "float")

    def ceil(self, x):
        return Expr(f"ceil({lit(x)})", "float")

    def abs(self, x):
        return Expr(f"abs({lit(x)})", self.kind_of(x))

    def sign(self, x):
        return Expr(f"sign({lit(x)})", self.kind_of(x))

    def clamp(self, x, lo=0.0, hi=1.0):
        return Expr(f"clamp({lit(x)}, {lit(lo)}, {lit(hi)})",
                    self.kind_of(x))

    def mix(self, a, b, t):
        return Expr(f"mix({lit(a)}, {lit(b)}, {lit(t)})", self.kind_of(a))

    def ramp(self, a, b, t):
        """`mix` with the words a Block row shows."""
        return self.mix(a, b, t)

    def pow(self, a, b):
        return Expr(f"pow({lit(a)}, {lit(b)})", self.kind_of(a))

    def max(self, a, b):
        return Expr(f"max({lit(a)}, {lit(b)})", self.kind_of(a))

    def min(self, a, b):
        return Expr(f"min({lit(a)}, {lit(b)})", self.kind_of(a))

    def length(self, v):
        return Expr(f"length({lit(v)})", "float")

    def normalize(self, v):
        return Expr(f"normalize({lit(v)})", self.kind_of(v))

    def dot(self, a, b):
        return Expr(f"dot({lit(a)}, {lit(b)})", "float")

    def step(self, edge, x):
        return Expr(f"step({lit(edge)}, {lit(x)})", "float")

    def smoothstep(self, a, b, x):
        return Expr(f"smoothstep({lit(a)}, {lit(b)}, {lit(x)})", "float")

    def hue(self, h):
        """A rainbow from one number, 0..1."""
        return Expr("clamp(abs(fract(vec3(h) + vec3(0.0, 0.6666667, "
                    "0.3333333)) * 6.0 - 3.0) - 1.0, 0.0, 1.0)"
                    .replace("vec3(h)", f"vec3({lit(h)})"), "vec3")

    def vec2(self, x=0.0, y=0.0):
        return Expr(f"vec2({lit(x)}, {lit(y)})", "vec2")

    def vec3(self, x=0.0, y=0.0, z=0.0):
        return Expr(f"vec3({lit(x)}, {lit(y)}, {lit(z)})", "vec3")

    def grey(self, c):
        return Expr(f"dot({lit(c)}, vec3(0.299, 0.587, 0.114))", "float")

    @staticmethod
    def kind_of(value):
        """Roughly what type an argument is, for the result's type."""
        return value.kind if isinstance(value, Expr) else "float"

    def emit(self):
        """The finished `main()` body: one assignment, however nested."""
        if isinstance(self.raw, str) and self.raw.strip():
            return self.raw.strip()
        out = self.out
        if out is None:
            return "frag = src;"
        if out.kind == "vec4":
            return f"frag = {out.text};"
        return f"frag = vec4({out.text}, {lit(self.alpha)});"


class Shader:
    """What a project's shader script defines."""

    name = "shader"
    mode = "screen"
    knobs = {}                   # name -> number, colour, or default
    doc = ""

    # a hand-written main() body; it wins over `frag`
    body = ""

    def frag(self, g):
        """Record the colour this shader paints."""
        return None

    def __getattr__(self, name):
        # a declared knob is a uniform; anything else is missing
        knobs = getattr(type(self), "knobs", {}) or {}
        if name in knobs:
            return Expr(f"k_{name}", knob_kind(knobs[name]))
        raise AttributeError(
            f"{type(self).__name__} has no knob {name!r}; its knobs are "
            f"{', '.join(sorted(knobs)) or 'none'}")


def knob_kind(default):
    """How a knob is declared in GLSL."""
    if isinstance(default, (tuple, list)) and len(default) == 4:
        return "vec4"
    if isinstance(default, (tuple, list)):
        return "vec3"
    return "float"


def knob_names(cls):
    return tuple((getattr(cls, "knobs", None) or {}).keys())


# knob uniforms must land above `u_*` built-ins
FS_BLIT_HEAD = """#version 330
in vec2 v_uv;
out vec4 frag;
uniform sampler2D u_tex;
uniform vec2 u_size;
uniform float u_time;
uniform float u_seed;
"""

FS_MESH_HEAD = """#version 330
in vec3 v_world;
in vec3 v_nrm;
in vec2 v_uv;
in vec4 v_col;
out vec4 frag;
uniform sampler2D u_tex;
uniform vec2 u_size;
uniform vec3 u_eye;
uniform float u_time;
uniform float u_seed;
"""

# what tops `main()` in each mode: the incoming colour
FS_BLIT_MAIN = """
void main() {
    vec4 src = texture(u_tex, v_uv);
"""

FS_MESH_MAIN = """
void main() {
    vec4 src = texture(u_tex, v_uv) * v_col;
"""

FOOTER = "}\n"


def label(cls):
    """The name a shader is called in a message."""
    got = getattr(cls, "name", None)
    if isinstance(got, str) and got:
        return got
    return str(getattr(cls, "__name__", None) or cls)


def compile_source(cls):
    """(fragment shader, knob types) for a shader class."""
    mode = str(getattr(cls, "mode", "screen") or "screen").lower()
    if mode not in MODES:
        raise ShaderError(f"{label(cls)}: no mode {mode!r} "
                          f"(use {', '.join(MODES)})")
    knobs = getattr(cls, "knobs", None) or {}
    types = {str(name): knob_kind(value) for name, value in knobs.items()}
    g = Builder(mode)
    body = str(getattr(cls, "body", "") or "").strip()
    if not body:
        holder = _KnobHolder(cls, g)
        try:
            got = cls.frag(holder, g)
        except ShaderError as exc:
            raise ShaderError(f"{label(cls)}: {exc}") from exc
        except AttributeError as exc:
            raise ShaderError(f"{label(cls)}: {exc}") from exc
        except TypeError as exc:
            raise ShaderError(f"{label(cls)}: frag() wants "
                              f"(self, g): {exc}") from exc
        if got is not None:
            g.out = got if isinstance(got, Expr) else Expr(lit(got), "vec3")
        body = g.emit()
    if not body:
        raise ShaderError(f"{label(cls)}: says nothing - give it a frag() "
                          f"or a body")
    # knob uniforms sit above `void main()`, with the built-ins
    decl = "".join(f"uniform {types[name]} k_{name};\n"
                   for name in sorted(types))
    if mode == "uv":
        text = FS_MESH_HEAD + decl + FS_MESH_MAIN
    else:
        text = FS_BLIT_HEAD + decl + FS_BLIT_MAIN
    lines = [f"    {line}" if line else "" for line in body.splitlines()]
    return text + "\n".join(lines) + "\n" + FOOTER, types


class _KnobHolder:
    """The `self` a `frag` reads for its knobs."""

    __slots__ = ("_cls", "_g")

    def __init__(self, cls, g):
        object.__setattr__(self, "_cls", cls)
        object.__setattr__(self, "_g", g)

    def __getattr__(self, name):
        cls = object.__getattribute__(self, "_cls")
        got = object.__getattribute__(self, "_g")
        if name == "knobs":
            return getattr(cls, "knobs", {}) or {}
        if name in ("mode", "name", "doc"):
            return getattr(cls, name, "")
        if name == "builder":
            return got
        knobs = getattr(cls, "knobs", {}) or {}
        if name in knobs:
            return Expr(f"k_{name}", knob_kind(knobs[name]))
        fn = getattr(cls, name, None)
        if callable(fn):
            return fn
        raise ShaderError(f"{label(cls)} has no knob {name!r}")


class ShaderPass:
    """One compiled shader, ready for a renderer to draw."""

    __slots__ = ("cls", "name", "mode", "source", "knob_types", "values",
                 "progs", "error")

    def __init__(self, cls, source=None, knob_types=None):
        self.cls = cls
        self.name = str(getattr(cls, "name", None) or cls.__name__)
        self.mode = str(getattr(cls, "mode", "screen") or "screen")
        self.source = source or ""
        self.knob_types = dict(knob_types or {})
        self.values = dict(getattr(cls, "knobs", None) or {})
        self.progs = weakref.WeakKeyDictionary()
        self.error = ""

    def set(self, name, value):
        """Retune one knob; unknown names are added."""
        self.values[str(name)] = value
        return self

    def get(self, name, default=None):
        return self.values.get(str(name), default)

    def program(self, renderer):
        """This renderer's program for the pass, built once and remembered."""
        if renderer in self.progs:
            return self.progs[renderer]
        prog = renderer.build_shader_program(self)
        self.progs[renderer] = prog
        return prog

    def __repr__(self):
        return f"<ShaderPass {self.name} {self.mode}>"


# one compiled pass per class, cached until a hot reload
_PASSES = weakref.WeakKeyDictionary()
_MISSING = object()              # "never asked", unlike "asked and failed"


def as_mode(cls, mode):
    """The same shader class read in another mode."""
    if str(getattr(cls, "mode", "screen") or "screen") == mode:
        return cls
    twins = cls.__dict__.get("_mode_twins") or {}
    twin = twins.get(mode)
    if twin is None:
        twin = type(cls.__name__, (cls,), {"mode": mode})
        cls._mode_twins = {**twins, mode: twin}
    return twin


def make_pass(cls):
    """Compile a shader class into a `ShaderPass`, or explain."""
    done = _PASSES.get(cls, _MISSING)
    if done is not _MISSING:
        return done
    try:
        source, types = compile_source(cls)
    except ShaderError as exc:
        report(str(exc), "error")
        _PASSES[cls] = None
        return None
    done = ShaderPass(cls, source, types)
    _PASSES[cls] = done
    return done


def resolve(project, names, want=POST_MODE):
    """Turn shader names into passes, skipping broken ones."""
    out = []
    for value in names or ():
        cls = None
        name = ""
        if isinstance(value, ShaderPass):
            cls, name = value.cls, value.name
        elif isinstance(value, type) and issubclass(value, Shader):
            cls = value
            name = str(getattr(value, "name", None) or value.__name__)
        elif project is not None:
            name = str(value)
            find = getattr(project, "shader_class", None)
            cls = find(name) if find is not None else None
        if cls is None:
            warn_once(f"no shader named {name!r} in this project")
            continue
        mode = str(getattr(cls, "mode", "screen") or "screen")
        if want and mode != want:
            warn_once(f"{name}: a {mode} shader cannot be a {want} pass")
            continue
        if isinstance(value, ShaderPass):
            out.append(value)
        else:
            made = make_pass(cls)
            if made is not None:
                out.append(made)
    return tuple(out)
