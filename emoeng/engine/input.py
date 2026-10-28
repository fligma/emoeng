"""Action-based input: bind keys once, scenes ask."""

import pygame

from . import config

# mouse buttons, by name and by pygame's number
MOUSE_BUTTONS = {"left": 1, "middle": 2, "right": 3, "x1": 4, "x2": 5}
MOUSE_NAMES = {1: "left", 2: "middle", 3: "right", 4: "x1", 5: "x2"}
WHEEL_BUTTONS = {4: 1.0, 5: -1.0}         # pygame numbers -> wheel direction

# how far a stick moves before an axis counts pressed
DEADZONE = 0.35

# SDL 2.0.14 tells a window the keyboard went away; pygame spells it two ways
WINDOWFOCUSLOST = getattr(pygame, "WINDOWFOCUSLOST", -1)


def is_focus_lost(e):
    """Did the window just lose the keyboard? No key-up is coming."""
    if e.type == WINDOWFOCUSLOST:
        return True
    if e.type != pygame.ACTIVEEVENT or not getattr(e, "state", 0) & \
            pygame.APPACTIVE:
        return False
    return not getattr(e, "gain", 1)


def _digits(text):
    return "".join(c for c in text if c.isdigit())


def parse_binding(value):
    """One token as a `(kind, ...)` tuple, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return ("key", value)
    text = str(value).strip().lower()
    if not text:
        return None
    kind, colon, rest = text.partition(":")
    if colon:
        if kind == "mouse":
            button = MOUSE_BUTTONS.get(rest)
            if button is None and rest.isdigit():
                button = int(rest)
            return ("mouse", button) if button else None
        if kind == "wheel":
            if rest in ("up", "1", "+1", "+"):
                return ("wheel", 1.0)
            if rest in ("down", "-1", "-"):
                return ("wheel", -1.0)
            return None
        if kind.startswith("joy"):
            pad = _digits(kind)
            if not pad:
                return None
            pad = int(pad)
            if rest.startswith("button") or rest.startswith("btn"):
                button = _digits(rest)
                return ("joybutton", pad, int(button)) if button else None
            if rest.startswith("axis") or rest.startswith("ax"):
                axis = _digits(rest)
                if not axis:
                    return None
                sign = -1.0 if "-" in rest else 1.0
                return ("joyaxis", pad, int(axis), sign)
            return None
        return None
    code = config.key_code(text)
    return ("key", code) if code is not None else None


def parse_bindings(values):
    """Tokens, de-duplicated, with unreadable ones dropped."""
    out = []
    for value in _flatten(values):
        token = parse_binding(value)
        if token is not None and token not in out:
            out.append(token)
    return tuple(out)


def _flatten(values):
    """`"w"`, `["w", "up"]`, `(pygame.K_w,)`... into one list of items."""
    if isinstance(values, (str, bytes, int, float)):
        return [values]
    out = []
    try:
        items = list(values)
    except TypeError:
        return [values]
    for item in items:
        out.extend(_flatten(item))
    return out


def binding_text(token):
    """The name a token was written as."""
    kind = token[0]
    if kind == "key":
        return config.key_name(token[1]) or f"key{token[1]}"
    if kind == "mouse":
        return f"mouse:{MOUSE_NAMES.get(token[1], token[1])}"
    if kind == "wheel":
        return "wheel:up" if token[1] > 0 else "wheel:down"
    if kind == "joybutton":
        return f"joy{token[1]}:button{token[2]}"
    if kind == "joyaxis":
        return f"joy{token[1]}:axis{'+' if token[3] > 0 else '-'}{token[2]}"
    return str(token)


def pad_for_instance(instance_id):
    """The `joyN:` number for an event's instance id."""
    try:
        count = pygame.joystick.get_count()
    except pygame.error:
        return instance_id
    for index in range(count):
        try:
            pad = pygame.joystick.Joystick(index)
            pad.init()
            if pad.get_instance_id() == instance_id:
                return index
        except pygame.error:
            continue
    return instance_id


# key names a player reads better than pygame's
BINDING_KEYS = {"escape": "Esc", "lshift": "Left Shift",
                "rshift": "Right Shift", "lctrl": "Left Ctrl",
                "rctrl": "Right Ctrl", "lalt": "Left Alt",
                "ralt": "Right Alt", "capslock": "Caps Lock",
                "pageup": "Page Up", "pagedown": "Page Down",
                "return": "Enter", "space": "Space", "tab": "Tab",
                "backspace": "Backspace"}
