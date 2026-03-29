"""
routes/game.py
Character creation, stat rolls, story, inventory, character sheet.
All endpoints session-scoped.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from models import (Character, StatBlock, EquipmentSlots, InventoryEntry,
                    CharacterCreateRequest, RollRequest, StoryChoiceRequest,
                    UseItemRequest, EquipItemRequest, AddItemRequest)
from engine.character_factory import build_character, validate_class_unlock, get_available_contexts
from engine.rng import stat_roll
from engine.story_router import resolve_choice, get_node, filter_choices_by_conditions
from engine.data_loader import get_story_arc, get_all_classes, get_all_abilities, get_item
import engine.world_state as ws
import engine.session_manager as sm

router = APIRouter(prefix="/game", tags=["Game"])


# ── Inline request models ─────────────────────────────────────────────────────

class StoryNodeRequest(BaseModel):
    session_id: str
    arc: str
    node_id: str
    character_name: str


# ── Session helpers ───────────────────────────────────────────────────────────

def _activate_session(session_id: str) -> None:
    meta = sm.get_session_meta(session_id)
    if not meta:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    ws.set_active_session(session_id)


def _get_char(session_id: str, name: str) -> dict:
    _activate_session(session_id)
    char = sm.load_character(session_id, name)
    if not char:
        raise HTTPException(404, f"No character '{name}' in session '{session_id}'.")
    return char


def _save_char(session_id: str, char_data: dict) -> None:
    sm.save_character(session_id, char_data)


def _to_model(char_data: dict) -> Character:
    return Character(
        **{**char_data,
           "base_stats":    StatBlock(**char_data["base_stats"]),
           "current_stats": StatBlock(**char_data["current_stats"]),
           "equipment":     EquipmentSlots(**char_data.get("equipment", {})),
           "inventory":     [InventoryEntry(**e) for e in char_data.get("inventory", [])],
        }
    )


def _interpolate(text: str, char: dict) -> str:
    return (text
        .replace("{starting_location}", char.get("starting_location", ""))
        .replace("{character_name}",    char.get("name", ""))
        .replace("{starting_context}",  char.get("starting_context_label", ""))
        .replace("{race}",              char.get("race", ""))
        .replace("{class}",             char.get("character_class", "")))


# ── Context discovery ─────────────────────────────────────────────────────────

@router.get("/contexts/{race}/{location}")
def get_starting_contexts(race: str, location: str):
    options = get_available_contexts(race, location)
    return {"race": race, "location": location, "contexts": options}


# ── Character Creation ────────────────────────────────────────────────────────

@router.post("/character/create")
def create_character(req: CharacterCreateRequest):
    _activate_session(req.session_id)

    if sm.character_exists(req.session_id, req.name):
        raise HTTPException(400, f"A character named '{req.name}' already exists in this session.")

    # FIX: only block if the location is explicitly given AND inaccessible
    # If null (random), server picks — skip the accessibility check
    if req.starting_location:
        if not ws.is_location_accessible(req.starting_location):
            loc_state = ws.get_location_state(req.starting_location)
            stability = loc_state.get("stability", "unknown")
            if stability == "destroyed":
                raise HTTPException(400,
                    f"'{req.starting_location}' has been destroyed. Choose another location.")
            raise HTTPException(400,
                f"'{req.starting_location}' is not currently accessible.")

    try:
        character = build_character(
            req.name, req.race, req.character_class,
            req.starting_location, req.context_id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    char_data = character.model_dump()
    char_data["session_id"] = req.session_id
    _save_char(req.session_id, char_data)

    ws.log_event(
        f"{req.name} the {req.race} {req.character_class} began their story "
        f"at {character.starting_location}."
    )

    return {
        "status":    "created",
        "character": char_data,
        "message":   character.backstory_seed,
        # FIX: always return the actual assigned location so frontend can display it
        "assigned_location": character.starting_location,
        "context": {
            "id":    character.starting_context,
            "label": character.starting_context_label,
        },
    }


@router.get("/character/{session_id}/{name}")
def get_character(session_id: str, name: str):
    return _get_char(session_id, name)


@router.get("/character/{session_id}/{name}/classes")
def available_classes_for_character(session_id: str, name: str):
    char = _get_char(session_id, name)
    result = []
    for cls in get_all_classes():
        valid, reason = validate_class_unlock(cls.name, char["race"])
        result.append({
            "name":          cls.name,
            "role":          cls.role,
            "focus":         cls.conixia_focus,
            "playstyle":     cls.playstyle,
            "available":     valid,
            "locked_reason": reason if not valid else None,
        })
    return result


# ── Character Sheet ───────────────────────────────────────────────────────────

@router.get("/character/{session_id}/{name}/sheet")
def character_sheet(session_id: str, name: str):
    char = _get_char(session_id, name)
    model = _to_model(char)

    all_abilities = {a.name: a.model_dump() for a in get_all_abilities()}
    known     = [all_abilities[a] for a in model.known_abilities if a in all_abilities]
    actives   = [a for a in known if a["type"] == "active"]
    passives  = [a for a in known if a["type"] == "passive"]
    ultimates = [a for a in known if a["type"] == "ultimate"]

    inventory_resolved = []
    total_weight = 0.0
    for entry in model.inventory:
        item = get_item(entry.item_id)
        if item:
            total_weight += item.weight * entry.quantity
            inventory_resolved.append({
                **item.model_dump(),
                "quantity": entry.quantity,
                "equipped": entry.item_id in [
                    model.equipment.weapon,
                    model.equipment.armour,
                    model.equipment.trinket,
                ]
            })

    equipped_resolved = {}
    for slot in ["weapon", "armour", "trinket"]:
        item_id = getattr(model.equipment, slot)
        if item_id:
            item = get_item(item_id)
            equipped_resolved[slot] = item.model_dump() if item else None
        else:
            equipped_resolved[slot] = None

    world = ws.get()
    faction_snapshot = {
        k: {"influence": v["influence"], "disposition": v["disposition_to_player"]}
        for k, v in world.get("factions", {}).items()
    }

    loc_state = ws.get_location_state(model.starting_location)

    return {
        "identity": {
            "name":                   model.name,
            "race":                   model.race,
            "class":                  model.character_class,
            "level":                  model.level,
            "experience":             model.experience,
            "starting_location":      model.starting_location,
            "starting_context":       model.starting_context,
            "starting_context_label": model.starting_context_label,
            "backstory":              model.backstory_seed,
            "location_state":         loc_state,
        },
        "vitals": {
            "hp":             model.hp,
            "max_hp":         model.max_hp,
            "conixia_energy": model.conixia_energy,
            "max_conixia":    model.max_conixia,
        },
        "stats":      model.current_stats.model_dump(),
        "base_stats": model.base_stats.model_dump(),
        "abilities": {
            "active":   actives,
            "passive":  passives,
            "ultimate": ultimates,
        },
        "equipment":    equipped_resolved,
        "inventory":    inventory_resolved,
        "carry_weight": round(total_weight, 2),
        "gold":         model.gold,
        "active_buffs": model.active_buffs,
        "flags":        model.flags,
        "factions":     faction_snapshot,
        "world_events": world.get("world_events_log", [])[-10:],
    }


# ── Stat Roll ─────────────────────────────────────────────────────────────────

@router.post("/roll")
def roll_stat_check(req: RollRequest):
    char_data = _get_char(req.session_id, req.character_name)
    stats    = char_data["current_stats"]
    stat_val = stats.get(req.stat)
    if stat_val is None:
        raise HTTPException(400, f"Unknown stat '{req.stat}'.")

    if req.use_reroll:
        if char_data["race"] != "Human":
            raise HTTPException(400, "Only Humans have the Fate Bound perk.")
        if char_data.get("fate_bound_used"):
            raise HTTPException(400, "Fate Bound already used this session.")
        char_data["fate_bound_used"] = True
        _save_char(req.session_id, char_data)

    result = stat_roll(stat_val, req.dc)
    return {"character": req.character_name, "stat": req.stat, "stat_value": stat_val, **result}


# ── Story ─────────────────────────────────────────────────────────────────────

@router.get("/story/{session_id}/{arc}/start")
def get_story_start(session_id: str, arc: str, character_name: str):
    char_data = _get_char(session_id, character_name)

    try:
        story = get_story_arc(arc)
    except FileNotFoundError:
        raise HTTPException(404, f"Story arc '{arc}' not found.")

    start_node = story["nodes"].get("start")
    if not start_node:
        raise HTTPException(500, f"Arc '{arc}' has no 'start' node.")

    text      = _interpolate(start_node["text"], char_data)
    character = _to_model(char_data)
    visible   = filter_choices_by_conditions(start_node.get("choices", []), character)

    choices = [{"index": i, "text": c["text"],
                "has_check": c.get("stat_check") is not None,
                "check_stat": c.get("stat_check", {}).get("stat") if c.get("stat_check") else None}
               for i, c in enumerate(visible)]

    return {"arc": arc, "node_id": "start", "text": text, "choices": choices}


@router.post("/story/node")
def get_story_node(req: StoryNodeRequest):
    """Load a specific story node directly (used for side quests and direct navigation)."""
    char_data = _get_char(req.session_id, req.character_name)

    try:
        story = get_story_arc(req.arc)
    except FileNotFoundError:
        raise HTTPException(404, f"Story arc '{req.arc}' not found.")

    node = story["nodes"].get(req.node_id)
    if not node:
        raise HTTPException(404, f"Node '{req.node_id}' not found in arc '{req.arc}'.")

    text      = _interpolate(node["text"], char_data)
    character = _to_model(char_data)
    visible   = filter_choices_by_conditions(node.get("choices", []), character)

    choices = [{"index": i, "text": c["text"],
                "has_check": c.get("stat_check") is not None,
                "check_stat": c.get("stat_check", {}).get("stat") if c.get("stat_check") else None}
               for i, c in enumerate(visible)]

    return {"arc": req.arc, "node_id": req.node_id, "text": text, "choices": choices}


@router.post("/story/choose")
def make_story_choice(req: StoryChoiceRequest):
    char_data = _get_char(req.session_id, req.character_name)
    character = _to_model(char_data)

    try:
        result = resolve_choice(character, req.arc, req.node_id, req.choice_index)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))

    if result.get("flags_added"):
        char_data["flags"] = list(set(
            char_data.get("flags", []) + result["flags_added"]
        ))

    # On prologue complete, advance world state
    if result.get("arc_complete") and req.arc == "prologue":
        ws.set_flag("prologue_complete", True)
        ws.set_flag("aim_first_contact", True)
        ws.adjust_faction_influence("aim", 5)
        ws.log_event(f"{req.character_name} completed the prologue.")

    _save_char(req.session_id, char_data)
    return result


# ── Inventory ─────────────────────────────────────────────────────────────────

@router.post("/inventory/add")
def add_item(req: AddItemRequest):
    char_data = _get_char(req.session_id, req.character_name)
    item = get_item(req.item_id)
    if not item:
        raise HTTPException(404, f"Item '{req.item_id}' not found.")

    inventory = char_data.get("inventory", [])
    if item.stackable:
        for entry in inventory:
            if entry["item_id"] == req.item_id:
                entry["quantity"] = min(entry["quantity"] + req.quantity, item.max_stack)
                _save_char(req.session_id, char_data)
                return {"status": "stacked", "inventory": inventory}

    inventory.append({"item_id": req.item_id, "quantity": req.quantity})
    char_data["inventory"] = inventory
    _save_char(req.session_id, char_data)
    return {"status": "added", "item": item.model_dump(), "inventory": inventory}


@router.post("/inventory/use")
def use_item(req: UseItemRequest):
    char_data = _get_char(req.session_id, req.character_name)
    inventory = char_data.get("inventory", [])

    entry = next((e for e in inventory if e["item_id"] == req.item_id), None)
    if not entry or entry["quantity"] < 1:
        raise HTTPException(400, f"'{req.item_id}' not in inventory.")

    item = get_item(req.item_id)
    if not item:
        raise HTTPException(404, f"Item '{req.item_id}' not found.")
    if item.category == "equipment":
        raise HTTPException(400, "Equip equipment items using /inventory/equip.")

    result_msg = _apply_item_effect(char_data, item)

    entry["quantity"] -= 1
    char_data["inventory"] = (
        [e for e in inventory if e["item_id"] != req.item_id]
        if entry["quantity"] <= 0 else inventory
    )

    _save_char(req.session_id, char_data)
    return {"status": "used", "item": item.name, "effect": result_msg, "character": char_data}


def _apply_item_effect(char_data: dict, item) -> str:
    effect = item.effect
    if effect.type == "heal_hp":
        char_data["hp"] = min(char_data["max_hp"], char_data["hp"] + effect.value)
        return f"Restored {effect.value} HP. Now at {char_data['hp']}/{char_data['max_hp']}."
    if effect.type == "restore_conixia":
        char_data["conixia_energy"] = min(
            char_data["max_conixia"], char_data["conixia_energy"] + effect.value
        )
        return f"Restored {effect.value} Conixia. Now at {char_data['conixia_energy']}/{char_data['max_conixia']}."
    if effect.type == "regen_hp":
        char_data.setdefault("active_buffs", []).append(
            {"type": "regen_hp", "value": effect.value, "turns_remaining": effect.duration_turns}
        )
        return f"Regen active: +{effect.value} HP for {effect.duration_turns} turns."
    if effect.type == "buff_stat":
        char_data.setdefault("active_buffs", []).append(
            {"type": "buff_stat", "stat": effect.stat, "value": effect.value,
             "turns_remaining": effect.duration_turns}
        )
        char_data["current_stats"][effect.stat] = (
            char_data["current_stats"].get(effect.stat, 0) + effect.value
        )
        return f"{effect.stat} +{effect.value} for {effect.duration_turns} turns."
    if effect.type == "apply_status":
        return f"Applied {effect.status} for {effect.duration_turns} turns."
    return "Effect applied."


@router.post("/inventory/equip")
def equip_item(req: EquipItemRequest):
    char_data = _get_char(req.session_id, req.character_name)
    inventory = char_data.get("inventory", [])

    if not any(e["item_id"] == req.item_id for e in inventory):
        raise HTTPException(400, f"'{req.item_id}' not in inventory.")

    item = get_item(req.item_id)
    if not item or item.category != "equipment":
        raise HTTPException(400, "Only equipment items can be equipped.")
    if not item.slot:
        raise HTTPException(400, "Item has no equipment slot.")
    if item.unlock and item.unlock.startswith("race:"):
        required = item.unlock.split("race:")[1]
        if char_data["race"] != required:
            raise HTTPException(400, f"This item requires the {required} race.")

    equipment = char_data.get("equipment", {})
    equipment[item.slot] = req.item_id
    char_data["equipment"] = equipment
    _save_char(req.session_id, char_data)
    return {"status": "equipped", "slot": item.slot, "item": item.name, "equipment": equipment}


@router.delete("/inventory/unequip/{session_id}/{name}/{slot}")
def unequip_slot(session_id: str, name: str, slot: str):
    char_data = _get_char(session_id, name)
    if slot not in ["weapon", "armour", "trinket"]:
        raise HTTPException(400, f"Invalid slot '{slot}'.")
    equipment = char_data.get("equipment", {})
    equipment[slot] = None
    char_data["equipment"] = equipment
    _save_char(session_id, char_data)
    return {"status": "unequipped", "slot": slot}
