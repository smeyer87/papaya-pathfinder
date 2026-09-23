# 00 — Inbox

Anything that doesn't obviously belong in another file. No formatting
required — bullets, fragments, links, questions. This gets triaged into
the numbered files during the planning session.

---
## Mission Package Summary
I see the following mission packages as our core for the next version.  Each can be built iteratively as their capabilities overlap but largely build from number 1 through number 4.
1. Map and Detect / Explore 
    - Operating within a Geofence, explore and map the area, identifying potential obstacles and creating a reusable virtual map that can be stored to a persistent file system (e.g. when in WiFi range, a cloud storage or DB facility such as a MongoDB instance running on Azure).
    - Classify obstacles as either permanent (likely to persist over multiple runs, e.g. a barrel, utility pole, fence post, etc.) or temporary (likely to change over time, like chairs, vehicles, etc.)
2. Track Chickens / Cats
    - Operating within a defined map, identify the presence and position of chickens and cats
    - Tag the location of the animals using the best available coordinate system (e.g. current Lat/Long position + bearing and range using ultrasonic or Lidar sensor distance)
    - Tag using the onboard timestamp and record the position record for upload when in high bandwidth mode
    - Identify individual / unique instances of the animals using the onboard camera. Using the classification model identify specific chickens by their feather coloring and tag using a Master ID.  When unsure, tag but also save sufficient detail to allow offline classification later.
3. Fetch and Retrieve
    - Take an input from a remote user to obtain a specific item like a beverage, a tool, or other small item that is transportable using the rover.  No heavy implements will be required.
    - Proceed to a known point to load the requested item.  
    - Another human user will provide the item and update a status button using a small onboard LCD or interacting through a shared web interface.
    - The rover then navigates to the delivery point, which must be allowed using the defined map (i.e. not inside a geofenced exclusion zone).
    - The rover signals to the requesting / remote user when it arrives and updates status if possible (if communication is available using onboard sensors).
4. Sentry Mode
    - Operating at night, conduct periodic sweeps around a defined chicken coop boundary
    - Identify any varmint or predator presence (e.g. raccoon, possum, coyote) and make noise or flash lights to ward off the predator.
    - Tag and alert the interaction.
    - This mode should be with very low power to allow operation through a complete night.
    - A separate sensor package could be applied to reduce power drain during the sweeps and maximize on-station time
The above mission packages should also be constructed modularly, and in an additive way.  For example if running the Fetch and Retrieve package, any new obstacles or map inputs discovered along the delivery route should be appended to the master map for future reference.  

## Capability Summary
These capabilities are my initial list defined offline.  They are not sorted in priority or sequential order.
1. Management UI 
    - We will require some form of management UI to pass information between the master controller system and the rover
    - Consider a cloud-hosted UI or a local computer a host running via a container architecture.
    - UI requirements will evolve
2. Geofence Management
    - Establish the concept of a Geofence for managing boundaries where the rover can and cannot operate
    - Assume the rover has GPS capability, though this could be a mission package specific if too power intensive.  In other words one thought is to use the GPS during the Mapping mission, but convert to an (x,y) coordinate system that the rover can maintain onboard using defined fixed waypoints and bearing/distance measurements (e.g. from fixed corners of buildings, trees unlikely to be removed, permanent fence posts, etc.)
    - Geofences should be defined using the management UI by drawing boundaries on a Google Maps overlay.
    - Geofences are defined as 'inclusive' meaning the rover should stay inside that boundary, or 'exclusive' meaning the rover should not proceed inside that boundary.  
    - Geofences will be layered, e.g. within a master Inclusive fence for the overall operating boundary, there will be multiple exclusive boundaries defining dangerous areas or areas where the rover should not operate.
    - If the rover finds itself accidentally within an Exclusive zone it should stop and send an alert.  This could be configurable, meaning if it is less than one rover length inside and can easily reverse then this might be okay, but if more than one rover length inside then it should stop and wait for help.
    - Possible alternative to external map-defined inputs - allow a manual capture mode for a geofence boundary by having a human operator manually drive (using the ELRS controller) the rover along the desired fence boundary.  Capture the positions and then upload the fence boundary on command.
