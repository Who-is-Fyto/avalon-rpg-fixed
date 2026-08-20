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
                    UseItemRequest, EquipItemRequest, AddItemRequest,
                    CombatStartRequest, CombatActionRequest, StatAllocationRequest,
                    RespecRequest, LineageEvolutionRequest, CreateContentRequest)
from engine.character_factory import build_character, validate_class_unlock, get_available_contexts
from engine.rng import stat_roll
from engine.story_router import resolve_choice, get_node, filter_choices_by_conditions
from engine.data_loader import get_story_arc, get_all_classes, get_all_abilities, get_item, item_from_record, ability_from_record
from engine.procedural import generate_item, generate_spell
from engine.encounters import generate_encounter, generate_loot, normalize_region, region_access, difficulty_access, encounter_type_access
from engine.combat_manager import start_combat, resolve_combat_action
from engine.combat_manager import normalize_status
from engine.progression import award_experience, restore_after_combat, recalculate_stats, allocate_stat_points
from engine.customisation import trait_for_character, projected_growth, respec, evolve_lineage
from engine.content_creation import materialize
import engine.world_state as ws
import engine.session_manager as sm

router = APIRouter(prefix="/game", tags=["Game"])


# ── Inline request models ─────────────────────────────────────────────────────

class StoryNodeRequest(BaseModel):
    session_id: str
    arc: str
    node_id: str
    character_name: str


class GenerateItemRequest(BaseModel):
    session_id: str
    character_name: str
    base_item_id: str
    seed: Optional[str] = None
    rarity: Optional[str] = None
    level: int = 1
    add_to_inventory: bool = True


class GenerateSpellRequest(BaseModel):
    session_id: str
    character_name: str
    base_ability_name: str
    seed: Optional[str] = None
    rarity: Optional[str] = None
    level: int = 1
    learn: bool = True


class GeneratedCombatStartRequest(BaseModel):
    session_id: str
    character_name: str
    region: Optional[str] = None
    seed: Optional[str] = None
    difficulty: str = "standard"
    encounter_type: str = "patrol"


class RegionUnlockRequest(BaseModel):
    session_id: str
    character_name: str
    region: str


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


def _resolve_item(char_data: dict, item_ref: str):
    generated = char_data.get("generated_items", {}).get(item_ref)
    if generated:
        return item_from_record(generated)
    return get_item(item_ref)


def _resolve_ability(char_data: dict, ability_ref: str):
    generated = char_data.get("generated_abilities", {}).get(ability_ref)
    if generated:
        return ability_from_record(generated)
    for record in char_data.get("generated_abilities", {}).values():
        if record.get("name", "").lower() == ability_ref.lower():
            return ability_from_record(record)
    for ability in get_all_abilities():
        if ability.name.lower() == ability_ref.lower():
            return ability
    return None


