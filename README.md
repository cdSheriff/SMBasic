# SMBasic
Flattening Adafruit's python SMBus & i2c libraries for raspberry pi (chasing ghosts)

**BACKGROUND**:
    _Hardware_
    duplicated Sensirion sensor (fixed i2c address)
    Bosch sensor
    duplicated TI multiplexer (different i2c address)
    RPi 4b (Broadcom BCM2711)

    _Problem_
    Using a bundle of Sensirion and Bosch peripherals through multiple TI multiplexers, the i2c bus would unpredictably
    lock up and cause bad things in the hardware. Adafruit uses layers of i2c bus classes for compatability reasons - 
    their code is meant to work on oodles of SoC's and SBC's running python, circuitpython, and micropython. But I only
    needed to fix the BCM2711/ RPi 4b implementation for my specific hardware project.

    _Solution_
    - Flatten the sensor/busio/board/smbus/mux/etc library onion into two layers: sensor and bus
    - Context manage SMbasic/SMMux: enter and exit for every poll (NOT COMPATIBLE WITH ALL SENSORS!!)
    - Mux channel locking is automatic when using SMMux: pass addr and channel, mux is locked for use
    - Add signal timeout to bus class, to crash out if the bus locks up

**Usage**
###########
"""
Example using direct Pi to peripheral connection (no multiplexer) and a MCP9600 thermocouple amp
"""
from smbasic import SMBasic

Class MCP9600:
    def __init__(self, bus, address = 0x67)
        self.bus = bus
        self.address = 0x67
        self._hot_junction_register = 0x00
        self._hot_junction_payload_len = 2

    @property
    def temperature(self):
        # write target register to peripheral
        self.bus.write_bytes(addr=self.address, buf=self._hot_junction_register)
        # read response from peripheral
        _data = self.bus.read_bytes(addr=self.address, number=self._hot_junction_payload_len)
        # convert bytes to value (from mfg datasheet)
        temperature = int.from_bytes((data[0], data[1]), byteorder='big', signed=True) / 16
        # return property
        return temperature

with SMBasic() as bus:
    mcp = MCP9600(bus)
    print(mcp.temperature)

###########
"""
Example using an MCP9600 thermocouple amp connected to RPi through multiplexer
"""

from smbasic import SMBasic

Class MCP9600:
    def __init__(self, bus, address = 0x67)
        self.bus = bus
        self.address = 0x67
        self._hot_junction_register = 0x00
        self._hot_junction_payload_len = 2

    @property
    def temperature(self):
        # write target register to peripheral
        self.bus.write_bytes(addr=self.address, buf=self._hot_junction_register)
        # read response from peripheral
        _data = self.bus.read_bytes(addr=self.address, number=self._hot_junction_payload_len)
        # convert bytes to value (from mfg datasheet)
        temperature = int.from_bytes((data[0], data[1]), byteorder='big', signed=True) / 16
        # return property
        return temperature

mux_addr = 0x70
channel = 1

with SMBasic(mux_addr, channel) as bus:
    mcp = MCP9600(bus)
    print(mcp.temperature)