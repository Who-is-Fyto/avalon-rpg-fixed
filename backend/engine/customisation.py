"""Advanced customisation rules: lineage traits, projections, respec, and evolution."""
import json
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).parent.parent
TRAITS_FILE = ROOT / "data" / "lineage_traits.json"
CURVES_FILE = ROOT / "data" / "race_growth_curves.json"
VALID_STATS = ("STR", "DEX", "CON", "INT", "WIS", "CHA", "AFF")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def lineage_traits():
    return _load(TRAITS_FILE)


def growth_curves():
    return _load(CURVES_FILE)


def hybrid_key(a, b):
    return "+".join(sorted((str(a).lower(), str(b).lower())))


def trait_for_character(char):
    components = char.get("race_components") or [char.get("race", "Human")]
    data = lineage_traits()
    if len(components) < 2:
        return deepcopy(data.get("pure", {}).get(components[0], {}))
    a, b = components[:2]
    ta = data.get("pure", {}).get(a, {})
    tb = data.get("pure", {}).get(b, {})
    key = hybrid_key(ta.get("affinity", "arcane"), tb.get("affinity", "arcane"))
    hybrid = deepcopy(data.get("hybrid", {}).get(key, {}))
    if not hybrid:
        reverse_key = "+".join(reversed(key.split("+")))
        hybrid = deepcopy(data.get("hybrid", {}).get(reverse_key, {}))
    if not hybrid:
        hybrid = {"name": f"{a}-{b} Confluence", "description": "The two lineages create a flexible blended affinity.", "affinity": f"{ta.get('affinity','arcane')}+{tb.get('affinity','arcane')}"}
    hybrid["components"] = [a, b]
    hybrid["ratio"] = char.get("hybrid_ratio", 0.5)
    return hybrid


def apply_lineage_traits(char):
    trait = trait_for_character(char)
    char["lineage_trait"] = trait
    if trait.get("affinity"):
        char["hybrid_affinity"] = trait["affinity"]
        if len(char.get("race_components", [])) > 1:
            char["affinity"] = trait["affinity"]
    for stat, amount in trait.get("passive", {}).get("stat_bonuses", trait.get("stat_bonuses", {})).items():
        if stat in VALID_STATS:
            char.setdefault("base_stats", {})[stat] = int(char.get("base_stats", {}).get(stat, 0)) + int(amount)
    for element, value in trait.get("elemental_resistances", {}).items():
        current = float(char.setdefault("elemental_resistances", {}).get(element, 1.0))
        char["elemental_resistances"][element] = round(max(0.0, current - float(value)), 3)
    for hazard, value in trait.get("hazard_resistances", {}).items():
        current = float(char.setdefault("hazard_resistances", {}).get(hazard, 0.0))
        char["hazard_resistances"][hazard] = round(min(1.0, current + float(value)), 3)
    perk_name = trait.get("passive", {}).get("name") or (trait.get("name") if len(char.get("race_components", [])) > 1 else None)
    if perk_name:
        flag = "perk_" + perk_name.lower().replace(" ", "_")
        if flag not in char.setdefault("flags", []):
            char["flags"].append(flag)
    return trait


def projected_growth(char, through_level=None):
    curves = growth_curves()
    components = char.get("race_components") or [char.get("race", "Human")]
    primary = curves.get(components[0], curves.get("Human"))
    secondary = curves.get(components[1], primary) if len(components) > 1 else None
    ratio = float(char.get("hybrid_ratio", 1.0)) if secondary else 1.0
    through_level = max(int(through_level or char.get("level", 1) or 1), 1)
    through_level = min(through_level, 60)
    stats = dict(char.get("base_stats", {}))
    vitals = {k: int(char.get(k, 0)) for k in ("max_hp", "max_conixia", "max_stamina")}
    points = []
    for level in range(1, through_level + 1):
        idx = (level - 2) % 12
        if level > 1:
            for stat in VALID_STATS:
                p = float(primary.get("stat_curves", {}).get(stat, [0] * 12)[idx])
                s = float(secondary.get("stat_curves", {}).get(stat, [0] * 12)[idx]) if secondary else p
                stats[stat] = int(stats.get(stat, 0)) + int(round(p * ratio + s * (1 - ratio)))
            for key in vitals:
                p = float(primary.get("vitals", {}).get(key, [0] * 12)[idx])
                s = float(secondary.get("vitals", {}).get(key, [0] * 12)[idx]) if secondary else p
                vitals[key] += int(round(p * ratio + s * (1 - ratio)))
        points.append({"level": level, "stats": dict(stats), "vitals": dict(vitals)})
    return {"through_level": through_level, "points": points}


def respec(char, allocations=None, cost=0):
    level_points = max(0, int(char.get("level", 1)) - 1)
    spent = sum(int(v) for v in (char.get("stat_allocations", {}) or {}).values())
    pool = level_points + spent
    allocations = allocations or {}
    if any(k not in VALID_STATS or int(v) < 0 for k, v in allocations.items()):
        raise ValueError("Respec allocations contain an invalid stat or negative value.")
    if sum(int(v) for v in allocations.values()) > pool:
        raise ValueError(f"Respec requires at most {pool} points.")
    base = dict(char.get("racial_base_stats", char.get("base_stats", {})))
    char["base_stats"] = {stat: int(base.get(stat, 0)) + int(allocations.get(stat, 0)) for stat in VALID_STATS}
    char["stat_allocations"] = {k: int(v) for k, v in allocations.items() if int(v)}
    char["unspent_stat_points"] = pool - sum(char["stat_allocations"].values())
    char["respec_count"] = int(char.get("respec_count", 0)) + 1
    char["last_respec_level"] = int(char.get("level", 1))
    return {"spent": sum(char["stat_allocations"].values()), "remaining": char["unspent_stat_points"], "base_stats": char["base_stats"]}


def evolve_lineage(char, target_race, target_secondary=None):
    if int(char.get("level", 1)) < 20:
        raise ValueError("Lineage evolution unlocks at level 20.")
    components = char.get("race_components") or [char.get("race", "Human")]
    if target_race not in growth_curves():
        raise ValueError("Unknown target lineage.")
    if target_secondary and target_secondary not in growth_curves():
        raise ValueError("Unknown secondary lineage.")
    char["race_components"] = [target_race] + ([target_secondary] if target_secondary and target_secondary != target_race else [])
    char["race"] = target_race + (f"-{target_secondary} Hybrid" if target_secondary else "")
    char["hybrid_ratio"] = 0.5 if target_secondary else 1.0
    char["growth_profile"] = {"primary": target_race, "secondary": target_secondary, "ratio": char["hybrid_ratio"]}
    char["lineage_evolution_count"] = int(char.get("lineage_evolution_count", 0)) + 1
    char.setdefault("flags", []).append("lineage_evolved")
    apply_lineage_traits(char)
    return {"race": char["race"], "race_components": char["race_components"], "lineage_trait": char.get("lineage_trait"), "hybrid_affinity": char.get("hybrid_affinity")}
