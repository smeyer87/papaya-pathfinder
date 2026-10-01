"""Real SensorHub implementations for the breadboard bench rig -- see
design spec: docs/superpowers/specs/2026-09-30-breadboard-bench-rig-design.md.

Every hardware dependency (a serial-like line source, an I2C IMU device,
a GPIO pulse timer, a camera classifier) is injected via the
constructor and typed against a Protocol defined in this file, never a
real hardware library -- see each class's docstring. Constructing the
real hardware objects (pyserial, pigpio, adafruit-blinka/BNO055,
picamera2/IMX500) is bench-time work, not built here.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.sensor_hub import (
    CameraSource,
    GpsSource,
    ImuSource,
    ObstacleDetection,
    UltrasonicSource,
)

logger = logging.getLogger("papaya_mission.hardware_sensor_hub")


class GpsLineSource(Protocol):
    """Duck-typed shape of the GPS's serial link. readline() must return
    b"" (not block) when nothing new has arrived -- same convention as
    HardwareEsp32Link's transport.
    """

    def readline(self) -> bytes: ...


def _nmea_coord_to_decimal(value: str, hemisphere: str) -> float | None:
    if not value:
        return None
    dot = value.index(".")
    degrees = int(value[: dot - 2])
    minutes = float(value[dot - 2 :])
    decimal = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return decimal


def _parse_gga(line: str, timestamp: float) -> GpsFix | None:
    if "GGA" not in line:
        return None
    body = line.split("*")[0]
    fields = body.split(",")
    if len(fields) < 9:
        return None
    try:
        fix_quality = int(fields[6]) if fields[6] else 0
        if fix_quality == 0:
            return None
        lat = _nmea_coord_to_decimal(fields[2], fields[3])
        lon = _nmea_coord_to_decimal(fields[4], fields[5])
        hdop = float(fields[8]) if fields[8] else 99.0
    except (ValueError, IndexError):
        return None
    if lat is None or lon is None:
        return None
    # Rough accuracy estimate: HDOP * typical SBAS-corrected UERE (~5m).
    # Refine once real-world fix data is available from bench testing.
    accuracy_m = hdop * 5.0
    return GpsFix(lat=lat, lon=lon, accuracy_m=accuracy_m, timestamp=timestamp)


class HardwareGpsSource:
    """Reads NMEA GGA sentences from the injected line source and returns
    the freshest valid GPS fix available this tick."""

    def __init__(self, line_source: GpsLineSource, clock: Callable[[], float] = time.monotonic) -> None:
        self._line_source = line_source
        self._clock = clock

    def read(self) -> GpsFix | None:
        fix: GpsFix | None = None
        while True:
            try:
                raw = self._line_source.readline()
            except Exception:
                logger.warning("GPS line source raised while reading", exc_info=True)
                break
            if not raw:
                break
            try:
                line = raw.decode("ascii", errors="ignore").strip()
            except UnicodeDecodeError:
                continue
            parsed = _parse_gga(line, self._clock())
            if parsed is not None:
                fix = parsed
        return fix


class Bno055Device(Protocol):
    """Duck-typed shape of an Adafruit CircuitPython BNO055 device
    object. Both properties return (None, None, None) when a fresh
    reading isn't currently available (e.g. not yet calibrated).
    """

    @property
    def euler(self) -> tuple[float | None, float | None, float | None]: ...
    @property
    def linear_acceleration(self) -> tuple[float | None, float | None, float | None]: ...


class HardwareImuSource:
    """Axis choice for forward acceleration (the second/Y element of
    linear_acceleration) assumes a specific physical mounting
    orientation -- confirm once physically mounted and adjust the index
    if the sign/axis turns out wrong.
    """

    def __init__(self, device: Bno055Device, clock: Callable[[], float] = time.monotonic) -> None:
        self._device = device
        self._clock = clock
        self._last_reading = ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=0.0)

    def read(self) -> ImuReading:
        try:
            heading, _roll, _pitch = self._device.euler
            _ax, forward_accel, _az = self._device.linear_acceleration
        except Exception:
            logger.warning("IMU device raised while reading", exc_info=True)
            return self._last_reading
        if heading is None or forward_accel is None:
            return self._last_reading
        reading = ImuReading(
            heading_deg=heading % 360.0,
            forward_acceleration_mps2=forward_accel,
            timestamp=self._clock(),
        )
        self._last_reading = reading
        return reading


class PulseMeasurer(Protocol):
    """Triggers the ultrasonic sensor and returns the echo pulse width
    in microseconds, or None if no echo was received (nothing in
    range). The real implementation (a pigpio-timed TRIG/ECHO sequence
    through the voltage divider) is bench-time work.
    """

    def measure_echo_pulse_us(self) -> float | None: ...


class HardwareUltrasonicSource:
    """The bench rig has no mast-rotation servo wired (see
    docs/wiring/breadboard-wiring-layout.yaml) -- the sensor is simply
    forward-facing, so relative_bearing_deg is always 0.0 here.
    """

    def __init__(self, pulse_measurer: PulseMeasurer) -> None:
        self._pulse_measurer = pulse_measurer

    def read(self) -> ObstacleDetection | None:
        try:
            pulse_us = self._pulse_measurer.measure_echo_pulse_us()
        except Exception:
            logger.warning("Ultrasonic pulse measurer raised while reading", exc_info=True)
            return None
        if pulse_us is None:
            return None
        range_m = (pulse_us / 58.0) / 100.0
        return ObstacleDetection(relative_bearing_deg=0.0, range_m=range_m)


class ClassifierSource(Protocol):
    """Returns the current camera classification, or None if nothing is
    classified this read. The real Pi AI Camera / picamera2 / IMX500
    backend is bench-time work -- its API is fast-moving and best
    confirmed against the actual camera and current docs, not guessed
    at here. Any real implementation that satisfies this shape drops in
    without changing HardwareCameraSource.
    """

    def classify(self) -> tuple[str, float] | None: ...


class HardwareCameraSource:
    """Delegates to the injected classifier source and returns its current
    classification, if any."""

    def __init__(self, classifier_source: ClassifierSource) -> None:
        self._classifier_source = classifier_source

    def read(self) -> tuple[str, float] | None:
        try:
            return self._classifier_source.classify()
        except Exception:
            logger.warning("Camera classifier source raised while reading", exc_info=True)
            return None


class HardwareSensorHub:
    """Plain bundling container for the four hardware sources -- no logic
    of its own, just satisfies the SensorHub Protocol's attribute shape."""

    def __init__(self, gps: GpsSource, imu: ImuSource, ultrasonic: UltrasonicSource, camera: CameraSource) -> None:
        self.gps = gps
        self.imu = imu
        self.ultrasonic = ultrasonic
        self.camera = camera
