"""2D HUD drawing: text, panels and bars."""

import pygame

from . import paths

DEFAULT_TEXT = (236, 236, 230)
SHADOW = (8, 8, 10)

_CACHE = {}
_CACHE_MAX = 512          # one entry per distinct line/colour/size

# the faces the engine ships, by name, plus system fallbacks
_BUNDLED = {"tahoma": ("tahoma.ttf",),
            "consolas": ("consola.ttf", "consolas.ttf")}
_LOCAL = {
    "tahoma": "tahoma,segoe ui,dejavusans,liberationsans,arial",
    "consolas": "consolas,dejavusansmono,liberationmono,courier new",
}
_FONTS = {}
_INITED = False


def bundled_font_file(name):
    """The TTF this build ships for a face, or None."""
    folder = paths.bundled_fonts()
    for cand in _BUNDLED.get(str(name).lower(), (f"{name}.ttf",)):
        path = folder / cand
        if path.is_file():
            return path
    return None


def font_names():
    """Every face a document may name: aliases, then files."""
    out = list(_BUNDLED)
    try:
        out += [p.stem.lower() for p in sorted(paths.bundled_fonts().iterdir())
                if p.suffix.lower() in (".ttf", ".otf")]
    except OSError:
        pass
    return tuple(dict.fromkeys(out))


def load_font(name, size, bold=False, italic=False):
    """A pygame font by face: shipped file, then the system's."""
    global _INITED
    size = max(1, int(size))
    key = (str(name), size, bool(bold), bool(italic))
    got = _FONTS.get(key)
    if got is not None:
        return got
    if not _INITED:
        pygame.font.init()
        _INITED = True
    font = None
    path = bundled_font_file(name)
    if path is not None:
        try:
            font = pygame.font.Font(str(path), size)
        except (pygame.error, OSError):
            font = None
    if font is None:
        face = _LOCAL.get(str(name).lower(), str(name))
        try:
            font = pygame.font.SysFont(face, size, bold=bold, italic=italic)
        except (pygame.error, OSError):
            font = None
    if font is None:
        try:
            font = pygame.font.Font(None, size)
        except (pygame.error, OSError):
            return None
    if bold or italic:
        font.set_bold(bold)
        font.set_italic(italic)
    _FONTS[key] = font
    return font


def clear_fonts():
    """Drop the cached faces; a font-size change rebuilds them."""
    _FONTS.clear()


def _raster(font, s, color):
    """A rendered line, kept between frames."""
    if isinstance(color, list):
        color = tuple(color)
    key = (font, s, color)
    img = _CACHE.get(key)
    if img is None:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        img = font.render(s, True, color)
        _CACHE[key] = img
    return img


def clear_cache():
    """Forget every rasterised line (theme change, font reload)."""
    _CACHE.clear()


def text(surf, font, s, pos, color=DEFAULT_TEXT, shadow=SHADOW,
         align="left", alpha=255):
    """Blit one line; align is left / centre / right."""
    s = str(s)
    img = _raster(font, s, color)
    x, y = pos
    if align == "centre":
        x -= img.get_width() // 2
    elif align == "right":
        x -= img.get_width()
    if shadow is not None:
        surf.blit(_raster(font, s, shadow), (x + 1, y + 1))
    if alpha < 255:
        # the cached image is shared: fade, then restore
        img.set_alpha(alpha)
        surf.blit(img, (x, y))
        img.set_alpha(255)
    else:
        surf.blit(img, (x, y))
    return img.get_rect(topleft=(x, y))


def panel(surf, rect, color=(10, 10, 14), alpha=150, border=None):
    """Translucent HUD backing panel."""
    rect = pygame.Rect(rect)
    ov = pygame.Surface(rect.size, pygame.SRCALPHA)
    ov.fill((color[0], color[1], color[2], alpha))
    surf.blit(ov, rect.topleft)
    if border is not None:
        pygame.draw.rect(surf, border, rect, 1)
    return rect


