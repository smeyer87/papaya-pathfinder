# Full-Suite Test Flakiness: Missing `/commands/poll` Handler Coverage — Design

**Status:** Approved, pending plan
**Related:** `docs/phase2/inputs/00-inbox.md` (observation logged across several plans this session)

## Root cause

`COMMAND_POLL_INTERVAL_S = 1.0` (`runtime_config.py:18`) — a genuinely short interval. `MissionRuntime.startup()` arms `_last_command_poll_monotonic = time.monotonic()`; any later `tick()` call whose real wall-clock gap since `startup()` exceeds 1.0 second makes `_poll_and_handle_commands_if_due` call `backend_client.poll_commands`, which issues `GET {base_url}/commands/poll/{rover_id}` (`backend_client.py:31`).

Six test files construct a `MissionRuntime` against a fake HTTP handler (via `httpx.MockTransport`) that does **not** implement that path, and falls through to `raise AssertionError(request.url.path)` for anything unhandled:

- `tests/test_digital_twin_scenarios.py`
- `tests/test_hardware_drivers_integration.py`
- `tests/test_runtime_resume.py`
- `tests/test_runtime_startup.py`
- `tests/test_runtime_tick_sensing.py`
- `tests/test_status_display_integration.py`

In isolation, a single test runs in milliseconds — nowhere near the 1-second threshold — so it never fires. Under a full ~270-test suite run, system load (CPU contention, disk I/O across many `tmp_path`-backed SQLite files running back-to-back) can occasionally stretch one specific test's own wall-clock execution between its `startup()` call and a later `tick()` call past 1 second, even though that same test is fast in isolation. When that happens, the legitimate, production-correct command-poll fires, hits one of these six handlers, and crashes the test with an `AssertionError` on `/commands/poll/rover-1` — which looks like "flaky," unrelated test failure, but is really just an incomplete test fixture meeting code it was never written to anticipate.

Two other files that ARE about command polling already handle this path correctly and were never affected: `tests/test_runtime_sync_and_integration.py` and `tests/test_runtime_tick_commands.py`.

## Fix

Add one branch to each of the six affected `_handler`/`_handler_for` functions, matching the exact pattern already used in `test_runtime_tick_commands.py`:

```python
if request.url.path == "/commands/poll/rover-1":
    return httpx.Response(200, json=[])
```

None of these six tests care about command-polling behavior — they just need the poll to not crash when it fires. An empty command list is exactly what a real backend returns when there's nothing queued, so this isn't a special-case hack for tests; it's the fixture finally behaving like a real backend would under the same request.

**Five of the six files** (`test_digital_twin_scenarios.py`, `test_hardware_drivers_integration.py`, `test_runtime_resume.py`, `test_runtime_tick_sensing.py`, `test_status_display_integration.py`) share an identical or near-identical `_handler(rover, geofences)` shape — insert the new branch right before each file's `raise AssertionError(request.url.path)` line.

**`test_runtime_startup.py`** has a slightly different shape: the function is named `_handler_for` (not `_handler`), its geofence-path check is `request.url.path == "/geofences/fence-1"` (hardcoded, not a `.startswith()` prefix match), and its fallback raises `AssertionError(f"unexpected request: {request.url.path}")` (a formatted message, not the bare path). Same fix, same insertion point (right before that file's own fallback raise), adapted to its exact existing style.

## Not changing

- `COMMAND_POLL_INTERVAL_S` itself, or any other `runtime_config.py` value — this is a test-fixture fix, not a production timing change.
- `tests/test_runtime_sync_and_integration.py` and `tests/test_runtime_tick_commands.py` — already correct.
- Any production code in `papaya_mission/`.

## Testing

This fix has no new test *cases* — it makes six existing test fixtures correctly handle a request path the production code was already allowed to make. Verification is: run the full suite multiple times in a row and confirm it stays green across all runs, not just once (a single green run doesn't prove flakiness is gone — the bug is probabilistic). Each of the six touched files' own test suite should also be run individually to confirm no behavioral change for the normal (non-polling) path.
