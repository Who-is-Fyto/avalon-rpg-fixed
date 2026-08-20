"""Deterministic procedural generation for items, equipment, spells, and loot."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Optional

from engine.elemental import ABILITY_ELEMENTS, normalize_element

DATA_FILE = Path(__file__).parent.parent / "data" / "procedural_affixes.json"

RARITIES = {
    "common": {"tier": 0, "label": "Common", "color": "#a6a6a6", "weight": 620, "affix_slots": 0, "power_budget": 0, "value_multiplier": 1.0},
    "uncommon": {"tier": 1, "label": "Uncommon", "color": "#61d18a", "weight": 240, "affix_slots": 1, "power_budget": 5, "value_multiplier": 1.35},
    "rare": {"tier": 2, "label": "Rare", "color": "#4ea7ff", "weight": 95, "affix_slots": 2, "power_budget": 11, "value_multiplier": 2.0},
    "epic": {"tier": 3, "label": "Epic", "color": "#bd6cff", "weight": 32, "affix_slots": 3, "power_budget": 20, "value_multiplier": 3.4},
    "legendary": {"tier": 4, "label": "Legendary", "color": "#ff9d38", "weight": 10, "affix_slots": 4, "power_budget": 34, "value_multiplier": 6.0},
    "mythic": {"tier": 5, "label": "Mythic", "color": "#ff4d8d", "weight": 2, "affix_slots": 5, "power_budget": 52, "value_multiplier": 11.0},
    "relic": {"tier": 6, "label": "Relic", "color": "#f5d76e", "weight": 1, "affix_slots": 6, "power_budget": 75, "value_multiplier": 20.0},
}


def _catalog() -> dict:
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def _rng(seed: str) -> random.Random:
    digest = hashlib.sha256(str(seed).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _weighted_choice(rng: random.Random, entries: list[dict], weight_key: str = "weight") -> dict:
    total = sum(max(0, float(entry.get(weight_key, 0))) for entry in entries)
    if total <= 0:
        return entries[0]
    point = rng.random() * total
    for entry in entries:
        point -= max(0, float(entry.get(weight_key, 0)))
        if point <= 0:
            return entry
    return entries[-1]


def select_rarity(seed: str, rarity: Optional[str] = None) -> tuple[str, dict]:
    if rarity:
        key = rarity.lower().strip()
        if key not in RARITIES:
            raise ValueError(f"Unknown rarity '{rarity}'.")
        return key, dict(RARITIES[key])
    rng = _rng(f"rarity:{seed}")
    entry = _weighted_choice(rng, [{"id": key, **data} for key, data in RARITIES.items()])
    return entry["id"], dict(RARITIES[entry["id"]])


def _roll_affix(rng: random.Random, affix: dict, tier: int, budget: int) -> dict:
    raw_min, raw_max = affix.get("min", 1), affix.get("max", 1)
    if isinstance(raw_min, float) or isinstance(raw_max, float):
        value = round(rng.uniform(float(raw_min), float(raw_max)), 3)
    else:
        value = rng.randint(int(raw_min), int(raw_max)) + max(0, tier - 1)
    value = min(value, budget)
    rolled = {"id": affix["id"], "name": affix["name"], "kind": affix["kind"], "value": value}
    for key in ("stat", "element"):
        if key in affix:
            rolled[key] = affix[key]
    return rolled


def _format_name(base_name: str, affixes: list[dict]) -> str:
    prefixes = [a["name"] for a in affixes if a["id"] in {"keen", "mighty", "scholarly", "vital", "wise", "resonant", "ember", "umbral", "astral", "frostbound"}]
    suffixes = [a["name"] for a in affixes if a["id"] not in {"keen", "mighty", "scholarly", "vital", "wise", "resonant", "ember", "umbral", "astral", "frostbound"}]
    return " ".join(prefixes + [base_name] + suffixes)


def generate_item(base_item: dict, seed: str, level: int = 1, rarity: Optional[str] = None) -> dict:
    rarity_id, rarity_data = select_rarity(seed, rarity)
    rng = _rng(f"item:{seed}:{rarity_id}")
    pool = _catalog()["prefixes"] + _catalog()["suffixes"]
    selected: list[dict] = []
    budget = int(rarity_data["power_budget"] + max(0, level - 1) * 2)
    remaining = budget
    for _ in range(rarity_data["affix_slots"]):
        available = [a for a in pool if a["id"] not in {x["id"] for x in selected}]
        if not available or remaining <= 0:
            break
        affix = _weighted_choice(rng, available)
        rolled = _roll_affix(rng, affix, rarity_data["tier"], remaining)
        cost = max(1, int(abs(float(rolled["value"]))))
        if cost > remaining:
            continue
        selected.append(rolled)
        remaining -= cost

    stat_bonuses = {}
    resistance_bonuses = {}
    generated_effect = dict(base_item.get("effect", {}))
    element = generated_effect.get("element")
    for affix in selected:
        if affix["kind"] == "stat":
            stat_bonuses[affix["stat"]] = stat_bonuses.get(affix["stat"], 0) + affix["value"]
        elif affix["kind"] == "resistance":
            resistance_bonuses[affix["element"]] = resistance_bonuses.get(affix["element"], 0.0) + float(affix["value"])
        elif affix["kind"] == "element":
            element = normalize_element(affix["element"])
        elif affix["kind"] == "vitals":
            stat_bonuses[affix["stat"]] = stat_bonuses.get(affix["stat"], 0) + affix["value"]
    if element:
        generated_effect["element"] = element

    instance_id = "itm_" + hashlib.sha1(f"{base_item['id']}:{seed}:{rarity_id}".encode()).hexdigest()[:14]
    item = {
        **base_item,
        "id": instance_id,
        "instance_id": instance_id,
        "base_id": base_item["id"],
        "name": _format_name(base_item["name"], selected),
        "description": f"{base_item.get('description', '')} Procedurally forged at level {level}.",
        "effect": generated_effect,
        "rarity": rarity_id,
        "rarity_data": {"id": rarity_id, **rarity_data, "remaining_power": remaining},
        "affixes": selected,
        "stat_bonuses": stat_bonuses,
        "resistance_bonuses": resistance_bonuses,
        "value": max(1, int(round(base_item.get("value", 0) * rarity_data["value_multiplier"]))),
        "generated": True,
        "seed": str(seed),
    }
    return item


def generate_spell(base_ability: dict, seed: str, level: int = 1, rarity: Optional[str] = None) -> dict:
    rarity_id, rarity_data = select_rarity(f"spell:{seed}", rarity)
    rng = _rng(f"spell:{seed}:{rarity_id}")
    selected = []
    pool = _catalog()["spell_modifiers"]
    for _ in range(rarity_data["affix_slots"]):
        available = [a for a in pool if a["id"] not in {x["id"] for x in selected}]
        if not available:
            break
        selected.append(_roll_affix(rng, _weighted_choice(rng, available), rarity_data["tier"], max(1, rarity_data["power_budget"])))

    power_bonus = sum(int(a["value"]) for a in selected if a["kind"] == "power") + level // 3
    cost_reduction = sum(int(a["value"]) for a in selected if a["kind"] == "cost")
    cooldown_reduction = sum(int(a["value"]) for a in selected if a["kind"] == "cooldown")
    instance_id = "spl_" + hashlib.sha1(f"{base_ability['name']}:{seed}:{rarity_id}".encode()).hexdigest()[:14]
    return {
        **base_ability,
        "name": f"{base_ability['name']} [{rarity_data['label']}]",
        "instance_id": instance_id,
        "base_name": base_ability["name"],
        "generated": True,
        "seed": str(seed),
        "element": base_ability.get("element") or ABILITY_ELEMENTS.get(base_ability["name"]),
        "cost": max(0, int(base_ability.get("cost", 0)) - cost_reduction),
        "cooldown": max(0, int(base_ability.get("cooldown", 0)) - cooldown_reduction),
        "power_bonus": power_bonus,
        "cost_reduction": cost_reduction,
        "cooldown_reduction": cooldown_reduction,
        "description": f"{base_ability.get('description', '')} Generated with {rarity_data['label'].lower()} mastery.",
        "affixes": selected,
        "rarity": rarity_id,
        "rarity_data": {"id": rarity_id, **rarity_data},
    }
