"""Action-based input: bind keys once and let scenes ask for actions.

    game.input.bind("forward", pygame.K_w, pygame.K_UP)
    if game.input.down("forward"): ...

Also carries the mouse delta, buttons, wheel and joystick axes, so a game
never has to rummage through the raw event list.
"""

import pygame


class Input:
    def __init__(self):
        self.bindings = {}
        self.down_actions = set()
        self.pressed_actions = set()
        self.released_actions = set()
        self.mouse_pos = (0, 0)
        self.mouse_rel = (0, 0)
        self.buttons = set()
        self.buttons_pressed = set()
        self.buttons_released = set()
        self.wheel = 0.0
        self.text = ""
        self.joystick = None
        self.grabbed = False

    # ------------------------------------------------------------ bindings
    def bind(self, action, *keys):
        self.bindings[action] = tuple(keys)
        return self

    def unbind(self, action):
        self.bindings.pop(action, None)

    def _actions_for(self, key):
        return [a for a, keys in self.bindings.items() if key in keys]

    # -------------------------------------------------------------- events
    def begin_frame(self):
        self.pressed_actions.clear()
        self.released_actions.clear()
        self.buttons_pressed.clear()
        self.buttons_released.clear()
        self.mouse_rel = (0, 0)
        self.wheel = 0.0

    def handle(self, e):
        """Feed one pygame event; returns True when it was input."""
        if e.type == pygame.KEYDOWN:
            if e.unicode and e.unicode.isprintable():
                self.text += e.unicode
            for a in self._actions_for(e.key):
                self.down_actions.add(a)
                self.pressed_actions.add(a)
            return True
        if e.type == pygame.KEYUP:
            for a in self._actions_for(e.key):
                self.down_actions.discard(a)
                self.released_actions.add(a)
            return True
        if e.type == pygame.MOUSEMOTION:
            self.mouse_pos = e.pos
            x, y = self.mouse_rel
            self.mouse_rel = (x + e.rel[0], y + e.rel[1])
            return True
        if e.type == pygame.MOUSEBUTTONDOWN:
            if e.button in (4, 5):
                self.wheel += 1.0 if e.button == 4 else -1.0
            else:
                self.buttons.add(e.button)
                self.buttons_pressed.add(e.button)
            return True
        if e.type == pygame.MOUSEBUTTONUP:
            self.buttons.discard(e.button)
            self.buttons_released.add(e.button)
            return True
        if e.type == pygame.JOYDEVICEADDED:
            self._open_joystick(e.device_index)
            return True
        return False

    def _open_joystick(self, index):
        try:
            self.joystick = pygame.joystick.Joystick(index)
            self.joystick.init()
        except pygame.error:
            self.joystick = None

    # --------------------------------------------------------------- state
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

    # --------------------------------------------------------------- axes
    def axis(self, positive, negative):
        return (1.0 if self.down(positive) else 0.0) - \
               (1.0 if self.down(negative) else 0.0)

    def move_axis(self):
        """WASD-style (right, forward) in -1..1."""
        return (self.axis("right", "left"), self.axis("forward", "back"))

    def stick(self, deadzone=0.18, axis_x=0, axis_y=1):
        if self.joystick is None:
            return (0.0, 0.0)
        try:
            x = self.joystick.get_axis(axis_x)
            y = self.joystick.get_axis(axis_y)
        except pygame.error:
            return (0.0, 0.0)
        if abs(x) < deadzone:
            x = 0.0
        if abs(y) < deadzone:
            y = 0.0
        return (x, -y)

    def grab_mouse(self, on=True):
        self.grabbed = bool(on)
        pygame.mouse.set_visible(not on)
        pygame.event.set_grab(bool(on))

    def clear(self):
        self.down_actions.clear()
        self.buttons.clear()
