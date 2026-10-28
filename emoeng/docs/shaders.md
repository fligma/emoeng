# Shaders

A *shader* is one look a project owns as a file. The engine used to ship
four hard-coded screen passes - dither, scanlines, vignette and grain -
painted by one composite nobody could change. That is gone. A look is now
a `shaders/<name>.shader` document plus the `scripts/shaders/<name>.py`
class beside it, and a game can add as many as it likes.

The maths is written as ordinary-looking Python against a recorder called
`g`. `frag()` runs **once, at compile time**, and only records text; no
Python runs per pixel. Knobs and the built-in clock become GPU uniforms,
so a look can be retuned every frame without recompiling. A shader that
will not compile is reported and skipped - an object draws with its plain
sheet, and a game never white-screens.

## The three modes

The mode is what decides *where* a shader runs, and it is set in the
document.

| Mode | Where it runs | How it is named | Reads |
| --- | --- | --- | --- |
| `screen` | One full-frame pass, after the scene drew | A scene's `post` chain / `set_post(...)` | The picture the scene just drew, as `g.color` |
| `uv` | Per fragment on one object's own mesh | `object.shader`, `scene.add(shader=...)` | The mesh's sheet, its normal, the camera |
| `texture` | The object's sheet rendered **once** into a new sheet | `object.shader`, `scene.place_model(shader=...)` | The sheet; the result becomes the sheet |

A `screen` shader is the only kind a scene's `post` chain may name; ask a
`post` for a `uv` one and it is reported and skipped. A `uv` shader keeps
its mesh on the live path (it is never welded into a static batch), so it
can move with time. A `texture` shader is baked once and costs nothing
afterwards, so its look is static. A `uv` shader asked of batched
geometry - or of a `place_model` - is compiled as a `texture` look
instead, and the caller is told.

## The `.shader` document

A `shaders/<name>.shader` file is JSON: the mode, the class that paints
it, and the knob values it is compiled with.

```json
{
 "format": 1,
 "_help": "a shader document: mode is screen, uv or texture, ...",
 "name": "uvscroll",
 "mode": "uv",
 "script": "scripts/shaders/uvscroll.py",
 "knobs": { "speed": 0.35, "tilt": 0.0 }
}
```

| Field | Meaning |
| --- | --- |
| `name` | The stem the project files it under; what code and `post` call it |
| `mode` | `screen`, `uv` or `texture` |
| `script` | The `scripts/shaders/<name>.py` file holding the class |
| `knobs` | Each knob's starting value - a number, an `(r, g, b)` colour, or a 4-part colour |

The document opens in the editor's Code tab as JSON to change the mode or
knobs; its paired `.py` opens in Code or Blocks like any other script.
`Project` reads them through `shader_names()`, `shader_doc(name)`,
`shader_class(name)` and `shader_script(name)`; the `shaders` folder is
watched, so edits hot-reload.

## The class

```python
"""slide a mesh's own sheet across it, forwards and sideways"""

import emoeng as fe


class UvScroll(fe.Shader):
    name = "uvscroll"
    mode = "uv"
    knobs = {"speed": 0.35, "tilt": 0.0}

    def frag(self, g):
        moved = g.wmuv(g.uv, g.vec2(self.speed, self.tilt), 1.0)
        g.out = g.tex(moved)
```

| Member | Meaning |
| --- | --- |
| `name` / `mode` | Match the document; `mode` is one of `MODES` |
| `knobs` | `name -> default`; each becomes a uniform read as `self.<name>` |
| `frag(self, g)` | Records the colour: set `g.out` (or return it) |
| `body` | Raw GLSL statements, for a look that needs a declaration; wins over `frag` when filled in |

A knob read as `self.amount` is that uniform, so the same script runs in
the editor and in a built game with no change. Reaching for a name the
builder does not know - or a mesh-only name in a `screen` shader - raises
`ShaderError` at compile, naming the shader, rather than failing later.

## What `g` gives you

`g` is the `Builder`. Reads are attributes; the finished colour is written
to `g.out`. Every read and call returns an expression, so one statement
per line is one line of GLSL and one Block row.

| Read | Type | Means | In modes |
| --- | --- | --- | --- |
| `g.uv` | vec2 | The fragment's 0..1 coordinate | all |
| `g.pixel` | vec2 | Its pixel position | all |
| `g.size` | vec2 | The frame or sheet size | all |
| `g.time` | float | The game clock | all |
| `g.seed` | float | The frame counter | all |
| `g.color` | vec3 | The incoming colour (the frame, for `screen`) | all |
| `g.alpha` | float | The incoming coverage | all |
| `g.source` | vec4 | The incoming colour and coverage together | all |
| `g.normal` | vec3 | The mesh surface normal | `uv` |
| `g.world` | vec3 | The fragment's world position | `uv` |
| `g.view` | vec3 | The camera (eye) position | `uv` |
| `g.tint` | vec4 | The mesh's per-vertex colour | `uv` |

