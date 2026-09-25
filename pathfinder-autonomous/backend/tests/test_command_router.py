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


def test_start_sweep_rejected_via_api_when_another_rover_active(client):
    rover_a_id = client.post("/rovers", json={"name": "George"}).json()["_id"]
    rover_b_id = client.post("/rovers", json={"name": "Rover2"}).json()["_id"]
    client.post("/commands", json={"rover_id": rover_a_id, "type": "start_sweep", "payload": {}})

    response = client.post(
        "/commands", json={"rover_id": rover_b_id, "type": "start_sweep", "payload": {}}
    )

    assert response.status_code == 409
