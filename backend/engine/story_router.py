"""
engine/story_router.py
Resolves player choices against story nodes.
Handles stat checks, roll outcomes, character flags, gold changes,
world-state effects, and arc progression.
"""

from models import Character
from engine.rng import stat_roll
from engine.data_loader import get_story_arc
import engine.world_state as ws


def get_node(arc: str, node_id: str) -> dict:
    story = get_story_arc(arc)
    node = story["nodes"].get(node_id)
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
    """Remove choices that fail world-state or character-flag conditions."""
    visible = []
    for i, choice in enumerate(choices):
        conditions = choice.get("conditions", [])
        char_conditions = choice.get("char_conditions", [])
        world_ok = ws.evaluate_conditions(conditions) if conditions else True
        char_ok = True
        for cc in char_conditions:
            flag_val = cc.get("flag") in character.flags
            if cc.get("value", True) != flag_val:
                char_ok = False
                break
        if world_ok and char_ok:
            visible.append({**choice, "_original_index": i})
    return visible


def _apply_effects(effects: list[dict] | None, flags_added: list[str], flags_removed: list[str]) -> tuple[list[str], int]:
    """Apply mixed legacy/current effects and return world log entries plus gold delta."""
    if not effects:
        return [], 0

    world_effects = []
    gold_delta = 0
    world_changes = []
    for effect in effects:
        etype = effect.get("type")
        if etype == "add_gold":
            gold_delta += int(effect.get("value", 0))
            world_changes.append(f"Gold +{int(effect.get('value', 0))}")
        elif etype == "remove_gold":
            amount = int(effect.get("value", 0))
            gold_delta -= amount
            world_changes.append(f"Gold -{amount}")
        elif etype == "flag":
            flag = effect.get("flag")
            if flag:
                if effect.get("value", True):
                    flags_added.append(flag)
                else:
                    flags_removed.append(flag)
        else:
            # Story files use both the modern set_flag/set_world_value names
            # and the older flag/world_value names. Normalize the latter.
            if etype == "flag":
                effect = {**effect, "type": "set_flag"}
            elif etype == "world_value":
                effect = {**effect, "type": "set_world_value"}
            world_effects.append(effect)

    if world_effects:
        world_changes.extend(ws.apply_world_effects(world_effects))
    return world_changes, gold_delta


def _build_response(node_id, text, roll_result, node, character, arc,
                    flags_added, flags_removed, world_changes, gold_delta) -> dict:
    visible_choices = filter_choices_by_conditions(node.get("choices", []), character)
    choices = [{
        "index": i,
        "text": c["text"],
        "has_check": c.get("stat_check") is not None,
        "check_stat": c.get("stat_check", {}).get("stat") if c.get("stat_check") else None,
    } for i, c in enumerate(visible_choices)]
    return {
        "node_id": node_id,
        "text": text,
        "roll_result": roll_result,
        "choices": choices,
        "flags_added": list(dict.fromkeys(flags_added)),
        "flags_removed": list(dict.fromkeys(flags_removed)),
        "world_changes": world_changes,
        "gold_delta": gold_delta,
        "arc_complete": node.get("arc_complete", False),
        "next_arc": node.get("next_arc"),
    }


def resolve_choice(character: Character, arc: str, node_id: str, choice_index: int) -> dict:
    """Process a player's choice. choice_index refers to visible choices."""
    node = get_node(arc, node_id)
    visible_choices = filter_choices_by_conditions(node.get("choices", []), character)
    if choice_index < 0 or choice_index >= len(visible_choices):
        raise ValueError(f"Choice index {choice_index} out of range.")

    choice = visible_choices[choice_index]
    stat_check = choice.get("stat_check")
    leads_to = choice.get("leads_to")
    flags_added: list[str] = []
    flags_removed: list[str] = []
    world_changes: list[str] = []
    gold_delta = 0

    # Effects attached directly to a choice must fire before the next node loads.
    changes, delta = _apply_effects(choice.get("world_effects"), flags_added, flags_removed)
    world_changes.extend(changes)
    gold_delta += delta
    if choice.get("flag"):
        flags_added.append(choice["flag"])

    if stat_check is None:
        next_node = get_node(arc, leads_to)
        changes, delta = _apply_effects(next_node.get("world_effects"), flags_added, flags_removed)
        world_changes.extend(changes)
        gold_delta += delta
        if next_node.get("flag"):
            flags_added.append(next_node["flag"])
        return _build_response(
            leads_to, interpolate_text(next_node["text"], character), None,
            next_node, character, arc, flags_added, flags_removed,
            world_changes, gold_delta
        )

    stat_value = character.current_stats.get(stat_check["stat"])
    dc = stat_check["dc"]
    roll_result = stat_roll(stat_value, dc)
    gate_node = get_node(arc, leads_to)
    roll_outcomes = gate_node.get("roll_outcomes", {})
    if roll_result["success"]:
        outcome_key = "success"
    elif "partial" in roll_outcomes and roll_result["roll"] + roll_result["modifier"] >= dc - 2:
        outcome_key = "partial"
    else:
        outcome_key = "failure"

    outcome_data = roll_outcomes.get(outcome_key, roll_outcomes.get("failure", {}))
    branch_node_id = outcome_data.get("leads_to", leads_to)
    branch_node = get_node(arc, branch_node_id)
    changes, delta = _apply_effects(outcome_data.get("world_effects"), flags_added, flags_removed)
    world_changes.extend(changes)
    gold_delta += delta
    changes, delta = _apply_effects(branch_node.get("world_effects"), flags_added, flags_removed)
    world_changes.extend(changes)
    gold_delta += delta
    if outcome_data.get("flag"):
        flags_added.append(outcome_data["flag"])
    if branch_node.get("flag"):
        flags_added.append(branch_node["flag"])

    return _build_response(
        branch_node_id,
        interpolate_text(outcome_data.get("text", branch_node["text"]), character),
        roll_result, branch_node, character, arc, flags_added, flags_removed,
        world_changes, gold_delta
    )
