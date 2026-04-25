import time
import board
import busio
import digitalio
import adafruit_vl53l1x

# ── XSHUT pins ────────────────────────────────────────────────────────────────
XSHUT_LEFT_PIN  = board.D17
XSHUT_RIGHT_PIN = board.D27

# ── Tuning ────────────────────────────────────────────────────────────────────
PRESENT_MM    = 300
DOMINANCE_MM  = 40
SWIPE_TIMEOUT = 1.5
NO_READING    = 65535


def make_xshut(pin):
    x = digitalio.DigitalInOut(pin)
    x.direction = digitalio.Direction.OUTPUT
    return x


def init_sensors():
    xshut_left  = make_xshut(XSHUT_LEFT_PIN)
    xshut_right = make_xshut(XSHUT_RIGHT_PIN)

    # Kill both
    xshut_left.value  = False
    xshut_right.value = False
    time.sleep(0.5)

    # Bring up left alone
    xshut_left.value = True
    time.sleep(0.5)
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor_left = adafruit_vl53l1x.VL53L1X(i2c)
    sensor_left.distance_mode = 1
    sensor_left.timing_budget = 50

    # Move left to 0x30
    sensor_left.set_address(0x30)
    time.sleep(0.5)

    # Deinit and reinit I2C bus completely
    i2c.deinit()
    time.sleep(0.5)
    i2c = busio.I2C(board.SCL, board.SDA)

    # Reconnect to left at new address
    sensor_left = adafruit_vl53l1x.VL53L1X(i2c, address=0x30)
    sensor_left.distance_mode = 1
    sensor_left.timing_budget = 50
    print("Left sensor ready at 0x30")

    # Now bring up right
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

    # swipe_dir tracks which direction we are detecting:
    # 0 = idle
    # 1 = L→R in progress (left triggered first)
    # 2 = R→L in progress (right triggered first)
    swipe_stage      = 0
    swipe_dir        = None
    swipe_start_time = 0

    print("--- Swipe Detection (Left↔Right) ---")
    print(f"Dominance margin: {DOMINANCE_MM}mm\n")

    while True:
        left  = read_one(sensor_left)
        right = read_one(sensor_right)

        left_present  = left  != NO_READING and left  < PRESENT_MM
        right_present = right != NO_READING and right < PRESENT_MM

        print(f"LEFT:{fmt(left)}  RIGHT:{fmt(right)}  [stage {swipe_stage} dir={swipe_dir}]")

        now = time.monotonic()

        if swipe_stage == 0:
            # Left triggered first → potential L→R swipe
            if left_present and (not right_present or left < right - DOMINANCE_MM):
                swipe_stage      = 1
                swipe_dir        = "LR"
                swipe_start_time = now
                print(f"  >> Stage 1: LEFT dominant — watching for RIGHT (L={fmt(left)} R={fmt(right)})")

            # Right triggered first → potential R→L swipe
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
                # Waiting for right side to become dominant
                if right_present and (not left_present or right < left - DOMINANCE_MM):
                    print("\n  ✨ SWIPE DETECTED: Left to Right! ✨\n")
                    swipe_stage = 0
                    swipe_dir   = None

            elif swipe_dir == "RL":
                # Waiting for left side to become dominant
                if left_present and (not right_present or left < right - DOMINANCE_MM):
                    print("\n  ✨ SWIPE DETECTED: Right to Left! ✨\n")
                    swipe_stage = 0
                    swipe_dir   = None

        time.sleep(0.02)


if __name__ == "__main__":
    main()
