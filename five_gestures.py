import time
import board
import busio
import digitalio
import adafruit_vl53l1x

# ── XSHUT pins ────────────────────────────────────────────────────────────────
XSHUT_LEFT_PIN  = board.D17
XSHUT_RIGHT_PIN = board.D27

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN   = "\033[92m"
RED     = "\033[91m"
YELLOW  = "\033[93m"
BLUE    = "\033[94m"
MAGENTA = "\033[95m"
RESET   = "\033[0m"

# ── Tuning ────────────────────────────────────────────────────────────────────
PRESENT_MM    = 300
DOMINANCE_MM  = 40
SWIPE_TIMEOUT = 0.5
HOLD_TIME     = 3.0
NO_READING    = 65535


def make_xshut(pin):
    x = digitalio.DigitalInOut(pin)
    x.direction = digitalio.Direction.OUTPUT
    return x


def init_sensors():
    xshut_left  = make_xshut(XSHUT_LEFT_PIN)
    xshut_right = make_xshut(XSHUT_RIGHT_PIN)

    xshut_left.value  = False
    xshut_right.value = False
    time.sleep(0.5)

    xshut_left.value = True
    time.sleep(0.5)
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor_left = adafruit_vl53l1x.VL53L1X(i2c)
    sensor_left.distance_mode = 1
    sensor_left.timing_budget = 50

    sensor_left.set_address(0x30)
    time.sleep(0.5)

    i2c.deinit()
    time.sleep(0.5)
    i2c = busio.I2C(board.SCL, board.SDA)

    sensor_left = adafruit_vl53l1x.VL53L1X(i2c, address=0x30)
    sensor_left.distance_mode = 1
    sensor_left.timing_budget = 50
    print("Left sensor ready at 0x30")

    xshut_right.value = True
    time.sleep(0.5)
    sensor_right = adafruit_vl53l1x.VL53L1X(i2c)
    sensor_right.distance_mode = 1
    sensor_right.timing_budget = 50
    print("Right sensor ready at 0x29")

    return sensor_left, sensor_right


def read_one(sensor):
    try:
        sensor.start_ranging()
        timeout = time.monotonic() + 0.5
        while not sensor.data_ready:
            if time.monotonic() > timeout:
                sensor.stop_ranging()
                return NO_READING
            time.sleep(0.005)
        dist = sensor.distance
        sensor.clear_interrupt()
        sensor.stop_ranging()
        return round(dist * 10) if dist is not None else NO_READING
    except OSError:
        return NO_READING


def fmt(v):
    return f"{v:4d}mm" if v != NO_READING else "  --  "


def main():
    print("Initialising sensors...")
    sensor_left, sensor_right = init_sensors()
    print("Both sensors ready.\n")

    swipe_stage      = 0
    swipe_dir        = None
    swipe_start_time = 0

    # Hold tracking — when each sensor first became present
    hold_left_start  = None
    hold_right_start = None
    hold_both_start  = None

    # Prevent repeated firing until hand is removed
    hold_left_fired  = False
    hold_right_fired = False
    hold_both_fired  = False

    print("--- Gesture Detection (Left↔Right Swipe + Hold) ---")
    print(f"Dominance margin: {DOMINANCE_MM}mm  |  Hold time: {HOLD_TIME}s\n")

    while True:
        left  = read_one(sensor_left)
        right = read_one(sensor_right)

        left_present  = left  != NO_READING and left  < PRESENT_MM
        right_present = right != NO_READING and right < PRESENT_MM

        print(f"LEFT:{fmt(left)}  RIGHT:{fmt(right)}  [stage {swipe_stage} dir={swipe_dir}]")

        now = time.monotonic()

        # ── Hold tracking ─────────────────────────────────────────────────────

        # Both held
        if left_present and right_present:
            if hold_both_start is None:
                hold_both_start = now
            if not hold_both_fired and now - hold_both_start >= HOLD_TIME:
                print(f"\n  {MAGENTA}✋ HOLD DETECTED: Both sensors! ✋{RESET}\n")
                hold_both_fired = True
        else:
            hold_both_start = None
            hold_both_fired = False

        # Left only held
        if left_present and not right_present:
            if hold_left_start is None:
                hold_left_start = now
            if not hold_left_fired and now - hold_left_start >= HOLD_TIME:
                print(f"\n  {YELLOW}✋ HOLD DETECTED: Left sensor! ✋{RESET}\n")
                hold_left_fired = True
        else:
            hold_left_start = None
            hold_left_fired = False

        # Right only held
        if right_present and not left_present:
            if hold_right_start is None:
                hold_right_start = now
            if not hold_right_fired and now - hold_right_start >= HOLD_TIME:
                print(f"\n  {BLUE}✋ HOLD DETECTED: Right sensor! ✋{RESET}\n")
                hold_right_fired = True
        else:
            hold_right_start = None
            hold_right_fired = False

        # ── Swipe detection ───────────────────────────────────────────────────

        if swipe_stage == 0:
            if left_present and (not right_present or left < right - DOMINANCE_MM):
                swipe_stage      = 1
                swipe_dir        = "LR"
                swipe_start_time = now
                print(f"  >> Stage 1: LEFT dominant — watching for RIGHT (L={fmt(left)} R={fmt(right)})")

            elif right_present and (not left_present or right < left - DOMINANCE_MM):
                swipe_stage      = 1
                swipe_dir        = "RL"
                swipe_start_time = now
                print(f"  >> Stage 1: RIGHT dominant — watching for LEFT (L={fmt(left)} R={fmt(right)})")

        elif swipe_stage == 1:
            if now - swipe_start_time > SWIPE_TIMEOUT:
                print("  >> Timeout, resetting")
                swipe_stage = 0
                swipe_dir   = None

            elif swipe_dir == "LR":
                if right_present and (not left_present or right < left - DOMINANCE_MM):
                    print(f"\n  {GREEN}✨ SWIPE DETECTED: Left to Right! ✨{RESET}\n")
                    swipe_stage = 0
                    swipe_dir   = None

            elif swipe_dir == "RL":
                if left_present and (not right_present or left < right - DOMINANCE_MM):
                    print(f"\n  {RED}✨ SWIPE DETECTED: Right to Left! ✨{RESET}\n")
                    swipe_stage = 0
                    swipe_dir   = None

        time.sleep(0.02)


if __name__ == "__main__":
    main()
