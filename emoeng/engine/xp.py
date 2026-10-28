"""Palette and widget drawing primitives for editor and game."""

import pygame


# surfaces
FACE = (236, 233, 216)          # dialog / window background (#ECE9D8)
HILITE = (255, 255, 255)        # raised bevel highlight
SHADOW = (170, 166, 150)        # raised bevel shadow
DK_SHADOW = (120, 116, 100)     # outer / sunken deep shadow
FIELD = (255, 255, 255)         # text fields, list boxes
FIELD_ALT = (247, 246, 240)     # alternating list rows

# title bar gradient (active window)
CAP_TOP = (38, 120, 222)        # light band under the top edge
CAP_HI = (18, 92, 205)          # top of the arch
CAP_MID = (10, 74, 180)         # middle
CAP_BOT = (8, 58, 148)          # where the caption meets the face
CAP_GLOW = (150, 198, 255)      # thin highlight line along the very top

# text
TEXT = (16, 16, 16)
TEXT_MUTED = (110, 110, 100)
CAPTION = (255, 255, 255)

# push buttons
BTN_TOP = (255, 255, 255)
BTN_MID = (240, 240, 232)
BTN_BOT = (214, 217, 199)
BTN_BORDER = (121, 121, 110)
BTN_HOVER_BORDER = (60, 135, 205)
BTN_HOVER_BG = (229, 241, 253)
BTN_DEFAULT_BORDER = (228, 195, 101)   # the green-ish default glow
BTN_PRESSED = (198, 204, 180)

# selection / focus
SELECTION = (49, 106, 197)             # list selection blue
PRESS_SELECTION = (24, 66, 130)        # ... and while a click holds it

# combo box button
COMBO_A = (255, 255, 255)
COMBO_B = (218, 206, 150)
COMBO_BORDER = (142, 135, 110)

# window caption buttons
SYS_BTN_A = (80, 160, 255)
SYS_BTN_B = (10, 90, 200)
CLOSE_BTN_A = (240, 130, 100)
CLOSE_BTN_B = (200, 40, 30)
CLOSE_BTN_EDGE = (255, 210, 200)

# theme swaps these names, so draw code reads `xp.NAME`
PANEL = (247, 246, 240)          # central workspace backdrop
OUTLINE = (128, 124, 108)        # hairline around the workspace
LINK = (20, 50, 100)             # accent headings
SELECT_BORDER = (60, 120, 200)
SELECT_TEXT = (255, 255, 255)
SELECT_SUBTEXT = (226, 236, 250)
THUMB_BG = (248, 246, 238)
THUMB_LINE = (196, 192, 182)
CARD_BG = (247, 246, 240)

LOG_BG = (252, 252, 250)
LOG_INFO = (58, 58, 54)
LOG_OK = (24, 110, 52)
LOG_WARN = (150, 96, 10)
LOG_ERROR = (170, 36, 30)
LOG_MUTED = (120, 118, 108)

SCROLL_TROUGH = (238, 236, 226)
SCROLL_TOP = (255, 255, 255)
SCROLL_BOT = (214, 214, 200)

TAB_HOVER_TOP = (246, 245, 236)
TAB_HOVER_BOT = (224, 221, 205)

CAPTION_SHADOW = (10, 40, 90)
SYS_BTN_EDGE = (200, 225, 255)
COMBO_ARROW = (40, 40, 40)
CHECK = (20, 90, 30)
TOOLTIP_BG = (255, 255, 225)
TOOLTIP_BORDER = (0, 0, 0)
TOOLTIP_TEXT = (0, 0, 0)

# code editor
CODE_TEXT = (24, 24, 24)
CODE_SELECT = (205, 222, 246)
CODE_CURRENT = (246, 249, 255)
GUTTER_BG = (238, 236, 226)
GUTTER_TEXT = (120, 120, 112)
GUTTER_LINE = (200, 198, 188)
CARET = (20, 20, 20)
MODIFIED = (190, 80, 40)
SYN_KW = (0, 0, 168)
SYN_BUILTIN = (0, 112, 140)
SYN_STR = (150, 38, 32)
SYN_COMMENT = (0, 128, 0)
SYN_NUMBER = (140, 60, 160)
SYN_DEF = (120, 70, 0)
SYN_SELF = (90, 60, 150)
SYN_OP = (70, 70, 70)
SYN_DECORATOR = (150, 100, 0)

