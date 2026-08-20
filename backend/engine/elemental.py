"""Data-driven elemental affinity and damage rules for Conixia combat."""

from __future__ import annotations

ELEMENTS = ("fire", "frost", "storm", "shadow", "arcane", "earth", "water", "physical")

# Racial Conixia styles provide a primary affinity without hard-locking builds.
RACE_AFFINITIES = {
    "Velari": "shadow",
    "Ignari": "fire",
    "Aetherin": "arcane",
    "Pillarian": "earth",
    "Human": "arcane",
    "Elarin": "water",
    "Ogrin": "earth",
    "Trollan": "water",
}

# A small, legible interaction table: strong elements deal 1.5x, opposed
# elements deal 0.75x. Neutral matchups stay at 1.0x.
STRONG_AGAINST = {
    "fire": "frost",
    "frost": "storm",
    "storm": "water",
    "water": "fire",
    "shadow": "arcane",
    "arcane": "earth",
    "earth": "storm",
}
OPPOSED_TO = {target: source for source, target in STRONG_AGAINST.items()}

ABILITY_ELEMENTS = {
    "Arcane Slash": "arcane",
    "Shadow Veil": "shadow",
    "Time Fracture": "arcane",
    "Conixia Surge": "arcane",
    "Silent Step": "shadow",
    "Mystic Guard": "arcane",
    "Elemental Channel": "arcane",
    "Dagger Fade": "shadow",
    "Smoke Bomb": "shadow",
    "Mental Barrier": "arcane",
    "Future Echo": "arcane",
    "Earthen Wall": "earth",
    "Pulverize": "earth",
    "Stone Bind": "earth",
    "Weight of the World": "earth",
    "Flame Burst": "fire",
    "Molten Sweep": "fire",
    "Cinderstorm": "fire",
    "Shadowmeld": "shadow",
    "Night Pierce": "shadow",
    "Dark Shroud": "shadow",
    "Umbral Leap": "shadow",
    "Judgement": "arcane",
    "Mana Surge": "arcane",
    "Mirror Image": "arcane",
    "Shroudstep": "shadow",
    "Mind Spike": "arcane",
    "Soul Drain": "shadow",
    "Radiant Heal": "arcane",
    "Frost Nova": "frost",
    "Lightning Arc": "storm",
    "Starfall": "arcane",
    "Tidal Wave": "water",
    "Tempest Call": "storm",
    "Gravity Well": "earth",
    "Wind Dash": "storm",
}

WEAPON_ELEMENTS = {
    "staff_conixia": "arcane",
    "dagger_shadow": "shadow",
    "sword_iron": "physical",
}

STATUS_BY_ELEMENT = {
    "fire": {"name": "burning", "turns": 2, "damage_per_turn": 3},
    "frost": {"name": "chilled", "turns": 2, "value": 2},
    "storm": {"name": "shocked", "turns": 1, "value": 1},
    "shadow": {"name": "blinded", "turns": 2},
    "earth": {"name": "rooted", "turns": 1},
    "water": {"name": "soaked", "turns": 2, "value": 1},
    "arcane": {"name": "marked", "turns": 2, "value": 1},
}


def normalize_element(element: str | None) -> str:
    element = (element or "physical").lower().strip()
    return element if element in ELEMENTS else "physical"


def affinity_for_character(race: str, explicit: str | None = None) -> str:
    return normalize_element(explicit or RACE_AFFINITIES.get(race, "arcane"))


def default_resistances(race: str) -> dict[str, float]:
    primary = affinity_for_character(race)
    return {primary: 0.75}


def damage_multiplier(attack_element: str, defense_element: str | None = None, resistances: dict | None = None) -> float:
    attack = normalize_element(attack_element)
    defense = normalize_element(defense_element)
    multiplier = 1.0
    if STRONG_AGAINST.get(attack) == defense:
        multiplier *= 1.5
    elif OPPOSED_TO.get(attack) == defense:
        multiplier *= 0.75
    if resistances and attack in resistances:
        multiplier *= max(0.0, float(resistances[attack]))
    return round(multiplier, 3)


def status_for_element(element: str) -> dict | None:
    data = STATUS_BY_ELEMENT.get(normalize_element(element))
    return dict(data) if data else None


def weapon_element(item_id: str | None, item_effect=None) -> str:
    if item_id in WEAPON_ELEMENTS:
        return WEAPON_ELEMENTS[item_id]
    if item_effect and getattr(item_effect, "element", None):
        return normalize_element(item_effect.element)
    return "physical"
