"""
engine/combat_manager.py
Expanded combat system with actions, resources, and status effects.
"""

import random
from typing import Optional, Dict, List
from models import Character, Ability, Item
from engine.rng import stat_roll
from engine.data_loader import get_ability, get_item
from engine.event_system import bus

class CombatState:
    def __init__(self, player: Character, enemies: List[Dict]):
        self.player = player
        self.enemies = enemies # List of enemy dicts with stats, hp, etc.
        self.turn_order = []
        self.current_turn_index = 0
        self.log = []
        self.is_over = False
        self.winner = None

    def add_log(self, message: str):
        self.log.append(message)

def calculate_damage(attacker_stat: int, defender_stat: int, base_damage: int = 10) -> int:
    # Simple D&D-ish damage: base + (stat-5) - (defender_stat-5)/2
    mod = attacker_stat - 5
    def_mod = max(0, (defender_stat - 5) // 2)
    damage = base_damage + mod - def_mod
    return max(1, damage)

def resolve_enemy_turn(state: CombatState) -> List[Dict]:
    """
    Resolves turns for all active enemies based on their archetypes.
    Archetypes: 'Aggressor', 'Defender', 'Caster', 'Trickster'
    """
    turn_results = []
    player = state.player
    
    for enemy in state.enemies:
        archetype = enemy.get("archetype", "Aggressor")
        action = {"enemy": enemy["name"], "type": "attack", "damage": 0, "message": ""}
        
        # AI Decision Logic
        if archetype == "Aggressor":
            # Pure damage focus
            damage = calculate_damage(enemy.get("STR", 10), player.current_stats.CON, base_damage=8)
            player.hp -= damage
            action["damage"] = damage
            action["message"] = f"The {enemy['name']} lunges at you, dealing {damage} damage!"
            
        elif archetype == "Defender":
            # 50% chance to guard, 50% chance to attack
            if random.random() > 0.5:
                action["type"] = "defend"
                action["message"] = f"The {enemy['name']} raises its shield, preparing for your next strike."
            else:
                damage = calculate_damage(enemy.get("STR", 8), player.current_stats.CON, base_damage=5)
                player.hp -= damage
                action["damage"] = damage
                action["message"] = f"The {enemy['name']} strikes cautiously for {damage} damage."
                
        elif archetype == "Caster":
            # Uses Conixia-style magic
            damage = calculate_damage(enemy.get("AFF", 12), player.current_stats.WIS, base_damage=12)
            player.hp -= damage
            action["type"] = "magic"
            action["damage"] = damage
            action["message"] = f"The {enemy['name']} blasts you with Conixia energy for {damage} damage!"
            
        elif archetype == "Trickster":
            # Debuff focus (simulated with a message for now)
            action["type"] = "debuff"
            action["message"] = f"The {enemy['name']} throws sand in your eyes! You feel weakened."
            # In a full system, this would apply a 'blind' status to the player
            
        turn_results.append(action)
        state.add_log(action["message"])
        
        if player.hp <= 0:
            state.is_over = True
            state.winner = "enemies"
            break
            
    return turn_results

def resolve_combat_action(state: CombatState, action_type: str, target_index: int, extra_id: Optional[str] = None) -> Dict:
    """
    Processes a single player action followed by the enemy turn.
    """
    player = state.player
    enemy = state.enemies[target_index]
    
    result = {"player_action": {"type": action_type, "success": True, "message": "", "damage": 0}, "enemy_turns": []}

    # 1. Resolve Player Action
    if action_type == "attack":
        roll = stat_roll(player.current_stats.STR, 10)
        if roll["success"]:
            damage = calculate_damage(player.current_stats.STR, enemy.get("CON", 10))
            if roll["outcome"] == "critical_success": damage *= 2
            enemy["hp"] -= damage
            result["player_action"]["damage"] = damage
            result["player_action"]["message"] = f"You hit {enemy['name']} for {damage} damage."
        else:
            result["player_action"]["success"] = False
            result["player_action"]["message"] = f"You missed the {enemy['name']}!"

    elif action_type == "ability":
        ability = get_ability(extra_id)
        if player.conixia_energy >= ability.cost:
            player.conixia_energy -= ability.cost
            damage = calculate_damage(player.current_stats.AFF, enemy.get("WIS", 10), base_damage=15)
            enemy["hp"] -= damage
            result["player_action"]["damage"] = damage
            result["player_action"]["message"] = f"You use {ability.name} for {damage} damage!"
        else:
            return {"success": False, "message": "Not enough Conixia!"}

    elif action_type == "flee":
        roll = stat_roll(player.current_stats.DEX, 12)
        if roll["success"]:
            state.is_over = True
            state.winner = "escaped"
            result["player_action"]["message"] = "Escaped!"
            return result

    # 2. Check for Enemy Death
    if enemy["hp"] <= 0:
        state.add_log(f"{enemy['name']} defeated!")
        bus.publish("enemy_killed", {"name": enemy["name"]})
        state.enemies.pop(target_index)
        if not state.enemies:
            state.is_over = True
            state.winner = "player"
            return result

    # 3. Resolve Enemy Turns (if combat not over)
    if not state.is_over:
        result["enemy_turns"] = resolve_enemy_turn(state)

    return result
