# Resumed-Session Obstacle-Count Seeding — Design

**Status:** Proposed
**Related:** `docs/phase2/inputs/00-inbox.md` (follow-up logged 2026-10-01), `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`

## Problem

`MissionRuntime._obstacle_count`/`_last_obstacle_type` are reset to `0`/`"-"` in `handle_start_sweep` (a fresh sweep), but `_resume_in_progress_session_if_any` — which reconstructs `self.sweep_session` from a persisted `in_progress`/`interrupted` row at process startup — never touches them. A resumed session therefore starts the LCD's obstacle counter at `0`/`"-"` even though obstacles may already be persisted for that exact session, understating what's actually been detected "this mission" (a resumed session is the same mission, per the counter's own design intent).

## Fix

In `_resume_in_progress_session_if_any`, right after `self.sweep_session` is rebuilt, query the obstacles already persisted for that session (`local_store.list_obstacles_for_session`) and seed the counters from them:

```python
resumed_obstacles = local_store.list_obstacles_for_session(self.conn, self.sweep_session.id)
self._obstacle_count = len(resumed_obstacles)
self._last_obstacle_type = (
    max(resumed_obstacles, key=lambda o: o["last_confirmed_at"] or o["first_detected_at"])["type"]
    if resumed_obstacles
    else "-"
)
```

**Why `last_confirmed_at or first_detected_at` as the recency key, not just `last_confirmed_at`:** a freshly-detected, never-re-detected obstacle has `last_confirmed_at = None` (see `Obstacle`'s default and both `obstacle_from_*` factories, neither of which sets it). Only `reconcile_obstacles`'s "confirmed" branch sets `last_confirmed_at` via `dataclasses.replace(known, last_confirmed_at=now)`. A session with a mix of fresh and re-confirmed obstacles would have `None` and real `datetime` values in the same list — `max(..., key=lambda o: o["last_confirmed_at"])` alone would raise `TypeError` comparing `None` to a `datetime`. Falling back to `first_detected_at` (always set at creation by both factories) avoids that crash and still correctly orders by "most recent obstacle-related event" either way.

**Reuse, don't re-query:** a few lines later, the existing resume-validation-arming code (inside `if self.sweep_session.last_completed_waypoint_index >= 0:`) already calls `local_store.list_obstacles_for_session(self.conn, self.sweep_session.id)` to build `self._resume_validation_known_rows` — the exact same query, same session, same moment (nothing mutates the obstacles table between the two points in this synchronous method). Fetch once, assign `self._resume_validation_known_rows = resumed_obstacles` there instead of querying again.

## Testing

`tests/test_runtime_resume.py` already covers `_resume_in_progress_session_if_any` directly and has the exact fixture needed:

- Extend the existing `test_startup_auto_resumes_interrupted_session` (which already persists one obstacle row, `"obs-pre-crash"`, `type="barrel"`, `last_confirmed_at=None`, for the resumed session) with two more assertions: `runtime._obstacle_count == 1` and `runtime._last_obstacle_type == "barrel"`. This is the "zero persisted obstacles still seeds correctly" case covered implicitly by every other existing test in that file that resumes a session with no obstacle rows (e.g. `test_startup_resumes_the_newest_of_several_resumable_sessions`) — add one assertion there too (`runtime._obstacle_count == 0`) rather than a whole new test.
- Add one new test for the `None`-safe ordering specifically: persist two obstacles for the same resumable session — one with `last_confirmed_at=None` (never re-detected) and a second, later-detected one with `last_confirmed_at` set to a real datetime (re-confirmed) — and confirm `_last_obstacle_type` picks the correct one without raising `TypeError`.

## Out of scope

- No change to `handle_start_sweep`'s existing reset-to-zero behavior for a genuinely fresh sweep.
- No change to `status_display.py` — it already reads `obstacle_count`/`last_obstacle_type` from `last_telemetry_readings` the same way regardless of how `MissionRuntime` arrived at those numbers.
