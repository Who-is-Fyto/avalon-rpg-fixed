"""
engine/rng.py
Weighted RNG — the heart of the system.

Stats don't guarantee outcomes — they bend the probability distribution.
High stat → shifts weights toward success, keeps tension alive.
Low stat → failure becomes more likely, never certain.
"""

import random
from typing import Any


# ── Weighted pool roll (direct port from RNG.h) ──────────────────────────────

def weighted_choice(options: list[dict], key: str = "weight") -> dict:
    """
    Pick one item from a weighted list.
    options: [{"value": ..., "weight": int}, ...]
    """
    total = sum(o[key] for o in options)
    roll  = random.randint(1, total)
    cumulative = 0
    for option in options:
        cumulative += option[key]
        if roll <= cumulative:
            return option
    return options[-1]


# ── Stat-modified success/partial/failure roll ────────────────────────────────

OUTCOME_LABELS = ("critical_success", "success", "partial", "failure", "critical_failure")

def weighted_d20(stat_value: int) -> int:
    """
    Returns a weighted d20 roll where higher stats increase the weight of high numbers.
    This creates a 'bending probability' feel instead of pure flat randomness.
    """
    # Higher stats increase the 'weight' of high rolls. 
    # Base weight is 1. Stat bonus adds to weights of rolls 11-20.
    bonus = max(0, stat_value - 5)
    weights = []
    for i in range(1, 21):
        if i > 10:
            weights.append(1 + bonus)
        else:
            weights.append(1)
    
    return random.choices(range(1, 21), weights=weights)[0]

def stat_roll(stat_value: int, dc: int, is_weighted: bool = True) -> dict:
    """
    Roll against a difficulty class using either a flat or weighted distribution.
    """
    modifier = stat_value - 5

    if is_weighted:
        raw = weighted_d20(stat_value)
    else:
        raw = random.randint(1, 20)
        
    total = raw + modifier

    if raw == 1:
        outcome = "critical_failure"
    elif raw == 20:
        outcome = "critical_success"
    elif total >= dc + 5:
        outcome = "critical_success"
    elif total >= dc:
        outcome = "success"
    elif total >= dc - 4:
        outcome = "partial"
    else:
        outcome = "failure"

    return {
        "outcome":  outcome,
        "roll":     raw,
        "modifier": modifier,
        "total":    total,
        "dc":       dc,
        "success":  outcome in ("success", "critical_success"),
        "is_weighted": is_weighted
    }


# ── Weighted starting location selector (direct port from RNG.h) ─────────────

def select_weighted_location(locations: list[dict]) -> str:
    """
    locations: [{"name": str, "weight": int}, ...]
    Returns the chosen location name.
    """
    pool = [{"value": loc["name"], "weight": loc["weight"]} for loc in locations]
    return weighted_choice(pool)["value"]


# ── Narrative consequence router ──────────────────────────────────────────────

def resolve_roll_outcome(roll_result: dict, outcomes: dict) -> dict:
    """
    Map a stat_roll result to a narrative outcome node.

    outcomes dict shape:
        {
          "critical_success": {...},
          "success":          {...},
          "partial":          {...},
          "failure":          {...},
          "critical_failure": {...},
        }
    Falls back through the chain if a specific tier isn't defined.
    """
    fallback_chain = {
        "critical_success": ["critical_success", "success", "partial"],
        "success":          ["success", "partial"],
        "partial":          ["partial", "failure"],
        "failure":          ["failure", "critical_failure"],
        "critical_failure": ["critical_failure", "failure"],
    }

    for key in fallback_chain.get(roll_result["outcome"], [roll_result["outcome"]]):
        if key in outcomes:
            return {**outcomes[key], "_roll": roll_result}

    # Last resort
    return {**list(outcomes.values())[-1], "_roll": roll_result}
