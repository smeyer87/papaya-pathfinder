"""GPS/IMU/ultrasonic/camera sensor interfaces Mission Runtime reads
from each tick -- these Protocols are the contract any driver
implements. `SimulatedSensorHub` here is the scripted-per-field test
double; `digital_twin.py` derives a coherent set of readings from one
shared simulated world instead; `hardware_sensor_hub.py` is the real
breadboard-bench implementation over injected hardware I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from papaya_mission.position_fusion import GpsFix, ImuReading


@dataclass(frozen=True)
class ObstacleDetection:
    relative_bearing_deg: float
    range_m: float


# Contract note shared by all four source Protocols below: a real driver
# SHOULD avoid raising from read() where possible -- return None (or, for
# the IMU, the last known reading) rather than propagating a transient
# bus error, since "no reading this tick" is a state every caller already
# handles. MissionRuntime also defensively catches exceptions around every
# one of these call sites as a second layer, so a driver that does raise
# degrades that tick rather than crashing the mission. That catch is a
# backstop, not a licence: a driver that raises routinely turns real
# detections into silent misses, and only the log will say so.


class GpsSource(Protocol):
    """See the contract note above: SHOULD return None rather than raise on
    a failed read; MissionRuntime catches regardless."""

    def read(self) -> GpsFix | None: ...


class ImuSource(Protocol):
    """See the contract note above. This one has no "no reading" return
    value -- a real IMU always has a current attitude -- so a driver that
    cannot read SHOULD return its last known reading. MissionRuntime skips
    the whole position step for the tick if this raises, because there is
    no safe substitute for a heading.
    """

    def read(self) -> ImuReading: ...


class UltrasonicSource(Protocol):
    """See the contract note above: SHOULD return None rather than raise on
    a failed read; MissionRuntime catches regardless."""

    def read(self) -> ObstacleDetection | None: ...


class CameraSource(Protocol):
    """See the contract note above: SHOULD return None rather than raise on
    a failed read; MissionRuntime catches regardless."""

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
