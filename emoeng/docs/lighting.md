# Lighting

`fe.lights` is one system with two halves: `Light3D` in a metre world,
`Light2D` in a pixel world. Both come from `Light`, so the same words move,
colour, dim, animate and hand them about, and a scene made of either answers
the same questions.

```python
import emoeng as fe                       # fe.lights, fe.Light, fe.Light2D,
                                          # fe.Light3D are all re-exported

class Cellar(fe.Scene3D):
    def setup(self):
        self.set_ambient("night", 0.06)          # nearly pitch black
        self.torch = self.add_light(shape="spot", angle=48, inner=0.6,
                                    radius=26, color="torch", glow=0.6,
                                    flicker=0.18, follow=self.player,
                                    align=True, local=True, aim=(0, -14))
        self.door = self.add_preset("doorway", (320.0, 180.0), dim=2,
                                    color="fog")
```

## Getting a light into a scene

| Route | Call | Use it for |
| --- | --- | --- |
| Scene, from nothing | `scene.add_light(pos, color, shape=..., **kw)` | The usual case; hands the `Light` back |
| Scene, from a recipe | `scene.add_preset("campfire", pos, dim=None, tag=None, **kw)` | One of the 25 ready lights, overridable |
| Object, owned | `obj.light(pos=None, color=..., shape=None, follow=False, offset=None, **kw)` | A prop's own lamp, removed by `dispose()` |
| Hand-built | `fe.Light3D(scene, ...)` / `fe.Light2D(scene, ...)` then `.add_to(scene)` | A light you build before you know where it goes |
| Draft, unclaimed | `fe.Light3D(None, ...)`, stashed on an object | A spare you will `add_to()` later |
| Copy into a scene | `light.copy(scene, pos=..., tag=...)` | A second one like this one, registered |
| Adopt an existing one | `scene.add_light(other_scene.torch.beam)` | Moving a light between scenes |
| Rebuild from data | `scene.add_light(saved_dict)` | A level file, a save, a spawned prefab |
| Duplicate in place | `scene.copy_light(light, pos=..., tag=..., **kw)` | A mirror lamp beside the first |
| Module recipe | `fe.lights.preset("siren", scene, pos, dim=2, **kw)` | A light without putting it anywhere |

A light only shines once it is in `scene.lights`; `add_light`, `add_preset`,
`obj.light` and `copy()` all put it there, `add_to()` is the explicit version
and is safe to call twice. `scene.remove_light(light_or_tag)` takes it back
out, `scene.clear_lights()` drops them all for a level rebuild.

Where a light is, is usually `pos`. The other answer is a thing it rides:

```python
self.torch.at(self.player, offset=(0.2, -0.1, 0.0), align=True,
              local=True, aim=(0, -12))     # metres, in the player's frame
self.torch.detach()                          # stop following
self.torch.move_to(3.0, 2.0, -4.0)           # or just move it
```

| Knob | Meaning |
| --- | --- |
| `follow` / `at(obj)` | Ride that object's `pos` |
| `offset` | World units (pixels in 2D) off its centre |
| `local=True` | Read `offset` in the owner's own axes, so it stays "in front" as the owner turns |
| `align=True` | Turn with the owner: a 3D cone takes its `yaw`/`pitch`, a 2D cone its `rot` |
| `aim=(pan, tilt)` | Degrees held off the owner's line of sight - a headlamp that lands on the floor ahead instead of the horizon |

## What every light carries (`Light`)

