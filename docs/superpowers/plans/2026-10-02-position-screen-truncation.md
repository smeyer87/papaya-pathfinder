# Position-Screen LCD Truncation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `_render_position` so its first line fits the LCD's 16-character width for this rover's realistic coordinate range, instead of silently losing longitude's last digits to `StatusDisplay.refresh`'s truncation.

**Architecture:** Reduce the coordinate format from 5 to 4 decimal places — a single format-string change in `_render_position`, plus a direct unit test (none currently exists for this function).

**Tech Stack:** Python 3.12, pytest. No new dependencies.

## Global Constraints

- The fix is localized to `_render_position` in `status_display.py` — no other renderer (`_render_mission`, `_render_obstacles`, `_render_drive`) changes.
- No changes to `runtime.py` or the GPS accuracy heuristic.
- 4 decimal places (not 3, not 5) — fits exactly 16 characters for this rover's realistic coordinate range (2-digit latitude, up to 3-digit-signed longitude) and is finer than the GPS accuracy heuristic's own resolution (`accuracy_m = hdop * 5.0`).
- Design spec: `docs/superpowers/specs/2026-10-02-position-screen-truncation-design.md`.

---

## File Structure

```
pathfinder-autonomous/pi-mission/
  papaya_mission/
    status_display.py          # MODIFY -- _render_position only
  tests/
    test_status_display.py     # MODIFY -- add 1 new unit test
```

---

### Task 1: Fit the position screen's first line within the LCD's 16-character width

**Files:**
- Modify: `pathfinder-autonomous/pi-mission/papaya_mission/status_display.py`
- Modify: `pathfinder-autonomous/pi-mission/tests/test_status_display.py`

**Interfaces:**
- Consumes: nothing new — `_render_position`'s signature (`Callable[[dict[str, Any]], tuple[str, str]]`) and its `DEFAULT_SCREENS` entry are unchanged.
- Produces: nothing consumed by a later task — this plan has one task.

- [ ] **Step 1: Write the failing test**

Append to `pathfinder-autonomous/pi-mission/tests/test_status_display.py` (no direct unit test for `_render_position` currently exists in this file — it's only exercised indirectly via the empty-state test and the separate integration test):

```python
def test_position_screen_fits_within_sixteen_characters():
    from papaya_mission.status_display import DEFAULT_SCREENS

    position_screen = next(s for s in DEFAULT_SCREENS if s.name == "position")

    line1, line2 = position_screen.render({"position": [-85.0, 38.05], "heading_deg": 90.0})

    assert line1 == "38.0500,-85.0000"
    assert len(line1) == 16
    assert line2 == "Hdg 90 deg"
```

- [ ] **Step 2: Run the test and verify it fails**

Run (from `pathfinder-autonomous/pi-mission/`): `pytest tests/test_status_display.py -k position_screen_fits -v`
Expected: FAIL — `AssertionError: assert '38.05000,-85.00000' == '38.0500,-85.0000'` (current code renders 5 decimal places, 18 characters, not 4/16)

- [ ] **Step 3: Write the implementation**

In `papaya_mission/status_display.py`, find this exact existing line:

```python
    return (f"{lat:.5f},{lon:.5f}", f"Hdg {heading:.0f} deg")
```

Replace it with:

```python
    # 4 decimal places (not 5): fits exactly 16 characters for this
    # rover's realistic coordinate range (2-digit latitude, up to
    # 3-digit-signed longitude) -- 5 decimals renders to 18 characters
    # here and StatusDisplay.refresh silently truncates the overflow.
    # ~11m of precision at this latitude, already finer than the GPS
    # accuracy heuristic's own resolution (accuracy_m = hdop * 5.0).
    return (f"{lat:.4f},{lon:.4f}", f"Hdg {heading:.0f} deg")
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `pytest tests/test_status_display.py -v`
Expected: PASS (all tests in the file, including the 1 new one)

- [ ] **Step 5: Run the full test suite and verify everything passes**

Run: `pytest -v` (from `pathfinder-autonomous/pi-mission/`)
Expected: PASS — all prior tests plus this plan's 1 new test. The existing integration test's assertion (`"38.05" in position_line1`, in `tests/test_status_display_integration.py`) is unaffected — `"38.05"` is a prefix of `"38.0500"` either way. Note: there is a KNOWN, pre-existing, unrelated flaky test group (`tests/test_digital_twin_scenarios.py`, `tests/test_hardware_drivers_integration.py` — timing-sensitive, documented in `docs/phase2/inputs/00-inbox.md`) that can occasionally show a few failures under full-suite wall-clock load. If you see ONLY those fail, re-run them in isolation to confirm, and don't treat it as caused by this change.

- [ ] **Step 6: Commit**

```bash
git add pathfinder-autonomous/pi-mission/papaya_mission/status_display.py pathfinder-autonomous/pi-mission/tests/test_status_display.py
git commit -m "fix(pi-mission): fit position screen within the LCD's 16-character width"
```
