import time
import board
import busio
import digitalio
import adafruit_vl53l1x

# ── XSHUT pins ────────────────────────────────────────────────────────────────
XSHUT_LEFT_PIN  = board.D17
XSHUT_RIGHT_PIN = board.D27

# ── Colors ────────────────────────────────────────────────────────────────────
COLOR_SWIPE_LR         = "\033[92m"       # Green
COLOR_SWIPE_RL         = "\033[91m"       # Red
COLOR_HOLD_LEFT        = "\033[93m"       # Yellow
COLOR_HOLD_RIGHT       = "\033[94m"       # Blue
COLOR_HOLD_BOTH        = "\033[95m"       # Magenta
COLOR_APPROACH_LEFT    = "\033[96m"       # Cyan
COLOR_RETREAT_LEFT     = "\033[38;5;208m" # Orange
COLOR_APPROACH_RIGHT   = "\033[97m"       # White
COLOR_RETREAT_RIGHT    = "\033[38;5;172m" # Dark orange
COLOR_DUAL_APPROACH    = "\033[38;5;118m" # Lime
COLOR_DUAL_RETREAT     = "\033[38;5;51m"  # Teal
COLOR_PINCH_FROM_LEFT  = "\033[38;5;213m" # Pink
COLOR_PINCH_FROM_RIGHT = "\033[38;5;141m" # Purple
RESET                  = "\033[0m"

# ── Tuning ────────────────────────────────────────────────────────────────────
PRESENT_MM       = 300
DOMINANCE_MM     = 40
SWIPE_TIMEOUT    = 1.5
HOLD_TIME        = 3.0
APPROACH_MM      = 80
RETREAT_MM       = 80
ZOOM_WINDOW      = 2.0
GESTURE_COOLDOWN = 0.5
NO_READING       = 65535


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
        self.delta = self.baseline - dist

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


def fire(msg, color, now):
    print(f"\n  {color}{msg}{RESET}\n")
    return now


def main():
    print("Initialising sensors...")
    sensor_left, sensor_right = init_sensors()
    print("Both sensors ready.\n")

    sw
