import pytest

from papaya_mission.classification import LOW_CONFIDENCE_THRESHOLD, classify_permanence


def test_permanent_type_high_confidence_is_permanent_pending():
    assert classify_permanence("barrel", confidence=0.9) == "permanent-pending"


def test_temporary_type_high_confidence_is_temporary():
    assert classify_permanence("chair", confidence=0.9) == "temporary"


def test_permanent_type_low_confidence_is_not_promoted():
    assert classify_permanence("barrel", confidence=0.2) == "temporary"


def test_unrecognized_type_defaults_to_temporary():
    assert classify_permanence("mystery_object", confidence=0.95) == "temporary"


def test_confidence_exactly_at_threshold_is_not_low_confidence():
    assert classify_permanence("fence_post", confidence=LOW_CONFIDENCE_THRESHOLD) == "permanent-pending"


def test_confidence_out_of_range_raises():
    with pytest.raises(ValueError):
        classify_permanence("barrel", confidence=1.5)
    with pytest.raises(ValueError):
        classify_permanence("barrel", confidence=-0.1)