# media player
WAVE_FG = (92, 68, 136)
WAVE_BG = (251, 250, 244)
WAVE_PLAYED = (92, 64, 140)
WAVE_REST = (186, 180, 200)
WAVE_AXIS = (196, 192, 182)
TRACK_BG = (206, 202, 190)
TRACK_FILL = (60, 110, 190)

MODEL_ROW_BG = (241, 239, 231)

_MENU_LABELS = ("File", "Edit", "View", "Project", "Help")


def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


_lerp = lerp_color


def gradient_v(surf, rect, top, bottom):
    """Fill rect with a smooth vertical gradient."""
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    for i in range(rect.height):
        t = i / max(1, rect.height - 1)
        pygame.draw.line(surf, _lerp(top, bottom, t),
                         (rect.x, rect.y + i), (rect.right - 1, rect.y + i))


def bevel(surf, rect, light=None, dark=None, sunken=False, width=1):
    """Classic Win32 3D edge. sunken flips the light/shadow sides."""
    light = HILITE if light is None else light
    dark = SHADOW if dark is None else dark
    x, y, w, h = rect
    a, b = (dark, light) if sunken else (light, dark)
    for k in range(width):
        pygame.draw.line(surf, a, (x + k, y + k), (x + w - 1 - k, y + k))
        pygame.draw.line(surf, a, (x + k, y + k), (x + k, y + h - 1 - k))
        pygame.draw.line(surf, b, (x + w - 1 - k, y + k),
                         (x + w - 1 - k, y + h - 1 - k))
        pygame.draw.line(surf, b, (x + k, y + h - 1 - k),
                         (x + w - 1 - k, y + h - 1 - k))


def raised(surf, rect):
    bevel(surf, rect.inflate(-2, -2), HILITE, DK_SHADOW, sunken=False)
    pygame.draw.rect(surf, DK_SHADOW, rect, 1)


def sunken(surf, rect):
    pygame.draw.rect(surf, DK_SHADOW, rect, 1)
    bevel(surf, rect.inflate(-2, -2), SHADOW, HILITE, sunken=True)


def field(surf, rect, bg=None):
    """A sunken white input/list field, the XP text-box look."""
    pygame.draw.rect(surf, FIELD if bg is None else bg, rect)
    sunken(surf, rect)


