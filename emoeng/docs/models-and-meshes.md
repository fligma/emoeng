# Models and Meshes

Two layers of geometry: model files - JSON in `models/` (or `maps/`),
authored in the Model tab or written by hand - and the `meshes` builders
that generate geometry at runtime. Both end up as `MeshData`, which the
renderer turns into one vertex batch per texture, lightmap and blend mode.

A model's extension is its dimension, the same way an object document's is:
`models/<name>.model3d` is a solid mesh, `models/<name>.model2d` a flat rig of
cutout parts. The old `.model` spelling is still read, and
`Project.upgrade_documents()` renames it to `.model3d` when the project opens.

A **map** reuses exactly the schema below, in `maps/`, and adds six keys: a
`kind`, a `collision` mode, a `spawn` point and a `nodes` list of things the
level places. `maps/<name>.map3d` is a walked level, `maps/<name>.map2d` its
flat twin; a legacy map file that is only geometry still loads. The full
format, the parts a level is carved into and swapping a level mid play are
[Maps](maps.md); here the geometry half is what matters, since it is spelled
the same way and carved the same way in the Model tab.

## The `.model3d` format

Plain JSON, so it stays diff-able and hand-editable.

```json
{
 "format": "fligmodel",
 "version": 1,
 "name": "crate",
 "texture": "crate",
 "color": [0.8, 0.8, 0.8],
 "pivot": [0.0, 0.0, 0.0],
 "verts": [[x, y, z], ...],
 "uvs":   [[u, v], ...],
 "tris":  [[a, b, c], ...],
 "tex":   ["stone", null, ...],
 "uv":    {"scale": [2, 2], "offset": [0, 0], "rot": 0.0}
}
```

| Key | Meaning |
| --- | --- |
| `format` / `version` | `'fligmodel'` / `1` |
| `name` | Overridden by the file stem on load and save |
| `texture` | Default surface for faces without their own tag - a texture key **or any colour spelling `fe.colors` reads** (`"#3c7ad6"`, `(60, 122, 214)`, `"gold"`), which the renderer turns into a solid sheet on the fly |
| `color` | Linear RGB multiply |
| `pivot` | Origin offset used when placing |
| `verts` | Positions, base on `y = 0`, so placing at ground level is just `pos` |
| `uvs` | One `[u, v]` per vertex, parallel to `verts` |
| `tris` | Index triples, counter-clockwise seen from outside |
| `tex` | Optional, parallel to `tris`: one surface per face, `null` for the default; takes a texture key or a colour just like `texture`, which is how the Model tab's Colour button paints one face |
| `uv` | Optional, one sheet transform for the whole model - see below |
| `uv2` | Optional, per-vertex second UV channel (the lightmap / paint atlas) |
| `lightmap` | Optional, texture key the second channel samples |
| `painted` | Optional flag; when true the albedo uses the second channel |
| `objects` | Optional, the named parts this file is built from - see Objects below |

A bare JSON array is read as a vertex list (`{"verts": [...], "tris": []}`), and
`faces` is accepted as a synonym of `tris`. `Model._fix_lengths()` pads `uvs`
and drops any triangle that indexes past the vertices, so a hand-edited file
cannot crash the loader.

Rendering flattens per-triangle normals - faceted shading, no smoothing groups -
and `mesh_groups()` splits a placed model into one batch per surface so a crate
can have iron bands with their own texture.

### Objects

A file can hold several named parts. `objects` is a list of small dicts, and
every one claims some of the model's faces:

```json
{
 "name": "keep", "texture": "grid",
 "verts": [[...]], "tris": [[...]],
 "objects": [
  {"name": "floor", "faces": [0, 1], "texture": "ground",
   "painted": false, "lightmap": null},
  {"name": "walls", "faces": [2, 3, 4, 5], "texture": "stone",
   "painted": false, "lightmap": null}
 ]
}
```

