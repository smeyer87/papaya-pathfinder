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
  Footprint: Standard 2x22 pin ESP32 layout

- Other connectors are just standard header pins.
    - Servo connectors S1, S2, S3, S4: 3-pin male headers (black/red/white sequence)
    - Radio receiver connector J4: 4-pin male headers. (Red/Black and Green/White)
