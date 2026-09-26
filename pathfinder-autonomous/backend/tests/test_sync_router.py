def test_sync_sweep_sessions_endpoint(client):
    payload = {
        "sessions": [
            {
                "_id": "sess-uuid-1",
                "rover_id": "rover-uuid-1",
                "geofence_id": "fence-uuid-1",
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

    response = client.post("/sync/sweep-sessions", json=payload)

    assert response.status_code == 200
    assert response.json() == {"synced": 1}


def test_sync_obstacles_endpoint(client):
    payload = {
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

    response = client.post("/sync/obstacles", json=payload)

    assert response.status_code == 200
    assert response.json() == {"synced": 1}


def test_sync_telemetry_endpoint(client):
    payload = {
        "records": [
            {
                "_id": "tel-uuid-1",
                "rover_id": "rover-uuid-1",
                "timestamp": "2026-09-24T12:00:05Z",
                "local_tz_offset_minutes": -300,
                "sweep_session_id": "sess-uuid-1",
                "sequence_number": 1,
                "metrics": {"battery_voltage": 11.8},
            }
        ]
    }

    response = client.post("/sync/telemetry", json=payload)

    assert response.status_code == 200
    assert response.json() == {"synced": 1}