| Key | Meaning |
| --- | --- |
| `name` | Unique inside the file; the Model tab's Objects rail shows one row per name |
| `faces` | Indices into `tris` - the faces this object owns |
| `texture` | The object's own surface - a texture key or a colour, or `null` for the face tag / the model sheet |
| `painted` | This object's albedo is a `uv2` atlas of its own |
| `lightmap` | This object's own baked map, `{model}-{object}-lm` |

The two rules underneath: every face belongs to **exactly one** object (a face
no object claims is filed to the first), and every vertex to one object too -
`make_object(name, faces)` duplicates any corner its faces share with another
object, at the same position, so moving one part never drags a neighbour.
`align_objects()` repairs both claims after a hand edit; a file with **no**
`objects` key is one implicit object wearing the model's name, and every
existing model, paint sheet and lightmap keeps its current bytes and keys.

What an object changes is where a value is read from. `meshdata()` works face
by face: a painted object samples `uv2`, an unpainted face samples `uv`, and
the albedo key comes from the face's owner before the face tag and the model
sheet. `MeshData` keeps a parallel `lms` list, so `texture_groups()` splits a
placed model by `(texture, lightmap)` - one batch per surface per map - and
stamps `piece.lightmap`. A `None` entry means "inherit the model's own", which
is what a legacy file asks for, and reduces to exactly the old code path.

### The `uv` block

`verts` and `uvs` are baked numbers, so a picture stretched over a big face used
to mean dragging every vertex. `uv` is the alternative: three values applied to
the whole sheet when geometry is built, so the stored vertices are never
rewritten and the block can be edited straight back out.

| Key | Default | Does |
| --- | --- | --- |
| `scale` | `[1, 1]` | Repeats - or stretches - the picture across `u` and `v`; `[2, 2]` tiles it four times, `[1, 0.25]` pulls it flat |
| `offset` | `[0, 0]` | Slides the sheet in uv space; with the default `wrap` of `repeat` it comes back on the other side instead of running off the edge |
| `rot` | `0.0` | Radians about the sheet centre - a quarter turn is `1.5708` |

The order is scale about `0.5, 0.5`, then rotate, then slide, so tiling stays
centred on the picture rather than drifting away from the middle of it.

```json
{
 "name": "pillar", "texture": "stone",
 "uv": {"scale": [2.0, 2.0], "offset": [0.0, 0.0], "rot": 0.0}
}
```

Nothing is written until the transform says something: `uv_identity()` holds for
the defaults and `to_dict()` emits a `uv` block only when it does not, so an
untouched model keeps the byte-exact file it always had. Values round to four
decimals, the same as the vertices.

What the block changes is where a sheet lands; how that sheet is sampled - hard
or smeared - stays the file's own setting in `assets.json`, since one GL texture
is shared by every model that names it. Both halves are edited side by side in
the Model tab's texture mode; see [The Editor](editor.md).

One exception, and it is a big one: a sheet that `assets.json` gave a world size
to (`textures.tile`) is a *material*, and the renderer re-unwraps whatever wears
it from the geometry's own metres. The `uv` block is still read and still
written for such a sheet, but it no longer decides where the picture lands - the
wall does. Leave `tile` at 0 for a model whose sheet is a picture of one
particular thing, which is nearly every prop: a face, a crate lid, an icon.
See [Camera and Rendering](camera-and-rendering.md) for how the tiling is done.

### UV2 and lightmaps

A model can carry a second UV channel, `uv2`, alongside the tiled albedo
channel `uv`. `uv2` maps each corner to a non-overlapping patch of a
square atlas - a **lightmap** or a **painted sheet** - so a picture can
be written per-texel without fighting a tile's repeats.

