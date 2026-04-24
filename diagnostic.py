import time
import board
import adafruit_vl53l1x
import struct

VL53L1X_ADDR   = 0x29
ROI_CENTER_REG = 0x007F
ROI_SIZE_REG   = 0x0080

def write_reg(i2c, reg, val):
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", reg) + bytes([val]))

def main():
    i2c  = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 200

    # Start once and NEVER stop
    vl53.start_ranging()

    print("PHASE 1: Continuous ranging, no ROI changes")
    print("Hold hand 20-40cm away")
    print("-" * 40)
    for _ in range(30):
        vl53.clear_interrupt()
        time.sleep(0.25)

        deadline = time.monotonic() + 2.0
        while not vl53.data_ready:
            if time.monotonic() > deadline:
                print("  TIMEOUT")
                break
            time.sleep(0.01)
        else:
            print(f"  dist = {vl53.distance} cm")
            vl53.clear_interrupt()

    # ── Now test ROI WITHOUT stopping ranging ──────────────────────────────
    print("\nPHASE 2: ROI changes WITHOUT stop/start")
    print("Keep hand in front, move left and right slowly")
    print("-" * 40)

    zones = [("LEFT", 147, 8, 16), ("RIGHT", 155, 8, 16)]

    for _ in range(30):
        row = ""
        for name, center, w, h in zones:
            # Write ROI while ranging is still active
            write_reg(i2c, ROI_CENTER_REG, center)
            write_reg(i2c, ROI_SIZE_REG, ((h-1) << 4) | (w-1))

            vl53.clear_interrupt()
            time.sleep(0.25)  # wait one full measurement cycle

            deadline = time.monotonic() + 1.0
            while not vl53.data_ready:
                if time.monotonic() > deadline:
                    row += f"{name}:TIMEOUT  "
                    break
                time.sleep(0.01)
            else:
                raw = vl53.distance
                mm = round(raw * 10) if raw else None
                row += f"{name}:{mm}mm  " if mm else f"{name}:None  "
                vl53.clear_interrupt()
        print(" ", row)

if __name__ == "__main__":
    main()
