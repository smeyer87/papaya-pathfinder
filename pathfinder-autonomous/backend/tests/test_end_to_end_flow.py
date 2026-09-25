def test_two_rover_fleet_mission_lifecycle(client):
    george = client.post(
        "/rovers", json={"name": "George", "supported_mission_packages": ["MP-1"]}
    ).json()
    prototype_b = client.post("/rovers", json={"name": "Prototype-B"}).json()

    field = client.post(
        "/geofences",
        json={
            "type": "inclusive",
            "name": "Main field",
            "boundary": {
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
            },
        },
    ).json()

    start = client.post(
        "/commands",
        json={
            "rover_id": george["_id"],
            "type": "start_sweep",
            "payload": {"geofence_id": field["_id"]},
        },
    )
    assert start.status_code == 201

    blocked = client.post(
        "/commands", json={"rover_id": prototype_b["_id"], "type": "start_sweep", "payload": {}}
    )
    assert blocked.status_code == 409

    polled = client.get(f"/commands/poll/{george['_id']}").json()
    assert len(polled) == 1
    assert polled[0]["type"] == "start_sweep"

    client.post(f"/commands/{polled[0]['_id']}/ack")

    stop = client.post(
        "/commands", json={"rover_id": george["_id"], "type": "stop_sweep", "payload": {}}
    )
    assert stop.status_code == 201

    now_allowed = client.post(
        "/commands", json={"rover_id": prototype_b["_id"], "type": "start_sweep", "payload": {}}
    )
    assert now_allowed.status_code == 201
