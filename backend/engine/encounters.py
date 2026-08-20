"""Server-owned procedural encounters with encounter types and world-state modifiers."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from engine.data_loader import get_item
from engine.procedural import RARITIES, generate_item

DATA_DIR = Path(__file__).parent.parent / "data"


def _load_json(name: str):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _progression_config() -> dict:
    return _load_json("region_progression.json")


def _rng(seed: str) -> random.Random:
    digest = hashlib.sha256(str(seed).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _region_table(region: str) -> dict:
    tables = _load_json("region_loot_tables.json")
    return tables.get(region, tables["default"])


def _enemy_templates() -> dict[str, dict]:
    return {row["id"]: row for row in _load_json("enemy_templates.json")}


def _encounter_types() -> dict[str, dict]:
    return _load_json("encounter_types.json")


def _boss_loot_tables() -> dict[str, dict]:
    return _load_json("boss_loot_tables.json")


def normalize_region(value: str) -> str:
    return (value or "default").lower().strip().replace(" ", "_")


def region_access(char_data: dict, region: str, world_state: dict) -> tuple[bool, str]:
    region = normalize_region(region)
    config = _progression_config()
    region_rule = config.get("regions", {}).get(region)
    if not region_rule:
        return False, f"Region '{region}' has no progression definition."
    if not world_state.get("regions", {}).get(region, {}).get("accessible", True):
        return False, f"Region '{region}' is not currently accessible."
    level = int(char_data.get("level", 1))
    if level < int(region_rule.get("min_level", 1)):
        return False, f"Region '{region}' requires level {region_rule['min_level']}."
    flags = set(char_data.get("flags", []))
    missing_flags = [flag for flag in region_rule.get("required_flags", []) if flag not in flags]
    if missing_flags:
        return False, f"Region '{region}' requires progression flag(s): {', '.join(missing_flags)}."
    unlocked = set(char_data.get("unlocked_regions", []))
    unlocked.add(normalize_region(char_data.get("starting_location", "")))
    missing_regions = [r for r in region_rule.get("required_regions", []) if r not in unlocked]
    if missing_regions:
        return False, f"Unlock prerequisite region(s) first: {', '.join(missing_regions)}."
    return True, "ok"


def difficulty_access(char_data: dict, difficulty: str) -> tuple[bool, str]:
    difficulty = difficulty.lower().strip()
    tiers = _progression_config()["difficulty_tiers"]
    if difficulty not in tiers:
        return False, f"Unknown difficulty tier '{difficulty}'."
    level = int(char_data.get("level", 1))
    if difficulty == "veteran" and level < 3:
        return False, "Veteran encounters require level 3."
    if difficulty == "nightmare" and level < 7:
        return False, "Nightmare encounters require level 7."
    return True, "ok"


def encounter_type_access(char_data: dict, encounter_type: str) -> tuple[bool, str]:
    profile = _encounter_types().get(encounter_type.lower().strip())
    if not profile:
        return False, f"Unknown encounter type '{encounter_type}'."
    if int(char_data.get("level", 1)) < int(profile.get("min_level", 1)):
        return False, f"{profile['label']} encounters require level {profile['min_level']}."
    return True, "ok"


def _danger_modifier(region_state: dict | None) -> float:
    if not region_state:
        return 0.0
    value = 0.0
    value += {"stable": 0.0, "tense": 0.05, "unstable": 0.1, "volatile": 0.18}.get(region_state.get("stability"), 0.0)
    value += {"none": 0.0, "low": 0.04, "medium": 0.09, "high": 0.16, "critical": 0.24}.get(region_state.get("blight_severity"), 0.0)
    return value


def _world_hazards(region: str, region_state: dict | None, world_state: dict | None, encounter_type: str) -> tuple[list[dict], float, float, float]:
    region_state = region_state or {}
    world_state = world_state or {}
    storylines = world_state.get("global_storylines", {})
    catalog = _load_json("environment_modifiers.json")["hazards"]
    triggers: list[str] = []
    blight = storylines.get("conixia_blight", {})
    void = storylines.get("whispers_of_the_void", {})
    sovereignty = storylines.get("sundered_sovereignty", {})
    if region_state.get("blight_severity") in {"low", "medium", "high", "critical"} or blight.get("status") in {"spreading", "escalating", "critical"} or float(blight.get("intensity", 0)) >= 0.2:
        triggers.append("blight")
    if void.get("status") in {"stirring", "active", "manifesting"} or float(void.get("corruption_level", 0)) >= 0.2:
        triggers.append("void")
    if region_state.get("stability") in {"unstable", "volatile"}:
        triggers.append("unstable")
    if sovereignty.get("status") in {"war", "cold_war"} or region_state.get("controlling_faction") == "ironclad_dominion":
        triggers.append("war")
    if float(blight.get("intensity", 0)) >= 0.6 or blight.get("status") == "critical":
        triggers.append("conixia")
    hazards = []
    budget_modifier = 0.0
    damage_modifier = 0.0
    loot_bias = 0.0
    for trigger in dict.fromkeys(triggers):
        hazard = next((value for value in catalog.values() if value.get("trigger") == trigger), None)
        if not hazard:
            continue
        record = {"id": next(key for key, value in catalog.items() if value is hazard), **hazard}
        if encounter_type == "boss" and trigger in {"blight", "void"}:
            record["turns"] = int(record.get("turns", 1)) + 1
        hazards.append(record)
        budget_modifier += float(record.get("budget_modifier", 0))
        damage_modifier += float(record.get("damage_modifier", 0))
        loot_bias += float(record.get("loot_bias", 0))
    return hazards, budget_modifier, damage_modifier, loot_bias


def _rarity_for_loot(seed: str, level: int, bias: float) -> str:
    rng = _rng(f"rarity:{seed}")
    weighted = []
    for rarity, data in RARITIES.items():
        adjusted = float(data["weight"]) * (1.0 + max(0, level - 1) * 0.035 * data["tier"] + bias * data["tier"])
        weighted.append((rarity, adjusted))
    point = rng.random() * sum(weight for _, weight in weighted)
    for rarity, weight in weighted:
        point -= weight
        if point <= 0:
            return rarity
    return "common"


def generate_encounter(region: str, player_level: int, seed: str, region_state: dict | None = None, difficulty: str = "standard", encounter_type: str = "patrol", world_state: dict | None = None) -> dict:
    level = max(1, int(player_level))
    config = _progression_config()
    difficulty_id = difficulty.lower().strip()
    type_id = encounter_type.lower().strip()
    if difficulty_id not in config["difficulty_tiers"]:
        raise ValueError(f"Unknown difficulty tier '{difficulty}'.")
    type_profiles = _encounter_types()
    if type_id not in type_profiles:
        raise ValueError(f"Unknown encounter type '{encounter_type}'.")
    difficulty_data = config["difficulty_tiers"][difficulty_id]
    type_data = type_profiles[type_id]
    table = _region_table(region)
    templates = _enemy_templates()
    rng = _rng(f"encounter:{region}:{level}:{difficulty_id}:{type_id}:{seed}")
    hazards, hazard_budget, hazard_damage, loot_bias = _world_hazards(region, region_state, world_state, type_id)
    count = rng.randint(int(type_data["count_min"]), int(type_data["count_max"]))
    if type_id == "boss":
        count = 1
    if type_id == "ambush" and level < 3:
        count = min(count, 2)
    danger = _danger_modifier(region_state)
    difficulty_multiplier = float(difficulty_data["budget_multiplier"])
    enemies = []
    for index in range(count):
        if type_id == "boss":
            template_id = max(table["templates"], key=lambda key: templates[key].get("base_hp", 0))
        else:
            template_id = table["templates"][rng.randrange(len(table["templates"]))]
        template = templates[template_id]
        scale = (1.0 + (level - 1) * 0.1 + danger) * float(difficulty_data["xp_multiplier"]) * float(type_data["xp_multiplier"])
        stat_scale = (1.0 + (level - 1) * 0.055 + danger * 0.35) * float(difficulty_data["damage_multiplier"]) * float(type_data["damage_multiplier"]) * (1.0 + hazard_damage)
        hp_scale = (1.0 + (level - 1) * 0.14 + danger) * float(difficulty_data["hp_multiplier"]) * float(type_data["hp_multiplier"])
        is_elite = bool(type_data.get("guaranteed_elite"))
        if is_elite:
            stat_scale *= 1.18
            hp_scale *= 1.25
        stats = {key: max(1, int(round(value * stat_scale))) for key, value in template["base_stats"].items()}
        max_hp = max(1, int(round(template["base_hp"] * hp_scale)))
        element = template["element"]
        enemy_name = f"{type_data['label']} {template['name']}" if is_elite else template["name"]
        budget_cost = max(1, int(round((template["base_hp"] / 4 + sum(template["base_stats"].values()) / 3) * float(type_data["budget_multiplier"]) * difficulty_multiplier * (1.0 + hazard_budget))))
        enemies.append({"id":template_id,"name":enemy_name,"archetype":template["archetype"],"element":element,"resistances":{element:0.75},"hp":max_hp,"max_hp":max_hp,**stats,"xp":max(1,int(round(template["xp"]*scale))),"loot_tags":template.get("loot_tags",[]),"level":level,"budget_cost":budget_cost,"is_elite":is_elite,"encounter_type":type_id,"phases":template.get("phases", []),"drop_table":template.get("drops", [])})
    budget_limit = max(1, int(round(float(type_data["max_budget"]) * difficulty_multiplier * (1.0 + hazard_budget))) + int(type_data.get("budget_bonus", 0)))
    budget_used = sum(enemy["budget_cost"] for enemy in enemies)
    while len(enemies) > 1 and budget_used > budget_limit:
        removed = enemies.pop()
        budget_used -= removed["budget_cost"]
    encounter_seed = hashlib.sha1(f"{region}:{level}:{difficulty_id}:{type_id}:{seed}".encode()).hexdigest()[:16]
    return {"region":region,"seed":str(seed),"encounter_seed":encounter_seed,"player_level":level,"difficulty":difficulty_id,"encounter_type":type_id,"difficulty_data":difficulty_data,"type_data":type_data,"danger_modifier":round(danger,3),"budget_used":budget_used,"budget_limit":budget_limit,"hazards":hazards,"hazard_budget_modifier":round(hazard_budget,3),"loot_bias":round(loot_bias,3),"enemies":enemies}


def generate_loot(region: str, player_level: int, encounter_seed: str, defeated_count: int = 1, region_state: dict | None = None, difficulty: str = "standard", encounter_type: str = "patrol", loot_bias: float = 0.0, defeated_enemy_ids: list[str] | None = None) -> dict:
    level = max(1, int(player_level))
    config = _progression_config()
    difficulty_data = config["difficulty_tiers"].get(difficulty, config["difficulty_tiers"]["standard"])
    type_data = _encounter_types().get(encounter_type, _encounter_types()["patrol"])
    table = _region_table(region)
    rng = _rng(f"loot:{region}:{level}:{difficulty}:{encounter_type}:{encounter_seed}")
    count = rng.randint(int(table.get("drop_count_min", 1)), int(table.get("drop_count_max", 2)))
    count = max(1, int(round(count * float(difficulty_data["loot_multiplier"]) * float(type_data["loot_multiplier"]))))
    count = min(count + max(0, defeated_count - 1) // 2, 6)
    items = []
    material_drops = []
    defeated_enemy_ids = defeated_enemy_ids or []
    templates = _enemy_templates()
    boss_tables = _boss_loot_tables()

    def add_static_or_generated(item_id: str, index: int, rarity_bias: float = 0.0):
        base = get_item(item_id)
        if not base:
            return
        if base.category in {"equipment", "trinket"}:
            rarity = _rarity_for_loot(f"{encounter_seed}:special:{index}:{item_id}", level, rarity_bias)
            items.append(generate_item(base.model_dump(), f"{encounter_seed}:special:{index}", level, rarity))
        else:
            material_drops.append({"item": base.model_dump(), "quantity": 1})

    # Every defeated enemy can contribute its own deterministic material drops.
    for enemy_index, enemy_id in enumerate(defeated_enemy_ids):
        template = templates.get(enemy_id, {})
        for drop_index, drop in enumerate(template.get("drops", [])):
            roll = _rng(f"drop:{encounter_seed}:{enemy_index}:{drop_index}")
            if roll.random() <= float(drop.get("chance", 0)):
                quantity = roll.randint(int(drop.get("min", 1)), int(drop.get("max", 1)))
                for quantity_index in range(quantity):
                    add_static_or_generated(drop["item_id"], enemy_index * 100 + drop_index * 10 + quantity_index, float(loot_bias))

    # Bosses use a dedicated table with guaranteed materials and special equipment rolls.
    if encounter_type == "boss":
        for enemy_id in defeated_enemy_ids:
            boss_table = boss_tables.get(enemy_id)
            if not boss_table:
                continue
            guaranteed_index = 5000
            for guaranteed in boss_table.get("guaranteed", []):
                roll = _rng(f"boss-guaranteed:{encounter_seed}:{enemy_id}:{guaranteed_index}")
                quantity = roll.randint(int(guaranteed.get("min", 1)), int(guaranteed.get("max", 1)))
                for quantity_index in range(quantity):
                    add_static_or_generated(guaranteed["item_id"], guaranteed_index + quantity_index, float(boss_table.get("rarity_bias", 0.0)))
                guaranteed_index += 1
            roll = _rng(f"boss-rolls:{encounter_seed}:{enemy_id}")
            for roll_index in range(int(boss_table.get("rolls", 0))):
                for drop in boss_table.get("drops", []):
                    if roll.random() <= float(drop.get("chance", 0)):
                        quantity = roll.randint(int(drop.get("min", 1)), int(drop.get("max", 1)))
                        for quantity_index in range(quantity):
                            add_static_or_generated(drop["item_id"], 6000 + roll_index * 100 + quantity_index, float(boss_table.get("rarity_bias", 0.0)))

    for index in range(count):
        base_id = table["item_pool"][rng.randrange(len(table["item_pool"]))]
        base = get_item(base_id)
        if not base:
            continue
        rarity = _rarity_for_loot(f"{encounter_seed}:{index}:{base_id}", level, float(table.get("rarity_bias", 0.0)) + float(loot_bias) + (0.08 if encounter_type == "boss" else 0.0))
        items.append(generate_item(base.model_dump(), f"{encounter_seed}:drop:{index}", level, rarity))
    gold = int(rng.randint(int(table.get("gold_min", 5)), int(table.get("gold_max", 20))) * max(1, level // 3 + 1) * float(difficulty_data["loot_multiplier"]) * float(type_data["loot_multiplier"]))
    for drop in material_drops:
        item = drop["item"]
        existing = next((entry for entry in items if entry.get("id") == item.get("id") and not item.get("generated")), None)
        # Materials stay as stackable catalog items; quantities are merged by inventory persistence.
        if existing:
            existing["quantity"] = existing.get("quantity", 1) + drop["quantity"]
        else:
            items.append({**item, "drop_quantity": drop["quantity"]})
    return {"region":region,"encounter_seed":encounter_seed,"gold":gold,"items":items,"drop_count":len(items),"difficulty":difficulty,"encounter_type":encounter_type,"material_drop_count":len(material_drops)}
