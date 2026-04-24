import time
import board
import adafruit_vl53l1x
import struct

VL53L1X_ADDR   = 0x29
ROI_CENTER_REG = 0x0007
ROI_SIZE_REG   = 0x0008

# Three zones across the middle row only
ZONES = [
    ("LEFT",   127),
    ("CENTER", 199),
    ("RIGHT",   83),
]

# Tuning
ROI_W         = 8
ROI_H         = 8
PRESENT_MM    = 300   # hand must be closer than this to count
SWIPE_TIMEOUT = 1.5   # seconds before resetting swipe state
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

    # Swipe state machine
    # Stage 0: waiting for LEFT
    # Stage 1: LEFT seen, waiting for CENTER
    # Stage 2: CENTER seen, waiting for RIGHT
    swipe_stage      = 0
    swipe_start_time = 0

    print("--- Left to Right Swipe Detection ---")
    print(f"Present threshold: {PRESENT_MM}mm\n")

    while True:
        # Read all three zones
        readings = {}
        for name, center in ZONES:
            readings[name] = read_zone(vl53, i2c, center)

        left   = readings["LEFT"]
        center = readings["CENTER"]
        right  = readings["RIGHT"]

        # Print raw values
        def fmt(v):
            return f"{v:4d}mm" if v != NO_READING else "  --  "
        print(f"LEFT:{fmt(left)}  CENTER:{fmt(center)}  RIGHT:{fmt(right)}  "
              f"[stage {swipe_stage}]")

        # Swipe state machine — hand must pass LEFT then CENTER then RIGHT
        now = time.monotonic()

        if swipe_stage == 0:
            if left != NO_READING and left < PRESENT_MM:
                swipe_stage      = 1
                swipe_start_time = now
                print("  >> Stage 1: LEFT detected, swipe started")

        elif swipe_stage == 1:
            if center != NO_READING and center < PRESENT_MM:
                swipe_stage = 2
                print("  >> Stage 2: CENTER detected")
            # Reset if timeout
            if now - swipe_start_time > SWIPE_TIMEOUT:
                print("  >> Timeout, resetting")
                swipe_stage = 0

        elif swipe_stage == 2:
            if right != NO_READING and right < PRESENT_MM:
                print("\n  ✨ SWIPE DETECTED: Left to Right! ✨\n")
                swipe_stage = 0
            # Reset if timeout
            if now - swipe_start_time > SWIPE_TIMEOUT:
                print("  >> Timeout, resetting")
                swipe_stage = 0

if __name__ == "__main__":
    main()

