# Resumed-Session Obstacle-Count Seeding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seed `MissionRuntime._obstacle_count`/`_last_obstacle_type` from the obstacles already persisted for a session when `_resume_in_progress_session_if_any` resumes an `in_progress`/`interrupted` sweep, so the LCD's obstacle counter reports "this mission" correctly across a process restart, not just within one continuous run.

**Architecture:** One query added to `_resume_in_progress_session_if_any`, reused by the existing `_resume_validation_known_rows` assignment a few lines later (same query, same session, same moment — no need to hit the DB twice).

**Tech Stack:** Python 3.12, pytest. No new dependencies.

## Global Constraints

- `handle_start_sweep`'s existing reset-to-`0`/`"-"` behavior for a genuinely fresh sweep is unchanged.
- `status_display.py` is not modified — it already reads `obstacle_count`/`last_obstacle_type` from `last_telemetry_readings` the same way regardless of how `MissionRuntime` arrived at those numbers.
- The "most recent obstacle" ordering key is `last_confirmed_at or first_detected_at` (never `last_confirmed_at` alone) — a freshly-detected, never-re-detected obstacle has `last_confirmed_at = None` (see `Obstacle`'s default and both `obstacle_from_*` factories in `obstacle_detection.py`, neither of which sets it), and `max()` over a mix of `None` and real `datetime` values raises `TypeError`.
- Design spec: `docs/superpowers/specs/2026-10-02-resumed-session-obstacle-count-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/
  papaya_mission/
    runtime.py               # MODIFY -- _resume_in_progress_session_if_any only
  tests/
    test_runtime_resume.py   # MODIFY -- extend 2 existing tests, add 1 new test
```

---

### Task 1: Seed the obstacle counter on session resume

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py`

**Interfaces:**
- Consumes: `papaya_mission.local_store.list_obstacles_for_session(conn, sweep_session_id) -> list[dict]` (unchanged, existing — each dict has keys `id`, `type`, `first_detected_at: datetime`, `last_confirmed_at: datetime | None`, per `_row_to_obstacle`). `MissionRuntime._obstacle_count: int`/`_last_obstacle_type: str` (unchanged fields, already declared in `__init__` by a prior plan).
- Produces: nothing consumed by a later task — this plan has one task.

- [ ] **Step 1: Write the failing tests**

In `pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py`, extend the existing `test_startup_auto_resumes_interrupted_session` test by adding two assertions at the end (it already persists one obstacle row for the resumed session — `"obs-pre-crash"`, `type="barrel"`, `last_confirmed_at=None` — these new asserts prove that row seeds the counter):

```python
    assert runtime.sweep_session is not None
    assert runtime.sweep_session.id == "sess-1"
    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS  # auto-resumed
    assert runtime.sweep_session.last_completed_waypoint_index == 0
    assert runtime._resume_validation_target == (-85.0, 38.0)  # waypoint order 0's position
    assert runtime._resume_validation_collected == []
    # The known-obstacle set is snapshotted at arm time, so it holds exactly
    # the pre-crash rows -- nothing this resume pass goes on to detect.
    assert [row["id"] for row in runtime._resume_validation_known_rows] == ["obs-pre-crash"]
    # The LCD's obstacle counter must reflect this session's history too,
    # not just what happens after this particular process restart.
    assert runtime._obstacle_count == 1
    assert runtime._last_obstacle_type == "barrel"
```

Extend the existing `test_startup_resumes_the_newest_of_several_resumable_sessions` test (which resumes a session with zero persisted obstacle rows) by adding one assertion at the end:

```python
    assert runtime.sweep_session is not None
    assert runtime.sweep_session.id == "sess-new"
    assert runtime._obstacle_count == 0  # no obstacle rows persisted for this session
```

Append this new test to the same file (it needs its own `_make_runtime`/`_interrupted_session` call, following the exact pattern of the existing tests in this file):

```python
def test_resume_seeds_last_obstacle_type_using_confirmed_time_when_available(tmp_path):
    """Regression test: a session can have a mix of never-re-detected
    obstacles (last_confirmed_at=None) and re-confirmed ones
    (last_confirmed_at set). Ordering by last_confirmed_at alone would
    raise TypeError comparing None to a real datetime -- the fallback to
    first_detected_at must apply per-obstacle, not just when ALL rows
    lack a confirmation time.
    """
    rover = {"_id": "rover-1", "name": "George"}
    inclusive = {"_id": "fence-1", "type": "inclusive", "boundary": {"type": "Polygon", "coordinates": [FIELD_RING]}}
    runtime, _ = _make_runtime(tmp_path, rover, geofences=[inclusive])
    local_store.save_sweep_session(
        runtime.conn, _interrupted_session("sess-1", datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc))
    )
    local_store.save_obstacle(
        runtime.conn,
        {
            "id": "obs-first",
            "sweep_session_id": "sess-1",
            "position": (-85.0, 38.0),
            "position_uncertainty_m": 1.5,
            "type": "barrel",
            "classification_confidence": 0.9,
            "detection_method": "ultrasonic+camera",
            "status": "permanent-pending",
            "first_detected_at": datetime(2026, 9, 25, 10, 1, 0, tzinfo=timezone.utc),
            "last_confirmed_at": None,  # never re-detected
        },
    )
    local_store.save_obstacle(
        runtime.conn,
        {
            "id": "obs-reconfirmed",
            "sweep_session_id": "sess-1",
            "position": (-85.0, 38.005),
            "position_uncertainty_m": 1.5,
            "type": "cone",
            "classification_confidence": 0.85,
            "detection_method": "ultrasonic+camera",
            "status": "permanent-pending",
            "first_detected_at": datetime(2026, 9, 25, 10, 0, 30, tzinfo=timezone.utc),
            "last_confirmed_at": datetime(2026, 9, 25, 10, 3, 0, tzinfo=timezone.utc),  # re-detected later
        },
    )
    local_store.commit(runtime.conn)

    runtime.startup()  # must not raise

    assert runtime._obstacle_count == 2
    # obs-reconfirmed's last_confirmed_at (10:03:00) is the most recent
    # obstacle-related event of the two -- its type wins, even though
    # obs-first's first_detected_at (10:01:00) is more recent than
    # obs-reconfirmed's OWN first_detected_at (10:00:30).
    assert runtime._last_obstacle_type == "cone"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run (from `pathfinder-autonomous/pi-mission/`): `pytest tests/test_runtime_resume.py -v`
