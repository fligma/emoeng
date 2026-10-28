# Collision

`engine.collision` is a set of pure functions, not a physics system. Nothing in
the game loop calls them by itself: the engine moves the camera, and a scene
only blocks a body once something has been filed as solid. Every box shape is
axis-aligned - a box is `(centre, half-size)` - because rooms, crates and slabs
already are. A triangle-mesh collider is the one exception: it stores the real
triangles and sweeps a body against them, which is what a `.map3d` file builds
out of its own outline.

```python
from emoeng.engine import collision
boxes = [collision.aabb((0, 1, 0), (2, 1, 2))]     # ((cx,cy,cz), (hx,hy,hz))
```

There are two layers here. These functions are the maths, and the
`Collision3D` / `Hitbox3D` / `Collision2D` / `Hitbox2D` / `Map3D` nodes of
`engine.components` are the data: a node files itself in `scene.colliders` when
it is built, and a mover's sweep reads that list. A shape placed in the editor
is therefore a shape the game honours with no code written about it. See
[Objects](objects.md) for the nodes themselves; the rest of this page is the
maths.

| Name | Meaning |
| --- | --- |
| `centre` | The box's middle, world units |
| `half` | Half extents on X, Y and Z - a `2x2x2` cube has `half=(1,1,1)` |
| `GRAZE` | `1e-4` - the slack that stops a face sliding parallel to movement catching |

## Function table

| Function | Signature | Returns |
| --- | --- | --- |
| `aabb` | `aabb(centre, half)` | The box, cast to floats |
| `expand` | `expand(box, amount)` | The same box grown on every axis (negative shrinks) |
| `contains_point` | `contains_point(box, point)` | `bool` |
| `overlap` | `overlap(a, b)` | `bool` - do two boxes intersect |
| `ray_aabb` | `ray_aabb(origin, direction, box)` | Entry distance along a **unit** ray, or `None` |
| `ray_plane` | `ray_plane(origin, direction, point, normal)` | Distance to an infinite plane, or `None` |
| `ray_sphere` | `ray_sphere(origin, direction, centre, radius)` | Distance to the near surface, or `None` |
| `move_slide` | `move_slide(pos, delta, boxes, half=(0.35, 0.9, 0.35))` | `(new_pos, (hit_x, hit_y, hit_z))` |
| `move_slide_mesh` | `move_slide_mesh(pos, delta, boxes, meshes, half=(0.35, 0.9, 0.35))` | The same sweep with `TriMesh` colliders added: stops at a wall triangle, walks up a ramp. `(new_pos, hits)` |
| `sphere_push` | `sphere_push(pos, radius, boxes)` | A depenetrated position list |
| `ground_clamp` | `ground_clamp(pos, height_fn, eye_height)` | `[x, height_fn(x, z) + eye_height, z]` |

The ray functions assume `direction` is normalised - `camera.forward()` and the
vectors from `Camera.ray()` already are.

## `move_slide` - walking through a level

Each axis is swept separately, so a body heading into a wall slides along it
instead of sticking. The body stops at the nearest collider face its path
crosses; it never snaps to the far side of a box it touched. A body already
inside a box can walk back out.

`Scene.move_body()` is this function with the scene's filed shapes already
gathered, which is what a `Player3D` calls; write your own only to add gravity,
a step-up or a knock on a wall. When the scene also holds triangle-mesh
colliders - a placed `.map3d` files one - `move_body` calls
`move_slide_mesh` instead, and the boxes and the triangles sweep together.
Nothing else changes: the same `(new_pos, hits)` answer, the same `group`
filter, the same `half` body.

```python
class Walker(fe.Player3D):
    def apply_move(self, dt):
        super().apply_move(dt)          # sweeps through scene.colliders
        self.on_wall = any(self.hits)   # (hit_x, hit_y, hit_z) from the sweep
```

```python
class Roller(fe.Object3D):
    """Something that is not a player, so it does the sweep itself."""

    def update(self, dt):
        super().update(dt)
        boxes = self.scene.collider_boxes(group=self.tag)
        self.pos, self.hits = collision.move_slide(self.pos, self.delta,
                                                  boxes, self.body_half)
```

`half` defaults to a human-sized body, `(0.35, 0.9, 0.35)`. Pass your own for
something smaller or taller; it is also the argument to widen a body at the
cost of a little clipping.

## Triangle meshes - `TriMesh` and a placed `.map3d`

