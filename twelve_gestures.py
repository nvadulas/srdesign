import time
import board
import busio
import digitalio
import adafruit_vl53l1x

# ── XSHUT pins ────────────────────────────────────────────────────────────────
XSHUT_LEFT_PIN  = board.D17
XSHUT_RIGHT_PIN = board.D27

# ── Colors ────────────────────────────────────────────────────────────────────
COLOR_SWIPE_LR          = "\033[92m"       # Green
COLOR_SWIPE_RL          = "\033[91m"       # Red
COLOR_DOUBLE_SWIPE_LR   = "\033[38;5;118m" # Lime
COLOR_DOUBLE_SWIPE_RL   = "\033[38;5;208m" # Orange
COLOR_SHORT_HOLD_LEFT   = "\033[93m"       # Yellow
COLOR_LONG_HOLD_LEFT    = "\033[38;5;172m" # Dark orange
COLOR_SHORT_HOLD_RIGHT  = "\033[94m"       # Blue
COLOR_LONG_HOLD_RIGHT   = "\033[38;5;51m"  # Teal
COLOR_SHORT_HOLD_BOTH   = "\033[95m"       # Magenta
COLOR_LONG_HOLD_BOTH    = "\033[38;5;141m" # Purple
COLOR_DOUBLE_TAP_LEFT   = "\033[96m"       # Cyan
COLOR_DOUBLE_TAP_RIGHT  = "\033[97m"       # White
RESET                   = "\033[0m"

# ── Tuning ────────────────────────────────────────────────────────────────────
PRESENT_MM            = 300
DOMINANCE_MM          = 40
SWIPE_TIMEOUT         = 1.5
SHORT_HOLD_TIME       = 3.0
LONG_HOLD_TIME        = 5.0
DOUBLE_SWIPE_WINDOW   = 2.0
TAP_MAX_DURATION      = 0.5    # hand must leave within this time to count as tap
DOUBLE_TAP_WINDOW     = 1.0    # time to complete second tap after first
GESTURE_COOLDOWN      = 3.0
NO_READING            = 65535


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


def fire(msg, color, now):
    print(f"\n  {color}{msg}{RESET}\n")
    return now


