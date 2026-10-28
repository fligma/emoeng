# UI and HUD

Three layers draw on top of the 3D frame: `engine.ui` for one-off HUD marks,
`engine.xp` for the Windows-Luna widget kit the editor and the pause menu share,
and `UIObject` for widgets that live in a scene. `engine.theme` recolours `xp`.

Everything is drawn into the `screen` surface the game hands to
`Scene.overlay(screen)` - after the renderer's frame, before the chrome.

## The overlay hook

| Fact | Detail |
| --- | --- |
| Signature | `Scene.overlay(screen)` - `screen` is the pygame display surface, in window pixels |
| When | Every frame, after post-processing and letterboxing |
| Exceptions | Caught: the loop prints it and draws `overlay error: ...` in `LOG_ERROR` red, so one bad line cannot kill the frame |
| Coordinates | Pixels, origin top-left; `game.screen.get_size()` is the current size |

```python
class Main(fe.Scene3D):
    def overlay(self, screen):
        w, h = screen.get_size()
        fe.ui.panel(screen, (12, 12, 200, 54))
        fe.ui.text(screen, self.game.fonts["normal"],
                   f"eyes {self.eyes}", (22, 20))
        fe.ui.bar(screen, (22, 44, 180, 12), self.health / 100.0)
```

## `self.hud` - the same calls, shortened

`ui` asks for a surface and a font every time, which is right for a module and
noisy in an overlay. `scene.hud` is a facade that holds this scene's game and
fills both in, so one readout is one call. Objects reach it through
`self.hud` too, and it is exactly what the blocks in the palette's `Hud`
drawer write.

| Call | Draws |
| --- | --- |
| `hud.text(s, pos, color=..., align="left", shadow=..., alpha=255)` | One line in `fonts["normal"]` |
| `hud.font_of(size="big")` | `small`, `normal`, `big`, `title` or `mono` |
| `hud.panel(rect, color=(10,10,14), alpha=150, border=None)` | A backing panel |
| `hud.bar(rect, frac, **kw)` | A value bar |
| `hud.crosshair(centre=None, **kw)` | A reticle, centred on the play area |
| `hud.prompt(key, label, centre=None, **kw)` | `[E] pick up`, low on the play area |
| `hud.hints(pairs, pos=None, **kw)` | Key/action rows, bottom left of the play area |
| `hud.subtitle(lines, bottom=None, **kw)` | Centred captions near the bottom |
| `hud.dim(amount=0.55)` | The full-window dark wash |

`bar`, `crosshair`, `prompt`, `hints` and `subtitle` pass their extra keywords
straight to `ui`, so `hud.bar(rect, frac, fill=(90, 190, 120))` works. The
surface is read from `game.screen` on every call, so a resized window needs no
rebuilding; `hud.screen` and `hud.font` expose the two, and every call answers
with what it painted.

```python
def overlay(self, screen):
    self.hud.crosshair()
    self.hud.text(f"eyes {self.eyes}", (24, 24))
    self.hud.bar((24, 44, 160, 10), self.health / 100.0)
    self.hud.hints([("wasd", "move"), ("e", "use")])
```

### `hud.area` and `game.play_area()`

The chrome paints its caption, menu and status bars *after* the scene's
`overlay()`, so a row inside the top ~50 px or the bottom 22 is covered by the
window rather than by the scene. `game.play_area()` is the rect that is left:

| Chrome | Bars taken off |
| --- | --- |
| windowed | `CAP_H 28` + `MENU_H 22` at the top, `STATUS_H 22` at the bottom |
| fullscreen | none - the whole window |

The editor's Scene preview and the smoke harness answer with the whole window
too: neither paints the bars, so a HUD laid out for windowed play is seen in
full there, a little higher up than the game draws it.

`hud.area` is that rect, and every default `hud` position is measured from it -
the crosshair at its centre, the hints at its bottom left, the prompt 92 px
above its bottom, the captions 16 px above it. Lay your own panels inside it as
well, or they end up under the menu bar:

```python
def overlay(self, screen):
    hud = self.hud
    box = pygame.Rect(12, hud.area.y + 4, 226, 58)
    hud.panel(box)
    hud.text(f"shards {self.taken}/{self.total}", (box.x + 12, box.y + 8))
    hud.bar((box.x + 12, box.y + 32, 196, 10), self.taken / self.total)
```

## Fonts

`Game` builds five fonts once. Use them rather than calling `SysFont` per
frame.

| Key | Font | For |
| --- | --- | --- |
| `small` | tahoma 11 | status bar, dense readouts |
| `normal` | tahoma 13 | body text, buttons |
| `big` | tahoma 18 bold | headings, a score |
| `title` | tahoma 28 bold | a title card |
| `mono` | consolas 12 | numbers, coordinates, the debug rows |

## `engine.ui`

