from papaya_mission.position_fusion import GpsFix, ImuReading
from papaya_mission.sensor_hub import ObstacleDetection, SimulatedSensorHub

INITIAL_IMU = ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=0.0)


def test_gps_source_returns_none_until_scripted():
    hub = SimulatedSensorHub(INITIAL_IMU)

    assert hub.gps.read() is None


def test_gps_source_returns_scripted_fix_once():
    hub = SimulatedSensorHub(INITIAL_IMU)
    fix = GpsFix(lat=38.0, lon=-85.0, accuracy_m=2.0, timestamp=1.0)
    hub.script_gps_fix(fix)

    assert hub.gps.read() == fix
    assert hub.gps.read() is None


def test_imu_source_returns_latest_scripted_reading_every_time():
    hub = SimulatedSensorHub(INITIAL_IMU)
    reading = ImuReading(heading_deg=90.0, forward_acceleration_mps2=1.0, timestamp=1.0)
    hub.script_imu_reading(reading)

    assert hub.imu.read() == reading
    assert hub.imu.read() == reading  # IMU always has a "current" reading, unlike GPS


def test_ultrasonic_and_camera_sources_consume_once():
    hub = SimulatedSensorHub(INITIAL_IMU)
    detection = ObstacleDetection(relative_bearing_deg=15.0, range_m=2.5)
    hub.script_ultrasonic(detection)
    hub.script_camera(("barrel", 0.9))

    assert hub.ultrasonic.read() == detection
    assert hub.ultrasonic.read() is None
    assert hub.camera.read() == ("barrel", 0.9)
    assert hub.camera.read() is None