def bar(surf, rect, frac, fill=(190, 50, 45), back=(30, 26, 28),
        border=(220, 216, 200)):
    """Simple value bar; frac 0..1 is clamped."""
    rect = pygame.Rect(rect)
    frac = max(0.0, min(1.0, float(frac)))
    pygame.draw.rect(surf, back, rect)
    inner = rect.inflate(-2, -2)
    if inner.width > 0 and frac > 0.0:
        pygame.draw.rect(surf, fill, (inner.x, inner.y,
                                      int(inner.width * frac), inner.height))
    pygame.draw.rect(surf, border, rect, 1)
    return rect


def crosshair(surf, centre, size=10, gap=3, color=(245, 240, 230), thick=1):
    x, y = int(centre[0]), int(centre[1])
    for dx in (-1, 1):
        pygame.draw.line(surf, color,
                         (x + dx * gap, y), (x + dx * size, y), thick)
    for dy in (-1, 1):
        pygame.draw.line(surf, color,
                         (x, y + dy * gap), (x, y + dy * size), thick)


def prompt(surf, font, key, label, centre, color=(255, 245, 210)):
    """'[E] pick up' style prompt: keycap plus text, centred."""
    key_img = _raster(font, str(key), (20, 20, 20))
    cap = pygame.Rect(0, 0, key_img.get_width() + 10, key_img.get_height() + 4)
    label_img = _raster(font, str(label), color)
    total = cap.width + 6 + label_img.get_width()
    cap.topleft = (int(centre[0] - total / 2), int(centre[1] - cap.height / 2))
    pygame.draw.rect(surf, (228, 224, 206), cap, border_radius=3)
    pygame.draw.rect(surf, (40, 40, 40), cap, 1, border_radius=3)
    surf.blit(key_img, (cap.x + 5, cap.centery - key_img.get_height() // 2))
    surf.blit(label_img, (cap.right + 6,
                          cap.centery - label_img.get_height() // 2))
    return pygame.Rect(cap.x, cap.y, total, cap.height)


def hints(surf, font, pairs, pos, color=(210, 206, 190)):
    """A stack of 'key  action' lines, e.g. at the bottom-left."""
    x, y = pos
    for key, label in pairs:
        key_img = _raster(font, str(key), (240, 236, 220))
        pygame.draw.rect(surf, (30, 30, 36), (x - 2, y - 1,
                                              key_img.get_width() + 4,
                                              key_img.get_height() + 2))
        surf.blit(key_img, (x, y))
        text(surf, font, label, (x + key_img.get_width() + 8, y), color)
        y += font.get_height() + 2


def menu(surf, font, options, selected, pos, width=240,
         accent=(70, 140, 220)):
    """Vertical option list with a highlighted row. Returns rects."""
    rows = []
    x, y = pos
    h = font.get_height() + 10
    for i, label in enumerate(options):
        row = pygame.Rect(x, y, width, h)
        if i == selected:
            panel(surf, row, accent, 190)
        text(surf, font, label, (x + 10, row.centery - font.get_height() // 2))
        rows.append(row)
        y += h
    return rows


def subtitle(surf, font, lines, bottom, color=(238, 234, 220)):
    """Centred subtitles sitting above the bottom edge."""
    if isinstance(lines, str):
        lines = [lines]
    y = bottom - len(lines) * (font.get_height() + 2)
    for line in lines:
        img = _raster(font, str(line), color)
        x = surf.get_width() // 2 - img.get_width() // 2
        panel(surf, (x - 6, y - 2, img.get_width() + 12,
                     img.get_height() + 4), (0, 0, 0), 130)
        surf.blit(img, (x, y))
        y += img.get_height() + 2


def dim(surf, amount=0.55):
    """Darken the whole frame for pause screens."""
    ov = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    ov.fill((0, 0, 0, int(255 * max(0.0, min(1.0, amount)))))
    surf.blit(ov, (0, 0))


def keycap(surf, font, key, pos, size=None):
    """Standalone XP-ish keycap, useful for tutorials."""
    img = _raster(font, str(key), (24, 24, 24))
    rect = pygame.Rect(pos[0], pos[1], img.get_width() + 12,
                       img.get_height() + 6)
    pygame.draw.rect(surf, (238, 234, 218), rect, border_radius=3)
    pygame.draw.rect(surf, (60, 60, 60), rect, 1, border_radius=3)
    surf.blit(img, (rect.centerx - img.get_width() // 2,
                    rect.centery - img.get_height() // 2))
    return rect
