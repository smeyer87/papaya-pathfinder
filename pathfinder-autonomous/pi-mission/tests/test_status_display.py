from papaya_mission.status_display import Screen, StatusDisplay


class _FakeLcdWriter:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def write_lines(self, line1: str, line2: str) -> None:
        self.writes.append((line1, line2))


def _make_test_screens() -> tuple[list[Screen], list]:
    actions_taken = []
    return [
        Screen(name="a", render=lambda state: ("A1", "A2")),
        Screen(
            name="b",
            render=lambda state: ("B1", "B2"),
            function_actions={0: lambda state: actions_taken.append(("b", 0, state))},
        ),
    ], actions_taken


def test_starts_on_the_first_screen():
    screens, _ = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)

    assert display.current_screen.name == "a"


def test_next_screen_wraps_around():
    screens, _ = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)

    display.next_screen()
    assert display.current_screen.name == "b"
    display.next_screen()
    assert display.current_screen.name == "a"


def test_previous_screen_wraps_around():
    screens, _ = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)

    display.previous_screen()
    assert display.current_screen.name == "b"


def test_refresh_writes_the_current_screens_render_output():
    screens, _ = _make_test_screens()
    lcd = _FakeLcdWriter()
    display = StatusDisplay(lcd=lcd, screens=screens)

    display.refresh(state={})

    assert lcd.writes == [("A1", "A2")]


def test_refresh_truncates_lines_longer_than_16_characters():
    screens = [Screen(name="long", render=lambda state: ("A" * 20, "B" * 20))]
    lcd = _FakeLcdWriter()
    display = StatusDisplay(lcd=lcd, screens=screens)

    display.refresh(state={})

    line1, line2 = lcd.writes[0]
    assert len(line1) == 16
    assert len(line2) == 16


def test_function_button_dispatches_to_the_current_screens_action():
    screens, actions_taken = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)
    display.next_screen()  # move to screen "b", which has a function_actions[0]

    display.press_function_button(0, state={"key": "value"})

    assert actions_taken == [("b", 0, {"key": "value"})]


def test_function_button_with_no_action_for_that_index_does_nothing():
    screens, actions_taken = _make_test_screens()
    display = StatusDisplay(lcd=_FakeLcdWriter(), screens=screens)
    display.next_screen()  # screen "b" only has an action for index 0

    display.press_function_button(1, state={})

    assert actions_taken == []


def test_default_screens_render_without_raising_on_an_empty_state():
    from papaya_mission.status_display import DEFAULT_SCREENS

    for screen in DEFAULT_SCREENS:
        line1, line2 = screen.render({})
        assert isinstance(line1, str)
        assert isinstance(line2, str)


def test_drive_screen_shows_link_unknown_when_halted_on_contact_is_absent():
    from papaya_mission.status_display import DEFAULT_SCREENS

    drive_screen = next(s for s in DEFAULT_SCREENS if s.name == "drive")

    _line1, line2 = drive_screen.render({})

    assert line2 == "LINK?"


def test_drive_screen_still_shows_running_for_an_explicit_false():
    from papaya_mission.status_display import DEFAULT_SCREENS

    drive_screen = next(s for s in DEFAULT_SCREENS if s.name == "drive")

    _line1, line2 = drive_screen.render({"halted_on_contact": False})

    assert line2 == "running"
