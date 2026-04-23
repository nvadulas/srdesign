import time
import board
import adafruit_vl53l1x

# ROI Centers (3x3 Grid)
ROI_CENTERS = [
    [147, 179, 211],  # Top Row
    [83, 91, 99],  # Mid Row (Used for Left-to-Right swipe)
    [51, 59, 67],  # Bot Row
]

# Settings
THRESHOLD_MM = 400  # Anything closer than 40cm is a hand
SWIPE_TIMEOUT = 1.5  # Seconds allowed to complete the full motion
ZONE_SETTLE_S = 0.05

def main():
    i2c = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)

    # Use the stable settings from your check_sensor()
    vl53.distance_mode = 1
    vl53.timing_budget = 50
    vl53.start_ranging()
    vl53.clear_interrupt()
    # Swipe state machine: 0=None, 1=Left detected, 2=Center detected
    swipe_stage = 0
    swipe_start_time = 0

    print("--- 3x3 Grid & Swipe Detection Active ---")

    while True:
        grid = []

        for r_idx, row in enumerate(ROI_CENTERS):
            grid_row = []
            for c_idx, center in enumerate(row):
                # Switch ROI and clear previous state
                vl53.stop_ranging()
                vl53.roi_center = center
                vl53.roi_width = 4
                vl53.roi_height = 4
                vl53.start_ranging()

                vl53.clear_interrupt()
                
                time.sleep(ZONE_SETTLE_S)
                # Wait for data with 200ms timeout
                start_wait = time.monotonic()
                while not vl53.data_ready:
                    if time.monotonic() - start_wait > 0.3:
                        break
                    time.sleep(0.005)

                # Read distance
                dist = vl53.distance
                val = round(dist * 10) if dist is not None else 65535
                grid_row.append(val)

                # -- Swipe Logic (Watch Middle Row only) ---
                if r_idx == 1 and val < THRESHOLD_MM:
                    if c_idx == 0 and swipe_stage == 0:
                        swipe_stage = 1
                        swipe_start_time = time.monotonic()
                    elif c_idx == 1 and swipe_stage == 1:
                        swipe_stage = 2
                    elif c_idx == 2 and swipe_stage == 2:
                        print("SWIPE DETECTED: LEFT TO RIGHT\n")
                        swipe_stage = 0
             
            grid.append(grid_row)

        # Print the grid to console
        print("---- 3x3 Grid (mm) ----")
        for g_row in grid:
            print("\t".join(f"{v:5}" for v in g_row))
        print()

        # Reset swipe if it takes too long to complete
        if swipe_stage > 0 and (time.monotonic() - swipe_start_time > SWIPE_TIMEOUT):
            swipe_stage = 0


if __name__ == "__main__":
    main()
