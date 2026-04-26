import time
import board
import busio
import digitalio
import adafruit_vl53l1x

XSHUT_LEFT_PIN  = board.D27
XSHUT_RIGHT_PIN = board.D17

ADDR_LEFT  = 0x30
ADDR_RIGHT = 0x29

NO_READING = 65535

def make_xshut(pin):
    x = digitalio.DigitalInOut(pin)
    x.direction = digitalio.Direction.OUTPUT
    return x

def init_sensors(i2c):
    xshut_left  = make_xshut(XSHUT_LEFT_PIN)
    xshut_right = make_xshut(XSHUT_RIGHT_PIN)

    xshut_left.value  = False
    xshut_right.value = False
    time.sleep(0.1)

    xshut_left.value = True
    time.sleep(0.5)
    sensor_left = adafruit_vl53l1x.VL53L1X(i2c)
    sensor_left.distance_mode = 1
    sensor_left.timing_budget = 50
    sensor_left.start_ranging()
    print("Left sensor ready")

    xshut_right.value = True
    time.sleep(0.5)
    sensor_right = adafruit_vl53l1x.VL53L1X(i2c)
    sensor_right.set_address(ADDR_RIGHT)
    time.sleep(0.1)
    sensor_right = adafruit_vl53l1x.VL53L1X(i2c, address=ADDR_RIGHT)
    sensor_right.distance_mode = 1
    sensor_right.timing_budget = 50
    sensor_right.start_ranging()
    print("Right sensor ready")

    return sensor_left, sensor_right

def read_sensor(sensor):
    try:
        if not sensor.data_ready:
            return NO_READING
        dist = sensor.distance
        sensor.clear_interrupt()
        return round(dist * 10) if dist is not None else NO_READING
    except OSError:
        return NO_READING

def fmt(v):
    return f"{v:4d}mm" if v != NO_READING else "  --  "

def main():
    i2c = busio.I2C(board.SCL, board.SDA)

    print("Initialising sensors...")
    sensor_left, sensor_right = init_sensors(i2c)
    print("Both sensors ready.\n")

    while True:
        try:
            left  = read_sensor(sensor_left)
            right = read_sensor(sensor_right)

            print(f"LEFT:{fmt(left)}  RIGHT:{fmt(right)}")

        except OSError as e:
            print(f"I2C error: {e}, retrying...")
            time.sleep(0.1)
            continue

        time.sleep(0.05)

if __name__ == "__main__":
    main()
