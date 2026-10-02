# OTA Safety Gating (Pi-Side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `ota_update` command handler to `MissionRuntime` that refuses to trigger an ESP32 firmware flash while a sweep session is in progress, retrying automatically once the mission pauses or ends.

**Architecture:** A new `_handle_command` branch dispatches to a new `_handle_ota_update` method, which raises when gated — reusing `_poll_and_handle_commands_if_due`'s existing "no ack on exception, backend redelivers" fault-isolation mechanism rather than inventing a new ack/nack protocol.

**Tech Stack:** Python 3.12, pytest. No new dependencies.

## Global Constraints

- The gate checks `sweep_session.status == SweepSessionStatus.IN_PROGRESS`, not mere presence of a `SweepSession` object — `sweep_session` is never reset to `None` anywhere in `runtime.py`, so gating on presence alone would block OTA forever after the first mission ever run.
- No change to `Esp32Link`, `FakeEsp32Link`, or `HardwareEsp32Link` — the gating lives entirely in `MissionRuntime`, before `trigger_ota()` is ever called.
- Device-level veto and "WiFi in range" gating are explicitly out of scope — already decided elsewhere (device veto needs ESP32 firmware cooperation not yet built; WiFi-in-range is structurally free since the Pi can't call `trigger_ota()` without a firmware file it already downloaded over WiFi).
- Design spec: `docs/superpowers/specs/2026-10-02-ota-safety-gating-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/
  papaya_mission/
    runtime.py                       # MODIFY -- _handle_command + new _handle_ota_update
  tests/
    test_runtime_tick_commands.py    # MODIFY -- 3 new tests
```

---

### Task 1: Add the gated `ota_update` command handler

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_commands.py`

**Interfaces:**
- Consumes: `self.esp32_link.trigger_ota(firmware_path: str) -> None` (unchanged, existing `Esp32Link` Protocol method). `self.sweep_session: SweepSession | None` and `SweepSessionStatus` (unchanged, existing).
- Produces: `MissionRuntime._handle_ota_update(payload: dict[str, Any]) -> None` — nothing consumed by a later task; this plan has one task.

- [ ] **Step 1: Write the failing tests**

Append to `pathfinder-autonomous/pi-mission/tests/test_runtime_tick_commands.py` (it already imports `FakeEsp32Link`, `SweepSessionStatus`, and defines `_make_started_runtime(tmp_path, commands, acked)`/`_make_idle_runtime(tmp_path, commands, acked)` — reuse them, do not redefine):

```python
def test_ota_update_is_refused_while_sweep_session_in_progress(tmp_path):
    commands = [{"_id": "cmd-1", "type": "ota_update", "payload": {"firmware_path": "/firmware/v2.bin"}}]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    assert runtime.sweep_session.status == SweepSessionStatus.IN_PROGRESS
    runtime._last_command_poll_monotonic = 0.0  # force a poll this tick

    runtime.tick()  # must not raise out of the tick itself

    assert runtime.esp32_link.ota_triggers == []  # never actually triggered
    assert acked == []  # never acked, so the backend redelivers it next poll


def test_ota_update_proceeds_with_no_sweep_session(tmp_path):
    commands = [{"_id": "cmd-1", "type": "ota_update", "payload": {"firmware_path": "/firmware/v2.bin"}}]
    acked = []
    runtime = _make_idle_runtime(tmp_path, commands, acked)
    assert runtime.sweep_session is None
    runtime._last_command_poll_monotonic = 0.0

    runtime.tick()

    assert runtime.esp32_link.ota_triggers == ["/firmware/v2.bin"]
    assert acked == ["/commands/cmd-1/ack"]


def test_ota_update_proceeds_when_sweep_session_is_interrupted_not_in_progress(tmp_path):
    """Regression test for the exact correctness gap this plan's design
    found: sweep_session is never reset to None after a pause/stop, so
    gating on mere presence (rather than .status == IN_PROGRESS) would
    block OTA forever after the very first mission ever run.
    """
    commands = [{"_id": "cmd-1", "type": "ota_update", "payload": {"firmware_path": "/firmware/v2.bin"}}]
    acked = []
    runtime = _make_started_runtime(tmp_path, commands, acked)
    runtime.sweep_session.interrupt(datetime.now(timezone.utc))
    assert runtime.sweep_session.status == SweepSessionStatus.INTERRUPTED
    runtime._last_command_poll_monotonic = 0.0

    runtime.tick()

    assert runtime.esp32_link.ota_triggers == ["/firmware/v2.bin"]
    assert acked == ["/commands/cmd-1/ack"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run (from `pathfinder-autonomous/pi-mission/`): `pytest tests/test_runtime_tick_commands.py -k ota_update -v`
Expected: FAIL — all three tests fail with a warning log ("received unhandled command type 'ota_update'") and `acked == ["/commands/cmd-1/ack"]` in every case (today's `_handle_command` falls through to the `else` branch for any unrecognized type, which still acks it per that branch's own comment) — so `test_ota_update_is_refused_while_sweep_session_in_progress`'s `assert acked == []` fails, and the other two tests fail on `assert runtime.esp32_link.ota_triggers == [...]` since nothing ever calls `trigger_ota`.

- [ ] **Step 3: Write the implementation**

In `papaya_mission/runtime.py`'s `_handle_command`, find this exact existing block:

```python
        elif command_type == "update_geofence":
            all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
            self.exclusion_polygons = [
                shape(g["boundary"]) for g in all_geofences if g["type"] == "exclusive"
            ]
        else:
```

Insert a new branch between `update_geofence` and the `else`:

```python
        elif command_type == "update_geofence":
            all_geofences = backend_client.list_geofences(self.http_client, self.backend_base_url)
            self.exclusion_polygons = [
                shape(g["boundary"]) for g in all_geofences if g["type"] == "exclusive"
            ]
        elif command_type == "ota_update":
            self._handle_ota_update(command.get("payload", {}))
        else:
```

Then add the new method. Place it immediately after `_handle_command` (find `_handle_command`'s closing `logger.warning(...)` block and the blank line after it, and insert the new method there):

```python
    def _handle_ota_update(self, payload: dict[str, Any]) -> None:
        # sweep_session is never reset to None anywhere in this class --
        # pausing/stopping/completing a sweep only changes its .status.
        # Checking mere presence here would block OTA forever after the
        # very first mission this rover ever runs; checking IN_PROGRESS
        # specifically (same idiom as the stop_sweep/abort_home branch
        # above) is the correct "a mission is actually underway" check.
        if self.sweep_session is not None and self.sweep_session.status == SweepSessionStatus.IN_PROGRESS:
            # Raising (rather than silently returning) means the caller in
            # _poll_and_handle_commands_if_due never acks this command, so
            # the backend redelivers it next poll -- the OTA retries
            # automatically once the mission pauses or ends, with no new
            # ack/nack protocol needed.
            raise RuntimeError(
                "refusing OTA update while a sweep session is in progress -- "
                "will retry automatically once the mission pauses/ends"
            )
        self.esp32_link.trigger_ota(payload["firmware_path"])
```

**Correction (final review, 2026-10-02):** The comment above (and this plan's Goal/Architecture framing) claiming the backend "redelivers" an unacked `ota_update` command is false. `pathfinder-autonomous/backend/app/services/commands.py`'s `poll_commands` transitions a command to `"delivered"` on poll, and nothing ever moves a `"delivered"` command back to `"pending"` -- confirmed by the existing backend test `test_poll_does_not_redeliver_already_delivered_commands`. So a refused OTA command is actually dropped permanently, not retried automatically; the operator must notice the refusal (now a dedicated `logger.warning` naming exactly what happened) and manually re-issue the OTA once the mission has ended. The safety-gating behavior itself is unaffected and correct. See `docs/phase2/inputs/00-inbox.md`'s "Command redelivery / OTA follow-ups" section for the backend-wide follow-up.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_runtime_tick_commands.py -v`
Expected: PASS (all tests in the file, including the 3 new ones)

- [ ] **Step 5: Run the full test suite and verify everything passes**

Run: `pytest -v` (from `pathfinder-autonomous/pi-mission/`)
Expected: PASS — all prior tests plus this plan's 3 new tests (count the real total from your own run). Note: there is a KNOWN, pre-existing, unrelated flaky test group (`tests/test_digital_twin_scenarios.py`, `tests/test_hardware_drivers_integration.py` — timing-sensitive, documented in `docs/phase2/inputs/00-inbox.md`) that can occasionally show a few failures under full-suite wall-clock load. If you see ONLY those fail, re-run them in isolation to confirm, and don't treat it as caused by this change.

- [ ] **Step 6: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/runtime.py pathfinder-autonomous/pi-mission/tests/test_runtime_tick_commands.py
git commit -m "feat(pi-mission): add Pi-side OTA safety gating (refuse while a sweep is in progress)"
```
