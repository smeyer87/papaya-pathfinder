# Full-Suite Test Flakiness: Missing `/commands/poll` Handler Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate a real, confirmed source of full-suite test flakiness: six test files' fake HTTP handlers crash with `AssertionError` when `MissionRuntime`'s legitimate 1-second command-poll fires mid-test (which it occasionally does under full-suite system load, even though the same test is fast in isolation), because those handlers never implemented `/commands/poll/{rover_id}`.

**Architecture:** Add one branch to each of the six affected handler functions, returning an empty command list — matching the exact pattern already used (correctly) in `tests/test_runtime_tick_commands.py`. Pure test-fixture fix; no production code changes.

**Tech Stack:** Python 3.12, pytest, httpx. No new dependencies.

## Global Constraints

- No change to `COMMAND_POLL_INTERVAL_S` or any other value in `papaya_mission/runtime_config.py` — this is a test-fixture fix, not a production timing change.
- No change to any file in `papaya_mission/` (production code) at all.
- No change to `tests/test_runtime_sync_and_integration.py` or `tests/test_runtime_tick_commands.py` — both already handle `/commands/poll/rover-1` correctly.
- Every rover id across all six affected tests is `"rover-1"` (verified) — the new branch always checks `/commands/poll/rover-1` and always returns `httpx.Response(200, json=[])`, an empty command list.
- Design spec: `docs/superpowers/specs/2026-10-02-test-flakiness-command-poll-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/tests/
  test_digital_twin_scenarios.py        # MODIFY -- _handler, one new branch
  test_hardware_drivers_integration.py  # MODIFY -- _handler, one new branch
  test_runtime_resume.py                # MODIFY -- _handler, one new branch
  test_runtime_startup.py               # MODIFY -- _handler_for, one new branch
  test_runtime_tick_sensing.py          # MODIFY -- _handler, one new branch
  test_status_display_integration.py    # MODIFY -- _handler, one new branch
```

---

### Task 1: Add `/commands/poll/rover-1` handling to the six affected test fixtures

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/tests/test_digital_twin_scenarios.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_hardware_drivers_integration.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_runtime_startup.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py`

**Interfaces:**
- Consumes: `httpx.Response`, `httpx.Request` (unchanged, already imported in every one of these files).
- Produces: nothing consumed by a later task — this plan has one task.

This task has no new test to write first (there is no reproducible failing test for a probabilistic timing bug — see the spec's Testing section). Instead, each step below is a verified, exact edit; run the full suite multiple times afterward to confirm no regression and reduced flake surface.

- [ ] **Step 1: Edit `test_digital_twin_scenarios.py`**

Find this exact existing block:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        raise AssertionError(request.url.path)
```

Replace with:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        if request.url.path == "/commands/poll/rover-1":
            # This test doesn't exercise command polling -- it just needs the
            # poll to not crash if MissionRuntime's 1-second cadence
            # (COMMAND_POLL_INTERVAL_S) happens to fire mid-test under
            # full-suite system load, even though this test is fast in
            # isolation. An empty list is exactly what a real backend
            # returns when nothing is queued.
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)
```

- [ ] **Step 2: Edit `test_hardware_drivers_integration.py`**

Find this exact existing block:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        raise AssertionError(request.url.path)
```

Replace with the same pattern as Step 1:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        if request.url.path == "/commands/poll/rover-1":
            # See test_digital_twin_scenarios.py's _handler for the full
            # rationale -- same fix, same reason.
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)
```

- [ ] **Step 3: Edit `test_runtime_resume.py`**

Find this exact existing block:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            match = next(g for g in geofences if g["_id"] == fid)
            return httpx.Response(200, json=match)
        raise AssertionError(request.url.path)
```

Replace with:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            match = next(g for g in geofences if g["_id"] == fid)
            return httpx.Response(200, json=match)
        if request.url.path == "/commands/poll/rover-1":
            # See test_digital_twin_scenarios.py's _handler for the full
            # rationale -- same fix, same reason.
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)
```

- [ ] **Step 4: Edit `test_runtime_startup.py`**

This file's handler is named `_handler_for` (not `_handler`) and has a different shape — a hardcoded `/geofences/fence-1` check, not a `.startswith("/geofences/")` prefix match, and its fallback message is formatted differently. Find this exact existing block:

```python
        if request.url.path == "/geofences/fence-1":
            return httpx.Response(200, json=geofences[0])
        if request.url.path == "/geofences":
            return httpx.Response(200, json=geofences)
        raise AssertionError(f"unexpected request: {request.url.path}")
```

Replace with:

```python
        if request.url.path == "/geofences/fence-1":
            return httpx.Response(200, json=geofences[0])
        if request.url.path == "/geofences":
            return httpx.Response(200, json=geofences)
        if request.url.path == "/commands/poll/rover-1":
            # See test_digital_twin_scenarios.py's _handler for the full
            # rationale -- same fix, same reason.
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.url.path}")
```

- [ ] **Step 5: Edit `test_runtime_tick_sensing.py`**

Find this exact existing block:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        raise AssertionError(request.url.path)
```

Replace with the same pattern as Step 1:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        if request.url.path == "/commands/poll/rover-1":
            # See test_digital_twin_scenarios.py's _handler for the full
            # rationale -- same fix, same reason.
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)
```

- [ ] **Step 6: Edit `test_status_display_integration.py`**

Find this exact existing block:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        raise AssertionError(request.url.path)
```

Replace with the same pattern as Step 1:

```python
        if request.url.path.startswith("/geofences/"):
            fid = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(g for g in geofences if g["_id"] == fid))
        if request.url.path == "/commands/poll/rover-1":
            # See test_digital_twin_scenarios.py's _handler for the full
            # rationale -- same fix, same reason.
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)
```

- [ ] **Step 7: Run each touched file's own test suite and verify it still passes**

Run (from `pathfinder-autonomous/pi-mission/`):

```bash
pytest tests/test_digital_twin_scenarios.py tests/test_hardware_drivers_integration.py tests/test_runtime_resume.py tests/test_runtime_startup.py tests/test_runtime_tick_sensing.py tests/test_status_display_integration.py -v
```

Expected: PASS — every existing test in all six files still passes unchanged. This step proves the new branch didn't alter any existing behavior (no test in these files currently exercises `/commands/poll/rover-1`, so none of their assertions should change).

- [ ] **Step 8: Run the full suite multiple times to confirm reduced flakiness**

Run (from `pathfinder-autonomous/pi-mission/`):

```bash
pytest -q
pytest -q
pytest -q
```

Expected: PASS all three times, back-to-back. A single green run does not prove the flakiness is fixed (the bug is probabilistic, tied to system load during that specific run) — running it 3 times in a row is the actual verification this fix is meant to satisfy. If any of the three runs fails with an error unrelated to `/commands/poll` (a different assertion, a different file), treat that as a separate, newly-discovered issue — do not attribute it to this fix.

- [ ] **Step 9: Commit**

```bash
git add pathfinder-autonomous/pi-mission/tests/test_digital_twin_scenarios.py pathfinder-autonomous/pi-mission/tests/test_hardware_drivers_integration.py pathfinder-autonomous/pi-mission/tests/test_runtime_resume.py pathfinder-autonomous/pi-mission/tests/test_runtime_startup.py pathfinder-autonomous/pi-mission/tests/test_runtime_tick_sensing.py pathfinder-autonomous/pi-mission/tests/test_status_display_integration.py
git commit -m "test(pi-mission): handle /commands/poll/rover-1 in 6 fixtures to fix full-suite flakiness"
```
