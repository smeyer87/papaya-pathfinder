"""MissionRuntime: the thin orchestrator tying position fusion,
coverage/obstacle detection, mission-flow decision logic, telemetry,
and sync into one running process. Owns no business logic of its own
-- see design notes for the full architecture and mission lifecycle.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from shapely.geometry import Polygon, shape

from papaya_mission import backend_client, local_store, sync_client
from papaya_mission.coverage_pattern import generate_coverage_pattern
from papaya_mission.esp32_link import Esp32Link
from papaya_mission.exclusion_check import find_intruded_exclusion
from papaya_mission.exclusion_decision import decide_exclusion_response
from papaya_mission.gps_loss_decision import decide_gps_loss_response
from papaya_mission.local_store import (
    DEFAULT_TELEMETRY_COMMIT_INTERVAL_S,
    commit as local_store_commit,
    save_telemetry_record,
    should_commit_telemetry,
)
from papaya_mission.obstacle_detection import (
    obstacle_from_bump_contact,
    obstacle_from_ultrasonic_camera_detection,
)
from papaya_mission.position_fusion import GpsFix, PositionFusion
from papaya_mission.resume_validation import reconcile_obstacles
from papaya_mission.row_spacing import derive_row_spacing_m
from papaya_mission.runtime_config import (
    COMMAND_POLL_INTERVAL_S,
    GPS_LOSS_GRACE_PERIOD_S,
    GPS_LOSS_MAX_ERROR_RADIUS_M,
    MP1_EXPECTED_METRICS,
    SENSOR_DETECTION_WIDTH_M,
    TELEMETRY_SAMPLE_INTERVAL_S,
)
from papaya_mission.sensor_hub import SensorHub
from papaya_mission.sweep_session import SweepSession, SweepSessionStatus, Waypoint
from papaya_mission.telemetry_record import build_telemetry_record

RESUME_VALIDATION_MATCH_RADIUS_M = 3.0
WAYPOINT_ARRIVAL_RADIUS_M = 1.0

# The two values `mission_alert` can hold, named so the set/clear logic can
# tell WHICH check raised the alert it is looking at. Each check only ever
# clears its own -- clearing by "is anything set?" would let one subsystem
# silently cancel another's alert.
GPS_LOSS_ALERT = "gps_stop_and_alert"
EXCLUSION_ALERT = "exclusion_wait_for_help"

logger = logging.getLogger("papaya_mission.runtime")


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
        self.mission_alert: str | None = None

    def startup(self) -> None:
        self.rover = backend_client.fetch_rover(self.http_client, self.backend_base_url, self.rover_id)
        # The manifest lists physical sensors ("gps"/"imu"/"bump"); MP-1's
        # derived telemetry fields (position, nav_mode, ...) are never in it,
        # so the two sets are unioned. Without the union, expected_metrics
        # held only sensor names, and build_telemetry_record's
        # floor-and-ceiling rule dropped every real reading as unexpected.
        self.expected_metrics = {
            entry["sensor"]
            for entry in self.rover.get("sensor_manifest", [])
            if entry.get("installed", True)
        } | MP1_EXPECTED_METRICS
        # Arm the command-poll/telemetry-sample cadence from mission start,
        # not from the __init__ sentinel of 0.0. time.monotonic()'s epoch is
        # unspecified (e.g. system uptime) and routinely already far larger
        # than COMMAND_POLL_INTERVAL_S/TELEMETRY_SAMPLE_INTERVAL_S, so leaving
        # these at 0.0 would make the very first tick() call look infinitely
        # overdue and fire an immediate, arbitrary-timing poll/sample before
        # the loop has settled into its real cadence.
        self._last_command_poll_monotonic = time.monotonic()
        self._last_telemetry_sample_monotonic = time.monotonic()
        self._resume_in_progress_session_if_any()

    def _resume_in_progress_session_if_any(self) -> None:
        candidates = [
            s
            for s in local_store.list_unsynced_sweep_sessions(self.conn)
            if s["status"] in ("in_progress", "interrupted")
        ]
        if not candidates:
            return
        # list_unsynced_sweep_sessions has no ORDER BY, so candidates[0] is
        # whatever SQLite returns first -- insertion order, not recency. With
        # an old interrupted-and-unsynced session still on disk alongside a
        # newer one (realistic after a stretch offline), that resumed the
        # wrong sweep. Sort newest-first here rather than changing the store's
        # query: recency is this caller's policy, not a property of the table.
        candidates.sort(key=lambda session: session["started_at"], reverse=True)
        if len(candidates) > 1:
            logger.warning(
                "multiple resumable sweep sessions found; resuming the newest (%s), skipping %s",
                candidates[0]["id"], [c["id"] for c in candidates[1:]],
            )
        session_dict = candidates[0]

        pattern = [
            Waypoint(
                order=wp["order"],
                position=tuple(wp["position"]["coordinates"]),
                leg_index=wp.get("leg_index", 0),
            )
            for wp in session_dict["pattern"]
        ]
        self.sweep_session = SweepSession(
            id=session_dict["id"],
            rover_id=session_dict["rover_id"],
            geofence_id=session_dict["geofence_id"],
            pattern=pattern,
            status=SweepSessionStatus(session_dict["status"]),
            last_completed_waypoint_index=session_dict["last_completed_waypoint_index"],
            started_at=session_dict["started_at"],
            interrupted_at=session_dict["interrupted_at"],
            completed_at=session_dict["completed_at"],
        )

        all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
        self.exclusion_polygons = [
            shape(g["boundary"]) for g in all_geofences if g["type"] == "exclusive"
        ]

        self._resume_validation_collected = []
        self._resume_validation_known_rows = []
        if self.sweep_session.last_completed_waypoint_index >= 0:
            resume_waypoint = next(
                wp for wp in self.sweep_session.pattern
                if wp.order == self.sweep_session.last_completed_waypoint_index
            )
            self._resume_validation_target = resume_waypoint.position
            # Snapshot the known obstacles ONCE, here, at the moment
            # resume-validation is armed -- the tick loop hasn't run yet, so
            # nothing this pass detects can be in it. Re-querying the store at
            # reconciliation time instead would be wrong: _detect_obstacles
            # defers paired detections while a pass is armed (Task 7), but bump
            # contacts still persist the moment they happen, at the rover's own
            # position. A live query would hand reconcile_obstacles those bump
            # rows as "known" obstacles sitting within metres of this pass's
            # fresh detections, and its greedy nearest-first matching would pair
            # a fresh detection with a row this same pass wrote, leaving the
            # genuinely pre-existing obstacle unmatched and wrongly reported as
            # cleared/discrepancies -- precisely the failure resume-validation
            # exists to catch. (The alternative, tagging freshly inserted ids
            # and subtracting them later, needs bookkeeping in every
            # _save_obstacle caller for the same result; the snapshot is a
            # single call at the one moment the boundary is unambiguous.)
            #
            # list_obstacles_for_session, not list_unsynced_obstacles: a
            # Home-return sync during the interrupted pass marks obstacles
            # synced, and an unsynced-only filter would drop them from the
            # known set, so reconciliation would treat each one as never-seen.
            #
            # Raw store rows, not domain objects: Obstacle has no id field
            # (ids are a persistence concern owned by local_store), so the row
            # is the only place an existing obstacle's id lives -- and a
            # confirmed re-detection has to be saved back under that id.
            self._resume_validation_known_rows = local_store.list_obstacles_for_session(
                self.conn, self.sweep_session.id
            )

        if self.sweep_session.status == SweepSessionStatus.INTERRUPTED:
            self.sweep_session.resume()
            self._save_sweep_session()

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

    def tick(self) -> None:
        now_monotonic = time.monotonic()
        self._read_position(now_monotonic)
        if self.position_fusion is not None:
            # Every step in this block reads the fused position estimate. If
            # this tick's position read failed outright (see _read_position's
            # defensive wrapping), there is no estimate to reason about --
            # skipping these is the graceful degradation, whereas letting them
            # dereference a None fusion would turn one flaky sensor into a
            # crashed mission. Telemetry and command polling stay outside the
            # block on purpose: a rover that cannot fix its position is
            # exactly when the ground most needs it observable and
            # controllable.
            self._check_gps_loss(now_monotonic)
            self._detect_obstacles()
            self._check_resume_validation_arrival()
            self._check_exclusion_zones()
            self._check_waypoint_arrival()
        self._sample_telemetry_if_due(now_monotonic)
        self._poll_and_handle_commands_if_due(now_monotonic)

    def _read_position(self, now_monotonic: float) -> None:
        # Each hardware read is wrapped individually rather than the method as
        # a whole, so one failing sensor degrades only its own contribution.
        # The Protocols in sensor_hub.py ask real drivers not to raise, but
        # that is a request, not an enforceable guarantee -- the Global
        # Constraint ("a failure reading one sensor must never stop the
        # mission") needs a second layer here that does not depend on every
        # future driver honouring it.
        try:
            imu_reading = self.sensor_hub.imu.read()
        except Exception:
            # The IMU is the one read with no graceful partial outcome:
            # seeding and dead reckoning both need a heading and a timestamp,
            # and there is no safe substitute for either. Skip the whole
            # position step for this tick -- 100ms of stale position is
            # recoverable, a fabricated heading is not.
            logger.warning("IMU read failed -- skipping the position step this tick", exc_info=True)
            return
        try:
            gps_fix = self.sensor_hub.gps.read()
        except Exception:
            # Indistinguishable, by design, from an honest "no fix this tick":
            # the dead-reckoning path and the GPS-loss safety clock already
            # handle exactly this, growing the error circle and eventually
            # raising gps_stop_and_alert if it persists.
            logger.warning("GPS read failed -- treating this tick as no fix", exc_info=True)
            gps_fix = None

        if self.position_fusion is None:
            seed_fix = gps_fix or GpsFix(lat=0.0, lon=0.0, accuracy_m=999.0, timestamp=imu_reading.timestamp)
            self.position_fusion = PositionFusion(seed_fix)
            # The clock starts here whether or not a REAL fix arrived. When it
            # did not, we are seeding from the dummy (0,0)/999m fix, and
            # leaving _last_gps_fix_monotonic as None made _check_gps_loss
            # return immediately forever: a cold boot under tree cover with
            # zero fixes ever acquired never evaluated GPS-loss safety at all,
            # however long dead reckoning ran. "Never had a fix" is at least
            # as unsafe as "just lost one", so it starts the same
            # grace-period clock rather than disabling the check.
            self._last_gps_fix_monotonic = now_monotonic
            return

        if gps_fix is not None:
            self.position_fusion.on_gps_fix(gps_fix)
            self._last_gps_fix_monotonic = now_monotonic
        else:
            self.position_fusion.on_imu_reading(imu_reading)

    def _check_gps_loss(self, now_monotonic: float) -> None:
        if self._last_gps_fix_monotonic is None or self.position_fusion is None:
            return
        seconds_since_last_fix = now_monotonic - self._last_gps_fix_monotonic
        response = decide_gps_loss_response(
            seconds_since_last_fix=seconds_since_last_fix,
            current_error_radius_m=self.position_fusion.current_estimate.error_radius_m,
            grace_period_s=GPS_LOSS_GRACE_PERIOD_S,
            max_error_radius_m=GPS_LOSS_MAX_ERROR_RADIUS_M,
        )
        # decide_gps_loss_response is re-evaluated from scratch every tick, so
        # the alert tracks it both ways rather than latching on forever: a
        # healthy fix resets both the clock and the error radius, at which
        # point holding the alert would be reporting a condition that has
        # already resolved. Logging happens only on the TRANSITION, not every
        # tick, or a held alert would bury the log at tick rate.
        if response == "stop_and_alert":
            if self.mission_alert != GPS_LOSS_ALERT:
                logger.error(
                    "GPS loss safety triggered (%.1fs since last fix, error radius %.1fm) "
                    "-- stop and alert",
                    seconds_since_last_fix,
                    self.position_fusion.current_estimate.error_radius_m,
                )
            self.mission_alert = GPS_LOSS_ALERT
        elif self.mission_alert == GPS_LOSS_ALERT:
            # Only clears an alert THIS check raised. An exclusion alert held
            # at the same time is none of this check's business.
            logger.info("GPS loss safety cleared -- fix recovered, resuming normal operation")
            self.mission_alert = None

    def _detect_obstacles(self) -> None:
        # Both reads fall back to None on failure, which the paired-detection
        # branch below already treats as "nothing detected this tick" -- a
        # missed detection is a real cost, but it is the same cost as the
        # sensor honestly seeing nothing, and far cheaper than aborting the
        # mission. A persistently failing sensor shows up as a repeating
        # warning in the log.
        try:
            ultrasonic = self.sensor_hub.ultrasonic.read()
        except Exception:
            logger.warning("ultrasonic read failed -- no detection this tick", exc_info=True)
            ultrasonic = None
        try:
            camera = self.sensor_hub.camera.read()
        except Exception:
            logger.warning("camera read failed -- no detection this tick", exc_info=True)
            camera = None
        if ultrasonic is not None and camera is not None:
            classified_type, confidence = camera
            paired_obstacle = obstacle_from_ultrasonic_camera_detection(
                rover_position=self.position_fusion.current_estimate,
                relative_bearing_deg=ultrasonic.relative_bearing_deg,
                range_m=ultrasonic.range_m,
                classified_type=classified_type,
                classification_confidence=confidence,
                detected_at=datetime.now(timezone.utc),
            )
            if self._resume_validation_target is not None:
                # A resume pass is armed -- don't persist yet. Reconciliation
                # (in _check_resume_validation_arrival) decides whether this is
                # a re-detection (reuse the known obstacle's id, one row) or
                # genuinely new (mint a fresh id, one row). Saving here too
                # would create a SECOND row for a re-detection: the fresh-id
                # row written now, plus the reused-id upsert written at
                # reconciliation -- one physical obstacle, two records, both
                # synced to the backend, and on the next resume pass the
                # orphan fails to match and is reported as a bogus "vanished"
                # discrepancy.
                self._resume_validation_collected.append(paired_obstacle)
            else:
                self._save_obstacle(paired_obstacle)

        # Bump contacts are a separate, reactive obstacle source -- kept
        # independent of the ultrasonic+camera branch above (not folded
        # into one shared variable) so a bump event can never overwrite
        # or double-save a same-tick ultrasonic+camera detection.
        try:
            bump_events = self.esp32_link.poll_bump_events()
        except Exception:
            # Losing the bump report is not losing the bump SAFETY: the ESP32
            # cuts the drive train itself on contact, via a hardware
            # interrupt, with no Pi round-trip (see esp32_link's module
            # docstring). Only the durable record is missed here, and
            # _handle_resume_sweep's halted_on_contact check catches a bump
            # that happened while the link was down.
            logger.warning("bump-event poll failed -- no bump records this tick", exc_info=True)
            bump_events = []
        for bump_event in bump_events:
            bump_obstacle = obstacle_from_bump_contact(
                rover_position=self.position_fusion.current_estimate,
                detected_at=bump_event.detected_at,
            )
            self._save_obstacle(bump_obstacle)

    def _check_resume_validation_arrival(self) -> None:
        """Reconcile this resume pass's collected detections against the known
        obstacles, once the rover is back at the resume-validation target.

        A tick step in its own right, called unconditionally -- deliberately
        NOT driven off a detection happening. Arriving at the target having
        detected nothing is the single most important case resume validation
        exists to report: it is what turns a pre-crash obstacle that is no
        longer there into a `cleared`/`discrepancies` entry. Hanging this off
        _detect_obstacles' paired-detection branch made that case unreachable,
        because with nothing detected there was no call site to reach it from.
        """
        if self._resume_validation_target is None:
            return

        from papaya_mission.geo_utils import flat_earth_distance_m

        estimate = self.position_fusion.current_estimate
        current_position = (estimate.lon, estimate.lat)
        distance_to_target = flat_earth_distance_m(current_position, self._resume_validation_target)
        if distance_to_target > RESUME_VALIDATION_MATCH_RADIUS_M:
            return  # still transiting back -- keep collecting, reconcile on arrival

        # The known set is the snapshot taken when resume-validation was armed
        # in _resume_in_progress_session_if_any (Task 6): the obstacles stored
        # BEFORE this resume pass began. It is deliberately not re-queried
        # here. Paired detections made during an armed pass are deferred rather
        # than saved, but bump contacts are NOT -- they are a reactive source
        # outside reconciliation and still persist the moment they happen, at
        # the rover's own position. A live list_obstacles_for_session call would
        # therefore hand those bump rows to reconcile_obstacles as "known"
        # obstacles, sitting within metres of this pass's fresh detections; its
        # greedy nearest-first matching would let a bump row claim a fresh
        # detection and crowd out the pre-existing obstacle that detection
        # should have been matched against -- wrongly reporting a
        # still-present obstacle as cleared. See the arming site for the full
        # rationale.
        known_rows = self._resume_validation_known_rows
        # A position can legitimately carry more than one row -- two bump
        # contacts logged at the same position estimate, say -- so map each
        # position to the list of ids stored there and let each confirmed
        # entry consume one. A flat position->id dict would collapse those
        # rows onto a single id, refreshing one row twice while leaving the
        # other stale: the same duplicate-row failure this id lookup exists
        # to prevent.
        known_ids_by_position: dict[tuple[float, float], list[str]] = {}
        for row in known_rows:
            known_ids_by_position.setdefault(row["position"], []).append(row["id"])
        known = [self._obstacle_dict_to_domain(row) for row in known_rows]
        result = reconcile_obstacles(
            known_obstacles=known,
            freshly_detected=self._resume_validation_collected,
            now=datetime.now(timezone.utc),
        )
        for confirmed in result.confirmed:
            # A confirmed obstacle is a RE-detection of one we already store a
            # row for, so it must reuse that row's id. That is what makes
            # save_obstacle's upsert-by-id refresh the record in place (and
            # re-flag it unsynced); minting a fresh id here would insert a
            # second row for the same physical obstacle and defeat the upsert
            # entirely.
            #
            # reconcile_obstacles builds each confirmed entry as
            # dataclasses.replace(known, last_confirmed_at=now), which changes
            # only that one field -- so the entry's position is identical to
            # the known obstacle it came from and is a safe key back to that
            # obstacle's stored id.
            self._save_obstacle(
                confirmed, obstacle_id=known_ids_by_position[confirmed.position].pop(0)
            )
        for new_obstacle in result.new_detections:
            # This is where a genuinely-new obstacle detected during the resume
            # pass finally gets persisted -- exactly once, with a fresh id
            # (no obstacle_id, so _save_obstacle mints one).
            #
            # _detect_obstacles deferred it precisely so this decision could be
            # made here: had it been saved on detection, a fresh row would
            # already exist for every entry that reconciliation then classified
            # as `confirmed`, on top of the reused-id upsert -- two rows per
            # re-detected obstacle. Deferring means each collected detection is
            # written once, under whichever id reconciliation says is correct.
            self._save_obstacle(new_obstacle)
        # `cleared` and `discrepancies` are logged for operator review via
        # telemetry/obstacle status -- no further action in v1.
        self._resume_validation_target = None
        self._resume_validation_collected = []
        self._resume_validation_known_rows = []

    @staticmethod
    def _obstacle_dict_to_domain(obstacle_dict: dict[str, Any]):
        from papaya_mission.obstacle import Obstacle

        return Obstacle(
            position=obstacle_dict["position"],
            position_uncertainty_m=obstacle_dict["position_uncertainty_m"],
            type=obstacle_dict["type"],
            classification_confidence=obstacle_dict["classification_confidence"],
            detection_method=obstacle_dict["detection_method"],
            status=obstacle_dict["status"],
            first_detected_at=obstacle_dict["first_detected_at"],
            last_confirmed_at=obstacle_dict["last_confirmed_at"],
        )

    def _save_obstacle(self, obstacle, *, obstacle_id: str | None = None) -> None:
        if self.sweep_session is None:
            # MP-1's obstacle tracking is scoped to sweep sessions: the local
            # store's obstacles.sweep_session_id is NOT NULL, matching the
            # backend's non-optional Obstacle.sweep_session_id. An obstacle
            # met while no session is active -- during transit, or a bump on
            # the way home -- has no session to attach to, so there is no
            # valid row to write and we skip persisting it rather than
            # inserting a null session id the schema rejects.
            #
            # This costs nothing operationally: the rover still reacts to the
            # obstacle through the normal avoidance path on this tick. Only
            # the durable record is skipped, and a durable record outside a
            # sweep session has nowhere to be reported to anyway.
            return

        lon, lat = obstacle.position
        local_store.save_obstacle(
            self.conn,
            {
                # A re-detected obstacle passes the id of the row it already
                # has, so save_obstacle's upsert refreshes that row in place.
                # A genuinely new detection gets a fresh id.
                "id": obstacle_id or str(uuid.uuid4()),
                "sweep_session_id": self.sweep_session.id,
                "position": (lon, lat),
                "position_uncertainty_m": obstacle.position_uncertainty_m,
                "type": obstacle.type,
                "classification_confidence": obstacle.classification_confidence,
                "detection_method": obstacle.detection_method,
                "status": obstacle.status,
                "first_detected_at": obstacle.first_detected_at,
                "last_confirmed_at": obstacle.last_confirmed_at,
            },
        )

    def _check_exclusion_zones(self) -> None:
        if not self.exclusion_polygons or self.rover is None or self.position_fusion is None:
            return
        estimate = self.position_fusion.current_estimate
        position = estimate.as_lon_lat()
        intrusion = find_intruded_exclusion(position, self.exclusion_polygons)
        if intrusion is None:
            # Out of every exclusion zone -- symmetric with _check_gps_loss,
            # clear only the alert THIS check raises. Precedence note: this
            # runs after _check_gps_loss in tick(), so if a GPS-loss alert is
            # simultaneously active, mission_alert holds GPS_LOSS_ALERT and
            # this branch is a no-op -- the more severe, more blocking
            # condition (we do not trust our own position, so we cannot
            # trust this very intrusion verdict either) stays reported until
            # GPS recovers. The converse also holds: raising an exclusion
            # alert below cannot overwrite a GPS alert, for the same reason.
            if self.mission_alert == EXCLUSION_ALERT:
                logger.info("exclusion-zone alert cleared -- rover is outside every exclusion zone")
                self.mission_alert = None
            return
        _exclusion, depth_m = intrusion
        rover_length_m = self.rover.get("length_m")
        if rover_length_m is None:
            return
        response = decide_exclusion_response(depth_m, rover_length_m)
        if response == "wait_for_help":
            if self.mission_alert == GPS_LOSS_ALERT:
                return  # GPS loss outranks this -- see the precedence note above
            if self.mission_alert != EXCLUSION_ALERT:
                logger.error(
                    "exclusion-zone intrusion %.2fm deep (rover length %.2fm) -- wait for help",
                    depth_m, rover_length_m,
                )
            self.mission_alert = EXCLUSION_ALERT
        elif self.mission_alert == EXCLUSION_ALERT:
            # Inside a zone but only shallowly -- auto-reverse handles it, so
            # the wait-for-help condition itself has resolved.
            logger.info("exclusion-zone alert cleared -- intrusion is now shallow enough to auto-reverse")
            self.mission_alert = None

    def _check_waypoint_arrival(self) -> None:
        if self.sweep_session is None or self.sweep_session.status != SweepSessionStatus.IN_PROGRESS:
            return
        remaining = self.sweep_session.remaining_waypoints
        if not remaining:
            return
        next_waypoint = remaining[0]

        from papaya_mission.geo_utils import flat_earth_distance_m
        estimate = self.position_fusion.current_estimate
        distance = flat_earth_distance_m((estimate.lon, estimate.lat), next_waypoint.position)
        if distance <= WAYPOINT_ARRIVAL_RADIUS_M:
            self.sweep_session.mark_waypoint_complete(next_waypoint.order)
            self._save_sweep_session()
            if self.sweep_session.is_fully_covered:
                self.sweep_session.complete(datetime.now(timezone.utc))
                self._save_sweep_session()
                self._home_return_sync()

    def _sample_telemetry_if_due(self, now_monotonic: float) -> None:
        if now_monotonic - self._last_telemetry_sample_monotonic < TELEMETRY_SAMPLE_INTERVAL_S:
            return
        self._last_telemetry_sample_monotonic = now_monotonic
        self._telemetry_sequence_number += 1

        estimate = self.position_fusion.current_estimate if self.position_fusion else None
        readings: dict[str, Any] = {}
        if estimate is not None:
            # GeoJSON [lon, lat] order, matching every other coordinate pair
            # in this codebase. as_lon_lat() rather than a hand-built tuple:
            # a swapped pair still serialises fine and is just quietly wrong.
            readings["position"] = list(estimate.as_lon_lat())
            # Both names are reported: position_uncertainty_m is the metric
            # name the backend/ground-control side uses for an obstacle's or
            # a position's uncertainty, error_radius_m is the fusion layer's
            # own name for the same number and is what existing telemetry
            # consumers already read.
            readings["position_uncertainty_m"] = estimate.error_radius_m
            readings["error_radius_m"] = estimate.error_radius_m
            readings["heading_deg"] = estimate.heading_deg
        if self.sweep_session is None:
            readings["nav_mode"] = "idle"
        elif self.sweep_session.status == SweepSessionStatus.IN_PROGRESS:
            readings["nav_mode"] = "sweeping"
        else:
            readings["nav_mode"] = "interrupted"
        readings["waypoint_index"] = (
            self.sweep_session.last_completed_waypoint_index
            if self.sweep_session is not None
            else -1
        )
        # "none" rather than omitting the key: build_telemetry_record would
        # otherwise store the "missing" sentinel, which means "the metric
        # could not be read", not "there is no alert" -- an important
        # difference for a safety field.
        readings["mission_alert"] = self.mission_alert or "none"

        try:
            drive_status = self.esp32_link.read_drive_status()
        except Exception:
            # Substituting an empty DriveStatus rather than a neutral one:
            # reporting throttle 0.0 when we simply could not read it would
            # assert the rover is stopped, which is a claim we cannot make.
            # Leaving the readings absent lets build_telemetry_record tag them
            # with the "missing" sentinel, which is exactly what happened.
            logger.warning("drive-status read failed -- reporting it as missing this sample", exc_info=True)
            drive_status = None
        if drive_status is not None:
            readings["throttle_position"] = drive_status.throttle_position
            for servo_id, angle_deg in drive_status.servo_positions_deg.items():
                readings[f"servo_{servo_id}_deg"] = angle_deg
        # Per-servo keys are dynamic (`servo_{id}_deg`, from whatever ids the
        # ESP32 reported THIS tick), so they cannot be pre-enumerated in the
        # static MP1_EXPECTED_METRICS -- and build_telemetry_record drops any
        # reading outside the expected set. Extend the set for this one sample
        # instead of changing that function: its floor-and-ceiling contract is
        # already established and tested by two earlier plans.
        expected_metrics_this_sample = self.expected_metrics | {
            f"servo_{servo_id}_deg"
            for servo_id in (drive_status.servo_positions_deg if drive_status else {})
        }

        record = build_telemetry_record(
            record_id=str(uuid.uuid4()),
            rover_id=self.rover_id,
            timestamp=datetime.now(timezone.utc),
            local_tz_offset_minutes=_local_tz_offset_minutes(),
            sequence_number=self._telemetry_sequence_number,
            readings=readings,
            expected_metrics=expected_metrics_this_sample,
            sweep_session_id=self.sweep_session.id if self.sweep_session else None,
        )
        save_telemetry_record(self.conn, record)

        now = datetime.now(timezone.utc)
        if should_commit_telemetry(self._last_telemetry_commit_at, now, DEFAULT_TELEMETRY_COMMIT_INTERVAL_S):
            local_store_commit(self.conn)
            self._last_telemetry_commit_at = now

    def _poll_and_handle_commands_if_due(self, now_monotonic: float) -> None:
        if now_monotonic - self._last_command_poll_monotonic < COMMAND_POLL_INTERVAL_S:
            return
        self._last_command_poll_monotonic = now_monotonic

        try:
            commands = backend_client.poll_commands(self.http_client, self.backend_base_url, self.rover_id)
        except httpx.HTTPError:
            logger.warning("command poll failed -- will retry next interval", exc_info=True)
            return

        for command in commands:
            try:
                self._handle_command(command)
                backend_client.ack_command(self.http_client, self.backend_base_url, command["_id"])
            except Exception:
                # Deliberately broader than httpx.HTTPError. _handle_command
                # reaches into caller-supplied dicts (command["type"],
                # payload["geofence_id"]), parses backend GeoJSON via
                # shape(), and runs derive_row_spacing_m -- KeyError,
                # ValueError and shapely's own errors are all reachable from
                # a single malformed command, and none of them is an HTTP
                # error. Per the Global Constraints' fault-isolation rule one
                # bad command must not take down the tick (nor the remaining
                # commands in this batch), so this is one wide net at the one
                # place a per-command failure can be contained. No ack is
                # sent on failure, so the backend can redeliver.
                logger.warning(
                    "failed to handle/ack command %s -- will retry next poll",
                    command.get("_id"), exc_info=True,
                )

    def _handle_command(self, command: dict[str, Any]) -> None:
        command_type = command["type"]
        if command_type == "start_sweep":
            self.handle_start_sweep(command.get("payload", {}))
        elif command_type == "pause_sweep":
            if self.sweep_session is not None:
                self.sweep_session.interrupt(datetime.now(timezone.utc))
                self._save_sweep_session()
        elif command_type == "resume_sweep":
            self._handle_resume_sweep()
        elif command_type in ("stop_sweep", "abort_home"):
            if self.sweep_session is not None and self.sweep_session.status == SweepSessionStatus.IN_PROGRESS:
                self.sweep_session.interrupt(datetime.now(timezone.utc))
                self._save_sweep_session()
            self._home_return_sync()
        elif command_type == "update_geofence":
            all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
            self.exclusion_polygons = [
                shape(g["boundary"]) for g in all_geofences if g["type"] == "exclusive"
            ]
        else:
            # An unknown type is still acked (the caller acks on return), so
            # the backend stops redelivering it -- but it must be visible in
            # the log rather than falling off the end of the if-chain in
            # silence. A silently-dropped command looks identical from the
            # ground to one that was carried out.
            logger.warning(
                "received unhandled command type %r (command %r)",
                command_type, command.get("_id"),
            )

    def _home_return_sync(self) -> None:
        try:
            sync_client.sync_all(self.conn, self.http_client, self.backend_base_url)
        except httpx.HTTPError:
            logger.warning(
                "Home-return sync failed -- records remain unsynced for the next attempt",
                exc_info=True,
            )

    def _handle_resume_sweep(self) -> None:
        try:
            status = self.esp32_link.status()
        except Exception:
            # This check exists to catch a bump that happened while the link
            # was down, so a link that is STILL failing is the very situation
            # it guards against -- refuse the resume rather than assume
            # not-halted and drive into whatever stopped us. The command is
            # left unacked by the caller's guard only on a raise; here we
            # return cleanly, so the session simply stays interrupted and
            # ground control can retry once the link is healthy.
            logger.warning("ESP32 status read failed -- refusing to resume the sweep", exc_info=True)
            return
        if status.halted_on_contact:
            # A bump occurred while the link was down (or since the last
            # check) -- treat it like any other bump event rather than
            # blindly resuming movement. See design notes: Error handling.
            #
            # With no position estimate (a failed IMU read this tick) there is
            # nowhere to place the obstacle, so the record is skipped -- but
            # the resume is still refused, which is the safety-relevant half.
            if self.position_fusion is not None:
                obstacle = obstacle_from_bump_contact(
                    rover_position=self.position_fusion.current_estimate,
                    detected_at=datetime.now(timezone.utc),
                )
                self._save_obstacle(obstacle)
            else:
                logger.warning(
                    "ESP32 reports halted-on-contact but no position estimate is available "
                    "-- refusing the resume without recording the obstacle"
                )
            return
        if self.sweep_session is not None and self.sweep_session.status == SweepSessionStatus.INTERRUPTED:
            self.sweep_session.resume()
            self._save_sweep_session()


def _local_tz_offset_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0
