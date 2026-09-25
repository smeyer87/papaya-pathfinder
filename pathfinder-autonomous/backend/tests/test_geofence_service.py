import pytest

from app.models.geo import GeoPolygon
from app.models.geofence import GeofenceCreate
from app.services import geofences as geofence_service

FIELD_RING = [
    (-85.10, 38.00),
    (-85.10, 38.10),
    (-84.90, 38.10),
    (-84.90, 38.00),
    (-85.10, 38.00),
]


def test_create_and_get_geofence(db):
    created = geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="inclusive", name="Main field", boundary=GeoPolygon(coordinates=[FIELD_RING])
        ),
    )

    fetched = geofence_service.get_geofence(db, created.id)

    assert fetched.name == "Main field"
    assert fetched.type == "inclusive"


def test_get_geofence_not_found_raises(db):
    with pytest.raises(geofence_service.GeofenceNotFound):
        geofence_service.get_geofence(db, "000000000000000000000000")


def test_list_geofences_returns_all(db):
    geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="inclusive", name="Main field", boundary=GeoPolygon(coordinates=[FIELD_RING])
        ),
    )
    geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="exclusive", name="Pond", boundary=GeoPolygon(coordinates=[FIELD_RING])
        ),
    )

    fences = geofence_service.list_geofences(db)

    assert {f.name for f in fences} == {"Main field", "Pond"}
