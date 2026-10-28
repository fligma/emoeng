# Camera and Rendering

Rendering is one moderngl pass into an offscreen target, read back as a pygame
`Surface` that the window blits and post-processes. Cameras are plain Python
objects, so a scene can own as many as it likes and cut between them.

## Camera

```python
Camera(eye=(0.0, 2.0, 8.0), yaw=0.0, pitch=0.0, fov=68.0, near=0.05,
       far=800.0, roll=0.0, viewport=None, name=None)
```

Yaw `0` looks down `+Z`, positive pitch looks up, positive roll tilts the
horizon. Right-handed, column-major matrices.

| Member | Signature | Notes |
| --- | --- | --- |
| `copy` | `copy(**overrides)` | A second camera with the same settings - a mirror view |
| `as_dict` | | Plain values, for save files and the debug overlay |
| `forward` / `side` / `up` | | Unit vectors from the current angles |
| `clamp_pitch` | `clamp_pitch(limit=1.5)` | Stop the gimbal flipping |
| `view_eye` / `view_yaw` / `view_pitch` / `view_roll` | | `eye` plus the live shake - what the frame actually renders with |
| `shake` | `shake(amount=1.0, duration=0.35, freq=None, scale=None, roll=None)` | Rattle the camera |
| `stop_shake` | | Cut it and put the eye back |
| `set_follow` | `set_follow(target=None, offset=None, damping=None)` | Follow something every frame |
| `follow` | `follow(target, dt=0.0, damping=None, offset=None, snap=False)` | One frame's easing toward target + offset |
| `aim` | `aim(yaw=None, pitch=None, dt=0.0, damping=None, limit=1.45, snap=False)` | Turn, easing through `damping` when set |
| `look_at_point` | `look_at_point(target, dt=0.0, damping=None, offset=None, limit=1.45)` | Point at a world position |
| `matrices` / `mvp` | `matrices(size, near=None, far=None)` | The projection and view pair |
| `project` | `project(point, size)` | World point to `(x, y, depth)` pixels, or `None` behind the camera |
| `ray` | `ray(size, pos)` | Screen pixel to `(origin, unit direction)` |
| `plane_hit` | `plane_hit(size, pos, point, normal)` | Where the mouse ray crosses a plane |
| `fly` | `fly(fwd=0.0, right=0.0, up=0.0, speed=10.0, dt=0.0)` | Move in camera space |
| `orbit` | `orbit(target, dist, yaw, pitch)` | Place the eye on a sphere and look at the centre |
| `update` | `update(dt)` | Advance shake and easing; every registered camera does this each frame |

Module helpers: `normalize(v)`, `wrap_angle(a)` (fold into `[-pi, pi)` so easing
never takes the long way), `ease(current, target, dt, damping=0.0)`,
`ease_angle(...)`, `wish(yaw, right, fwd)` (world `(x, z)` for WASD at a yaw),
`point_of(target)` (the `(x, y, z)` of a point or of anything with a `pos`).

## Camera2D

An orthographic rig for 2D and UI scenes: pixels, zoom, and the same shake API.

```python
Camera2D(size=(640, 360), zoom=1.0, center=None, viewport=None, name=None)
```

| Member | Notes |
| --- | --- |
| `projection` | `'ortho'` - how the renderer tells the two rigs apart |
| `resize(size)` | Adopt a new window size |
| `view_size()` | The world-pixel rectangle this frame shows at this zoom |
| `set_center(center=None, x=None, y=None)` | Where to look |
| `zoom_by(steps, lo=0.1, hi=16.0)` | Wheel steps, clamped |
| `anchor_center()` | The default centre when nothing set one - the middle of the world |
| `to_world(pixel)` | Screen pixel to world pixel, for picking |
| `ortho_box()` | `(left, right, bottom, top, near, far)` for the projection |
| `shake(...)` / `stop_shake()` / `update(dt)` | `roll` is accepted and ignored so one call site drives both rigs |

## CameraHost

The mixin that puts one `Camera` behind `eye`, `yaw` and `pitch`, so a `Game`
or a `Scene` can be steered without exposing the rig.