def button(surf, rect, label, font, default=False, hovered=False,
           pressed=False, enabled=True, icon=None, gap=6):
    """Draw a Luna push button; returns the rect."""
    interior = rect.inflate(-2, -2)
    if pressed and enabled:
        surf.fill(BTN_PRESSED, rect)
        bevel(surf, interior, BTN_PRESSED, BTN_PRESSED)
        text_y = rect.centery + 1
    else:
        gradient_v(surf, rect, BTN_TOP, BTN_BOT)
        pygame.draw.rect(surf, BTN_BORDER, rect.inflate(2, 2), 1,
                         border_radius=3)
        pygame.draw.rect(surf, BTN_MID, rect, 1, border_radius=3)
        text_y = rect.centery
    if enabled and hovered and not pressed:
        pygame.draw.rect(surf, BTN_HOVER_BG, rect.inflate(-2, -2),
                         border_radius=3)
        pygame.draw.rect(surf, BTN_HOVER_BORDER, rect, 1, border_radius=3)
    if enabled and default:
        pygame.draw.rect(surf, BTN_DEFAULT_BORDER, rect.inflate(2, 2), 1,
                         border_radius=3)
        pygame.draw.rect(surf, BTN_BORDER, rect.inflate(4, 4), 1,
                         border_radius=3)
    color = TEXT_MUTED if not enabled else TEXT
    img = font.render(label, True, color)
    x = rect.centerx - img.get_width() // 2
    if icon is not None:
        # an icon-only button keeps no gap, landing centre
        room = gap if label else 0
        span = icon.get_width() + room + img.get_width()
        x = rect.centerx - span // 2
        surf.blit(icon, (x, rect.centery - icon.get_height() // 2))
        x += icon.get_width() + room
    surf.blit(img, (x, text_y - img.get_height() // 2))
    return rect


def checkbox(surf, pos, checked, label, font, text_color=None):
    """A sunken check box with a label; pos is vertical."""
    bx = pygame.Rect(pos[0], pos[1] - 13 // 2, 13, 13)
    surf.fill(FIELD, bx)
    sunken(surf, bx)
    if checked:
        pygame.draw.lines(surf, CHECK, False,
                          [(bx.x + 2, bx.centery),
                           (bx.x + 5, bx.bottom - 3),
                           (bx.right - 2, bx.y + 2)], 2)
    img = font.render(label, True, TEXT if text_color is None
                      else text_color)
    surf.blit(img, (bx.right + 6, pos[1] - img.get_height() // 2))
    return pygame.Rect(bx.x, bx.y, bx.width + 6 + img.get_width(),
                       max(bx.height, img.get_height()))


def combo(surf, rect, value, font, hovered=False):
    """Read-only dropdown: white field, value text, and an arrow button."""
    field(surf, rect)
    img = font.render(value, True, TEXT)
    surf.blit(img, (rect.x + 4, rect.centery - img.get_height() // 2))
    btn = pygame.Rect(rect.right - 16, rect.y + 2, 15, rect.height - 4)
    gradient_v(surf, btn, COMBO_A, COMBO_B)
    pygame.draw.rect(surf, COMBO_BORDER, btn, 1)
    if hovered:
        pygame.draw.rect(surf, BTN_HOVER_BORDER, btn, 1)
    cx, cy = btn.centerx, btn.centery
    pygame.draw.polygon(surf, COMBO_ARROW,
                        [(cx - 3, cy - 2), (cx + 3, cy - 2), (cx, cy + 2)])
    return rect


def slider(surf, rect, frac, live=False):
    """Track and grab thumb for a 0..1 value."""
    frac = max(0.0, min(1.0, float(frac)))
    trough = pygame.Rect(rect.x, rect.centery - 3, rect.width, 7)
    surf.fill(SCROLL_TROUGH, trough)
    sunken(surf, trough)
    fill = pygame.Rect(trough.x, trough.y + 1,
                       int((trough.width - 2) * frac), trough.height - 2)
    if fill.width > 0:
        pygame.draw.rect(surf, SELECTION, fill)
    size = 16 if live else 14
    x = trough.x + int((trough.width - size) * frac)
    thumb = pygame.Rect(x, rect.centery - size // 2, size, size)
    gradient_v(surf, thumb, BTN_TOP, BTN_BOT)
    pygame.draw.rect(surf, BTN_BORDER, thumb, 1)
    if live:
        pygame.draw.rect(surf, BTN_HOVER_BORDER, thumb, 1)
    for dx in (-1, 1):
        pygame.draw.line(surf, SHADOW if dx < 0 else HILITE,
                         (thumb.centerx + dx, thumb.y + 3),
                         (thumb.centerx + dx, thumb.bottom - 4))
    return thumb


def slider_frac(rect, pos):
    """The 0..1 position of a mouse point along the track."""
    span = max(1, rect.width - 14)
    return max(0.0, min(1.0, (pos[0] - rect.x - 7) / span))


def groupbox(surf, rect, label, font, text_color=None):
    """Etched frame with a caption breaking the top border."""
    pygame.draw.rect(surf, HILITE, rect.inflate(2, 2), 1)
    pygame.draw.rect(surf, SHADOW, rect, 1)
    pad = 6
    img = font.render(label, True, TEXT_MUTED if text_color is None
                      else text_color)
    surf.fill(FACE, (rect.x + pad * 2, rect.y - img.get_height() // 2,
                     img.get_width() + pad, img.get_height()))
    surf.blit(img, (rect.x + pad * 2 + pad // 2,
                    rect.y - img.get_height() // 2))
    return img


def _fit(font, text, width):
    """`text` shortened with ... until it fits `width`."""
    text = str(text)
    if font is None or width <= 0:
        return ""
    if font.size(text)[0] <= width:
        return text
    room = width - font.size("...")[0]
    cut = text
    while cut and font.size(cut)[0] > room:
        cut = cut[:-1]
    return (cut.rstrip() + "...") if cut.strip() else ""


def titlebar(surf, rect, title, font, icon=None, dialog=False):
    """Blue Luna caption with gradient, glow line and title."""
    g = rect.copy()
    gradient_v(surf, (g.x, g.y, g.w, g.h), CAP_HI, CAP_BOT)
    glow = pygame.Rect(g.x + 2, g.y + 2, g.w - 4, int(g.h * 0.55))
    gradient_v(surf, glow, CAP_TOP, CAP_MID)
    pygame.draw.rect(surf, CAP_GLOW, (g.x + 2, g.y, g.w - 4, 1))
    for corner in (g.x, g.right - 2):
        pygame.draw.line(surf, FACE, (corner, g.bottom - 1),
                         (corner, g.bottom - 1))
    x = g.x + 5
    if icon is not None:
        if icon.get_height() > g.height - 4:
            ratio = (g.height - 4) / icon.get_height()
            icon = pygame.transform.smoothscale(
                icon, (max(1, int(icon.get_width() * ratio)),
                       g.height - 4))
        surf.blit(icon, (x, g.centery - icon.get_height() // 2))
        x += icon.get_width() + 6
    else:
        x += 20
    # window buttons own the right end; long paths are cut
    buttons = 3 + (16 + 3) * (1 if dialog else 3)
    title = _fit(font, title, g.right - buttons - x - 4)
    t = font.render(title, True, CAPTION)
    shadow = font.render(title, True, CAPTION_SHADOW)
    ty = g.centery - t.get_height() // 2
    surf.blit(shadow, (x + 3, ty + 1))
    surf.blit(t, (x + 2, ty))
    size = 16
    pad = 3
    top = g.y + (g.height - size) // 2
    close = pygame.Rect(g.right - size - 3, top, size, size)
    maximize = close.move(-(size + pad), 0)
    minimize = close.move(-2 * (size + pad), 0)
    if not dialog:
        for b in (minimize, maximize):
            gradient_v(surf, b, SYS_BTN_A, SYS_BTN_B)
            pygame.draw.rect(surf, SYS_BTN_EDGE, b, 1)
        pygame.draw.rect(surf, (255, 255, 255),
                         (minimize.x + 4, minimize.bottom - 5, 7, 2))
        pygame.draw.rect(surf, (255, 255, 255),
                         (maximize.x + 3, maximize.y + 3, 9, 8), 1)
        pygame.draw.line(surf, (255, 255, 255),
                         (maximize.x + 3, maximize.y + 4),
                         (maximize.right - 4, maximize.y + 4), 2)
    gradient_v(surf, close, CLOSE_BTN_A, CLOSE_BTN_B)
    pygame.draw.rect(surf, CLOSE_BTN_EDGE, close, 1)
    pygame.draw.lines(surf, (255, 255, 255), False,
                      [(close.x + 4, close.y + 4),
                       (close.right - 4, close.bottom - 4)], 2)
    pygame.draw.lines(surf, (255, 255, 255), False,
                      [(close.right - 4, close.y + 4),
                       (close.x + 4, close.bottom - 4)], 2)
    return close


def menubar(surf, rect, active=None, font=None, labels=_MENU_LABELS,
            hover=None, pressed=None):
    """XP menu strip; `hover`/`pressed` are cell indexes, open or one-shot.

    A cell the pointer is over glows pale blue and gains a border; a cell
    being clicked sinks to its pressed face, which is what makes a click
    look like a click rather than a teleport.
    """
    surf.fill(FACE, rect)
    pygame.draw.line(surf, SHADOW, (rect.x, rect.bottom - 1),
                     (rect.right, rect.bottom - 1))
    pygame.draw.line(surf, HILITE, (rect.x, rect.bottom),
                     (rect.right, rect.bottom))
    x = rect.x + 6
    cells_out = []
    for i, lbl in enumerate(labels):
        img = font.render(lbl, True, TEXT)
        w = img.get_width() + 12
        cell = pygame.Rect(x, rect.y + 2, w, rect.height - 4)
        if active == i:
            field(surf, cell, SELECTION)
            img = font.render(lbl, True, SELECT_TEXT)
        elif pressed == i:
            field(surf, cell, BTN_PRESSED)
            bevel(surf, cell, SHADOW, HILITE, sunken=True)
        elif hover == i:
            field(surf, cell, BTN_HOVER_BG)
            pygame.draw.rect(surf, BTN_HOVER_BORDER, cell, 1)
        x += w + 2
        surf.blit(img, (cell.x + 6, cell.centery - img.get_height() // 2))
        cells_out.append(cell)
    return cells_out


def menu_items(surf, pos, items, font, hover=-1, width=170, pressed=-1):
    """XP dropdown panel. items: [(label, enabled[, icon])] where a label

    `hover` lights the row under the pointer and `pressed` sinks the one
    being clicked, so a choice answers the hand as well as the eye. Cells
    are the strip's own widths, so a caller that measures them its own way
    may hit-test the returned list instead.
    """
    rows = []
    h = 4
    for item in items:
        h += 6 if item[0] in (None, "-") else font.get_height() + 8
    panel = pygame.Rect(pos[0], pos[1], width, h)
    pygame.draw.rect(surf, DK_SHADOW, panel.inflate(2, 2), 0)
    surf.fill(FACE, panel)
    sunken(surf, panel)
    y = panel.y + 3
    for i, item in enumerate(items):
        label, enabled = item[0], item[1]
        art = item[2] if len(item) > 2 else None
        if label in (None, "-"):
            pygame.draw.line(surf, SHADOW, (panel.x + 4, y + 3),
                             (panel.right - 4, y + 3))
            y += 6
            rows.append(None)
            continue
        row = pygame.Rect(panel.x + 2, y, panel.w - 4, font.get_height() + 8)
        lit = enabled and (i == hover or i == pressed)
        if lit:
            # a press deepens the band and lifts the label a pixel
            surf.fill(PRESS_SELECTION if i == pressed else SELECTION, row)
        color = TEXT if enabled else TEXT_MUTED
        if lit:
            color = SELECT_TEXT
        if art is not None:
            # the 18 px gutter is the icon column; rows align
            surf.blit(art, (row.x + 2, row.centery - art.get_height() // 2))
        surf.blit(font.render(label, True, color),
                  (row.x + 18, row.centery - font.get_height() // 2 -
                   (1 if i == pressed else 0)))
        y = row.bottom
        rows.append(row)
    return panel, rows


def statusbar(surf, rect, panels, font):
    """Bottom grip bar with sunken text panels, widths shared out."""
    surf.fill(FACE, rect)
    pygame.draw.line(surf, HILITE, (rect.x, rect.y), (rect.right, rect.y))
    pygame.draw.line(surf, SHADOW, (rect.x, rect.y + 1),
                     (rect.right, rect.y + 1))
    n = max(1, len(panels))
    usable = max(40, rect.width - 26 - (n - 1) * 3)
    if n == 1:
        widths = [usable]
    else:
        first = int(usable * 0.40)
        last = int(usable * 0.34)
        share = max(30, (usable - first - last) // max(1, n - 2))
        widths = [first] + [share] * (n - 2) + [max(30, usable - first -
                                                    share * (n - 2))]
    x = rect.x + 3
    for i, text in enumerate(panels):
        panel = pygame.Rect(x, rect.y + 3, widths[i], rect.height - 6)
        bevel(surf, panel, SHADOW, HILITE, sunken=True)
        img = font.render(text, True, TEXT)
        old = surf.get_clip()
        surf.set_clip(panel.inflate(-6, 0))
        surf.blit(img, (panel.x + 4, panel.centery - img.get_height() // 2))
        surf.set_clip(old)
        x = panel.right + 3
    for r in range(3):
        for c in range(3):
            if r + c >= 2:
                p = (rect.right - 4 - c * 4, rect.bottom - 4 - r * 4)
                pygame.draw.line(surf, HILITE, p, p)
                pygame.draw.line(surf, SHADOW, (p[0] + 1, p[1]),
                                 (p[0] + 1, p[1]))


def tooltip(surf, pos, lines, font):
    """A tool tip: pale yellow bubble, hairline black border."""
    imgs = [font.render(line, True, TOOLTIP_TEXT) for line in lines]
    w = max([i.get_width() for i in imgs] or [0]) + 8
    h = sum(i.get_height() + 1 for i in imgs) + 6
    box = pygame.Rect(pos[0] + 12, pos[1] + 18, w, h)
    area = surf.get_rect()
    if box.right > area.right - 2:
        box.x = area.right - 2 - w
    if box.bottom > area.bottom - 2:
        box.y = max(2, pos[1] - h - 8)
    surf.fill(TOOLTIP_BG, box)
    pygame.draw.rect(surf, TOOLTIP_BORDER, box, 1)
    y = box.y + 3
    for img in imgs:
        surf.blit(img, (box.x + 4, y))
        y += img.get_height() + 1
    return box


def message_frame(surf, rect, title, font, icon=None):
    """A modal dialog window: caption + face body."""
    pygame.draw.rect(surf, DK_SHADOW, rect.inflate(2, 2), 1)
    surf.fill(FACE, rect)
    cap = pygame.Rect(rect.x + 2, rect.y + 2, rect.w - 4, 24)
    close = titlebar(surf, cap, title, font, icon=icon, dialog=True)
    body = pygame.Rect(rect.x + 2, cap.bottom, rect.w - 4,
                       rect.bottom - cap.bottom - 2)
    surf.fill(FACE, body)
    return body, close


def tabs(surf, rect, labels, active, font, hover=-1, icons=None,
         marks=None, icon_gap=5):
    """XP property-sheet tabs along the top edge. Returns tab rects."""
    surf.fill(FACE, rect)
    pygame.draw.line(surf, SHADOW, (rect.x, rect.bottom - 1),
                     (rect.right, rect.bottom - 1))
    old = surf.get_clip()
    surf.set_clip(rect)
    out = []
    x = rect.x + 4
    # reserve badge width on every tab, dirty or not
    res = max([m.get_width() + 3 for m in marks if m] or [0]) \
        if marks is not None else 0
    # tabs are measured first; narrow strips drop all captions
    widths = []
    for i, label in enumerate(labels):
        art = icons[i] if icons is not None and i < len(icons) else None
        room = art.get_width() + icon_gap if art is not None else 0
        widths.append(font.size(label)[0] + 26 + room + res)
    total = sum(widths) + 2 * len(widths)
    spare = max(0, rect.width - 4)
    squeeze = min(1.0, spare / total) if total else 1.0
    for i, label in enumerate(labels):
        art = icons[i] if icons is not None and i < len(icons) else None
        mark = marks[i] if marks is not None and i < len(marks) else None
        room = art.get_width() + icon_gap if art is not None else 0
        w = max(30, int(widths[i] * squeeze))
        if x + w > rect.right - 2:
            w = max(0, rect.right - 2 - x)
        # the caption gives way so the tab stays clickable
        label = _fit(font, label, max(6, w - 26 - room - res))
        img = font.render(label, True, TEXT)
        h = rect.height - 3
        tab = pygame.Rect(x, rect.y + 1, w, h)
        if i == active:
            tab.y = rect.y
            tab.h = rect.height
            surf.fill(FACE, tab.inflate(-1, 0))
            pygame.draw.line(surf, HILITE, (tab.x + 1, tab.y),
                             (tab.right - 2, tab.y))
            pygame.draw.line(surf, HILITE, (tab.x, tab.y + 1),
                             (tab.x, tab.bottom - 2))
            pygame.draw.line(surf, SHADOW, (tab.right - 1, tab.y + 1),
                             (tab.right - 1, tab.bottom - 2))
            pygame.draw.line(surf, FACE, (tab.x, tab.bottom - 1),
                             (tab.right, tab.bottom - 1))
        elif i == hover:
            gradient_v(surf, tab, TAB_HOVER_TOP, TAB_HOVER_BOT)
            pygame.draw.rect(surf, SHADOW, tab, 1)
        color = TEXT if i == active else TEXT_MUTED
        # the caption group is centred left of the badge
        group = img.get_width() + room
        tx = tab.x + (tab.width - res - group) // 2
        if art is not None:
            surf.blit(art, (tx, tab.centery - art.get_height() // 2))
            tx += art.get_width() + icon_gap
        surf.blit(font.render(label, True, color),
                  (tx, tab.centery - img.get_height() // 2))
        if mark is not None:
            surf.blit(mark, (tab.right - mark.get_width() - 2, tab.y + 2))
        out.append(tab)
        x += w + 2
    surf.set_clip(old)
    return out


def scrollbar(surf, rect, frac, page, vertical=True):
    """Sunken trough with a raised thumb; frac is 0..1."""
    field(surf, rect, SCROLL_TROUGH)
    if vertical:
        track = rect.inflate(-2, -2)
        th = max(18, int(track.height * min(1.0, max(page, 0.05))))
        ty = track.y + int((track.height - th) * min(max(frac, 0.0), 1.0))
        thumb = pygame.Rect(track.x, ty, track.width, th)
    else:
        track = rect.inflate(-2, -2)
        tw = max(18, int(track.width * min(1.0, max(page, 0.05))))
        tx = track.x + int((track.width - tw) * min(max(frac, 0.0), 1.0))
        thumb = pygame.Rect(tx, track.y, tw, track.height)
    gradient_v(surf, thumb, SCROLL_TOP, SCROLL_BOT)
    pygame.draw.rect(surf, BTN_BORDER, thumb, 1)
    return thumb
