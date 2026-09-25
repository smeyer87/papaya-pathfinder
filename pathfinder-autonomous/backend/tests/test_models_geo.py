import pytest
from pydantic import ValidationError

from app.models.geo import GeoPoint, GeoPolygon


def test_geo_point_valid():
    point = GeoPoint(coordinates=(-85.654321, 38.123456))

    assert point.type == "Point"
    assert point.coordinates == (-85.654321, 38.123456)


def test_geo_point_rejects_out_of_range_longitude():
    with pytest.raises(ValidationError):
        GeoPoint(coordinates=(200.0, 38.123456))


def test_geo_point_rejects_out_of_range_latitude():
    with pytest.raises(ValidationError):
        GeoPoint(coordinates=(-85.654321, 95.0))


def test_geo_polygon_valid_closed_ring():
    ring = [(-85.0, 38.0), (-85.0, 38.1), (-84.9, 38.1), (-84.9, 38.0), (-85.0, 38.0)]

    polygon = GeoPolygon(coordinates=[ring])

    assert polygon.type == "Polygon"
    assert polygon.coordinates == [ring]


def test_geo_polygon_rejects_unclosed_ring():
    ring = [(-85.0, 38.0), (-85.0, 38.1), (-84.9, 38.1), (-84.9, 38.0)]

    with pytest.raises(ValidationError):
        GeoPolygon(coordinates=[ring])


def test_geo_polygon_rejects_too_few_points():
    ring = [(-85.0, 38.0), (-85.0, 38.1), (-85.0, 38.0)]

    with pytest.raises(ValidationError):
        GeoPolygon(coordinates=[ring])


def test_geo_polygon_rejects_out_of_range_longitude():
    ring = [(-85.0, 38.0), (200.0, 38.1), (-84.9, 38.1), (-84.9, 38.0), (-85.0, 38.0)]

    with pytest.raises(ValidationError) as exc_info:
        GeoPolygon(coordinates=[ring])

    assert "longitude" in str(exc_info.value)


def test_geo_polygon_rejects_out_of_range_latitude():
    ring = [(-85.0, 38.0), (-85.0, 95.0), (-84.9, 38.1), (-84.9, 38.0), (-85.0, 38.0)]

    with pytest.raises(ValidationError) as exc_info:
        GeoPolygon(coordinates=[ring])

    assert "latitude" in str(exc_info.value)


def test_geo_polygon_range_error_names_the_ring():
    outer = [(-85.0, 38.0), (-85.0, 38.1), (-84.9, 38.1), (-84.9, 38.0), (-85.0, 38.0)]
    hole = [(-85.0, 38.0), (-85.0, 38.05), (-999.0, 38.05), (-84.95, 38.0), (-85.0, 38.0)]

    with pytest.raises(ValidationError) as exc_info:
        GeoPolygon(coordinates=[outer, hole])

    message = str(exc_info.value)
    assert "ring 1" in message
    assert "-999" in message
