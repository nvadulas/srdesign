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

# How much closer the winning zone must be vs the others (mm)
# Increase this to make it less sensitive
DOMINANCE_MM  = 100
CONFIRM_COUNT = 3      # consecutive scans before declaring a side
NO_READING    = 65535

def set_roi(i2c, center, width=8, height=8):
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

def dominant_zone(readings):
    """
    Returns the zone name that is clearly closer than all others,
    or None if no zone dominates.
    
    A zone dominates if:
    1. It has a valid reading
    2. It reads at least DOMINANCE_MM closer than every other valid zone
    """
    valid = {name: val for name, val in readings.items() if val != NO_READING}
    if not valid:
        return None

    # Find the closest zone
    winner = min(valid, key=valid.get)
    winner_val = valid[winner]

    # Check it beats every other zone by DOMINANCE_MM
    others = {n: v for n, v in valid.items() if n != winner}
    if all(winner_val < v - DOMINANCE_MM for v in others.values()):
        return winner

    return None  # no clear winner

def main():
    i2c  = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 100
    vl53.start_ranging()

    confirm_streak = {"LEFT": 0, "CENTER": 0, "RIGHT": 0}
    last_declared  = None

    print("--- Dominant Zone Detection ---")
    print(f"Dominance margin: {DOMINANCE_MM}mm | Confirm: {CONFIRM_COUNT} scans\n")

    while True:
        readings = {}
        for name, center in ZONES:
            readings[name] = read_zone(vl53, i2c, center)

        # Print raw readings
        row = ""
        for name, _ in ZONES:
            v = readings[name]
            cell = "----" if v == NO_READING else f"{v:4d}"
            row += f"{name}:{cell}  "
        print(row)

        # Find dominant zone
        winner = dominant_zone(readings)

        # Update confirmation streaks
        for name in confirm_streak:
            if name == winner:
                confirm_streak[name] += 1
            else:
                confirm_streak[name] = 0

        # Declare detection only after CONFIRM_COUNT consecutive wins
        for name in confirm_streak:
            if confirm_streak[name] >= CONFIRM_COUNT and last_declared != name:
                print(f"  >>> HAND ON {name}")
                last_declared = name

        # Reset declared side when no winner
        if winner is None:
            last_declared = None

if __name__ == "__main__":
    main()
