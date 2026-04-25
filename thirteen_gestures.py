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
COLOR_HOLD_LEFT         = "\033[93m"       # Yellow
COLOR_HOLD_RIGHT        = "\033[94m"       # Blue
COLOR_HOLD_BOTH         = "\033[95m"       # Magenta
COLOR_APPROACH_LEFT     = "\033[96m"       # Cyan
COLOR_RETREAT_LEFT      = "\033[38;5;208m" # Orange
COLOR_APPROACH_RIGHT    = "\033[97m"       # White
COLOR_RETREAT_RIGHT     = "\033[38;5;172m" # Dark orange
COLOR_DUAL_APPROACH     = "\033[38;5;118m" # Lime
COLOR_DUAL_RETREAT      = "\033[38;5;51m"  # Teal
COLOR_PINCH_FROM_LEFT   = "\033[38;5;213m" # Pink
COLOR_PINCH_FROM_RIGHT  = "\033[38;5;141m" # Purple
RESET                   = "\033[0m"

# ── Tuning ────────────────────────────────────────────────────────────────────
PRESENT_MM        = 300
DOMINANCE_MM      = 40
SWIPE_TIMEOUT     = 1.5
HOLD_TIME         = 3.0
APPROACH_MM       = 80
RETREAT_MM        = 80
ZOOM_WINDOW       = 2.0
GESTURE_COOLDOWN  = 0.5
NO_READING        = 65535


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


class SensorState:
    """Tracks baseline and delta for a single sensor."""
    def __init__(self):
        self.baseline      = None
        self.baseline_time = None
        self.delta         = 0

    def update(self, dist, now):
        if dist == NO_READING:
            self.baseline      = None
            self.baseline_time = None
            self.delta         = 0
            return

        if self.baseline is None:
            self.baseline      = dist
            self.baseline_time = now
            self.delta         = 0
            return

        elapsed    = now - self.baseline_time
        self.delta = self.baseline - dist   # positive = closer, negative = farther

        if elapsed > ZOOM_WINDOW:
            self.reset_baseline(dist, now)

    def is_approaching(self):
        return self.delta >= APPROACH_MM

    def is_retreating(self):
        return self.delta <= -RETREAT_MM

    def reset_baseline(self, dist, now):
        self.baseline      = dist
        self.baseline_time = now
        self.delta         = 0


def fire(msg, color, last_gesture_time, now):
    """Print a gesture and return updated last_gesture_time."""
    print(f"\n  {color}{msg}{RESET}\n")
    return now


