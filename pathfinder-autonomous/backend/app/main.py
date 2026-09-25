from fastapi import FastAPI

from app.db import ensure_indexes, get_client, get_database

app = FastAPI(title="Papaya Pathfinder Backend")


@app.on_event("startup")
def on_startup() -> None:
    db = get_database(get_client())
    ensure_indexes(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