3. Map Development and Storage
    - Support the storage of maps onboard in a format most efficient for the rover usage. 
    - Allow map segmentation perhaps to make good use of the rover onboard memory.  For example there might be several large operating sectors each with a detailed map.  If the rover is only in one sector then that is the only map needed in active memory.  As it approaches a boundary from Sector A to Sector B then it would load the Sector B map.
    - Allow map updates with ongoing operations, but permanent changes to maps should require a human review to ensure maps are not erroneously updated based on a temporary condition or a sensor error
4. Telemetry Reporting
    - This is a core requirement
    - The rover must be able to report telemetry to a remote server which could be on-premise (e.g. container hosted app endpoint) or to a cloud endpoint. 
    - Telemetry requirements will need further definition, but should be expected to include at least the following:
        - Rover ID - there is the possibility of multiple rovers operating in the same environment simultaneously
        - Time - record all times in UTC but with a local timezone for easy conversion to local time (UI reports would always be displayed in local time)
        - Rover position - as GPS coordinates (to 5 or 6 decimals?) or as (x,y) positions, or both.  Altitude (z coordinate) is less important but could be captured and stored if easily available from the GPS.  Not required.
        - Onboard statistics and metrics such as:
            - Power levels (on all power supplies if multiple batteries)
            - Current draw at all measurement points (could be down to the individual motor / servo level, sensors, etc.)
            - Internal temperatures within the payload bay
            - External temperature (e.g. environmental temp)
            - External light level
            - External humidity or other environmental measures depending on which sensors we add
            - GPS fix/status - position (Lat/Long/Alt) with associated accuracy metrics (e.g. HDOP/VDOP), number of satellites, etc.
            - Motor speeds and positions (wheel speeds and steering angle, etc.)
            - Sensor status and error flags for all sensors
            - Internal processor load and memory usage
            - Communication status - WiFi signal strength, cellular signal strength (if applicable), range of ELRS signal (estimated from signal strength), LoRa signal status (if applicable)
            - Navigation status - current navigation mode (e.g. Manual/Cruise/Explore/Fetch/Sentry/etc.), distance to next waypoint (if on a path), distance to exclusion zone boundary (if inside one), distance to target (if fetching/returning), etc.
        - Mission status - current mission, mission phase, mission phase progress/percentage, etc.
        - Error and event logs - significant events such as errors, warnings, alerts, user commands, etc.
5. Communication Systems - Rover to Host
    - Need a robust communication system to allow the rover to report telemetry and receive commands.
    - Consider several options:
        - WiFi - allows high bandwidth, but range is limited.  Could be used for local/on-premise hosting.
        - Cellular - allows high bandwidth and long range, but can be expensive and requires a SIM card.  Cellular is unlikely unless we consider self-hosting an older 1G / 2G local cell network and an older device model.  That decision would not be for the simple Version 2 scope.  
        DECISION - consider Cellular comms out of scope for Version 2.
        - LoRaWAN or similar long-range, low-power protocols for basic telemetry.
        - A hybrid approach might be best: LoRaWAN for basic telemetry and low-bandwidth commands, WiFi or cellular for higher-bandwidth data like images or maps.
6. Power Systems
    - Need to define power budget for the rover.
    - May require multiple power sources and power distribution system.
    - Consider a modular approach where power components can be added or removed as needed.
    - Need to consider redundancy and fail-safes.
    - Consider optimal ways to manage the power for recharging (ease of battery access or removal for charging, battery replacement, etc.).  This will impact the physical design as well as onboard electrical connections.
7. Remote Operation
    - Allow remote operation of the rover.
    - Will require a UI for remote operation.
    - Should support both direct control (e.g. manual control via ELRS) and indirect control (e.g. mission commands).
    - Will need to define the hierarchy of control - master controller system, remote users, etc.
    - Consider the rover to primarily operate in remote / autonomous mode but accepting mission commands as needed.
    - Manual control using an ELRS controller would be for backup or recovery use, or specifically when used to drive the rover along Exclusion Geofence boundaries, etc.
8. Basic Object Classification
    - Support object image detection and classification using an onboard processing model
    - Basic classification will include humans, chickens, and cats, along with predator animals defined.  Note that predator mapping would only be needed for specific mission packages (normally only at night)
    - Other object classification would be for farm objects like vehicles (mowers, tractors, pickup trucks), stationary objects like barrels, fence posts, etc.
    - There are no complex farm machines like combines, harvesters, etc. only small mowers and tractors.
