"""Turn-based combat and Conixia ability resolution.

Combat state is JSON-serializable so it can be persisted inside a character save.
"""

from __future__ import annotations

import random
from typing import Optional

from models import Character, Ability
from engine.data_loader import get_ability, get_item
from engine.event_system import bus
from engine.rng import stat_roll
from engine.elemental import (
    ABILITY_ELEMENTS, damage_multiplier, status_for_element,
    weapon_element, normalize_element,
)


class CombatState:
    def __init__(self, player: Character, enemies: list[dict]):
        self.player = player
        self.enemies = [normalize_enemy(enemy) for enemy in enemies]
        self.turn = 1
        self.cooldowns: dict[str, int] = {}
        self.player_affinity = normalize_element(player.affinity)
        self.player_resistances = dict(player.elemental_resistances or {})
        self.player_hazard_resistances = dict(player.hazard_resistances or {})
        self.player_statuses: list[dict] = [normalize_status(buff, source="item") for buff in player.active_buffs]
        self.log: list[str] = []
        self.is_over = False
        self.winner: Optional[str] = None

    def add_log(self, message: str) -> None:
        self.log.append(message)

    def to_dict(self) -> dict:
        return {
            "turn": self.turn,
            "enemies": self.enemies,
            "cooldowns": self.cooldowns,
            "player_affinity": self.player_affinity,
            "player_resistances": self.player_resistances,
            "player_hazard_resistances": self.player_hazard_resistances,
            "player_statuses": self.player_statuses,
            "log": self.log[-30:],
            "is_over": self.is_over,
            "winner": self.winner,
        }


