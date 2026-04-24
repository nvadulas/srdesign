import time
import board
import adafruit_vl53l1x
import struct

VL53L1X_ADDR   = 0x29
ROI_CENTER_REG = 0x0007
ROI_SIZE_REG   = 0x0008

ZONES = [
    ("LEFT",   127),
    ("CENTER", 199),
    ("RIGHT",   83),
]

ROI_W         = 8
ROI_H         = 8
PRESENT_MM    = 300
DOMINANCE_MM  = 40    # LEFT must be this much closer than RIGHT to start swipe
SWIPE_TIMEOUT = 1.5
NO_READING    = 65535

def set_roi(i2c, center, width=ROI_W, height=ROI_H):
    size_byte = ((height - 1) << 4) | (width - 1)
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", ROI_CENTER_REG) + bytes([center]))
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", ROI_SIZE_REG)   + bytes([size_byte]))

def read_zone(vl53, i2c, center):
    set_roi(i2c, center)
    vl53.clear_interrupt()
    time.sleep(0.08)

    timeout = time.monotonic() + 0.5
    while not vl53.data_ready:
        if time.monotonic() > timeout:
            return NO_READING
        time.sleep(0.005)

    dist = vl53.distance
    vl53.clear_interrupt()
    return round(dist * 10) if dist is not None else NO_READING

def main():
    i2c  = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 100
    vl53.start_ranging()

    swipe_stage      = 0
    swipe_start_time = 0

    print("--- Left to Right Swipe Detection ---")
    print(f"Dominance margin: {DOMINANCE_MM}mm\n")

    while True:
        readings = {}
        for name, center in ZONES:
            readings[name] = read_zone(vl53, i2c, center)

        left   = readings["LEFT"]
        center = readings["CENTER"]
        right  = readings["RIGHT"]

        def fmt(v):
            return f"{v:4d}mm" if v != NO_READING else "  --  "
        print(f"LEFT:{fmt(left)}  CENTER:{fmt(center)}  RIGHT:{fmt(right)}  "
              f"[stage {swipe_stage}]")

        now = time.monotonic()

        if swipe_stage == 0:
            # LEFT must be present AND clearly closer than RIGHT
            left_valid  = left  != NO_READING and left  < PRESENT_MM
            right_valid = right != NO_READING and right < PRESENT_MM

            if left_valid and right_valid:
                if left < right - DOMINANCE_MM:
                    swipe_stage      = 1
                    swipe_start_time = now
                    print(f"  >> Stage 1: LEFT dominant "
                          f"(L={left} R={right} diff={right-left}mm)")
            elif left_valid and right == NO_READING:
                # Right has no reading at all — left clearly dominant
                swipe_stage      = 1
                swipe_start_time = now
                print(f"  >> Stage 1: LEFT dominant (R=no reading)")

        elif swipe_stage == 1:
            if now - swipe_start_time > SWIPE_TIMEOUT:
                print("  >> Timeout, resetting")
                swipe_stage = 0
            elif center != NO_READING and center < PRESENT_MM:
                swipe_stage = 2
                print("  >> Stage 2: CENTER detected")

        elif swipe_stage == 2:
            if now - swipe_start_time > SWIPE_TIMEOUT:
                print("  >> Timeout, resetting")
                swipe_stage = 0
            elif right != NO_READING and right < PRESENT_MM:
                # RIGHT must be clearly closer than LEFT now
                if right_valid := (right < PRESENT_MM):
                    if left == NO_READING or right < left - DOMINANCE_MM:
                        print("\n  ✨ SWIPE DETECTED: Left to Right! ✨\n")
                        swipe_stage = 0
                    elif right < left + DOMINANCE_MM:
                        # Close enough — accept it
                        print("\n  ✨ SWIPE DETECTED: Left to Right! ✨\n")
                        swipe_stage = 0

if __name__ == "__main__":
    main()