| Name | Default | Meaning |
| --- | --- | --- |
| `pos` | origin | World position; `x` / `y` / `z` are live properties |
| `color` | `"torch"` | Any spelling `fe.colors` parses |
| `energy` | `1.0` | Brightness; what the animation verbs move |
| `radius` / `range` | 3D `18.0`, 2D `190.0` | Reach, in metres or pixels; 3D `0` keeps the old inverse-square curve |
| `alpha` | `1.0` | Multiplied into the light's own `level()` |
| `atten` | `"smooth"` | Falloff curve: `smooth`, `linear`, `power`, `inv`, `none` |
| `falloff` | `0.0` | Fraction of the reach that stays at full strength first |
| `exponent` | `2.0` | Shapes `power` and `inv` |
| `soft` | 2D `0.18` | The 2D alias of `falloff`, the flat middle of a pool |
| `flicker` | `0.0` | Jitter amount; `flicker_rate=9.0`, `flicker_style="candle"` |
| `pulse` | `0.0` | Sine the energy forever, at `pulse_rate=1.0` |
| `blink` | `None` | `(on, off)` or `(on, off, dim)` at construction |
| `layer` | `-1` (`all`) | Bit mask matched against an object's `light_layer` |
| `negative` | `False` | Subtract instead of add: a pool of darkness |
| `cookie` | `None` | Project a texture through a `spot` cone or a 2D shape |
| `outer` | `None` | Colour at the far end of the gradient |
| `priority` | `0.0` | A 3D light that must never lose a shader slot |
| `tag` | class name | What `remove_light("tag")` and `by_tag` know it by |
| `enabled` | `True` | `on()` / `off()` / `toggle()` / `enable(bool)` |
| `bake` | `False` | Freeze into a per-model lightmap; see Baked lights |
| `gate` | `None` | Only shine while `fn` says so |
| `seed` | `0` | So two candles in a room do not flicker in step |
| `follow` `offset` `align` `local` `aim` | see above | Placement that rides another object |

`light.set(...)` takes any subset and returns the light; unknown names are
ignored rather than raised, so a preset written for 3D can be handed to a 2D
light. Old code that treated a light as a dict still works:
`light["energy"] = 2.0`, `light.get("color")`, `light.keys()`.

`level()` is the number everything reads - `energy` shaped by every animation,
times `alpha`, times the master dimmer, negative for a dark pool. `tint()` is
`color x level()`.

## `Light3D` shapes

| `shape=` | Needs | Is |
| --- | --- | --- |
| `point` (also `area`, `omni`) | `radius` | Omni bulb |
| `spot` (also `cone`) | `dir` or `yaw`/`pitch`, `angle`, `inner`, `glow`, `cookie` | Cone torch, flashlight, window light, lighthouse |
| `sun` | `dir` | Directional; it lives on `scene.sun` and costs no slot |
| `tube` (also `line`, `strip`, `neon`) | `dir`, `length` | Distance measured to a segment: a neon sign, a lava crack, a tunnel |

| Name | Default | Meaning |
| --- | --- | --- |
| `dir` | `(0, -1, 0)` | The axis a `spot` or `tube` runs along; `yaw=` / `pitch=` (radians) are the friendlier way in |
| `angle` | `42.0` | Cone's full width, degrees; `180` is a hemisphere |
| `inner` | `0.6` | Fraction of that width at full strength - the rest is the soft rim |
| `glow` | `0.0` | A visible additive flame on the light itself, in metres (`True` = 1.0) |
| `length` | `0.0` | How far a `tube` runs from `pos` |

Aiming: `turn(yaw, pitch)` (radians), `look_at(target)`, `yaw()` and
`elevation()` read it back, `spin(secs)` turns it forever and
`sweep(a0, a1, secs)` rocks it between two yaws - `spin(None)` / `sweep(None)`
call either off. `set_time(hour)` drives a sun from the clock, taking
direction, colour and energy from `daylight()`.

3D light does not cast shadows in this renderer - it shines through geometry.
A maze keeps the beam narrow and close, and a 3D level that needs real
occlusion is usually better told in 2D.

## `Light2D` shapes

| `shape=` | Needs | Is |
| --- | --- | --- |
| `radial` (also `point`, `glow`, `circle`) | `radius` | A circle of light |
| `cone` (also `torch`, `fov`, `spot`) | `dir`, `angle`, `inner` | A field of view, a torch beam |
| `rect` (also `box`, `door`) | `size` or `length`/`width`, `dir` | A doorway, a lit counter, a window |
| `strip` (also `line`, `bar`, `slit`) | `length`, `width` | A laser, a slash, a neon tube |
| `ring` (also `halo`, `ping`, `shock`) | `radius`, `hole` | A band with the middle cut out: sonar, a magic circle |
| `poly` | `points` | An outline you supply |
| `world` (also `screen`, `frame`, `wash`, `flash`) | nothing | Whatever the frame shows: an alarm tint, a whole level going amber |