| Member | Notes |
| --- | --- |
| `init_camera(**kw)` | Build the backing camera |
| `eye` / `yaw` / `pitch` | Read-write properties onto the camera |
| `shake(amount=1.0, duration=0.35, ...)` | Safe to spam from an impact handler |
| `set_roll(roll)` | Tilt the horizon; scenes normally set `scene.roll` |
| `set_viewport(viewport)` | Limit the view to a rect, in pixels or 0..1 |
| `sync_camera(scene, dt)` | Copy the scene's knobs onto the camera, then tick it |

## OrbitCamera

The turntable used by the Model tab: `target`, `dist`, `yaw`, `pitch`, `fov`,
`near`, `far`, plus `camera()`, `orbit(dx, dy)`, `zoom(steps)`,
`pan(dx, dy, size)` and `frame(bounds, pad=1.9)`.

## Renderer

```python
r = fe.Renderer(width, height, render_scale=1.0)
```

| Member | Signature | Notes |
| --- | --- | --- |
| `texture` | `texture(key, arr=None, rgba=False, repeat=True, filter='linear', mipmaps=True, tile=0.0)` | Cache by name; pass a `uint8` `(H, W, 3/4)` array to upload. `rgba=True` switches to clamp and no mipmaps, which is what sprite sheets need. `tile` is the sheet's world size in metres - see [Textures as materials](#textures-as-materials) |
| `tile_for` | `tile_for(key, blend='opaque')` | Metres one repeat covers for this sheet, 0 when the layer does not want a material |
| `has_texture` | `has_texture(key)` | |
| `add` | `add(data, texture='white', blend='opaque', claim=None, opacity=1.0)` | Queue a `MeshData` for batching. `opacity` rides on the vertices, so a thinned piece also moves layer - see `blend_for` |
| `blend_for` | `blend_for(blend, opacity=1.0)` | The layer a thing of this opacity really draws in: solid `'opaque'` thinned becomes `'trans'`, a faded `'trans'` faded back up goes home |
| `build` | | Merge every queued piece into one VAO per (texture, blend) |
| `reset` | | Clear the batches - done before each new scene |
| `new_dynamic` | `new_dynamic(data, texture='white', blend='add', view_model=False, on_top=False, opacity=1.0)` | A `DynamicMesh` |
| `fade` | `fade(mesh, opacity)` | Re-composite a dynamic mesh at a new solidity - no new geometry, one buffer write |
| `dispose` | | Free the GL objects |
| `resize` | `resize(w, h)` | Window size changed |
| `set_render_scale` | `set_render_scale(scale)` | Clamped to `MIN_SCALE..MAX_SCALE` |
| `stats` | | Debug counters |
| `render` | `render(eye, yaw=None, pitch=None, scene=None, *, fov=None, near=None, far=None, roll=None, viewport=None)` | Draw `scene` from a camera or a raw transform, return a `Surface` |

### `stats()` keys

| Key | Meaning |
| --- | --- |
| `triangles`, `static_tris`, `dynamic_tris` | What the frame submitted |
| `batches` | VAOs drawn |
| `draw_calls` | Actual GL calls |
| `textures` | Uploaded textures |
| `viewport` | The rect rendered into |
| `target`, `render_scale` | Internal resolution and its ratio |

### Lighting the shader sees

3D lights go straight into the world program; 2D lights are drawn into a
separate mask and multiplied over the frame. See
[Lighting](lighting.md) for the light objects themselves.

