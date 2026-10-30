"""The Document tab: scene and object files as a form."""

import copy
from pathlib import Path

import pygame

from ..engine import scenedoc, xp
from . import api, widgets

STRIP_H = 22           # the open-document tab row inside the tab
TOOL_H = 26            # the Add / Scene / Save toolbar
NODE_ROW = 18          # one tree row
PROP_ROW = 20          # one property row
HDR_ROW = 17           # one section title row
LABEL_W = 92           # how much of a property row holds its name
TREE_W = 236           # the node column when there is room for one
TRI_W = 13             # the room a fold triangle takes in a tree row

# the mark an instanced node wears, so prefabs read apart
LINK_COLOUR = (150, 120, 210)

# node art comes from `widgets.node_icon`, reading the registry

# the words `kind` and `type` may hold, off the registry
SCENE_KINDS = tuple(scenedoc.SCENE_KINDS)

# the icon a document wears in the tab strip
SCENE_ICONS = {"scene3d": "file-scene-3d", "scene2d": "file-scene-2d",
               "sceneui": "file-scene-ui"}

# look fields that read as number lists
VECTORS = ("pos", "size")
# a row's kind picks its widget: text, num, vec, bool


def fmt(value):
    """A stored value as a person would type it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return " ".join(f"{float(c):g}" for c in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _num(text):
    """One float from a field, or None."""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _vec(text):
    """A list of floats from `1 2 3`, or None."""
    parts = str(text).replace(",", " ").split()
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    return nums or None


def _kind_of(value):
    """Which editor widget one stored value wants."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (list, tuple)):
        return "vec"                         # a typed list stays one list
    if isinstance(value, (int, float)):
        return "num"
    return "text"


def _opt_label(value):
    """The picker's words for a stored enum value."""
    text = str(value)
    if text.startswith("scene"):
        return {"scene3d": "3D scene", "scene2d": "2D scene",
                "sceneui": "UI scene"}.get(text, text)
    row = scenedoc.node_type(text)
    return row[1] if row else text


class _Tab:
    """One open document: its file, edits and pick."""

    def __init__(self, path, kind, doc):
        self.path = Path(path)
        self.kind = kind                 # "scene", "object" or "entity"
        self.doc = doc                   # the JSON dict, in memory
        self.name = self.path.stem
        self.sel = None                  # the picked node's id, None = root
        self.collapsed = set()           # folded node ids
        self.nodes_scroll = 0
        self.props_scroll = 0
        self.dirty = False

    def title(self):
        star = "*" if self.dirty else ""
        return f"{self.name}{star}"


