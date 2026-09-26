"""CLI entrypoint for the Mission Runtime. Wires MissionRuntime with
SimulatedSensorHub / a placeholder Esp32Link until real hardware
drivers exist (future hardware-integration pass -- see design notes'
Architecture & file structure)."""
from __future__ import annotations

import logging
import time

from papaya_mission.esp32_link import FakeEsp32Link
from papaya_mission.position_fusion import ImuReading
from papaya_mission.runtime import MissionRuntime
from papaya_mission.runtime_config import TICK_INTERVAL_S, load_runtime_settings
from papaya_mission.sensor_hub import SimulatedSensorHub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("papaya_mission.runtime")


def main() -> None:
    settings = load_runtime_settings()
    sensor_hub = SimulatedSensorHub(
        ImuReading(heading_deg=0.0, forward_acceleration_mps2=0.0, timestamp=time.monotonic())
    )
    esp32_link = FakeEsp32Link()

    runtime = MissionRuntime(
        rover_id=settings.rover_id,
        backend_base_url=settings.backend_base_url,
        local_db_path=settings.local_db_path,
        sensor_hub=sensor_hub,
        esp32_link=esp32_link,
    )
    runtime.startup()
    logger.info("Mission Runtime started for rover %s", settings.rover_id)

    while True:
        tick_started = time.monotonic()
        runtime.tick()
        tick_duration_s = time.monotonic() - tick_started
        if tick_duration_s > TICK_INTERVAL_S:
            logger.warning(
                "tick took %.3fs, over the %.3fs budget (TICK_HZ) -- see design notes' Scaling note",
                tick_duration_s, TICK_INTERVAL_S,
            )
        time.sleep(max(0.0, TICK_INTERVAL_S - tick_duration_s))


if __name__ == "__main__":
    main()
