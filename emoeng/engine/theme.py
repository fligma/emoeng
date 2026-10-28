"""Editor and runtime palettes, plus the saved theme preference."""

from . import config, xp

DEFAULT = "dark"
NAMES = ("dark", "light")

# Light base: the legacy Luna palette
LIGHT = {
    "FACE": (236, 233, 216),
    "HILITE": (255, 255, 255),
    "SHADOW": (170, 166, 150),
    "DK_SHADOW": (120, 116, 100),
    "FIELD": (255, 255, 255),
    "FIELD_ALT": (247, 246, 240),
    "CAP_TOP": (38, 120, 222),
    "CAP_HI": (18, 92, 205),
    "CAP_MID": (10, 74, 180),
    "CAP_BOT": (8, 58, 148),
    "CAP_GLOW": (150, 198, 255),
    "TEXT": (16, 16, 16),
    "TEXT_MUTED": (110, 110, 100),
    "CAPTION": (255, 255, 255),
    "BTN_TOP": (255, 255, 255),
    "BTN_MID": (240, 240, 232),
    "BTN_BOT": (214, 217, 199),
    "BTN_BORDER": (121, 121, 110),
    "BTN_HOVER_BORDER": (60, 135, 205),
    "BTN_HOVER_BG": (229, 241, 253),
    "BTN_DEFAULT_BORDER": (228, 195, 101),
    "BTN_PRESSED": (198, 204, 180),
    "SELECTION": (49, 106, 197),
    "COMBO_A": (255, 255, 255),
    "COMBO_B": (218, 206, 150),
    "COMBO_BORDER": (142, 135, 110),
    "SYS_BTN_A": (80, 160, 255),
    "SYS_BTN_B": (10, 90, 200),
    "CLOSE_BTN_A": (240, 130, 100),
    "CLOSE_BTN_B": (200, 40, 30),
    "CLOSE_BTN_EDGE": (255, 210, 200),
    "PANEL": (247, 246, 240),
    "OUTLINE": (128, 124, 108),
    "LINK": (20, 50, 100),
    "SELECT_BORDER": (60, 120, 200),
    "SELECT_TEXT": (255, 255, 255),
    "SELECT_SUBTEXT": (226, 236, 250),
    "THUMB_BG": (248, 246, 238),
    "THUMB_LINE": (196, 192, 182),
    "CARD_BG": (247, 246, 240),
    "LOG_BG": (252, 252, 250),
    "LOG_INFO": (58, 58, 54),
    "LOG_OK": (24, 110, 52),
    "LOG_WARN": (150, 96, 10),
    "LOG_ERROR": (170, 36, 30),
    "LOG_MUTED": (120, 118, 108),
    "SCROLL_TROUGH": (238, 236, 226),
    "SCROLL_TOP": (255, 255, 255),
    "SCROLL_BOT": (214, 214, 200),
    "TAB_HOVER_TOP": (246, 245, 236),
    "TAB_HOVER_BOT": (224, 221, 205),
    "CAPTION_SHADOW": (10, 40, 90),
    "SYS_BTN_EDGE": (200, 225, 255),
    "COMBO_ARROW": (40, 40, 40),
    "CHECK": (20, 90, 30),
    "TOOLTIP_BG": (255, 255, 225),
    "TOOLTIP_BORDER": (0, 0, 0),
    "TOOLTIP_TEXT": (0, 0, 0),
    "CODE_TEXT": (24, 24, 24),
    "CODE_SELECT": (205, 222, 246),
    "CODE_CURRENT": (246, 249, 255),
    "GUTTER_BG": (238, 236, 226),
    "GUTTER_TEXT": (120, 120, 112),
    "GUTTER_LINE": (200, 198, 188),
    "CARET": (20, 20, 20),
    "MODIFIED": (190, 80, 40),
    "SYN_KW": (0, 0, 168),
    "SYN_BUILTIN": (0, 112, 140),
    "SYN_STR": (150, 38, 32),
    "SYN_COMMENT": (0, 128, 0),
    "SYN_NUMBER": (140, 60, 160),
    "SYN_DEF": (120, 70, 0),
    "SYN_SELF": (90, 60, 150),
    "SYN_OP": (70, 70, 70),
    "SYN_DECORATOR": (150, 100, 0),
    "WAVE_FG": (92, 68, 136),
    "WAVE_BG": (251, 250, 244),
    "WAVE_PLAYED": (92, 64, 140),
    "WAVE_REST": (186, 180, 200),
    "WAVE_AXIS": (196, 192, 182),
    "TRACK_BG": (206, 202, 190),
    "TRACK_FILL": (60, 110, 190),
    "MODEL_ROW_BG": (241, 239, 231),
}

