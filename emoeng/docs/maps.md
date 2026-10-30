# Maps

A **map** is a whole level in one file: the geometry it is carved into named
parts, the nodes it places - walls, lights, triggers, prefabs - and the spot a
player starts on. `maps/<name>.map3d` is a walked 3D level and `maps/<name>.map2d`
is its flat twin; both are the same document shape, and both are loaded,
swapped and re-dressed at runtime.

This is the point of the format. A scene does not build its room out of
`self.add(...)` calls any more:

```python
class Main(fe.Scene3D):
    name = "main"
    map_name = "hall"          # or "map": "hall" in scenes/main.scene

    def setup(self):
        start, yaw = self.spawn_point()      # the map says where
        self.player = self.spawn(fe.Player3D, pos=start, yaw=yaw)
```

The level is a file, so the editor draws it, the Project View lists its parts
and nodes, and a second level is a second file rather than a second scene.

| Page | What it covers here |
| --- | --- |
| [Models and Meshes](models-and-meshes.md) | The geometry keys a map reuses verbatim - `verts`, `tris`, `tex`, `objects`, `uv` |
| [Scenes](scenes.md) | Where a map sits in a scene's build order |
| [Collision](collision.md) | `TriMesh` sweeps, `Collision3D` / `Collision2D` boxes |
| [Objects](objects.md) | The node types a map may place, and their `knobs` |
| [Editor](editor.md) | The `maps/` folder, New Map 3D / 2D, the Scene tab's map row |

## The format

Plain JSON, `format` `"fligmap"`, `version` `2`. Everything a model file
spells is here under exactly the same name, and six keys are new.

```json
{
 "format": "fligmap",
 "version": 2,
 "kind": "map3d",
 "name": "hall",
 "texture": "ground",
 "color": [1.0, 1.0, 1.0],
 "verts": [[x, y, z], ...],
 "uvs":   [[u, v], ...],
 "tris":  [[a, b, c], ...],
 "tex":   ["stone", null, ...],
 "objects": [
  {"name": "floor", "faces": [0, 1], "texture": null,
   "painted": false, "lightmap": null},
  {"name": "wall_left", "faces": [2, 3], "texture": null,
   "painted": false, "lightmap": null}
 ],
 "collision": "none",
 "solid": false,
 "spawn": [0.0, 0.0, 5.2],
 "spawn_yaw": 3.1416,
 "nodes": [
  {"id": "wall_left", "type": "collision3d", "pos": [-4.0, 1.5, 0.0],
   "knobs": {"shape": "box", "half": [0.15, 1.5, 4.0]}},
  {"id": "lamp_w", "type": "omnilight3d", "pos": [-2.0, 2.7, -3.0],
   "knobs": {"color": "#ffad68", "energy": 2.2, "radius": 8.5}},
  {"id": "lectern_spot", "type": "spotlight3d", "pos": [0.0, 2.9, 1.2],
   "knobs": {"angle": 52.0, "aim": [180.0, -51.0]}}
 ],
 "overrides": {}
}
```

| Key | Meaning |
| --- | --- |
| `kind` | `"map3d"` or `"map2d"`; the file extension says the same thing and wins when a file is opened by name |
| `verts` `uvs` `tris` `tex` `uv` `uv2` `lightmap` `painted` `objects` `texture` `color` `pivot` | The geometry half, spelled exactly as a `.model3d` spells it - see [Models and Meshes](models-and-meshes.md) |
| `collision` | How the map's **own faces** stop a body: `"mesh"` (a `TriMesh` built from the triangles), `"boxes"` (one solid shape per carved part) or `"none"` (the placed nodes do all the stopping). A `.map2d` has no triangles to sweep, so `"mesh"` settles to `"boxes"` - one rect per part, which is what a flat map has always filed |
| `solid` | Optional; whether this map's shape is a wall at all. `false` with `"collision": "none"` means the level is scenery and its `collision3d` / `collision2d` nodes are the stops |
| `group` | Optional; who this map's collider stops, as `Collision3D.group` spells it |
| `tint` | Optional; a colour multiplied over the whole level |
| `spawn` | `[x, y, z]` for a 3D map, `[x, y]` for a flat one (a `z` is appended). Absent or empty means the scene falls back to its own default |
| `spawn_yaw` | Radians the player is turned to at that spot |
| `nodes` | What the map places, in exactly the shape a scene document's `objects` list uses - node types, scripts, and `{"object": ...}` instances with `children` |
| `overrides` | Per-node tweaks keyed by node id, the same `plan` a scene document writes when you drag something |