`engine.unwrap.split_and_unwrap(model, faces=None)` returns `(verts, uvs, uv2,
tris, tex)` for any model. It builds face adjacency, cuts seams at boundary
edges and at sharp dihedral bends, unfolds each chart by swing-out BFS
so edge lengths are preserved, and shelf-packs the charts into 0..1
with a margin. Coplanar runs merge into one chart, so a cube comes back
as six patches rather than twelve. A chart that will not flatten
without overlap falls back to per-face planar projection, so a
degenerate mesh still gets an atlas, just a coarser one. A model with
no triangles returns five empty lists. Passing `faces=[...]` unwraps
only those triangles into the full 0..1 and splits their corners off
from the rest, leaving every other object's `uv2` untouched - one
object, one sheet.

Two keys use the channel:

- `lightmap` names a texture key the renderer samples on `uv2` and
  multiplies over the lit result. See [Lighting](lighting.md) for how
  a `bake`-flagged light fills one.
- `painted` says the model's own albedo sheet is that atlas: it too is
  sampled on `uv2`, and the whole-model `uv` block stops deciding
  where the picture lands.

The two are independent. A model that is only **baked** keeps its
tiled albedo on `uv` and uses `uv2` solely for the lightmap; a model
that is only **painted** switches its albedo onto the painted atlas
and has no lightmap; a model that is both uses `uv2` twice, once for
albedo and once for the map.

