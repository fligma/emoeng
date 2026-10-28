"""Enemy: an aggro Entity3D that chases and attacks the player.

Scene side:

    from scripts.entities.enemy import Enemy
    self.spawn(Enemy, pos=(0.0, 0.0, -5.0))

Demonstrates the Entity3D base class with aggro AI, health, and hitbox.
"""

import emoeng as fe
from emoeng.engine import meshes


class Enemy(fe.Entity3D):
    name = "enemy"
    health = 100.0
    max_health = 100.0
    ai_type = "aggro"
    ai_config = {}
    hitbox_shape = "box"
    hitbox_half = (0.5, 1.0, 0.5)
    team = "enemy"
    aggro_range = 15.0
    deaggro_range = 30.0
    attack_range = 2.0
    attack_damage = 15.0
    attack_cooldown = 1.5
    move_speed = (3.0, 8.0)

    def build(self):
        # A simple box body
        self.add(meshes.box(centre=(0, 1, 0), size=(1.0, 2.0, 1.0),
                            col=(0.8, 0.2, 0.2)), texture="white")