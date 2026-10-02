"""LCD status display: a small set of screens cycled by up/down
buttons, with 2 function buttons whose meaning depends on the current
screen (soft-key style) -- see design spec:
docs/superpowers/specs/2026-09-30-breadboard-bench-rig-design.md.

Reads the same state MissionRuntime already assembles into telemetry
each tick -- no separate data path. The LCD write backend (the real
1602A/PCF8574 byte-banged protocol -- see github.com/UCTRONICS/KB0005
for the confirmed reference) is injected via the constructor, so every
screen/navigation/dispatch rule here is testable without a real LCD.
Building the real PCF8574 writer is bench-time work, not done here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class LcdWriter(Protocol):
    """Writes exactly two lines (already truncated to the display's
    width) to the physical LCD.
    """

    def write_lines(self, line1: str, line2: str) -> None: ...


@dataclass(frozen=True)
class Screen:
    name: str
    render: Callable[[dict[str, Any]], tuple[str, str]]
    # Maps function-button index (0 or 1) to an action taken on press.
    # A screen with no entry for a given index does nothing on that
    # button -- not every screen needs to use both function buttons.
    function_actions: dict[int, Callable[[dict[str, Any]], None]] = field(default_factory=dict)


def _render_position(state: dict[str, Any]) -> tuple[str, str]:
    position = state.get("position")
    heading = state.get("heading_deg")
    if position is None or heading is None:
        return ("GPS: no fix", "")
    lon, lat = position
    return (f"{lat:.5f},{lon:.5f}", f"Hdg {heading:.0f} deg")


def _render_mission(state: dict[str, Any]) -> tuple[str, str]:
    alert = state.get("mission_alert") or "none"
    nav_mode = state.get("nav_mode", "idle")
    return (f"Mode: {nav_mode}", f"Alert: {alert}")


def _render_obstacles(state: dict[str, Any]) -> tuple[str, str]:
    count = state.get("obstacle_count", 0)
    last_type = state.get("last_obstacle_type", "-")
    return (f"Obstacles: {count}", f"Last: {last_type}")


def _render_drive(state: dict[str, Any]) -> tuple[str, str]:
    if "throttle_position" not in state:
        # Absent, not 0.0: same ESP32-status-read-failed (or no-sample-yet)
        # gap as halted_on_contact below -- see MissionRuntime
        # ._sample_telemetry_if_due. A missing throttle reading is not a
        # confirmed zero throttle.
        line1 = "Throttle: ?"
    else:
        line1 = f"Throttle: {state['throttle_position']:.2f}"
    if "halted_on_contact" not in state:
        # Absent, not False: either the ESP32 status read failed this
        # sample (see MissionRuntime._sample_telemetry_if_due) or no
        # sample has completed yet. Neither is "confirmed not halted".
        status_text = "LINK?"
    else:
        status_text = "HALTED" if state["halted_on_contact"] else "running"
    return (line1, status_text)


DEFAULT_SCREENS: list[Screen] = [
    Screen(name="position", render=_render_position),
    Screen(name="mission", render=_render_mission),
    Screen(name="obstacles", render=_render_obstacles),
    Screen(name="drive", render=_render_drive),
]


class StatusDisplay:
    def __init__(self, lcd: LcdWriter, screens: list[Screen] | None = None) -> None:
        self._lcd = lcd
        self._screens = screens if screens is not None else DEFAULT_SCREENS
        self._index = 0

    @property
    def current_screen(self) -> Screen:
        return self._screens[self._index]

    def next_screen(self) -> None:
        self._index = (self._index + 1) % len(self._screens)

    def previous_screen(self) -> None:
        self._index = (self._index - 1) % len(self._screens)

    def press_function_button(self, index: int, state: dict[str, Any]) -> None:
        action = self.current_screen.function_actions.get(index)
        if action is not None:
            action(state)

    def refresh(self, state: dict[str, Any]) -> None:
        line1, line2 = self.current_screen.render(state)
        self._lcd.write_lines(line1[:16], line2[:16])
