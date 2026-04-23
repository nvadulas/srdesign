import time
import board
import adafruit_vl53l1x

# Test just two opposite corners to confirm steering works
CORNERS = [
    ("TOP-LEFT",    167),
    ("TOP-RIGHT",   183),
    ("BOT-LEFT",     71),
    ("BOT-RIGHT",    55),
    ("CENTER",       99),
]

def main():
    i2c = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 200
    vl53.roi_width  = 8
    vl53.roi_height = 8
    vl53.start_ranging()

    print("--- Corner steering test ---")
    print("Hold your hand to ONE side and watch if the correct zone reads closer\n")

    while True:
        for name, center in CORNERS:
            vl53.roi_center = center
            vl53.clear_interrupt()
            time.sleep(0.2)

            timeout = time.monotonic() + 1.0
            while not vl53.data_ready:
                if time.monotonic() > timeout:
                    print(f"{name}: TIMEOUT")
                    break
                time.sleep(0.005)

            dist = vl53.distance
            vl53.clear_interrupt()
            val = f"{round(dist * 10):4d} mm" if dist else "  None"
            print(f"  {name:<12}: {val}")
        print()

if __name__ == "__main__":
    main()