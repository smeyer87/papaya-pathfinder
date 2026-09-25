def test_enqueue_poll_ack_flow(client):
    rover_id = client.post("/rovers", json={"name": "George"}).json()["_id"]

    enqueue_response = client.post(
        "/commands", json={"rover_id": rover_id, "type": "update_geofence", "payload": {}}
    )
    assert enqueue_response.status_code == 201
    command_id = enqueue_response.json()["_id"]

    poll_response = client.get(f"/commands/poll/{rover_id}")
    assert poll_response.status_code == 200
    assert len(poll_response.json()) == 1
    assert poll_response.json()[0]["status"] == "delivered"

    ack_response = client.post(f"/commands/{command_id}/ack")
    assert ack_response.status_code == 200
    assert ack_response.json()["status"] == "acked"


FIELD_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-85.10, 38.00],
            [-85.10, 38.10],
            [-84.90, 38.10],
            [-84.90, 38.00],
            [-85.10, 38.00],
        ]
    ],
}


def test_enqueue_with_unknown_geofence_id_returns_404(client):
    rover_id = client.post("/rovers", json={"name": "George"}).json()["_id"]

    response = client.post(
        "/commands",
        json={
            "rover_id": rover_id,
            "type": "start_sweep",
            "payload": {"geofence_id": "000000000000000000000000"},
        },
    )

    assert response.status_code == 404
    assert client.get(f"/rovers/{rover_id}").json()["status"] == "inactive"


def test_enqueue_with_real_geofence_id_returns_201(client):
    rover_id = client.post("/rovers", json={"name": "George"}).json()["_id"]
    geofence_id = client.post(
        "/geofences",
        json={"type": "inclusive", "name": "Main field", "boundary": FIELD_POLYGON},
    ).json()["_id"]

    response = client.post(
        "/commands",
        json={
            "rover_id": rover_id,
            "type": "start_sweep",
            "payload": {"geofence_id": geofence_id},
        },
    )

    assert response.status_code == 201


def test_pause_then_resume_via_api_keeps_rover_active(client):
    rover_a_id = client.post("/rovers", json={"name": "George"}).json()["_id"]
    rover_b_id = client.post("/rovers", json={"name": "Rover2"}).json()["_id"]
    client.post(
        "/commands", json={"rover_id": rover_a_id, "type": "start_sweep", "payload": {}}
    )

    paused = client.post(
        "/commands", json={"rover_id": rover_a_id, "type": "pause_sweep", "payload": {}}
    )
    assert paused.status_code == 201
    assert client.get(f"/rovers/{rover_a_id}").json()["status"] == "active"

    # The lock is still held while paused.
    blocked = client.post(
        "/commands", json={"rover_id": rover_b_id, "type": "start_sweep", "payload": {}}
    )
    assert blocked.status_code == 409

    resumed = client.post(
        "/commands", json={"rover_id": rover_a_id, "type": "resume_sweep", "payload": {}}
    )
    assert resumed.status_code == 201
    assert client.get(f"/rovers/{rover_a_id}").json()["status"] == "active"


def test_start_sweep_rejected_via_api_when_another_rover_active(client):
    rover_a_id = client.post("/rovers", json={"name": "George"}).json()["_id"]
    rover_b_id = client.post("/rovers", json={"name": "Rover2"}).json()["_id"]
    client.post("/commands", json={"rover_id": rover_a_id, "type": "start_sweep", "payload": {}})

    response = client.post(
        "/commands", json={"rover_id": rover_b_id, "type": "start_sweep", "payload": {}}
    )

    assert response.status_code == 409
