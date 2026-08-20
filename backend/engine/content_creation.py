"""Safe, data-driven authoring for custom game content."""
import re
from copy import deepcopy
from uuid import uuid4

VALID_TYPES = {"ability", "skill", "spell", "item", "equipment"}
VALID_ABILITY_TYPES = {"active", "passive", "ultimate"}
VALID_ITEM_CATEGORIES = {"consumable", "equipment", "weapon", "armour", "trinket", "material", "quest"}
VALID_STATS = {"STR", "DEX", "CON", "INT", "WIS", "CHA", "AFF", "max_hp", "max_conixia", "max_stamina"}
VALID_EFFECT_TYPES = {"damage", "heal", "buff_stat", "status", "passive_bonus", "restore_conixia", "restore_stamina", "none"}


def _safe_slug(value):
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug[:48] or "custom_content"


def validate_content(content_type, payload):
    kind = str(content_type).lower()
    if kind not in VALID_TYPES:
        raise ValueError(f"content_type must be one of: {', '.join(sorted(VALID_TYPES))}.")
    data = deepcopy(payload or {})
    name = str(data.get("name", "")).strip()
    if not 3 <= len(name) <= 48:
        raise ValueError("Custom content name must be between 3 and 48 characters.")
    data["name"] = name
    data["description"] = str(data.get("description", "")).strip()[:500]
    if kind in {"ability", "skill", "spell"}:
        data["type"] = data.get("type", "active")
        if data["type"] not in VALID_ABILITY_TYPES:
            raise ValueError("Ability type must be active, passive, or ultimate.")
        data["cost"] = max(0, int(data.get("cost", 0)))
        data["cooldown"] = max(0, int(data.get("cooldown", 0)))
        data["effect_type"] = data.get("effect_type", "none")
        if data["effect_type"] not in VALID_EFFECT_TYPES:
            raise ValueError("Unsupported ability effect_type.")
        data["power_bonus"] = int(data.get("power_bonus", 0))
        data["element"] = str(data.get("element", ""))[:24]
        budget = data["power_bonus"] + int(data["cost"] / 5) + int(data["cooldown"] / 2)
        if budget > 60:
            raise ValueError("Custom ability exceeds the power budget of 60.")
        data["tag"] = str(data.get("tag", "custom"))[:32]
    else:
        data["category"] = data.get("category", "equipment" if kind == "equipment" else "material")
        if data["category"] not in VALID_ITEM_CATEGORIES:
            raise ValueError("Unsupported item category.")
        data["subcategory"] = str(data.get("subcategory", "custom"))[:32]
        data["slot"] = data.get("slot") if data.get("slot") in {"weapon", "armour", "trinket"} else None
        data["stat_bonuses"] = {k: int(v) for k, v in (data.get("stat_bonuses", {}) or {}).items() if k in VALID_STATS}
        if sum(abs(v) for v in data["stat_bonuses"].values()) > 30:
            raise ValueError("Custom item stat bonuses exceed the budget of 30.")
        data["hazard_resistances"] = {str(k): min(0.75, max(0.0, float(v))) for k, v in (data.get("hazard_resistances", {}) or {}).items()}
        data["resistance_bonuses"] = {str(k): min(1.0, max(0.0, float(v))) for k, v in (data.get("resistance_bonuses", {}) or {}).items()}
        data["effect"] = data.get("effect", {"type": "none"})
        data["weight"] = max(0.0, float(data.get("weight", 0)))
        data["value"] = max(0, int(data.get("value", 0)))
    data["content_type"] = kind
    return data


def materialize(content_type, payload, owner):
    data = validate_content(content_type, payload)
    instance_id = f"custom_{_safe_slug(data['name'])}_{uuid4().hex[:8]}"
    data.update({"id": instance_id, "instance_id": instance_id, "base_id": instance_id, "generated": True, "authored": True, "owner": owner})
    if content_type in {"ability", "skill", "spell"}:
        data.setdefault("counterplay", {})
        data.setdefault("hazard_resistances", {})
    else:
        data.setdefault("rarity", "custom")
        data.setdefault("rarity_data", {"label": "Custom"})
        data.setdefault("affixes", [])
    return data
