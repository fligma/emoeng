"""Colour parsing: one place that decides what a colour is."""

import re

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_FUNC = re.compile(r"^rgba?\s*\(\s*([^)]*)\)\s*$", re.IGNORECASE)

# handy words for `color=` arguments; deliberately not texture keys
NAMED = {
    "white": (255, 255, 255), "black": (0, 0, 0),
    "grey": (128, 128, 128), "gray": (128, 128, 128),
    "red": (220, 60, 50), "green": (70, 190, 90), "blue": (60, 122, 214),
    "yellow": (235, 205, 60), "orange": (235, 140, 50),
    "purple": (150, 80, 190), "cyan": (70, 200, 210), "brown": (130, 90, 60),
    "stone": (150, 148, 142), "rust": (148, 78, 44), "steel": (110, 128, 146),
    "sand": (214, 190, 140), "grass": (96, 150, 76), "blood": (122, 22, 24),
    "gold": (226, 180, 80), "torch": (255, 170, 70), "flame": (255, 130, 40),
    "night": (26, 30, 46), "fog": (150, 156, 170), "shadow": (16, 18, 26),
}


def _channel(value):
    """One channel in any scale, as a float 0..1."""
    v = float(value)
    if v > 1.0:
        v /= 255.0
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _from_channels(parts):
    """Grey, rgb or rgba in any scale as 0..1 floats."""
    got = [_channel(p) for p in parts]
    if len(got) == 1:
        got = [got[0], got[0], got[0], 1.0]
    elif len(got) == 3:
        got.append(1.0)
    elif len(got) != 4:
        return None
    return tuple(got)


def rgba(value, default=None):
    """Parse any colour spelling into rgba floats 0..1."""
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        m = _HEX.match(text)
        if m:
            digits = m.group(1)
            if len(digits) == 3:                     # "#abc" -> "aabbcc"
                digits = "".join(c * 2 for c in digits)
            parts = [int(digits[i:i + 2], 16)
                     for i in range(0, len(digits), 2)]
            return _from_channels(parts) or default
        m = _FUNC.match(text)
        if m:
            parts = [p for p in m.group(1).replace(";", ",").split(",")
                     if p.strip() != ""]
            if parts:
                try:
                    return _from_channels(parts) or default
                except ValueError:
                    return default
        return _named(text) or default
    if isinstance(value, (int, float)):
        return _from_channels([value]) or default
    try:
        parts = list(value)
    except TypeError:
        return default
    if not parts or len(parts) > 4:
        return default
    try:
        return _from_channels(parts) or default
    except (TypeError, ValueError):
        return default


def _named(text):
    """A bare colour word, or None."""
    found = NAMED.get(str(text).strip().lower())
    return _from_channels(list(found)) if found else None


def rgb(value, default=None):
    """Like `rgba()` but without the alpha."""
    got = rgba(value, default)
    return None if got is None else got[:3]


def is_color(value):
    """True when `value` reads as a colour at all."""
    return rgba(value) is not None


def is_spelling(value):
    """True when `value` spells a colour outright, without naming it."""
    if isinstance(value, str):
        text = value.strip()
        return bool(text[:1] == "#" or _FUNC.match(text))
    return rgba(value) is not None


def key(value):
    """The texture key for `value`: a colour becomes "#rrggbb[aa]"."""
    if isinstance(value, str):
        text = value.strip()
        if not (text.startswith("#") or _FUNC.match(text)):
            return value
    got = rgba(value)
    if got is None:
        return value
    out = "#" + "".join("{0:02x}".format(round(c * 255)) for c in got[:3])
    return out if got[3] >= 0.999 else out + \
        "{0:02x}".format(round(got[3] * 255))


def text(value, default="#ffffff"):
    """A colour as the hex string an inspector shows."""
    got = rgba(value)
    return ("#" + "".join("{0:02x}".format(round(c * 255)) for c in got[:3])
            if got is not None else str(default))


def mix(a, b, t=0.5):
    """Linear blend of two colours at `t`."""
    ca = rgba(a, (0.0, 0.0, 0.0, 1.0))
    cb = rgba(b, (0.0, 0.0, 0.0, 1.0))
    k = max(0.0, min(1.0, float(t)))
    return tuple(ca[i] + (cb[i] - ca[i]) * k for i in range(4))


def scaled(value, factor):
    """Brighten or dim a colour, keeping its alpha."""
    got = rgba(value, (0.0, 0.0, 0.0, 1.0))
    k = float(factor)
    return (got[0] * k, got[1] * k, got[2] * k, got[3])


def gray(value):
    """A colour as luminance grey, for ramps."""
    r, g, b, a = rgba(value, (0.0, 0.0, 0.0, 1.0))
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return (lum, lum, lum, a)


def bytes_rgb(value):
    """The colour as 0..255 integers."""
    return tuple(round(c * 255) for c in rgba(value, (0, 0, 0, 1)))