def main():
    print("Initialising sensors...")
    sensor_left, sensor_right = init_sensors()
    print("Both sensors ready.\n")

    swipe_stage      = 0
    swipe_dir        = None
    swipe_start_time = 0
    last_gesture_time = 0

    # Hold tracking
    hold_left_start  = None
    hold_right_start = None
    hold_both_start  = None
    hold_left_fired  = False
    hold_right_fired = False
    hold_both_fired  = False

    # Zoom state
    state_left  = SensorState()
    state_right = SensorState()

    zoom_left_approach_fired  = False
    zoom_left_retreat_fired   = False
    zoom_right_approach_fired = False
    zoom_right_retreat_fired  = False

    dual_both_approach_fired = False
    dual_both_retreat_fired  = False
    dual_pinch_fired         = False
    dual_spread_fired        = False

    print("--- Gesture Detection ---")
    print(f"Present: <{PRESENT_MM}mm  |  Dominance: {DOMINANCE_MM}mm  |  "
          f"Hold: {HOLD_TIME}s  |  Approach/Retreat: {APPROACH_MM}mm  |  "
          f"Cooldown: {GESTURE_COOLDOWN}s\n")

    while True:
        left  = read_one(sensor_left)
        right = read_one(sensor_right)

        left_present  = left  != NO_READING and left  < PRESENT_MM
        right_present = right != NO_READING and right < PRESENT_MM
        both_present  = left_present and right_present

        print(f"LEFT:{fmt(left)}  RIGHT:{fmt(right)}  [stage {swipe_stage} dir={swipe_dir}]")

        now      = time.monotonic()
        cooldown = (now - last_gesture_time) < GESTURE_COOLDOWN

        # ── Update sensor states always ───────────────────────────────────────
        state_left.update(left   if left_present  else NO_READING, now)
        state_right.update(right if right_present else NO_READING, now)

        # ── Reset fired flags when hands leave ────────────────────────────────
        if not left_present:
            zoom_left_approach_fired = False
            zoom_left_retreat_fired  = False
        if not right_present:
            zoom_right_approach_fired = False
            zoom_right_retreat_fired  = False
        if not both_present:
            dual_both_approach_fired = False
            dual_both_retreat_fired  = False
            dual_pinch_fired         = False
            dual_spread_fired        = False
        if not left_present and not right_present:
            swipe_stage = 0
            swipe_dir   = None

        # ── Skip all gesture detection during cooldown ────────────────────────
        if cooldown:
            time.sleep(0.02)
            continue

        # ── Single sensor approach / retreat ──────────────────────────────────
        if left_present and not right_present:
            if state_left.is_approaching() and not zoom_left_approach_fired:
                last_gesture_time = fire(
                    f"📲 APPROACH: Left sensor! ({state_left.delta}mm closer)",
                    COLOR_APPROACH_LEFT, last_gesture_time, now)
                zoom_left_approach_fired = True
                state_left.reset_baseline(left, now)

            elif state_left.is_retreating() and not zoom_left_retreat_fired:
                last_gesture_time = fire(
                    f"🔙 RETREAT: Left sensor! ({-state_left.delta}mm farther)",
                    COLOR_RETREAT_LEFT, last_gesture_time, now)
                zoom_left_retreat_fired = True
                state_left.reset_baseline(left, now)

        if right_present and not left_present:
            if state_right.is_approaching() and not zoom_right_approach_fired:
                last_gesture_time = fire(
                    f"📲 APPROACH: Right sensor! ({state_right.delta}mm closer)",
                    COLOR_APPROACH_RIGHT, last_gesture_time, now)
                zoom_right_approach_fired = True
                state_right.reset_baseline(right, now)

            elif state_right.is_retreating() and not zoom_right_retreat_fired:
                last_gesture_time = fire(
                    f"🔙 RETREAT: Right sensor! ({-state_right.delta}mm farther)",
                    COLOR_RETREAT_RIGHT, last_gesture_time, now)
                zoom_right_retreat_fired = True
                state_right.reset_baseline(right, now)

        # ── Dual sensor gestures ──────────────────────────────────────────────
        if both_present:
            l_app = state_left.is_approaching()
            l_ret = state_left.is_retreating()
            r_app = state_right.is_approaching()
            r_ret = state_right.is_retreating()

            if l_app and r_app and not dual_both_approach_fired:
                last_gesture_time = fire(
                    f"🤲 DUAL APPROACH: Both closer! "
                    f"(L:{state_left.delta}mm R:{state_right.delta}mm)",
                    COLOR_DUAL_APPROACH, last_gesture_time, now)
                dual_both_approach_fired = True
                state_left.reset_baseline(left, now)
                state_right.reset_baseline(right, now)

            elif l_ret and r_ret and not dual_both_retreat_fired:
                last_gesture_time = fire(
                    f"↔️  DUAL RETREAT: Both farther! "
                    f"(L:{-state_left.delta}mm R:{-state_right.delta}mm)",
                    COLOR_DUAL_RETREAT, last_gesture_time, now)
                dual_both_retreat_fired = True
                state_left.reset_baseline(left, now)
                state_right.reset_baseline(right, now)

            elif l_app and r_ret and not dual_pinch_fired:
                last_gesture_time = fire(
                    f"🤏 PINCH: Left closer + Right farther! "
                    f"(L:{state_left.delta}mm R:{-state_right.delta}mm)",
                    COLOR_PINCH_FROM_LEFT, last_gesture_time, now)
                dual_pinch_fired = True
                state_left.reset_baseline(left, now)
                state_right.reset_baseline(right, now)

            elif r_app and l_ret and not dual_spread_fired:
                last_gesture_time = fire(
                    f"🤏 PINCH: Right closer + Left farther! "
                    f"(R:{state_right.delta}mm L:{-state_left.delta}mm)",
                    COLOR_PINCH_FROM_RIGHT, last_gesture_time, now)
                dual_spread_fired = True
                state_left.reset_baseline(left, now)
                state_right.reset_baseline(right, now)

        # ── Hold tracking ─────────────────────────────────────────────────────
        if both_present:
            if hold_both_start is None:
                hold_both_start = now
            if not hold_both_fired and now - hold_both_start >= HOLD_TIME:
                last_gesture_time = fire(
                    "✋ HOLD: Both sensors!",
                    COLOR_HOLD_BOTH, last_gesture_time, now)
                hold_both_fired = True
        else:
            hold_both_start = None
            hold_both_fired = False

        if left_present and not right_present:
            if hold_left_start is None:
                hold_left_start = now
            if not hold_left_fired and now - hold_left_start >= HOLD_TIME:
                last_gesture_time = fire(
                    "✋ HOLD: Left sensor!",
                    COLOR_HOLD_LEFT, last_gesture_time, now)
                hold_left_fired = True
        else:
            hold_left_start = None
            hold_left_fired = False

        if right_present and not left_present:
            if hold_right_start is None:
                hold_right_start = now
            if not hold_right_fired and now - hold_right_start >= HOLD_TIME:
                last_gesture_time = fire(
                    "✋ HOLD: Right sensor!",
                    COLOR_HOLD_RIGHT, last_gesture_time, now)
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
                print(f"  >> Stage 1: LEFT dominant — watching for RIGHT "
                      f"(L={fmt(left)} R={fmt(right)})")

            elif right_present and (not left_present or right < left - DOMINANCE_MM):
                swipe_stage      = 1
                swipe_dir        = "RL"
                swipe_start_time = now
                print(f"  >> Stage 1: RIGHT dominant — watching for LEFT "
                      f"(L={fmt(left)} R={fmt(right)})")

        elif swipe_stage == 1:
            if now - swipe_start_time > SWIPE_TIMEOUT:
                print("  >> Timeout, resetting")
                swipe_stage = 0
                swipe_dir   = None

            elif swipe_dir == "LR":
                if right_present and (not left_present or right < left - DOMINANCE_MM):
                    last_gesture_time = fire(
                        "✨ SWIPE: Left to Right! ✨",
                        COLOR_SWIPE_LR, last_gesture_time, now)
                    swipe_stage = 0
                    swipe_dir   = None

            elif swipe_dir == "RL":
                if left_present and (not right_present or left < right - DOMINANCE_MM):
                    last_gesture_time = fire(
                        "✨ SWIPE: Right to Left! ✨",
                        COLOR_SWIPE_RL, last_gesture_time, now)
                    swipe_stage = 0
                    swipe_dir   = None

        time.sleep(0.02)


if __name__ == "__main__":
    main()