| Quantity | Limit / source |
| --- | --- |
| 3D point / spot / sun / tube | `MAX_LIGHTS = 8` shader slots, taken from `scene.lights` ranked by `priority` then distance to the eye (`_pick_lights`); off or spent lights are skipped, and 2D-only shapes do not eat a slot |
| Spot cookie | One projected sheet per frame - the first cookie'd 3D spot in the list owns it (`_bind_cookie`, `u_cookie_slot`) |
| Ambient | `scene.ambient`, scaled by `scene.master` |
| Directional | `scene.sun_dir` and `scene.sun_col` |
| 2D light mask | An off-screen buffer cleared to `scene.ambient2d * master`; every `blend='light'` mesh is added with its energy on `u_boost`, and a negative light (`boost < 0`) is blended as a complement so dark pools actually eat light (`_lit_mask`) |
| 2D composite | The mask is multiplied over the just-drawn rect with `(DST_COLOR, ZERO)` - the frame shows only where the mask is bright (`_composite_mask`) |
| Unlit layers | `blend='alpha'` then `blend='hud'` are drawn after the multiply (`_flat`), so text and widgets stay readable in a dark room; `_flat` turns off the depth test *and* face culling and paints in the order the pieces were made, so a later mesh covers an earlier one and a quad wound twice is drawn twice |
| Translucent layer | `blend='trans'` is world geometry with something behind it - lit exactly like the opaque pass, then blended, so a ghost, a pane or a fading prop keeps its shading |
| Panel layer | `blend='panel'` is a shaped picture that is depth-tested but neither lit nor fogged. This is what a `Screen3D` wears: a monitor is bright where its picture is bright and black where it is black, and never a window onto the wall behind it |
| Additive layer | `blend='add'` is its own batch with culling off and depth on, which is what lets a flame's far side show through. A screen drawn this way instead of on `panel` adds its light to the wall, so its darks turn to glass - `glow=True` asks for exactly that |
| Vertex alpha | `in_col` is a `vec4`, and every layer above reads `texture alpha * vertex alpha` as one coverage. The texture's own alpha is a thing's *shape*; the vertex alpha is its *opacity*, and the two multiply rather than fight |
| Sheet alpha | A PNG's see-through pixels are recorded per key in `Renderer.holes` when the sheet is uploaded, and `layer_for()` then draws a batch wearing it on the blended `trans` layer even if it asked for `opaque` - the opaque batch is drawn with blending off, so its blank areas would paint out whatever stands behind. `relayer_sheets()` re-sorts the live meshes the moment a painted sheet gains or loses its holes |
| Fog | `scene.fog_color`, `fog_near`, `fog_far` |
| Clear colour | `scene.clear_color` |

Passing a `Camera` (or `Camera2D`) as `eye` is the usual call; `render()` then
reads `view_eye()`, `view_yaw()`, `view_pitch()`, `view_roll()` so shake and
damping are honoured automatically. `scene=None` renders only the static
batches, which is what the model and preview viewports do.

### View-model and on-top meshes

`new_dynamic(..., view_model=True, on_top=False)` marks a mesh as a first-person
weapon or hand - depth-tested against the world but drawn at the end.
`on_top=True` draws over everything, ignoring depth, for markers and reticles.

## Render scale and viewport

| Value | Effect |
| --- | --- |
| `render_scale = 1.0` | One internal pixel per window pixel |
| `render_scale = 0.5` | Half resolution, upscaled - chunky pixels, cheaper frames |
| `MIN_SCALE` / `MAX_SCALE` | `0.2` and `1.0`; `clamp_scale()` keeps requests inside |
| `scene.viewport = (x, y, w, h)` | Render a sub-rect, in pixels or in 0..1; split-screen at two cameras |

Order of resolution for the scale: `Game(render_scale=...)` -> config
`runtime.render_scale` (when non-zero) -> manifest `render.scale`.

## Post: shader passes on the frame

The engine ships no built-in screen look. A frame's mood is a chain of
`screen`-mode **shaders** the project owns as `shaders/<name>.shader`
files, painted in order after `Renderer.render()` has drawn the scene.
See [Shaders](shaders.md) for the mode, the `g` builder and the stock
looks.

```python
class Night(fe.Scene3D):
    post = ("grey", "vignette")        # names of screen shaders

    def setup(self):
        self.set_post("posterize", "filmgrain")

    def update(self, dt):
        # a knob is a uniform, so the look can be driven per frame
        self.set_shader_knob("vignette", "amount", 0.4 + 0.1 * dt)
```

