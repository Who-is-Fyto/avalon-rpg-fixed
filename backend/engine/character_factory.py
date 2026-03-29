"""
engine/character_factory.py
Handles character creation, race-lock validation, stat assembly, starting
inventory, and starting context assignment.
"""

import json
import random
from pathlib import Path
from models import Character, StatBlock, InventoryEntry, EquipmentSlots
from engine.data_loader import get_race, get_class
from engine.rng import select_weighted_location, weighted_choice

CONTEXTS_FILE = Path(__file__).parent.parent / "data" / "starting_contexts.json"

CLASS_STARTING_ITEMS: dict[str, list[dict]] = {
    "Spellblade":     [{"id": "health_potion_minor", "qty": 2}, {"id": "conixia_draught_minor", "qty": 2}, {"id": "sword_iron", "qty": 1}],
    "Whisper":        [{"id": "health_potion_minor", "qty": 2}, {"id": "smoke_bomb", "qty": 3},            {"id": "dagger_shadow", "qty": 1}],
    "Seer":           [{"id": "health_potion_minor", "qty": 2}, {"id": "conixia_draught_minor", "qty": 3}, {"id": "staff_conixia", "qty": 1}],
    "Stonecaller":    [{"id": "health_potion_standard", "qty": 2}, {"id": "hearty_stew", "qty": 2}],
    "Emberheart":     [{"id": "health_potion_minor", "qty": 2}, {"id": "elixir_of_might", "qty": 1}],
    "Twilight Walker":[{"id": "health_potion_minor", "qty": 2}, {"id": "smoke_bomb", "qty": 2}, {"id": "dagger_shadow", "qty": 1}],
    "Warlord":        [{"id": "health_potion_standard", "qty": 2}, {"id": "sword_iron", "qty": 1},         {"id": "armour_leather", "qty": 1}],
    "Arcanist":       [{"id": "health_potion_minor", "qty": 2}, {"id": "conixia_draught_standard", "qty": 1}, {"id": "staff_conixia", "qty": 1}],
}

CLASS_STARTING_GOLD: dict[str, int] = {
    "Spellblade": 50, "Whisper": 75, "Seer": 40,
    "Stonecaller": 30, "Emberheart": 35, "Twilight Walker": 80,
    "Warlord": 45, "Arcanist": 40,
}


def _load_contexts() -> dict:
    with open(CONTEXTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_available_contexts(race_name: str, location_name: str) -> list[dict]:
    """Return context options for this race+location combo, or empty list."""
    contexts = _load_contexts()
    race_contexts = contexts.get(race_name, {})
    return race_contexts.get(location_name, [])


def select_context(race_name: str, location_name: str, context_id: str | None = None) -> dict | None:
    """
    Pick a starting context. If context_id is given, find it by id.
    Otherwise pick one weighted-randomly. Returns None if no contexts exist.
    """
    options = get_available_contexts(race_name, location_name)
    if not options:
        return None

    if context_id:
        match = next((c for c in options if c["id"] == context_id), None)
        return match  # None if not found (caller should handle)

    # Weighted random
    pool = [{"value": c, "weight": c.get("weight", 10)} for c in options]
    return weighted_choice(pool)["value"]


def validate_class_unlock(class_name: str, race_name: str) -> tuple[bool, str]:
    char_class = get_class(class_name)
    if not char_class:
        return False, f"Class '{class_name}' not found."
    unlock = char_class.unlock
    if unlock == "default":
        return True, ""
    if unlock.startswith("race:"):
        required_race = unlock.split("race:")[1].strip()
        if race_name.lower() != required_race.lower():
            return False, f"'{class_name}' is locked to the {required_race} race."
    return True, ""


def build_character(
    name: str,
    race_name: str,
    class_name: str,
    location: str | None = None,
    context_id: str | None = None,
) -> Character:
    race       = get_race(race_name)
    char_class = get_class(class_name)

    if not race:
        raise ValueError(f"Race '{race_name}' not found.")
    if not char_class:
        raise ValueError(f"Class '{class_name}' not found.")

    valid, reason = validate_class_unlock(class_name, race_name)
    if not valid:
        raise ValueError(reason)

    base_stats = race.stat_modifiers

    chosen_location = location or select_weighted_location(
        [{"name": loc.name, "weight": loc.weight} for loc in race.starting_locations]
    )

    # ── Starting context ──────────────────────────────────────────────────────
    context = select_context(race_name, chosen_location, context_id)
    context_flags = context.get("flags", []) if context else []
    context_label = context.get("label", "") if context else ""
    context_id_chosen = context.get("id", "") if context else ""

    backstory = (
        context.get("backstory", f"Raised in {chosen_location}, you've always been drawn to the art of {char_class.name}.")
        if context else
        f"Raised in {chosen_location}, you've always been drawn to the art of {char_class.name}."
    )

    known_abilities = char_class.starting_abilities[:]

    max_hp      = 80 + base_stats.CON * 4
    max_conixia = 60 + base_stats.AFF * 8

    starting_items = CLASS_STARTING_ITEMS.get(class_name, [])
    inventory = [InventoryEntry(item_id=i["id"], quantity=i["qty"]) for i in starting_items]

    equipment = EquipmentSlots()
    from engine.data_loader import get_item
    for entry in inventory:
        item = get_item(entry.item_id)
        if item and item.slot:
            if item.slot == "weapon" and not equipment.weapon:
                equipment.weapon = entry.item_id
            elif item.slot == "armour" and not equipment.armour:
                equipment.armour = entry.item_id
            elif item.slot == "trinket" and not equipment.trinket:
                equipment.trinket = entry.item_id

    gold = CLASS_STARTING_GOLD.get(class_name, 40)

    return Character(
        name=name,
        race=race.name,
        character_class=char_class.name,
        base_stats=base_stats,
        current_stats=base_stats.model_copy(),
        starting_location=chosen_location,
        level=1,
        experience=0,
        conixia_energy=max_conixia,
        max_conixia=max_conixia,
        hp=max_hp,
        max_hp=max_hp,
        known_abilities=known_abilities,
        backstory_seed=backstory,
        flags=list(set(context_flags + [f"race_{race.name.lower()}", f"class_{char_class.name.lower()}"])),
        inventory=inventory,
        equipment=equipment,
        gold=gold,
        # Store context info on the character
        starting_context=context_id_chosen,
        starting_context_label=context_label,
    )