# Dark: slate panels, navy chrome, cool syntax colours.
DARK = {
    "FACE": (44, 46, 51),
    "HILITE": (74, 78, 86),
    "SHADOW": (30, 31, 35),
    "DK_SHADOW": (15, 16, 19),
    "FIELD": (31, 33, 37),
    "FIELD_ALT": (36, 38, 43),
    "CAP_TOP": (64, 100, 164),
    "CAP_HI": (48, 80, 138),
    "CAP_MID": (36, 60, 106),
    "CAP_BOT": (24, 42, 76),
    "CAP_GLOW": (96, 144, 210),
    "TEXT": (226, 228, 233),
    "TEXT_MUTED": (148, 152, 161),
    "CAPTION": (255, 255, 255),
    "BTN_TOP": (68, 71, 78),
    "BTN_MID": (58, 61, 67),
    "BTN_BOT": (46, 48, 53),
    "BTN_BORDER": (21, 22, 25),
    "BTN_HOVER_BORDER": (86, 146, 214),
    "BTN_HOVER_BG": (56, 72, 94),
    "BTN_DEFAULT_BORDER": (214, 176, 80),
    "BTN_PRESSED": (38, 40, 45),
    "SELECTION": (44, 86, 152),
    "COMBO_A": (72, 75, 82),
    "COMBO_B": (52, 55, 61),
    "COMBO_BORDER": (23, 24, 27),
    "SYS_BTN_A": (74, 116, 178),
    "SYS_BTN_B": (38, 66, 116),
    "CLOSE_BTN_A": (198, 104, 84),
    "CLOSE_BTN_B": (158, 42, 32),
    "CLOSE_BTN_EDGE": (255, 196, 184),
    "PANEL": (34, 36, 40),
    "OUTLINE": (14, 15, 18),
    "LINK": (122, 182, 255),
    "SELECT_BORDER": (92, 150, 228),
    "SELECT_TEXT": (255, 255, 255),
    "SELECT_SUBTEXT": (196, 214, 238),
    "THUMB_BG": (43, 45, 50),
    "THUMB_LINE": (72, 76, 84),
    "CARD_BG": (38, 40, 45),
    "LOG_BG": (29, 31, 35),
    "LOG_INFO": (206, 209, 214),
    "LOG_OK": (120, 206, 148),
    "LOG_WARN": (232, 188, 104),
    "LOG_ERROR": (240, 122, 110),
    "LOG_MUTED": (140, 144, 152),
    "SCROLL_TROUGH": (29, 31, 35),
    "SCROLL_TOP": (86, 90, 98),
    "SCROLL_BOT": (54, 57, 63),
    "TAB_HOVER_TOP": (56, 59, 66),
    "TAB_HOVER_BOT": (44, 46, 52),
    "CAPTION_SHADOW": (8, 14, 26),
    "SYS_BTN_EDGE": (150, 180, 220),
    "COMBO_ARROW": (214, 218, 224),
    "CHECK": (122, 214, 150),
    "TOOLTIP_BG": (56, 52, 34),
    "TOOLTIP_BORDER": (120, 112, 72),
    "TOOLTIP_TEXT": (238, 232, 200),
    "CODE_TEXT": (216, 220, 226),
    "CODE_SELECT": (46, 68, 104),
    "CODE_CURRENT": (39, 42, 48),
    "GUTTER_BG": (36, 38, 43),
    "GUTTER_TEXT": (122, 128, 138),
    "GUTTER_LINE": (26, 27, 30),
    "CARET": (226, 230, 236),
    "MODIFIED": (238, 128, 70),
    "SYN_KW": (120, 158, 240),
    "SYN_BUILTIN": (96, 200, 215),
    "SYN_STR": (226, 140, 120),
    "SYN_COMMENT": (118, 160, 118),
    "SYN_NUMBER": (200, 150, 235),
    "SYN_DEF": (230, 190, 110),
    "SYN_SELF": (190, 150, 240),
    "SYN_OP": (190, 194, 204),
    "SYN_DECORATOR": (226, 180, 90),
    "WAVE_FG": (124, 166, 240),
    "WAVE_BG": (34, 36, 40),
    "WAVE_PLAYED": (130, 176, 250),
    "WAVE_REST": (88, 94, 108),
    "WAVE_AXIS": (66, 70, 78),
    "TRACK_BG": (56, 59, 65),
    "TRACK_FILL": (74, 142, 222),
    "MODEL_ROW_BG": (40, 42, 47),
}

_PALETTES = {"dark": DARK, "light": LIGHT}
_state = {"name": None}


def available():
    return NAMES


def current():
    return _state["name"] or DEFAULT


def apply(name=None):
    """Install a palette into xp; unknown names go dark."""
    name = str(name or DEFAULT).lower()
    if name not in _PALETTES:
        name = DEFAULT
    palette = dict(LIGHT)
    palette.update(_PALETTES[name])
    for key, value in palette.items():
        setattr(xp, key, value)
    _state["name"] = name
    return name


def toggle():
    """Swap dark <-> light, persist, and return the new name."""
    name = "light" if current() == "dark" else "dark"
    apply(name)
    save(name)
    return name


# values live in the config store; these keep `load()`/`save()`
def load():
    """The configured theme name, or DEFAULT when nothing readable exists."""
    name = str(config.get("editor.theme", DEFAULT)).lower()
    return name if name in _PALETTES else DEFAULT


def save(name=None):
    """Persist the theme through config and return the file written."""
    if name is not None:
        _state["name"] = str(name).lower()
    config.set("editor.theme", current())
    return config.save()