def main():
    print("Initialising sensors...")
    sensor_left, sensor_right = init_sensors()
    print("Both sensors ready.\n")

    # ── Swipe state ───────────────────────────────────────────────────────────
    swipe_stage      = 0
    swipe_dir        = None
    swipe_start_time = 0

    # ── Double swipe state ────────────────────────────────────────────────────
    # After first swipe fires, track direction and time for second swipe
    last_swipe_dir   = None
    last_swipe_time  = 0

    # ── Entry tracking ────────────────────────────────────────────────────────
    left_was_absent  = True
    right_was_absent = True

    # ── Cooldown ──────────────────────────────────────────────────────────────
    last_gesture_time = 0

    # ── Hold state ────────────────────────────────────────────────────────────
    hold_left_start   = None
    hold_right_start  = None
    hold_both_start   = None
    hold_left_fired   = False   # fired short
    hold_right_fired  = False
    hold_both_fired   = False
    hold_left_long    = False   # fired long
    hold_right_long   = False
    hold_both_long    = False

    # ── Double tap state ──────────────────────────────────────────────────────
    # Track entry/exit times per sensor for tap detection
    left_entry_time   = None
    right_entry_time  = None
    left_tap_count    = 0
    right_tap_count   = 0
    left_first_tap_time  = 0
    right_first_tap_time = 0

    print("--- Gesture Detection ---")
    print(f"Present: <{PRESENT_MM}mm  |  Dominance: {DOMINANCE_MM}mm  |  "
          f"Short hold: {SHORT_HOLD_TIME}s  |  Long hold: {LONG_HOLD_TIME}s  |  "
          f"Double swipe window: {DOUBLE_SWIPE_WINDOW}s  |  "
          f"Tap max: {TAP_MAX_DURATION}s  |  Cooldown: {GESTURE_COOLDOWN}s\n")

    while True:
        left  = read_one(sensor_left)
        right = read_one(sensor_right)

        left_present  = left  != NO_READING and left  < PRESENT_MM
        right_present = right != NO_READING and right < PRESENT_MM
        both_present  = left_present and right_present

        now      = time.monotonic()
        cooldown = (now - last_gesture_time) < GESTURE_COOLDOWN
        swiping  = swipe_stage == 1

        print(f"LEFT:{fmt(left)}  RIGHT:{fmt(right)}  "
              f"[stage {swipe_stage} dir={swipe_dir} "
              f"cooldown={'yes' if cooldown else 'no'}]")

        # ── Track entry times for tap detection ───────────────────────────────
        if left_present and left_was_absent:
            left_entry_time = now
        if right_present and right_was_absent:
            right_entry_time = now

        # ── Detect tap on exit — hand must have been present < TAP_MAX_DURATION
        left_tapped  = False
        right_tapped = False

        if not left_present and not left_was_absent:
            if left_entry_time and (now - left_entry_time) < TAP_MAX_DURATION:
                left_tapped = True
        if not right_present and not right_was_absent:
            if right_entry_time and (now - right_entry_time) < TAP_MAX_DURATION:
                right_tapped = True

        # ── Reset swipe if both hands leave ───────────────────────────────────
        if not left_present and not right_present:
            swipe_stage = 0
            swipe_dir   = None

        # ── SWIPE — highest priority, always runs ─────────────────────────────
        if swipe_stage == 0:
            if not cooldown:
                if (left_present and left_was_absent and
                        (not right_present or left < right - DOMINANCE_MM)):
                    swipe_stage      = 1
                    swipe_dir        = "LR"
                    swipe_start_time = now
                    print(f"  >> Stage 1: LEFT entered — watching for RIGHT "
                          f"(L={fmt(left)} R={fmt(right)})")

                elif (right_present and right_was_absent and
                        (not left_present or right < left - DOMINANCE_MM)):
                    swipe_stage      = 1
                    swipe_dir        = "RL"
                    swipe_start_time = now
                    print(f"  >> Stage 1: RIGHT entered — watching for LEFT "
                          f"(L={fmt(left)} R={fmt(right)})")

        elif swipe_stage == 1:
            if now - swipe_start_time > SWIPE_TIMEOUT:
                print("  >> Timeout, resetting")
                swipe_stage = 0
                swipe_dir   = None

            elif swipe_dir == "LR":
                if right_present and (not left_present or right < left - DOMINANCE_MM):
                    # Check if this completes a double swipe
                    if (last_swipe_dir == "LR" and
                            now - last_swipe_time <= DOUBLE_SWIPE_WINDOW):
                        last_gesture_time = fire(
                            "✨✨ DOUBLE SWIPE: Left to Right! ✨✨",
                            COLOR_DOUBLE_SWIPE_LR, now)
                        last_swipe_dir  = None
                        last_swipe_time = 0
                    else:
                        last_gesture_time = fire(
                            "✨ SWIPE: Left to Right! ✨",
                            COLOR_SWIPE_LR, now)
                        last_swipe_dir  = "LR"
                        last_swipe_time = now
                    swipe_stage = 0
                    swipe_dir   = None

            elif swipe_dir == "RL":
                if left_present and (not right_present or left < right - DOMINANCE_MM):
                    if (last_swipe_dir == "RL" and
                            now - last_swipe_time <= DOUBLE_SWIPE_WINDOW):
                        last_gesture_time = fire(
                            "✨✨ DOUBLE SWIPE: Right to Left! ✨✨",
                            COLOR_DOUBLE_SWIPE_RL, now)
                        last_swipe_dir  = None
                        last_swipe_time = 0
                    else:
                        last_gesture_time = fire(
                            "✨ SWIPE: Right to Left! ✨",
                            COLOR_SWIPE_RL, now)
                        last_swipe_dir  = "RL"
                        last_swipe_time = now
                    swipe_stage = 0
                    swipe_dir   = None

        # ── All other gestures blocked during swipe or cooldown ───────────────
        if swiping or cooldown:
            left_was_absent  = not left_present
            right_was_absent = not right_present
            time.sleep(0.02)
            continue

        # ── Double tap detection ──────────────────────────────────────────────
        if left_tapped and not right_present:
            if left_tap_count == 0:
                left_tap_count       = 1
                left_first_tap_time  = now
            elif left_tap_count == 1:
                if now - left_first_tap_time <= DOUBLE_TAP_WINDOW:
                    last_gesture_time = fire(
                        "👆👆 DOUBLE TAP: Left sensor!",
                        COLOR_DOUBLE_TAP_LEFT, now)
                    left_tap_count = 0
                else:
                    # Too slow — reset and count this as first tap
                    left_tap_count      = 1
                    left_first_tap_time = now

        if right_tapped and not left_present:
            if right_tap_count == 0:
                right_tap_count       = 1
                right_first_tap_time  = now
            elif right_tap_count == 1:
                if now - right_first_tap_time <= DOUBLE_TAP_WINDOW:
                    last_gesture_time = fire(
                        "👆👆 DOUBLE TAP: Right sensor!",
                        COLOR_DOUBLE_TAP_RIGHT, now)
                    right_tap_count = 0
                else:
                    right_tap_count      = 1
                    right_first_tap_time = now

        # Reset tap counts if window expired
        if left_tap_count == 1 and now - left_first_tap_time > DOUBLE_TAP_WINDOW:
            left_tap_count = 0
        if right_tap_count == 1 and now - right_first_tap_time > DOUBLE_TAP_WINDOW:
            right_tap_count = 0

        # ── Hold tracking ─────────────────────────────────────────────────────
        if both_present:
            if hold_both_start is None:
                hold_both_start = now
            elapsed = now - hold_both_start
            if not hold_both_fired and elapsed >= SHORT_HOLD_TIME:
                last_gesture_time = fire(
                    "✋ SHORT HOLD: Both sensors!",
                    COLOR_SHORT_HOLD_BOTH, now)
                hold_both_fired = True
            if not hold_both_long and elapsed >= LONG_HOLD_TIME:
                last_gesture_time = fire(
                    "✋✋ LONG HOLD: Both sensors!",
                    COLOR_LONG_HOLD_BOTH, now)
                hold_both_long = True
        else:
            hold_both_start = None
            hold_both_fired = False
            hold_both_long  = False

        if left_present and not right_present:
            if hold_left_start is None:
                hold_left_start = now
            elapsed = now - hold_left_start
            if not hold_left_fired and elapsed >= SHORT_HOLD_TIME:
                last_gesture_time = fire(
                    "✋ SHORT HOLD: Left sensor!",
                    COLOR_SHORT_HOLD_LEFT, now)
                hold_left_fired = True
            if not hold_left_long and elapsed >= LONG_HOLD_TIME:
                last_gesture_time = fire(
                    "✋✋ LONG HOLD: Left sensor!",
                    COLOR_LONG_HOLD_LEFT, now)
                hold_left_long = True
        else:
            hold_left_start = None
            hold_left_fired = False
            hold_left_long  = False

        if right_present and not left_present:
            if hold_right_start is None:
                hold_right_start = now
            elapsed = now - hold_right_start
            if not hold_right_fired and elapsed >= SHORT_HOLD_TIME:
                last_gesture_time = fire(
                    "✋ SHORT HOLD: Right sensor!",
                    COLOR_SHORT_HOLD_RIGHT, now)
                hold_right_fired = True
            if not hold_right_long and elapsed >= LONG_HOLD_TIME:
                last_gesture_time = fire(
                    "✋✋ LONG HOLD: Right sensor!",
                    COLOR_LONG_HOLD_RIGHT, now)
                hold_right_long = True
        else:
            hold_right_start = None
            hold_right_fired = False
            hold_right_long  = False

        # ── Update entry tracking at end of every loop ────────────────────────
        left_was_absent  = not left_present
        right_was_absent = not right_present

        time.sleep(0.02)


if __name__ == "__main__":
    main()
