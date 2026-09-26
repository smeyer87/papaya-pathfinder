# Papaya Pathfinder — Pi Mission

Pure geometry, obstacle-handling, and decision-logic layer for MP-1:
GPS+IMU dead-reckoning position fusion with a growing error-circle,
boustrophedon coverage-pattern generation, exclusion-zone intrusion
checks, obstacle detection/classification, and the mission-flow
decision logic (row spacing, sweep-session lifecycle, exclusion and
GPS-loss responses) built on top of it. See
`../../docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md`
for the design this implements.

No hardware I/O here -- `GpsFix`/`ImuReading` are plain data a later
sensor-driver layer will produce from real hardware; this package only
does the math. No persistence either -- `SweepSession` is a plain
in-memory state object the caller drives and persists themselves. The
actual runtime loop (waypoint navigation driving, command-queue
polling, telemetry writes, Home-return sync triggering) is deferred to
a not-yet-written Mission Runtime plan. Two of its three dependencies
are now done -- Position & Coverage Geometry and Obstacle Detection &
Classification -- leaving only the Pi Telemetry + Sync and backend
command-channel plans still to exist as code.

**Time handling:** `position_fusion.py`'s `timestamp` fields are
monotonic seconds (e.g. `time.monotonic()`), used only for computing
elapsed-time deltas -- never wall-clock time. Everything else
(`Obstacle.first_detected_at`, `detected_at`, `now`) is a real UTC
`datetime`.

**Bearing convention:** ultrasonic/camera detections report a bearing
relative to the rover's own heading (0 = straight ahead), not an
absolute compass bearing -- the mast rotates independently of the
chassis. `obstacle_detection.py` combines it with the rover's current
heading before placing the obstacle.

## Run the tests

    python3 -m venv .venv
    source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    pytest -v

## Modules

- `position_fusion.py` — `PositionFusion`: seed with a `GpsFix`, feed
  `ImuReading`s between fixes, read `.current_estimate` for the fused
  position + heading + error-circle radius.
- `coverage_pattern.py` — `generate_coverage_pattern(inclusive, exclusions,
  row_spacing_m)`: ordered lawnmower *legs* — a list of contiguous
  `(lon, lat)` polylines. Each leg is independently drivable; routing
  between legs is the caller's job (an exclusion zone may sit in the gap).
- `exclusion_check.py` — `find_intruded_exclusion(position, exclusions)`:
  which exclusion zone (if any) a position is inside, and how deep.
- `geo_utils.py` — shared degrees/meters helpers (`project_position`,
  `flat_earth_distance_m`) used by every other module.
- `obstacle.py` — `Obstacle`: the detection domain object.
- `classification.py` — `classify_permanence(type, confidence)`: the
  permanent/temporary heuristic, with a low-confidence safety override.
- `obstacle_detection.py` — turns a sensor detection (ultrasonic+camera
  relative-bearing/range, or a bump contact) into an `Obstacle` at an
  absolute position.
- `resume_validation.py` — `reconcile_obstacles(known, fresh, now)`:
  confirms, clears, or flags-as-discrepancy previously known obstacles
  during a resume pass.
- `row_spacing.py` — derives coverage row spacing from sensor detection
  width; validates it against the rover's chosen turn style
  (spin-in-place vs. graceful) and turn diameter.
- `sweep_session.py` — the sweep-session state machine (start/
  interrupt/resume/complete). Build one from a coverage pattern with
  `SweepSession.from_legs(legs, ...)`, which tags each waypoint with its
  `leg_index` so leg boundaries survive; never flatten the legs yourself.
- `exclusion_decision.py` — auto-reverse vs. wait-for-help.
- `gps_loss_decision.py` — continue-on-dead-reckoning vs. stop-and-alert.
- `local_store.py` — SQLite local store for obstacles/sweep-sessions/
  telemetry. Obstacle/session saves commit immediately; telemetry saves
  defer commit to the caller (`commit()`), batched per
  `DEFAULT_TELEMETRY_COMMIT_INTERVAL_S` (currently 60s — change this one
  constant, or pass a different `interval_s` to `should_commit_telemetry`,
  if the SD-card-wear tradeoff ever needs revisiting; see the design
  spec's resolved open items).
- `telemetry_record.py` — `build_telemetry_record()`: the two-tier
  telemetry record's missing-value tagging (present / `"missing"` /
  omitted).
- `sync_client.py` — pushes unsynced local-store records to the
  backend's `/sync/*` endpoints at a Home-return checkpoint. Tests run
  against `httpx.MockTransport`, not a live server -- no MongoDB or
  running backend needed to build or test this module.

## Mission Runtime

`python -m papaya_mission` runs the mission loop. Requires `.env` with
`ROVER_ID`, `BACKEND_BASE_URL` (the running Backend Core service), and
`LOCAL_DB_PATH` (SQLite file path — created if absent).

Currently wired to `SimulatedSensorHub` and a fake `Esp32Link` — real
hardware drivers (GPS/IMU/ultrasonic/camera modules, the actual
UART/I2C link to the ESP32) are a future hardware-integration pass, not
part of this plan. `runtime.py`'s `MissionRuntime` takes both as
constructor arguments specifically so real drivers can be swapped in
later without touching orchestration logic.

**Note — that swap-in story holds for sensing, not for motion.** The
`Esp32Link` contract currently covers bump-safety reporting and
drive-status telemetry only; it has no drive/steering-commanding method
yet, and `MissionRuntime` never issues a movement command anywhere in
`tick()`. Actual navigation (driving toward the next waypoint) is not
yet implemented: this runtime can *detect* waypoint arrival and make
mission-level decisions off it, but it has no way to *cause* that
arrival. A future hardware-integration pass needs to add both a
movement-commanding method to `Esp32Link` and a navigation step to
`tick()` before the rover can physically move itself.

Per-tick duration is logged; a warning means a tick exceeded its
`TICK_HZ` budget — see the MP-1 Mission Runtime design notes' "Scaling
note" for what that means and what to do about it.
