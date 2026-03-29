"""
engine/data_loader.py
Loads and caches all static JSON data at startup.
"""

import json
from pathlib import Path
from models import Race, CharacterClass, Ability, Item, ItemEffect, StatBlock, StartingLocation, Perk

DATA_DIR = Path(__file__).parent.parent / "data"


def _load(filename: str) -> list | dict:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _load_story(arc: str) -> dict:
    if arc == "prologue":
        arc = "prologue_expanded"
    elif arc == "chapter_1":
        arc = "chapter_1_refined"
    elif arc == "chapter_2":
        arc = "chapter_2_refined"
    elif arc == "side_quests":
        arc = "side_quests"
    with open(DATA_DIR / "story" / f"{arc}.json", encoding="utf-8") as f:
        return json.load(f)


def get_all_races() -> list[Race]:
    raw = _load("races.json")
    result = []
    for r in raw:
        result.append(Race(
            name=r["name"],
            conixia_style=r["conixia_style"],
            society_role=r["society_role"],
            stat_modifiers=StatBlock(**r["stat_modifiers"]),
            starting_locations=[StartingLocation(**loc) for loc in r["starting_locations"]],
            perk=Perk(**r["perk"]),
        ))
    return result


def get_race(name: str) -> Race | None:
    for r in get_all_races():
        if r.name.lower() == name.lower():
            return r
    return None


def get_all_classes() -> list[CharacterClass]:
    raw = _load("classes.json")
    return [CharacterClass(**c) for c in raw]


def get_class(name: str) -> CharacterClass | None:
    for c in get_all_classes():
        if c.name.lower() == name.lower():
            return c
    return None


def get_all_abilities() -> list[Ability]:
    raw = _load("abilities.json")
    return [Ability(**a) for a in raw]


def get_ability(name: str) -> Ability | None:
    for a in get_all_abilities():
        if a.name.lower() == name.lower():
            return a
    return None


def get_all_items() -> list[Item]:
    raw = _load("items.json")
    result = []
    for i in raw:
        item = Item(
            id=i["id"],
            name=i["name"],
            category=i["category"],
            subcategory=i["subcategory"],
            description=i["description"],
            effect=ItemEffect(**i["effect"]),
            weight=i.get("weight", 0.0),
            value=i.get("value", 0),
            stackable=i.get("stackable", False),
            max_stack=i.get("max_stack", 1),
            rarity=i.get("rarity", "common"),
            slot=i.get("slot"),
            unlock=i.get("unlock"),
        )
        result.append(item)
    return result


def get_item(item_id: str) -> Item | None:
    for item in get_all_items():
        if item.id == item_id:
            return item
    return None


def get_story_arc(arc: str) -> dict:
    return _load_story(arc)