| Call | Returns | Means |
| --- | --- | --- |
| `g.tex(uv)` | vec3 | The sheet's colour at `uv` |
| `g.alpha_at(uv)` | float | The sheet's coverage at `uv` |
| `g.noise(uv, scale=1)` | float | One hash of `uv`: grain, speckle |
| `g.wmuv(uv, direction, speed)` | vec2 | `uv` slid over time - a scroll |
| `g.mix(a, b, t)` / `g.ramp(a, b, t)` | like `a` | Blend `a` into `b` by `t` |
| `g.hue(h)` | vec3 | A rainbow from one number, `0..1` |
| `g.grey(c)` | float | Luminance of a colour |
| `g.clamp(x, lo=0, hi=1)` | like `x` | Hold `x` inside a range |
| `g.smoothstep(a, b, x)` | float | Soft `a..b` ramp |
| `g.step(edge, x)` | float | Hard `x >= edge` |
| `g.sin` / `g.cos` / `g.fract` | float | Waves and wraps |
| `g.floor` / `g.ceil` / `g.abs` / `g.sign` | like `x` | Level and sign maths |
| `g.pow` / `g.max` / `g.min` | like `a` | More arithmetic |
| `g.length` / `g.normalize` / `g.dot` | float / like `v` | Vector maths |
| `g.vec2(x, y)` / `g.vec3(x, y, z)` | vec2 / vec3 | Build a vector |

Plain `+ - * / **` and unary `-` work on any of these and stay
parenthesised, so precedence never lies.

## Naming one from code

A scene's frame runs a chain of `screen` shaders, in order:

```python
class Main(fe.Scene3D):
    post = ("scanlines",)         # or set it partway through

    def setup(self):
        self.set_post("grey", "vignette")

    def update(self, dt):
        self.set_shader_knob("vignette", "amount", 0.4 + 0.1 * dt)
```

An object - or a placed mesh - wears a `uv` or `texture` shader:

```python
self.scroll = self.add(fe.meshes.box(), shader="uvscroll")
self.plinth = self.place_model("orb", (0, 0, 1), shader="brushed")

self.player.set_shader("tintpulse")   # None clears it
```

| API | Notes |
| --- | --- |
| `scene.post` / `set_post(*names)` | Names of `screen` shaders the project owns |
| `scene.set_shader_knob(name, knob, value)` | Retune one uniform per frame |
| `scene.add/dynamic(..., shader=name)` | A `uv` shader forces the live path |
| `scene.place_model(..., shader=name)` | `texture` only; a `uv` name is baked |
| `object.set_shader(name_or_None)` | Resolves through `project.shaders`; a `screen` name for an object is refused with one log line |
| a `.scene` node's `shader` | A look field, so a placed node keeps its shader through a drag |

## Creating one in the editor

`New Shader` (from the `shaders` folder's `+`) offers a name and a
template chooser. Each choice writes the paired `.shader` document and
`scripts/shaders/<name>.py` in one step. The stock templates:

| Stem | Mode | Knobs | Look |
| --- | --- | --- | --- |
| `invert` | screen | `amount` | Push the frame towards its negative |
| `grey` | screen | - | Drop the colour, keep the light |
| `posterize` | screen | `steps`, `grain` | Few colour levels, dithered per pixel |
| `vignette` | screen | `amount`, `soft` | Wash to black at the edges |
| `scanlines` | screen | `amount`, `lines` | Darken every other row |
| `filmgrain` | screen | `amount`, `dots` | Speckle with moving noise |
| `ripple` | screen | `amount`, `speed`, `scale` | Bend rings out from the centre |
| `uvscroll` | uv | `speed`, `tilt` | Slide a mesh's own sheet |
| `tintpulse` | uv | `amount`, `speed` | Breathe a cycling hue over a mesh |
| `brushed` | texture | `amount`, `lines` | Stripe a sheet once, keep the result |

In the Blocks tab a shader script gets a `shader` drawer: rows for
`g.*` calls and the `g.time` / `g.uv` shortcuts, with the `frag` hook
(`self, g`) as its entry point. Assigning to `g.out` uses the ordinary
`set` block.

Related pages: [Camera and Rendering](camera-and-rendering.md),
[Objects](objects.md), [Scenes](scenes.md), [Blocks](blocks.md),
[Project Folder](project-folder.md).
