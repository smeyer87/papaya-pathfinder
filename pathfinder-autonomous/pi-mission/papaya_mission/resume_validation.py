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
    new_detections: list[Obstacle]


def reconcile_obstacles(
    known_obstacles: list[Obstacle],
    freshly_detected: list[Obstacle],
    now: datetime,
    match_radius_m: float = 3.0,
) -> ReconciliationResult:
    """Pair known obstacles against this pass's fresh detections.

    Matching is greedy nearest-first and strictly one-to-one: every
    (known, fresh) pair within `match_radius_m` is ranked by distance and
    the closest pair claims each other, after which both drop out. That
    one-to-one rule is the point -- letting a single fresh detection
    confirm several known obstacles would quietly mark a missing obstacle
    as still-there whenever a neighbour of it got re-detected, which is
    exactly the discrepancy a resume pass exists to surface.

    Bookkeeping is by list index, not by object identity or value:
    `Obstacle` is a frozen dataclass, so two genuinely distinct obstacles
    with identical fields compare and hash equal.
    """
    candidate_pairs: list[tuple[float, int, int]] = []
    for known_index, known in enumerate(known_obstacles):
        for fresh_index, fresh in enumerate(freshly_detected):
            distance = flat_earth_distance_m(known.position, fresh.position)
            if distance <= match_radius_m:
                candidate_pairs.append((distance, known_index, fresh_index))
    candidate_pairs.sort(key=lambda pair: pair[0])

    matched_known: set[int] = set()
    matched_fresh: set[int] = set()
    for _distance, known_index, fresh_index in candidate_pairs:
        if known_index in matched_known or fresh_index in matched_fresh:
            continue
        matched_known.add(known_index)
        matched_fresh.add(fresh_index)

    confirmed: list[Obstacle] = []
    cleared: list[Obstacle] = []
    discrepancies: list[Obstacle] = []

    for known_index, known in enumerate(known_obstacles):
        if known_index in matched_known:
            confirmed.append(dataclasses.replace(known, last_confirmed_at=now))
        elif known.status == "temporary":
            cleared.append(known)
        else:
            discrepancies.append(known)

    new_detections = [
        fresh
        for fresh_index, fresh in enumerate(freshly_detected)
        if fresh_index not in matched_fresh
    ]

    return ReconciliationResult(
        confirmed=confirmed,
        cleared=cleared,
        discrepancies=discrepancies,
        new_detections=new_detections,
    )
