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
    element: Optional[str] = None


class Item(BaseModel):
    id: str
    name: str
    category: str
    subcategory: str
    description: str
    effect: ItemEffect
    instance_id: Optional[str] = None
    base_id: Optional[str] = None
    generated: bool = False
    seed: Optional[str] = None
    rarity_data: dict = {}
    affixes: list[dict] = []
    stat_bonuses: dict = {}
    resistance_bonuses: dict = {}
    hazard_resistances: dict = {}
    counterplay: dict = {}
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
    instance_id: Optional[str] = None


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
    instance_id: Optional[str] = None
    base_name: Optional[str] = None
    generated: bool = False
    seed: Optional[str] = None
    element: Optional[str] = None
    power_bonus: int = 0
    cost_reduction: int = 0
    cooldown_reduction: int = 0
    affixes: list[dict] = []
    rarity_data: dict = {}
    counterplay: dict = {}
    hazard_resistances: dict = {}


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
    race_components: list[str] = []
    hybrid_ratio: float = 1.0
    secondary_affinity: Optional[str] = None
    growth_profile: dict = {}
    lineage_trait: dict = {}
    hybrid_affinity: Optional[str] = None
    racial_base_stats: dict = {}
    stat_allocations: dict = {}
    growth_history: list[dict] = []
    growth_remainders: dict = {}
    respec_count: int = 0
    lineage_evolution_count: int = 0
    character_class: str
    base_stats: StatBlock
    current_stats: StatBlock
    starting_location: str
    starting_context: str = ""
    starting_context_label: str = ""
    level: int = 1
    experience: int = 0
    unspent_stat_points: int = 0
    affinity: str = "arcane"
    elemental_resistances: dict = {}
    hazard_resistances: dict = {}
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
    temporary_abilities: list[dict] = []
    generated_items: dict = {}
    generated_abilities: dict = {}
    faction_rep: dict = {}
    unlocked_regions: list[str] = []
    combat_state: Optional[dict] = None
    stamina: int = 100
    max_stamina: int = 100
    session_id: str = ""
    last_saved: str = ""


# ── Request models ────────────────────────────────────────────────────────────

class CharacterCreateRequest(BaseModel):
    name: str
    race: str
    secondary_race: Optional[str] = None
    hybrid_ratio: float = 1.0
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


class CombatStartRequest(BaseModel):
    character_name: str
    session_id: str
    enemies: list[dict]


class CombatActionRequest(BaseModel):
    character_name: str
    session_id: str
    action_type: str
    target_index: int = 0
    ability_name: Optional[str] = None


class StatAllocationRequest(BaseModel):
    character_name: str
    session_id: str
    allocations: dict[str, int]


class RespecRequest(BaseModel):
    character_name: str
    session_id: str
    allocations: dict[str, int] = {}


class LineageEvolutionRequest(BaseModel):
    character_name: str
    session_id: str
    target_race: str
    target_secondary_race: Optional[str] = None


class CreateContentRequest(BaseModel):
    character_name: str
    session_id: str
    content_type: str
    payload: dict