A box is a poor wall when the wall is a room: a level of `Collision3D`
slabs means arranging a shape per face and matching each to the picture.
A `TriMesh` is the alternative: the real triangles, hashed once.

```python
md = model.meshdata(pos, yaw, scale)          # world-space corners
pts = md.pos
tris = [pts[i:i + 3] for i in range(0, len(pts) - 2, 3)]
mesh = collision.TriMesh(tris, cell=4.0)
pos, hits = collision.move_slide_mesh(pos, delta, boxes, [mesh], half)
```

| Member | Notes |
| --- | --- |
| `TriMesh(tris, cell=4.0)` | `tris` is three consecutive world-space corners per face, read straight off a `MeshData.pos`. One uniform grid buckets them by cell, built once when the map is placed, not per frame |
| `tris_near(box)` | The triangles a `(centre, half)` body could touch - the cells its footprint spans |
| `contains(point)` | Even-odd ray parity over the hashed triangles: is a world point inside the shell |
| `bounds` | `(min, max)` corners of the whole mesh, or `None` when empty - what a `box()` for a broadphase is built from |

`move_slide_mesh(pos, delta, boxes, meshes, half)` keeps `move_slide`'s
per-axis order - X, then Z, then Y - and answers the same `(pos, hits)`.
For each axis it gathers the triangles near the body's path and stops at the
nearest one that overlaps, using the standard AABB-triangle separating-axis
set: the triangle's own normal, the three slab axes and the edge-cross
normals. Grazing faces slide on, exactly as a box face does.

Step-up is the reason a ramp is walkable. When a horizontal axis is blocked
by a triangle whose normal tilts up (`n.y >= 0.35`), that face is treated as
walkable: the body is lifted onto it and the Y pass settles it, so a sloped
floor raises the walker instead of the slope head-butting them. Faces that
steep are skipped when blocking a horizontal move - you do not bump into a
ramp - and every other triangle still stops you dead.

