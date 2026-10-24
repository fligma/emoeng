"""Windows XP "Luna" look & feel.

Palette + widget drawing primitives so the engine's editor and every game
built with it read like native XP programs: blue gradient title bars, soft
beige dialogs, beveled push buttons, sunken list fields, combo boxes and
checkboxes. Every function just blits onto a surface you pass in, so the
caller keeps full control of layout.

Copied from the app's src/xp.py so fligengine stays self-contained.
"""

import pygame

# ------------------------------------------------------------------ palette

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

# ------------------------------------------------------------------ extras
# Editor surfaces and detail colours. theme.py swaps every name in this
# module at runtime, so draw code must read them as `xp.NAME` (never import
# a colour by value).
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
           pressed=False, enabled=True):
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
    surf.blit(img, (rect.centerx - img.get_width() // 2,
                    text_y - img.get_height() // 2))
    return rect


def checkbox(surf, pos, checked, label, font, text_color=None):
    """13x13 sunken box with a check plus a label; pos is the vertical
    center shared by box and text so they never sit misaligned.
    Returns its full rect."""
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


def titlebar(surf, rect, title, font, icon=None, dialog=False):
    """Blue Luna caption with gradient, glow line and title.
    dialog=True draws only the close button, like an XP message box;
    returns the close button rect."""
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


def menubar(surf, rect, active=None, font=None, labels=_MENU_LABELS):
    surf.fill(FACE, rect)
    pygame.draw.line(surf, SHADOW, (rect.x, rect.bottom - 1),
                     (rect.right, rect.bottom - 1))
    pygame.draw.line(surf, HILITE, (rect.x, rect.bottom),
                     (rect.right, rect.bottom))
    x = rect.x + 6
    for i, lbl in enumerate(labels):
        img = font.render(lbl, True, TEXT)
        w = img.get_width() + 12
        cell = pygame.Rect(x, rect.y + 2, w, rect.height - 4)
        if active == i:
            field(surf, cell, SELECTION)
            img = font.render(lbl, True, SELECT_TEXT)
        x += w + 2
        surf.blit(img, (cell.x + 6, cell.centery - img.get_height() // 2))


def menu_items(surf, pos, items, font, hover=-1, width=170):
    """XP dropdown panel. items: [(label, enabled)] where a label of None
    or "-" draws a separator. Returns the list of clickable row rects."""
    rows = []
    h = 4
    for label, _en in items:
        h += 6 if label in (None, "-") else font.get_height() + 8
    panel = pygame.Rect(pos[0], pos[1], width, h)
    pygame.draw.rect(surf, DK_SHADOW, panel.inflate(2, 2), 0)
    surf.fill(FACE, panel)
    sunken(surf, panel)
    y = panel.y + 3
    for i, (label, enabled) in enumerate(items):
        if label in (None, "-"):
            pygame.draw.line(surf, SHADOW, (panel.x + 4, y + 3),
                             (panel.right - 4, y + 3))
            y += 6
            rows.append(None)
            continue
        row = pygame.Rect(panel.x + 2, y, panel.w - 4, font.get_height() + 8)
        if i == hover and enabled:
            surf.fill(SELECTION, row)
        color = TEXT if enabled else TEXT_MUTED
        if i == hover and enabled:
            color = SELECT_TEXT
        surf.blit(font.render(label, True, color),
                  (row.x + 18, row.centery - font.get_height() // 2))
        y = row.bottom
        rows.append(row)
    return panel, rows


def statusbar(surf, rect, panels, font):
    """Bottom grip bar with sunken text panels. Widths are shared out so
    any number of panels fits; long text is clipped to its cell."""
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
    """A classic XP tool tip: pale yellow bubble, hairline black border,
    drawn just below-right of the cursor and clamped inside the surface so
    it never hangs off a window edge. Returns the bubble rect."""
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
    """A modal dialog window: caption + face body.
    Returns (body rect, close button rect)."""
    pygame.draw.rect(surf, DK_SHADOW, rect.inflate(2, 2), 1)
    surf.fill(FACE, rect)
    cap = pygame.Rect(rect.x + 2, rect.y + 2, rect.w - 4, 24)
    close = titlebar(surf, cap, title, font, icon=icon, dialog=True)
    body = pygame.Rect(rect.x + 2, cap.bottom, rect.w - 4,
                       rect.bottom - cap.bottom - 2)
    surf.fill(FACE, body)
    return body, close


def tabs(surf, rect, labels, active, font, hover=-1):
    """XP property-sheet tabs along the top edge. Returns tab rects."""
    surf.fill(FACE, rect)
    pygame.draw.line(surf, SHADOW, (rect.x, rect.bottom - 1),
                     (rect.right, rect.bottom - 1))
    out = []
    x = rect.x + 4
    for i, label in enumerate(labels):
        img = font.render(label, True, TEXT)
        w = img.get_width() + 26
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
        surf.blit(font.render(label, True, color),
                  (tab.centerx - img.get_width() // 2,
                   tab.centery - img.get_height() // 2))
        out.append(tab)
        x += w + 2
    return out


def scrollbar(surf, rect, frac, page, vertical=True):
    """Sunken trough with a raised Luna thumb. frac is 0..1, page is the
    visible fraction. Returns the thumb rect (for dragging)."""
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
