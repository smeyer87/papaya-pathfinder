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

# A "bowtie": edge 1 ((-85.0, 38.0) -> (-84.9, 38.1)) crosses edge 3
# ((-84.9, 38.0) -> (-85.0, 38.1)). Pydantic's closure/range checks all pass, so
# only MongoDB's 2dsphere index catches this -- as a real WriteError at insert.
BOWTIE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-85.00, 38.00],
            [-84.90, 38.10],
            [-84.90, 38.00],
            [-85.00, 38.10],
            [-85.00, 38.00],
        ]
    ],
}


def test_create_geofence_returns_201(client):
    response = client.post(
        "/geofences",
        json={"type": "inclusive", "name": "Main field", "boundary": FIELD_POLYGON},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Main field"


def test_create_geofence_with_self_intersecting_polygon_returns_400(client):
    response = client.post(
        "/geofences",
        json={"type": "inclusive", "name": "Bowtie", "boundary": BOWTIE_POLYGON},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"]


def test_create_geofence_with_out_of_range_coordinate_returns_422(client):
    bad_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [-85.00, 38.00],
                [200.00, 38.10],
                [-84.90, 38.10],
                [-84.90, 38.00],
                [-85.00, 38.00],
            ]
        ],
    }

    response = client.post(
        "/geofences",
        json={"type": "inclusive", "name": "Out of range", "boundary": bad_polygon},
    )

    assert response.status_code == 422


def test_get_unknown_geofence_returns_404(client):
    response = client.get("/geofences/000000000000000000000000")

    assert response.status_code == 404
