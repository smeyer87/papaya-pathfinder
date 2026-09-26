from papaya_mission.exclusion_decision import decide_exclusion_response


def test_shallow_intrusion_auto_reverses():
    assert decide_exclusion_response(intrusion_depth_m=0.3, rover_length_m=0.6) == "auto_reverse"


def test_deep_intrusion_waits_for_help():
    assert decide_exclusion_response(intrusion_depth_m=1.0, rover_length_m=0.6) == "wait_for_help"


def test_exactly_one_rover_length_waits_for_help():
    assert decide_exclusion_response(intrusion_depth_m=0.6, rover_length_m=0.6) == "wait_for_help"
