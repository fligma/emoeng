"""Entity3D: an NPC/enemy with AI, health, and hitboxes.

Scene side:

    from scripts.objects.enemy import Enemy
    self.spawn(Enemy, pos=(0.0, 0.0, 0.0), ai_type="aggro")

The entity has built-in AI types:
- "none": no AI, just sits there
- "follow": follows a target (player or another entity)
- "patrol": patrols between waypoints (set in ai_config)
- "wander": wanders randomly
- "aggro": chases and attacks the player when in range

Health and damage:
- health/max_health: current and maximum health
- take_damage(amount, source): apply damage
- heal(amount): restore health
- on_hit(source): called when damaged
- on_death(source): called when killed

Hitbox:
- hitbox_shape: "box", "sphere", or "capsule"
- hitbox_half: half-extents for box (x, y, z)
- hitbox_radius/hitbox_height: for sphere/capsule

Advanced:
- team: "player", "enemy", "neutral", "friendly"
- aggro_range/deaggro_range: when to chase/lose interest
- attack_range/attack_damage/attack_cooldown: combat settings
"""

import math
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

    def on_hit(self, source):
        # Flash red when hit
        pass

    def on_death(self, source):
        # Drop loot, play death effect, etc.
        pass