| Fact | Detail |
| --- | --- |
| Resolution | `scene.post` names are resolved through `project.shaders` to `ShaderPass` objects |
| A bad name | Not a shader, or not `screen` mode: reported once and skipped, never a crash |
| Order | Chain runs in the order named; the last one's output is what shows |
| Chain storage | `Renderer.set_post(passes)` ping-pongs between two scratch targets |
| Retune | `set_shader_knob(name, knob, value)` writes that pass's uniform |
| Empty chain | The frame blits straight out, exactly as an unused rig would |

A scene's offscreen `Screen3D`/`Screen2D` rig resolves its own `post` the
same way, so a panel embedded in a scene can wear its own chain.

## Drawing geometry yourself

```python
from emoeng.engine import meshes

md = meshes.box(centre=(0, 0.75, -4), size=(3, 1.5, 1),
                col=(0.7, 0.6, 0.5))
scene.add(md, texture="stone")                 # static batch
scene.add(md, texture="glass", blend="trans", opacity=0.35)
flame = mote.dynamic(meshes.billboards(pos, 1.0, 1.4, count=3),
                     texture="flame", blend="add")
flame.update(new_mesh_each_frame)              # reshaped every frame
```

Every builder returns a `MeshData`. See
[Models and Meshes](models-and-meshes.md) for the full list.

`billboards(centre, w, h, count=3)` crosses `count` quads through one centre and
gives each its own back copy, so a flame reads as volume from any angle. That
mirrored copy is only ever right for something radially symmetric: on words it
reads as a doubling, and in an unlit layer - which neither depth-tests nor culls
- the back copy is painted over the front one rather than hidden behind it. Flat
signposting therefore builds one quad and turns it itself. `fe.Text3D` is that:
`billboard=True` aims the single quad back down the line of sight each time the
view changes, `billboard=False` keeps the node's own `yaw` and leaves it mounted
where it was placed, readable from the front and mirrored from behind the way
paint on glass is.

### Textures as materials

A `uv` count on a builder - `uv=(2, 2)`, `uv_scale=` - repeats a sheet by
*saying* how many times it should land. That works, and it is also how a
picture ends up stretched down the side of a model the moment the model is
longer than expected.

The other way is to say how big the *material* is and let the world do the
arithmetic. `assets.json` gives a sheet its metre size (`tile`), and the
renderer re-unwraps every face wearing it: geometry is projected from the two
axes lying across the face, pinned on a *pin* - the body's own place and turn -
so an 18 m wall of a 2 m stone draws nine repeats, a 0.5 m post draws a
quarter of one, and the bricks are the same size on both. A side that turns all
the way round is the one case a flat projection smears - there `u` is measured
along the arc it covers instead, so a post's sheet wraps once per
circumference and the bricks stay square round the back.
`meshes.tile_world(data, metres, anchor)` is that step on its own; it returns a
twin and leaves the mesh it was handed alone, because an owner keeps its soup
and files it again next frame.

The pin is what stops a picture swimming under a moving body. `frame_pin(pos,
yaw)` writes one and `slide_pin(pin, off)` carries it along; a live object hands
its mesh a `frame` callable that reports where it stands now, so each frame the
projection is measured in the body's own axes. Drag a crate in Edit, or fly one
past the camera in a game, and its sheet rides with it instead of sliding
across the surface. A mesh with no pin falls back on its own middle.

Two things keep this from disturbing anything already made:

* the default is `tile: 0.0`, so a sheet is a picture of one thing until a
  project names its metres; and
* only the two lit layers (`opaque`, `trans`) ask for a material. A sprite, a
  UI cut-out, a glow and a light cookie keep the 0..1 window they were drawn
  with, however their sheet is set up.

A sheet with a metre size outranks a model's own `uv` block - the block is
still read and written, but the world decides where the picture lands. The
Model tab's Settings shelf says so while such a sheet is picked.

## 2D and UI rendering

2D and UI scenes go through the same renderer, with `Camera2D` and the flat
builders (`meshes.quad2d`, `rect2d`, `billboards`). `quad2d` flips the V axis on
the way in, so image coordinates and `Object2D.uv` line up with the file as you
see it in an editor. Text is drawn by rendering a pygame surface to an RGBA
texture and welding a quad to the panel - see [UI and HUD](ui-and-hud.md).
