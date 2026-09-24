# 01 — Mission Packages

What the Phase 2 rover should *do*. Describe outcomes and scenarios, not
hardware — "map a room and return to start", not "add a LIDAR".

## Vision

Four core mission packages, built iteratively, each largely building on
the last (1 → 4). Missions should be modular and additive: any obstacle
or map data discovered while running one mission (e.g. new obstacles
found along a Fetch and Retrieve route) should be appended to the shared
master map for every other mission to benefit from.

## Operating environment

<!-- This drives nearly every downstream choice. -->

- **Indoor / outdoor / both:** Outdoor (farm property — geofenced
  fields, chicken coop).
- **Terrain** (floors, carpet, grass, gravel, slopes, obstacles, stairs?):
  Relatively open fields with gentle slopes; no road-network/street-level
  routing needed (per CAP-10 Route Planning notes).
- **Lighting** (daylight, dark, both): Both — MP-1/2/3 assume daytime
  only initially (see D-2); MP-4 (Sentry) requires nighttime operation.
- **Weather exposure** (dry only, dust, light rain): Fair-weather
  operation assumed; should tolerate a short-term surprise weather event
  (e.g. brief rain) without damage (see A-1).
- **Operating range from operator:** Not specified — TBD.
- **Typical mission duration / runtime needed:** Not specified for
  MP-1/2/3. MP-4 must run a full night sweep cycle at very low power.
- **People / pets / fragile things nearby?** Yes — chickens and cats
  (MP-2), humans during Fetch/Retrieve handoffs (MP-3), farm vehicles
  (mowers, tractors, pickup trucks) and predator animals at night (MP-4).

## Learning goals

Things you want to build or learn for their own sake, even if a mission
doesn't strictly need them. Downstream items can trace to these.

- **MP-L1:**

## Mission packages

<!-- Copy this block per mission. -->

### MP-1: Map and Detect / Explore

- **Priority:** Must
- **Scenario:** Operating within a geofence, explore and map the area,
  identifying potential obstacles and building a reusable virtual map
  stored to a persistent file system (e.g. synced to cloud storage/a DB
  such as MongoDB on Azure when in WiFi range).
- **Autonomy level:** TBD
- **Success looks like:** A reusable virtual map is persisted; obstacles
  are classified as permanent (likely to persist across runs — barrel,
  utility pole, fence post) or temporary (likely to change — chairs,
  vehicles); map syncs to cloud/DB when WiFi is available.
- **Failure / safety behavior:** Not specified.
- **Notes:** Foundational mission — other missions append newly
  discovered obstacles/map data back into this master map (see Vision).
  Supports CAP-3 (Map Development and Storage), CAP-9 (Object Avoidance).

### MP-2: Track Chickens / Cats

- **Priority:** Must
- **Scenario:** Operating within a defined (mapped) map, identify the
  presence and position of chickens and cats. Tag each animal's location
  using the best available coordinate system (current lat/long + bearing
  and range from an ultrasonic or LiDAR sensor). Tag with the onboard
  timestamp and queue the position record for upload once in high-
  bandwidth mode. Identify individual animals via the onboard camera and
  classification model — for chickens, by feather coloring — assigning a
  Master ID. When uncertain, tag anyway and retain enough detail
  (image/features) to allow offline classification later.
- **Autonomy level:** TBD
- **Success looks like:** Animals detected, positioned, and tagged with
  timestamp + Master ID (or flagged uncertain with retained detail for
  later offline classification); records queued/uploaded in high-
  bandwidth mode.
- **Failure / safety behavior:** Not specified.
- **Notes:** Depends on MP-1's map. Supports CAP-8 (Object
  Classification), CAP-4 (Telemetry Reporting).

### MP-3: Fetch and Retrieve

- **Priority:** Must
- **Scenario:** Take an input from a remote user requesting a specific
  small, transportable item (a beverage, a tool, or similar — no heavy
  implements). Proceed to a known load point. A human loads the item and
  updates status via a small onboard LCD or a shared web interface. The
  rover navigates to the delivery point, which must be permitted by the
  map (not inside an exclusion geofence). The rover signals arrival to
  the requesting/remote user and updates status if communication is
  available.
- **Autonomy level:** TBD
- **Success looks like:** Item delivered to the correct, geofence-
  permitted point; status updated at load and at arrival.
- **Failure / safety behavior:** Delivery route must respect exclusion
  geofences (CAP-2). Rover should run a pre-mission check of whether it
  has sufficient power reserve for the round trip before departing (see
  CAP-11 / D-4 Bingo Fuel), with an allowance factor for the weight of
  the item being carried (precise weight-based draw modeling not
  required for the initial release).
- **Notes:** External payload should accommodate a beverage (soda can,
  20 oz bottle, water container) or a small tool/gloves/phone/firearm —
  weight- and space-limited, no towed trailer (see PLT-6). Any new
  obstacles/map data discovered along the delivery route should be
  appended to the master map (see Vision, CAP-3).

### MP-4: Sentry Mode

- **Priority:** Should (sequenced after MP-1–3, see D-2)
- **Scenario:** Operating at night, conduct periodic sweeps around a
  defined chicken-coop boundary. Identify any varmint/predator presence
  (raccoon, possum, coyote) and make noise or flash lights to ward off
  the predator. Tag and alert the interaction.
- **Autonomy level:** TBD
- **Success looks like:** Predator detected, deterred (noise/light), and
  the interaction tagged and alerted.
- **Failure / safety behavior:** Must run at very low power to sustain a
  complete night of operation. Open question on whether an additional
  night-sensing package (e.g. IR camera/sensors) is needed, and whether
  a separate, lower-power sensor package should be used during sweeps to
  maximize on-station time (see Q-4).
- **Notes:** —

## Out of scope for Phase 2 (parking lot)

Ideas worth keeping but explicitly deferred to a later phase.

- Home/base charging and map-data-offload station — explicitly deferred
  as "nice to have, not required for V1" (see D-5).

## Raw notes

