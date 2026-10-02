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

- **Drive screen can't distinguish "confirmed not halted" from "couldn't
  read the ESP32's status this sample."** `_sample_telemetry_if_due`
  correctly omits `halted_on_contact` from the live snapshot when
  `esp32_link.status()` raises (rather than asserting a not-halted state
  it can't confirm), but `_render_drive`'s `state.get("halted_on_contact",
  False)` then reads that omission as "not halted" and the LCD says
  "running" — in exactly the situation (a dropped Pi↔ESP32 link) a bench
  operator would be staring at the screen to debug. Strictly better than
  before this branch (the field didn't exist at all), but the honest fix
  needs a third display state (e.g. "LINK?"/"UNKNOWN") in
  `_render_drive`/`status_display.py`, which that plan's additive-only
  scope forbade touching.
- **A resumed (not fresh) sweep session restarts `obstacle_count` at 0**
  instead of seeding it from the obstacles already persisted for that
  session. `handle_start_sweep` resets the counter; `_resume_in_progress_
  session_if_any` doesn't set it. The counter's own spec says it reports
  "this mission," and a resumed session is the same mission — a one-liner
  at the resume-arming site (count `local_store.list_obstacles_for_
  session(...)` for that session) would fix it, but neither the spec nor
  plan called for it, so it's an open design question, not a bug.
- **The position screen's `f"{lat:.5f},{lon:.5f}"` can exceed the LCD's
  16-char width and silently truncates** (e.g. `"38.05000,-85.000"` —
  longitude's last digit(s) cut off). Pre-existing `status_display.py`
  formatting, unrelated to any particular plan — first made visible by
  the runtime-state-gap plan's own integration test. Worth re-checking
  once real GPS fixes (not test coordinates) are in hand at the bench.
- **Syncing `obstacle_count`/`last_obstacle_type`/`halted_on_contact` to
  ground control** was explicitly deferred during that plan's
  brainstorming (kept local/live-only, read via
  `MissionRuntime.last_telemetry_readings`, deliberately kept out of
  `MP1_EXPECTED_METRICS`/the backend sync path) — a good long-term idea,
  not built there. A regression test now locks in that the deferral holds
  (`test_live_only_fields_are_never_synced_to_the_telemetry_record`), so
  future work has to touch that test deliberately, not drift into it by
  accident.