A key the engine does not know is left where it is, so a map can hold its own
notes. A **legacy** `.map3d` - one that has only geometry, written before there
were levels - still loads: `mapdoc.load()` fills in `nodes: []`,
`collision: "mesh"` and no spawn, so it draws and collides exactly as it always
did and simply places nothing.

### What the map itself stops you with

`collision` and `solid` are the same two questions, and only the first is about
shape:

| `collision` | The map node files | Walking into a wall |
| --- | --- | --- |
| `"mesh"` | one `TriMesh` of the whole level, re-filed when the node moves | stopped by the real surface, at any angle |
| `"boxes"` | one `Collision3D` child per carved part, as a world AABB - `map_node.shape_nodes` | stopped by the part's box, so a narrow gap inside one part is walkable |
| `"none"` | nothing | walked straight through: only the map's `nodes` stop a body |

`solid: false` switches the whole shape off without changing it, which is what
a scenery level or a backdrop wants. `"mesh"` costs a triangle sweep over every
face; `"boxes"` is the cheap answer for a level made of rectangular rooms. Both
are per-part honest: `"boxes"` reads the same `objects` list the editor carves,
so renaming or moving a part moves its shape too.

### Parts

The `objects` list is what a level is carved into: `floor`, `wall_left`,
`plinth_2`, `roof`. Every face belongs to exactly one part, and a part is the
unit a script re-dresses at runtime:

```python
scene.map.parts()                       # ['floor', 'wall_left', ...]
scene.map.set_part_texture("floor", "stone")
scene.map.set_part_texture("floor", None)   # back to the carved sheets
```

`None` reverts to whatever the file tagged, so a switch that puts a new sheet
on the floor can always put the old one back. A face with no tag of its own
wears the whole map's `texture`.

### Nodes

`nodes` is placed by the same router a scene document uses
(`engine.placement.Placer`), so anything a scene can put down a map can too:

| Entry | What it does |
| --- | --- |
| `{"type": "collision3d", "knobs": {"shape", "half", "group"}}` | A solid box / sphere / capsule the scene stops at - the usual reason a map sets `collision: "none"` |
| `{"type": "hitbox3d", ...}` | The same shape, non-solid: it only reports entries |
| `{"type": "collision2d" / "hitbox2d", "size": [w, h]}` | The flat pair |
| `{"type": "omnilight3d" / "spotlight3d" / "directionallight3d", "knobs": {...}}` | A light that leaves with the map |
| `{"type": "model3d", "model": "crate"}` | A mesh from `models/` stamped at this node |
| `{"script": "scripts/objects/door.py"}` | A scripted object the map owns |
| `{"object": "objects/prop.obj3d"}` | An instance: the prefab's whole branch, with `children` of its own |
| `{"children": [...]}` | Nesting, on any of the above - a node rides its parent's move, turn and scale |

An entry's `id` is how it is found again, from the editor and from code:

```python
door = scene.map.node_named("front_door")   # by id, at any depth
```

`solid` and `group` on the map itself, and `tint`, are copied onto the map node
when the level is spawned, so the file is the one place they are set. So is
`collision`.

## Loading a map

Three routes reach the same level, and they run in this order during
`Project.scene()`:

| Route | Where it is written | When it runs |
| --- | --- | --- |
| `map` field | `scenes/main.scene` - `"map": "hall"`, or `{"map": "hall"}` | First, before `setup()`, so a script can read the level it is standing in |
| `map_name` | The scene class, as an attribute | Same moment, when the document says nothing |
| `maps` list | `scenes/main.scene` - `"maps": ["keep", {"map": "yard", "pos": [...]}]` | After `setup()`, as placed `Map3D` nodes, one per name |

The first two are **the level**: one map, its own spawn point, swappable. The
`maps` list is the older placement route and stays for a scene that wants two
independent levels side by side; each entry is one `Map3D` node in the tree,
positioned and turned like any other placed thing.

A `Map3D` / `Map2D` node can also be added straight from the node tree, by
`self.spawn(components.Map3D, look={"knobs": {"map": "hall"}})`, or from the
editor's Add Node picker. `map` is the stem; `solid`, `group`, `tint` and
`collision` are its knobs, and a level loaded as the scene's map gets all four
from the file.

