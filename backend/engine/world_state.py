"""
engine/world_state.py  (v2 — session-aware)

The living record of Avalon. Now session-scoped: each session has its own
world_state.json. The active session's world is cached in memory and flushed
on every mutation.
"""

import json
from pathlib import Path
from typing import Any

DATA_DIR   = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "world_state.json"   # template / fallback

_active_session_id: str | None = None
_state: dict = {}


def set_active_session(session_id: str) -> None:
    global _active_session_id, _state
    _active_session_id = session_id
    from engine.session_manager import load_session_world
    _state = load_session_world(session_id)


def get_active_session() -> str | None:
    return _active_session_id


def load() -> dict:
    global _state
    if _active_session_id:
        from engine.session_manager import load_session_world
        _state = load_session_world(_active_session_id)
    else:
        with open(STATE_FILE, encoding="utf-8") as f:
            _state = json.load(f)
    return _state


def save() -> None:
    if _active_session_id:
        from engine.session_manager import save_session_world
        save_session_world(_active_session_id, _state)
    else:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2, ensure_ascii=False)


def get() -> dict:
    if not _state:
        load()
    return _state


def get_value(path: str, default: Any = None) -> Any:
    state = get()
    keys  = path.split(".")
    node  = state
    for key in keys:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return default
    return node


def set_value(path: str, value: Any, persist: bool = True) -> None:
    state = get()
    keys  = path.split(".")
    node  = state
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    if persist:
        save()


def adjust_value(path: str, delta: int | float, clamp: tuple | None = None, persist: bool = True) -> Any:
    current = get_value(path, 0)
    updated = current + delta
    if clamp:
        updated = max(clamp[0], min(clamp[1], updated))
    set_value(path, updated, persist=persist)
    return updated


def set_flag(flag: str, value: bool = True, persist: bool = True) -> None:
    set_value(f"flags.{flag}", value, persist=persist)


def get_flag(flag: str) -> bool:
    return bool(get_value(f"flags.{flag}", False))


def log_event(description: str, persist: bool = True) -> None:
    state = get()
    state["world_events_log"].append(description)
    if persist:
        save()


def adjust_faction_influence(faction: str, delta: int, persist: bool = True) -> None:
    adjust_value(f"factions.{faction}.influence", delta, clamp=(0, 100), persist=persist)


def set_npc_disposition(npc: str, disposition: str, persist: bool = True) -> None:
    set_value(f"npc_states.{npc}.disposition", disposition, persist=persist)


def set_region_stability(region: str, stability: str, persist: bool = True) -> None:
    set_value(f"regions.{region}.stability", stability, persist=persist)


def advance_storyline(storyline: str, status: str, persist: bool = True) -> None:
    set_value(f"global_storylines.{storyline}.status", status, persist=persist)


# ── Location accessibility ────────────────────────────────────────────────────

def is_location_accessible(location_name: str) -> bool:
    regions = get_value("regions", {})
    key = _location_key(location_name)
    if key in regions:
        region = regions[key]
        if not region.get("accessible", True):
            return False
        if region.get("stability") == "destroyed":
            return False
    return True


def get_location_state(location_name: str) -> dict:
    regions = get_value("regions", {})
    key = _location_key(location_name)
    return regions.get(key, {})


def destroy_location(location_name: str, persist: bool = True) -> None:
    key = _location_key(location_name)
    set_value(f"regions.{key}.accessible", False, persist=False)
    set_value(f"regions.{key}.stability", "destroyed", persist=False)
    log_event(f"{location_name} has been destroyed.", persist=persist)


def _location_key(location_name: str) -> str:
    return location_name.lower().replace(" ", "_").replace("'", "")


# ── Condition evaluator ───────────────────────────────────────────────────────

def evaluate_condition(condition: dict) -> bool:
    ctype = condition.get("type")

    if ctype == "flag":
        actual = get_flag(condition["flag"])
        return actual == condition.get("value", True)

    if ctype == "faction":
        path   = f"factions.{condition['faction']}.{condition['field']}"
        actual = get_value(path)
        return _compare(actual, condition.get("op", "eq"), condition["value"])

    if ctype == "region":
        path   = f"regions.{condition['region']}.{condition['field']}"
        actual = get_value(path)
        return _compare(actual, condition.get("op", "eq"), condition["value"])

    if ctype == "storyline":
        path   = f"global_storylines.{condition['storyline']}.{condition['field']}"
        actual = get_value(path)
        return _compare(actual, condition.get("op", "eq"), condition["value"])

    if ctype == "world_value":
        actual = get_value(condition["path"])
        return _compare(actual, condition.get("op", "eq"), condition["value"])

    if ctype == "location_accessible":
        return is_location_accessible(condition["location"])

    return True


def evaluate_conditions(conditions: list[dict]) -> bool:
    return all(evaluate_condition(c) for c in conditions)


def _compare(actual: Any, op: str, expected: Any) -> bool:
    ops = {
        "eq":  lambda a, b: a == b,
        "neq": lambda a, b: a != b,
        "gt":  lambda a, b: a >  b,
        "gte": lambda a, b: a >= b,
        "lt":  lambda a, b: a <  b,
        "lte": lambda a, b: a <= b,
    }
    return ops.get(op, lambda a, b: a == b)(actual, expected)


# ── World event applicator ────────────────────────────────────────────────────

def apply_world_effects(effects: list[dict], persist: bool = True) -> list[str]:
    applied = []

    for effect in effects:
        etype = effect.get("type")

        if etype == "set_flag":
            set_flag(effect["flag"], effect.get("value", True), persist=False)
            applied.append(f"Flag set: {effect['flag']} = {effect.get('value', True)}")

        elif etype == "faction_influence":
            new_val = adjust_faction_influence(effect["faction"], effect["delta"], persist=False)
            applied.append(f"{effect['faction']} influence → {new_val}")

        elif etype == "npc_disposition":
            set_npc_disposition(effect["npc"], effect["value"], persist=False)
            applied.append(f"{effect['npc']} disposition → {effect['value']}")

        elif etype == "region_stability":
            set_region_stability(effect["region"], effect["value"], persist=False)
            applied.append(f"{effect['region']} stability → {effect['value']}")

        elif etype == "advance_storyline":
            advance_storyline(effect["storyline"], effect["status"], persist=False)
            applied.append(f"{effect['storyline']} → {effect['status']}")

        elif etype == "log_event":
            log_event(effect["description"], persist=False)
            applied.append(f"World event: {effect['description']}")

        elif etype == "set_world_value":
            set_value(effect["path"], effect["value"], persist=False)
            applied.append(f"{effect['path']} → {effect['value']}")

        elif etype == "destroy_location":
            destroy_location(effect["location"], persist=False)
            applied.append(f"{effect['location']} destroyed")

        elif etype == "set_location_accessible":
            key = _location_key(effect["location"])
            set_value(f"regions.{key}.accessible", effect["value"], persist=False)
            applied.append(f"{effect['location']} accessible → {effect['value']}")

    if persist and applied:
        save()

    return applied