| Name | Default | Meaning |
| --- | --- | --- |
| `dir` | `0.0` | Heading in degrees: `0` is `+x`, `90` is down the screen |
| `angle` | `360.0` | Spread, degrees - a `radial` narrowed to 90 is a quarter pool |
| `inner` | `0.0` | The part of a cone's spread at full strength, so the sides are soft |
| `soft` | `0.18` | Flat middle before the falloff starts |
| `cast` | `True` | Occluded by `blockers`: what shows is what the light reaches |
| `blockers` | `None` | This light's own walls, else `scene.blockers` |
| `samples` | `48` | Rays per outline; fewer is cheaper and rougher |
| `blur` | `0.0` | Pays three more raycasts for a penumbra instead of a hard cut |
| `size` / `length` / `width` | `None` | A `rect`/`strip`'s box, in pixels |
| `points` | `None` | A `poly`'s outline |
| `hole` | `0.0` | A `ring`'s dark middle, as a fraction of the reach |

`turn(angle)` takes degrees or radians (a number over 6.3 is read as degrees),
`look_at(point, offset=0.0)` aims at a world pixel, `spin(secs)` sweeps it
round and `sweep(a0, a1, secs)` rocks it - a guard whose patrol view slides
down a corridor. A swept light that also `align=True`s onto an object is
overridden by that object every frame, so pick one.

Casting is the reason to use 2D lights. `outline()` hands back the polygon the
light actually reaches (a visibility polygon for `radial`/`cone`, a
ray-clamped outline for `rect`/`poly`), `shapes()` the one - or three, with
`blur` - meshes that go into the mask, and `poly` caches the main outline for
`strength_at()`. None from `outline()` means "a plain quad is enough".

```python
self.blockers = lambda: self.maze.blockers_near(self.player.pos, 600.0)
fov = self.add_light(pos=here, shape="cone", angle=76, radius=460,
                     follow=self.player, align=True, cast=True)
```

`blockers` - on the scene or on one light - accepts wall segments
`(x0, y0, x1, y1)`, objects with a `rect()`, objects with a `points` list, and
a zero-argument callable returning any of those. `fe.lights.blockers_of(items)`
is what flattens them, and `segment`, `rect_sides`, `poly_sides`,
`visibility(origin, walls, radius, center, spread, samples)`, `ray_hit`,
`clip_walls` and `point_in_polygon` are the maths underneath, yours to call.

## Making it alive

Every verb returns the light, so they chain.

| Verb | Signature | Looks like |
| --- | --- | --- |
| `fade_to` | `fade_to(energy=1.0, secs=0.5, keep=True, rate=None)` | A lamp coming up; `keep=False` switches it off at the end |
| `flash` | `flash(amount=2.0, secs=0.14)` | A muzzle flash, a hit, one bright kick that decays |
| `blink` | `blink((on, off))` or `blink((on, off, dim))` | A sign; `dim` is what the off half holds |
| `strobe` | `strobe(rate=8.0, duty=0.5)` | An alarm, a camera flash |
| `sputter` | `sputter(amount=0.9, rate=2.5)` | A dying bulb, random dropouts |
| `flickering` | `flickering(amount=0.18, rate=9.0, seed=None)` | An open flame |
| `pulsing` | `pulsing(amount=0.35, rate=1.0)` | A warning lamp |
| `throb` | `throb(rate=1.2, amount=0.7)` | A heartbeat - fast, deep |
| `breathe` | `breathe(rate=0.25, amount=0.5)` | Slow in-out that never darkens fully |
| `ramp` | `ramp(stops, secs=4.0, loop=True)` | Keyframed colour + energy: a siren, a forge |
| `grow` | `grow(radius=None, secs=0.5, loop=False, dim=False)` | A ping widening, an explosion opening, a beam dying |
| `steady` | `steady()` | Undo blink / strobe / sputter / ramp / flash / fade / grow |
| `orbit` | `orbit(radius=1.0, secs=6.0, phase=0.0, plane=None)` | A wisp circling its spot |
| `sway` | `sway(amount=0.4, secs=3.0, axis=0)` | A swinging lantern |
| `path` | `path(points, secs=8.0, loop=True)` | Walk a polyline at a steady pace |
| `still` | `still()` | Stop `orbit` / `sway` / `path` where it stands |
| `spin` | `spin(secs=6.0, reverse=False)` | 3D: turn the cone; 2D: turn the shape |
| `sweep` | 3D `sweep(a0=-0.7, a1=0.7, secs=4.0)`, 2D in degrees | Rock between two headings |
| `gate` | `gate(fn)` / `ungate()` | Only shine while a predicate says so |
| `after` | `after(secs, fn)` | `fn(self)` once, from now |
| `every` | `every(secs, fn, count=None)` | `fn(self)` forever, or `count` times |

