import time
import board
import adafruit_vl53l1x
import struct

VL53L1X_ADDR   = 0x29
ROI_CENTER_REG = 0x007F
ROI_SIZE_REG   = 0x0080

def write_reg(i2c, reg, val):
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", reg) + bytes([val]))

def set_roi(i2c, center, w, h):
    write_reg(i2c, ROI_CENTER_REG, center)
    write_reg(i2c, ROI_SIZE_REG, ((max(4,h)-1) << 4) | (max(4,w)-1))

def flush_and_read(vl53, i2c, cycles=2):
    """
    After a register write, the VL53L1X discards the in-progress measurement.
    We must throw away the first reading and take the second one.
    cycles=2 means: discard 1, keep 1.
    """
    reading = None
    for i in range(cycles):
        vl53.clear_interrupt()
        # Wait longer than timing_budget (200ms) to guarantee a fresh measurement
        time.sleep(0.28)

        deadline = time.monotonic() + 1.5
        while not vl53.data_ready:
            if time.monotonic() > deadline:
                break
            time.sleep(0.005)

        raw = vl53.distance
        vl53.clear_interrupt()

        if i == cycles - 1:   # only keep the last cycle
            reading = round(raw * 10) if raw else None

    return reading

def read_zone(vl53, i2c, center, w, h):
    set_roi(i2c, center, w, h)
    return flush_and_read(vl53, i2c, cycles=2)

def main():
    i2c  = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 200

    vl53.start_ranging()

    # Warm up — let sensor stabilise before we touch any registers
    print("Warming up (2s)...")
    for _ in range(8):
        vl53.clear_interrupt()
        time.sleep(0.25)
        if vl53.data_ready:
            _ = vl53.distance
            vl53.clear_interrupt()

    print("Ready. Move hand left and right ~25cm from sensor.\n")

    ZONES = [
        ("LEFT",   147, 8, 16),
        ("RIGHT",  155, 8, 16),
    ]

    DOMINANCE_MM  = 40   # start low — tune upward if false triggers
    CONFIRM_COUNT = 2

    streak = {"LEFT": 0, "RIGHT": 0}
    last_declared = None

    while True:
        readings = {}
        for name, center, w, h in ZONES:
            readings[name] = read_zone(vl53, i2c, center, w, h)

        L = readings["LEFT"]
        R = readings["RIGHT"]
        l_str = f"{L}mm" if L else "----"
        r_str = f"{R}mm" if R else "----"
        diff  = (L - R) if (L and R) else 0
        print(f"LEFT:{l_str:<8} RIGHT:{r_str:<8} diff:{diff:+d}mm", end="")

        # Dominant zone logic
        winner = None
        if L and R:
            if L < R - DOMINANCE_MM:
                winner = "LEFT"
            elif R < L - DOMINANCE_MM:
                winner = "RIGHT"
        elif L and not R:
            winner = "LEFT"
        elif R and not L:
            winner = "RIGHT"

        for name in streak:
            streak[name] = streak[name] + 1 if name == winner else 0

        for name in streak:
            if streak[name] >= CONFIRM_COUNT and last_declared != name:
                print(f"  >>> {name}")
                last_declared = name
                break
        else:
            print()

        if winner is None:
            last_declared = None

if __name__ == "__main__":
    main()
