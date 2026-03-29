"""
routes/sessions.py
Session and save management endpoints.
"""

from fastapi import APIRouter, HTTPException
from models import SessionCreateRequest
import engine.session_manager as sm
import engine.world_state as ws

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get("/")
def list_sessions():
    """List all sessions with metadata and character counts."""
    return sm.list_sessions()


@router.post("/")
def create_session(req: SessionCreateRequest):
    """Create a new session with a fresh world state."""
    meta = sm.create_session(req.display_name)
    return {"status": "created", **meta}


@router.get("/{session_id}")
def get_session(session_id: str):
    meta = sm.get_session_meta(session_id)
    if not meta:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    chars = sm.list_characters(session_id)
    return {**meta, "characters": chars}


@router.delete("/{session_id}")
def delete_session(session_id: str):
    ok = sm.delete_session(session_id)
    if not ok:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    return {"status": "deleted", "session_id": session_id}


@router.get("/{session_id}/world")
def get_session_world(session_id: str):
    """Get the world state for a session."""
    try:
        return sm.load_session_world(session_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Session '{session_id}' not found.")


@router.get("/{session_id}/characters")
def list_session_characters(session_id: str):
    meta = sm.get_session_meta(session_id)
    if not meta:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    return sm.list_characters(session_id)


@router.delete("/{session_id}/characters/{character_name}")
def delete_character(session_id: str, character_name: str):
    ok = sm.delete_character(session_id, character_name)
    if not ok:
        raise HTTPException(404, f"Character '{character_name}' not found in session '{session_id}'.")
    return {"status": "deleted", "character": character_name}
