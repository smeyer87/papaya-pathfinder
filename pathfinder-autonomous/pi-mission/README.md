# Papaya Pathfinder — Pi Mission (Position & Coverage Geometry)

Pure geometry/algorithm layer for MP-1: GPS+IMU dead-reckoning position
fusion with a growing error-circle, boustrophedon coverage-pattern
generation, and exclusion-zone intrusion checks. See
`../../docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md`
for the design this implements.

No hardware I/O here -- `GpsFix`/`ImuReading` are plain data a later
sensor-driver layer will produce from real hardware; this package only
does the math. No persistence or orchestration either -- that's the
mission-flow state machine plan that imports these modules.

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
