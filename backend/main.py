"""
main.py — Avalon RPG Backend  v0.5
Run with: uvicorn main:app --reload
API docs: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.data import router as data_router
from routes.game import router as game_router
from routes.sessions import router as sessions_router
import engine.world_state as ws

app = FastAPI(
    title="Avalon RPG API",
    description="Conixia-powered narrative RPG — weighted RNG + stat checks + living world state.",
    version="0.8.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(data_router)
app.include_router(game_router)


@app.on_event("startup")
def startup():
    ws.load()
    print("✓ Avalon RPG backend ready.")
    print("✓ Sessions will be stored in: backend/sessions/")


@app.get("/")
def root():
    return {"status": "online", "game": "Avalon RPG", "version": "0.8.1", "docs": "/docs"}