`ramp()` stops are `[(at, color), (at, color, energy), ...]` with `at` running
0..1, and the same as dicts (`{"at":, "color":, "energy":}`); a bare
`(at, energy)` pair works when every entry is a number. `flicker_style` is
`candle`, `bulb`, `fluorescent` or `random`.

## Ready-made lights

`scene.add_preset(name, pos, dim=None, tag=None, **kw)` or
`fe.lights.preset(name, scene, pos, ...)`; every key is a plain constructor
keyword, so a preset is a starting point. `dim=2` builds the 2D version of a
3D recipe (a `spot` becomes a `cone`), `dim=3` the 3D one.

| Preset | Shape | Character |
| --- | --- | --- |
| `candle` | point / radial | Small, deep flicker, visible glow |
| `campfire` | point / radial | Warm, big, lazy flicker |
| `torch` | spot / cone | Narrow, held, flickering |
| `lantern` | point / radial | Soft, close, gently unsteady |
| `flashlight` | spot / cone | Long, tight, `power` falloff |
| `bulb` | point / radial | Steady with a wide flat middle |
| `streetlamp` | point / radial | Amber, faintly buzzing |
| `neon` | point / radial | Cyan, fast shallow flicker |
| `fluorescent` | point / radial | White, drops out at random |
| `siren` | spot + `spin`, `strobe` | Red, strobing, turning |
| `lighthouse` | spot + `spin` | Long thin beam, one turn per 6 s |
| `searchlight` | spot + `sweep` | Rocks between two headings |
| `firefly` | point / radial | Gold, pulsing, tiny glow |
| `lava` | point / radial | Deep red, slow breathing |
| `monitor` | point / radial | Blue, 23 Hz shimmer |
| `sun` | sun | Directional, from `sun_direction(10)` |
| `tube` | tube / strip | A run of light, not a point |
| `pool` | radial | 2D: a quiet even circle |
| `doorway` | rect | 2D: light through an opening |
| `strip` | strip | 2D: a long thin bar |
| `ping` | ring + `grow` | 2D: a sonar ring that expands and dies |
| `wash` | world | 2D: an even tint over the frame |
| `blackout` | world, `negative` | 2D: the whole frame going dark |
| `void` | radial, `negative` | 2D: a pool that eats the light around it |
| `shadow` | radial, `negative` | 2D: a soft dark patch |

## Colour, and colour as a texture

`fe.colors` is the one parser behind every colour in the engine. All four
spellings reach the same sheet:

```python
self.add(meshes.box(), texture="#3c7ad6")            # hex, 3, 6 or 8 digits
self.add(meshes.box(), texture="rgb(60, 122, 214)")
self.add(meshes.box(), texture=(60, 122, 214))       # ints 0..255
self.add(meshes.box(), texture=(0.235, 0.478, 0.839)) # floats 0..1
```

| Function | Returns |
| --- | --- |
| `rgba(value, default=None)` | `(r, g, b, a)` floats 0..1, or `default` |
| `rgb(value, default=None)` | The same without alpha |
| `is_color(value)` / `is_spelling(value)` | Whether it reads as a colour at all / whether it spells one outright (hex, `rgb()`, a tuple) |
| `key(value)` | The texture key: a colour becomes `"#rrggbb[aa]"`, anything else passes through |
| `text(value, default="#ffffff")` | The hex string an inspector shows |
| `mix(a, b, t=0.5)` / `scaled(value, factor)` / `gray(value)` / `bytes_rgb(value)` | Blend, brighten, luminance grey, 0..255 ints |
| `NAMED` | 24 words: `white black grey gray red green blue yellow orange purple cyan brown stone rust steel sand grass blood gold torch flame night fog shadow` |