9. Object Avoidance
    - While in motion the system should be capable of detecting obstacles by ultrasonic or Lidar or camera and plotting an avoidance route.  
    - Avoidance can be dynamic meaning a potentially moveable object like a cat or chicken may not require the same avoidance method as a barrel, hose, pipe, etc.
10. Route Planning
    - Especially for the 'Fetch and Retrieve' mission, the rover should be able to review its load point to delivery point position and determine a simple route to the destination point, staying within geofences and avoiding exclusion areas.
    - Route planning is simple and should not need extensive design, there are not roads or other high-risk elements or street-level type routing.  For Version 2 we can assume relatively open fields and gentle slopes.
11. 'Go Home' concept
    - If the rover ends up unsure of its current state, it should have a recovery mode to proceed to a "home" point and await further instruction.
    - It is possible to define multiple Home points, which largely should be a sheltered point identified so that the human operators can easily find the rover
    - A Go Home command could also be issued on a low-power situation.  See the specific capability defined for power management
12. 'Send Help' concept
    - If the rover becomes immovable or stuck between obstacles and is unable to navigate, it issues a 'Send Help' message to the remote operator.
    - This message should include the rover's current state and location, and any other relevant information
    - The 'Send Help' message should be sent with the highest priority possible and with the greatest range possible
## Sensor Updates
Based on my initial review, the following sensor updates are likely in the new design. This is not a prescriptive list, we can evaluate and refine as we proceed through design.
1. Core platform Architecture
    - Do we stay with ESP32 based architecture given its low power and ease of integration with digital to analog components?  
    - Do we shift to a Raspberry Pi based architecture to integrate better with the AI-cameras and other more advanced capabilities required?
    - Do we use a hybrid approach - use the Raspberry Pi as a master controller with delegation to ESP32 for sensor collection and management?
    - If selecting a Pi-based architecture, which Pi platform should we use?
        - A full-sized Pi like a Raspberry Pi 5?  This would allow more integraton with NVMe drives, AI sensors, etc. but also significantly increases power and space requirements.
        - A Raspberry Pi Zero 2W?  This is a known lower power model but also less capable for more advanced processing.
        - A Raspberry Pi Pico 2W also is an option, but largely would replicate the functionaly capability of the ESP32 platform boards.  This likely would only suffice if we want to go to a 'multi device' (e.g. hyrid of one control system for drive train and onboard data capture, with the more intelligent platform for AI cameras and mission logic etc).  
2. Power Management
    - Need more integration with the onboard battery. LiPo batteries offer a cell level dongle connection to track voltages at each cell level.  This is used for low-voltage alarms which can damage the battery.
    - Rather than use the separate manual dongle that I have today, can we build a connector and capture the data through this connection to track battery voltages at the cell level and integrate with the telemetry package
    - What other power measurement points should we identify for useful places to track voltage and current to ensure adequate monitoring and controls
    - Power measurement points may also not be required at all times. We might capture quickly on startup as a validation check, but then capture less frequently to minimize the volume of the telemetry data packet.  But also allow configuration driven changes to allow toggle on/off of detailed data collection and change of sampling rates, etc. based on mission needs or preferences.
    - Note that if we move to a multi-battery option, then power management needs to include all power sources
3. Detection Sensors
    What onboard detection sensors are required for autonomous operation?
    - Ultrasonic 
        - Seems like an obvious yes.  Low power, low capability, but very easy to integrate for basic 'bearing and range' metrics based on an assumption of a rotating mast.
    - Lidar
        - Requires more power but could be useful for the mapping mission
        - What capability could it provide for a more normal use case, but perhaps in a lower frequency rate to limit the power draw?
    - AI Camera
        - Some form of camera will be required in all cases
        - The Raspberry Pi AI camera is very capable and can take object classification all the way to the camera edge.  This is a high priority capability and unless there are highly capable ESP32 compatible variants this is a key draw driving to a Raspberry Pi / Hybrid controller design.
    - Touch / Bump Sensors
        - Should perhaps have a minimal set of bump sensors at the corners of the rover to to capture where an undetected object makes contact with the rover.  Since the ultrasonic, Lidar, etc. will be at some height above ground, there is a possibility that a low-lying obstacle might not be detected.
        - We would want the bump sensor to provide immediate feedback that the rover should stop forward motion 
        - Ideally with the 'object avoidance' capability, the rover should interrupt the current path and back up or move in a way to avoid the bump-sensor detected object.
