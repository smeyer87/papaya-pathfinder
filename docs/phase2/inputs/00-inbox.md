# 00 — Inbox

Anything that doesn't obviously belong in another file. No formatting
required — bullets, fragments, links, questions. This gets triaged into
the numbered files during the planning session.

---

<!-- Triaged 2026-09-24: Mission Package Summary → 01-missions.md (MP-1..MP-4);
Capability Summary → 02-capabilities.md (CAP-1..CAP-12); Sensor Updates →
03-sensors-compute-electronics.md (SEN-1..SEN-6, CMP-1, PWR-1..PWR-3,
COM-1..COM-4); Physical Platform Updates → 04-physical-platform.md
(PLT-1..PLT-6); Key Assumptions → 05-assumptions-decisions.md
(A-1, D-1..D-5, Q-1..Q-8). -->

## Training mode / recovery-maneuver capture (2026-09-30, not yet triaged)

From real test runs: small ground obstacles (a fallen branch, a rut, tall
grass/plants) likely won't register via camera or ultrasonic, but still
impair wheel operation. Idea: a "training mode" — deliberately stage one
of these situations, drive into it and out of it manually, and capture
telemetry at a much higher frequency (multi-Hz, vs. normal mission
cadence) to record the control inputs/response that got the rover unstuck
(e.g. added throttle over a branch, reverse-with-turn out of a rut).
Explicitly an early step toward autonomous recovery, not a near-term
build. Open question the user raised themselves: is this a capability
that supports many/all missions (most likely framing), or its own mission
package? Leave open until a real planning pass.

## OTA safety gating: no-mission-underway check (2026-09-30)

From the breadboard design session: OTA firmware updates should be
restricted to when a mission is NOT underway (no accidental reflash
mid-mission). A "WiFi in range" condition doesn't need separate
handling — the Pi can't call `trigger_ota()` without a firmware file
it already downloaded over WiFi, so that gate already exists
structurally. "No mission underway" is the real one, and splits into
two tiers worth keeping distinct:
- **Pi-side gating (straightforward, do this):** before calling
  `trigger_ota()`, check whether `MissionRuntime` has an active
  `SweepSession` and refuse if so.
- **Device-level veto (real tradeoff, not for the breadboard):** the
  ESP32 itself refusing a reflash independent of whether the Pi got it
  right. This conflicts with the breadboard's simplified OTA mechanism
  (`esptool`'s DTR/RTS auto-reset bypasses the running firmware
  entirely — nothing to hook a refusal into). Getting genuine
  defense-in-depth here means a cooperative handshake (Pi asks "safe to
  flash?", firmware checks its own mission-active state and acks/
  nacks) instead of the bare auto-reset. Belongs in the real ESP32
  firmware plan, where OTA sophistication is already expected to grow
  — not built into the bench rig's first-pass OTA validation.

## Manual drive override via LCD + spare ELRS controller (2026-09-30)

A second controller/receiver could let an operator manually override
drive mode (triggered via an LCD screen/button) to extract a stuck rover,
then resume the mission or head home. This is the concrete answer to an
open question from the breadboard design session: once the ESP32 firmware
plan adds a real Pi→ESP32 autonomous drive-command channel, something has
to arbitrate autonomous-vs-human control — a local, LCD-triggered
override (works even with no WiFi/backend) is a clean mechanism, and
ties naturally to the existing `pause_sweep`/`abort_home` command
handling already in `MissionRuntime`. Reserve an LCD screen/function-key
slot for this later; not built as part of the breadboard itself (no
autonomous drive-command channel exists yet to override).

## StatusDisplay follow-ups from the runtime-state-gap plan (2026-10-01)

From the final whole-branch review of
`docs/superpowers/plans/2026-10-01-status-display-runtime-gap.md`:

- **FIXED (2026-10-01):** Drive screen couldn't distinguish "confirmed not
  halted" from "couldn't read the ESP32's status this sample" (and had the
  identical gap for `throttle_position`). `_render_drive` now checks for
  key absence explicitly for both fields: `halted_on_contact` absent shows
  "LINK?" instead of a false "running", and `throttle_position` absent
  shows "Throttle: ?" instead of a false "Throttle: 0.00". See
  `docs/superpowers/plans/2026-10-01-drive-screen-halted-ambiguity.md` for
  the fix plan and tests.
