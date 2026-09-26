def test_full_mission_sync_then_idempotent_retry(client):
    rover_id = client.post("/rovers", json={"name": "George"}).json()["_id"]
    field = client.post(
        "/geofences",
        json={
            "type": "inclusive",
            "name": "Main field",
            "boundary": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-85.001, 38.000],
                        [-85.001, 38.001],
                        [-85.000, 38.001],
                        [-85.000, 38.000],
                        [-85.001, 38.000],
                    ]
                ],
            },
        },
    ).json()

    sweep_session_payload = {
        "sessions": [
            {
                "_id": "sess-uuid-1",
                "rover_id": rover_id,
                "geofence_id": field["_id"],
                "status": "completed",
                "pattern": [
                    {"order": 0, "position": {"type": "Point", "coordinates": [-85.0, 38.0]}}
                ],
                "last_completed_waypoint_index": 0,
                "started_at": "2026-09-24T12:00:00Z",
                "completed_at": "2026-09-24T12:30:00Z",
            }
        ]
    }
    obstacle_payload = {
        "obstacles": [
            {
                "_id": "obs-uuid-1",
                "sweep_session_id": "sess-uuid-1",
                "position": {"type": "Point", "coordinates": [-85.0005, 38.0005]},
                "position_uncertainty_m": 1.5,
                "type": "barrel",
                "classification_confidence": 0.9,
                "detection_method": "ultrasonic+camera",
                "status": "permanent-pending",
                "first_detected_at": "2026-09-24T12:01:00Z",
            }
        ]
    }
    telemetry_payload = {
        "records": [
            {
                "_id": "tel-uuid-1",
                "rover_id": rover_id,
                "timestamp": "2026-09-24T12:00:05Z",
                "local_tz_offset_minutes": -300,
                "sweep_session_id": "sess-uuid-1",
                "sequence_number": 1,
                "metrics": {"battery_voltage": 11.8},
            }
        ]
    }

    first_pass = [
        client.post("/sync/sweep-sessions", json=sweep_session_payload),
        client.post("/sync/obstacles", json=obstacle_payload),
        client.post("/sync/telemetry", json=telemetry_payload),
    ]
    assert all(r.status_code == 200 and r.json() == {"synced": 1} for r in first_pass)

    # Simulate the connection dropping right after a successful sync, and
    # the rover retrying the same batch on its next Home-return checkpoint.
    retry = [
        client.post("/sync/sweep-sessions", json=sweep_session_payload),
        client.post("/sync/obstacles", json=obstacle_payload),
        client.post("/sync/telemetry", json=telemetry_payload),
    ]
    assert retry[0].json() == {"synced": 1}  # upsert -- still "processed", no duplicate created
    assert retry[1].json() == {"synced": 1}  # upsert -- same
    assert retry[2].json() == {"synced": 0}  # insert-only -- correctly reports nothing NEW