def _item_lookup_for(char_data: dict):
    return lambda item_ref: _resolve_item(char_data, item_ref)


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
            req.starting_location, req.context_id, req.secondary_race, req.hybrid_ratio
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    char_data = character.model_dump()
    char_data["session_id"] = req.session_id
    _save_char(req.session_id, char_data)

    ws.log_event(
        f"{req.name} the {character.race} {req.character_class} began their story "
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
    known = [all_abilities[a] for a in model.known_abilities if a in all_abilities]
    known.extend(record for name in model.known_abilities for record in model.generated_abilities.values() if record.get("name") == name)
    actives   = [a for a in known if a["type"] == "active"]
    passives  = [a for a in known if a["type"] == "passive"]
    ultimates = [a for a in known if a["type"] == "ultimate"]

    inventory_resolved = []
    total_weight = 0.0
    for entry in model.inventory:
        item = _resolve_item(char, entry.instance_id or entry.item_id)
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
            item = _resolve_item(char, item_id)
            equipped_resolved[slot] = item.model_dump() if item else None
        else:
            equipped_resolved[slot] = None

    world = ws.get()
    faction_snapshot = {
        k: {"influence": v["influence"], "disposition": v["disposition_to_player"]}
        for k, v in world.get("factions", {}).items()
    }

    loc_state = ws.get_location_state(model.starting_location)

    hazard_sources = {"base": dict(char.get("base_hazard_resistances", {})), "equipment": {}, "abilities": {}}
    hazard_totals = dict(model.hazard_resistances or {})
    for slot, item in equipped_resolved.items():
        if item and item.get("hazard_resistances"):
            hazard_sources["equipment"][slot] = item["hazard_resistances"]
    for ability in known:
        if ability.get("hazard_resistances"):
            hazard_sources["abilities"][ability.get("name", "ability")] = ability["hazard_resistances"]
            if ability.get("type") == "passive":
                for hazard, value in ability["hazard_resistances"].items():
                    hazard_totals[hazard] = min(1.0, float(hazard_totals.get(hazard, 0.0)) + float(value))

    return {
        "identity": {
            "name":                   model.name,
            "race":                   model.race,
            "race_components":        model.race_components,
            "hybrid_ratio":           model.hybrid_ratio,
            "secondary_affinity":     model.secondary_affinity,
            "growth_profile":         model.growth_profile,
            "lineage_trait":          model.lineage_trait,
            "hybrid_affinity":        model.hybrid_affinity,
            "stat_allocations":       model.stat_allocations,
            "respec_count":           model.respec_count,
            "lineage_evolution_count": model.lineage_evolution_count,
            "class":                  model.character_class,
            "level":                  model.level,
            "experience":             model.experience,
            "unspent_stat_points":    model.unspent_stat_points,
            "starting_location":      model.starting_location,
            "starting_context":       model.starting_context,
            "starting_context_label": model.starting_context_label,
            "affinity":               model.affinity,
            "elemental_resistances":  model.elemental_resistances,
            "hazard_resistances":     model.hazard_resistances,
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
        "hazard_resistance_breakdown": {"totals": hazard_totals, "sources": hazard_sources},
        "progression": {"history": model.growth_history, "projection": projected_growth(char, max(12, model.level))},
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


# ── Progression ────────────────────────────────────────────────────────────────

@router.post("/character/{session_id}/{name}/allocate-stats")
def allocate_stats(session_id: str, name: str, req: StatAllocationRequest):
    if req.session_id != session_id or req.character_name != name:
        raise HTTPException(400, "Request character and session do not match the URL.")
    char_data = _get_char(session_id, name)
    try:
        allocation = allocate_stat_points(char_data, req.allocations)
    except ValueError as e:
        raise HTTPException(400, str(e))
    recalculate_stats(char_data, _item_lookup_for(char_data))
    _save_char(session_id, char_data)
    return {"status": "allocated", "allocation": allocation, "character": char_data}


@router.post("/character/{session_id}/{name}/respec")
def respec_character(session_id: str, name: str, req: RespecRequest):
    if req.session_id != session_id or req.character_name != name:
        raise HTTPException(400, "Request character and session do not match the URL.")
    char_data = _get_char(session_id, name)
    if int(char_data.get("level", 1)) < 10:
        raise HTTPException(400, "Respec unlocks at level 10.")
    try:
        result = respec(char_data, req.allocations)
        recalculate_stats(char_data, _item_lookup_for(char_data))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _save_char(session_id, char_data)
    return {"status": "respecced", "result": result, "character": char_data}


@router.post("/character/{session_id}/{name}/lineage-evolve")
def evolve_character_lineage(session_id: str, name: str, req: LineageEvolutionRequest):
    if req.session_id != session_id or req.character_name != name:
        raise HTTPException(400, "Request character and session do not match the URL.")
    char_data = _get_char(session_id, name)
    try:
        result = evolve_lineage(char_data, req.target_race, req.target_secondary_race)
        recalculate_stats(char_data, _item_lookup_for(char_data))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _save_char(session_id, char_data)
    return {"status": "lineage_evolved", "result": result, "character": char_data}


@router.get("/character/{session_id}/{name}/growth")
def character_growth(session_id: str, name: str, through_level: int = 60):
    char_data = _get_char(session_id, name)
    return {"projection": projected_growth(char_data, through_level), "history": char_data.get("growth_history", [])}


@router.post("/creation/{session_id}/{name}")
def create_custom_content(session_id: str, name: str, req: CreateContentRequest):
    if req.session_id != session_id or req.character_name != name:
        raise HTTPException(400, "Request character and session do not match the URL.")
    char_data = _get_char(session_id, name)
    try:
        record = materialize(req.content_type, req.payload, f"{session_id}:{name}")
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    if req.content_type.lower() in {"ability", "skill", "spell"}:
        char_data.setdefault("generated_abilities", {})[record["instance_id"]] = record
        if record["name"] not in char_data.setdefault("known_abilities", []):
            char_data["known_abilities"].append(record["name"])
    else:
        char_data.setdefault("generated_items", {})[record["instance_id"]] = record
        char_data.setdefault("inventory", []).append({"item_id": record["instance_id"], "quantity": 1, "instance_id": record["instance_id"]})
    _save_char(session_id, char_data)
    return {"status": "created", "content": record, "character": char_data}


# ── Combat and Conixia ─────────────────────────────────────────────────────────

@router.post("/combat/start")
def combat_start(req: CombatStartRequest):
    char_data = _get_char(req.session_id, req.character_name)
    if char_data.get("combat_state"):
        raise HTTPException(400, "This character is already in combat.")
    if not req.enemies or len(req.enemies) > 8:
        raise HTTPException(400, "Combat requires between 1 and 8 enemies.")
    try:
        state = start_combat(_to_model(char_data), req.enemies)
    except ValueError as e:
        raise HTTPException(400, str(e))
    char_data["combat_state"] = state
    _save_char(req.session_id, char_data)
    return {"status": "started", "combat": state, "character": char_data}


@router.get("/regions/{session_id}/{name}")
def region_progress(session_id: str, name: str):
    char_data = _get_char(session_id, name)
    config = __import__("engine.encounters", fromlist=["_progression_config"])._progression_config()
    result = []
    for region, rule in config.get("regions", {}).items():
        allowed, reason = region_access(char_data, region, ws.get())
        result.append({"region": region, "unlocked": region in char_data.get("unlocked_regions", []) or normalize_region(char_data.get("starting_location", "")) == region, "available": allowed, "reason": reason, "recommended_level": rule.get("recommended_level", rule.get("min_level", 1)), "min_level": rule.get("min_level", 1)})
    return {"regions": result, "unlocked_regions": char_data.get("unlocked_regions", [])}


@router.post("/regions/unlock")
def unlock_region(req: RegionUnlockRequest):
    char_data = _get_char(req.session_id, req.character_name)
    region = normalize_region(req.region)
    allowed, reason = region_access(char_data, region, ws.get())
    if not allowed:
        raise HTTPException(403, reason)
    unlocked = char_data.setdefault("unlocked_regions", [])
    if region not in unlocked:
        unlocked.append(region)
    _save_char(req.session_id, char_data)
    return {"status": "unlocked", "region": region, "unlocked_regions": unlocked}


@router.post("/combat/start-generated")
def combat_start_generated(req: GeneratedCombatStartRequest):
    char_data = _get_char(req.session_id, req.character_name)
    region = normalize_region(req.region or char_data.get("starting_location", "default"))
    allowed, reason = region_access(char_data, region, ws.get())
    if not allowed:
        raise HTTPException(403, reason)
    allowed, reason = difficulty_access(char_data, req.difficulty)
    if not allowed:
        raise HTTPException(400, reason)
    allowed, reason = encounter_type_access(char_data, req.encounter_type)
    if not allowed:
        raise HTTPException(400, reason)
    seed = req.seed or f"{req.session_id}:{req.character_name}:{region}:{char_data.get('level', 1)}:{req.difficulty}"
    world_regions = ws.get().get("regions", {})
    region_state = world_regions.get(region, {})
    try:
        encounter = generate_encounter(region, char_data.get("level", 1), seed, region_state, req.difficulty, req.encounter_type, ws.get())
        state = start_combat(_to_model(char_data), encounter["enemies"])
        state["environmental_hazards"] = []
        hazard_resistances = state.get("player_hazard_resistances", {})
        for hazard in encounter.get("hazards", []):
            hazard_record = dict(hazard)
            resistance = min(1.0, float(hazard_resistances.get(hazard.get("id"), 0.0)) + float(hazard_resistances.get(hazard.get("status"), 0.0)))
            hazard_record["resistance"] = resistance
            hazard_record["resisted"] = resistance >= 1.0
            hazard_record["effective_turns"] = max(0, int(round(int(hazard.get("turns", 1)) * (1.0 - resistance))))
            hazard_record["effective_value"] = max(0, int(round(int(hazard.get("value", 0)) * (1.0 - resistance))))
            state["environmental_hazards"].append(hazard_record)
            if hazard_record["effective_turns"] > 0:
                state.setdefault("player_statuses", []).append(normalize_status({"name": hazard.get("status"), "turns": hazard_record["effective_turns"], "value": hazard_record["effective_value"], "source": "environment", "element": hazard.get("element")}, source="environment"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    state["encounter"] = {key: encounter[key] for key in ("region", "seed", "encounter_seed", "player_level", "difficulty", "encounter_type", "danger_modifier", "budget_used", "budget_limit", "hazard_budget_modifier", "loot_bias")}
    state["encounter"]["enemy_count"] = len(encounter["enemies"])
    char_data["combat_state"] = state
    _save_char(req.session_id, char_data)
    return {"status": "started", "encounter": encounter, "combat": state, "character": char_data}


@router.get("/combat/{session_id}/{name}")
def combat_state(session_id: str, name: str):
    char_data = _get_char(session_id, name)
    return {"active": bool(char_data.get("combat_state")), "combat": char_data.get("combat_state")}


@router.post("/combat/action")
def combat_action(req: CombatActionRequest):
    char_data = _get_char(req.session_id, req.character_name)
    state = char_data.get("combat_state")
    if not state:
        raise HTTPException(400, "This character is not in combat.")
    before_xp = sum(int(enemy.get("xp", 0)) for enemy in state.get("enemies", []))
    combat_character = _to_model(char_data)
    try:
        result = resolve_combat_action(
            combat_character, state, req.action_type,
            req.target_index, req.ability_name
        )
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e))

    # The combat engine mutates the model, so copy mutable vitals back to the
    # persisted character record after every action.
    result_character = combat_character
    char_data["hp"] = result_character.hp
    char_data["conixia_energy"] = result_character.conixia_energy
    char_data["stamina"] = result_character.stamina

    progression = None
    loot = None
    # Persist item-origin statuses with their remaining turns and metadata.
    char_data["active_buffs"] = []
    for status in state.get("player_statuses", []):
        if status.get("source") == "item":
            char_data["active_buffs"].append({
                "type": status.get("type", "status"),
                "status": status.get("status"),
                "stat": status.get("stat"),
                "value": status.get("value", 0),
                "turns_remaining": status.get("turns", 0),
                "source": "item",
            })

    if state.get("is_over"):
        if state.get("winner") == "player":
            progression = award_experience(char_data, before_xp)
            encounter_meta = state.get("encounter")
            if encounter_meta:
                loot = generate_loot(
                    encounter_meta.get("region", "default"),
                    char_data.get("level", 1),
                    encounter_meta.get("encounter_seed", ""),
                    defeated_count=int(encounter_meta.get("enemy_count", 1)),
                    difficulty=encounter_meta.get("difficulty", "standard"),
                    encounter_type=encounter_meta.get("encounter_type", "patrol"),
                    loot_bias=float(encounter_meta.get("loot_bias", 0.0)),
                    defeated_enemy_ids=list(combat_state.get("defeated_enemy_ids", [])),
                    region_state=ws.get().get("regions", {}).get(encounter_meta.get("region", ""), {}),
                )
                char_data["gold"] = int(char_data.get("gold", 0)) + int(loot.get("gold", 0))
                for item in loot.get("items", []):
                    inventory = char_data.setdefault("inventory", [])
                    if item.get("instance_id"):
                        char_data.setdefault("generated_items", {})[item["instance_id"]] = item
                        inventory.append({"item_id": item["instance_id"], "instance_id": item["instance_id"], "quantity": 1})
                    else:
                        item_id = item["id"]
                        quantity = int(item.get("drop_quantity", 1))
                        existing = next((entry for entry in inventory if entry.get("item_id") == item_id and not entry.get("instance_id")), None)
                        if existing:
                            existing["quantity"] = int(existing.get("quantity", 0)) + quantity
                        else:
                            inventory.append({"item_id": item_id, "quantity": quantity})
        restore_after_combat(char_data)
    else:
        char_data["combat_state"] = state
    recalculate_stats(char_data, _item_lookup_for(char_data))
    _save_char(req.session_id, char_data)
    return {
        "status": "resolved",
        "result": result,
        "combat": None if state.get("is_over") else state,
        "winner": state.get("winner"),
        "progression": progression,
        "loot": loot,
        "character": char_data,
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

    if result.get("flags_added") or result.get("flags_removed"):
        flags = set(char_data.get("flags", []))
        flags.update(result.get("flags_added", []))
        flags.difference_update(result.get("flags_removed", []))
        char_data["flags"] = sorted(flags)

    if result.get("gold_delta"):
        char_data["gold"] = max(0, char_data.get("gold", 0) + result["gold_delta"])

    # On prologue complete, advance world state
    if result.get("arc_complete") and req.arc == "prologue":
        ws.set_flag("prologue_complete", True)
        ws.set_flag("aim_first_contact", True)
        ws.adjust_faction_influence("aim", 5)
        ws.log_event(f"{req.character_name} completed the prologue.")

    _save_char(req.session_id, char_data)
    return result


# ── Procedural generation ─────────────────────────────────────────────────────

@router.post("/generation/item")
def generate_item_instance(req: GenerateItemRequest):
    char_data = _get_char(req.session_id, req.character_name)
    base = get_item(req.base_item_id)
    if not base:
        raise HTTPException(404, f"Base item '{req.base_item_id}' not found.")
    seed = req.seed or f"{req.session_id}:{req.character_name}:item:{len(char_data.get('generated_items', {})) + 1}"
    try:
        generated = generate_item(base.model_dump(), seed, max(1, req.level), req.rarity)
    except ValueError as e:
        raise HTTPException(400, str(e))
    char_data.setdefault("generated_items", {})[generated["instance_id"]] = generated
    if req.add_to_inventory:
        char_data.setdefault("inventory", []).append({"item_id": generated["instance_id"], "instance_id": generated["instance_id"], "quantity": 1})
    _save_char(req.session_id, char_data)
    return {"status": "generated", "item": generated, "added_to_inventory": req.add_to_inventory}


@router.post("/generation/spell")
def generate_spell_instance(req: GenerateSpellRequest):
    char_data = _get_char(req.session_id, req.character_name)
    base = next((a for a in get_all_abilities() if a.name.lower() == req.base_ability_name.lower()), None)
    if not base:
        raise HTTPException(404, f"Base ability '{req.base_ability_name}' not found.")
    seed = req.seed or f"{req.session_id}:{req.character_name}:spell:{len(char_data.get('generated_abilities', {})) + 1}"
    try:
        generated = generate_spell(base.model_dump(), seed, max(1, req.level), req.rarity)
    except ValueError as e:
        raise HTTPException(400, str(e))
    char_data.setdefault("generated_abilities", {})[generated["instance_id"]] = generated
    if req.learn and generated["name"] not in char_data.setdefault("known_abilities", []):
        char_data["known_abilities"].append(generated["name"])
    _save_char(req.session_id, char_data)
    return {"status": "generated", "spell": generated, "learned": req.learn}


@router.get("/generation/rarities")
def get_rarity_catalog():
    from engine.procedural import RARITIES
    return {"rarities": RARITIES}


# ── Inventory ─────────────────────────────────────────────────────────────────

@router.post("/inventory/add")
def add_item(req: AddItemRequest):
    char_data = _get_char(req.session_id, req.character_name)
    item = _resolve_item(char_data, req.item_id)
    if not item:
        raise HTTPException(404, f"Item '{req.item_id}' not found.")

    inventory = char_data.get("inventory", [])
    if item.stackable:
        for entry in inventory:
            if (entry.get("instance_id") or entry["item_id"]) == req.item_id:
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

    entry = next((e for e in inventory if (e.get("instance_id") or e["item_id"]) == req.item_id), None)
    if not entry or entry["quantity"] < 1:
        raise HTTPException(400, f"'{req.item_id}' not in inventory.")

    item = _resolve_item(char_data, req.item_id)
    if not item:
        raise HTTPException(404, f"Item '{req.item_id}' not found.")
    if item.category == "equipment":
        raise HTTPException(400, "Equip equipment items using /inventory/equip.")

    result_msg = _apply_item_effect(char_data, item)

    entry["quantity"] -= 1
    char_data["inventory"] = (
        [e for e in inventory if (e.get("instance_id") or e["item_id"]) != req.item_id]
        if entry["quantity"] <= 0 else inventory
    )

    recalculate_stats(char_data, _item_lookup_for(char_data))
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
            {"type": "regen_hp", "name": "regen_hp", "value": effect.value, "turns_remaining": effect.duration_turns, "source": "item"}
        )
        return f"Regen active: +{effect.value} HP for {effect.duration_turns} turns."
    if effect.type == "buff_stat":
        char_data.setdefault("active_buffs", []).append(
            {"type": "buff_stat", "name": "buff_stat", "stat": effect.stat, "value": effect.value,
             "turns_remaining": effect.duration_turns, "source": "item"}
        )
        char_data["current_stats"][effect.stat] = (
            char_data["current_stats"].get(effect.stat, 0) + effect.value
        )
        return f"{effect.stat} +{effect.value} for {effect.duration_turns} turns."
    if effect.type == "apply_status":
        char_data.setdefault("active_buffs", []).append(
            {"type": "status", "name": effect.status, "status": effect.status, "turns_remaining": effect.duration_turns or 1, "source": "item"}
        )
        return f"Applied {effect.status} for {effect.duration_turns or 1} turns."
    if effect.type == "grant_ability_temp" and effect.ability:
        if effect.ability not in char_data.setdefault("known_abilities", []):
            char_data["known_abilities"].append(effect.ability)
        char_data.setdefault("temporary_abilities", []).append({
            "name": effect.ability,
            "encounters_remaining": effect.duration_encounters or 1,
        })
        return f"Granted {effect.ability} for {effect.duration_encounters or 1} encounter(s)."
    return "Effect applied."


@router.post("/inventory/equip")
def equip_item(req: EquipItemRequest):
    char_data = _get_char(req.session_id, req.character_name)
    inventory = char_data.get("inventory", [])

    if not any((e.get("instance_id") or e["item_id"]) == req.item_id for e in inventory):
        raise HTTPException(400, f"'{req.item_id}' not in inventory.")

    item = _resolve_item(char_data, req.item_id)
    if not item or item.category not in {"equipment", "trinket"}:
        raise HTTPException(400, "Only equipment or trinket items can be equipped.")
    if not item.slot:
        raise HTTPException(400, "Item has no equipment slot.")
    if item.unlock and item.unlock.startswith("race:"):
        required = item.unlock.split("race:")[1]
        if char_data["race"] != required:
            raise HTTPException(400, f"This item requires the {required} race.")

    equipment = char_data.get("equipment", {})
    equipment[item.slot] = item.instance_id or req.item_id
    char_data["equipment"] = equipment
    recalculate_stats(char_data, _item_lookup_for(char_data))
    _save_char(req.session_id, char_data)
    return {"status": "equipped", "slot": item.slot, "item": item.name, "equipment": equipment, "current_stats": char_data["current_stats"]}


@router.delete("/inventory/unequip/{session_id}/{name}/{slot}")
def unequip_slot(session_id: str, name: str, slot: str):
    char_data = _get_char(session_id, name)
    if slot not in ["weapon", "armour", "trinket"]:
        raise HTTPException(400, f"Invalid slot '{slot}'.")
    equipment = char_data.get("equipment", {})
    equipment[slot] = None
    char_data["equipment"] = equipment
    recalculate_stats(char_data, _item_lookup_for(char_data))
    _save_char(session_id, char_data)
    return {"status": "unequipped", "slot": slot, "current_stats": char_data["current_stats"]}
