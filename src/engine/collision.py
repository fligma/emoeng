"""Swept-box collision helpers for walking around a level.

All shapes are axis-aligned in world space: a box is (centre, half-size),
which is what most low-poly PS2 rooms and crates already are. `move_slide`
resolves one axis at a time so a player slides along walls instead of
sticking to them.
"""

import math


def aabb(centre, half):
    return (tuple(float(c) for c in centre), tuple(float(h) for h in half))


def expand(box, amount):
    centre, half = box
    return (centre, tuple(h + amount for h in half))


def contains_point(box, point):
    centre, half = box
    return all(abs(point[i] - centre[i]) <= half[i] for i in range(3))


def overlap(a, b):
    ca, ha = a
    cb, hb = b
    return all(abs(ca[i] - cb[i]) <= ha[i] + hb[i] for i in range(3))


def ray_aabb(origin, direction, box):
    """Entry distance along a unit ray, or None."""
    centre, half = box
    tmin, tmax = 0.0, 1e9
    for i in range(3):
        o = origin[i] - centre[i]
        d = direction[i]
        if abs(d) < 1e-9:
            if abs(o) > half[i]:
                return None
            continue
        t1 = (-half[i] - o) / d
        t2 = (half[i] - o) / d
        if t1 > t2:
            t1, t2 = t2, t1
        tmin = max(tmin, t1)
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    return tmin


def ray_plane(origin, direction, point, normal):
    denom = sum(direction[i] * normal[i] for i in range(3))
    if abs(denom) < 1e-9:
        return None
    t = sum((point[i] - origin[i]) * normal[i] for i in range(3)) / denom
    return t if t >= 0.0 else None


def ray_sphere(origin, direction, centre, radius):
    m = [origin[i] - centre[i] for i in range(3)]
    b = sum(m[i] * direction[i] for i in range(3))
    c = sum(v * v for v in m) - radius * radius
    disc = b * b - c
    if disc < 0.0:
        return None
    t = -b - math.sqrt(disc)
    if t < 0.0:
        t = -b + math.sqrt(disc)
    return t if t >= 0.0 else None


def move_slide(pos, delta, boxes, half=(0.35, 0.9, 0.35)):
    """Move a box-shaped body, stopping at colliders per axis. Returns
    the new position and a (hit_x, hit_y, hit_z) flag tuple."""
    pos = [float(c) for c in pos]
    hits = [False, False, False]
    for axis in range(3):
        if abs(delta[axis]) < 1e-9:
            continue
        pos[axis] += delta[axis]
        test = (tuple(pos), tuple(half))
        for box in boxes:
            if overlap(test, box):
                # push back out along the movement axis
                centre = box[0]
                if delta[axis] > 0:
                    pos[axis] = centre[axis] - box[1][axis] - half[axis]
                else:
                    pos[axis] = centre[axis] + box[1][axis] + half[axis]
                hits[axis] = True
                test = (tuple(pos), tuple(half))
    return pos, tuple(hits)


def sphere_push(pos, radius, boxes):
    """Cheap depenetration for a sphere against axis-aligned boxes."""
    pos = list(pos)
    for centre, half in boxes:
        nearest = [max(centre[i] - half[i], min(pos[i], centre[i] + half[i]))
                   for i in range(3)]
        d = [pos[i] - nearest[i] for i in range(3)]
        dist = math.sqrt(sum(v * v for v in d))
        if dist < radius:
            if dist < 1e-6:
                pos[1] = centre[1] + half[1] + radius
                continue
            push = (radius - dist)
            for i in range(3):
                pos[i] += d[i] / dist * push
    return pos


def ground_clamp(pos, height_fn, eye_height):
    """Keep a walking camera gliding over terrain."""
    y = height_fn(pos[0], pos[2]) + eye_height
    return [pos[0], y, pos[2]]
