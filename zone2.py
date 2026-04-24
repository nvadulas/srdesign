import time
import board
import adafruit_vl53l1x
import struct

# ---------------------------------------------------------------------------
# Sensor config
# ---------------------------------------------------------------------------
VL53L1X_ADDR   = 0x29
ROI_CENTER_REG = 0x0007
ROI_SIZE_REG   = 0x0008

ROI_CENTERS = [
    [167, 175, 183],  # Top Row:    TL, TC, TR
    [103, 199,  91],  # Middle Row: ML, MC, MR
    [ 71,  63,  55],  # Bottom Row: BL, BC, BR
]

ZONE_NAMES = [
    ["TL", "TC", "TR"],
    ["ML", "MC", "MR"],
    ["BL", "BC", "BR"],
]

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------
ROI_WIDTH     = 12
ROI_HEIGHT    = 12
THRESHOLD_MM  = 250   # hand must be closer than this to count as detected
CONFIRM_COUNT = 3     # zone must read consistently for N scans to confirm
NO_READING    = 65535

# ---------------------------------------------------------------------------
# ROI
# ---------------------------------------------------------------------------
def set_roi(i2c, center, width=ROI_WIDTH, height=ROI_HEIGHT):
    size_byte = ((height - 1) << 4) | (width - 1)
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", ROI_CENTER_REG) + bytes([center]))
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", ROI_SIZE_REG)   + bytes([size_byte]))

# ---------------------------------------------------------------------------
# Single zone read
# ---------------------------------------------------------------------------
def read_zone(vl53, i2c, center):
    set_roi(i2c, center)
    vl53.clear_interrupt()
    time.sleep(0.1)

    timeout = time.monotonic() + 0.5
    while not vl53.data_ready:
        if time.monotonic() > timeout:
            return NO_READING
        time.sleep(0.005)

    dist = vl53.distance
    vl53.clear_interrupt()
    return round(dist * 10) if dist is not None else NO_READING

# ---------------------------------------------------------------------------
# Print grid
# ---------------------------------------------------------------------------
def print_grid(grid, confirmed):
    print("---- 3x3 Grid (mm) ----")
    for r, g_row in enumerate(grid):
        row_str = ""
        for c, v in enumerate(g_row):
            label = ZONE_NAMES[r][c]
            if v == NO_READING:
                cell = "---- "
            elif confirmed[r][c]:
                cell = f"{v}* "    # * = confirmed hand detection
            else:
                cell = f"{v}  "
            row_str += f"{label}:{cell:<7}"
        print(row_str)
    print()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    i2c  = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 100
    vl53.start_ranging()

    # Confirmation counters — how many consecutive scans each zone was active
    zone_counts = [[0] * 3 for _ in range(3)]

    print("--- 3x3 Grid Scanner ---")
    print(f"Threshold: {THRESHOLD_MM}mm | Confirm: {CONFIRM_COUNT} scans\n")

    while True:
        grid      = []
        confirmed = [[False] * 3 for _ in range(3)]

        for r, row in enumerate(ROI_CENTERS):
            grid_row = []
            for c, center in enumerate(row):
                val = read_zone(vl53, i2c, center)
                grid_row.append(val)

                # Update confirmation counter
                if val != NO_READING and val < THRESHOLD_MM:
                    zone_counts[r][c] += 1
                else:
                    zone_counts[r][c] = 0

                confirmed[r][c] = zone_counts[r][c] >= CONFIRM_COUNT

            grid.append(grid_row)

        print_grid(grid, confirmed)

if __name__ == "__main__":
    main()