The RAM key a scene-entry bake uses is `"{model.name}@lm"` for a whole model,
or `"{model.name}-{object.name}@lm"` for one object of a multi-object file; the
file a build-time bake writes is `textures/{model.name}-lm.png` - or
`textures/{model.name}-{object.name}-lm.png` - and the document's `lightmap`
(the object's, when there are objects) becomes that stem. A UV Paint save
goes to `textures/{model.name}-uv-tex.png`, and the model's `texture`
becomes `"{model.name}-uv-tex"`; a save on one object of a multi-object file
goes to `textures/{model.name}-{object.name}-uv-tex.png` and sets that
object's `texture`. A legacy single-object file keeps the model-level
spellings exactly.

## `Model` API

```python
m = Model(name="crate", verts=None, uvs=None, tris=None, texture="white",
          color=(1.0, 1.0, 1.0), pivot=(0, 0, 0), tex=None, uv=None)
```

| Group | Members |
| --- | --- |
| Facts | `tri_count`, `empty`, `bounds()`, `centre()`, `radius()` |
| Sheet transform | `uv_scale`, `uv_offset`, `uv_rot`, `uv_identity()` |
| Second channel | `uv2`, `lightmap`, `painted` - see UV2 and lightmaps |
| File IO | `Model.load(path)`, `Model.loads(text, name=...)`, `to_dict()`, `dumps()`, `save(path)` |
| For rendering | `meshdata(pos, yaw, scale, tint, faces=None)`, `mesh_groups(pos, yaw, scale, tint)` |
| Editing | `add_vertex(pos, uv)`, `add_face(a, b, c, uvs=None, tex=None)`, `add_meshdata(md)`, `append(other, offset)`, `add_primitive(kind, size, offset)` |
| Objects | `has_objects`, `object_names()`, `object_of_face(f)`, `object_verts(name)`, `obj_bounds(name)`, `align_objects()`, `make_object(name, faces)`, `rename_object(old, new)`, `set_object_texture(name, key)`, `merge_objects(names)` |
| Removing | `delete_faces(faces)`, `delete_vertices(indices)`, `faces_using(indices)` |
| Faces | `face_normal(face)`, `face_centre(face)`, `flip_face(face)`, `face_texture(face)`, `set_face_texture(face, key)` |
| Transforms | `move_verts(indices, delta, snap=0.0)`, `translate(delta)`, `scale(factor, origin)`, `rotate_y(angle, origin)` |
| Tools | `extrude(face, dist)`, `weld(eps=0.0001)`, `auto_uv(faces=None)`, `align_tex()`, `clone()`, `snapshot()`, `restore(snap)` |

`snapshot()` / `restore()` are what the Model tab's undo stack keeps, and
`add_meshdata()` is how a script pours generated geometry into a file.
`meshdata(faces=[...])` hands back just one object's triangles - what a
per-object bake uses - and `merge_objects(names)` folds two or more parts
into the first-named one, dropping any face that ends up enclosed inside a
neighbour and welding the survivors' coincident vertices.

### Primitive factories

| Function | Signature | Shape |
| --- | --- | --- |
| `new_model` | `new_model(kind='box', size=1.0, texture='white', name=None)` | The one entry point the editor uses |
| `box_model` | `box_model(size=1.0, name='box')` | Cube, base on `y = 0` |
| `plane_model` | `plane_model(size=2.0, name='plane')` | Flat quad |
| `wedge_model` | `wedge_model(size=1.0, name='wedge')` | Ramp, rising toward `+Z` |
| `cylinder_model` | `cylinder_model(size=1.0, seg=12, name='cylinder')` | Y-up, base on `y = 0` |
| `cone_model` | `cone_model(size=1.0, seg=10, name='cone')` | |
| `sphere_model` | `sphere_model(size=1.0, seg=12, rings=6, name='sphere')` | UV sphere, base on `y = 0` |

`model.PRIMITIVES = ('box', 'wedge', 'cylinder', 'cone', 'plane', 'sphere')` -
the same list the Model tab's toolbar offers. `new_model()` is what the editor's
New Model and New Map dialogs call; the first writes
`models/<stem>.model3d`, the second `maps/<stem>.map2d` or `.map3d` depending
on the kind picked - see [Maps](maps.md).

Each factory unwraps its own shape in metres per repeat, so a cube side, a
drum and a ramp all wear the same grain at the same size. That is why
`new_model()` does **not** finish with `auto_uv()`: the projection is normalised
by the model's bounds, so running it over a shape that already knows its sheet
squeezes every narrow face into a slice of the picture - the stretch two sides
of a box used to show. `auto_uv(faces=None)` is the fallback for geometry that
arrived with no sheet of its own, and takes a face list so an imported mesh can
be unwrapped part by part.

## `.model2d`

The flat sibling: named cutout parts plus keyframe tracks, for sprites that bend
instead of flipping through a sheet.

```json
{
 "format": "fligmodel2d", "version": 1, "name": "hero",
 "size": [64, 64], "texture": null, "pivot": [0.5, 0.5],
 "parts":  [{"name": "body", "texture": null, "uv": [0, 0, 1, 1],
             "pos": [0, 0], "rot": 0.0, "scale": [1, 1], "parent": null}],
 "tracks": [{"part": "body", "prop": "rot", "keys": [[0.0, 0.0], [0.5, 0.3]]}]
}
```

| Field | Meaning |
| --- | --- |
| `size` | The rig's box in pixels; every part is drawn at this size, so a part is a window on a sheet rather than a shape of its own |
| `texture` | The sheet a part with no `texture` of its own is cut from; a colour works in its place |
| `pivot` | `0..1` inside that box, which the node's `pos` sits on |
| `parts[].uv` | `0..1` rect cut from the texture |
| `parts[].pos` | Pixels from the pivot |
| `parts[].rot` | Radians |
| `parts[].parent` | Another part name, so limbs hinge |
| `tracks[].prop` | One numeric part property |
| `tracks[].keys` | `[time, value]` pairs, linear between them |

`Model2D` members: `part(name)`, `load`, `loads`, `to_dict`, `dumps`, `save`, and
the plain `size` / `texture` / `pivot` / `parts` / `tracks` the document holds;
`new_model2d(name, size, texture)` writes one `body` part covering the whole
sheet.

A `.model2d` opens in the editor's Model tab in a dedicated 2D rig mode - the
parts, transforms, uv, parents and rot tracks edited in a flat viewport that
draws them the way `fe.Sprite2D` below will; see [The Editor](editor.md).

`fe.Sprite2D` is what draws it. A node whose document names `"model": "hero"`
takes one quad per part, keeps the rig's own box as the node's `size`, and plays
the tracks as it updates - `track_value(part, prop, t)` is the sampled number, and
`playing` / `speed` are the knobs a document can set. So a swaying lantern is a
`.model2d` and an `.obj2d`, with no script anywhere:

```json
{
 "format": 1, "name": "lantern", "type": "sprite2d",
 "model": "lantern", "pos": [36.0, 40.0]
}
```

Only `rot` tracks are played back on a part's own quad, and a flat sheet is
still the simplest way to animate a sprite: `Object2D(grid=(cols, rows))` with
`animate(fps)` walks the cells - see [Objects](objects.md).

### Which nodes read which file

| Node | Reads | Does |
| --- | --- | --- |
| `Model3D` | `models/<name>.model3d` | Draws it at the node's transform, movable, or stamped into the static batch with `knobs: {"stamp": true}` |
| `Map3D` | `maps/<name>.map3d` | Draws it **and** files a `TriMesh` built from its own triangles - what `collision` in the file does with that shape (`"mesh"` / `"boxes"` / `"none"`) and `solid` decide whether a body is stopped by it - see [Collision](collision.md) and [Maps](maps.md) |
| `Map2D` | `maps/<name>.map2d` | Draws the same file flat, one quad per part, and files one `Collision2D` **per carved part** at the map's `solid` |
| `Sprite2D` | `models/<name>.model2d` | One quad per part, with the rig's tracks playing |
| `Object3D.place_model()` | the same files | The script-side stamp; `model_object()` is the movable one |

## `meshes` builders

Every builder returns a `MeshData`. Colours are linear RGB `(r, g, b)` in 0..1;
`uv` pairs are tiling repeats across the face. A fourth colour number is
accepted anywhere a colour is, and it is the piece's *opacity* - see
[Objects](objects.md) for the `opacity` knob that drives it.

### 3D

| Function | Signature |
| --- | --- |
| `box` | `box(centre=(0,0,0), size=(1,1,1), yaw=0.0, col=(1,1,1), uv=(1,1), lean=0.0)` |
| `cylinder` | `cylinder(centre=(0,0,0), r=0.5, h=1.0, seg=10, col=(1,1,1), yaw=0.0, lean=0.0, capped=True, uv=(1,1), taper=1.0)` |
| `cone` | `cone(centre=(0,0,0), r=1.0, h=1.5, seg=9, col=(1,1,1), yaw=0.0, uv=(1,1))` |
| `plane` | `plane(centre=(0,0,0), size=(50,50), seg=32, height_fn=lambda x, z: 0.0, color_fn=lambda x, z, h: (1,1,1), uv_scale=8.0)` |
| `tile_plane` | `tile_plane(centre, size, seg, height_fn, color_fn, tile_fn=lambda ix, iz: (0, 0), cols=8, rows=16)` |
| `face_auto` | `face_auto(md, pts, col, uvs=None, outward=None)` |
| `billboards` | `billboards(centre, w, h, count=3, col=(1,1,1))` |

| Notes | |
| --- | --- |
| `taper < 1` | Turns a cylinder into a trunk or cone |
| `lean` | Rotates about Z, tipping a Y-up shape toward `+X` |
| `plane.height_fn` | Deforms the XZ grid; normals come from finite differences |
| `tile_plane` | Independent quads, each picking one cell of a tiled sheet - ground that changes per tile |
| `face_auto` | Adds a 3- or 4-point polygon and works its own normal out of the winding |
| `billboards` | Crossed camera-facing quads for flames and glows - a yaw-only fake |
| `tile_world` | `tile_world(data, metres, anchor=None)` - not a builder: re-unwrap a finished mesh so its sheet repeats every `metres` world metres. Returns a twin with new uv and the same soup, and it is what the renderer does by itself for any sheet `assets.json` gave a size to, so a scene's hand-written `uv=` counts are only needed when a sheet has none. A side that turns all the way round is measured along its arc, so `uv_tile` holds on a cylinder as well as on a wall |
| `anchor` | The pin the projection is measured from: `(x, y, z)`, or `(x, y, z, yaw)` to write it in a turned body's own axes. `frame_pin(pos, yaw)` makes one from an object and `slide_pin(pin, off)` carries it with the body, so a moving or turning mesh keeps the same picture rather than swimming through it; without one the mesh's own middle is used |

### 2D

| Function | Signature | Notes |
| --- | --- | --- |
| `quad2d` | `quad2d(pos, size, col=(1,1,1), uv=(0,0,1,1), rot=0.0, layer=0.0, anchor=(0.5,0.5))` | The sprite quad; flips V so image coordinates read naturally |
| `rect2d` | `rect2d(pos, size, col=(1,1,1), rot=0.0, layer=0.0, anchor=(0.5,0.5))` | Flat untextured fill - panels, bars |
| `sprite_uv` | `sprite_uv(col, row, cols, rows, pad=0.0)` | The `(u0, v0, u1, v1)` of one sheet cell; `pad` bleeds inward to stop neighbour seepage |

`layer` is the draw order within the batch for 2D, so parallax rows can be
stacked without touching depth.

### `MeshData`

| Member | Notes |
| --- | --- |
| `vert(p, n, uv, col)` / `tri(a, b, c, tex=None)` | Append by hand |
| `quad(a, b, c, d, n, col, uvs=None, flip=False, tex=None)` | Two triangles and a normal |
| `quad_idx(a, b, c, d, reverse=False, tex=None)` | Same, from existing vertex indices |
| `append(other)` | Concatenate another piece |
| `bounds()` | `(min, max)` corners, or `None` when empty |
| `uv2`, `lightmap`, `lms` | The second channel, the model-wide baked key, and one key per face (`None` inherits `lightmap`) |
| `texture_groups(default='white')` | Split into `[(key, MeshData)]`, one per **(surface, lightmap)** pair - a batch whose faces share both |
| `align_tex()` / `align_lms()` | Pad or trim the per-face tags / lightmap keys to the triangle count |
| `arrays()` | The interleaved-ready buffers the renderer consumes |
| `empty` | Property |

## Procedural textures (`proctex`)

Painted from numpy noise at runtime, so a game needs no image files to look like
something. Each returns a `uint8` array ready for `renderer.texture(key, arr)`.

| Function | Signature | Look |
| --- | --- | --- |
| `checker` | `checker(size=64, cells=8, a=(0.55,0.55,0.52), b=(0.3,0.3,0.34))` | The editor / placeholder checker |
| `grid` | `grid(size=128, cells=8, line=(0.18,0.2,0.22), fill=(0.38,0.4,0.42), width=2)` | Floors, crates, editor surfaces |
| `ground` | `ground(size=256, seed=101)` | Soil and grit |
| `stone` | `stone(size=128, seed=202)` | Blocky rock |
| `rust` | `rust(size=128, seed=303)` | Orange bloom over dark iron |
| `bark` | `bark(size=64, seed=404)` | Vertical fibre |
| `cloth` | `cloth(size=64, seed=505)` | Woven weave |
| `stripes` | `stripes(size=64, count=8, a=(0.55,0.18,0.12), b=(0.8,0.74,0.55), vertical=True)` | Bands |
| `glow` | `glow(size=128, color=(1.0,0.62,0.22), seed=606)` | RGBA radial glow for additive billboards |
| `flame` | `flame(size=128, seed=707)` | RGBA teardrop fire with a hot core |
| `noise_rgb` | `noise_rgb(size=128, seed=808, tint=(1.0,1.0,1.0))` | Grain for dirt overlays and UI fills |
| `noise` | `noise(size=128, cells=6, octaves=4, seed=909, gain=0.5, contrast=1.0, tint=(0.62,0.60,0.56), base=0.0, alpha=False)` | Fractal value noise, filed as a sheet in its own right; `alpha=True` cuts holes instead of painting a colour |
| `noise2d` | `noise2d(h, w, cells, seed)` | The smooth value noise the rest are built from. Its lattice wraps, so a sheet built on it tiles |
| `solid` | `solid(color=(1.0,1.0,1.0), size=2)` | A flat swatch - what `renderer.color_texture()` paints so a colour works wherever a texture name goes |
| `radial` | `radial(size=128, soft=0.0, mode=0, exponent=2.0, outer=(1,1,1), shape="circle", hole=0.0)` | The falloff gradient a 2D light draws its shape with (`shape` `circle`/`box`/`ring`, `hole` the dark middle of a ring) |

```python
def setup(self):
    r = self.renderer
    r.texture("ground", fe.proctex.ground(256))
    r.texture("bark", fe.proctex.bark(64))
    r.texture("halo", fe.proctex.glow(128, (0.4, 0.8, 1.0)), rgba=True)
```

RGBA images (the ones with real transparency) want `rgba=True`, which clamps the
wrap and skips mipmaps so a sprite's edges stay clean.

### The built-in sheets

`proctex.SHEETS` is the table of sheets a renderer can name without a file -
ten `(name, factory, knob defaults, register options)` rows, flattened into the
`(name, build it, options)` tuples `proctex.BUILTIN` holds, in the order a
palette lists them:

| Name | Built by | `tile` m | |
| --- | --- | --- | --- |
| `checker` | `checker(64, 8)` | 0.5 | |
| `grid` | `grid(128, 8)` | 1.0 | |
| `ground` | `ground(256)` | 2.0 | |
| `stone` | `stone(128)` | 1.0 | |
| `rust` | `rust(128)` | 0.5 | |
| `bark` | `bark(64)` | 0.25 | |
| `cloth` | `cloth(64)` | 0.2 | |
| `noise` | `noise(128, cells=6)` | 1.0 | the generator, filed as a sheet |
| `flame` | `flame(128)` | - | `rgba`, no repeat |
| `glow` | `glow(128)` | - | `rgba`, no repeat |

`tile` is the metres one repeat of the sheet covers, and that is what makes a
built-in lie over the uv the way a shader would rather than as a picture
pasted over one object: a 2 m floor and a 20 m wall then wear the same grain
per metre. The renderer does it itself through `meshes.tile_world`, so a scene
that only names `"stone"` needs no `uv=` count, and the Model tab's Texture
shelf shows the number and lets you turn it - see [The Editor](editor.md).
The eight that repeat meet themselves at the seam, so a floor drawn repeat
after repeat of one has no grid across it. `flame` and `glow` are sprites and
are not meant to tile.

| Helper | Returns |
| --- | --- |
| `names()` | the built-in stems, in the order a palette lists them |
| `knobs(name)` | every knob of one sheet, with the value it starts on |
| `accepts(name)` | the knob names its factory actually takes |
| `build(name, **over)` | the sheet as an array with knobs turned, or `None` |
| `options(name)` | how it registers: `tile`, `rgba`, `repeat` |

So a palette can paint a thumbnail of the bytes a scene will actually draw, and
offer the knobs of any sheet as fields, without naming a factory.
`register_builtin_textures(renderer)` uploads the whole table - `Game` calls it
before the first scene, and so do the editor's preview and every screen's own
renderer, because a renderer skips a batch whose texture it was never given. A
project may file a built-in's stem under `assets.json` `textures.sheets` as well
as a PNG's, and `builtin_sheet(name, project)` reads those overrides before
uploading - which is how a `stone` is made coarser, or a `bark` set to
`nearest`, with still no image file anywhere.

```python
from emoeng.engine.game import register_builtin_textures

register_builtin_textures(renderer)      # "stone" now means something
```

Project files under `textures/` are loaded instead - and with the filter, wrap
and mipmap settings from `assets.json` - by
`Project.register_textures(renderer)`, which the game calls at start-up. A
sheet can carry its own entry inside those settings, which is how a pixel-art
`stone` stays `nearest` while a painted sky goes `linear`; see
[Project Folder](project-folder.md). A scene can therefore mix a PNG bark with a
procedural glow without either knowing about the other.
