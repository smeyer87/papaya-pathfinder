import httpx
import pytest

from papaya_mission import backend_client

BASE_URL = "http://backend.local"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_rover_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rovers/rover-1"
        return httpx.Response(200, json={"_id": "rover-1", "name": "George"})

    result = backend_client.fetch_rover(_client(handler), BASE_URL, "rover-1")

    assert result == {"_id": "rover-1", "name": "George"}


def test_fetch_geofence_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/geofences/fence-1"
        return httpx.Response(200, json={"_id": "fence-1", "type": "inclusive"})

    result = backend_client.fetch_geofence(_client(handler), BASE_URL, "fence-1")

    assert result == {"_id": "fence-1", "type": "inclusive"}


def test_list_geofences_returns_json_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/geofences"
        return httpx.Response(200, json=[{"_id": "fence-1"}, {"_id": "fence-2"}])

    result = backend_client.list_geofences(_client(handler), BASE_URL)

    assert result == [{"_id": "fence-1"}, {"_id": "fence-2"}]


def test_poll_commands_returns_json_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/commands/poll/rover-1"
        return httpx.Response(200, json=[{"_id": "cmd-1", "type": "pause_sweep"}])

    result = backend_client.poll_commands(_client(handler), BASE_URL, "rover-1")

    assert result == [{"_id": "cmd-1", "type": "pause_sweep"}]


def test_ack_command_posts_and_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/commands/cmd-1/ack"
        return httpx.Response(200, json={"_id": "cmd-1", "status": "acked"})

    result = backend_client.ack_command(_client(handler), BASE_URL, "cmd-1")

    assert result == {"_id": "cmd-1", "status": "acked"}


def test_fetch_rover_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    with pytest.raises(httpx.HTTPStatusError):
        backend_client.fetch_rover(_client(handler), BASE_URL, "unknown")
