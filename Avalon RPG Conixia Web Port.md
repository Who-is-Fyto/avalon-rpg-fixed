# Avalon RPG — Conixia Web Port

Avalon RPG is a data-driven narrative RPG and turn-based combat engine built around elemental magic, procedural equipment, dynamic hazards, race-specific progression, hybrid lineages, and extensible player-authored content. The project is currently implemented as a Python/FastAPI backend with JSON data storage and a single-page HTML/CSS/Vanilla JavaScript frontend.

This README describes the **implemented repository state**, including the advanced customisation systems added after the original narrative prototype. It distinguishes current behavior from future extension points so that the documentation remains useful to anyone continuing development.

## 1. Technology and Runtime

| Layer | Implementation | Responsibility |
|---|---|---|
| HTTP backend | Python 3.11+ and FastAPI | REST endpoints, request validation, session-scoped game operations, and API documentation. |
| Domain validation | Pydantic models | Typed character, race, ability, item, inventory, equipment, and request payloads. |
| Game data | JSON files under `backend/data/` | Races, classes, abilities, items, growth curves, lineage traits, encounters, hazards, world state, and story arcs. |
| Persistence | JSON session files under `backend/sessions/` | Session metadata, world state, character state, generated content, equipment, progression, and faction data. |
| Deterministic systems | Seeded RNG and procedural generators | Reproducible stat rolls, procedural item and spell generation, encounters, loot, and authored content instances. |
| Frontend | `frontend/index.html` with CSS and Vanilla JavaScript | Character creation, hybrid selection, combat lab, inventory, character sheet, hazard breakdowns, progression graphs, and customisation controls. |

The backend entry point is `backend/main.py`. The current frontend can be opened directly during development, although serving it through a local static server is preferable when browser security policies interfere with API requests.

## 2. Setup

```bash
cd backend
python3 -m pip install -r requirements.txt
uvicorn main:app --reload
```