4. IMU (Inertial Measurement Unit)
    - The accelerometer and gyroscope can be useful for orientation but may not be required across the board.
    - I consider this optional but desired if it does not overly complicate the architecture or power demands.
5. GPS 
    - Almost certainly mandatory
    - I understand GPS very well but have not used it in a local / portable architecture like this project.
    - Accuracy will be important, ideally to the decimeter level to ensure accurate position and object avoidance
    - GPS Update frequency can be controlled based on the rover speed, i.e. the rover will operate at fairly low speed, so GPS update frequency can be fairly moderate (several times per minute is likely sufficient)
6. Antennas
    - All of the above radio sensors will involve different antennas
    - Do we consolidate multiple individual antennas to a common Antenna mast deployed with the overall rover mast
    - Can we integrate the ELRS, LoRa, WAN, GPS, etc. antennas to a common antenna structure or do we need a 'nest' of them
7. Communications
    - Out of sequence with (6)
    - What communication protocols do we need
        - WiFi - assumed from either the core ESP32 or Raspberry Pi platform itself
        - Used if in range, but we know there are large areas within the farm where Wifi is not available
        - LoRa - for telemetry and core message processing, but not suitable for large scale data transfer
        - Cellular - out of scope for this version unless we determine it is absolutely required.  Do not desire setting up a separate SIM card and plan for the robots
            - See previous discussion of Cellular and a non-version 2 capability to set up a private 1G or 2G cell network 
    - Multimode capability is nice as well
        - Zigbee mesh - allow Rovers to pass messages to each other to extend range and relay messages
8. Charging
    - Links with power management
    - Depending on the types of batteries and the mission, can onboard solar panels provide some/all of the power requirements for the rover?  
        - Agree this likely is insufficient for core motor and servo drivers
        - Can it sustain part of the control electronics and radio communications?
        - Consider this 'nice to have' but not essential, and may add significant bulk and weight to the overall platform.  But would enable much greater autonomy
    - In any event we do want the onboard power connections to have easily accessible charging points.  Ideally it would be nice to charge without having to physically remove the batteries
    - Any external power connection would need to be covered to avoid risk of shorts due to environmental conditions

## Physical Platform Updates
1. Drive train - would like to leverage and reuse the existing drive train
    - The existing 6 wheeled rover style works very well for the type of terrain likely to be encountered
    - Open to considering a shift to a tracked-vehicle architecture if required, but believe this adds complexity without value for our missions
2. Mast
    - Some type of rotating mast will be required for the cameras, ultrasonic, etc.
    - The mast can double as an antenna mast if appropriate, though separate antenna points may be deployed as well if most efficient
3. Waterproofing & Dustproofing
    - We expect the rover to operate only in reasonably fair weather conditions
    - Rover will not operate in heavy rain or precipitation
    - Some ground water like dew, etc. is possible.  Especially the wheel drive motors need some protection from the current design which has them located exposed and nearly at ground level.
    - While a full waterproof enclosure is not required, we should aim for a high degree of dustproofing and weather resistance in the final design
    - Where possible use sliding panels or thumb-screw capable fasteners to simplify access.  Permanent mounting via standard screws is acceptable for internal component mounts that will not need frequent access.
    - As the current platform bay is entirely open, enclosing it may create internal heat conditions that are not a problem today.  If we enclose the payload bay we need to consider adding fans and some type of vent ports to enable cooling airflow through the bay.
4. Wiring enclosures
    - The current design doesn't enclose any wires.  Wire runs to the servos, to the wheel motors, between the power distribution terminals, etc. is all exposed.
    - Ideally we will minimize the amount of exposed wires so that the rover has little risk of grounding out exposed electrical connections or the risk of snagging an exposed wire on a branch or weed that the rover may pass near.
    - Wiring runs should be logical and clearly mark all wires
    - The current design of the wheel assemblies should ideally be enhanced to route the motor wires interior to the wheel and axle frame.  This will require some experimentation in the 3D printing design to add these wire channels.
    - Similarly for the servos, today the servos are completely exposed and will need some form of 'cap' and wire route to minimize exposure to the environment and risk of snagging wires on vegetation.
