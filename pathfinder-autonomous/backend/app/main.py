from fastapi import FastAPI

from app.db import ensure_indexes, get_client, get_database
from app.routers import commands, geofences, rovers, sync

app = FastAPI(title="Papaya Pathfinder Backend")

app.include_router(rovers.router)
app.include_router(geofences.router)
app.include_router(commands.router)
app.include_router(sync.router)


@app.on_event("startup")
def on_startup() -> None:
    db = get_database(get_client())
    ensure_indexes(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
