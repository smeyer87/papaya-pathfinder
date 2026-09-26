from papaya_mission.gps_loss_decision import decide_gps_loss_response


def test_within_grace_period_and_error_continues():
    result = decide_gps_loss_response(
        seconds_since_last_fix=2.0,
        current_error_radius_m=3.0,
        grace_period_s=5.0,
        max_error_radius_m=10.0,
    )

    assert result == "continue_dead_reckoning"


def test_grace_period_exceeded_stops():
    result = decide_gps_loss_response(
        seconds_since_last_fix=6.0,
        current_error_radius_m=3.0,
        grace_period_s=5.0,
        max_error_radius_m=10.0,
    )

    assert result == "stop_and_alert"


def test_error_radius_exceeded_stops_even_within_grace_period():
    result = decide_gps_loss_response(
        seconds_since_last_fix=1.0,
        current_error_radius_m=15.0,
        grace_period_s=5.0,
        max_error_radius_m=10.0,
    )

    assert result == "stop_and_alert"
