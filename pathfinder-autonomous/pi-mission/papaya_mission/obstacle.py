"""The obstacle detection domain object. Mirrors the fields the backend's
Obstacle record needs (design spec: Data Model -- Obstacle record) that
this plan's logic actually determines. Persistence-lifecycle fields (id,
review_status, reviewed_by, reviewed_at, synced_at) are owned by the
Pi-telemetry-and-sync plan and the backend review workflow, not here.

Timestamp fields are real (wall-clock, UTC) datetimes -- unlike
position_fusion.py's monotonic-seconds timestamps, these are
record-keeping values meant to be logged, compared, and eventually
synced.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

DetectionMethod = Literal["ultrasonic+camera", "contact-only"]
ObstacleStatus = Literal["temporary", "permanent-pending"]


@dataclass(frozen=True)
class Obstacle:
    position: tuple[float, float]  # (lon, lat)
    position_uncertainty_m: float
    type: str
    classification_confidence: float
    detection_method: DetectionMethod
    status: ObstacleStatus
    first_detected_at: datetime
    last_confirmed_at: datetime | None = None
