import time
import board
import busio
import digitalio
import adafruit_vl53l1x

# ── GPIO pins wired to each sensor's XSHUT ──────────────────────────────────
XSHUT_LEFT_PIN  = board.D17
XSHUT_RIGHT_PIN = board.D27

# ── Addresses ────────────────────────────────────────────────────────────────
ADDR_LEFT  = 0x29   # default — left sensor keeps it
ADDR_RIGHT = 0x30   # right sensor gets reassigned at boot

# ── Tuning ───────────────────────────────────────────────────────────────────
PRESENT_MM    = 300
DOMINANCE_MM  = 40
SWIPE_TIMEOUT = 1.5
NO_READING    = 65535


def make_xshut(pin):
    x = digitalio.DigitalInOut(pin)
    x.direction = digitalio.Direction.OUTPUT
    return x


def init_sensors(i2c):
    """
    Boot sensors one at a time so we can give the right sensor a new address.
    Both XSHUT lines must be wired for this to work.
    """
    xshut_left  = make_xshut(XSHUT_LEFT_PIN)
    xshut_right = make_xshut(XSHUT_RIGHT_PIN)

    # Hold both in reset
    xshut_left.value  = False
    xshut_right.value = False
    time.sleep(0.01)

    # Bring up LEFT first — it keeps the default address 0x29
    xshut_left.value = True
    time.sleep(0.01)
    sensor_left = adafruit_vl53l1x.VL53L1X(i2c)          # 0x29

    # Bring up RIGHT and immediately move it to 0x30
    xshut_right.value = True
    time.sleep(0.01)
    sensor_right = adafruit_vl53l1x.VL53L1X(i2c)         # still 0x29 for now
    sensor_right.set_address(ADDR_RIGHT)                  # now 0x30

    return sensor_left, sensor_right


def configure(sensor):
    sensor.distance_mode = 1    # short mode, good up to ~130 cm
    sensor.timing_budget = 50   # ms — faster than before since no ROI switching
    sensor.start_ranging()


def read_sensor(sensor):
    """Non-blocking read; returns distance in mm or NO_READING."""
    if not sensor.data_ready:
        return NO_READING
    dist = sensor.distance
    sensor.clear_interrupt()
    return round(dist * 10) if dist is not None else NO_READING


def fmt(v):
    return f"{v:4d}mm" if v != NO_READING else "  --  "


def main():
    i2c = busio.I2C(board.SCL, board.SDA)

    print("Initialising sensors…")
    sensor_left, sensor_right = init_sensors(i2c)
    configure(sensor_left)
    configure(sensor_right)
    print("Sensors ready.\n")

    swipe_stage      = 0
    swipe_start_time = 0

    print("--- Left to Right Swipe Detection (dual sensor) ---")
    print(f"Dominance margin: {DOMINANCE_MM} mm\n")

    while True:
        left  = read_sensor(sensor_left)
        right = read_sensor(sensor_right)

        print(f"LEFT:{fmt(left)}  RIGHT:{fmt(right)}  [stage {swipe_stage}]")

        now = time.monotonic()

        if swipe_stage == 0:
            left_present  = left  != NO_READING and left  < PRESENT_MM
            right_present = right != NO_READING and right < PRESENT_MM

            if left_present and (not right_present or left < right - DOMINANCE_MM):
                swipe_stage      = 1
                swipe_start_time = now
                print(f"  >> Stage 1: LEFT dominant (L={fmt(left)} R={fmt(right)})")

        elif swipe_stage == 1:
            if now - swipe_start_time > SWIPE_TIMEOUT:
                print("  >> Timeout, resetting")
                swipe_stage = 0
            else:
                right_present = right != NO_READING and right < PRESENT_MM
                left_present  = left  != NO_READING and left  < PRESENT_MM

                if right_present and (not left_present or right < left - DOMINANCE_MM):
                    print("\n  ✨ SWIPE DETECTED: Left to Right! ✨\n")
                    swipe_stage = 0

        time.sleep(0.02)   # ~50 Hz loop; sensors update at their own timing_budget rate


if __name__ == "__main__":
    main()
