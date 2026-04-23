# vl53l1x_grid_scan.py
# Raspberry Pi port of the Arduino 3x3 ROI grid scanner.
# Uses the Adafruit CircuitPython VL53L1X library.
#
# Install dependencies:
#   pip3 install adafruit-circuitpython-vl53l1x
# Enable I2C on the Pi:
#   sudo raspi-config -> Interface Options -> I2C -> Enable

import time
import board
import adafruit_vl53l1x

# ---------------------------------------------------------------------------
# ROI centre SPAD addresses — identical to the Arduino version.
# The VL53L1X SPAD array is 16×16; these values match the pololu/Arduino
# library conventions and are accepted by the Adafruit driver as-is.
# ---------------------------------------------------------------------------
ROI_CENTERS = [
    [147, 179, 211],
    [ 83,  91,  99],
    [ 51,  59,  67],
]

ROI_SIZE = (4, 4)          # width, height in SPADs
TIMING_BUDGET_MS = 50      # must be one of: 15,20,33,50,100,200,500
ZONE_SETTLE_S   = 0.02     # 30 ms settle after changing ROI (like the Arduino delay(30))
LOOP_DELAY_S    = 0.15     # 150 ms between full grid scans

def main():
	i2c = board.I2C()                       # uses GPIO 2 (SDA) and GPIO 3 (SCL)
	sensor = adafruit_vl53l1x.VL53L1X(i2c)

	sensor.distance_mode = 1               # 2 = Long (matches setDistanceMode(Long))
	sensor.timing_budget = 50
	sensor.timing_budget = TIMING_BUDGET_MS
	sensor.start_ranging()
	print("Starting stable 3x3 long-range scan...")
    
	while True:
		print("---- 3x3 Grid (mm) ----")
		for row in ROI_CENTERS:
			grid_row_values = []
			for center in row:
				sensor.roi_width = 4
				sensor.roi_height = 4
				sensor.roi_center = center
			
				sensor.clear_interrupt()

				start = time.monotonic()
				while not sensor.data_ready:
					if time.monotonic() - start > 0.2:
						break
					time.sleep(0.005)

				dist = sensor.distance
				if dist is None:
					grid_row_values.append("65535")
				else:
				 	grid_row_values.append(str(round(dist * 10)))
			print("\t".join(grid_row_values))
		print("\n")
		time.sleep(0.1)

if __name__ == "__main__":
    main()
