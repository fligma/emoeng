"""Save slots: JSON dictionaries a game can read and write."""

import json
import time
from pathlib import Path

from .. import const
from . import paths

DEFAULT_SLOT = const.SAVE_SLOT


class SaveStore:
    """One JSON slot, loaded on open and written by save()."""

    def __init__(self, project=None, slot=DEFAULT_SLOT, autoload=True):
        self.project = project
        self.slot = str(slot or DEFAULT_SLOT)
        self.data = {}
        self.loaded = False
        self.error = None
        if autoload:
            self.load()

    def folder(self):
        if self.project is not None:
            return Path(self.project.path) / "saves"
        return paths.user_dir() / "saves"

    def path(self):
        name = "".join(c if c.isalnum() or c in "_-" else "_"
                       for c in self.slot)
        return self.folder() / f"{name or DEFAULT_SLOT}.json"

    def load(self):
        path = self.path()
        self.data = {}
        self.error = None
        self.loaded = False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.loaded = True
            return self.data
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.loaded = True
            return self.data
        values = payload.get("values") if isinstance(payload, dict) else None
        if isinstance(values, dict):
            self.data = dict(values)
        elif isinstance(payload, dict):
            self.data = dict(payload)         # hand-written flat file
        self.loaded = True
        return self.data

    def save(self, slot=None):
        if slot is not None:
            self.slot = str(slot)
        path = self.path()
        payload = {
            "slot": self.slot,
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "values": self.data,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            self.error = None
            return path
        except OSError as exc:
            fallback = paths.user_dir() / "saves" / path.name
            try:
                fallback.parent.mkdir(parents=True, exist_ok=True)
                fallback.write_text(json.dumps(payload, indent=1),
                                    encoding="utf-8")
                self.error = None
                return fallback
            except OSError:
                self.error = str(exc)
                return None

    def clear(self, save_file=True):
        self.data = {}
        if save_file:
            try:
                self.path().unlink()
            except OSError:
                pass
        return self

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        return value

    def add(self, key, amount=1):
        """Numeric bump; non-numbers are replaced by `amount`."""
        current = self.data.get(key, 0)
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            current = 0
        self.data[key] = current + amount
        return self.data[key]

    def flag(self, key, value=True):
        """Set a boolean flag and return it."""
        self.data[key] = bool(value)
        return bool(value)

    def unflag(self, key):
        self.data.pop(key, None)
        return self

    def has(self, key):
        return key in self.data

    def pop(self, key, default=None):
        return self.data.pop(key, default)

    def keys(self):
        return self.data.keys()

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __contains__(self, key):
        return key in self.data

    def __len__(self):
        return len(self.data)

    def __repr__(self):
        return f"<SaveStore {self.slot} {len(self.data)} keys>"
