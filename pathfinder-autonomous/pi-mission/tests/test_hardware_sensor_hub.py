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


def test_gps_returns_none_when_line_source_raises():
    source = HardwareGpsSource(line_source=_FakeLineSource([], raises=True), clock=lambda: 1.0)

    assert source.read() is None


class _FakeLineSource:
    def __init__(self, lines: list[bytes], raises: bool = False):
        self._lines = list(lines)
        self.raises = raises

    def readline(self) -> bytes:
        if self.raises:
            raise OSError("serial read error")
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeBno055Device:
    def __init__(self, euler=(None, None, None), linear_acceleration=(None, None, None), raises: bool = False):
        self._euler = euler
        self._linear_acceleration = linear_acceleration
        self.raises = raises

    @property
    def euler(self):
        if self.raises:
            raise OSError("I2C bus error reading euler")
        return self._euler

    @euler.setter
    def euler(self, value):
        self._euler = value

    @property
    def linear_acceleration(self):
        if self.raises:
            raise OSError("I2C bus error reading linear_acceleration")
        return self._linear_acceleration

    @linear_acceleration.setter
    def linear_acceleration(self, value):
        self._linear_acceleration = value


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


def test_imu_returns_last_known_reading_when_device_raises():
    device = _FakeBno055Device(euler=(45.0, 0.0, 0.0), linear_acceleration=(0.0, 1.0, 0.0))
    source = HardwareImuSource(device=device, clock=lambda: 1.0)
    first = source.read()

    device.raises = True
    second = source.read()

    assert second == first


from papaya_mission.hardware_sensor_hub import (
    HardwareCameraSource,
    HardwareSensorHub,
    HardwareUltrasonicSource,
)


class _FakePulseMeasurer:
    def __init__(self, pulse_us: float | None, raises: bool = False) -> None:
        self._pulse_us = pulse_us
        self.raises = raises

    def measure_echo_pulse_us(self) -> float | None:
        if self.raises:
            raise OSError("GPIO timing error")
        return self._pulse_us


def test_ultrasonic_returns_none_when_no_echo():
    source = HardwareUltrasonicSource(pulse_measurer=_FakePulseMeasurer(None))

    assert source.read() is None


def test_ultrasonic_returns_none_when_pulse_measurer_raises():
    source = HardwareUltrasonicSource(pulse_measurer=_FakePulseMeasurer(None, raises=True))

    assert source.read() is None


def test_ultrasonic_converts_pulse_width_to_range_with_zero_bearing():
    # Standard HC-SR04 formula: distance_cm = pulse_width_us / 58.0.
    # 580us / 58.0 = 10cm = 0.1m.
    source = HardwareUltrasonicSource(pulse_measurer=_FakePulseMeasurer(580.0))

    detection = source.read()

    assert detection is not None
    assert detection.relative_bearing_deg == 0.0
    assert detection.range_m == 0.1


class _FakeClassifierSource:
    def __init__(self, result: tuple[str, float] | None, raises: bool = False) -> None:
        self._result = result
        self.raises = raises

    def classify(self) -> tuple[str, float] | None:
        if self.raises:
            raise OSError("camera classifier error")
        return self._result


def test_camera_returns_none_when_nothing_classified():
    source = HardwareCameraSource(classifier_source=_FakeClassifierSource(None))

    assert source.read() is None


def test_camera_returns_none_when_classifier_raises():
    source = HardwareCameraSource(classifier_source=_FakeClassifierSource(None, raises=True))

    assert source.read() is None


def test_camera_passes_through_a_classification():
    source = HardwareCameraSource(classifier_source=_FakeClassifierSource(("barrel", 0.9)))

    assert source.read() == ("barrel", 0.9)


def test_hardware_sensor_hub_bundles_all_four_sources():
    gps = HardwareGpsSource(line_source=_FakeLineSource([]), clock=lambda: 1.0)
    imu = HardwareImuSource(device=_FakeBno055Device(), clock=lambda: 1.0)
    ultrasonic = HardwareUltrasonicSource(pulse_measurer=_FakePulseMeasurer(None))
    camera = HardwareCameraSource(classifier_source=_FakeClassifierSource(None))

    hub = HardwareSensorHub(gps=gps, imu=imu, ultrasonic=ultrasonic, camera=camera)

    assert hub.gps is gps
    assert hub.imu is imu
    assert hub.ultrasonic is ultrasonic
    assert hub.camera is camera
