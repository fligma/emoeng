"""A loaded map: one file's level, built into a scene and swappable."""

from pathlib import Path

from . import components, mapdoc, placement


class MapLevel:
    """One `maps/<name>.map3d` or `.map2d`, built into a live scene.

    A level owns the map node that draws the carved geometry and every
    node the document places. `dispose()` takes both out again, so a
    scene can swap maps mid play and keep everything it spawned itself.
    """

    def __init__(self, scene, name, doc=None):
        self.scene = scene
        self.project = scene.project
        self.name = Path(str(name)).stem
        self.doc = doc if doc is not None else self.project.map_doc(self.name)
        if self.doc is None:
            self.doc = mapdoc.blank(self.name, mapdoc.kind_of(name) or "map3d")
        self.kind = mapdoc.kind_name((self.doc or {}).get("kind") or
                                     mapdoc.kind_of(name))
        self.node = None            # the Map3D / Map2D drawing the parts
        self.model = None           # the carved geometry it drew
        self.roots = []             # every node the document placed
        self.live = False

    # -- building ---------------------------------------------------------
    def node_class(self):
        """The map node a scene of this kind draws with."""
        flat = getattr(self.scene, "kind", "3d") in ("2d", "ui")
        return components.Map2D if flat else components.Map3D

    def build(self):
        """Draw the parts and place the nodes; the scene's own plan stays
        out of it, since a map carries its own overrides."""
        keep, self.scene.plan = self.scene.plan, {}
        try:
            self.node = self._spawn_node()
            self.model = getattr(self.node, "model", None)
            self.roots = self._place_nodes()
        finally:
            self.scene.plan = keep
        self.live = True
        return self

    def _spawn_node(self):
        """One map node, carrying the map's own solidity and tint."""
        knobs = {"map": self.name,
                 "collision": mapdoc.collision_of(self.doc, self.kind)}
        for key in ("solid", "group", "tint"):
            if key in self.doc:
                knobs[key] = self.doc[key]
        return self.scene.spawn(self.node_class(), look={"knobs": knobs})

    def _place_nodes(self):
        """Everything `nodes` names, through the project's one router."""
        items = mapdoc.nodes(self.doc)
        if not items:
            return []
        placer = placement.Placer(self.project)
        return placer.place(self.scene, items,
                            dict(self.doc.get("overrides") or {}))

    # -- what the level knows ---------------------------------------------
    def spawn_point(self):
        """The map's player start as ((x, y, z), yaw), or (None, 0.0)."""
        return mapdoc.spawn_of(self.doc)

    def parts(self):
        """The named parts the geometry is carved into."""
        return [str(o.get("name")) for o in (self.model.objects
                                             if self.model else ())]

    def part_faces(self, part):
        """The face indices one named part owns."""
        if self.model is None:
            return []
        for got in self.model.objects:
            if got.get("name") == str(part):
                return list(got.get("faces") or ())
        return []

    def set_part_texture(self, part, key):
        """Re-dress one named part: floor, walls, arches, ..."""
        if self.node is not None:
            self.node.set_part_texture(part, key)
        return self

    def node_named(self, name):
        """One node the map placed, by its document id or tag."""
        for root in self.roots:
            found = _find(root, name)
            if found is not None:
                return found
        return None

    # -- tearing down -----------------------------------------------------
    def dispose(self):
        """Take the placed nodes and the geometry out of the scene."""
        for root in list(self.roots):
            self.scene.despawn(root)        # a branch leaves with its root
        self.roots = []
        if self.node is not None:
            self.scene.despawn(self.node)   # its collider children go too
            self.node = None
        self.model = None
        self.live = False
        return self

    def __repr__(self):
        return f"<MapLevel {self.kind} '{self.name}' " \
               f"{len(self.roots)} node(s){'' if self.live else ' gone'}>"


def _find(obj, name):
    """A node answering to that name, at any depth under `obj`."""
    want = str(name)
    if getattr(obj, "placed_id", None) == want or \
            getattr(obj, "tag", None) == want:
        return obj
    for child in getattr(obj, "children", ()) or ():
        found = _find(child, want)
        if found is not None:
            return found
    return None
