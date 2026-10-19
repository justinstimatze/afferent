# Runs automatically on boot. Reads the SCD-41 over the STEMMA QT I2C bus
# (GPIO19 SCL / GPIO22 SDA -- the QT Py ESP32 Pico's second I2C bus, per
# Adafruit's pinout guide; the board's other SCL/SDA pins are NOT this bus)
# and prints one line per reading to USB serial, matching the format the
# station poller expects (see ambient-context-design.md).

import time
import machine
from machine import Pin, I2C
from scd41 import SCD41

_MAX_CONSECUTIVE_FAULTS = 5

i2c = I2C(1, scl=Pin(19), sda=Pin(22), freq=100000)
sensor = SCD41(i2c)

sensor.stop_periodic_measurement()
sensor.start_periodic_measurement()

consecutive_faults = 0
while True:
    try:
        if sensor.data_ready():
            co2, temp, rh = sensor.read_measurement()
            print("co2={},temp={:.1f},rh={:.0f}".format(co2, temp, rh))
        consecutive_faults = 0
    except (OSError, ValueError) as e:
        # An uncaught fault would drop the board to the REPL until it is
        # power-cycled. Print a line instead (the poller ignores anything
        # that does not match co2=..., so it is not mistaken for a reading)
        # and keep going; reset the board only if faults persist.
        consecutive_faults += 1
        print("scd41 fault ({}/{}): {}".format(
            consecutive_faults, _MAX_CONSECUTIVE_FAULTS, e))
        if consecutive_faults >= _MAX_CONSECUTIVE_FAULTS:
            print("too many consecutive faults, resetting")
            machine.reset()
    time.sleep(1)
