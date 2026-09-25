from app.models.geo import GeoPolygon
from app.models.geofence import GeofenceCreate
from app.services import geofences as geofence_service

POND_RING = [
    (-85.05, 38.04),
    (-85.05, 38.06),
    (-85.03, 38.06),
    (-85.03, 38.04),
    (-85.05, 38.04),
]


def test_point_inside_exclusive_zone_is_found(db):
    geofence_service.create_geofence(
        db,
        GeofenceCreate(type="exclusive", name="Pond", boundary=GeoPolygon(coordinates=[POND_RING])),
    )

    hit = geofence_service.point_in_any_exclusive_zone(db, lon=-85.04, lat=38.05)

    assert hit is not None
    assert hit.name == "Pond"


def test_point_outside_exclusive_zone_is_not_found(db):
    geofence_service.create_geofence(
        db,
        GeofenceCreate(type="exclusive", name="Pond", boundary=GeoPolygon(coordinates=[POND_RING])),
    )

    hit = geofence_service.point_in_any_exclusive_zone(db, lon=-84.50, lat=38.50)

    assert hit is None


def test_point_inside_inclusive_zone_is_ignored(db):
    # point_in_any_exclusive_zone only matches type="exclusive" fences
    geofence_service.create_geofence(
        db,
        GeofenceCreate(
            type="inclusive", name="Main field", boundary=GeoPolygon(coordinates=[POND_RING])
        ),
    )

    hit = geofence_service.point_in_any_exclusive_zone(db, lon=-85.04, lat=38.05)

    assert hit is None
