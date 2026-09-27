# Digital-Twin Simulator — Design Notes

*Approved 2026-09-26.*

**Motivation:** the MP-1 Mission Runtime plan (merged 2026-09-26) already has
test doubles for hardware — `SimulatedSensorHub` and `FakeEsp32Link` — but
each one scripts a single field in isolation (e.g. "next ultrasonic read
returns this" and "next camera read returns that" independently), with no
relationship between them. That's fine for narrow unit tests, but it can't
exercise a realistic end-to-end scenario ("rover drives toward a barrel,
ultrasonic and camera should agree on what's there, then a bump event fires
if it gets close enough"). It's also the only way Claude can keep exercising
realistic scenarios once real bench hardware exists — Claude can't physically
place objects or move a rover, so a coherent simulated world is what lets
scenario testing continue without a human at the bench for every run.

This is explicitly the first of two supporting pieces (the other being a
breadboard bench rig) the user wants in place before the ESP32 firmware
plan is written — see project memory `project-esp32-testing-strategy`.

## Decisions made so far

| Question | Decision |
|---|---|
| Primary consumer | Test-only: a richer test double for pytest scenarios, not a standalone app or interactive CLI |
| Relationship to existing fakes | Additive — `SimulatedSensorHub`/`FakeEsp32Link` are untouched; this is a new module used by new scenario tests |
| How the rover moves | Nothing in the codebase commands autonomous movement yet (Phase 1 hardware is RC/ELRS-driven; `Esp32Link` has no drive-command method — that's the ESP32 firmware plan's job to define). So the twin's rover moves however a scenario tells it to, tick by tick: `world.step(dt_s, heading_deg, speed_mps)` |
| Coordinate frame | Reuse `geo_utils.project_position`/`flat_earth_distance_m` directly — rover and obstacle positions stay in (lat, lon), no new coordinate system |
| Sensor determinism | Deterministic except GPS: true position is always known exactly inside the twin; the GPS *reading* wanders within a disk of radius `gps_accuracy_m` around true position, via a seeded RNG, so tests stay reproducible but can exercise GPS wander |
| GPS loss | `world.gps_available = False` makes the GPS source return `None` — the same named scenario Mission Runtime already handles, not modeled as extreme noise |
| Ultrasonic/camera field of view | Co-located on one mast that sweeps back and forth (radar-like, but bounded, not continuous rotation) at a configurable turn rate, within a configurable sweep limit, with a configurable beam half-angle. No Pi→ESP32 mast-position command exists (same gap as drive commands), so the twin advances the sweep autonomously every `step()` call — mirrors the existing bump-sensor-safety precedent of the ESP32 owning a behavior independently of the Pi |
| Mast/sensor defaults | `mast_sweep_limit_deg=60.0`, `mast_turn_rate_dps=30.0`, `mast_beam_half_angle_deg=7.5`, `max_ultrasonic_range_m` — all constructor parameters on `TwinWorld`, not hardcoded, since real sensor/processing-cycle numbers aren't chosen yet |
| Obstacles | Static only (position, collision radius, classified type, classification confidence) — no moving obstacles, since nothing in Mission Flow decision logic needs them yet |
| Exclusion zones | Reuse `shapely.geometry.Polygon` directly — the same objects a scenario would hand `MissionRuntime`/`find_intruded_exclusion` |

## Architecture

One `TwinWorld` object owns all shared state. Thin adapter classes each
implement one `SensorHub`/`Esp32Link` Protocol method by reading through to
that shared state — the same pattern `SimulatedSensorHub`'s
`_SimGpsSource`/etc. already use, just backed by a coherent world instead of
independently-scripted fields. `MissionRuntime` sees the exact same
`SensorHub`/`Esp32Link` Protocols either way; only what's behind them
changes.

```
pathfinder-autonomous/pi-mission/papaya_mission/
  digital_twin.py   # NEW — TwinWorld, TwinObstacle, and the private
                     #       _Twin*Source / _TwinEsp32Link adapters.
                     #       Exposes world.sensor_hub / world.esp32_link,
                     #       ready to pass straight into MissionRuntime(...).

pathfinder-autonomous/pi-mission/tests/
  test_digital_twin.py            # NEW — the twin in isolation: kinematics,
                                   #       mast sweep, GPS jitter bounds,
                                   #       bump-vs-cone detection
  test_digital_twin_scenarios.py  # NEW — end-to-end scenarios driving a
                                   #       real MissionRuntime against the twin
```

## World state & rover kinematics

`TwinWorld` holds: true rover position (`lat`, `lon`, `heading_deg`,
`speed_mps`), a list of `TwinObstacle` (plain mutable list, appended to
directly by scenario code — no builder API), a list of exclusion-zone
`Polygon`s, mast state (see below), a seeded RNG, and a running clock
(`clock_s`). Constructor parameters with defaults: `start_lat`, `start_lon`,
`gps_accuracy_m`, `mast_sweep_limit_deg`, `mast_turn_rate_dps`,
`mast_beam_half_angle_deg`, `max_ultrasonic_range_m`, and `rng_seed`.
`gps_available` defaults to `True` and is a plain mutable attribute a
scenario flips directly.

Movement is scenario-driven, not autonomous: `world.step(dt_s, heading_deg,
speed_mps)` sets the commanded heading/speed for that tick and advances true
position via `geo_utils.project_position(lat, lon, heading_deg, speed_mps *
dt_s)` — no new movement math, reusing what `obstacle_detection.py` already
uses to project a detected obstacle outward from the rover. IMU's
`forward_acceleration_mps2` is derived as `(speed_mps - previous_speed_mps) /
dt_s`. A convenience helper, `world.drive_route(waypoints, speed_mps, dt_s)`,
walks a straight-line multi-leg path over successive `step()` calls, for
scenarios that don't want to hand-compute per-leg headings.

The same `step()` call also advances the mast sweep (see below) — there is
no separate "tick the sensors" call; one `step()` per simulated tick keeps
rover motion and mast motion from drifting out of sync with each other.

## Sensor derivation

- **GPS** (`_TwinGpsSource.read()`): returns `None` if
  `world.gps_available` is `False` — the GPS-loss scenario Mission Runtime
  already handles explicitly. Otherwise returns a `GpsFix` whose `lat`/`lon`
  is the true rover position offset by a point sampled uniformly inside a
  disk of radius `world.gps_accuracy_m`, using the world's seeded RNG, with
  `accuracy_m=world.gps_accuracy_m` and `timestamp=world.clock_s`. True
  position is never itself corrupted, only the reported fix.

- **IMU** (`_TwinImuSource.read()`): always returns the current true
  `heading_deg` and the acceleration computed in `step()` — no noise, since
  Mission Runtime already treats a failed IMU read as fatal-for-the-tick
  (no safe substitute for heading) and nothing has asked for IMU noise
  modeling yet.

- **Ultrasonic + Camera — mast sweep**: `TwinWorld` tracks `mast_angle_deg`
  (relative to chassis heading, 0 = straight ahead), a sweep direction
  (±1), and three constructor parameters: `mast_sweep_limit_deg` (default
  60.0), `mast_turn_rate_dps` (default 30.0 — deliberately conservative
  since real image-capture/classification and ultrasonic-ranging cycle
  times haven't been scoped yet; a faster physical sweep than the sensing
  pipeline can keep up with would mean the mast points somewhere new before
  a reading finishes, which this simulator doesn't model yet — see Out of
  scope), and `mast_beam_half_angle_deg` (default 7.5). Every `step()` call
  advances `mast_angle_deg` by `mast_turn_rate_dps * dt_s` in the current
  sweep direction, reversing direction exactly at ±`mast_sweep_limit_deg`.

  An obstacle is "in view" this tick only if it falls within
  `mast_beam_half_angle_deg` of the mast's *current* pointing direction
  (not the rover's heading) and within `max_ultrasonic_range_m`. On a hit,
  `_TwinUltrasonicSource.read()` returns `ObstacleDetection(
  relative_bearing_deg=mast_angle_deg, range_m=<true distance to the
  obstacle>)` — reporting the mast's own pointing angle as the bearing,
  since a real narrow-beam sensor can't resolve an object's position within
  its beam any finer than "something is in the direction I'm currently
  aimed." `_TwinCameraSource.read()` fires in the same tick, for the same
  obstacle, since both sensors share the mast — this shared-state agreement
  is the whole point of the twin over the old independently-scripted fakes.

  For deterministic test setup, `world.point_mast_at(deg)` directly sets
  `mast_angle_deg`, so a scenario can force "the mast is looking straight at
  the obstacle right now" instead of stepping through an unpredictable
  number of ticks waiting for the autonomous sweep to arrive.

- **Bump** (`_TwinEsp32Link.poll_bump_events()`): fires a `BumpEvent` when
  true rover position moves within an obstacle's `collision_radius_m`,
  using `geo_utils.flat_earth_distance_m` — including obstacles outside the
  current mast beam, matching `obstacle_from_bump_contact`'s framing of a
  bump as a reactive detection that catches what the proactive sensors
  missed.

- **Drive status / geofence / OTA**: `_TwinEsp32Link.read_drive_status()`
  returns a placeholder `DriveStatus` derived from commanded heading/speed
  (not real servo angles — no steering-servo model exists yet, same
  "placeholder pending final wiring" caveat already in `esp32_link.py`).
  `send_geofence_update`/`trigger_ota` just record calls, identical to
  `FakeEsp32Link` today — the twin doesn't need to *react* to geofence
  pushes, since exclusion-zone response is `MissionRuntime`'s decision
  logic being tested, not the twin's job to simulate.

## Example usage

```python
world = TwinWorld(start_lat=38.0, start_lon=-121.0)
world.obstacles.append(TwinObstacle(
    lat=38.0003, lon=-121.0, collision_radius_m=0.5,
    classified_type="barrel", classification_confidence=0.9,
))
runtime = MissionRuntime(
    rover_id="r1", backend_base_url=..., local_db_path=...,
    sensor_hub=world.sensor_hub, esp32_link=world.esp32_link,
)
runtime.startup()
for _ in range(50):
    world.point_mast_at(0.0)  # force the sweep to look forward this tick
    world.step(dt_s=0.5, heading_deg=0.0, speed_mps=1.0)
    runtime.tick()
# assert the obstacle got recorded, mission_alert set appropriately, etc.
```

Same `runtime.tick()` loop the existing MP-1 tests already drive — only
what's behind `sensor_hub`/`esp32_link` changed.

## Testing/validation for the twin itself

The twin is new test infrastructure, so it gets its own unit tests before
anything relies on it: movement matches `flat_earth_distance_m` after N
steps, mast angle reverses exactly at the sweep limits, GPS readings fall
within `gps_accuracy_m` of true position across repeated seeded samples, and
a detection disappears once the mast sweeps past the beam window.

## Out of scope (for this project)

- **Pi→ESP32 drive-command interface.** Nothing today lets the Pi command
  heading/speed — Phase 1 hardware is RC/ELRS-driven, and defining that
  autonomous command channel (and the ESP32-side conversion to
  servo/throttle) is the ESP32 firmware plan's job. The twin's
  scenario-scripted `step()` is a stand-in for whatever that future
  interface eventually decides, not a preview of it.
- **Sensing-cycle-time gating on the mast sweep.** Real image-capture and
  classification latency, and real ultrasonic ranging cycle time, may need
  to cap how fast the mast can usefully sweep — noted in the mast-sweep
  code as a comment, not modeled, since real hardware/pipeline numbers
  aren't chosen yet. Cheap to add later because the mast constants are
  already parameterized rather than hardcoded.
- **Moving obstacles, IMU noise, non-GPS sensor noise.** None of MP-1's
  decision logic needs them yet; add if a real scenario needs them.
- **Retrofitting existing tests onto the twin.** `SimulatedSensorHub`/
  `FakeEsp32Link` stay exactly as they are for today's narrowly-scripted
  unit tests.
