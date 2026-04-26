import time
import board
import busio
import digitalio
import adafruit_vl53l1x

XSHUT_LEFT_PIN = board.D17
XSHUT_RIGHT_PIN = board.D27

i2c = busio.I2C(board.SCL, board.SDA)

# Hold both in reset
xshut_left = digitalio.DigitalInOut(XSHUT_LEFT_PIN)
xshut_left.direction = digitalio.Direction.OUTPUT
xshut_right = digitalio.DigitalInOut(XSHUT_RIGHT_PIN)
xshut_right.direction = digitalio.Direction.OUTPUT

xshut_left.value = False
xshut_right.value = False
time.sleep(0.5)

# Bring up LEFT only
xshut_left.value = True
time.sleep(0.5)

print("Connecting to left sensor...")
sensor = adafruit_vl53l1x.VL53L1X(i2c)
print("Connected. Setting distance mode...")
sensor.distance_mode = 1
print("Done! Sensor works.")