A `Map3D` node owns one of these. `build()` draws `project.map(stem)` and
files a `TriMesh` over exactly the triangles that were drawn, transformed
by the node's `pos`/`yaw`/`scale`; `dispose()` takes the filing off, and
moving the node rebuilds it. The node is itself the collider: `solid`,
`group`, `box()` (the mesh's overall AABB) and `contains(point)` all answer
through it, so `Player3D` and every script mover that calls `move_body` keep
working untouched - no `Collision3D` arranged anywhere.

What stays box-shaped, on purpose: `sphere_push`, every 2D rect, the
collider broadphase and a trigger's `contains()` still read the overall
`box()`. Only the `move_body` sweep is per-triangle.

## Jumping, gravity and floors

The engine does not integrate gravity. Two lines in `update()` are enough, and
`hits[1]` is what tells you the floor stopped you.

```python
def update(self, dt):
    super().update(dt)
    self.vy -= 22.0 * dt
    pos, hits = collision.move_slide(self.pos,
                                     [0.0, self.vy * dt, 0.0], self.boxes)
    self.pos = pos
    if hits[1]:
        self.vy = 0.0
        self.grounded = True
    else:
        self.grounded = False
    if self.grounded and self.input.pressed("jump"):
        self.vy = 8.5
```

`jump` is not one of the engine's actions, so the scene names it:
`actions = {"jump": ["space"]}` - see
[Player and Input](player-and-input.md).

## Spheres - a ball, a marble, an orb

`sphere_push` is cheap depenetration against boxes: it finds the closest point
on each box and pushes the sphere out along that vector. A sphere exactly
inside a box is lifted onto its top face rather than dividing by zero.

```python
def update(self, dt):
    super().update(dt)
    self.vel = [self.vel[0] * 0.98, self.vel[1] - 18.0 * dt,
                self.vel[2] * 0.98]
    self.pos = collision.sphere_push([c + v * dt for c, v in zip(self.pos,
                                                                self.vel)],
                                     self.radius,
                                     self.scene.collider_boxes())
```

## Terrain - `ground_clamp`

For heightmap ground with nothing solid in it, `ground_clamp()` keeps a walking
body on the surface, given any `height_fn(x, z)` - typically the scene's own.

```python
def update(self, dt):
    super().update(dt)
    self.pos = collision.ground_clamp(self.pos, self.scene.ground_height,
                                     self.eye_height)
```

## Raycasting - picking, line of sight, pinging

`Camera.ray(size, pos)` turns a screen pixel into `(origin, unit direction)`;
the rays then measure the distance.

```python
def handle_event(self, e):
    if e.button == 1 and e.type == pygame.MOUSEBUTTONDOWN:
        origin, direction = self.view.ray(self.game.screen.get_size(), e.pos)
        best, hit = None, None
        for name, box in self.targets.items():
            t = collision.ray_aabb(origin, direction, box)
            if t is not None and (best is None or t < best):
                best, hit = t, name
        if hit:
            self.message = f"clicked {hit} at {best:.1f} m"
```

| Need | Use |
| --- | --- |
| Anything under the cursor | `ray_aabb` per candidate, keep the shortest |
| Where a click lands on a plane | `camera.plane_hit(size, pos, point, normal)` or `ray_plane` |
| Is the player visible from here | `ray_aabb` at the target's centre; a hit closer than the distance means blocked |
| A round trigger volume | `ray_sphere`, or `overlap(expand(box, r), body)` |
| A body's own hit box | `collision.aabb(obj.pos, half)` with `half` from the model |

A world-to-screen marker needs no ray at all:

```python
def overlay(self, screen):
    point = self.view.project(self.gem.pos, self.game.screen.get_size())
    if point is not None:                    # None means behind the camera
        x, y, depth = point
        fe.ui.bar(screen, (x - 20, y - 30, 40, 4), 1.0 - depth / 60.0)
```

## Building the box list

Colliders are data you place. Four ordinary ways to get them:

| Source | How |
| --- | --- |
| The scene's filed nodes | `scene.collider_boxes(group="", solid=True)` for 3D, `collider_rects(...)` for 2D - what every `Collision3D` in the documents adds up to |
| A placed `.map3d` | `scene.colliders` holds a `Map3D` whose `mesh` is a `TriMesh`; `move_body` picks it up itself, and `mesh.bounds` gives the box around the whole map |
| Authored in the scene | A plain list of `(centre, half)` pairs, converted with `aabb()` |
| From a `.model3d` file | `m.bounds()` gives `(min, max)` corners - or `None` for an empty model; `m.centre()` gives the middle |
| From generated geometry | `MeshData.bounds()` returns the same `(min, max)` pair |

```python
def boxes_from_models(self):
    """A shape for each model you want solid, sized from its own bounds."""
    out = []
    for name, pos, yaw in self.solid_placements:
        bounds = self.models[name].bounds()
        if bounds is None:
            continue                       # empty model, nothing to hit
        lo, hi = bounds
        half = tuple((hi[i] - lo[i]) / 2.0 * self.model_scale for i in range(3))
        centre = (pos[0] + (lo[0] + hi[0]) / 2.0 * self.model_scale,
                  pos[1] + (lo[1] + hi[1]) / 2.0 * self.model_scale,
                  pos[2] + (lo[2] + hi[2]) / 2.0 * self.model_scale)
        out.append(collision.aabb(centre, half))
    return out
```

The `group` on a shape is how one wall can be solid to the player and open to a
ghost: `colliders_of(group)` returns the shapes with no group (they stop
everybody) plus the ones naming that group, and a mover passes its own
`collide_group` - which a `Player3D` names `"player"`.

Axis-aligned means no rotated *boxes*: a rotated prop gets a box around its
unrotated extent, which is usually what a level wants. A `TriMesh` is the way
to keep an angled surface honest - a ramp, a stair, a slanted roof - because
its triangles already sit wherever the map drew them.

## What is *not* here

| Absent | Because |
| --- | --- |
| Rigid bodies, joints, torque | Movement is `pos += delta` and a slide |
| Broadphase over boxes | Box levels are small enough to loop over every one; only a `TriMesh` hashes its cells, because a map's triangle count is not a wall count |
| Continuous collision beyond one axis at a time | A `dt` step is far smaller than a wall |
| Automatic colliders on spawned objects | A `Model3D` draws; the space a thing takes up is a `Collision3D` you place beside it. A `Map3D` is the one node that collides by itself - that is what a map file is for |
| A solver for stacked or resting bodies | Nothing falls; a `Hitbox3D` reports and a mover sweeps |
| Mesh collision in 2D | `move_body2d`, `sphere_push` and every rect test stay against a collider's overall `box()` |

Related pages: [Objects](objects.md) for the nodes and the tree, [Scenes](scenes.md)
for the sweep methods on a scene, [Camera and Rendering](camera-and-rendering.md),
[Animation and Timing](animation-and-timing.md).