Expected: FAIL — the two extended tests fail with `AssertionError: assert 0 == 1` (and similar); the new test fails the same way, or with `AttributeError`/`TypeError` depending on current state (counters are never touched by the resume path today, so they stay at their `__init__` default of `0`/`"-"`).

- [ ] **Step 3: Write the implementation**

In `papaya_mission/runtime.py`, find this exact existing block in `_resume_in_progress_session_if_any`:

```python
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
```

Insert between the `SweepSession(...)` assignment and the `all_geofences = ...` line:

```python
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

        # The LCD's obstacle counter reports "this mission" -- a resumed
        # session is the same mission, so it must be seeded from whatever
        # was already persisted, not restarted at 0 just because the
        # process did. last_confirmed_at falls back to first_detected_at
        # per-obstacle (not only when every row lacks one): a never-
        # re-detected obstacle has last_confirmed_at=None (see Obstacle's
        # default and obstacle_detection.py's factories, neither of which
        # sets it), and max() over a mix of None and real datetimes raises
        # TypeError.
        resumed_obstacles = local_store.list_obstacles_for_session(self.conn, self.sweep_session.id)
        self._obstacle_count = len(resumed_obstacles)
        self._last_obstacle_type = (
            max(resumed_obstacles, key=lambda o: o["last_confirmed_at"] or o["first_detected_at"])["type"]
            if resumed_obstacles
            else "-"
        )

        all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
```

Then find this exact existing line further down the same method:

```python
            self._resume_validation_known_rows = local_store.list_obstacles_for_session(
                self.conn, self.sweep_session.id
            )
```

Replace it with (reusing the `resumed_obstacles` fetched above instead of querying again — same session, same moment, nothing mutates the obstacles table in between):

```python
            self._resume_validation_known_rows = resumed_obstacles
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_resume.py -v`
Expected: PASS (all tests in the file, including the 2 extended and 1 new)

- [ ] **Step 5: Run the full test suite and verify everything passes**

Run: `pytest -v` (from `pathfinder-autonomous/pi-mission/`)
Expected: PASS — all prior tests plus this plan's 1 new test (the 2 extended tests don't add to the count). Note: there is a KNOWN, pre-existing, unrelated flaky test group (`tests/test_digital_twin_scenarios.py`, `tests/test_hardware_drivers_integration.py` — timing-sensitive, documented in `docs/phase2/inputs/00-inbox.md`) that can occasionally show a few failures under full-suite wall-clock load. If you see ONLY those fail, re-run them in isolation to confirm they pass there, and don't treat it as caused by this change.

- [ ] **Step 6: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py
git commit -m "fix(pi-mission): seed obstacle_count/last_obstacle_type when resuming a sweep session"
```