Build order matters for a flat scene, which draws in creation order: the
declared map goes down before anything else, so the level is behind every
sprite the scene spawns.

## Swapping a map mid play

```python
scene.load_map("vault")        # build one and put it in
scene.change_map("vault")      # take the old one out first
scene.unload_map()             # leave with no level at all
scene.map                      # the live MapLevel, or None
```

`change_map` and `swap_map` are the same call. What leaves with a map is
everything the map brought: its drawn geometry, its collider, every node in
`nodes` with their children, and every light those nodes filed. What stays is
everything the **scene** spawned itself - the player, a screen, an inventory -
so a second level needs no second script.

Two hooks let a scene re-tune a level the moment it lands:

```python
MAPS = ("hall", "vault")

def map_index(self):
    return MAPS.index(getattr(self.map, "name", MAPS[0]))

def next_map(self):
    self.change_map(MAPS[(self.map_index() + 1) % len(MAPS)])

def on_map_loaded(self, level):
    self.dress.set_level(level)             # read its parts
    start, yaw = self.spawn_point()
    if self.player is not None and start is not None:
        self.player.teleport(start, yaw)    # stand where it says

def on_map_unloaded(self, level):
    if self.dress.level is level:
        self.dress.set_level(None)          # stop dressing a gone level
```

Bind `swap_map` to a key through the project's input map and one trigger is all
a level-change needs: `self.next_map()` from `on_trigger("swap_map")`.

On the **first** load there is nothing to hook: the map is built before
`setup()` runs, so `on_map_loaded` fires early and `self.player` does not exist
yet. Guard a hook with `getattr(self, "dress", None)`, and read the spawn point
in `setup()` as above.

`spawn_point()` follows the live map - `Scene3D` returns its `[x, y, z]` and yaw,
`Scene2D` its world pixels - and falls back to the origin or the middle of
`world_size` when no map is loaded or the file names no start. `on_enter()`
puts the player there every time play mode (re)starts, so a scene that declares
a map never needs its own `spawn_point()` override.

## `MapLevel` - the live level

`engine.level.MapLevel` is what `scene.map` holds.

| Member | Meaning |
| --- | --- |
| `name` / `kind` / `doc` | The stem, `"map3d"` or `"map2d"`, and the document it was built from |
| `node` | The `Map3D` / `Map2D` drawing the geometry |
| `model` | The carved `Model` behind it |
| `roots` | Every node the map placed, at the top of its own branch |
| `live` | Whether it is in the scene right now |
| `build()` / `dispose()` | Put the level in / take it and every node out |
| `spawn_point()` | `((x, y, z), yaw)` as the file says, or `(None, 0.0)` |
| `parts()` / `part_faces(part)` | The part names, and the faces one owns |
| `set_part_texture(part, key)` | Re-dress one part; `None` reverts |
| `node_named(name)` | One placed node by `id` or `tag`, at any depth |

`node_class()` picks `Map2D` when the scene's kind is `"2d"` or `"ui"` and
`Map3D` otherwise, so a flat scene loading a `.map3d` gets a flat drawing of it
rather than a crash. `level.node` is the drawing node itself, and its `mesh` (a
`TriMesh` under `"mesh"`) and `shape_nodes` (the per-part `Collision3D` list
under `"boxes"`) are what the map's own faces stop a body with.

## `mapdoc` - the file

`engine.mapdoc` owns the format; `Project` owns where it lives.

| Function | Meaning |
| --- | --- |
| `blank(name, kind="map3d")` | A fresh document: no geometry, nothing placed, `collision: "mesh"` |
| `load(path, kind=None)` / `save(path, doc)` | Read and write, filling in every field a reader expects; `save` is atomic |
| `kind_of(path)` / `kind_name(kind)` / `ext_of(kind)` | `"map3d"` / `"map2d"` from a path, from any spelling, or to an extension |
| `collision_of(doc, kind=None)` | The `collision` mode settled for the map's kind - `"mesh"` on a `.map2d` becomes `"boxes"` |
| `geometry(doc)` / `model_of(doc)` / `with_model(doc, model)` | The geometry half, on its own; a document's mesh as a `Model`; a document's mesh rewritten from a live one, keeping its nodes |
| `nodes(doc)` / `walk(doc)` | The placed list; every entry, parents before their `children` |
| `parts(doc)` / `part_names(doc)` / `part_faces(doc, name)` | The carved parts and what each owns |
| `spawn_of(doc)` / `set_spawn(doc, pos, yaw)` | Read or write the player start; `set_spawn(doc, None)` clears it |
| `placed(doc, id)` / `parent_of(doc, id)` / `add_placed(doc, entry, parent)` / `remove_placed(doc, id)` | Edit one node in the branch |
| `describe(doc)` | `"map3d 'hall' 12 part(s), 17 node(s)"` |

