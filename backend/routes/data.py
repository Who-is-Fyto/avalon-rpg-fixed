from fastapi import APIRouter, HTTPException
from engine.data_loader import get_all_races, get_all_classes, get_all_abilities, get_all_items, get_race, get_class, get_item
import engine.world_state as ws

router = APIRouter(prefix="/data", tags=["Data"])

@router.get("/races")
def list_races():
    return [r.model_dump() for r in get_all_races()]

@router.get("/races/{name}")
def get_race_detail(name: str):
    race = get_race(name)
    if not race:
        raise HTTPException(404, f"Race '{name}' not found.")
    return race.model_dump()

@router.get("/classes")
def list_classes():
    return [c.model_dump() for c in get_all_classes()]

@router.get("/classes/{name}")
def get_class_detail(name: str):
    cls = get_class(name)
    if not cls:
        raise HTTPException(404, f"Class '{name}' not found.")
    return cls.model_dump()

@router.get("/abilities")
def list_abilities():
    return [a.model_dump() for a in get_all_abilities()]

@router.get("/items")
def list_items(category: str | None = None):
    items = get_all_items()
    if category:
        items = [i for i in items if i.category == category]
    return [i.model_dump() for i in items]

@router.get("/items/{item_id}")
def get_item_detail(item_id: str):
    item = get_item(item_id)
    if not item:
        raise HTTPException(404, f"Item '{item_id}' not found.")
    return item.model_dump()

@router.get("/world-state")
def get_world_state():
    return ws.get()

@router.get("/world-state/factions")
def get_factions():
    return ws.get_value("factions", {})

@router.get("/world-state/regions")
def get_regions():
    return ws.get_value("regions", {})

@router.get("/world-state/storylines")
def get_storylines():
    return ws.get_value("global_storylines", {})
