# Papaya Pathfinder — Backend

Local, container-hosted backend for MP-1: Rover fleet registry, Geofence
CRUD, and the polled command queue. Data lives in MongoDB Atlas (hosted
separately, not part of this compose file) — see
`docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md` for
the design this implements.

## Configure

    cp .env.example .env

Fill in `.env` with your MongoDB Atlas connection string (Atlas UI:
Database > Connect > Drivers) — this is the one cluster the app and its
tests talk to; nothing in this codebase creates or substitutes a
different database. `.env` is gitignored — never commit real
credentials.

## Run it

    docker compose up --build

Backend on http://localhost:8000, health check at `/health`.

## Run the tests

Requires `.env`'s `MONGO_URI` to already be set to a reachable Atlas
cluster:

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest -v

Tests use a separate `papaya_pathfinder_test` database on that same
cluster and drop it after each run.

## API surface

- `POST/GET /rovers`, `GET/PATCH /rovers/{id}` — fleet registry
- `POST/GET /geofences`, `GET /geofences/{id}` — inclusive/exclusive boundaries
- `POST /commands` — enqueue (rejects `start_sweep` with 409 if another
  rover is already active)
- `GET /commands/poll/{rover_id}` — a rover polls this for its pending
  commands (marks them `delivered`)
- `POST /commands/{id}/ack` — rover acknowledges a delivered command
