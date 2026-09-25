# Papaya Pathfinder — Pi Mission (Position & Coverage Geometry)

Pure geometry/algorithm layer for MP-1: GPS+IMU dead-reckoning position
fusion with a growing error-circle, boustrophedon coverage-pattern
generation, and exclusion-zone intrusion checks. See
`docs/superpowers/specs/2026-09-24-mp1-map-detect-explore-design.md` for
the design this implements.

No hardware I/O here -- `GpsFix`/`ImuReading` are plain data a later
sensor-driver layer will produce from real hardware; this package only
does the math. No persistence or orchestration either -- that's the
mission-flow state machine plan that imports these modules.

## Run the tests

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    pytest -v

## Modules

- `position_fusion.py` — `PositionFusion`: seed with a `GpsFix`, feed
  `ImuReading`s between fixes, read `.current_estimate` for the fused
  position + error-circle radius.
- `coverage_pattern.py` — `generate_coverage_pattern(inclusive, exclusions,
  row_spacing_m)`: ordered `(lon, lat)` lawnmower waypoints.
- `exclusion_check.py` — `find_intruded_exclusion(position, exclusions)`:
  which exclusion zone (if any) a position is inside, and how deep.
