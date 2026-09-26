"""GPS/IMU/ultrasonic/camera sensor interfaces Mission Runtime reads
from each tick. Real hardware drivers are deferred to a future
hardware-integration pass, same as every other Pi-mission plan treats
sensor acquisition -- these Protocols are the contract a real driver
will eventually implement; SimulatedSensorHub is the test double used
until then.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from papaya_mission.position_fusion import GpsFix, ImuReading


@dataclass(frozen=True)
class ObstacleDetection:
    relative_bearing_deg: float
    range_m: float


class GpsSource(Protocol):
    def read(self) -> GpsFix | None: ...


class ImuSource(Protocol):
    def read(self) -> ImuReading: ...


class UltrasonicSource(Protocol):
    def read(self) -> ObstacleDetection | None: ...


class CameraSource(Protocol):
    def read(self) -> tuple[str, float] | None: ...


class SensorHub(Protocol):
    gps: GpsSource
    imu: ImuSource
    ultrasonic: UltrasonicSource
    camera: CameraSource


class SimulatedSensorHub:
    """In-memory fake for tests. Each scripted value is consumed exactly
    once by the next matching .read() call, except the IMU which always
    has a "current" reading (a real IMU has no concept of "no reading
    yet" the way GPS/ultrasonic/camera do).
    """

    def __init__(self, initial_imu: ImuReading) -> None:
        self._next_gps_fix: GpsFix | None = None
        self._current_imu_reading = initial_imu
        self._next_ultrasonic: ObstacleDetection | None = None
        self._next_camera: tuple[str, float] | None = None
        self.gps: GpsSource = _SimGpsSource(self)
        self.imu: ImuSource = _SimImuSource(self)
        self.ultrasonic: UltrasonicSource = _SimUltrasonicSource(self)
        self.camera: CameraSource = _SimCameraSource(self)

    def script_gps_fix(self, fix: GpsFix | None) -> None:
        self._next_gps_fix = fix

    def script_imu_reading(self, reading: ImuReading) -> None:
        self._current_imu_reading = reading

    def script_ultrasonic(self, detection: ObstacleDetection | None) -> None:
        self._next_ultrasonic = detection

    def script_camera(self, classification: tuple[str, float] | None) -> None:
        self._next_camera = classification


class _SimGpsSource:
    def __init__(self, hub: SimulatedSensorHub) -> None:
        self._hub = hub

    def read(self) -> GpsFix | None:
        fix, self._hub._next_gps_fix = self._hub._next_gps_fix, None
        return fix


class _SimImuSource:
    def __init__(self, hub: SimulatedSensorHub) -> None:
        self._hub = hub

    def read(self) -> ImuReading:
        return self._hub._current_imu_reading


class _SimUltrasonicSource:
    def __init__(self, hub: SimulatedSensorHub) -> None:
        self._hub = hub

    def read(self) -> ObstacleDetection | None:
        detection, self._hub._next_ultrasonic = self._hub._next_ultrasonic, None
        return detection


class _SimCameraSource:
    def __init__(self, hub: SimulatedSensorHub) -> None:
        self._hub = hub

    def read(self) -> tuple[str, float] | None:
        result, self._hub._next_camera = self._hub._next_camera, None
        return result
