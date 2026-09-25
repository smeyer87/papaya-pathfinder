def test_create_get_list_update_rover_via_api(client):
    create_response = client.post("/rovers", json={"name": "George"})
    assert create_response.status_code == 201
    rover_id = create_response.json()["_id"]

    get_response = client.get(f"/rovers/{rover_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "George"

    list_response = client.get("/rovers")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    update_response = client.patch(f"/rovers/{rover_id}", json={"notes": "prototype A"})
    assert update_response.status_code == 200
    assert update_response.json()["notes"] == "prototype A"


def test_get_unknown_rover_returns_404(client):
    response = client.get("/rovers/000000000000000000000000")

    assert response.status_code == 404
