"""
engine/session_manager.py

The Session/Save Manager for Avalon RPG.

Architecture:
  sessions/
    session_001/
      meta.json          ← session metadata (name, created, last played)
      world_state.json   ← shared living world for this session
      players/
        ara.json         ← individual character save
        dren.json

A Session is a shared world. Multiple characters can exist in the same
session and their actions affect each other's world. Starting fresh means
creating a new session with a clean world_state.json.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from models import Character, StatBlock, EquipmentSlots, InventoryEntry

# ── Paths ─────────────────────────────────────────────────────────────────────

BACKEND_DIR  = Path(__file__).parent.parent
SESSIONS_DIR = BACKEND_DIR / "sessions"
TEMPLATE_WS  = BACKEND_DIR / "data" / "world_state.json"

SESSIONS_DIR.mkdir(exist_ok=True)


# ── Session helpers ───────────────────────────────────────────────────────────

def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / session_id

def _meta_path(session_id: str) -> Path:
    return _session_path(session_id) / "meta.json"

def _world_path(session_id: str) -> Path:
    return _session_path(session_id) / "world_state.json"

def _players_dir(session_id: str) -> Path:
    return _session_path(session_id) / "players"

def _player_path(session_id: str, character_name: str) -> Path:
    safe = character_name.lower().replace(" ", "_")
    return _players_dir(session_id) / f"{safe}.json"


# ── Session lifecycle ─────────────────────────────────────────────────────────

def list_sessions() -> list[dict]:
    """Return all sessions sorted by last_played descending."""
    sessions = []
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_file = d / "meta.json"
        if not meta_file.exists():
            continue
        with open(meta_file, encoding="utf-8") as f:
            meta = json.load(f)
        # Count characters
        players_d = d / "players"
        char_count = len(list(players_d.glob("*.json"))) if players_d.exists() else 0
        sessions.append({**meta, "character_count": char_count})
    return sorted(sessions, key=lambda s: s.get("last_played", ""), reverse=True)


def create_session(display_name: str = "") -> dict:
    """Create a new session with a fresh world state."""
    # Generate ID
    existing = [d.name for d in SESSIONS_DIR.iterdir() if d.is_dir()]
    nums = []
    for name in existing:
        if name.startswith("session_"):
            try:
                nums.append(int(name.split("_")[1]))
            except (IndexError, ValueError):
                pass
    next_num = max(nums, default=0) + 1
    session_id = f"session_{next_num:03d}"

    session_dir = _session_path(session_id)
    session_dir.mkdir()
    _players_dir(session_id).mkdir()

    # Copy clean world state template
    shutil.copy(TEMPLATE_WS, _world_path(session_id))

    now = _now()
    meta = {
        "session_id":   session_id,
        "display_name": display_name or f"Session {next_num}",
        "created":      now,
        "last_played":  now,
    }
    with open(_meta_path(session_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return meta


def get_session_meta(session_id: str) -> dict | None:
    p = _meta_path(session_id)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _touch_session(session_id: str) -> None:
    """Update last_played timestamp."""
    p = _meta_path(session_id)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        meta = json.load(f)
    meta["last_played"] = _now()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def delete_session(session_id: str) -> bool:
    d = _session_path(session_id)
    if not d.exists():
        return False
    shutil.rmtree(d)
    return True


# ── World state per session ───────────────────────────────────────────────────

def load_session_world(session_id: str) -> dict:
    """Load the world state for a specific session into memory."""
    p = _world_path(session_id)
    if not p.exists():
        raise FileNotFoundError(f"Session '{session_id}' world state not found.")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_session_world(session_id: str, state: dict) -> None:
    """Flush a world state dict back to the session's file."""
    with open(_world_path(session_id), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    _touch_session(session_id)


# ── Character saves ───────────────────────────────────────────────────────────

def list_characters(session_id: str) -> list[dict]:
    """Return summary of all characters in a session."""
    players_d = _players_dir(session_id)
    if not players_d.exists():
        return []
    chars = []
    for p in players_d.glob("*.json"):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        chars.append({
            "name":              data.get("name"),
            "race":              data.get("race"),
            "character_class":   data.get("character_class"),
            "level":             data.get("level", 1),
            "starting_location": data.get("starting_location"),
            "starting_context":  data.get("starting_context", ""),
            "last_saved":        data.get("last_saved", ""),
        })
    return sorted(chars, key=lambda c: c.get("last_saved", ""), reverse=True)


def save_character(session_id: str, character_data: dict) -> None:
    """Persist a character dict to the session's players folder."""
    character_data = {**character_data, "last_saved": _now(), "session_id": session_id}
    path = _player_path(session_id, character_data["name"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(character_data, f, indent=2, ensure_ascii=False)
    _touch_session(session_id)


def load_character(session_id: str, character_name: str) -> dict | None:
    path = _player_path(session_id, character_name)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def character_exists(session_id: str, character_name: str) -> bool:
    return _player_path(session_id, character_name).exists()


def delete_character(session_id: str, character_name: str) -> bool:
    path = _player_path(session_id, character_name)
    if not path.exists():
        return False
    path.unlink()
    return True


# ── Utility ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
