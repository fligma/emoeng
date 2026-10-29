"""One project's named inputs: actions to poll, triggers to broadcast."""

from . import config
from . import input as inputmod

# an action is polled every frame; a trigger's press is an event of its own
ACTION = "action"
TRIGGER = "trigger"

# the manifest section both tables live in
SECTION = "input"


def clean_keys(value):
    """One binding cell: `"w"`, `"w, up"`, `["w"]` into a tidy list."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [v.strip() for v in value.replace(";", ",").split(",")]
    else:
        try:
            parts = [str(v).strip() for v in value]
        except TypeError:
            parts = [str(value)]
    return [v.lower() for v in parts if v and not str(v).startswith("_")]


def _table(mapping):
    """`{name: keys}`, notes dropped, names kept in file order."""
    out = {}
    for name, values in (mapping or {}).items():
        text = str(name).strip()
        if not text or text.startswith("_"):
            continue
        out[text] = clean_keys(values)
    return out


def config_table():
    """The user's keymap as `{action: keys}`, read off the config schema."""
    cfg = config.load()
    out = {}
    for key in config.keys("input"):
        out[key.split(".", 1)[1]] = clean_keys(cfg.get(key))
    return out


def engine_table():
    """The engine's own keymap, before a player's config is laid over it."""
    return {key.split(".", 1)[1]: clean_keys(config.DEFAULTS.get(key))
            for key in config.keys("input")}


def config_label(name):
    """What an action does, in the words the settings tab uses."""
    entry_ = config.BY_KEY.get(f"{SECTION}.{name}")
    return entry_.label if entry_ is not None else \
        str(name).replace("_", " ").title()


# per-name numbers a project may tune, with the type each one takes
TUNING = {"deadzone": float}


def clean_tuning(value):
    """A tuning block with unknown keys and unreadable numbers dropped."""
    out = {}
    for key, raw in (value or {}).items():
        name = str(key).strip()
        cast = TUNING.get(name)
        if cast is None:
            continue
        try:
            out[name] = cast(raw)
        except (TypeError, ValueError):
            continue
    return out