BINDING_MOUSE = {"left": "Mouse Left", "middle": "Mouse Middle",
                 "right": "Mouse Right", "x1": "Mouse X1",
                 "x2": "Mouse X2"}


def binding_label(value):
    """A binding name as a help panel spells it."""
    name = str(value).lower()
    kind, colon, rest = name.partition(":")
    if colon:
        if kind == "mouse":
            return BINDING_MOUSE.get(rest) or f"Mouse {rest}"
        if kind == "wheel":
            return "Wheel Up" if rest.startswith("up") else "Wheel Down"
        if kind.startswith("joy"):
            pad = kind[3:] or "0"
            if rest.startswith("button"):
                return f"Pad {pad} Button {rest[6:]}"
            if rest.startswith("axis"):
                return f"Pad {pad} Axis {rest[4:]}"
            return f"Pad {pad} {rest}"
        return name
    if name in BINDING_KEYS:
        return BINDING_KEYS[name]
    return name.upper() if len(name) == 1 else name.capitalize()


def binding_labels(values):
    """A binding list in words, one help column."""
    return ", ".join(binding_label(v) for v in (values or ()))


class Input:
    def __init__(self):
        self.bindings = {}              # action -> tuple of tokens
        self.triggers = set()           # actions whose press broadcasts
        self.down_actions = set()
        self.pressed_actions = set()
        self.released_actions = set()
        self.mouse_pos = (0, 0)
        self.mouse_rel = (0, 0)
        self._mouse_pos_known = False
        self.buttons = set()
        self.buttons_pressed = set()
        self.buttons_released = set()
        self.wheel = 0.0
        self.text = ""
        self.joystick = None            # the first pad found
        self.joysticks = {}             # token index -> pygame Joystick
        self._joy_index = {}            # instance id -> token index
        self.grabbed = False
        self._notches = set()           # actions a wheel notch fired
        self._axes = {}                 # (pad, axis) -> current sign
        self.rescan()

    def bind(self, action, *bindings):
        """Bind `action` to tokens; accepts names and pygame constants."""
        self.bindings[str(action)] = parse_bindings(bindings)
        return self

    def bind_action(self, action, values):
        """`bind()` with one iterable, as a map hands over."""
        return self.bind(action, *list(_flatten(values)))

    def unbind(self, action):
        self.bindings.pop(action, None)

    def bindings_of(self, action):
        """The names an action is bound to, for display."""
        return [binding_text(t) for t in self.bindings.get(action, ())]

    def actions(self):
        return sorted(self.bindings)

    def has_action(self, action):
        return action in self.bindings

    def bound_by(self, token_value):
        """Which actions would fire on this token ("" when unbound)."""
        token = parse_binding(token_value)
        if token is None:
            return []
        return sorted(a for a, tokens in self.bindings.items()
                      if token in tokens)

    def conflicts(self):
        """Tokens two or more actions share: [(name, [action, ...])]."""
        seen = {}
        for action, tokens in self.bindings.items():
            for token in tokens:
                seen.setdefault(token, []).append(action)
        return sorted((binding_text(token), sorted(actions))
                      for token, actions in seen.items() if len(actions) > 1)

    def bind_defaults(self, forward=(pygame.K_w, pygame.K_UP),
                      back=(pygame.K_s, pygame.K_DOWN),
                      left=(pygame.K_a, pygame.K_LEFT),
                      right=(pygame.K_d, pygame.K_RIGHT),
                      run=(pygame.K_LSHIFT, pygame.K_RSHIFT),
                      up=pygame.K_SPACE, down=(pygame.K_q, pygame.K_LCTRL),
                      use=pygame.K_e, reload=pygame.K_r):
        """Install the WASD-arrows set every scene can poll."""
        self.bind("forward", forward)
        self.bind("back", back)
        self.bind("left", left)
        self.bind("right", right)
        self.bind("run", run)
        self.bind("up", up)
        self.bind("down", down)
        self.bind("use", use)
        self.bind("reload", reload)
        return self

    def bind_map(self, mapping, replace=False):
        """Bind a whole `{action: tokens}` map."""
        mapping = mapping or {}
        if replace:
            self.bindings.clear()
        for action, values in mapping.items():
            if str(action).startswith("_"):
                continue
            tokens = parse_bindings(_flatten(values))
            if tokens:
                self.bindings[str(action)] = tokens
        return self

    def bind_triggers(self, mapping):
        """Bind trigger names too, and remember them as triggers."""
        for name, values in (mapping or {}).items():
            if str(name).startswith("_"):
                continue
            self.bind_map({name: values})
            self.mark_trigger(name)
        return self

    def mark_trigger(self, action):
        """Say an action's press should be broadcast as a trigger."""
        self.triggers.add(str(action))
        return str(action)

    def unmark(self, action):
        """Stop broadcasting an action; its bindings stay."""
        self.triggers.discard(str(action))
        return str(action)

    def fired_triggers(self):
        """Triggers pressed since the frame began, in name order."""
        return sorted(self.triggers & self.pressed_actions)

    def _actions_for(self, token):
        return [a for a, bound in self.bindings.items() if token in bound]

    def begin_frame(self):
        self.pressed_actions.clear()
        self.released_actions.clear()
        self.buttons_pressed.clear()
        self.buttons_released.clear()
        self.mouse_rel = (0, 0)
        self.wheel = 0.0
        # a wheel notch is a click, not a held key
        self.down_actions -= self._notches
        self._notches.clear()
        self.text = ""

    def handle(self, e):
        """Feed one pygame event; returns True when it was input."""
        if e.type == pygame.KEYDOWN:
            if e.unicode and e.unicode.isprintable():
                self.text += e.unicode
            self._fire(("key", e.key), down=True)
            return True
        if e.type == pygame.KEYUP:
            self._fire(("key", e.key), down=False)
            return True
        if e.type == pygame.MOUSEMOTION:
            pos = tuple(e.pos)
            x, y = self.mouse_rel
            dx, dy = e.rel
            if not self.grabbed and self._mouse_pos_known and not (dx or dy):
                dx = pos[0] - self.mouse_pos[0]
                dy = pos[1] - self.mouse_pos[1]
            self.mouse_pos = pos
            self._mouse_pos_known = True
            self.mouse_rel = (x + dx, y + dy)
            return True
        if e.type == pygame.MOUSEBUTTONDOWN:
            notch = WHEEL_BUTTONS.get(e.button)
            if notch is not None:
                self.wheel += notch
                self._notches.update(self._fire(("wheel", notch), down=True))
            else:
                self.buttons.add(e.button)
                self.buttons_pressed.add(e.button)
                self._fire(("mouse", e.button), down=True)
            return True
        if e.type == pygame.MOUSEBUTTONUP:
            self.buttons.discard(e.button)
            self.buttons_released.add(e.button)
            self._fire(("mouse", e.button), down=False)
            return True
        if e.type == pygame.JOYDEVICEADDED:
            self._open_joystick(e.device_index)
            return True
        if e.type == pygame.JOYDEVICEREMOVED:
            instance = getattr(e, "instance_id", None)
            index = self._joy_index.pop(instance, None)
            self.joysticks.pop(index, None)
            if not self.joysticks:
                self.joystick = None
            return True
        if e.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
            joy = self._pad_index(e.joy)
            self._fire(("joybutton", joy, e.button),
                       down=e.type == pygame.JOYBUTTONDOWN)
            return True
        if e.type == pygame.JOYAXISMOTION:
            return self._axis_motion(self._pad_index(e.joy), e.axis, e.value)
        return False

    def _fire(self, token, down):
        """Move every action bound to `token` in or out."""
        fired = self._actions_for(token)
        for action in fired:
            if down:
                self.down_actions.add(action)
                self.pressed_actions.add(action)
            else:
                self.down_actions.discard(action)
                self.released_actions.add(action)
        return fired

    def consume(self, button):
        """Throw away one mouse button's state: the scene took the"""
        button = int(button)
        bound = set(self._actions_for(("mouse", button)))
        self.pressed_actions -= bound
        self.down_actions -= bound
        self.released_actions -= bound
        self.buttons_pressed.discard(button)
        self.buttons_released.discard(button)

    def _axis_motion(self, joy, axis, value):
        """A stick returning to centre releases like a key."""
        sign = 0.0
        if value > DEADZONE:
            sign = 1.0
        elif value < -DEADZONE:
            sign = -1.0
        was = self._axes.get((joy, axis), 0.0)
        if sign == was:
            return False
        if was:
            self._fire(("joyaxis", joy, axis, was), down=False)
        if sign:
            self._fire(("joyaxis", joy, axis, sign), down=True)
        self._axes[(joy, axis)] = sign
        return True

    def _open_joystick(self, index):
        try:
            pad = pygame.joystick.Joystick(index)
            pad.init()
        except pygame.error:
            return None
        self.joysticks[index] = pad
        try:
            self._joy_index[pad.get_instance_id()] = index
        except pygame.error:
            pass
        if self.joystick is None:
            self.joystick = pad
        return pad

    def _pad_index(self, instance_id):
        """The pad number a `joyN:` token means."""
        cached = self._joy_index.get(instance_id)
        if cached is not None:
            return cached
        index = pad_for_instance(instance_id)
        self._joy_index[instance_id] = index
        return index

    def rescan(self):
        """Open plugged-in pads; returns how many are live."""
        try:
            count = pygame.joystick.get_count()
        except pygame.error:
            count = 0
        for index in range(count):
            if index not in self.joysticks:
                self._open_joystick(index)
        return len(self.joysticks)

    def down(self, action):
        return action in self.down_actions

    def pressed(self, action):
        return action in self.pressed_actions

    def released(self, action):
        return action in self.released_actions

    def mouse_down(self, button=1):
        return button in self.buttons

    def mouse_pressed(self, button=1):
        return button in self.buttons_pressed

    def mouse_released(self, button=1):
        return button in self.buttons_released

    def axis(self, positive, negative):
        """The -1..1 value of two actions."""
        return (1.0 if self.down(positive) else 0.0) - \
               (1.0 if self.down(negative) else 0.0)

    def move_axis(self):
        """WASD-style (right, forward) in -1..1."""
        return (self.axis("right", "left"), self.axis("forward", "back"))

    def stick(self, deadzone=0.18, axis_x=0, axis_y=1, pad=None):
        """The analog left stick, always available."""
        pad_ = self.joystick if pad is None else \
            self.joysticks.get(pad, self.joystick)
        if pad_ is None:
            return (0.0, 0.0)
        try:
            x = pad_.get_axis(axis_x)
            y = pad_.get_axis(axis_y)
        except (pygame.error, IndexError):
            return (0.0, 0.0)
        if abs(x) < deadzone:
            x = 0.0
        if abs(y) < deadzone:
            y = 0.0
        return (x, -y)

    def trigger(self, pad=0, index=2, deadzone=0.05):
        """One analog axis as a 0..1 trigger value."""
        pad_ = self.joysticks.get(pad)
        if pad_ is None:
            return 0.0
        try:
            value = pad_.get_axis(index)
        except (pygame.error, IndexError):
            return 0.0
        return max(0.0, (value + 1.0) / 2.0) if value > deadzone else 0.0

    def grab_mouse(self, on=True):
        self.grabbed = bool(on)
        pygame.mouse.set_visible(not on)
        pygame.event.set_grab(bool(on))
        if not on:
            try:
                self.mouse_pos = tuple(pygame.mouse.get_pos())
                self._mouse_pos_known = True
            except pygame.error:
                self._mouse_pos_known = False

    def poll_keys(self):
        """Recover held action keys from SDL state as well as key events."""
        try:
            pressed = pygame.key.get_pressed()
        except pygame.error:
            return
        for action, tokens in self.bindings.items():
            held = False
            for token in tokens:
                if token[0] != "key":
                    continue
                try:
                    held = bool(pressed[token[1]])
                except (IndexError, TypeError):
                    held = False
                if held:
                    break
            if held and action not in self.down_actions:
                self.down_actions.add(action)
                self.pressed_actions.add(action)

    def clear(self):
        self.down_actions.clear()
        self.buttons.clear()
        self._notches.clear()
        self._axes.clear()

    def release_all(self):
        """Let go of everything held, and report each one as released.

        A window that loses the keyboard never sees the key-up for a key
        it was held with, so the drop has to look like the release it was:
        a silent `clear()` leaves a scene watching for one, and an editor
        camera keeps flying.
        """
        self.released_actions |= self.down_actions
        self.buttons_released |= self.buttons
        self.clear()
