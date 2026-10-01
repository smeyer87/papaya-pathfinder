import math

from papaya_mission.hardware_sensor_hub import HardwareGpsSource, HardwareImuSource

# A real GGA sentence: fix quality 1, HDOP 1.2, lat 38 29.3754' N, lon 85 45.1234' W
_GGA_FIX = b"$GPGGA,123519,3829.3754,N,08545.1234,W,1,08,1.2,10.0,M,-34.2,M,,*6A\n"
_GGA_NO_FIX = b"$GPGGA,123519,,,,,0,00,99.9,,,,,,,*66\n"


def test_gps_returns_none_with_no_lines_available():
    source = HardwareGpsSource(line_source=_FakeLineSource([]), clock=lambda: 1.0)

    assert source.read() is None


def test_gps_parses_a_valid_gga_fix():
    source = HardwareGpsSource(line_source=_FakeLineSource([_GGA_FIX]), clock=lambda: 1.0)

    fix = source.read()

    assert fix is not None
    assert math.isclose(fix.lat, 38.0 + 29.3754 / 60.0, abs_tol=1e-6)
    assert math.isclose(fix.lon, -(85.0 + 45.1234 / 60.0), abs_tol=1e-6)
    assert math.isclose(fix.accuracy_m, 1.2 * 5.0, rel_tol=1e-6)
    assert fix.timestamp == 1.0


def test_gps_ignores_a_no_fix_sentence():
    source = HardwareGpsSource(line_source=_FakeLineSource([_GGA_NO_FIX]), clock=lambda: 1.0)

    assert source.read() is None


def test_gps_keeps_the_freshest_fix_when_multiple_lines_arrived():
    second_fix = b"$GPGGA,123520,3830.0000,N,08545.1234,W,1,08,1.0,10.0,M,-34.2,M,,*6B\n"
    source = HardwareGpsSource(line_source=_FakeLineSource([_GGA_FIX, second_fix]), clock=lambda: 2.0)

    fix = source.read()

    assert math.isclose(fix.lat, 38.0 + 30.0000 / 60.0, abs_tol=1e-6)


def test_gps_ignores_malformed_lines():
    source = HardwareGpsSource(line_source=_FakeLineSource([b"garbage\n", _GGA_FIX]), clock=lambda: 1.0)

    assert source.read() is not None


class _FakeLineSource:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeBno055Device:
    def __init__(self, euler=(None, None, None), linear_acceleration=(None, None, None)):
        self.euler = euler
        self.linear_acceleration = linear_acceleration


def test_imu_returns_default_reading_before_any_valid_read():
    source = HardwareImuSource(device=_FakeBno055Device(), clock=lambda: 1.0)

    reading = source.read()

    assert reading.heading_deg == 0.0
    assert reading.forward_acceleration_mps2 == 0.0


def test_imu_reads_heading_and_forward_acceleration():
    device = _FakeBno055Device(euler=(90.0, 1.0, 2.0), linear_acceleration=(0.1, 0.5, -9.8))
    source = HardwareImuSource(device=device, clock=lambda: 3.0)

    reading = source.read()

    assert reading.heading_deg == 90.0
    assert reading.forward_acceleration_mps2 == 0.5
    assert reading.timestamp == 3.0


def test_imu_returns_last_known_reading_when_device_reports_none():
    device = _FakeBno055Device(euler=(45.0, 0.0, 0.0), linear_acceleration=(0.0, 1.0, 0.0))
    source = HardwareImuSource(device=device, clock=lambda: 1.0)
    first = source.read()

    device.euler = (None, None, None)
    device.linear_acceleration = (None, None, None)
    second = source.read()

    assert second == first
