"""Read/poll half of talking to the Backend Core API. sync_client.py
(Pi Local Store & Sync Client plan) is the push half. See design
notes: Architecture & file structure.
"""
from __future__ import annotations

from typing import Any

import httpx


def fetch_rover(client: httpx.Client, base_url: str, rover_id: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/rovers/{rover_id}")
    response.raise_for_status()
    return response.json()


def fetch_geofence(client: httpx.Client, base_url: str, geofence_id: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/geofences/{geofence_id}")
    response.raise_for_status()
    return response.json()


def list_geofences(client: httpx.Client, base_url: str) -> list[dict[str, Any]]:
    response = client.get(f"{base_url}/geofences")
    response.raise_for_status()
    return response.json()


def poll_commands(client: httpx.Client, base_url: str, rover_id: str) -> list[dict[str, Any]]:
    response = client.get(f"{base_url}/commands/poll/{rover_id}")
    response.raise_for_status()
    return response.json()


def ack_command(client: httpx.Client, base_url: str, command_id: str) -> dict[str, Any]:
    response = client.post(f"{base_url}/commands/{command_id}/ack")
    response.raise_for_status()
    return response.json()
