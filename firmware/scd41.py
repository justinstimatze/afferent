# Minimal SCD-41 (Sensirion SCD4x) driver for MicroPython over I2C.
#
# Command opcodes, CRC8 parameters, and the temp/RH scaling formulas are
# verified against Adafruit's CircuitPython SCD4X driver
# (github.com/adafruit/Adafruit_CircuitPython_SCD4X), which implements the
# Sensirion SCD4x datasheet. Only the read path used by this project's
# poller loop is ported: stop/start periodic measurement, data-ready poll,
# and read-measurement.

import time

_ADDR = 0x62
_STOP_PERIODIC = 0x3F86
_START_PERIODIC = 0x21B1
_READ_MEASUREMENT = 0xEC05
_DATA_READY = 0xE4B8


def _crc8(data):
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def _check_crc(buf):
    for i in range(0, len(buf), 3):
        word, crc = buf[i:i + 2], buf[i + 2]
        if _crc8(word) != crc:
            raise ValueError("SCD-41: CRC mismatch on I2C reply")


class SCD41:
    def __init__(self, i2c, addr=_ADDR):
        self.i2c = i2c
        self.addr = addr

    def _send_command(self, cmd, delay=0):
        self.i2c.writeto(self.addr, bytes([(cmd >> 8) & 0xFF, cmd & 0xFF]))
        if delay:
            time.sleep(delay)

    def stop_periodic_measurement(self):
        self._send_command(_STOP_PERIODIC, delay=0.5)

    def start_periodic_measurement(self):
        self._send_command(_START_PERIODIC)

    def data_ready(self):
        self._send_command(_DATA_READY, delay=0.001)
        buf = self.i2c.readfrom(self.addr, 3)
        _check_crc(buf)
        return not ((buf[0] & 0x07 == 0) and (buf[1] == 0))

    def read_measurement(self):
        self._send_command(_READ_MEASUREMENT, delay=0.001)
        buf = self.i2c.readfrom(self.addr, 9)
        _check_crc(buf)
        co2 = (buf[0] << 8) | buf[1]
        raw_temp = (buf[3] << 8) | buf[4]
        raw_rh = (buf[6] << 8) | buf[7]
        temp = -45 + 175 * (raw_temp / 65535)
        rh = 100 * (raw_rh / 65535)
        return co2, temp, rh
