"""MissionRuntime: the thin orchestrator tying position fusion,
coverage/obstacle detection, mission-flow decision logic, telemetry,
and sync into one running process. Owns no business logic of its own
-- see design notes for the full architecture and mission lifecycle.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from shapely.geometry import Polygon, shape

from papaya_mission import backend_client, local_store
from papaya_mission.coverage_pattern import generate_coverage_pattern
from papaya_mission.esp32_link import Esp32Link
from papaya_mission.row_spacing import derive_row_spacing_m
from papaya_mission.runtime_config import SENSOR_DETECTION_WIDTH_M
from papaya_mission.sensor_hub import SensorHub
from papaya_mission.sweep_session import SweepSession, Waypoint


class MissionRuntime:
    def __init__(
        self,
        rover_id: str,
        backend_base_url: str,
        local_db_path: str,
        sensor_hub: SensorHub,
        esp32_link: Esp32Link,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.rover_id = rover_id
        self.backend_base_url = backend_base_url
        self.sensor_hub = sensor_hub
        self.esp32_link = esp32_link
        self.http_client = http_client or httpx.Client()
        self.conn = local_store.connect(local_db_path)

        self.rover: dict[str, Any] | None = None
        self.expected_metrics: set[str] = set()
        self.position_fusion = None  # set on start_sweep/resume (Task 6/7)
        self.sweep_session: SweepSession | None = None
        self.exclusion_polygons: list[Polygon] = []

        # Populated by later tasks; declared here so every task's tests
        # can construct a MissionRuntime against one consistent __init__.
        self._last_gps_fix_monotonic: float | None = None
        self._last_command_poll_monotonic: float = 0.0
        self._last_telemetry_sample_monotonic: float = 0.0
        self._last_telemetry_commit_at: datetime | None = None
        self._telemetry_sequence_number = 0
        self._resume_validation_target: tuple[float, float] | None = None
        self._resume_validation_collected: list[Any] = []
        # Raw local_store rows for the obstacles that were already stored
        # when a resume pass was armed. Snapshotted, not queried live -- see
        # _resume_in_progress_session_if_any (Task 6) for why.
        self._resume_validation_known_rows: list[dict[str, Any]] = []

    def startup(self) -> None:
        self.rover = backend_client.fetch_rover(self.http_client, self.backend_base_url, self.rover_id)
        self.expected_metrics = {
            entry["sensor"]
            for entry in self.rover.get("sensor_manifest", [])
            if entry.get("installed", True)
        }
        # Task 6 extends this to check local storage for an in-progress
        # session and resume it. Nothing found here yet -> stay idle,
        # waiting for start_sweep (handled by the tick loop, Task 8).

    def handle_start_sweep(self, payload: dict[str, Any]) -> None:
        geofence_id = payload["geofence_id"]
        inclusive = backend_client.fetch_geofence(self.http_client, self.backend_base_url, geofence_id)
        all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
        exclusive = [g for g in all_geofences if g["type"] == "exclusive"]

        inclusive_polygon = shape(inclusive["boundary"])
        self.exclusion_polygons = [shape(g["boundary"]) for g in exclusive]

        turn_style = self.rover.get("turn_style", "spin_in_place")
        min_turn_diameter_m = self.rover.get("min_turn_diameter_m")
        row_spacing_m = derive_row_spacing_m(
            sensor_detection_width_m=SENSOR_DETECTION_WIDTH_M,
            turn_style=turn_style,
            min_turn_diameter_m=min_turn_diameter_m,
        )

        legs = generate_coverage_pattern(
            inclusive_polygon, self.exclusion_polygons, row_spacing_m
        )
        self.sweep_session = SweepSession.from_legs(
            legs,
            id=str(uuid.uuid4()),
            rover_id=self.rover_id,
            geofence_id=geofence_id,
            started_at=datetime.now(timezone.utc),
        )
        self._save_sweep_session()

    def _save_sweep_session(self) -> None:
        session = self.sweep_session
        local_store.save_sweep_session(
            self.conn,
            {
                "id": session.id,
                "rover_id": session.rover_id,
                "geofence_id": session.geofence_id,
                "status": session.status.value,
                "pattern": [
                    {
                        "order": wp.order,
                        "position": {"type": "Point", "coordinates": list(wp.position)},
                        "leg_index": wp.leg_index,
                    }
                    for wp in session.pattern
                ],
                "last_completed_waypoint_index": session.last_completed_waypoint_index,
                "started_at": session.started_at,
                "interrupted_at": session.interrupted_at,
                "completed_at": session.completed_at,
            },
        )
