import pytest

from app.models.command import CommandCreate
from app.models.geo import GeoPolygon
from app.models.geofence import GeofenceCreate
from app.models.rover import RoverCreate
from app.services import commands as command_service
from app.services import geofences as geofence_service
from app.services import rovers as rover_service

FIELD_RING = [
    (-85.10, 38.00),
    (-85.10, 38.10),
    (-84.90, 38.10),
    (-84.90, 38.00),
    (-85.10, 38.00),
]


def _make_geofence(db):
    return geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="inclusive",
            name="Main field",
            boundary=GeoPolygon(coordinates=[FIELD_RING]),
        ),
    )


def test_enqueue_and_poll_command(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    geofence = _make_geofence(db)

    enqueued = command_service.enqueue_command(
        db,
        CommandCreate(
            rover_id=rover.id,
            type="update_geofence",
            payload={"geofence_id": geofence.id},
        ),
    )
    assert enqueued.status == "pending"

    polled = command_service.poll_commands(db, rover.id)

    assert len(polled) == 1
    assert polled[0].id == enqueued.id
    assert polled[0].status == "delivered"


def test_poll_only_returns_own_rovers_commands(db):
    rover_a = rover_service.create_rover(db, RoverCreate(name="George"))
    rover_b = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_a.id, type="update_geofence", payload={})
    )

    polled_b = command_service.poll_commands(db, rover_b.id)

    assert polled_b == []


def test_poll_does_not_redeliver_already_delivered_commands(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="update_geofence", payload={})
    )
    command_service.poll_commands(db, rover.id)

    second_poll = command_service.poll_commands(db, rover.id)

    assert second_poll == []


def test_ack_command_marks_it_acked(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    enqueued = command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="update_geofence", payload={})
    )

    acked = command_service.ack_command(db, enqueued.id)

    assert acked.status == "acked"
    assert acked.acked_at is not None


def test_ack_unknown_command_raises(db):
    with pytest.raises(command_service.CommandNotFound):
        command_service.ack_command(db, "000000000000000000000000")


def test_enqueue_command_for_unknown_rover_raises(db):
    with pytest.raises(rover_service.RoverNotFound):
        command_service.enqueue_command(
            db,
            CommandCreate(
                rover_id="000000000000000000000000", type="update_geofence", payload={}
            ),
        )


def test_start_sweep_activates_rover(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))

    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="start_sweep", payload={})
    )

    assert rover_service.get_rover(db, rover.id).status == "active"


def test_start_sweep_rejected_while_another_rover_active(db):
    rover_a = rover_service.create_rover(db, RoverCreate(name="George"))
    rover_b = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_a.id, type="start_sweep", payload={})
    )

    with pytest.raises(rover_service.AnotherRoverActive):
        command_service.enqueue_command(
            db, CommandCreate(rover_id=rover_b.id, type="start_sweep", payload={})
        )


def test_stop_sweep_deactivates_rover(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="start_sweep", payload={})
    )

    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="stop_sweep", payload={})
    )

    assert rover_service.get_rover(db, rover.id).status == "inactive"


def test_abort_home_deactivates_rover(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="start_sweep", payload={})
    )

    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="abort_home", payload={})
    )

    assert rover_service.get_rover(db, rover.id).status == "inactive"


def test_pause_sweep_does_not_deactivate_rover(db):
    # A paused mission still owns the rover -- only stop_sweep/abort_home release it.
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="start_sweep", payload={})
    )

    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="pause_sweep", payload={})
    )

    assert rover_service.get_rover(db, rover.id).status == "active"


def test_pause_sweep_keeps_lock_against_other_rovers(db):
    rover_a = rover_service.create_rover(db, RoverCreate(name="George"))
    rover_b = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_a.id, type="start_sweep", payload={})
    )
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_a.id, type="pause_sweep", payload={})
    )

    with pytest.raises(rover_service.AnotherRoverActive):
        command_service.enqueue_command(
            db, CommandCreate(rover_id=rover_b.id, type="start_sweep", payload={})
        )


def test_pause_then_resume_same_rover_stays_active(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="start_sweep", payload={})
    )
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="pause_sweep", payload={})
    )
    assert rover_service.get_rover(db, rover.id).status == "active"

    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="resume_sweep", payload={})
    )

    assert rover_service.get_rover(db, rover.id).status == "active"


def test_resume_sweep_rejected_when_another_rover_grabbed_the_lock(db):
    # A stopped its sweep (releasing the rover), B started one, and now A tries to
    # resume: resume must re-assert the lock and be refused.
    rover_a = rover_service.create_rover(db, RoverCreate(name="George"))
    rover_b = rover_service.create_rover(db, RoverCreate(name="Rover2"))
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_a.id, type="start_sweep", payload={})
    )
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_a.id, type="stop_sweep", payload={})
    )
    command_service.enqueue_command(
        db, CommandCreate(rover_id=rover_b.id, type="start_sweep", payload={})
    )

    with pytest.raises(rover_service.AnotherRoverActive):
        command_service.enqueue_command(
            db, CommandCreate(rover_id=rover_a.id, type="resume_sweep", payload={})
        )

    assert rover_service.get_rover(db, rover_b.id).status == "active"
    assert rover_service.get_rover(db, rover_a.id).status == "inactive"


def test_start_sweep_with_unknown_geofence_id_raises(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))

    with pytest.raises(geofence_service.GeofenceNotFound):
        command_service.enqueue_command(
            db,
            CommandCreate(
                rover_id=rover.id,
                type="start_sweep",
                payload={"geofence_id": "000000000000000000000000"},
            ),
        )


def test_start_sweep_with_unknown_geofence_id_does_not_activate_rover(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))

    with pytest.raises(geofence_service.GeofenceNotFound):
        command_service.enqueue_command(
            db,
            CommandCreate(
                rover_id=rover.id,
                type="start_sweep",
                payload={"geofence_id": "000000000000000000000000"},
            ),
        )

    assert rover_service.get_rover(db, rover.id).status == "inactive"
    assert command_service.poll_commands(db, rover.id) == []


def test_update_geofence_with_unknown_geofence_id_raises(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))

    with pytest.raises(geofence_service.GeofenceNotFound):
        command_service.enqueue_command(
            db,
            CommandCreate(
                rover_id=rover.id,
                type="update_geofence",
                payload={"geofence_id": "000000000000000000000000"},
            ),
        )


def test_start_sweep_with_real_geofence_id_succeeds(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))
    geofence = _make_geofence(db)

    enqueued = command_service.enqueue_command(
        db,
        CommandCreate(
            rover_id=rover.id,
            type="start_sweep",
            payload={"geofence_id": geofence.id},
        ),
    )

    assert enqueued.status == "pending"
    assert enqueued.payload["geofence_id"] == geofence.id
    assert rover_service.get_rover(db, rover.id).status == "active"


def test_geofence_id_is_optional_in_payload(db):
    # Commands that legitimately omit geofence_id must still be accepted.
    rover = rover_service.create_rover(db, RoverCreate(name="George"))

    enqueued = command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="start_sweep", payload={})
    )

    assert enqueued.status == "pending"