| Function | Signature | Draws |
| --- | --- | --- |
| `text` | `text(surf, font, s, pos, color=DEFAULT_TEXT, shadow=SHADOW, align="left", alpha=255)` | One line with a 1px dark drop shadow; `align` is `left`, `centre` or `right`; returns its rect |
| `panel` | `panel(surf, rect, color=(10,10,14), alpha=150, border=None)` | Translucent backing rectangle; optional 1px `border` |
| `bar` | `bar(surf, rect, frac, fill=(190,50,45), back=(30,26,28), border=(220,216,200))` | Value bar; `frac` is clamped `0..1`, inset 1px on each side |
| `crosshair` | `crosshair(surf, centre, size=10, gap=3, color=(245,240,230), thick=1)` | Four ticks around a gap - a reticle |
| `prompt` | `prompt(surf, font, key, label, centre, color=(255,245,210))` | `[E] pick up` - keycap plus label, centred on `centre`; returns the whole rect |
| `hints` | `hints(surf, font, pairs, pos, color=(210,206,190))` | A stack of `("WASD", "move")` lines, growing downward |
| `menu` | `menu(surf, font, options, selected, pos, width=240, accent=(70,140,220))` | Vertical option list with one highlighted row; returns the row rects |
| `subtitle` | `subtitle(surf, font, lines, bottom, color=(238,234,220))` | Centred caption lines sitting `bottom` pixels up, each on its own black panel |
| `dim` | `dim(surf, amount=0.55)` | Full-frame dark wash, for pause and death screens |
| `keycap` | `keycap(surf, font, key, pos, size=None)` | A lone keycap, for tutorials |

Module colours: `DEFAULT_TEXT = (236, 236, 230)` and `SHADOW = (8, 8, 10)`.
`text()` accepts anything stringifiable, so `fe.ui.text(s, f, self.health, ...)`
is fine.

```python
def overlay(self, screen):
    f = self.game.fonts
    if self.nearby:
        fe.ui.prompt(screen, f["normal"], self.game.key_text("use"),
                     self.nearby, (screen.get_width() // 2,
                                   screen.get_height() - 80))
    if self.line:
        fe.ui.subtitle(screen, f["big"], self.line, 90)
    if self.game.paused:
        fe.ui.dim(screen, 0.6)
```

## The keymap, in the game's own words

`Game` builds its help text from the live bindings, so a rebind - in the
config, in `input.map.json`, or in a scene's `actions` - shows up with nothing
to maintain.

| Call | Returns |
| --- | --- |
| `game.key_text(action)` | `"W / Up"`, `""` when unbound |
| `game.control_hint()` | One line for the status bar: move / mouse look / use / pause / "for the rest" |
| `game.controls()` | `[(control, description)]` for the F1 panel |
| `scene.status()` | A list of status-bar panels; the game appends the hint |
| `scene.controls` | A tuple of extra action names to add to the F1 list |

```python
class Main(fe.Scene3D):
    actions = {"dash": ["mouse:left"], "grab": ["g"]}
    controls = ("dash", "grab")

    def status(self):
        return [f"{self.name}  eyes {self.eyes}", self.game.control_hint()]

    def overlay(self, screen):
        fe.ui.hints(screen, self.game.fonts["small"],
                    [(self.game.key_text(a), a.title()) for a in self.controls],
                    (14, screen.get_height() - 60))
```

`CONTROLS_HINT` is `(("forward", "move"), ("use", "use"), ("pause", "pause"))`
and `CONTROLS_EXTRA` lists what no binding can name: `Mouse / Look around`,
`Ctrl+T / Dark / light theme`, `F6 / Re-read code (hot reload)`. Both adapt to
the scene kind - "Look around" is only offered for a 3D scene, and a 2D or UI
scene's hint is just the pause key.

## `engine.xp` - the Luna widget kit

Every colour is a module global, which is what makes a theme a `setattr` sweep.
Each function draws into a surface you pass; nothing is a stateful widget, so
the editor and the pause menu drive hit-testing themselves from the returned
rects.

| Function | Signature | Returns |
| --- | --- | --- |
| `lerp_color` | `lerp_color(c1, c2, t)` | A blended triple (`_lerp` is an alias) |
| `gradient_v` | `gradient_v(surf, rect, top, bottom)` | `None` |
| `bevel` | `bevel(surf, rect, light=None, dark=None, sunken=False, width=1)` | The Win32 3D edge |
| `raised` / `sunken` | `raised(surf, rect)`, `sunken(surf, rect)` | One-line bevels |
| `field` | `field(surf, rect, bg=None)` | A sunken white input field |
| `button` | `button(surf, rect, label, font, default=False, hovered=False, pressed=False, enabled=True)` | The rect |
| `checkbox` | `checkbox(surf, pos, checked, label, font, text_color=None)` | The full box-plus-label rect; `pos` is the shared vertical centre |
| `combo` | `combo(surf, rect, value, font, hovered=False)` | A read-only dropdown |
| `slider` | `slider(surf, rect, frac, live=False)` | The thumb rect - drag it |
| `slider_frac` | `slider_frac(rect, pos)` | The `0..1` value under a mouse point |
| `groupbox` | `groupbox(surf, rect, label, font, text_color=None)` | Etched frame with a caption; returns the label image |
| `titlebar` | `titlebar(surf, rect, title, font, icon=None, dialog=False)` | The close-button rect; `dialog=True` draws only close |
| `menubar` | `menubar(surf, rect, active=None, font=None, labels=("File","Edit","View","Project","Help"))` | `None` |
| `menu_items` | `menu_items(surf, pos, items, font, hover=-1, width=170)` | `(panel_rect, row_rects)` from `[(label, enabled)]`; a `None`/`"-"` label is a separator and its slot is `None` |
| `statusbar` | `statusbar(surf, rect, panels, font)` | Sunken text panels, widths shared out, long text clipped |
| `tooltip` | `tooltip(surf, pos, lines, font)` | The bubble rect, clamped inside the surface |
| `message_frame` | `message_frame(surf, rect, title, font, icon=None)` | `(body_rect, close_rect)` - a modal-looking dialog |
| `tabs` | `tabs(surf, rect, labels, active, font, hover=-1)` | The tab rects |
| `scrollbar` | `scrollbar(surf, rect, frac, page, vertical=True)` | The thumb rect; `page` is the visible fraction |

