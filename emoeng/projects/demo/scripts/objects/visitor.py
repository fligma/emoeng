"""Visitor: the pair of eyes the floor is walked with."""

import emoeng as fe


class Visitor(fe.Player3D):
    name = "visitor"
    move_speed = (3.4, 6.0)
    eye_height = 1.72
    world_radius = 26.0           # the floor ends well before the fog does
