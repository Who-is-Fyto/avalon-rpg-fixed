"""Character progression, stat allocation, and resource rules."""
import json
from pathlib import Path

VALID_STATS = ("STR", "DEX", "CON", "INT", "WIS", "CHA", "AFF")
GROWTH_FILE = Path(__file__).parent.parent / "data" / "race_growth_profiles.json"
CURVES_FILE = Path(__file__).parent.parent / "data" / "race_growth_curves.json"


def _growth_profiles() -> dict:
    with open(GROWTH_FILE, encoding="utf-8") as f:
        return json.load(f)


def _growth_curves() -> dict:
    with open(CURVES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _race_growth(char_data: dict) -> tuple[dict, dict]:
    curves = _growth_curves()
    components = char_data.get("race_components") or [char_data.get("race", "Human")]
    primary = curves.get(components[0], curves["Human"])
    secondary = curves.get(components[1], primary) if len(components) > 1 else None
    ratio = min(0.75, max(0.25, float(char_data.get("hybrid_ratio", 0.5)))) if secondary else 1.0
    level = max(2, int(char_data.get("level", 2)))
    idx = (level - 2) % 12
    growth = {}
    for stat in VALID_STATS:
        p = primary.get("stat_curves", {}).get(stat, [0] * 12)[idx]
        s = secondary.get("stat_curves", {}).get(stat, [0] * 12)[idx] if secondary else p
        growth[stat] = float(p) * ratio + float(s) * (1.0 - ratio)
    vitals = {}
    for key in ("max_hp", "max_conixia", "max_stamina"):
        p = primary.get("vitals", {}).get(key, [0] * 12)[idx]
        s = secondary.get("vitals", {}).get(key, [0] * 12)[idx] if secondary else p
        vitals[key] = float(p) * ratio + float(s) * (1.0 - ratio)
    return {"growth": growth, **vitals}, {"hybrid": bool(secondary), "level_index": idx}


def _apply_growth(char_data: dict) -> None:
    profile, _ = _race_growth(char_data)
    remainders = char_data.setdefault("growth_remainders", {})
    base = dict(char_data.get("base_stats", {}))
    for stat in VALID_STATS:
        total = float(profile.get("growth", {}).get(stat, 0)) + float(remainders.get(stat, 0.0))
        whole = int(total)
        remainders[stat] = round(total - whole, 6)
        base[stat] = int(base.get(stat, 0)) + whole
    char_data["base_stats"] = base
    history = char_data.setdefault("growth_history", [])
    history.append({"level": int(char_data.get("level", 1)), "growth": {k: round(float(v), 3) for k, v in profile.get("growth", {}).items()}, "vitals": {k: round(float(profile.get(k, 0)), 3) for k in ("max_hp", "max_conixia", "max_stamina")}})
    for key in ("max_hp", "max_conixia", "max_stamina"):
        total = float(profile.get(key, 0)) + float(remainders.get(key, 0.0))
        whole = int(total)
        remainders[key] = round(total - whole, 6)
        char_data[key] = int(char_data.get(key, 0)) + whole



def experience_to_next_level(level: int) -> int:
    return 100 + max(0, level - 1) * 75


def award_experience(char_data: dict, amount: int) -> dict:
    amount = max(0, int(amount))
    char_data["experience"] = int(char_data.get("experience", 0)) + amount
    levels_gained = 0

    while char_data["experience"] >= experience_to_next_level(char_data.get("level", 1)):
        threshold = experience_to_next_level(char_data.get("level", 1))
        char_data["experience"] -= threshold
        char_data["level"] = int(char_data.get("level", 1)) + 1
        levels_gained += 1
        char_data["unspent_stat_points"] = int(char_data.get("unspent_stat_points", 0)) + 1
        _apply_growth(char_data)
        char_data["hp"] = char_data["max_hp"]
        char_data["conixia_energy"] = char_data["max_conixia"]
        char_data["stamina"] = char_data["max_stamina"]

    return {
        "experience_gained": amount,
        "levels_gained": levels_gained,
        "new_level": char_data.get("level", 1),
        "stat_points_awarded": levels_gained,
        "unspent_stat_points": char_data.get("unspent_stat_points", 0),
        "experience": char_data.get("experience", 0),
        "next_level_experience": experience_to_next_level(char_data.get("level", 1)),
    }


def allocate_stat_points(char_data: dict, allocations: dict[str, int]) -> dict:
    """Spend unspent points atomically across the seven core stats."""
    if not isinstance(allocations, dict) or not allocations:
        raise ValueError("Provide at least one stat allocation.")
    unknown = sorted(set(allocations) - set(VALID_STATS))
    if unknown:
        raise ValueError(f"Unknown stat(s): {', '.join(unknown)}.")
    normalized = {}
    for stat, amount in allocations.items():
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError(f"Allocation for {stat} must be a non-negative integer.")
        if amount:
            normalized[stat] = amount
    total = sum(normalized.values())
    available = int(char_data.get("unspent_stat_points", 0))
    if total <= 0:
        raise ValueError("Allocation must spend at least one point.")
    if total > available:
        raise ValueError(f"You have {available} unspent stat point(s), but requested {total}.")

    current = dict(char_data.get("base_stats", {}))
    for stat, amount in normalized.items():
        current[stat] = int(current.get(stat, 0)) + amount
    char_data["base_stats"] = current
    allocations = dict(char_data.get("stat_allocations", {}))
    for stat, amount in normalized.items():
        allocations[stat] = int(allocations.get(stat, 0)) + amount
    char_data["stat_allocations"] = allocations
    char_data["unspent_stat_points"] = available - total
    return {"spent": total, "remaining": char_data["unspent_stat_points"], "base_stats": current}


def recalculate_stats(char_data: dict, item_lookup) -> dict:
    """Rebuild current stats from base stats, equipment, and active buffs."""
    base = dict(char_data.get("base_stats", {}))
    char_data.setdefault("base_max_hp", char_data.get("max_hp", 100))
    char_data.setdefault("base_max_conixia", char_data.get("max_conixia", 100))
    char_data["max_hp"] = int(char_data["base_max_hp"])
    char_data["max_conixia"] = int(char_data["base_max_conixia"])
    current = {stat: int(base.get(stat, 0)) for stat in VALID_STATS}
    equipment = char_data.get("equipment", {})
    base_resistances = dict(char_data.setdefault("base_elemental_resistances", char_data.get("elemental_resistances", {})))
    resistances = dict(base_resistances)
    hazard_resistances = dict(char_data.setdefault("base_hazard_resistances", char_data.get("hazard_resistances", {})))
    for item_id in equipment.values():
        if not item_id:
            continue
        item = item_lookup(item_id)
        if not item:
            continue
        for stat, value in getattr(item, "stat_bonuses", {}).items():
            if stat in VALID_STATS:
                current[stat] = current.get(stat, 0) + int(value)
            elif stat == "max_hp":
                char_data["max_hp"] = int(char_data.get("max_hp", 100)) + int(value)
            elif stat == "max_conixia":
                char_data["max_conixia"] = int(char_data.get("max_conixia", 100)) + int(value)
        for element, value in getattr(item, "resistance_bonuses", {}).items():
            resistances[element] = round(float(resistances.get(element, 1.0)) - float(value), 3)
        for hazard, value in getattr(item, "hazard_resistances", {}).items():
            hazard_resistances[hazard] = round(min(1.0, float(hazard_resistances.get(hazard, 0.0)) + float(value)), 3)
        if item.effect and item.effect.type in {"stat_bonus", "passive_bonus"} and item.effect.stat:
            current[item.effect.stat] = current.get(item.effect.stat, 0) + int(item.effect.value or 0)
    for buff in char_data.get("active_buffs", []):
        if buff.get("type") == "buff_stat" and buff.get("stat"):
            current[buff["stat"]] = current.get(buff["stat"], 0) + int(buff.get("value", 0))
    char_data["current_stats"] = current
    char_data["elemental_resistances"] = resistances
    char_data["hazard_resistances"] = hazard_resistances
    return current


def restore_after_combat(char_data: dict) -> None:
    """Restore turn resources and expire encounter-scoped effects."""
    char_data["conixia_energy"] = min(char_data.get("max_conixia", 0), char_data.get("conixia_energy", 0) + 2)
    char_data["stamina"] = char_data.get("max_stamina", 100)
    # Active item buffs and statuses are encounter-scoped unless explicitly
    # marked persistent; equipment bonuses are recalculated separately.
    char_data["active_buffs"] = [b for b in char_data.get("active_buffs", []) if b.get("persistent")]
    temporary = char_data.get("temporary_abilities", [])
    if temporary:
        temporary_names = {entry.get("name") for entry in temporary}
        char_data["known_abilities"] = [a for a in char_data.get("known_abilities", []) if a not in temporary_names]
        char_data["temporary_abilities"] = []
    char_data["combat_state"] = None