class InputMap:
    """Actions and triggers in one table, as Godot's InputMap is."""

    def __init__(self, actions=None, triggers=None, tuning=None):
        self.actions = _table(actions)
        self.triggers = _table(triggers)
        self.tuning = clean_tuning(tuning)   # stick deadzone, and the like
        self._project = None          # the project this map was read from

    @classmethod
    def defaults(cls):
        """The engine's own keymap, with nothing of the project's in it."""
        return cls(config_table())

    @classmethod
    def from_project(cls, project):
        """Only what this project declares; defaults stay in `Input`."""
        if project is None:
            return cls()
        return cls(getattr(project, "input_map", dict)(),
                   getattr(project, "trigger_map", dict)(),
                   getattr(project, "input_tuning", dict)())

    def own(self, name):
        """Which table holds `name`, or None."""
        name = str(name)
        if name in self.triggers:
            return TRIGGER
        if name in self.actions:
            return ACTION
        return None

    def has(self, name):
        return self.own(name) is not None

    def is_trigger(self, name):
        return self.own(name) == TRIGGER

    @property
    def deadzone(self):
        """How far a stick travels before an axis counts as pressed."""
        return self.tuning.get("deadzone", inputmod.DEADZONE)

    def set_tuning(self, key, value):
        """Store one tuning number, or drop it back to the engine's own."""
        if value is None:
            self.tuning.pop(str(key), None)
            return None
        cast = TUNING.get(str(key))
        if cast is None:
            return None
        try:
            self.tuning[str(key)] = cast(value)
        except (TypeError, ValueError):
            return None
        return self.tuning[str(key)]

    def source(self, name):
        """Where a name's keys come from: project, player config, engine."""
        if self.has(name):
            return "project"
        name = str(name)
        mine = clean_keys(config_table().get(name))
        theirs = clean_keys(engine_table().get(name))
        return "player" if mine and mine != theirs else "engine"

    def names(self, trigger=None):
        """Every name, or just one table's, in alphabetical order."""
        if trigger is None:
            return sorted(set(self.actions) | set(self.triggers))
        table = self.triggers if trigger else self.actions
        return sorted(table)

    def keys_of(self, name):
        """The bindings stored for a name, from either table."""
        table = self.triggers if self.is_trigger(name) else self.actions
        return list(table.get(str(name), ()))

    def resolved(self, name):
        """The keys a name ends up with: the project's, else the default's."""
        return self.keys_of(name) or InputMap.defaults().keys_of(name)

    def labels(self, trigger=None):
        """Every name this map can show, with its keys and its purpose."""
        defaults = config_table()
        listed = self.names(trigger)
        if trigger is None:
            listed = sorted(set(listed) | set(defaults))
        out = []
        for name in listed:
            keys = self.keys_of(name) or clean_keys(defaults.get(name))
            out.append({"name": name, "keys": keys,
                        "what": config_label(name),
                        "kind": TRIGGER if self.is_trigger(name) else ACTION,
                        "here": self.has(name)})
        return out

    def set_keys(self, name, keys, trigger=None):
        """Write one name's bindings, moving it between tables on request."""
        name = str(name)
        keys = clean_keys(keys)
        want = self.is_trigger(name) if trigger is None else bool(trigger)
        self.actions.pop(name, None)
        self.triggers.pop(name, None)
        (self.triggers if want else self.actions)[name] = keys
        return keys

    def add(self, name, keys=(), trigger=False):
        """Name a new input; a trigger's press broadcasts its own name."""
        name = str(name).strip().replace(" ", "_")
        if not name:
            return None
        self.set_keys(name, keys, trigger=trigger)
        return name

    def remove(self, name):
        """Drop a name from both tables; True when something went."""
        name = str(name)
        return bool(self.actions.pop(name, None) is not None or
                    self.triggers.pop(name, None) is not None)

    def rename(self, old, new):
        """Re-name a name, keeping its bindings and its table."""
        old, new = str(old), str(new)
        kind = self.own(old)
        if not new or new == old or kind is None:
            return False
        keys = self.keys_of(old)
        self.remove(old)
        self.set_keys(new, keys, trigger=kind == TRIGGER)
        return True

    def conflicts(self):
        """Bindings two names share: [(token, [names, ...])].

        What the engine binds by default counts, so a trigger given `w` is
        reported against `forward` even in a project that binds nothing.
        """
        defaults = config_table()
        seen = {}
        for name in sorted(set(self.actions) | set(self.triggers)
                           | set(defaults)):
            for token in self.keys_of(name) or list(defaults.get(name, ())):
                seen.setdefault(token, set()).add(name)
        return sorted((token, sorted(names))
                      for token, names in seen.items() if len(names) > 1)

    def as_sections(self):
        """The manifest shape: `{"actions": ..., "triggers": ...}`."""
        return {"actions": {k: list(v) for k, v in self.actions.items()},
                "triggers": {k: list(v) for k, v in self.triggers.items()},
                "tuning": dict(self.tuning)}

    def apply(self, input_obj):
        """Bind the whole chain onto an `Input`, lowest layer first."""
        input_obj.bind_defaults()
        config.bind_defaults(input_obj)
        input_obj.bind_map(self.actions)
        input_obj.bind_triggers(self.triggers)
        input_obj.deadzone = self.deadzone
        return input_obj

    def __repr__(self):
        return (f"<InputMap {len(self.actions)} action(s), "
                f"{len(self.triggers)} trigger(s)>")


CURRENT = None


def load(project=None, force=False):
    """The process-wide map, rebuilt when the project changes."""
    global CURRENT
    path = str(getattr(project, "path", "")) if project is not None else ""
    if CURRENT is None or force or (path and path != CURRENT._project):
        CURRENT = InputMap.from_project(project)
    if path:
        CURRENT._project = path
    return CURRENT


def current():
    return load()


def save(project, mapping):
    """Write a map into the project's manifest; False with no project."""
    if project is None or not hasattr(project, "set"):
        return False
    sections = mapping.as_sections() if isinstance(mapping, InputMap) \
        else sections_of(mapping)
    if hasattr(project, "save_input_maps"):
        try:
            project.save_input_maps(sections["actions"], sections["triggers"],
                                    sections["tuning"])
        except TypeError:
            # an older project object takes the two tables only
            project.save_input_maps(sections["actions"], sections["triggers"])
    else:
        project.set(SECTION, "actions", sections["actions"])
        project.set(SECTION, "triggers", sections["triggers"])
        project.set(SECTION, "tuning", sections["tuning"])
        project.save_meta()
    load(project, force=True)
    return True


def sections_of(raw):
    """A plain `{...}` manifest section, both tables filled."""
    raw = raw or {}
    return {"actions": _table(raw.get("actions")),
            "triggers": _table(raw.get("triggers")),
            "tuning": clean_tuning(raw.get("tuning"))}


def binding_labels(keys):
    """A name's bindings in words, one help column."""
    return inputmod.binding_labels(keys)