- **FIXED (2026-10-02):** A resumed (not fresh) sweep session restarted
  `obstacle_count` at 0 instead of seeding it from the obstacles already
  persisted for that session. `_resume_in_progress_session_if_any` now
  seeds `_obstacle_count`/`_last_obstacle_type` from
  `local_store.list_obstacles_for_session(...)` for that session, and
  `_save_obstacle` only increments the count for a genuinely new detection
  (no existing `obstacle_id`) so a confirmed re-detection during the resume
  pass no longer double-counts against that seeded baseline. See
  `docs/superpowers/plans/2026-10-02-resumed-session-obstacle-count.md` for
  the fix plan and tests.
- **FIXED (2026-10-02):** The position screen's `f"{lat:.5f},{lon:.5f}"`
  could exceed the LCD's 16-char width and silently truncate (e.g.
  `"38.05000,-85.000"` — longitude's last digit(s) cut off).
  `_render_position` now formats to 4 decimal places instead of 5, which
  fits exactly 16 characters for this rover's realistic coordinate range.
  See `docs/superpowers/plans/2026-10-02-position-screen-truncation.md`
  for the fix plan and tests.
- **Syncing `obstacle_count`/`last_obstacle_type`/`halted_on_contact` to
  ground control** was explicitly deferred during that plan's
  brainstorming (kept local/live-only, read via
  `MissionRuntime.last_telemetry_readings`, deliberately kept out of
  `MP1_EXPECTED_METRICS`/the backend sync path) — a good long-term idea,
  not built there. A regression test now locks in that the deferral holds
  (`test_live_only_fields_are_never_synced_to_the_telemetry_record`), so
  future work has to touch that test deliberately, not drift into it by
  accident.
- **`hardware_esp32_link.py:98`'s `bool(message.get("halted", False))` has
  the same absent-vs-default pattern one layer down.** A `status` message
  missing its `"halted"` key silently resets `_halted_on_contact` to
  `False`, which could clear a latched halt. Depends on the ESP32
  firmware's actual message contract, which isn't built yet — flag it as
  something to check once the real firmware's message shapes are known,
  not something to fix now.
- **Full-suite test runs occasionally show 3-4 unrelated test failures**
  (`tests/test_digital_twin_scenarios.py`,
  `tests/test_hardware_drivers_integration.py`) that always pass in
  isolation — looks like wall-clock sensitivity (tests manipulate
  monotonic state directly while runtime code compares against real
  `time.monotonic()`, so a slow/cold full-suite run can cross a threshold
  mid-test). Pre-existing, unrelated to any specific plan; worth a
  dedicated look (e.g. injecting a fake clock into the affected runtime
  checks) at some point.
- **`HardwareImuSource.read()` (in `hardware_sensor_hub.py`) returns a
  confident-looking but potentially dishonest heading during IMU
  cold-boot.** Per `sensor_hub.py`'s own docstring ("a driver that cannot
  read SHOULD return its last known reading"), `read()` correctly falls
  back to `self._last_reading` whenever the real BNO055 reports
  `(None, None, None)` (not yet calibrated). But `_last_reading` is seeded
  at construction with `heading_deg=0.0`, so a rover whose IMU hasn't
  finished calibrating at boot reports a confident heading of 0.0 (due
  north) rather than an honest "unknown" — indistinguishable from a
  genuinely north-facing rover, and every obstacle logged during that
  warm-up window gets misplaced by the true heading error. Surfaced by the
  final review of
  `docs/superpowers/plans/2026-10-02-position-fusion-heading-staleness.md`
  (now that the Pi-side math is correct, this is the one remaining path by
  which a stale heading reaches obstacle placement in production). Fix
  direction: expose reading age/validity from `HardwareImuSource`, or
  refuse to emit a reading before the BNO055 reports calibration —
  bench-time work, not fixable from pure software here.
