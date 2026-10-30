"""Placing a document's entries: scenes and maps share one router."""

from . import scenedoc


def walk(items, parent=None, depth=0):
    """Every entry in a list, parents before their nodes."""
    for entry in items or ():
        if not isinstance(entry, dict):
            continue
        yield entry, parent, depth
        for row in walk(entry.get("children"), entry, depth + 1):
            yield row


class Placer:
    """Resolves entries to classes and spawns them, instances included."""

    def __init__(self, project):
        self.project = project

    def place(self, scene, items, plan=None):
        """Spawn each entry, parents first; hand back the root instances."""
        made = {}
        plan = plan if plan is not None else (scene.plan or {})
        roots = []
        for entry, parent_entry, _depth in walk(items):
            parent = made.get(str(parent_entry.get("id"))) \
                if isinstance(parent_entry, dict) else None
            inst = self.one(scene, entry, parent, made,
                            str(entry.get("id")), plan)
            if inst is not None and parent is None:
                roots.append(inst)
        scene.sync_tree()
        return roots

    def one(self, scene, entry, parent, made, this_id, plan=None):
        """Build one placed entry, following an instance to its source."""
        what, how, source = self.entry_build(scene, entry)
        if what is None:
            return None
        how = dict(how)
        how.update((plan or {}).get(this_id) or {})
        pos = how.pop("pos", None)
        if pos is not None and parent is not None:
            pos = parent.child_world(pos)
        inst = scene.spawn(what, pos=pos, parent=parent, look=how)
        inst.placed_id = this_id
        made[this_id] = inst
        if source is not None:
            # names the instance's children so prefab copies never collide
            for child, child_parent, _d in walk(scenedoc.roots(source)):
                if not isinstance(child, dict):
                    continue
                pid = str(child_parent.get("id")) if \
                    isinstance(child_parent, dict) else None
                real_parent = made.get(f"{this_id}/{pid}") if pid else inst
                cid = f"{this_id}/{child.get('id')}"
                self.one(scene, child, real_parent, made, cid, plan)
        return inst

    def entry_build(self, scene, entry):
        """Resolve an entry to (class, look, source_doc_or_None)."""
        base = getattr(scene, "object_base", None)
        if not scenedoc.is_instance(entry):
            target = scenedoc.script_stem(entry.get("script"))
            what = target or self.project.node_class(entry.get("type"), base)
            return what, scenedoc.look(entry), None
        value, is_scene = scenedoc.instance_source(entry)
        path = scenedoc.resolve_instance(self.project, value)
        if path is None:
            return None, {}, None
        src = scenedoc.load(path, "scene" if is_scene else "object")
        if is_scene:
            kind = str(src.get("kind") or "scene3d").lower()
            flat = "2d" if kind in ("scene2d", "sceneui") else "3d"
            what = self.project.node_class("object2d" if flat == "2d"
                                           else "object3d", base)
            return what, scenedoc.look(entry), src
        target = scenedoc.script_stem(src.get("script"))
        what = target or self.project.node_class(src.get("type"), base)
        how = scenedoc.look(src)
        how.update(scenedoc.look(entry))
        return what, how, src
