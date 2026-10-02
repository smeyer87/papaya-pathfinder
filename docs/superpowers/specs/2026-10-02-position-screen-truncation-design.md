# Position-Screen LCD Truncation — Design

**Status:** Approved, pending plan
**Related:** `docs/phase2/inputs/00-inbox.md` (follow-up logged 2026-10-01), `pathfinder-autonomous/pi-mission/papaya_mission/status_display.py`

## Problem

`_render_position`'s first line, `f"{lat:.5f},{lon:.5f}"`, is 18 characters for this rover's real operating region (e.g. `lat=38.05, lon=-85.0` → `"38.05000,-85.00000"`), but `StatusDisplay.refresh` truncates every line to 16 characters before writing it to the LCD. Longitude's last 1-2 digits silently disappear. This isn't a GPS-fix-quality issue (re-checking with real fixes wouldn't change it) — it's a fixed format-width bug: any latitude/longitude pair in this rover's realistic range renders to the same 18 characters regardless of fix accuracy.

## Fix

Reduce precision from 5 to 4 decimal places: `f"{lat:.4f},{lon:.4f}"`.

For this rover's realistic coordinate range (2-digit latitude, up to 3-digit-signed longitude — matching the Kentucky-area test fixtures used throughout this codebase, e.g. `lat≈38`, `lon≈-85`), this renders to exactly 16 characters: `"38.0500,-85.0000"` (7 + 1 + 8 = 16). No truncation.

4 decimal places is ≈11m of precision at this latitude — already finer than the GPS accuracy heuristic's own resolution (`accuracy_m = hdop * 5.0`, typically 5-50m for a real fix), so nothing meaningful is lost versus 5 decimals (≈1.1m, false precision given the sensor's actual accuracy).

**Not handled:** an extreme global coordinate (near a pole, or the antimeridian, where the integer part grows to 3 digits for latitude or 4 for longitude) would still truncate under this fix. Out of scope — this rover operates in one fixed real-world region, not globally, so the realistic range is the right design target, not the theoretical range of all possible latitudes/longitudes.

## Testing

- Add a direct unit test for `_render_position` in `tests/test_status_display.py` (no such test currently exists — it's only exercised indirectly today): given a representative position/heading in this rover's realistic range, assert the rendered first line is exactly 16 characters or fewer, and that the full expected string matches precisely (e.g. `"38.0500,-85.0000"` for `lat=38.05, lon=-85.0`).
- The existing integration test's assertion (`"38.05" in position_line1`, `test_status_display_integration.py:74`) continues to pass unchanged — `"38.05"` is a prefix of `"38.0500"` either way, so no modification needed there.
- Confirm the existing `test_default_screens_render_without_raising_on_an_empty_state` (empty-state, no-fix case) still passes unmodified — the `"GPS: no fix"` branch is untouched by this fix.

## Out of scope

- No change to `_render_mission`, `_render_obstacles`, or `_render_drive`.
- No change to `runtime.py` or the GPS accuracy heuristic itself.
