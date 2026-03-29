"""
engine/event_system.py
Event Bus for decoupled communication between game systems.
Allows combat, items, and story nodes to trigger world-state changes.
"""

from typing import Callable, Dict, List, Any
import engine.world_state as ws

class EventBus:
    def __init__(self):
        self.listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)

    def publish(self, event_type: str, data: Any):
        if event_type in self.listeners:
            for callback in self.listeners[event_type]:
                callback(data)

# Global Event Bus Instance
bus = EventBus()

# --- Default Listeners for World State Integration ---

def on_enemy_killed(data: Dict):
    """Update world state when an enemy is defeated."""
    enemy_name = data.get("name")
    ws.log_event(f"Defeated {enemy_name}")
    
    # Example: Clearing blight if a blighted enemy is killed
    if "blighted" in enemy_name.lower():
        current_blight = ws.get_value("global_storylines.conixia_blight.corruption_level", 0.0)
        ws.set_value("global_storylines.conixia_blight.corruption_level", max(0, current_blight - 0.05))

def on_quest_completed(data: Dict):
    """Update faction reputation on quest completion."""
    faction = data.get("faction")
    amount = data.get("rep_gain", 10)
    if faction:
        ws.adjust_faction_influence(faction, amount)

# Register default listeners
bus.subscribe("enemy_killed", on_enemy_killed)
bus.subscribe("quest_complete", on_quest_completed)
