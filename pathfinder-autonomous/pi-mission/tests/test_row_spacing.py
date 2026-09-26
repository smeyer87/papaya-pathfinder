import pytest

from papaya_mission.row_spacing import derive_row_spacing_m


def test_row_spacing_matches_sensor_width_for_spin_in_place():
    spacing = derive_row_spacing_m(sensor_detection_width_m=8.0, turn_style="spin_in_place")

    assert spacing == 8.0


def test_row_spacing_matches_sensor_width_when_graceful_turn_fits():
    spacing = derive_row_spacing_m(
        sensor_detection_width_m=8.0, turn_style="graceful", min_turn_diameter_m=3.0
    )

    assert spacing == 8.0


def test_rejects_non_positive_sensor_width():
    with pytest.raises(ValueError):
        derive_row_spacing_m(sensor_detection_width_m=0.0)


def test_rejects_infeasible_graceful_turn_diameter():
    with pytest.raises(ValueError):
        derive_row_spacing_m(
            sensor_detection_width_m=2.0, turn_style="graceful", min_turn_diameter_m=5.0
        )


def test_graceful_turn_without_a_diameter_is_treated_as_unconstrained():
    # No min_turn_diameter_m given -- nothing to check against, so it
    # falls back to the sensor-width spacing rather than erroring.
    spacing = derive_row_spacing_m(sensor_detection_width_m=8.0, turn_style="graceful")

    assert spacing == 8.0
