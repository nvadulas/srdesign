import time
import board
import adafruit_vl53l1x
import struct

VL53L1X_ADDR   = 0x29

# ── The CORRECT registers ──────────────────────────────────────────────────
# 0x0007/0x0008 are wrong — they are not ROI registers on this chip
# The real registers are:
ROI_CENTER_REG = 0x007F
ROI_SIZE_REG   = 0x0080

def write_reg(i2c, reg, val):
    """Write one byte to a 16-bit register address."""
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", reg) + bytes([val]))

def read_reg(i2c, reg):
    """Read one byte back from a register to confirm it was written."""
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", reg))
    result = bytearray(1)
    i2c.readfrom_into(VL53L1X_ADDR, result)
    return result[0]

def set_roi(i2c, center, w, h):
    w = max(4, min(16, w))
    h = max(4, min(16, h))
    write_reg(i2c, ROI_CENTER_REG, center)
    write_reg(i2c, ROI_SIZE_REG, ((h - 1) << 4) | (w - 1))

def read_zone(vl53, i2c, center, w, h):
    vl53.stop_ranging()            # MUST stop before changing ROI
    set_roi(i2c, center, w, h)

    # Confirm the write actually took
    c_back = read_reg(i2c, ROI_CENTER_REG)
    s_back = read_reg(i2c, ROI_SIZE_REG)
    print(f"    [verify] center wrote={center} read={c_back} | size wrote={((h-1)<<4)|(w-1)} read={s_back}")

    vl53.start_ranging()
    vl53.clear_interrupt()
    time.sleep(0.2)

    deadline = time.monotonic() + 0.8
    while not vl53.data_ready:
        if time.monotonic() > deadline:
            vl53.stop_ranging()
            return None
        time.sleep(0.005)

    dist = vl53.distance
    vl53.clear_interrupt()
    vl53.stop_ranging()
    return round(dist * 10) if dist is not None else None

def main():
    i2c  = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 200

    # ── Test 1: Full array baseline ────────────────────────────────────────
    # 16x16 ROI = full sensor. This tells us the sensor works at all.
    print("=" * 50)
    print("TEST 1: Full array (16x16) — should get a clean reading")
    print("=" * 50)
    for _ in range(5):
        d = read_zone(vl53, i2c, center=199, w=16, h=16)
        print(f"  Full array: {d}mm\n")
        time.sleep(0.3)

    # ── Test 2: Hard left vs hard right — maximum possible split ──────────
    # If these two read identically, ROI is not working at all on your unit
    print("=" * 50)
    print("TEST 2: LEFT half (w=8) vs RIGHT half (w=8)")
    print("Put your hand on the LEFT side only, then RIGHT side only")
    print("=" * 50)
    for i in range(20):
        # LEFT: center SPAD column 3, row 9  → SPAD = 9*16+3 = 147
        # RIGHT: center SPAD column 11, row 9 → SPAD = 9*16+11 = 155
        # These are the two most separated valid centers for a half-width split
        left  = read_zone(vl53, i2c, center=147, w=8, h=16)
        right = read_zone(vl53, i2c, center=155, w=8, h=16)

        diff = (left or 0) - (right or 0)
        l_str = f"{left}mm"  if left  else "----"
        r_str = f"{right}mm" if right else "----"
        print(f"  LEFT: {l_str:<8}  RIGHT: {r_str:<8}  diff: {diff:+d}mm")
        time.sleep(0.1)

    # ── Test 3: Tiny ROI vs full ROI — proves ROI masking works at all ────
    print("=" * 50)
    print("TEST 3: 4x4 (tiny) vs 16x16 (full) — readings should differ")
    print("=" * 50)
    for _ in range(10):
        tiny = read_zone(vl53, i2c, center=199, w=4,  h=4)
        full = read_zone(vl53, i2c, center=199, w=16, h=16)
        t_str = f"{tiny}mm" if tiny else "----"
        f_str = f"{full}mm" if full else "----"
        print(f"  4x4: {t_str:<8}  16x16: {f_str:<8}")
        time.sleep(0.1)

if __name__ == "__main__":
    main()