Anywhere a texture name goes, a colour works too - `scene.add(texture=)`, a
`.model3d`'s `texture` and its per-face `tex` list, `ModelObject(texture=)` and
`set_surface(face, key)`, `Object2D(texture=)`, `place_model(tint=)`.
`renderer.color_texture(value)` registers a solid sheet on the spot and hands
back its key; channels snap to 8 bits, so that key is `"#3c7ad6"` and one
sheet serves every surface tinted with it. A bare word is only read as a
colour where a colour - not a name - is expected, so a project's `stone.png`
can never be shadowed by the `stone` tint; `color="torch"` does take words.
`renderer.resolve_texture(value)` is the safe lookup: a key that exists, or
`None`, never a quiet swap to white.

Lights take colour the same way, plus `kelvin(temp)` on any light and
`lights.kelvin_rgb(temp)` (1000..40000 K) as the raw function.

## Ambient, sun, layers and the master dimmer

| Call | Does |
| --- | --- |
| `scene.set_ambient(color, level=1.0)` | The light that is always on, in 3D (`ambient`) and 2D (`ambient2d`) at once |
| `scene.ambient` / `scene.ambient2d` | The two numbers, for one world at a time |
| `scene.set_sun(dir=, color=, energy=, hour=)` | The scene's one directional light, on `scene.sun`, costing no slot |
| `scene.sync_sun()` | Copy the sun onto the uniforms the renderer reads |
| `scene.set_master(value)` | Dim everything, lights and ambient: `0` is a true blackout |
| `fe.lights.set_master(value)` / `get_master()` | The same dimmer without a scene; 0..4 is the band |
| `light.link("player", "fx")` / `unlink()` | Restrict a light to named layers |
| `obj.light_layer` | Which layers an object accepts light from (`None` = all) |
| `fe.lights.LAYERS` / `layer_bits(spec)` | `all world prop player enemy fx ui ground sky water`, and the parser for names, lists, `"a|b"` or a raw int |

The GPU passes do not sort by layer: use `affects(obj)` and `strength_at(pos)`
for the answer in your own logic.

Day / night:

```python
def update(self, dt):
    super().update(dt)
    self.hour = (self.hour + dt / 240.0) % 24.0
    self.sun.set_time(self.hour)          # dir, colour and energy at once
```

`fe.lights.daylight(hour)` hands back `{"hour", "sun_dir", "sun_col",
"sun_energy", "ambient", "fog"}` from `DAY_SKY`, and `sun_direction(hour,
tilt=0.25)` is the vector alone. `set_sun(hour=...)` applies the whole set,
including the ambient and the fog.

## Asking about light

| Call | Answers |
| --- | --- |
| `light.strength_at(pos)` | How much of it reaches a point (an occluding 2D light checks the polygon it drew) |
| `light.contains(pos)` | Whether that is nonzero |
| `light.affects(obj)` | Whether the layer masks agree |
| `light.distance_to(pos)` | Straight line, in the light's own units |
| `light.level()` / `light.tint(factor)` | The intensity it is carrying, and colour x that |
| `fe.lights.luminance_at(pos, lights, ambient=0.0)` | Total from any iterable |
| `scene.luminance(pos=None)` | The same over the scene's lights, ambient included; `pos=None` is the player |
| `scene.lights_near(pos, radius=None)` | Lights around a point, nearest first |
| `scene.light_count()` | `{"lights", "shining", "sun"}` |
| `light.gpu()` | The five tuples the shader actually uploads |

A stealth check is one line: `if self.scene.luminance(self.player.pos) > 0.2`.

## Saving a light

`light.to_dict()` writes everything - kind, pos, colour, knobs, shape and all
- and `Light.from_dict(data, scene)` rebuilds the right class. `scene.add_light(dict)`
does the same through the adoption route, so a level file is just a list:

```python
def on_save(self, save):
    save.set("lamps", [L.to_dict() for L in self.lights])

def on_load(self, save):
    for entry in save.get("lamps", ()): self.add_light(entry)
```

