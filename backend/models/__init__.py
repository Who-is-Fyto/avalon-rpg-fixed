from pydantic import BaseModel, Field
from typing import Optional, Any


class StatBlock(BaseModel):
    STR: int = 0
    DEX: int = 0
    CON: int = 0
    INT: int = 0
    WIS: int = 0
    CHA: int = 0
    AFF: int = 0

    def get(self, stat: str) -> int:
        return getattr(self, stat, 0)

    def apply_modifiers(self, modifiers: "StatBlock") -> "StatBlock":
        return StatBlock(
            STR=self.STR + modifiers.STR,
            DEX=self.DEX + modifiers.DEX,
            CON=self.CON + modifiers.CON,
            INT=self.INT + modifiers.INT,
            WIS=self.WIS + modifiers.WIS,
            CHA=self.CHA + modifiers.CHA,
            AFF=self.AFF + modifiers.AFF,
        )


class ItemEffect(BaseModel):
    type: str
    value: Optional[Any] = None
    stat: Optional[str] = None
    duration_turns: Optional[int] = None
    duration_encounters: Optional[int] = None
    status: Optional[str] = None
    ability: Optional[str] = None


class Item(BaseModel):
    id: str
    name: str
    category: str
    subcategory: str
    description: str
    effect: ItemEffect
    weight: float = 0.0
    value: int = 0
    stackable: bool = False
    max_stack: int = 1
    rarity: str = "common"
    slot: Optional[str] = None
    unlock: Optional[str] = None


class InventoryEntry(BaseModel):
    item_id: str
    quantity: int = 1


class EquipmentSlots(BaseModel):
    weapon:  Optional[str] = None
    armour:  Optional[str] = None
    trinket: Optional[str] = None


class Ability(BaseModel):
    name: str
    description: str
    type: str
    cost: int = 0
    cooldown: int = 0
    tag: str = ""


class Perk(BaseModel):
    name: str
    description: str


class StartingLocation(BaseModel):
    name: str
    weight: int


class Race(BaseModel):
    name: str
    conixia_style: str
    society_role: str
    stat_modifiers: StatBlock
    starting_locations: list[StartingLocation]
    perk: Perk


class CharacterClass(BaseModel):
    name: str
    conixia_focus: str
    role: str
    playstyle: list[str]
    primary_stats: list[str]
    starting_abilities: list[str]
    unlock: str = "default"


class Character(BaseModel):
    name: str
    race: str
    character_class: str
    base_stats: StatBlock
    current_stats: StatBlock
    starting_location: str
    starting_context: str = ""
    starting_context_label: str = ""
    level: int = 1
    experience: int = 0
    conixia_energy: int = 100
    max_conixia: int = 100
    hp: int = 100
    max_hp: int = 100
    known_abilities: list[str] = []
    backstory_seed: str = ""
    flags: list[str] = []
    inventory: list[InventoryEntry] = []
    equipment: EquipmentSlots = Field(default_factory=EquipmentSlots)
    gold: int = 0
    carry_weight: float = 0.0
    fate_bound_used: bool = False
    active_buffs: list[dict] = []
    faction_rep: dict = {}
    combat_state: Optional[dict] = None
    stamina: int = 100
    max_stamina: int = 100
    session_id: str = ""
    last_saved: str = ""


# ── Request models ────────────────────────────────────────────────────────────

class CharacterCreateRequest(BaseModel):
    name: str
    race: str
    character_class: str
    starting_location: Optional[str] = None
    context_id: Optional[str] = None    # if None, weighted random
    session_id: str                     # required — which session to create in


class SessionCreateRequest(BaseModel):
    display_name: str = ""


class RollRequest(BaseModel):
    character_name: str
    stat: str
    dc: int
    use_reroll: bool = False
    is_weighted: bool = True
    session_id: str


class StoryChoiceRequest(BaseModel):
    character_name: str
    arc: str
    node_id: str
    choice_index: int
    session_id: str


class UseItemRequest(BaseModel):
    character_name: str
    item_id: str
    session_id: str


class EquipItemRequest(BaseModel):
    character_name: str
    item_id: str
    session_id: str


class AddItemRequest(BaseModel):
    character_name: str
    item_id: str
    quantity: int = 1
    session_id: str
