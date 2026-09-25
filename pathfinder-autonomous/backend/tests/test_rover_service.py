import pytest

from app.models.rover import RoverCreate, RoverUpdate, SensorManifestEntry
from app.services import rovers as rover_service


def test_create_and_get_rover(db):
    created = rover_service.create_rover(
        db, RoverCreate(name="George", supported_mission_packages=["MP-1"])
    )

    fetched = rover_service.get_rover(db, created.id)

    assert fetched.name == "George"
    assert fetched.supported_mission_packages == ["MP-1"]
    assert fetched.status == "inactive"


def test_get_rover_not_found_raises(db):
    with pytest.raises(rover_service.RoverNotFound):
        rover_service.get_rover(db, "000000000000000000000000")


def test_list_rovers_returns_all(db):
    rover_service.create_rover(db, RoverCreate(name="George"))
    rover_service.create_rover(db, RoverCreate(name="Rover2"))

    rovers = rover_service.list_rovers(db)

    assert {r.name for r in rovers} == {"George", "Rover2"}


def test_update_rover_sensor_manifest(db):
    created = rover_service.create_rover(db, RoverCreate(name="George"))

    updated = rover_service.update_rover(
        db,
        created.id,
        RoverUpdate(
            sensor_manifest=[SensorManifestEntry(sensor="gps", installed=True)]
        ),
    )

    assert updated.sensor_manifest[0].sensor == "gps"
    assert updated.name == "George"  # untouched field preserved


def test_activate_rover_sets_status_active(db):
    created = rover_service.create_rover(db, RoverCreate(name="George"))

    activated = rover_service.activate_rover(db, created.id)

    assert activated.status == "active"


def test_activate_second_rover_while_first_active_raises(db):
    first = rover_service.create_rover(db, RoverCreate(name="George"))
    second = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    rover_service.activate_rover(db, first.id)

    with pytest.raises(rover_service.AnotherRoverActive) as exc_info:
        rover_service.activate_rover(db, second.id)

    assert exc_info.value.active_rover_id == first.id


def test_deactivate_then_activate_another_succeeds(db):
    first = rover_service.create_rover(db, RoverCreate(name="George"))
    second = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    rover_service.activate_rover(db, first.id)

    rover_service.deactivate_rover(db, first.id)
    activated_second = rover_service.activate_rover(db, second.id)

    assert activated_second.status == "active"


def test_reactivating_the_same_rover_is_a_safe_no_op(db):
    created = rover_service.create_rover(db, RoverCreate(name="George"))
    rover_service.activate_rover(db, created.id)

    result = rover_service.activate_rover(db, created.id)

    assert result.status == "active"
