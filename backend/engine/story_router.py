"""
engine/story_router.py
Resolves player choices against story nodes.
Handles: stat checks, roll outcomes, flag setting, world state effects, arc progression.
"""

from models import Character
from engine.rng import stat_roll
from engine.data_loader import get_story_arc
import engine.world_state as ws


def get_node(arc: str, node_id: str) -> dict:
    story = get_story_arc(arc)
    node  = story["nodes"].get(node_id)
    if not node:
        raise ValueError(f"Node '{node_id}' not found in arc '{arc}'.")
    return node


def interpolate_text(text: str, character: Character) -> str:
    return (text
        .replace("{starting_location}", character.starting_location)
        .replace("{character_name}", character.name)
        .replace("{race}", character.race)
        .replace("{class}", character.character_class)
    )


def filter_choices_by_conditions(choices: list[dict], character: Character) -> list[dict]:
    """
    Remove choices that fail world-state or character-flag conditions.
    Choices without conditions always pass.
    """
    visible = []
    for i, choice in enumerate(choices):
        conditions      = choice.get("conditions", [])
        char_conditions = choice.get("char_conditions", [])

        # World state conditions
        world_ok = ws.evaluate_conditions(conditions) if conditions else True

        # Character flag conditions
        char_ok = True
        for cc in char_conditions:
            flag_val = cc.get("flag") in character.flags
            if cc.get("value", True) != flag_val:
                char_ok = False
                break

        if world_ok and char_ok:
            visible.append({**choice, "_original_index": i})

    return visible


def resolve_choice(character: Character, arc: str, node_id: str, choice_index: int) -> dict:
    """
    Process a player's choice at a given story node.
    choice_index refers to the visible (filtered) choice list.
    """
    node           = get_node(arc, node_id)
    all_choices    = node.get("choices", [])
    visible_choices = filter_choices_by_conditions(all_choices, character)

    if choice_index >= len(visible_choices):
        raise ValueError(f"Choice index {choice_index} out of range.")

    choice      = visible_choices[choice_index]
    stat_check  = choice.get("stat_check")
    leads_to    = choice.get("leads_to")
    roll_result = None
    flags_added = []
    world_changes = []

    # ── No roll: straight branch ──────────────────────────────────────────────
    if stat_check is None:
        next_node = get_node(arc, leads_to)
        text      = interpolate_text(next_node["text"], character)

        if "flag" in next_node:
            flags_added.append(next_node["flag"])

        # Apply world effects defined directly on the destination node
        if "world_effects" in next_node:
            world_changes = ws.apply_world_effects(next_node["world_effects"])

        return _build_response(
            node_id=leads_to,
            text=text,
            roll_result=None,
            node=next_node,
            character=character,
            arc=arc,
            flags_added=flags_added,
            world_changes=world_changes,
        )

    # ── Stat check required ───────────────────────────────────────────────────
    stat_value  = character.current_stats.get(stat_check["stat"])
    dc          = stat_check["dc"]
    roll_result = stat_roll(stat_value, dc)

    gate_node     = get_node(arc, leads_to)
    roll_outcomes = gate_node.get("roll_outcomes", {})

    if roll_result["success"]:
        outcome_key = "success"
    elif "partial" in roll_outcomes and roll_result["roll"] + roll_result["modifier"] >= dc - 2:
        outcome_key = "partial"
    else:
        outcome_key = "failure"
    
    outcome_data = roll_outcomes.get(outcome_key, roll_outcomes.get("failure", {}))

    branch_node_id = outcome_data.get("leads_to", leads_to)
    branch_node    = get_node(arc, branch_node_id)

    text = interpolate_text(outcome_data.get("text", branch_node["text"]), character)

    if "flag" in outcome_data:
        flags_added.append(outcome_data["flag"])

    # World effects from the roll outcome
    if "world_effects" in outcome_data:
        world_changes += ws.apply_world_effects(outcome_data["world_effects"])

    if "world_effects" in branch_node:
        world_changes += ws.apply_world_effects(branch_node["world_effects"])

    return _build_response(
        node_id=branch_node_id,
        text=text,
        roll_result=roll_result,
        node=branch_node,
        character=character,
        arc=arc,
        flags_added=flags_added,
        world_changes=world_changes,
    )


def _build_response(node_id, text, roll_result, node, character, arc, flags_added, world_changes) -> dict:
    all_choices    = node.get("choices", [])
    visible_choices = filter_choices_by_conditions(all_choices, character)

    choices = []
    for i, c in enumerate(visible_choices):
        choices.append({
            "index":      i,
            "text":       c["text"],
            "has_check":  c.get("stat_check") is not None,
            "check_stat": c.get("stat_check", {}).get("stat") if c.get("stat_check") else None,
        })

    return {
        "node_id":       node_id,
        "text":          text,
        "roll_result":   roll_result,
        "choices":       choices,
        "flags_added":   flags_added,
        "world_changes": world_changes,
        "arc_complete":  node.get("arc_complete", False),
        "next_arc":      node.get("next_arc"),
    }