`scenedoc.walk()` must not be pointed at a map document: a scene reader looks
for `doc["objects"]`, and in a map file that key is the **carved parts**, not
placed nodes. Use `mapdoc.walk()`, which reads `nodes`.

| `Project` method | Meaning |
| --- | --- |
| `map_names()` / `map2d_names()` | The stems in `maps/`, both kinds / flat ones only |
| `map_path(name, kind=None)` | The file, preferring the spelling `kind` means and falling back to a legacy `.model3d` in `maps/` |
| `map_doc(name)` / `save_map_doc(name, doc)` | The document, or `None`; write it under the extension its `kind` means |
| `new_map(name, kind)` | Start an empty document and hand back its path |
| `map(name)` / `map2d(name)` | The carved geometry as a `Model`, cached by path |
| `store_map(model, name=None, doc=None, kind=None)` | Save geometry, keeping the nodes the file already placed |
| `map_scene(name, game)` | A bare scene around one map, which is what the editor's Play map shows |

## In the editor

`maps/` is a folder row in the Project View with a `+` on it, and a Maps row in
the Assets tab's rail with a `New Map...` button under it. `File > New 3D Map...`
and `New 2D Map...`, that Assets button and the `Map` group of the unified New
dialog all write an empty document of the kind picked. A map's card in the Assets
grid is drawn from the file - a stone level in silhouette over `N tris  M parts`,
or the same seen flat over `N parts  M nodes` - so a project with six rooms reads
as six rooms, and the Inspector adds the map's Vertices, Faces, Parts, Nodes and
Spawn rows beneath the picture.

A map opens in the Model tab, where Edit shapes the geometry, Texture paints its
faces, UV Paint lays its atlas and the Objects rail carves and renames its parts;
the `File` band flips a model into a map and back, moving the file between the
folders. `maps/` is a watched folder, so `Ctrl+S` there rebuilds the Scene tab's
preview the way saving a script does. `collision`, `solid`, `group` and `tint`
are knobs of the node, so the Document tab edits them there.

A scene document's root rows carry a **map** row: one pick over
`project.map_names()`, which writes the `map` field the loader obeys at runtime.
The multi-select **maps** row beneath it - 3D kinds only - edits the older
placement list, and writes nothing when every box is clear. Right-clicking a map
in the Project View offers **Play in Scene tab**, which runs
`Project.map_scene()`: the level alone in a bare scene, with no scene script and
no document involved.

Blocks knows maps too. The `scene` drawer offers **load the map**, **swap to the
map** and **take the map out**, whose *map* row opens the same `maps/` pick list
the Document tab uses, and the `events` drawer offers the `on_map_loaded(self,
level)` and `on_map_unloaded(self, level)` hats beside `on_save`. See
[Blocks](blocks.md).

## Starter maps

A new project that ships a world ships it as a map, and its start scene only
declares it:

| Template | Ships | The map holds |
| --- | --- | --- |
| Game 3D | `maps/room.map3d` | A floor and four walls as parts, four `collision3d` nodes and one `omnilight3d`, and a spawn in the near corner |
| Game 2D | `maps/arena.map2d` | A floor and four border bands as parts, four `collision2d` nodes, and a spawn at the bottom of the arena |

Both are `collision: "none"` with `solid: false`, so what a player walks into is
exactly what the map's `nodes` list - the one list the editor can move - and
nothing the mesh happens to touch. The other starters (Fly 3D, Platformer 2D,
Menu, the two Empties) ship no map and build their own geometry, which is still
fully supported.

`templates.make_map(stem)` writes one from the `MAPS` table, `MAPS[stem]` being
`(kind, across, up)` - metres for a room, world pixels for a flat arena - and
`templates.map_for(kind, ships)` is how a starter scene's document learns which
of its own maps to name.
