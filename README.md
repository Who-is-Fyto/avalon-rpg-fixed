# Avalon RPG — Conixia Web Port

Narrative RPG with weighted RNG stat checks and branching story. Ported from C++ to Python/FastAPI + HTML frontend.

---

## Stack

| Layer    | Tech                        |
|----------|-----------------------------|
| Backend  | Python 3.11+ · FastAPI      |
| Story    | JSON files (data/story/)    |
| Data     | JSON files (data/)          |
| Frontend | HTML · CSS · Vanilla JS     |
| Later    | React + SQLite/Redis        |

---

## Project Structure

```
avalon-rpg/
├── backend/
│   ├── main.py                  # FastAPI app entry point
│   ├── requirements.txt
│   ├── models/
│   │   └── __init__.py          # Pydantic models (Character, Race, Ability, etc.)
│   ├── engine/
│   │   ├── rng.py               # Weighted RNG + stat roll system
│   │   ├── data_loader.py       # JSON loaders
│   │   ├── character_factory.py # Character creation + race-lock validation
│   │   └── story_router.py      # Story choice resolution + flag tracking
│   ├── routes/
│   │   ├── data.py              # GET /data/races, /data/classes, /data/abilities
│   │   └── game.py              # POST /game/character/create, /game/story/choose, etc.
│   └── data/
│       ├── races.json
│       ├── classes.json
│       ├── abilities.json
│       └── story/
│           └── prologue.json    # First story arc
└── frontend/
    └── index.html               # Full UI (race picker → class picker → name → story)
```

---

## Setup

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Backend runs at: http://localhost:8000  
API docs (Swagger): http://localhost:8000/docs

Open `frontend/index.html` directly in your browser (no server needed for dev).

---

## API Endpoints

### Data
- `GET /data/races` — all races
- `GET /data/classes` — all classes
- `GET /data/abilities` — all abilities

### Game
- `POST /game/character/create` — create character, start session
- `GET  /game/character/{name}` — fetch character state
- `GET  /game/character/{name}/classes` — available/locked classes for this race
- `POST /game/roll` — standalone stat check (d20 + modifier vs DC)
- `GET  /game/story/{arc}/start?character_name=X` — get opening node
- `POST /game/story/choose` — resolve a player choice (triggers roll if needed)

---

## The RNG System

Stats shift probability — they don't guarantee outcomes.

```
roll = d20 (1–20)
modifier = stat_value - 5   (stat 5 = no modifier, D&D adjacent)
total = roll + modifier

total >= dc+5  → critical success
total >= dc    → success
total >= dc-4  → partial success
total <  dc-4  → failure
raw 1          → critical failure (always)
raw 20         → critical success (always)
```

Human perk (Fate Bound) — one reroll per session via `POST /game/roll` with `use_reroll: true`.

---

## Adding Story

Create a new file in `data/story/` following the `prologue.json` schema:

```json
{
  "arc": "chapter_1",
  "title": "Your Arc Title",
  "nodes": {
    "start": {
      "id": "start",
      "text": "Narrative text. Use {starting_location}, {character_name} as placeholders.",
      "choices": [
        { "text": "Choice label", "stat_check": null, "leads_to": "next_node" },
        { "text": "Risky choice", "stat_check": { "stat": "CHA", "dc": 12 }, "leads_to": "roll_gate_node" }
      ]
    },
    "roll_gate_node": {
      "id": "roll_gate_node",
      "text": "ROLL: CHA vs DC 12",
      "roll_outcomes": {
        "success":  { "text": "Success narrative.", "leads_to": "good_branch" },
        "failure":  { "text": "Failure narrative.", "leads_to": "bad_branch", "flag": "optional_flag_name" }
      }
    }
  }
}
```

---

## Next Steps

- [ ] Swap in-memory session store for SQLite (add `aiosqlite` + `databases`)
- [ ] Add combat encounter nodes to story arcs
- [ ] Build React frontend (same API, no backend changes needed)
- [ ] Add hybrid race system (from `SpeciesPerks.h` hybrid rules)
- [ ] Add ability cost tracking during story encounters
