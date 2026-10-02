# Papaya Pathfinder — Pi Mission

The MP-1 ("Map/Detect/Explore") mission software: GPS+IMU dead-reckoning
position fusion with a growing error-circle, boustrophedon
coverage-pattern generation, exclusion-zone intrusion checks, obstacle
detection/classification and resume-after-restart reconciliation, and
`MissionRuntime` — the orchestrator that ties all of it into one running
process (startup/resume, the tick loop, command handling, telemetry
cadence, Home-return sync). See
`../../docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md`
for the design this implements, and the "Mission Runtime" section below
for how it actually runs.

`GpsFix`/`ImuReading` are plain data; a sensor-driver layer underneath
`MissionRuntime` produces them from either real or simulated hardware
(see "Sensing backends" below) — this package's own math modules
(`position_fusion.py`, `coverage_pattern.py`, etc.) never touch hardware
directly. Persistence is local-first: `local_store.py`'s SQLite store
holds obstacles/sweep-sessions/telemetry, synced to the backend at a
Home-return checkpoint by `sync_client.py`.

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
- `runtime.py` — `MissionRuntime`: the orchestrator. Owns no business
  logic of its own; ties position fusion, obstacle detection, the
  mission-flow decision modules, telemetry, and sync into one running
  process. Takes a `SensorHub` and an `Esp32Link` as constructor
  arguments (see "Sensing backends" below).
- `runtime_config.py` — named constants and `.env`-loaded settings
  (`TICK_HZ`, poll/sample intervals, GPS-loss thresholds, etc.).
- `esp32_link.py` / `sensor_hub.py` — the `Esp32Link`/`SensorHub`
  Protocols `MissionRuntime` depends on, plus `FakeEsp32Link`/
  `SimulatedSensorHub`, the scripted-per-field test doubles used by most
  of this package's own tests.
- `backend_client.py` — read/poll half of talking to the Backend Core
  API (rover/geofence fetch, command polling); `sync_client.py` is the
  push half.

### Sensing backends

Three things can sit behind the `SensorHub`/`Esp32Link` Protocols,
swapped in via `MissionRuntime`'s constructor without touching
orchestration logic:

- **`sensor_hub.py`'s `SimulatedSensorHub` / `esp32_link.py`'s
  `FakeEsp32Link`** — scripted per-field test doubles. Each test sets
  exactly the value it needs; fields have no relationship to each other.
- **`digital_twin.py`** — one coherent simulated rover world (position,
  heading, speed, a bounded mast sweep, bounded GPS jitter, bump/halt
  detection) that *derives* every sensor reading from shared state, so a
  scenario test can rely on them agreeing with each other the way real
  sensors would.
- **`hardware_esp32_link.py` / `hardware_sensor_hub.py`** — real
  implementations for the breadboard bench rig: NMEA GPS parsing, a
  BNO055-shaped IMU, HC-SR04-style ultrasonic ranging, a thin camera
  pass-through, and the real newline-delimited-JSON Pi↔ESP32 UART
  protocol. Every hardware dependency (a serial-like transport, an I2C
  device, a GPIO pulse timer) is injected via the constructor against a
  `Protocol` defined in the same file, so none of this needs real
  hardware or hardware-specific libraries (`pyserial`, `pigpio`, etc.)
  to unit-test — only to actually run against physical hardware, which
  is bench-time work (constructing the real `serial.Serial`/`pigpio.pi()`
  objects) not yet wired into `__main__.py`.
- **`status_display.py`** — an LCD status display (screen cycling, 2
  soft-key function buttons) reading `MissionRuntime.last_telemetry_
  readings`, the same hardware-driver pattern: logic is fully testable,
  the real PCF8574/1602A write backend is bench-time work.

## Mission Runtime

`python -m papaya_mission` runs the mission loop. Requires `.env` with
`ROVER_ID`, `BACKEND_BASE_URL` (the running Backend Core service), and
`LOCAL_DB_PATH` (SQLite file path — created if absent).

The CLI entrypoint (`__main__.py`) currently wires `SimulatedSensorHub`
and `FakeEsp32Link` — real hardware drivers exist (`hardware_sensor_hub.py`,
`hardware_esp32_link.py`, see "Sensing backends" above) but constructing
the actual hardware objects they're injected with (a real serial port, a
real `pigpio` connection) is bench-time work not yet done, so the CLI
entrypoint hasn't been switched over.

**Note — the swap-in story holds for sensing, not yet for motion.** The
`Esp32Link` contract currently covers bump-safety reporting and
drive-status telemetry only; it has no drive/steering-commanding method
yet, and `MissionRuntime` never issues a movement command anywhere in
`tick()`. Actual navigation (driving toward the next waypoint) is not
yet implemented: this runtime can *detect* waypoint arrival and make
mission-level decisions off it, but it has no way to *cause* that
arrival. The ESP32 firmware plan needs to add both a movement-commanding
method to `Esp32Link` and a navigation step to `tick()` before the rover
can physically move itself.

Per-tick duration is logged; a warning means a tick exceeded its
`TICK_HZ` budget — see the MP-1 Mission Runtime design notes' "Scaling
note" for what that means and what to do about it.
