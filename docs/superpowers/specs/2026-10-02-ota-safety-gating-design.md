# OTA Safety Gating (Pi-Side) — Design

**Status:** Approved, pending plan
**Related:** `docs/phase2/inputs/00-inbox.md` (requirement logged 2026-09-30), `pathfinder-autonomous/pi-mission/papaya_mission/runtime.py`

## Background

The inbox note framed this as "before calling `trigger_ota()`, check whether `MissionRuntime` has an active `SweepSession` and refuse if so" — but checking the actual code first: `MissionRuntime._handle_command` has no command type that calls `trigger_ota()` at all yet. `Esp32Link.trigger_ota()` exists on the Protocol (and both `FakeEsp32Link`/`HardwareEsp32Link` implement it), but nothing in the runtime invokes it. This design adds the command handler itself, gated from the start — not a guard bolted onto an existing call site.

**A correctness detail the inbox note's wording glossed over, checked against the actual state machine before designing further:** `self.sweep_session` is **never reset to `None`** anywhere in `runtime.py` — `handle_start_sweep`/`_resume_in_progress_session_if_any` only ever *replace* it with a new `SweepSession`; stopping, pausing, or completing a sweep only changes its `.status` (`SweepSessionStatus.IN_PROGRESS` → `INTERRUPTED`/`COMPLETED`). So gating on "`sweep_session is not None`" literally, as the inbox phrased it, would block OTA forever after the very first mission ever run. The correct check is the session's **status**, matching the exact idiom already used for `stop_sweep`/`abort_home` at `runtime.py:859`: `sweep_session is not None and sweep_session.status == SweepSessionStatus.IN_PROGRESS`.

## Design

Add an `"ota_update"` command type to `_handle_command`'s existing if/elif chain, dispatching to a new `_handle_ota_update` method:

```python
elif command_type == "ota_update":
    self._handle_ota_update(command.get("payload", {}))
```

```python
def _handle_ota_update(self, payload: dict[str, Any]) -> None:
    if self.sweep_session is not None and self.sweep_session.status == SweepSessionStatus.IN_PROGRESS:
        raise RuntimeError(
            "refusing OTA update while a sweep session is in progress -- "
            "will retry automatically once the mission pauses/ends"
        )
    self.esp32_link.trigger_ota(payload["firmware_path"])
```

**Why `raise` instead of silently refusing:** `_poll_and_handle_commands_if_due`'s existing fault-isolation wrapper already treats any exception from `_handle_command` as "don't ack this command, let the backend redeliver it next poll" (its own comment: "No ack is sent on failure, so the backend can redeliver"). Raising when gated reuses this exact, already-tested mechanism — the OTA command simply gets retried automatically every poll cycle until the mission ends, with zero new ack/nack protocol needed. Two existing tests already prove this pattern works for other commands: `test_malformed_command_does_not_stop_the_tick_or_the_rest_of_the_batch` and `test_start_sweep_with_a_malformed_payload_does_not_raise_out_of_tick`, both confirming a raised exception means the command stays unacked while the rest of the tick/batch proceeds normally.

**Payload shape:** `{"firmware_path": "<path the Pi already downloaded over WiFi>"}` — matches the existing OTA mechanism design (Pi downloads firmware over its own WiFi connection, then flashes the ESP32 locally over the serial link; `trigger_ota` just needs the local file path). Accessed via `payload["firmware_path"]` (direct, not `.get()` with a default) — matching `handle_start_sweep`'s existing style for a genuinely required field with no sensible default.

## Explicitly out of scope

- **Device-level veto** (the ESP32 itself refusing a reflash independent of whether the Pi got it right) — already decided in the original inbox note as a real tradeoff requiring firmware cooperation (`esptool`'s DTR/RTS auto-reset bypasses the running firmware entirely, nothing to hook a refusal into), belongs in the ESP32 firmware plan, not here.
- **"WiFi in range" gating** — already established as structurally free: the Pi can't call `trigger_ota()` without a firmware file it already downloaded over WiFi, so no separate check is needed.
- Any change to `Esp32Link`, `FakeEsp32Link`, or `HardwareEsp32Link` — the gating lives entirely in `MissionRuntime`, before `trigger_ota()` is ever called; the link implementations are untouched.

## Testing

`tests/test_runtime_tick_commands.py` already has the exact fixture pattern needed (`_make_started_runtime`/`_make_idle_runtime`, a `commands`/`acked` list pair, and `_handler`'s `/commands/poll/rover-1` + `/commands/.../ack` routes):

- An `ota_update` command polled while `_make_started_runtime`'s session is `IN_PROGRESS` must NOT call `trigger_ota` and must NOT be acked (`acked == []`), matching the existing `test_start_sweep_with_a_malformed_payload_does_not_raise_out_of_tick`'s assertion shape.
- The same command polled via `_make_idle_runtime` (no sweep session at all) MUST call `trigger_ota` with the right `firmware_path` and MUST be acked.
- A command polled against a session whose status is `INTERRUPTED` (not `IN_PROGRESS`) MUST also succeed — proving the gate checks status, not mere presence, closing the exact correctness gap this design found in the inbox note's original phrasing.
- `runtime.tick()` must not raise out of the tick itself in the gated case — only the command goes unacked; the rest of that tick's work (and any other commands in the same batch) proceeds normally, matching the existing fault-isolation tests' pattern.