The backend listens at `http://localhost:8000`. Interactive OpenAPI documentation is available at [`http://localhost:8000/docs`](http://localhost:8000/docs). From the repository root, a simple static frontend server can be started separately:

```bash
python3 -m http.server 5173 --directory frontend
```

Then open [`http://localhost:5173`](http://localhost:5173). The frontend's API helper should point to the FastAPI server if it is not using the same origin.

## 3. Repository Structure

```text
avalon-rpg-fixed-main/
├── backend/
│   ├── main.py                         # FastAPI application entry point
│   ├── models/__init__.py              # Pydantic domain and request models
│   ├── routes/
│   │   ├── data.py                     # Static data endpoints
│   │   ├── game.py                     # Character, combat, progression, creation APIs
│   │   └── sessions.py                 # Session and character persistence APIs
│   ├── engine/
│   │   ├── character_factory.py        # Pure/hybrid character creation
│   │   ├── combat_manager.py           # Turn-based combat, bosses, statuses, hazards
│   │   ├── content_creation.py         # Validated custom content authoring
│   │   ├── customisation.py            # Traits, projections, respec, evolution
│   │   ├── data_loader.py              # JSON-to-Pydantic adapters
│   │   ├── elemental.py                # Affinities and elemental resistance rules
│   │   ├── encounters.py               # Regions, budgets, hazards, enemy generation
│   │   ├── procedural.py               # Procedural items, spells, rarity, affixes
│   │   ├── progression.py              # XP, non-linear level growth, allocations
│   │   ├── session_manager.py          # JSON session persistence
│   │   └── world_state.py              # Global events, regions, factions, hazards
│   └── data/
│       ├── races.json                  # Base races and racial modifiers
│       ├── classes.json                # Class roles, playstyles, and unlocks
│       ├── abilities.json              # Static abilities
│       ├── items.json                  # Static items and equipment
│       ├── lineage_traits.json         # Pure and hybrid passive identities
│       ├── race_growth_profiles.json   # Legacy/base growth compatibility data
│       ├── race_growth_curves.json     # Non-linear per-level growth arrays
│       ├── hazards.json                # Environmental hazards and counterplay
│       └── story/                      # Story arc JSON files
└── frontend/
    └── index.html                      # Single-page UI and character-sheet renderer
```

## 4. Core Game Systems

### 4.1 Character creation and lineage composition

Character creation accepts a primary race, an optional secondary race, and a primary inheritance ratio between **25% and 75%**. A character without a secondary race remains a pure lineage. A hybrid receives two lineage components, a saved ratio, two source affinities, blended elemental resistances, class-unlock compatibility from either lineage, and a unique hybrid trait when a matching affinity combination exists.

The primary and secondary race data are blended in `backend/engine/character_factory.py`. The created character stores both the display lineage and machine-readable fields such as `race_components`, `hybrid_ratio`, `growth_profile`, `secondary_affinity`, `hybrid_affinity`, `racial_base_stats`, and `lineage_trait`. Existing pure-race characters remain compatible because these fields have defaults and the progression engine falls back to the primary race when no components are present.

### 4.2 Race identity and hybrid passive perks

Pure races and hybrid combinations are intentionally not only cosmetic variations. Their identities affect playstyle through passive descriptions, stat bonuses, elemental resistance adjustments, hazard resistance, and affinity metadata.

| Identity type | Example | Gameplay direction |
|---|---|---|
| Pure lineage | Ignari — Emberblood | Fire-oriented offense, burning counterplay, and strength emphasis. |
| Pure lineage | Aetherin — Astral Attunement | Arcane power, Conixia efficiency, and void resistance. |
| Pure lineage | Ogrin — Colossus Frame | High physical durability and maximum-health potential with weaker spell economy. |
| Hybrid convergence | Ignari + Aetherin — Cinderstar Convergence | Fire and arcane interplay with balanced affinity and resistance benefits. |
| Hybrid convergence | Pillarian + Trollan — Mirestone Continuum | Earth resilience combined with water/blight survivability. |
| Hybrid convergence | Velari + Aetherin — Umbral Astralism | Shadow mobility and arcane control with void resistance. |

Hybrid definitions are stored in `backend/data/lineage_traits.json`. The `customisation.py` loader checks the affinity pair in either order, applies the matching convergence, and persists a `perk_<name>` flag. If a particular pairing has no authored entry, the engine creates a generic confluence identity rather than failing character creation; this fallback is a safe extension point for future authored hybrid perks.

### 4.3 Elemental affinities and resistances

Elemental affinity is distinct from elemental resistance. An affinity identifies the character's primary magical relationship and is used by ability and combat systems, while resistance values reduce or modify incoming elemental effects. Pure characters retain their primary affinity. Hybrids receive source affinities and, when a convergence exists, a dedicated `hybrid_affinity` such as `cinderstar`, `mirestone`, or `duskfen`.

Hazard resistance is tracked separately from elemental resistance. The character sheet reports totals and breaks them down by base lineage, equipment slot, and passive ability. Equipment and authored abilities can contribute hazard resistance, but the creation engine caps an individual authored hazard value at **75%** before the combat engine applies its own total clamping.

### 4.4 Non-linear race-specific progression

Level growth is driven by `backend/data/race_growth_curves.json`, not by a single universal bonus. Each race has arrays for core-stat growth and vital growth. The progression engine selects the array entry associated with the new level, wraps through the authored twelve-step cycle for levels beyond that range, and blends two arrays for hybrids using the saved inheritance ratio.

This means a race can gain strongly in one level, plateau in another, and contribute less in a later level. The curve is intentionally not a straight line. Fractional hybrid contributions are preserved in `growth_remainders`, preventing repeated rounding from silently deleting the secondary lineage's influence. Each applied level records its actual growth event in `growth_history`, which is returned by the character-sheet and growth endpoints.

The graph shown in the character sheet is a projection of accumulated curve values, not a promise that every future level will increase every stat. It allows players to compare a lineage's long-term shape before committing to an evolution or respec.

## 5. Respec and Lineage Evolution

### 5.1 Respec behavior

Respec unlocks at **level 10** through:

```text
POST /game/character/{session_id}/{name}/respec
```

The request body is:

```json
{
  "session_id": "session_id_here",
  "character_name": "Ash",
  "allocations": {
    "STR": 2,
    "CON": 4,
    "AFF": 3
  }
}
```

The system calculates the respec pool as the character's level-earned points plus points previously recorded in `stat_allocations`. It restores the character's racial baseline from `racial_base_stats`, reapplies the requested allocation map, calculates any remaining unspent points, increments `respec_count`, and records `last_respec_level`. Equipment and active modifiers are then reapplied through `recalculate_stats`.

Respec does not erase the character's level, experience, inventory, equipment, story flags, faction reputation, generated content, or growth history. It changes the allocation layer above the racial baseline. This is important because racial identity remains meaningful even after a player changes their build.

### 5.2 Lineage evolution behavior

Lineage evolution unlocks at **level 20** through:

```text
POST /game/character/{session_id}/{name}/lineage-evolve
```

Example request:

```json
{
  "session_id": "session_id_here",
  "character_name": "Ash",
  "target_race": "Elarin",
  "target_secondary_race": "Trollan"
}
```

Leaving `target_secondary_race` empty produces a pure evolved lineage. Supplying a different valid race produces a new 50/50 hybrid. The endpoint validates both target lineages, updates `race_components`, updates the display race, resets the stored growth profile to the new lineage pair, sets the hybrid ratio to `0.5` for a new hybrid, increments `lineage_evolution_count`, marks the character with `lineage_evolved`, applies the new pure or hybrid trait, and recalculates equipment-adjusted stats.

### 5.3 Stat recalibration rules during evolution

The current implementation uses a **preservation-first transition model**. It does not destroy the character's level, experience, story progression, inventory, equipment, generated items, generated abilities, faction data, or existing growth history. Existing allocated stats are also preserved as an allocation record unless the player separately performs a respec.

The new lineage immediately changes the character's lineage metadata and passive trait layer. Future level-ups use the new race or hybrid growth curve. Equipment and active bonuses are recalculated immediately. The stored `racial_base_stats` remains the original creation baseline for respec purposes; therefore, a player who wants a complete rebuild around the evolved lineage should use respec after evolution. This two-step behavior makes evolution meaningful without silently deleting investment.

> **Important current limitation:** the repository does not yet contain a separate talent-tree graph or node-unlock model. “Talent adjustment” currently means the lineage passive flag, lineage trait metadata, known abilities, and stat-allocation layer are updated while the character's existing learned abilities are preserved. A future talent-tree implementation should add a versioned node graph and an explicit migration policy rather than inferring talent state from ability names.

In practical terms, evolution currently handles talent continuity conservatively: existing `known_abilities` remain learned, the old lineage passive flag is retained in historical character flags, the new lineage perk flag is added, and future decisions use the new lineage identity. If the desired design is to replace, refund, or migrate lineage-specific talent nodes automatically, that should be added as a dedicated evolution policy rather than hidden inside stat recalibration.

## 6. Character Sheet and Progression APIs

The character sheet endpoint is:

```text
GET /game/character/{session_id}/{name}/sheet
```

Its response includes identity, vitals, current and base stats, elemental resistances, hazard-resistance sources, abilities, equipment, inventory, flags, factions, world events, lineage traits, and progression information. The progression object contains both applied history and a projected curve:

```json
{
  "progression": {
    "history": [
      {
        "level": 2,
        "growth": {"STR": 1.0, "DEX": 0.0, "AFF": 0.5},
        "vitals": {"max_hp": 11.0, "max_conixia": 5.0, "max_stamina": 6.0}
      }
    ],
    "projection": {
      "through_level": 20,
      "points": []
    }
  }
}
```

For clients that do not need the full sheet, use:

```text
GET /game/character/{session_id}/{name}/growth?through_level=60
```

The frontend renders the projection as an SVG line graph. Each line represents one core stat, and the graph is based on accumulated curve values, so plateaus and dips remain visible.

## 7. Combat, Magic, Items, and World State

The combat engine is turn-based and supports active abilities, passive effects, ultimates, elemental interactions, status ticking, equipment modifiers, environmental hazards, multiphase bosses, specialised boss drops, and generated encounters. `combat_manager.py` owns action resolution and status processing, while `elemental.py` and the hazard data define affinity and environmental interactions.

The encounter engine supports region progression, difficulty tiers, encounter types, budget constraints, patrols, ambushes, bosses, expeditions, world-state modifiers, and global events such as blight-style conditions. Enemy templates and loot tables are generated from player level, region, difficulty, encounter type, and deterministic seed inputs.

Procedural items and spells use a rarity and affix system. Generated records are converted into the same Pydantic `Item` and `Ability` models used by static content, which lets combat, inventory, equipment, and character-sheet code handle static and generated content through the same interfaces.

## 8. Custom Content Creation Engine

The authoring endpoint is:

```text
POST /game/creation/{session_id}/{name}
```

The request envelope is:

```json
{
  "session_id": "session_id_here",
  "character_name": "Ash",
  "content_type": "skill",
  "payload": {
    "name": "Ashen Step",
    "description": "Teleport through a short trail of cinders.",
    "type": "active",
    "cost": 12,
    "cooldown": 3,
    "effect_type": "damage",
    "power_bonus": 10,
    "element": "fire"
  }
}
```

Supported content types are `ability`, `skill`, `spell`, `item`, and `equipment`. Abilities, skills, and spells are materialised into `generated_abilities` and added to `known_abilities`. Items and equipment are materialised into `generated_items` and added to inventory as unique instances with a generated ID.

### 8.1 Ability power budget

The current ability budget is calculated as:

```text
power_budget = power_bonus + floor(cost / 5) + floor(cooldown / 2)
```

The maximum permitted budget is **60**. This is a deliberately transparent first-pass budget rather than a complete combat simulator. It prevents a custom ability from combining unlimited raw power with trivial resource cost and no cooldown. The validator also restricts ability types to `active`, `passive`, and `ultimate`, and effect types to the engine's supported effect vocabulary.

The validator enforces the following ability constraints:

| Field | Enforcement |
|---|---|
| Name | Trimmed length must be between 3 and 48 characters. |
| Type | Must be `active`, `passive`, or `ultimate`. |
| Cost | Converted to a non-negative integer. |
| Cooldown | Converted to a non-negative integer. |
| Effect type | Must be one of the supported combat effect types. |
| Power bonus | Converted to an integer and included in the budget formula. |
| Element and tag | Normalised to bounded strings for safe storage. |
| Total budget | Must not exceed 60. |

The budget is not intended to replace encounter-specific balance review. A future version can add rarity budgets, level-scaled budgets, damage-per-turn simulation, status-duration costs, target-count costs, and class or lineage restrictions.

### 8.2 Item and equipment caps

Custom item and equipment records are validated separately from abilities. Only recognised categories and equipment slots are accepted. Unknown stat keys are ignored rather than being allowed to create arbitrary model fields.

| Field | Enforcement |
|---|---|
| Item category | Must be `consumable`, `equipment`, `weapon`, `armour`, `trinket`, `material`, or `quest`. |
| Equipment slot | Must be `weapon`, `armour`, or `trinket`, or is stored as empty for non-equipment content. |
| Stat bonuses | Only core stats and recognised vital keys are accepted. |
| Stat-budget cap | Sum of absolute stat bonuses must not exceed **30**. |
| Hazard resistance | Each authored hazard value is clamped to the inclusive range `0.0` to `0.75`. |
| Elemental resistance | Each authored resistance value is clamped to the inclusive range `0.0` to `1.0`. |
| Weight | Cannot be negative. |
| Value | Cannot be negative. |

The **30-point stat budget** limits the total magnitude of an authored item's stat package. The **75% per-hazard cap** prevents a single authored item from trivialising an environmental hazard. The combat and progression layers still clamp accumulated hazard resistance totals and recalculate equipment contributions when equipment changes.

The current engine clamps hazard and elemental values after validation rather than rejecting every over-limit value. This keeps the authoring interface convenient while ensuring the persisted record cannot exceed the declared ceiling. If a stricter authoring workflow is desired, the validator can be changed to reject out-of-range values instead of normalising them.

### 8.3 Content identity and persistence

Every authored record receives a unique `custom_<slug>_<suffix>` instance ID, `generated: true`, `authored: true`, and an owner marker. This prevents a custom item from colliding with a static item ID and allows future systems to audit, export, disable, or version authored content. The materialised record is then passed through the same `Item` or `Ability` adapter used by static data.

## 9. API Reference Summary

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/sessions/` | List saved sessions. |
| `POST` | `/sessions/` | Create a session. |
| `GET` | `/sessions/{session_id}/characters` | List characters in a session. |
| `POST` | `/game/character/create` | Create a pure or hybrid character. |
| `GET` | `/game/character/{session_id}/{name}` | Fetch persisted character state. |
| `GET` | `/game/character/{session_id}/{name}/sheet` | Fetch the complete character-sheet payload. |
| `GET` | `/game/character/{session_id}/{name}/growth` | Fetch growth history and projections. |
| `POST` | `/game/character/{session_id}/{name}/allocate-stats` | Spend available level-up points. |
| `POST` | `/game/character/{session_id}/{name}/respec` | Rebuild stat allocations from the respec pool. |
| `POST` | `/game/character/{session_id}/{name}/lineage-evolve` | Transition to a new pure or hybrid lineage at level 20. |
| `POST` | `/game/creation/{session_id}/{name}` | Create validated custom skills, abilities, spells, items, or equipment. |
| `POST` | `/game/combat/start` | Start a manually defined encounter. |
| `POST` | `/game/combat/action` | Resolve a combat action. |
| `POST` | `/game/combat/start-generated` | Generate and start a seeded encounter. |
| `POST` | `/game/generation/item` | Generate a procedural item instance. |
| `POST` | `/game/generation/spell` | Generate a procedural spell instance. |

The exact request and response schemas are available through FastAPI's generated OpenAPI document at `/docs`.

## 10. Adding Data and Extending the Engine

To add a pure race, update `races.json`, add a matching entry to `lineage_traits.json`, and add a growth entry to `race_growth_curves.json`. A new pure race should define an affinity, a passive identity, optional stat bonuses, elemental resistances, hazard resistances, and twelve-step stat/vital curve arrays.

To add a named hybrid convergence, add a key to `lineage_traits.json` using the two source affinities, such as `fire+arcane`. The loader checks both affinity orders. The entry should define a name, description, hybrid affinity, and optional stat, elemental, and hazard adjustments.

To add a static ability or item, follow the existing schemas in `abilities.json` and `items.json`. For content that should be created at runtime, prefer the creation endpoint so it receives validation, a unique instance ID, and persistence metadata.

To add a story arc, create a JSON file under `backend/data/story/` using the existing node and choice schema. Story placeholders include `{starting_location}`, `{character_name}`, `{starting_context}`, `{race}`, and `{class}`.

## 11. Testing and Verification

The project has been smoke-tested for backend compilation, frontend JavaScript syntax, pure and hybrid character creation, hybrid trait application, nonlinear projections with both upward and downward transitions, fractional hybrid growth, custom skill persistence, custom equipment adaptation, level-gated respec, and level-gated lineage evolution.

A repeatable API smoke-test script may be kept locally during development as `backend/advanced_customisation_smoke.py`. It should not be treated as production game content; it creates temporary JSON session data and is excluded from release archives.

Recommended regression coverage for future changes includes the following cases:

| Test area | Required assertion |
|---|---|
| Hybrid ordering | `A + B` and `B + A` resolve the same convergence trait when their affinities match. |
| Growth | A race's projection contains its authored curve shape and a hybrid preserves fractional contributions. |
| Respec | Invalid stats, negative values, and allocations above the available pool are rejected. |
| Evolution | Evolution below level 20 is rejected and valid transitions preserve non-lineage state. |
| Content budget | Ability budget over 60 and item stat magnitude over 30 are rejected. |
| Resistance caps | Authored hazard values cannot exceed 75% and equipment totals remain clamped. |
| Persistence | Generated IDs, `authored`, `generated`, inventory, known abilities, and evolution counters survive reload. |

## 12. Known Extension Points

The current implementation provides a stable base for a more formal talent-tree system, but it does not yet define talent nodes, prerequisites, refunds, or migration schemas. The recommended next step is a versioned `talent_trees.json` structure with node IDs, prerequisites, lineage tags, costs, and transition policies. Lineage evolution could then choose one of three explicit policies: preserve all nodes, refund lineage-specific nodes, or migrate nodes through a compatibility map.

The current power budget is also intentionally lightweight. A production-grade balance pass should account for target count, duration, status strength, area of effect, range, damage type, scaling stat, resource regeneration, and interaction with existing elemental and hazard systems. The current caps prevent obvious runaway records, but they do not mathematically prove that every authored ability is equally strong in every encounter.

## References

The project-specific descriptions above are derived from the repository's source code and JSON data. The following official references describe the framework and validation technologies used by the project:

[1]: https://fastapi.tiangolo.com/ "FastAPI documentation"
[2]: https://docs.pydantic.dev/ "Pydantic documentation"
[3]: https://developer.mozilla.org/en-US/docs/Web/SVG "MDN SVG documentation"
