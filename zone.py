import time
import board
import adafruit_vl53l1x
import struct

VL53L1X_ADDR = 0x29
ROI_CENTER_REG = 0x0007
ROI_SIZE_REG = 0x0008

ROI_CENTERS = [
   [199, 175, 151],
   [127, 199, 71],
   [79, 55, 31],
]

ZONE_NAMES = [
   ["TL", "TC", "TR"],
   ["ML", "MC", "MR"],
   ["BL", "BC", "BR"],
]

def set_roi(i2c, center, width=12, height=12):
    size_byte = ((height - 1) << 4) | (width -1)
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", ROI_CENTER_REG) + bytes([center]))
    i2c.writeto(VL53L1X_ADDR, struct.pack(">H", ROI_SIZE_REG) + bytes([size_byte]))

def main():
    i2c = board.I2C()
    vl53 = adafruit_vl53l1x.VL53L1X(i2c)
    vl53.distance_mode = 1
    vl53.timing_budget = 100
    vl53.start_ranging()

    print("--- Full 3x3 Grid Debugging ---")
    while True:
       grid = []
       for r, row in enumerate(ROI_CENTERS):
          grid_row = []
          for c, center in enumerate(row):
             set_roi(i2c, center, width=4, height=4)
             vl53.clear_interrupt()
             time.sleep(0.1)
        
             timeout = time.monotonic() + 0.5
             while not vl53.data_ready:
                if time.monotonic() > timeout:
                   break
                time.sleep(0.005)
             dist = vl53.distance
             vl53.clear_interrupt()
             val = f"{round(dist * 10)} mm" if dist else 65535
             grid_row.append(val)
          grid.append(grid_row)

       print("---- 3x3 Grid (mm) ----")
       for r, g_row in enumerate(grid):
          row_str = ""
          for c, v in enumerate(g_row):
             label = ZONE_NAMES[r][c]
             cell = "----" if v == 65535 else str(v)
             row_str += f"{label}:{cell:<6}"
          print(row_str)
       print()
if __name__ == "__main__":
    main()