def normalize_enemy(enemy: dict) -> dict:
    if not enemy.get("name"):
        raise ValueError("Every enemy needs a name.")
    max_hp = max(1, int(enemy.get("max_hp", enemy.get("hp", 30))))
    normalized = {
        **enemy,
        "name": str(enemy["name"]),
        "hp": max(1, min(max_hp, int(enemy.get("hp", max_hp)))),
        "max_hp": max_hp,
        "STR": int(enemy.get("STR", 10)),
        "DEX": int(enemy.get("DEX", 10)),
        "CON": int(enemy.get("CON", 10)),
        "WIS": int(enemy.get("WIS", 10)),
        "AFF": int(enemy.get("AFF", 10)),
        "archetype": enemy.get("archetype", "Aggressor"),
        "xp": max(0, int(enemy.get("xp", max_hp // 2))),
        "statuses": list(enemy.get("statuses", [])),
        "phases": list(enemy.get("phases", [])),
        "phase_index": int(enemy.get("phase_index", 0)),
        "phase_damage_multiplier": float(enemy.get("phase_damage_multiplier", 1.0)),
        "phase_name": enemy.get("phase_name"),
        "element": normalize_element(enemy.get("element", enemy.get("affinity", "physical"))),
        "resistances": dict(enemy.get("resistances", {})),
    }
    return normalized


def calculate_damage(attacker_stat: int, defender_stat: int, base_damage: int = 10, true_damage: bool = False) -> int:
    if true_damage:
        return max(1, int(base_damage + max(0, attacker_stat - 5)))
    return max(1, int(base_damage + (attacker_stat - 5) - max(0, (defender_stat - 5) // 2)))


def elemental_damage(base_damage: int, element: str, defender_element: str | None = None, resistances: dict | None = None) -> tuple[int, float]:
    multiplier = damage_multiplier(element, defender_element, resistances)
    return max(0, int(round(base_damage * multiplier))), multiplier


def start_combat(player: Character, enemies: list[dict]) -> dict:
    if not enemies:
        raise ValueError("At least one enemy is required.")
    state = CombatState(player, enemies)
    state.add_log("Combat begins.")
    return state.to_dict()


def normalize_status(raw: dict, source: str = "ability") -> dict:
    name = raw.get("name") or raw.get("status") or raw.get("type")
    turns = raw.get("turns", raw.get("turns_remaining", raw.get("duration_turns", 1)))
    return {
        "name": name,
        "type": raw.get("type", "status"),
        "status": raw.get("status", name),
        "turns": max(1, int(turns or 1)),
        "value": int(raw.get("value", 0) or 0),
        "stat": raw.get("stat"),
        "element": raw.get("element"),
        "source": raw.get("source", source),
        "damage_per_turn": int(raw.get("damage_per_turn", 0) or 0),
    }


def _status(state: dict, name: str) -> Optional[dict]:
    return next((s for s in state.get("player_statuses", []) if s.get("name") == name), None)


def _add_status(statuses: list[dict], name: str, turns: int, value: int = 0, **extra) -> None:
    existing = next((s for s in statuses if s.get("name") == name), None)
    if existing:
        existing["turns"] = max(existing.get("turns", 0), turns)
        existing["value"] = max(existing.get("value", 0), value)
        existing.update(extra)
    else:
        statuses.append(normalize_status({"name": name, "turns": turns, "value": value, **extra}))


def _remove_status(statuses: list[dict], name: str) -> None:
    statuses[:] = [s for s in statuses if s.get("name") != name]


def _damage_player(player: Character, state: dict, amount: int, magical: bool = False, element: str = "physical") -> int:
    amount = max(0, int(amount))
    amount, _ = elemental_damage(amount, element, state.get("player_affinity"), state.get("player_resistances", {}))
    shield = _status(state, "mystic_guard") or _status(state, "earthen_wall")
    if shield:
        amount = max(0, amount // 2)
    if magical and any(a in player.known_abilities for a in ["Arcane Ward", "Mental Barrier"]):
        amount = max(0, amount // 2)
    player.hp = max(0, player.hp - amount)
    return amount


def _enemy_damage(enemy: dict, player: Character, state: dict, magical: bool = False) -> int:
    stat = enemy.get("AFF", 10) if magical else enemy.get("STR", 10)
    defender = player.current_stats.WIS if magical else player.current_stats.CON
    base = 10 if magical else 8
    element = enemy.get("element", "arcane" if magical else "physical")
    if any(s.get("name") in ("dark_shroud", "mirror_image") for s in state.get("player_statuses", [])):
        if random.random() < 0.35:
            return 0
    enemy_status_names = {s.get("name") for s in enemy.get("statuses", [])}
    if "weakened" in enemy_status_names or "chilled" in enemy_status_names:
        base = max(1, base - 2)
    if _status(state, "weakened"):
        base = max(1, base - 2)
    if "shocked" in enemy_status_names and random.random() < 0.2:
        return 0
    raw_damage = calculate_damage(stat, defender, base, true_damage=False)
    raw_damage = max(1, int(round(raw_damage * float(enemy.get("phase_damage_multiplier", 1.0)))))
    damage = _damage_player(player, state, raw_damage, magical, element)
    effect = status_for_element(element)
    if effect:
        _add_status(state.setdefault("player_statuses", []), effect["name"], effect.get("turns", 1), effect.get("value", 0), damage_per_turn=effect.get("damage_per_turn", 0), element=element, source="enemy")
    return damage


def _find_ability(player: Character, ability_name: str) -> Ability | None:
    for key, record in (player.generated_abilities or {}).items():
        if key == ability_name or record.get("name", "").lower() == ability_name.lower():
            return Ability(**record)
    return get_ability(ability_name)


def _apply_ability(player: Character, state: dict, ability_name: str, target_index: int) -> dict:
    ability = _find_ability(player, ability_name)
    if not ability:
        raise ValueError(f"Unknown ability '{ability_name}'.")
    if ability.name not in player.known_abilities:
        raise ValueError(f"You do not know {ability.name}.")
    if state.get("cooldowns", {}).get(ability.name, 0) > 0:
        raise ValueError(f"{ability.name} is on cooldown for {state['cooldowns'][ability.name]} more turn(s).")
    if player.conixia_energy < ability.cost:
        raise ValueError(f"Not enough Conixia. Need {ability.cost}, have {player.conixia_energy}.")

    enemies = state["enemies"]
    if target_index < 0 or target_index >= len(enemies):
        raise ValueError("Invalid combat target.")
    target = enemies[target_index]
    player.conixia_energy -= ability.cost
    state.setdefault("cooldowns", {})[ability.name] = ability.cooldown
    tag = ability.tag
    element = normalize_element(ability.element or ABILITY_ELEMENTS.get(ability.base_name or ability.name, player.affinity))
    affected = enemies if tag in {"area_damage", "area_control"} else [target]
    messages = []

    if tag in {"damage", "damage_debuff", "stealth_damage", "ambush", "true_damage", "area_damage"}:
        for enemy in affected:
            base = (15 if ability.type == "ultimate" else 12) + int(ability.power_bonus or 0)
            if tag in {"stealth_damage", "ambush"}:
                base += 5
            raw_damage = calculate_damage(player.current_stats.AFF, enemy.get("WIS", 10), base, tag == "true_damage")
            affinity_bonus = 1.15 if normalize_element(player.affinity) == element else 1.0
            damage, multiplier = elemental_damage(raw_damage * affinity_bonus, element, enemy.get("element"), enemy.get("resistances", {}))
            enemy["hp"] -= damage
            messages.append(f"{ability.name} [{element}] deals {damage} damage to {enemy['name']} ({multiplier:.2f}x).")
            element_status = status_for_element(element)
            if element_status:
                _add_status(enemy.setdefault("statuses", []), element_status["name"], element_status.get("turns", 1), element_status.get("value", 0), damage_per_turn=element_status.get("damage_per_turn", 0), element=element, source="ability")
            if tag == "damage_debuff":
                _add_status(enemy.setdefault("statuses", []), "weakened", 2, 2, source="ability")
    elif tag == "heal":
        amount = 12 + max(0, player.current_stats.WIS - 5)
        player.hp = min(player.max_hp, player.hp + amount)
        messages.append(f"{ability.name} restores {amount} HP.")
    elif tag == "recharge":
        amount = 12
        player.conixia_energy = min(player.max_conixia, player.conixia_energy + amount)
        messages.append(f"{ability.name} restores {amount} Conixia.")
    elif tag == "defense":
        _add_status(state.setdefault("player_statuses", []), "mystic_guard", 2, source="ability")
        if ability.hazard_resistances:
            for hazard, value in ability.hazard_resistances.items():
                state.setdefault("player_hazard_resistances", {})[hazard] = min(1.0, float(state.setdefault("player_hazard_resistances", {}).get(hazard, 0.0)) + float(value))
            _add_status(state.setdefault("player_statuses", []), "hazard_ward", 2, source="ability")
            messages.append(f"{ability.name} strengthens your resistance to environmental hazards.")
        if ability.counterplay.get("blocks_hazard_turn"):
            _add_status(state.setdefault("player_statuses", []), "hazard_block", int(ability.counterplay["blocks_hazard_turn"]), source="ability")
            messages.append(f"{ability.name} blocks the next environmental hazard tick.")
        messages.append(f"{ability.name} reduces incoming damage for 2 turns.")
    elif tag == "buff":
        if ability.name == "Elemental Channel":
            _add_status(state.setdefault("player_statuses", []), "weapon_infused", 2, source="ability", element=normalize_element(player.affinity))
            messages.append(f"{ability.name} infuses your weapon with {normalize_element(player.affinity)} energy.")
        else:
            _add_status(state.setdefault("player_statuses", []), "empowered", 2, 3, source="ability")
            messages.append(f"{ability.name} empowers your next attacks.")
    elif tag in {"control", "area_control"}:
        for enemy in affected:
            _add_status(enemy.setdefault("statuses", []), "stunned", 1)
        messages.append(f"{ability.name} controls {len(affected)} enemy(ies).")
    elif tag == "cleanse":
        cleanse_names = set(ability.counterplay.get("cleanse_statuses", ["weakened", "blinded"]))
        state["player_statuses"] = [s for s in state.get("player_statuses", []) if s.get("name") not in cleanse_names]
        messages.append(f"{ability.name} removes: {', '.join(sorted(cleanse_names))}.")
    elif tag in {"stealth", "mobility", "debuff", "decoy"}:
        _add_status(state.setdefault("player_statuses", []), tag, 2, source="ability")
        messages.append(f"{ability.name} is active.")
    else:
        messages.append(f"{ability.name} has no combat effect yet.")

    return {"ability": ability.name, "cost": ability.cost, "cooldown": ability.cooldown, "messages": messages}


def _resolve_enemy_turn(player: Character, state: dict) -> list[dict]:
    results = []
    for enemy in list(state.get("enemies", [])):
        stunned = next((s for s in enemy.get("statuses", []) if s.get("name") in {"stunned", "rooted"} and s.get("turns", 0) > 0), None)
        if stunned:
            stunned["turns"] -= 1
            results.append({"enemy": enemy["name"], "type": "stunned", "damage": 0, "message": f"{enemy['name']} loses its turn."})
            continue
        archetype = enemy.get("archetype", "Aggressor")
        if archetype == "Defender" and random.random() < 0.4:
            results.append({"enemy": enemy["name"], "type": "defend", "damage": 0, "message": f"{enemy['name']} raises its guard."})
            continue
        magical = archetype == "Caster"
        damage = _enemy_damage(enemy, player, state, magical)
        results.append({"enemy": enemy["name"], "type": "magic" if magical else "attack", "damage": damage, "message": f"{enemy['name']} deals {damage} damage."})
        if player.hp <= 0:
            state["is_over"] = True
            state["winner"] = "enemies"
            break
    return results


def _tick_effects(player: Character, state: dict) -> list[str]:
    """Resolve all end-of-turn effects, then decrement and expire them."""
    events = []
    hazard_block = next((s for s in state.get("player_statuses", []) if s.get("name") == "hazard_block" and s.get("turns", 0) > 0), None)
    for status in state.get("player_statuses", []):
        name = status.get("name")
        value = int(status.get("value", 0) or 0)
        if status.get("source") == "environment" and hazard_block:
            events.append(f"{name} is blocked by your hazard countermeasure.")
            hazard_block["turns"] = 0
            status["turns"] = max(0, int(status.get("turns", 0)) - 1)
            continue
        if name == "regen_hp":
            before = player.hp
            player.hp = min(player.max_hp, player.hp + value)
            events.append(f"Regeneration restores {player.hp - before} HP.")
        elif status.get("damage_per_turn", 0):
            damage = _damage_player(player, state, status["damage_per_turn"])
            events.append(f"{name} deals {damage} damage.")
        status["turns"] = max(0, int(status.get("turns", 0)) - 1)

    state["player_statuses"] = [s for s in state.get("player_statuses", []) if s.get("turns", 0) > 0]
    for enemy in state.get("enemies", []):
        for status in enemy.get("statuses", []):
            dot = int(status.get("damage_per_turn", 0) or 0)
            if dot:
                damage, _ = elemental_damage(dot, status.get("element", "physical"), enemy.get("element"), enemy.get("resistances", {}))
                enemy["hp"] = max(0, enemy.get("hp", 0) - damage)
                events.append(f"{enemy['name']} suffers {damage} elemental damage.")
            status["turns"] = max(0, int(status.get("turns", 0)) - 1)
        enemy["statuses"] = [s for s in enemy.get("statuses", []) if s.get("turns", 0) > 0]

    state["turn"] = state.get("turn", 1) + 1
    for name in list(state.get("cooldowns", {})):
        state["cooldowns"][name] = max(0, state["cooldowns"][name] - 1)
        if state["cooldowns"][name] == 0:
            del state["cooldowns"][name]
    return events


def resolve_combat_action(player: Character, state: dict, action_type: str, target_index: int = 0, ability_name: Optional[str] = None) -> dict:
    if state.get("is_over"):
        raise ValueError("Combat is already over.")
    enemies = state.get("enemies", [])
    if not enemies and action_type != "flee":
        raise ValueError("Combat has no remaining enemies.")
    if action_type != "flee" and (target_index < 0 or target_index >= len(enemies)):
        raise ValueError("Invalid combat target.")

    result = {"player_action": {"type": action_type, "success": True, "damage": 0, "messages": []}, "enemy_turns": [], "status_events": []}
    target = enemies[target_index] if enemies else None
    if action_type == "attack":
        roll = stat_roll(player.current_stats.STR, max(8, target.get("DEX", 10)), is_weighted=False)
        result["player_action"]["roll"] = roll
        blinded = any(s.get("name") == "blinded" for s in state.get("player_statuses", []))
        if blinded and random.random() < 0.35:
            roll["success"] = False
            roll["outcome"] = "failure"
        if roll["success"]:
            damage = calculate_damage(player.current_stats.STR, target.get("CON", 10), 10)
            if _status(state, "empowered"):
                damage += 3
            if roll["outcome"] == "critical_success":
                damage *= 2
            weapon_id = player.equipment.weapon
            weapon = get_item(weapon_id) if weapon_id else None
            element = weapon_element(weapon_id, weapon.effect if weapon else None)
            infused = _status(state, "weapon_infused")
            if infused:
                element = normalize_element(infused.get("element", player.affinity))
            damage, multiplier = elemental_damage(damage, element, target.get("element"), target.get("resistances", {}))
            target["hp"] -= damage
            result["player_action"]["damage"] = damage
            result["player_action"]["element"] = element
            result["player_action"]["multiplier"] = multiplier
            result["player_action"]["messages"].append(f"You hit {target['name']} with {element} damage for {damage} ({multiplier:.2f}x).")
            element_status = status_for_element(element)
            if element_status and element != "physical":
                _add_status(target.setdefault("statuses", []), element_status["name"], element_status.get("turns", 1), element_status.get("value", 0), damage_per_turn=element_status.get("damage_per_turn", 0), element=element, source="weapon")
        else:
            result["player_action"]["success"] = False
            result["player_action"]["messages"].append(f"You miss {target['name']}.")
    elif action_type == "ability":
        ability_result = _apply_ability(player, state, ability_name or "", target_index)
        result["player_action"].update(ability_result)
    elif action_type == "flee":
        if _status(state, "rooted"):
            result["player_action"]["success"] = False
            result["player_action"]["messages"].append("The environment roots you in place; you cannot flee this turn.")
            result["enemy_turns"] = _resolve_enemy_turn(player, state)
            result["status_events"] = _tick_effects(player, state)
            return result
        roll = stat_roll(player.current_stats.DEX, 12, is_weighted=False)
        result["player_action"]["roll"] = roll
        if roll["success"]:
            state["is_over"] = True
            state["winner"] = "escaped"
            result["player_action"]["messages"].append("You escape the encounter.")
            player.combat_state = None
            return result
        result["player_action"]["success"] = False
        result["player_action"]["messages"].append("You fail to escape.")
    else:
        raise ValueError(f"Unknown combat action '{action_type}'.")

    for enemy in enemies:
        phases = enemy.get("phases", [])
        phase_index = int(enemy.get("phase_index", 0))
        hp_ratio = enemy.get("hp", 0) / max(1, enemy.get("max_hp", 1))
        if phase_index < len(phases) and hp_ratio <= float(phases[phase_index].get("threshold", 0)):
            phase = phases[phase_index]
            enemy["phase_index"] = phase_index + 1
            enemy["phase_name"] = phase.get("name", f"Phase {phase_index + 2}")
            enemy["phase_damage_multiplier"] = float(phase.get("damage_multiplier", 1.0))
            if phase.get("element"):
                enemy["element"] = normalize_element(phase["element"])
            message = f"{enemy['name']} enters {enemy['phase_name']}!"
            state.setdefault("log", []).append(message)
            result.setdefault("phase_events", []).append(message)
            if phase.get("hazard") == "blight_spores":
                _add_status(state.setdefault("player_statuses", []), "weakened", 2, 2, source="boss_phase")
                result["phase_events"].append("The phase transition releases blight spores.")

    defeated = [e for e in enemies if e.get("hp", 0) <= 0]
    for enemy in defeated:
        state["log"] = state.get("log", []) + [f"{enemy['name']} defeated."]
        state.setdefault("defeated_enemy_ids", []).append(enemy.get("id"))
        bus.publish("enemy_killed", {"name": enemy["name"]})
    state["enemies"] = [e for e in enemies if e.get("hp", 0) > 0]
    if not state["enemies"]:
        state["is_over"] = True
        state["winner"] = "player"
        result["enemy_turns"] = []
        return result

    result["enemy_turns"] = _resolve_enemy_turn(player, state)
    result["status_events"] = _tick_effects(player, state)
    state["enemies"] = [enemy for enemy in state.get("enemies", []) if enemy.get("hp", 0) > 0]
    if not state["enemies"]:
        state["is_over"] = True
        state["winner"] = "player"
    if player.hp <= 0:
        state["is_over"] = True
        state["winner"] = "enemies"
    state["log"] = (state.get("log", []) + result["player_action"].get("messages", []) + [e["message"] for e in result["enemy_turns"]] + result.get("status_events", []))[-30:]
    return result
