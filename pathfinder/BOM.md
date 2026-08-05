# Physical Parts Purchased for PCB Footprint Analysis
Note- these are the 'on board' components only.

- PCB Screw Terminal Assortment: Used for general screw terminal attachments.
  Amazon URL: https://www.amazon.com/dp/B0D1GMMTZ5?ref=ppx_yo2ov_dt_b_fed_asin_title&th=1
  Amazon ASIN: B0D1GMMTZ5
  Usage: Primary off-board connectors for incoming power and ground, plus connections from ESP32 to BTS motor controller signal connections.  The BTS connections could be header pin based if needed to conserve board space.
  Footprint: Single connectors at approximately 5mm square, but can be combined into multiple component blocks at 5mm increments.

- UBEC 5V/3A: Tagged as 'U2'
  Amazon URL: https://www.amazon.com/dp/B07PLSYX9G?ref=ppx_yo2ov_dt_b_fed_asin_title
  Amazon ASIN: B07PLSYX9G
  Footprint: rectangular with 4 pins at the corners, approx 10mm x 15mm.  Input and output pins are on the 'short' sides.

- ESP32-S3 Development Board: used for ESP32 footprint.
  Amazon URL: https://www.amazon.com/dp/B0F5QCK6X5?ref=ppx_yo2ov_dt_b_fed_asin_title&th=1
  Amazon ASIN: B0F5QCK6X5
  Footprint: NOT a single 2x22 block -- two separate 1x22 P2.54mm header rows
  (Espressif calls them J1/J3). Measured row-to-row centerline spacing was
  25.5-26.0mm; deliberately loosened to 25.40mm row spacing / 2.0mm pad /
  1.1mm drill for assembly tolerance rather than targeting the raw
  measurement exactly. Pin 1 of both rows is at the same end of the board;
  row orientation corrected after an initial mirrored build (J1-origin pins
  on the +Y row, J3-origin on -Y). Custom footprint:
  pathfinder/kicad/papaya-pcb/papaya-pcb.pretty/ESP32S3_DevKit_2x1x22_split.kicad_mod,
  pin assignment per Espressif's published ESP32-S3-DevKitC-1 J1/J3 tables.

- Other connectors are just standard header pins.
    - Servo connectors S1, S2, S3, S4: 3-pin male headers (black/red/white sequence)
    - Radio receiver connector J4: 4-pin male headers. (Red/Black and Green/White)
