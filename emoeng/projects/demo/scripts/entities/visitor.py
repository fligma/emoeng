"""Visitor: the pair of eyes the floor is walked with.

The document is `entities/visitor.ent3d`, so the Project View files this
player with the other things that are scripted rather than placed.
"""

import emoeng as fe


class Visitor(fe.Player3D):
    name = "visitor"
    move_speed = (3.4, 6.0)
    eye_height = 1.72
    world_radius = 26.0           # the floor ends well before the fog does