5. Larger electronics payload bay
    - The current payload bay is absolutely not sufficient for Version 2
    - Can I easily just 'make it bigger' or what does this do to the overall physical stability and viability of the rover if I make the central box significantly larger in all three dimensions (wider, longer, taller) to internalize all of the existing components where I had to mount externally.
    - As noted above, incorporate sliding panel covers and possibly thumb-screw type fasteners to help ensure a minimal level of protection
6. External payload area on the rover
    - Specific to the 'Fetch and Retrieve' mission
    - The rover should be capable of transporting simple implements such as a beverage (soda can, 20 oz soda bottle, or some type of water container).  Weight will be important and need to be understood for stability and battery requirements
    - Other possible 'Fetch' items might be a tool, gloves, phone, firearm, etc. but would be weight and space limited.
    - I do not anticipate any type of towed trailer or heavier payload for the rover in this release.
    - I would recommend the external payload have a 'standard cupholder' shaped option, perhaps as an insert if that is the desired item.  But this can be removed to add more space for a larger item if needed.
## Key Assumptions
1. We will begin with the mission packages 1, 2, and 3 first with an assumption of Daytime operation only.
2. Mission package 4 (Sentry mode) Will require nighttime operation
    - Would any additional sensor packages (e.g. IR camera or IR sensors) be necessary for this to work?
3. Fair-weather operation is assumed, but the rover should be protected against a short-term weather event like a surprise rain, etc.
    - Identified 'shelter' points might be defined in the map data
4. We will need to decide on a Coordinate system
    - Do we stay with a full Lat/Long based system across all maps, communications, etc.
    - Do we use GPS primarily for an initial mapping, but convert to a local (x,y) coordinate system to 'keep things simple' (possibly integer vs. decimal based processing). Or does (x,y) make things more complex and not add value
    - Suggest we allow an overlay of (x,y) on top of GPS as this may be useful for defining more fixed obstacle type areas
    - I am a fan of the 'What3Words' system for overlaying location identifiers on top of GPS positions.  If What3Words is easily available without expensive licenses, it could be useful for the 'Fetch and Retrieve' mission which could require delivery to points not always defined in the master map.
5. Ensure that battery access is simple to allow for easy battery changeouts without a major effort
    - This can still support sliding panels or other easily removable panels
6. Long-term, the concept of a 'base' or 'home' station where the rover can be charged and where its mapping data can be offloaded is a nice to have but not required for V1.
7. The rover should have an onboard algorithm to compare 'distance from home' with 'remaining battery level' to know if it is getting to a distance which is too far from home and won't have enough power to return to a charging point.
    - The Naval Aviation concept of a 'Bingo Fuel' level is a desired concept
    - The rover would track its current voltage and consumption pattern against the 'bingo' reserve level
    - At "Bingo" the rover would cease the current mission and begin navigating at the optimal speed to reach the charging point.
    - If a Bingo event is triggered, this should be communicated through the telemetry package with high priority to notify the humans of the event and that the rover is coming home for a charge.
    - Part of mission package 1.3 (Fetch and Retrieve) should include a basic calculation of 'DO I have sufficient power reserves to complete this mission?' based on the expected range and consumption for the mission plan.  (Attempting to incorporate the power drain for the weight of the object being transported is not required in the initial release, but we should allow some factor for this in the calculation - i.e. expected current draw under a 'typical' or 'assumed' weight of the object being transported)
    - NOTE that I assume this requirement will involve some preliminary data capture throughout the early mission 1.1 for the mapping development.  Through the telemetry capture, we should be able to later develop the consumption models that will enable the rover to make these 'Bingo' determinations in the field.  (This may not be "realtime" in the purest sense if we are still developing the models, but the capability should be there).  
    - Note also that battery consumption may be non-linear.  We won't consider temperature variations as much, but more that a power draw of a certain amps to drive the motors and servos may have a more dramatic impact on the battery voltage when it is underpowered than when at full charge.  This should be incorporated into the initial model development, based on data we collect with the real platform.
