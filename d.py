import time
import board
import adafruit_vl53l1x
import struct

VL53L1X_ADDR   = 0x29
ROI_CENTER_REG = 0x0007
ROI_SIZE_REG   = 0x0008

ROI_CENTERS = [
    [191, 175, 159],  # Top Row:    TL,  TC,  TR
    [127, 199,  83],  # Middle Row: ML,  MC,  MR
    [ 79,  63,  47],  # Bottom Row: BL,  BC,  BR
]

ZONE_NAMES = [
    ["TL", "TC", "TR"],
    ["ML", "MC", "MR"],
    ["BL", "BC", "BR"],
]

BASELINE_SAMPLES = 10    # number of scans to average for baseline
DELTA_THRESHOLD  = 80    # mm drop from baseline to count as hand present
DOMINANCE_MM     = 60    # how much more drop the winner needs vs others
CONFIRM_COUNT    = 3
NO_READING       = 65535

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

def scan_grid(vl53, i2c):
    readings = []
    for r, row in enumerate(ROI_CENTERS):
        grid_row = []
        for c, center in enumerate(row):
            grid_row.append(read_zone(vl53, i2c, center))
        readings.append(grid_row)
    return readings

def calibrate_baseline(vl53, i2c):
    """
    Scan the grid several times with NO hand present and average
    the results. This becomes our reference — any reading that drops
    significantly below baseline means a hand is blocking that zone.
    """
    print("--- Calibrating baseline (keep hand away) ---")
    totals  = [[0.0] * 3 for _ in range(3)]
    counts  = [[0]   * 3 for _ in range(3)]

    for i in range(BASELINE_SAMPLES):
        print(f"  Sample {i+1}/{BASELINE_SAMPLES}...")
        grid = scan_grid(vl53, i2c)
        for r in range(3):
            for c in range(3):
                if grid[r][c] != NO_READING:
                    totals[r][c] += grid[r][c]
                    counts[r][c] += 1

    baseline = []
    for r in range(3):
        row = []
        for c in range(3):
            if counts[r][c] > 0:
                row.append(totals[r][c] / counts[r][c])
            else:
                row.append(NO_READING)
        baseline.append(row)

    print("\nBaseline (mm):")
    for r in range(3):
        row_str = ""
        for c in range(3):
            label = ZONE_NAMES[r][c]
            v = baseline[r][c]
            cell = "----" if v == NO_READING else f"{v:.0f}"
            row_str += f"{label}:{cell:<7}"
        print(row_str)
    print()
    return baseline

def compute_deltas(readings, baseline):
    """
    Compute how much each zone dropped from baseline.
    A large positive delta means a hand is closer than the baseline object.
    """
    deltas = []
    for r in range(3):
        row = []
        for c in range(3):
            b = baseline[r][c]
            v = readings[r][c]
            if b == NO_READING or v == NO_READING:
                row.append(0)
            else:
                # Positive delta = hand is closer than baseline
                row.append(max(0, b - v))
        deltas.append(row)
    return deltas

def dominant_zone(deltas):
    """
    Find zone with the largest delta that also beats all others by DOMINANCE_MM.
    """
    # Flatten
    flat = {}
    for r in range(3):
        for c in range(3):
            d = deltas[r][c]
            if d >= DELTA_THRESHOLD:
                flat[(r, c)] = d

    if not flat:
        return None

    winner = max(flat, key=flat.get)
    winner_delta = flat[winner]

    others = {k: v for k, v in flat.items() if k != winner}
    if all(winner_delta > v + DOMINANCE_MM for v in others.values()):
        return winner

    # If no single dominant zone, return None
    return None

def print_grid(readings, deltas, confirmed_zone):
    print("---- 3x3 Grid (mm) | delta ----")
    for r in range(3):
        row_str = ""
        for c in range(3):
            v     = readings[r][c]
            d     = deltas[r][c]
            label = ZONE_NAMES[r][c]
            marker = "*" if confirmed_zone == (r, c) else " "
            if v == NO_READING:
                cell = "----      "
            else:
                cell = f"{v}(Δ{d:+.0f}){marker}"
            row_str += f"{label}:{cell:<14}"
        print(row_str)
    print()

def main():
    i2c  = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 100
    vl53.start_ranging()

    # Calibrate baseline first
    baseline = calibrate_baseline(vl53, i2c)

    streaks        = [[0] * 3 for _ in range(3)]
    confirmed_zone = None
    last_declared  = None

    print("--- 3x3 Delta Detection ---")
    print(f"Delta threshold: {DELTA_THRESHOLD}mm | "
          f"Dominance: {DOMINANCE_MM}mm | Confirm: {CONFIRM_COUNT}\n")

    while True:
        readings = scan_grid(vl53, i2c)
        deltas   = compute_deltas(readings, baseline)
        winner   = dominant_zone(deltas)

        # Update streaks
        for r in range(3):
            for c in range(3):
                if winner == (r, c):
                    streaks[r][c] += 1
                else:
                    streaks[r][c] = 0

        # Confirm zone
        confirmed_zone = None
        for r in range(3):
            for c in range(3):
                if streaks[r][c] >= CONFIRM_COUNT:
                    confirmed_zone = (r, c)

        print_grid(readings, deltas, confirmed_zone)

        if confirmed_zone and confirmed_zone != last_declared:
            r, c = confirmed_zone
            print(f"  >>> HAND AT {ZONE_NAMES[r][c]}\n")
            last_declared = confirmed_zone
        elif confirmed_zone is None:
            last_declared = None

if __name__ == "__main__":
    main()