## Baked lights

A light with `bake=True` stops costing a shader slot. Once, the engine
draws its contribution - ambient, sun, every bake light, its atten
curve, spot cone, cookie - into a square texture called a **lightmap**
held in RAM and sampled on the second UV channel `uv2`. One map covers
a whole model - `"{model.name}@lm"` - or, when the file is split into
named objects, one map per object - `"{model}-{object}@lm"` - because
a per-object unwrap already gives each part the full 0-1 square to
itself. The per-frame cost becomes one `texture()` fetch and a
multiply. Live (non-bake) lights still add on top; a bake light does
not shine live.

Two entry points:

- `scene.bake_lights(size=None)` runs the pass by hand; the game calls
  it at scene entry when the project sets `render.bake_on_run` to true
  (default false). `size` is the lightmap's edge in pixels, the
  renderer's default (1024) when nothing is said. The call hands back
  how many maps got baked - models, or objects inside a model.
- The Build tab fires the same pass through
  `Project.bake_for_build(plan)`, wired in as `BuildConfig.post_stage`,
  right after the trim plan has staged the project. The pass writes
  `textures/{name}-lm.png` for every affected model - or
  `textures/{model}-{object}-lm.png` for each baked object of a split
  file - and patches the staged document to name that stem in its
  `lightmap` (the object's entry when there are objects, the top level
  otherwise), and drops every bake-flagged light entry from the staged
  scene docs. Nothing in the source project is touched; the built game
  pays no runtime bake for those lights.

Only a model with a `uv2` channel can hold a lightmap, so a plain
untouched prop keeps living on the scene's ambient and whatever lights
are still live. The Model tab unwraps a `.model3d` the first time UV
Paint mode opens, and `engine.unwrap.split_and_unwrap(model)` is
callable from a script; either qualifies the model for baking. See
[Models and Meshes](models-and-meshes.md).

Two scoping rules:

- One lightmap per model **name** - per (model, object) pair once the
  file carries objects - shared across every placement of that model,
  matching the engine's no-shadow distance-atten lighting model. Two
  crates under the same bake lamp wear the same map. Per-placement
  lightmaps are out of scope.
- Only 3D lights bake. A `Light2D` stays live; the 2D pass already
  draws a per-shape mask and is not the cost this feature targets.

Bake means base intensity. `flicker`, `pulse`, `blink`, `strobe`,
`fade_to` and `ramp` on a bake light record the energy the light was
made with - not what it would look like mid-animation - so a bake
light worth seeing is usually one that also `steady()`s.

Caveat: the build strip only removes bake nodes placed in scene
documents. A script that calls `scene.add_light(..., bake=True)` at
runtime keeps that light live in the built game and no map for it is
written; add bake lights from the Scene tab, not from scripts, if the
build pass should see them.

## How it is drawn

| Fact | Detail |
| --- | --- |
| 3D slots | `renderer.MAX_LIGHTS = 8`, chosen by `priority` then distance from the eye; a light switched off or spent is out before either |
| 2D lights | Cost no slot: each owns one small mesh drawn into a light-mask FBO, multiplied over the frame at the end of its region |
| Unlit corners | The mask is cleared to `scene.ambient2d x master`, so the multiply is what makes them dark |
| Dark pools | A `negative` light emits its complement and is blended as a multiply - an 8-bit target cannot go below zero |
| Energy | Rides one shared gradient sheet as `u_boost`, so a hundred lamps are one texture |
| Cookies | `cookie="fan"` projects a texture through a 2D shape or a 3D `spot` cone - one sheet per frame in 3D, the first cookie'd spot in the list owning it |
| HUD | `blend="hud"` (what `UIObject` defaults to) is drawn after the multiply, so widgets stay readable in a dark room |
| 3D shadows | Not implemented - light passes through geometry |
| Cost | 2D `cast` raycasts every dirty frame; `samples` and `blur` are the two dials, and a `blockers` callable that returns only nearby walls keeps a maze cheap |

`lights.PRESETS`, `SHAPES_3D`, `SHAPES_2D`, `NAME_2D`, `ATTEN`, `FLICKER` and
`LAYERS` are plain dicts, readable and extensible.
