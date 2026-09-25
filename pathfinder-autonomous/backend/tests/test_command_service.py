import pytest

from app.models.command import CommandCreate
from app.models.rover import RoverCreate
from app.services import commands as command_service
from app.services import rovers as rover_service


def test_enqueue_and_poll_command(db):
    rover = rover_service.create_rover(db, RoverCreate(name="George"))

    enqueued = command_service.enqueue_command(
        db, CommandCreate(rover_id=rover.id, type="update_geofence", payload={"geofence_id": "abc"})
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