The game's own pause and F1 screens are drawn with it: `message_frame` for the
window, `button` for Resume / Restart / Quit, `titlebar` and `menubar` for the
window chrome.

```python
def overlay(self, screen):
    if not self.paused:
        return
    body, _close = fe.xp.message_frame(screen, (200, 140, 360, 200),
                                       "Paused", self.game.fonts["normal"])
    fe.xp.button(screen, pygame.Rect(body.x + 20, body.y + 20, 150, 30),
                 "Resume", self.game.fonts["normal"], default=True,
                 hovered=self.hover == "resume")
```

The editor's own popups are built on the same kit. The asset picker that opens
under a texture / model / shader / sound slot (`widgets.Choices`) is painted in
the `menu_items` panel style and returns the word clicked, and the Output
panel's `Copy` button runs through `widgets.copy_to_clipboard` - `pygame.scrap`
first, a `Set-Clipboard` subprocess as a Windows fallback, wrapped so a machine
with neither answers `False` rather than raising. See [Blocks](blocks.md) and
[The Editor](editor.md).

## `engine.theme`

| Call | Effect |
| --- | --- |
| `theme.available()` | `("dark", "light")` |
| `theme.current()` | The installed palette name |
| `theme.apply(name)` | Write a palette into `xp`; an unknown name falls back to `dark` |
| `theme.toggle()` | Swap dark/light, persist it, return the new name |
| `theme.load()` | The configured name from `editor.theme` |
| `theme.save(name=None)` | Persist through `config` and return the file written |
| `theme.DARK` / `theme.LIGHT` | The palette dicts, ~90 colour keys each |

`apply()` starts from `LIGHT` and overlays the chosen palette, so every key is
always defined. `Game.__init__` calls `theme.apply(theme.load())` before it
builds a window, and `Ctrl+T` is bound to the toggle in the game loop as well as
the editor.

## Widgets in a scene - `UIObject`

Clickable panels that live in a `SceneUI` or `Scene2D`, with text baked into an
RGBA texture. Full API in [Objects](objects.md); the interaction contract:

| Piece | Behaviour |
| --- | --- |
| `action=callable` | Called by `click()` first |
| `on_click()` | Called after `action` |
| `on_hover()` / `on_leave()` | Pointer entered / left |
| `hover_color` / `press_color` | `None` keeps the base colour - nothing auto-lightens |
| `enabled=False` | Ignores input; greyed by your own draw code |
| `set_text(text)` | Re-renders the label texture |
| `SceneUI.route_mouse(e)` | Hands the event to the topmost widget under the pointer |

```python
class Menu(fe.SceneUI):
    name = "menu"

    def setup(self):
        w, h = self.window_size
        for i, (label, action) in enumerate((("New game", self.start),
                                             ("Options", self.options),
                                             ("Quit", self.game.quit))):
            self.spawn(fe.UIObject, (w // 2, 200 + i * 74), text=label,
                       size=(320.0, 56.0), anchor=(0.5, 0.5), action=action,
                       hover_color=(0.24, 0.52, 0.9),
                       press_color=(0.12, 0.3, 0.6))

    def start(self):
        self.play_scene("main")
```

`SceneUI.world_size` is `None`, so the world *is* the window: one world unit is
one window pixel, zoom is 1:1 and `self.window_size` is the current size - read
it in `setup()`, or re-place widgets when the window changes. A `Scene2D` with a
`world_size` instead scales a fixed design box, so `0.5, 0.5`-style fractions
only make sense there through `to_world()` and the camera's zoom.

A `UIObject` label is real geometry, so it scales with the scene's `world_size`
and `scale_mode` - text stays part of the picture rather than a pixel overlay.
Use `ui.text` in `overlay()` for readouts that must stay crisp at exactly
window size.

Related pages: [Objects](objects.md), [Scenes](scenes.md),
[Game Loop](game-loop.md), [Player and Input](player-and-input.md).
