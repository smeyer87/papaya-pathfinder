# pathfinder-autonomous/pi-mission/papaya_mission/resume_validation.py
"""Resume-validation obstacle reconciliation: compares previously known
obstacles against freshly re-detected ones during a resume pass. See
design spec: Mission Flow -- Resume validation.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from papaya_mission.geo_utils import flat_earth_distance_m
from papaya_mission.obstacle import Obstacle


@dataclass
class ReconciliationResult:
    confirmed: list[Obstacle]
    cleared: list[Obstacle]
    discrepancies: list[Obstacle]


def reconcile_obstacles(
    known_obstacles: list[Obstacle],
    freshly_detected: list[Obstacle],
    now: datetime,
    match_radius_m: float = 3.0,
) -> ReconciliationResult:
    confirmed: list[Obstacle] = []
    cleared: list[Obstacle] = []
    discrepancies: list[Obstacle] = []

    for known in known_obstacles:
        match = _find_nearby_match(known, freshly_detected, match_radius_m)
        if match is not None:
            confirmed.append(dataclasses.replace(known, last_confirmed_at=now))
        elif known.status == "temporary":
            cleared.append(known)
        else:
            discrepancies.append(known)

    return ReconciliationResult(confirmed=confirmed, cleared=cleared, discrepancies=discrepancies)


def _find_nearby_match(
    known: Obstacle, freshly_detected: list[Obstacle], match_radius_m: float
) -> Obstacle | None:
    for candidate in freshly_detected:
        if flat_earth_distance_m(known.position, candidate.position) <= match_radius_m:
            return candidate
    return None