class DocTab:
    """The Document tab's state; the Editor owns one."""

    def __init__(self, app):
        self.app = app
        self.fonts = app.fonts
        self.project = None
        self.tabs = []
        self.active = -1
        # transient interaction state
        self.grip = None                 # (spec, TextField) while typing
        self.popup = None                # {"x","y","items","target","tab"}
        self.popup_rows = []
        self.buttons = []                # toolbar (action, rect) this frame
        self.strip_rects = []            # document-tab rects this frame
        self.strip_close = []            # their close-button rects
        self.node_rows = []              # tree (id, rect) this frame
        self.node_toggles = []           # fold (id, rect) this frame
        self.prop_fields = {}            # editable-row spec -> rect
        self.tree_body = pygame.Rect(0, 0, 0, 0)
        self.props_body = pygame.Rect(0, 0, 0, 0)
        self.drag = None                 # (id, start_pos, moved) while dragging
        self.hover_combo = None
        # an instance row's picture, cached rather than read per redraw
        self._icon_cache = {}

    def set_project(self, project):
        """Forget the open documents when a different project loads."""
        self.project = project
        self.tabs = []
        self.active = -1
        self._icon_cache = {}
        self.grip = self.popup = self.drag = None

    def current(self):
        if 0 <= self.active < len(self.tabs):
            return self.tabs[self.active]
        return None

    def is_open(self, path):
        return any(str(t.path) == str(path) for t in self.tabs)

    def open(self, path):
        """Load a document into a focused tab; True if opened."""
        path = Path(path)
        kind = scenedoc.kind_of(path)
        if kind is None or self.project is None:
            return False
        for i, tab in enumerate(self.tabs):
            if str(tab.path) == str(path):
                self.active = i
                return True
        try:
            doc = scenedoc.load(path, kind)
        except Exception as exc:                 # a broken file opens blank
            self.app.log(f"{path.name}: {exc}", "error")
            if kind == "scene":
                doc = scenedoc.blank_scene(path.stem)
            elif kind == "entity":
                doc = scenedoc.blank_entity(path.stem)
            else:
                doc = scenedoc.blank_object(path.stem)
        self.tabs.append(_Tab(path, kind, doc))
        self.active = len(self.tabs) - 1
        self.grip = self.popup = None
        self.app.log(f"opened {self.app.relative(path)} ({kind})", "muted")
        return True

    def close_current(self):
        """Drop the focused document; the tree re-opens it."""
        if not (0 <= self.active < len(self.tabs)):
            return False
        self.tabs.pop(self.active)
        self.active = min(self.active, len(self.tabs) - 1)
        self.grip = self.popup = None
        return True

    def title_of(self, path):
        for tab in self.tabs:
            if str(tab.path) == str(path):
                return tab.title()
        return Path(path).name

    @property
    def dirty(self):
        return any(tab.dirty for tab in self.tabs)

    def save(self, write=True):
        tab = self.current()
        if tab is None or self.project is None:
            return False
        if not write:
            tab.dirty = False
            return True
        try:
            if tab.kind == "scene":
                self.project.save_scene_doc(tab.name, tab.doc)
            elif tab.kind == "entity":
                # an entity document goes back where it was read from
                self.project.save_entity_doc(tab.name, tab.doc)
            else:
                self.project.save_object_doc(tab.name, tab.doc)
        except Exception as exc:
            self.app.log(f"save {tab.path.name}: {exc}", "error")
            return False
        tab.dirty = False
        self.app.log(f"saved {self.app.relative(tab.path)}", "ok")
        self.app.refresh_tree()
        # a running preview scene rebuilds from the file
        if tab.kind == "scene" and self.app.preview.scene_name == tab.name:
            self.app.preview.pending = tab.name
        return True

    def save_all(self):
        """Write every dirty document; called on tab change."""
        keep = self.active
        for i, tab in enumerate(self.tabs):
            if tab.dirty:
                self.active = i
                self.save()
        self.active = keep
        return keep

    def revert(self):
        """Throw the edits away and re-read the focused document."""
        tab = self.current()
        if tab is None or self.project is None:
            return False
        if not tab.path.is_file():
            self.app.log(f"{tab.path.name} is gone from disk", "warn")
            return False
        tab.doc = scenedoc.load(tab.path, tab.kind)
        tab.sel = None
        tab.collapsed = set()
        tab.dirty = False
        self.grip = self.popup = None
        self.app.log(f"reverted {tab.path.name}", "ok")
        return True

    def _family(self, tab):
        """Which registry half this document is in: 3d or 2d."""
        if tab.kind == "scene":
            return "3d" if str(tab.doc.get("kind")) == "scene3d" else "2d"
        return scenedoc.type_family(tab.doc.get("type"))

    def _node_family(self, entry, fallback):
        t = entry.get("type")
        return scenedoc.type_family(t) if t else fallback

    def _types_for(self, family):
        """One family's createable node types, grouped for the menu."""
        out = []
        for group, items in scenedoc.node_groups():
            keep = [it for it in items
                    if it[4] == family and it[5] is not None]
            if keep:
                out.append((group, keep))
        return out

    def _picker_rows(self, family):
        """The Create Node list for one family's types."""
        rows = []
        for group, items in self._types_for(family):
            for item in items:
                rows.append((("type", item[0]), item[1], group))
        for action, label in self._instance_options(family):
            rows.append((("inst", action[len("inst:"):]), label,
                         "Instantiate"))
        return rows

    def _entry_nodes(self, tab):
        """The visible tree rows: (id, entry, depth, has_children)."""
        if tab.kind != "scene":
            return []
        out = []
        for entry, _parent, depth in scenedoc.walk(tab.doc):
            eid = str(entry.get("id") or "")
            hidden = False
            for cid in tab.collapsed:
                if eid.startswith(cid + "/"):
                    hidden = True
                    break
            if hidden:
                continue
            kids = [c for c in scenedoc.children(entry)
                    if isinstance(c, dict)]
            out.append((eid, entry, depth, bool(kids)))
        return out

    def _selected(self, tab):
        """The picked entry, or None for the document root itself."""
        if tab.sel is None:
            return None
        return scenedoc.placed(tab.doc, tab.sel)

    def _free_id(self, tab, label, parent_id):
        index = 0
        while scenedoc.placed(tab.doc,
                              scenedoc.key(label, index, parent_id)) is not None:
            index += 1
        return scenedoc.key(label, index, parent_id)

    def add_node(self, type_name):
        """File a new node under the pick, or at roots."""
        tab = self.current()
        row = scenedoc.node_type(type_name)
        if tab is None or row is None or tab.kind != "scene":
            return False
        parent = self._selected(tab)
        parent_id = str(parent.get("id")) if parent else None
        label = row[1]
        solid = row[4] == "3d"
        node_id = self._free_id(tab, label, parent_id)
        entry = {"id": node_id, "type": type_name,
                 "pos": [0.0, 0.0, 0.0] if solid else [0.0, 0.0]}
        scenedoc.add_placed(tab.doc, entry, parent)
        tab.sel = node_id
        tab.dirty = True
        self.app.log(f"added {node_id}", "ok")
        return True

    def _instance_options(self, family):
        """The project's own documents, for the Add Node menu."""
        if self.project is None:
            return []
        out = []
        for kind, exts in (("objects", scenedoc.OBJECT_EXTS),
                           ("entities", scenedoc.ENTITY_EXTS),
                           ("scenes", (scenedoc.SCENE_EXT,))):
            for p in self.project.files(kind):
                if p.suffix.lower() not in exts:
                    continue
                if scenedoc.type_family(
                        self._family_of(p)) != family:
                    continue
                out.append((f"inst:{self.project.relative(p)}", p.stem))
        return out

    def _family_of(self, path):
        """'3d' or '2d' for a document path, read once."""
        path = Path(path)
        if path.suffix.lower() == scenedoc.SCENE_EXT:
            kind = str(scenedoc.load(path, "scene").get("kind")
                       or "scene3d").lower()
            return "2d" if kind in ("scene2d", "sceneui") else "3d"
        return scenedoc.type_family(
            str(scenedoc.load(path, "object").get("type") or "").lower())

    def instantiate(self, relpath):
        """Place an existing object/scene file as a child instance."""
        tab = self.current()
        if tab is None or tab.kind != "scene" or self.project is None:
            return False
        path = scenedoc.resolve_instance(self.project, relpath)
        if path is None:
            self.app.log(f"cannot find {relpath}", "warn")
            return False
        is_scene = path.suffix.lower() == scenedoc.SCENE_EXT
        solid = self._family_of(path) == "3d"
        parent = self._selected(tab)
        parent_id = str(parent.get("id")) if parent else None
        label = path.stem
        node_id = self._free_id(tab, label, parent_id)
        field = "scene" if is_scene else "object"
        entry = {"id": node_id,
                 field: scenedoc.instance_field(relpath),
                 "pos": [0.0, 0.0, 0.0] if solid else [0.0, 0.0]}
        scenedoc.add_placed(tab.doc, entry, parent)
        tab.sel = node_id
        # open the branch just grown so the instance shows
        if parent_id:
            tab.collapsed.discard(parent_id)
        tab.dirty = True
        self.app.log(f"instanced {label} as {node_id}", "ok")
        return True

    def remove_node(self):
        """Take the picked node and its branch out."""
        tab = self.current()
        if tab is None or tab.kind != "scene" or tab.sel is None:
            self.app.log("pick a placed node to delete", "warn")
            return False
        gone = str(tab.sel)
        scenedoc.remove_placed(tab.doc, tab.sel)
        self.app.log(f"removed {gone}", "ok")
        tab.sel = None
        tab.collapsed.discard(gone)
        tab.dirty = True
        return True

    def duplicate_node(self):
        """Copy the picked node and branch under a new name."""
        tab = self.current()
        entry = self._selected(tab)
        if tab is None or entry is None:
            return False
        label = str(entry.get("id", "Node")).rsplit("#", 1)[0]
        parent = scenedoc.parent_of(tab.doc, str(entry.get("id")))
        parent_id = str(parent.get("id")) if parent else None
        clone = copy.deepcopy(entry)
        new_id = self._free_id(tab, label, parent_id)
        self._rekey(clone, new_id)
        scenedoc.add_placed(tab.doc, clone, parent)
        tab.sel = new_id
        tab.dirty = True
        self.app.log(f"duplicated to {new_id}", "ok")
        return True

    def _rekey(self, entry, new_id):
        """Give a copied branch its new path-names, parent before children."""
        entry["id"] = new_id
        kids = scenedoc.children(entry)
        for i, child in enumerate(kids):
            if not isinstance(child, dict):
                continue
            old = str(child.get("id") or "")
            tail = old.rsplit("/", 1)[-1] or f"node#{i}"
            self._rekey(child, f"{new_id}/{tail}")

    def reparent(self, node_id, new_parent_id):
        """Move a node under another, or to the roots."""
        tab = self.current()
        if tab is None or tab.kind != "scene" or not node_id:
            return False
        entry = scenedoc.placed(tab.doc, node_id)
        if entry is None or node_id == new_parent_id:
            return False
        if new_parent_id and str(new_parent_id).startswith(f"{node_id}/"):
            self.app.log("cannot move a node inside itself", "warn")
            return False
        scenedoc.remove_placed(tab.doc, node_id)
        # branch names follow the parent, so moves rewrite them
        tail = str(node_id).rsplit("/", 1)[-1]
        new_id = f"{new_parent_id}/{tail}" if new_parent_id else tail
        self._shift_ids(entry, str(node_id), new_id)
        scenedoc.add_placed(tab.doc, entry, new_parent_id)
        tab.sel = new_id
        tab.collapsed.discard(str(node_id))
        tab.dirty = True
        self.app.log(f"reparented {node_id} -> {new_parent_id or 'root'}",
                     "ok")
        return True

    def _shift_ids(self, entry, old_id, new_id):
        """Rename one branch's path-names after a re-parent."""
        got = str(entry.get("id") or "")
        if got.startswith(old_id):
            entry["id"] = new_id + got[len(old_id):]
        for child in scenedoc.children(entry):
            if isinstance(child, dict):
                self._shift_ids(child, old_id, new_id)

    def set_field(self, spec, value):
        """Write a parsed value onto the document or entry."""
        tab = self.current()
        if tab is None:
            return False
        scope, name, index = spec[0], spec[1], spec[2] if len(spec) > 2 \
            else None
        if scope == "doc":
            holder = tab.doc
            self._write(holder, name, index, value)
        elif scope == "knob":
            entry = self._selected(tab) or tab.doc
            knobs = entry.setdefault("knobs", {})
            self._write(knobs, name, index, value)
        else:
            entry = self._selected(tab) or tab.doc
            self._write(entry, name, index, value)
        tab.dirty = True
        return True

    def _write(self, holder, name, index, value):
        """Set a key or one list number, dropping empties."""
        if index is None:
            if value is None or value == "":
                holder.pop(name, None)
            else:
                holder[name] = value
            return
        got = holder.get(name)
        seq = list(got) if isinstance(got, (list, tuple)) else []
        while len(seq) <= index:
            seq.append(0.0)
        seq[index] = value
        holder[name] = seq

    def clear_field(self, spec):
        tab = self.current()
        if tab is None:
            return
        self.set_field(spec, None)

    def _property_rows(self):
        """(label, value_text, spec, kind, options) for the current pick."""
        tab = self.current()
        if tab is None:
            return []
        if tab.kind == "scene" and tab.sel is not None and \
                scenedoc.placed(tab.doc, tab.sel) is None:
            tab.sel = None            # the picked node is gone: edit the root
        rows = []
        if tab.kind == "scene" and tab.sel is None:
            doc = tab.doc
            rows.append(("-", ""))
            rows.append(("kind", str(doc.get("kind") or "scene3d"),
                         ("doc", "kind"), "enum", list(SCENE_KINDS)))
            rows.append(("script", str(doc.get("script") or ""),
                         ("doc", "script"), "text", None))
            rows.append(("map", str(doc.get("map") or "-"),
                         ("doc", "map"), "pick", self._map_options()))
            # one map is the blessed way; the list is for multi-level play
            extra = self._maps_of(doc)
            if extra and str(doc.get("kind") or "scene3d") != "scene2d":
                rows.append(("maps (advanced)", ", ".join(extra),
                             ("doc", "maps"), "maps",
                             self._map_options()))
            rows.append(("placed", str(len(scenedoc.roots(doc))), None))
            ov = doc.get("overrides") or {}
            rows.append(("overrides", str(len(ov)), None))
            return rows
        entry = self._selected(tab) if tab.kind == "scene" else tab.doc
        # an object or entity document edits its own root, not a picked node
        owned = tab.kind in ("object", "entity")
        fam = (self._family(tab) if owned
               else self._node_family(entry or {}, self._family(tab)))
        label = tab.kind if owned else "node"
        rows.append(("-", ""))
        rows.append((label, str(entry.get("id") or entry.get("name")
                                 or tab.name), None))
        tname = entry.get("type")
        rows.append(("type", str(tname or "(script)"),
                     ("entry", "type"), "enum",
                     [it[0] for it in sum(
                         [grp[1] for grp in self._types_for(fam)], [])]))
        rows.append(("script", str(entry.get("script") or ""),
                     ("entry", "script"), "text", None))
        # the transform: the numbers this family takes
        pos = entry.get("pos")
        pos = list(pos) if isinstance(pos, (list, tuple)) else \
            [0.0, 0.0, 0.0][:3 if fam == "3d" else 2]
        axes = "xyz"[:len(pos)] if fam == "3d" else "xy"[:len(pos)]
        for i, ax in enumerate(axes):
            rows.append((f"pos {ax}", fmt(pos[i]),
                         ("entry", "pos", i), "num", None))
        if fam == "3d":
            rows.append(("yaw", fmt(entry.get("yaw")),
                         ("entry", "yaw"), "num", None))
            rows.append(("scale", fmt(entry.get("scale")),
                         ("entry", "scale"), "num", None))
        else:
            rows.append(("rot", fmt(entry.get("rot")),
                         ("entry", "rot"), "num", None))
            size = entry.get("size")
            if isinstance(size, (list, tuple)):
                for i, ax in enumerate("wh"):
                    rows.append((f"size {ax}", fmt(size[i]),
                                 ("entry", "size", i), "num", None))
        # the look it can name: a folder list, or a name of your own
        for field in ("model", "texture"):
            if field in entry:
                rows.append((field, fmt(entry[field]),
                             ("entry", field), "pick",
                             list(api.choices(self.project, field))))
        for field in ("color", "showing"):
            if field in entry:
                rows.append((field, fmt(entry[field]),
                             ("entry", field), "text", None))
        # only knobs the type owns, never another type's
        schema = self._knob_schema(tab, entry, tname)
        for name, kind, default, options in schema:
            value = (entry.get("knobs") or {}).get(name, default)
            rows.append((name, fmt(value), ("knob", name), kind, options))
        return rows

    def _knob_schema(self, tab, entry, tname):
        """[(knob, kind, default, options)] from the node's engine class."""
        out = []
        cls = None
        if tname:
            cls = self.project.node_class(tname) if self.project else None
        if cls is not None:
            defaults = {}
            for name in getattr(cls, "doc_knobs", ()) or ():
                default = getattr(cls, name, None)
                defaults[name] = default
                options = None
                words = api.enum_for(name, cls)
                if words:
                    # what the class itself spells: shape, blend, hitbox_shape
                    options = list(words)
                kind = _kind_of(default) if default is not None else "text"
                if options:
                    kind = "enum"
                out.append((name, kind, default, options))
        for name, value in sorted((entry.get("knobs") or {}).items()):
            if any(name == row[0] for row in out):
                continue
            out.append((name, _kind_of(value), value, None))
        return out

    def _maps_of(self, doc):
        """The scene's map stems, from names or rows."""
        out = []
        for entry in doc.get("maps") or ():
            stem = entry.get("map") if isinstance(entry, dict) else entry
            stem = str(stem or "").strip()
            if stem and stem not in out:
                out.append(stem)
        return out

    def _map_options(self):
        """The project's maps to offer in the `maps` multi-select."""
        if self.project is None:
            return []
        try:
            return list(self.project.map_names())
        except OSError:
            return []

    def _toggle_map(self, doc, stem):
        """Add or drop a map stem in the scene document."""
        got = self._maps_of(doc)
        if stem in got:
            got.remove(stem)
        else:
            got.append(stem)
        if got:
            doc["maps"] = got
        else:
            doc.pop("maps", None)

    def info(self):
        tab = self.current()
        if tab is None:
            return [("document", "none open")]
        rows = [("Document", tab.path.name),
                ("Kind", tab.kind),
                ("Editing", tab.sel or "(root)")]
        if tab.kind == "scene":
            rows.append(("Placed", str(len(scenedoc.roots(tab.doc)))))
        rows.append(("Saved", "no, unsaved edits" if tab.dirty
                     else "yes, matches the file"))
        return rows

    def use_fonts(self, fonts):
        self.fonts = fonts

    def handle_event(self, e):
        if self.popup is not None:
            return self._popup_event(e)
        if self.grip is not None:
            return self._grip_event(e)
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
            return self._rpress(e.pos)
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            return self._press(e.pos)
        if e.type == pygame.MOUSEMOTION and self.drag is not None:
            self.drag = (self.drag[0], self.drag[1], True)
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            return self._release(e.pos)
        if e.type == pygame.MOUSEWHEEL:
            return self._wheel(e)
        if e.type == pygame.KEYDOWN:
            return self._key(e)
        return False

    def _press(self, pos):
        for i, rect in enumerate(self.strip_rects):
            if rect.collidepoint(pos):
                self.active = i
                self.grip = self.popup = None
                return True
        for i, rect in enumerate(self.strip_close):
            if rect.collidepoint(pos):
                self.active = i
                self.close_current()
                return True
        for action, rect in self.buttons:
            if rect.collidepoint(pos):
                return self._toolbar(action, rect)
        # tree toggles fold; node rows pick and arm moves
        for key, rect in self.node_toggles:
            if rect.collidepoint(pos):
                tab = self.current()
                if tab is not None:
                    if key in tab.collapsed:
                        tab.collapsed.discard(key)
                    else:
                        tab.collapsed.add(key)
                return True
        for key, rect in self.node_rows:
            if rect.collidepoint(pos):
                tab = self.current()
                if tab is not None:
                    tab.sel = None if key == "__doc__" else key
                    self.drag = (key, pos, False)
                return True
        for spec, rect in self.prop_fields.items():
            if rect.collidepoint(pos):
                return self._field_press(spec, rect)
        return True

    def _rpress(self, pos):
        """Right-click a tree row: Add Child, Duplicate, Delete."""
        for key, rect in self.node_rows:
            if not rect.collidepoint(pos):
                continue
            tab = self.current()
            if tab is None or tab.kind != "scene":
                return True
            tab.sel = None if key == "__doc__" else key
            items = [("add", "Add Child Node")]
            if key != "__doc__":
                items.append(("duplicate", "Duplicate"))
                items.append(("remove", "Delete"))
            self.popup = {"x": pos[0], "y": pos[1] + NODE_ROW,
                          "items": items, "target": None,
                          "tab": self.active}
            return True
        return False

    def _release(self, pos):
        if self.drag is None:
            return False
        key, _start, moved = self.drag
        self.drag = None
        if not moved or key == "__doc__":
            return True
        target = None
        for node_id, rect in self.node_rows:
            if rect.collidepoint(pos) and node_id != key:
                target = None if node_id == "__doc__" else node_id
                break
        if target is not None or any(
                r.collidepoint(pos) for _k, r in self.node_rows):
            self.reparent(key, target)
        return True

    def _multi_pick(self, hit):
        """One click in the `maps` list toggles a map."""
        tab = self.current()
        if hit is None:
            self.popup = None
            return True
        doc = tab.doc
        if hit == "mclear":
            doc.pop("maps", None)
        elif str(hit).startswith("mmap:"):
            self._toggle_map(doc, str(hit)[5:])
        else:
            self.popup = None
            return True
        tab.dirty = True
        self._reopen_maps()
        return True

    def _reopen_maps(self):
        """Redraw the open `maps` popup with its check marks refreshed."""
        popup = self.popup
        tab = self.current()
        row = self._row_for(popup.get("target"))
        chosen = set(self._maps_of(tab.doc))
        options = list((row[4] if row else None) or [])
        items = [(f"mmap:{stem}",
                  ("[x] " if stem in chosen else "[ ] ") + stem)
                 for stem in options]
        if chosen:
            items.append(("mclear", "(clear all)"))
        popup["items"] = items

    def _field_press(self, spec, rect):
        """Start editing a property: bools flip, enums list."""
        row = self._row_for(spec)
        if row is None:
            return True
        kind = row[3]
        if kind == "bool":
            value = not self._bool_value(spec)
            self.set_field(spec, value)
            return True
        if kind in ("enum", "pick"):
            items = [(opt, _opt_label(opt)) for opt in (row[4] or [])]
            if kind == "pick":
                items.append(("__custom__", widgets.ADD_ROW))
            self.popup = {"x": rect.x, "y": rect.bottom,
                          "items": items,
                          "target": spec, "tab": self.active}
            return True
        if kind == "maps":
            chosen = set(self._maps_of(self.current().doc))
            options = list(row[4] or [])
            items = [(f"mmap:{stem}",
                      ("[x] " if stem in chosen else "[ ] ") + stem)
                     for stem in options]
            if chosen:
                items.append(("mclear", "(clear all)"))
            self.popup = {"x": rect.x, "y": rect.bottom, "items": items,
                          "target": spec, "tab": self.active, "multi": True}
            return True
        text = row[1]
        self.grip = (spec, widgets.TextField(text, 256))
        return True

    def _grip_event(self, e):
        spec, field = self.grip
        if e.type == pygame.KEYDOWN:
            result = field.handle(e)
            if result == "submit":
                self._commit(spec, field.text)
                self.grip = None
            elif e.key == pygame.K_ESCAPE:
                self.grip = None
            return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            rect = self.prop_fields.get(spec)
            if rect is None or not rect.collidepoint(e.pos):
                self._commit(spec, field.text)
                self.grip = None
            return True
        return False

    def _commit(self, spec, text):
        """Parse a typed value as its field's type, then write."""
        row = self._row_for(spec)
        kind = row[3] if row else "text"
        text = str(text).strip()
        if text == "":
            self.set_field(spec, None)
            return True
        if kind == "num":
            value = _num(text)
            if value is None:
                self.app.log(f"'{text}' is not a number", "warn")
                return True
        elif kind == "vec":
            value = _vec(text)
            if value is None:
                self.app.log(f"'{text}' is not a list of numbers", "warn")
                return True
        else:
            value = text
        self.set_field(spec, value)
        return True

    def _bool_value(self, spec):
        tab = self.current()
        if tab is None:
            return False
        entry = self._selected(tab) or tab.doc
        if spec[0] == "knob":
            return bool((entry.get("knobs") or {}).get(spec[1]))
        return bool(entry.get(spec[1]))

    def _row_for(self, spec):
        for row in self._property_rows():
            if len(row) > 2 and row[2] == spec:
                return row
        return None

    def _wheel(self, e):
        tab = self.current()
        if tab is None:
            return False
        mouse = pygame.mouse.get_pos()
        if self.tree_body.collidepoint(mouse):
            tab.nodes_scroll = max(0, tab.nodes_scroll - e.y * 3)
            return True
        if self.props_body.collidepoint(mouse):
            tab.props_scroll = max(0, tab.props_scroll - e.y * 3)
            return True
        return False

    def _key(self, e):
        if e.key == pygame.K_DELETE:
            return self.remove_node()
        return False

    def _popup_event(self, e):
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.popup = None
            return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            hit = None
            for label, rect in self.popup_rows:
                if rect.collidepoint(e.pos):
                    hit = label
                    break
            if self.popup.get("multi"):
                return self._multi_pick(hit)
            target = self.popup.get("target")
            self.popup = None
            if hit is not None:
                if hit == "__custom__" and target is not None:
                    # not a name: give the row its keyboard back
                    self.grip = (target, widgets.TextField("", 256))
                    return True
                if target is not None:
                    self.set_field(target, hit)
                else:
                    self._toolbar(hit, None)
            return True
        if e.type == pygame.MOUSEBUTTONDOWN:
            self.popup = None
        return True

    def _toolbar(self, action, rect):
        """One toolbar button: `add:<type>`, a verb, or a menu."""
        if action == "close":
            return self.close_current()
        if action == "save":
            return self.save()
        if action == "revert":
            return self.revert()
        if action == "add":
            # one searchable grouped list, filtered to this document's family
            tab = self.current()
            fam = self._family(tab) if tab else "3d"
            self.app.open_node_picker(self._picker_rows(fam), "doc")
            return True
        if action == "remove":
            return self.remove_node()
        if action == "duplicate":
            return self.duplicate_node()
        if action == "scene":
            tab = self.current()
            self.popup = {"x": rect.x if rect else 8,
                          "y": (rect.bottom if rect else TOOL_H),
                          "items": [("scene:arm", "Arm in Scene tab"),
                                    ("scene:play", "Preview this scene"),
                                    ("scene:start", "Set as start scene"),
                                    ("scene:raw", "View raw JSON")],
                          "target": None, "tab": self.active}
            return True
        if str(action).startswith("add:"):
            return self.add_node(str(action)[4:])
        if str(action).startswith("inst:"):
            return self.instantiate(str(action)[5:])
        return self._scene_action(action)

    def _scene_action(self, action):
        tab = self.current()
        app = self.app
        if tab is None or not str(action).startswith("scene:"):
            return False
        verb = str(action)[6:]
        if verb == "raw":
            return self.app.open_raw(tab.path)
        if tab.kind != "scene":
            return False
        name = tab.name
        if verb == "arm":
            app.preview.arm(name)
            app.log(f"armed scene {name}", "ok")
        elif verb == "play":
            app.preview.play(name)
            app.log(f"previewing scene {name}", "ok")
        elif verb == "start" and app.project is not None:
            app.project.start = name
            app.project.save_meta()
            app.refresh_tree()
            app.log(f"start scene is now {name}", "ok")
        return True

    def draw(self, surface, area, dt):
        self.buttons = []
        self.strip_rects = []
        self.strip_close = []
        self.node_rows = []
        self.node_toggles = []
        self.prop_fields = {}
        surface.fill(xp.FACE, area)
        if self.current() is None:
            self._draw_empty(surface, area)
            return
        tab = self.current()
        strip = pygame.Rect(area.x, area.y, area.width, STRIP_H)
        self._draw_strip(surface, strip)
        bar = pygame.Rect(area.x, strip.bottom, area.width, TOOL_H)
        self._draw_toolbar(surface, bar, tab)
        body = pygame.Rect(area.x, bar.bottom, area.width,
                           max(0, area.bottom - bar.bottom))
        show_tree = body.width > 360 and tab.kind == "scene"
        tree_w = TREE_W if show_tree else 0
        tree = pygame.Rect(body.x + 3, body.y + 3, tree_w,
                           body.height - 6)
        props = pygame.Rect(tree.right + (4 if show_tree else 3), body.y + 3,
                            max(120, body.right - tree.right - 6),
                            body.height - 6)
        if show_tree:
            self._draw_tree(surface, tree, tab)
        self._draw_props(surface, props, tab)
        if self.popup is not None:
            self._draw_popup(surface)

    def _draw_empty(self, surface, area):
        img = widgets.cached_text(self.fonts["small"],
                                  "open a .scene or .obj3d/.obj2d file",
                                  xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (area.x + 12, area.y + 12))

    def _draw_strip(self, surface, strip):
        """The open-document tab row."""
        surface.fill(xp.FACE, strip)
        pygame.draw.line(surface, xp.SHADOW, (strip.x, strip.bottom - 1),
                         (strip.right, strip.bottom - 1))
        small = self.fonts["small"]
        mouse = pygame.mouse.get_pos()
        x = strip.x + 4
        for i, tab in enumerate(self.tabs):
            label = widgets.elide(small, tab.title(), 132)
            w = small.size(label)[0] + 26
            rect = pygame.Rect(x, strip.y + 3, w, strip.height - 3)
            self.strip_rects.append(rect)
            bg = xp.FIELD_ALT if i == self.active else xp.FACE
            surface.fill(bg, rect)
            edge = xp.SELECTION if i == self.active else xp.OUTLINE
            pygame.draw.rect(surface, edge, rect, 1, border_radius=2)
            if rect.collidepoint(mouse) and i != self.active:
                surface.fill(xp.BTN_HOVER_BG, rect)
            art = None
            if tab.kind == "scene":
                art = SCENE_ICONS.get(str(tab.doc.get("kind")))
            else:
                art = widgets.node_icon(tab.doc.get("type"))
            tx = rect.x + 4
            img = widgets.icon(art, 12) if art else None
            if img is not None:
                surface.blit(img, (tx, rect.centery - img.get_height() // 2))
                tx += img.get_width() + 4
            text = widgets.cached_text(small, label, xp.TEXT)
            if text is not None:
                surface.blit(text, (tx, rect.centery - text.get_height() // 2))
            close = pygame.Rect(rect.right - 16, rect.y + 3, 13, 13)
            self.strip_close.append(close)
            if tab.dirty:
                pygame.draw.rect(surface, xp.DK_SHADOW, close, 1)
                pygame.draw.line(surface, xp.TEXT, (close.x + 3, close.y + 3),
                                 (close.right - 4, close.bottom - 4))
                pygame.draw.line(surface, xp.TEXT, (close.right - 4, close.y + 3),
                                 (close.x + 3, close.bottom - 4))
            x = rect.right + 3

    def _draw_toolbar(self, surface, bar, tab):
        surface.fill(xp.MODEL_ROW_BG, bar)
        pygame.draw.line(surface, xp.HILITE, (bar.x, bar.y),
                         (bar.right, bar.y))
        pygame.draw.line(surface, xp.SHADOW, (bar.x, bar.bottom - 1),
                         (bar.right, bar.bottom - 1))
        small = self.fonts["small"]
        mouse = pygame.mouse.get_pos()
        x = bar.x + 4

        def add(label, action, enabled=True):
            nonlocal x
            if not label:
                x += 8
                return
            r = pygame.Rect(x, bar.y + 3, small.size(label)[0] + 16,
                            bar.height - 7)
            xp.button(surface, r, label, small, hovered=r.collidepoint(mouse),
                      enabled=enabled)
            self.buttons.append((action, r))
            x = r.right + 3

        if tab.kind == "scene":
            add("Scene v", "scene")
            add("+ Add Node", "add")
            add("Duplicate", "duplicate", tab.sel is not None)
            add("Remove", "remove", tab.sel is not None)
        add(None, None)
        add("Revert", "revert")
        add("Save" if tab.dirty else "Saved", "save", tab.dirty)
        hint = ("click a value to edit it, drag a node onto another to "
                "re-parent it")
        img = widgets.cached_text(small, hint, xp.TEXT_MUTED)
        if img is not None and x + 12 + img.get_width() < bar.right:
            surface.blit(img, (bar.right - 8 - img.get_width(),
                               bar.centery - img.get_height() // 2))

    def _draw_tree(self, surface, rect, tab):
        head = pygame.Rect(rect.x, rect.y, rect.width, 20)
        count = str(len(scenedoc.roots(tab.doc)))
        widgets.header(surface, head, "Tree", self.fonts["small"],
                       right=count)
        # the header's plus adds at root or under the pick
        cw = self.fonts["small"].size(count)[0]
        plus = pygame.Rect(head.right - cw - 36, head.y + 3, 16,
                           head.height - 6)
        if plus.collidepoint(pygame.mouse.get_pos()):
            pygame.draw.rect(surface, xp.BTN_HOVER_BG, plus)
        pygame.draw.line(surface, xp.TEXT, (plus.centerx - 4, plus.centery),
                         (plus.centerx + 4, plus.centery))
        pygame.draw.line(surface, xp.TEXT, (plus.centerx, plus.centery - 4),
                         (plus.centerx, plus.centery + 4))
        self.buttons.append(("add", plus))
        body = pygame.Rect(rect.x, head.bottom + 2, rect.width,
                           max(20, rect.height - head.height - 4))
        pygame.draw.rect(surface, xp.FIELD, body)
        xp.sunken(surface, body)
        self.tree_body = body
        rows = [("__doc__", None, 0, True)] + self._entry_nodes(tab)
        max_scroll = max(0, len(rows) * NODE_ROW + 4 - body.height)
        tab.nodes_scroll = max(0, min(tab.nodes_scroll, max_scroll))
        old = widgets.clip(surface, body.inflate(-1, -1))
        if old is None:
            return
        mouse = pygame.mouse.get_pos()
        y = body.y + 2 - tab.nodes_scroll
        for key, entry, depth, kids in rows:
            row = pygame.Rect(body.x + 3, y, body.width - 16, NODE_ROW)
            if row.bottom > body.y and row.y < body.bottom:
                picked = (tab.sel is None and entry is None) or \
                    (entry is not None and str(entry.get("id")) == tab.sel)
                if picked:
                    surface.fill(xp.SELECTION, row)
                elif row.collidepoint(mouse):
                    surface.fill(xp.BTN_HOVER_BG, row)
                self._draw_node_row(surface, row, key, entry, depth, kids)
            self.node_rows.append((key, row))
            y += NODE_ROW
        surface.set_clip(old)

    def _instance_icon(self, entry):
        """The referenced document's own picture, read once and cached."""
        value, is_scene = scenedoc.instance_source(entry)
        if value is None:
            return None
        got = self._icon_cache.get(value)
        if got is not None:
            return got or None
        art = None
        path = scenedoc.resolve_instance(self.project, value)
        if path is not None:
            if is_scene:
                kind = str(scenedoc.load(path, "scene").get("kind")
                           or "scene3d").lower()
                art = SCENE_ICONS.get(kind)
            else:
                doc = scenedoc.load(path, "object")
                art = widgets.node_icon(doc.get("type"))
        self._icon_cache[value] = art or ""
        return art

    def _draw_node_row(self, surface, row, key, entry, depth, kids):
        small = self.fonts["small"]
        tx = row.x + 3 + depth * 10
        label = "(scene)" if entry is None else \
            str(entry.get("id") or entry.get("name") or "").rsplit("/", 1)[-1]
        if kids:
            tri = pygame.Rect(tx, row.y + 3, TRI_W - 3, NODE_ROW - 6)
            open_ = key not in (self.current().collapsed if entry else set())
            mid = (tri.centerx, tri.centery)
            pts = ([(mid[0] - 3, mid[1] - 2), (mid[0] + 3, mid[1] - 2),
                    (mid[0], mid[1] + 2)] if open_ else
                   [(mid[0] - 2, mid[1] - 3), (mid[0] + 2, mid[1]),
                    (mid[0] - 2, mid[1] + 3)])
            pygame.draw.polygon(surface, xp.TEXT, pts)
            if entry is not None:
                self.node_toggles.append((key, pygame.Rect(
                    tx, row.y, TRI_W, NODE_ROW)))
            tx += TRI_W
        art = None
        instance = entry is not None and scenedoc.is_instance(entry)
        if entry is not None:
            art = self._instance_icon(entry) if instance else \
                widgets.node_icon(entry.get("type"))
        drew = bool(art) and widgets.draw_icon(
            surface, art, pygame.Rect(tx, row.y + 2, 13, 13))
        tx += 15 if drew else 2
        if instance:
            mark = pygame.Rect(tx, row.centery - 3, 6, 6)
            pygame.draw.rect(surface, LINK_COLOUR, mark, border_radius=2)
            pygame.draw.rect(surface, xp.OUTLINE, mark, 1, border_radius=2)
            tx += 9
        picked = (self.current().sel is None and entry is None) or \
            (entry is not None and str(entry.get("id")) == self.current().sel)
        colour = (255, 255, 255) if picked else xp.TEXT
        text = widgets.cached_text(small, widgets.elide(
            small, label, row.right - tx - 4), colour)
        if text is not None:
            surface.blit(text, (tx, row.centery - text.get_height() // 2))

    def _draw_props(self, surface, rect, tab):
        head = pygame.Rect(rect.x, rect.y, rect.width, 20)
        right = tab.sel or ("object" if tab.kind == "object" else "scene")
        widgets.header(surface, head, "Properties", self.fonts["small"],
                       right=widgets.elide(self.fonts["small"], right,
                                           rect.width - 90))
        body = pygame.Rect(rect.x, head.bottom + 2, rect.width,
                           max(20, rect.height - head.height - 4))
        pygame.draw.rect(surface, xp.FIELD_ALT, body)
        xp.sunken(surface, body)
        self.props_body = body
        rows = self._property_rows()
        y = body.y + 3 - tab.props_scroll
        old = widgets.clip(surface, body.inflate(-1, -1))
        if old is None:
            return
        small = self.fonts["small"]
        mouse = pygame.mouse.get_pos()
        for row in rows:
            label = row[0]
            if label == "-":
                y += 2
                pygame.draw.line(surface, xp.SHADOW, (body.x + 4, y),
                                 (body.right - 4, y))
                y += 6
                continue
            if y + PROP_ROW > body.bottom:
                break
            if y + PROP_ROW > body.y:
                self._draw_prop(surface, body, label, row, y, small, mouse)
            y += PROP_ROW
        surface.set_clip(old)

    def _draw_prop(self, surface, body, label, row, y, small, mouse):
        prow = pygame.Rect(body.x + 4, y, body.width - 8, PROP_ROW)
        img = widgets.cached_text(small, label, xp.TEXT_MUTED)
        if img is not None:
            surface.blit(img, (prow.x, prow.centery - img.get_height() // 2))
        field = pygame.Rect(prow.x + LABEL_W, prow.y + 1,
                            max(20, prow.width - LABEL_W), PROP_ROW - 4)
        kind = row[3] if len(row) > 3 else None
        value = row[1]
        if kind is None:                        # a static read-out
            text = widgets.cached_text(small, widgets.elide(
                small, value, field.width - 6), xp.TEXT)
            if text is not None:
                surface.blit(text, (field.x + 3,
                                    field.centery - text.get_height() // 2))
            return
        self.prop_fields[row[2]] = field
        if kind == "enum":
            xp.combo(surface, field, value, small,
                     hovered=field.collidepoint(mouse))
            return
        if self.grip is not None and self.grip[0] == row[2]:
            self.grip[1].draw(surface, field, small)
            return
        xp.field(surface, field)
        text = widgets.cached_text(small, widgets.elide(
            small, value, field.width - 6), xp.TEXT)
        if text is not None:
            surface.blit(text, (field.x + 3,
                                field.centery - text.get_height() // 2))

    def _draw_popup(self, surface):
        """The list under a field: it fits the window, and flips up."""
        small = self.fonts["small"]
        items = list(self.popup["items"])
        step = small.get_height() + 8
        room = max(2, (surface.get_height() - 16) // step - 1)
        if len(items) > room:
            # the window is the limit: the tail waits for a taller page
            items = items[:room] + [(None, f"+{len(items) - room} more")]
        tall = 4 + sum(6 if not label else step for _action, label in items)
        wide = 180
        # the panel is a guest: keep it in the window
        x = max(0, min(self.popup["x"], surface.get_width() - wide - 6))
        y = self.popup["y"]
        if y + tall > surface.get_height() - 4:
            # a field low on the page opens its list upwards instead
            field = self.prop_fields.get(self.popup.get("target"))
            above = (field.top if field is not None else y) - tall - 2
            y = max(2, above)
        panel, rects = xp.menu_items(surface, (x, y),
                                     [(label or "-", bool(label))
                                      for _action, label in items],
                                     small, width=wide)
        self.popup_rows = [(action, rect)
                           for (action, _label), rect in zip(items, rects)
                           if rect is not None and action is not None]
