import board
#import busio
import adafruit_vl53l1x

def check_sensor():
    print("--- VL53L1X Hardware Scan ---")

    # 1. Check I2C Bus
    try:
        i2c = board.I2C()
        print("✅ I2C Bus initialized successfully.")
    except Exception as e:
        print(f"❌ Failed to initialize I2C: {e}")
        print("Tip: Ensure I2C is enabled in 'sudo raspi-config'")
        return

    # 2. Scan for Device Address (0x29)
    i2c.try_lock()
    addresses = i2c.scan()
    i2c.unlock()

    if 0x29 in addresses:
        print("✅ Sensor found at address 0x29.")
    else:
        print("❌ Sensor NOT found at 0x29.")
        print(f"Devices seen on bus: {[hex(a) for a in addresses]}")
        return

    # 3. Try to initialize the Driver
    try:
        vl53 = adafruit_vl53l1x.VL53L1X(i2c)
        print(f"✅ Driver loaded. Model ID: {vl53.model_info}")

        # 4. Perform a test read
        vl53.distance_mode = 1  # Short mode for desk test
        vl53.start_ranging()

        print("Taking test reading...")
        import time
        for i in range(100):
            timeout = time.monotonic() + 5.0
            time.sleep(0.5)
            while not vl53.data_ready:
                if time.monotonic() > timeout:
                    print(f"Sample {i} Timeout (No data ready)")
                    break
                time.sleep(0.01)
            if vl53.data_ready:
                dist = vl53.distance
                if dist is not None: 
                    print(f"✅ Test Reading: {vl53.distance * 10:.1f} mm")
                else:
                    print("⚠️ Driver connected, but no distance data received.")
                vl53.clear_interrupt()
            time.sleep(0.1)
        vl53.stop_ranging()


    except Exception as e:
        print(f"❌ Driver error: {e}")


if __name__ == "__main__":
    check_sensor()
