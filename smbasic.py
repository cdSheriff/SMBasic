from fcntl import ioctl
from typing import Union
# from typing_extensions import Self

import time
import signal

try:
    import threading
except ImportError:
    threading = None

_I2C_DEVICE = 0x0703  # Use this device address
_I2C_TIMEOUT = 2  # seconds to wait before crashing out of i2c command
_MUX_UNLOCK_REGISTER = 0x00.to_bytes(1, 'big')  # sending no channel to mux unlocks the mux channel lock

class TimeoutException(Exception):
    def __init__(self, message: str = '') -> None:
        self.message = message
    def __str__(self):
        return repr(self.message)

class ContextManaged:
    """An object that automatically deinitializes hardware with a context manager."""

    def __enter__(self):
        print('context manager started')
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        print('context manager ending')
        self.deinit()

    # pylint: disable=no-self-use
    def deinit(self):
        """Free any hardware used by the object."""
        return

    # pylint: enable=no-self-use


class Lockable(ContextManaged):
    """An object that must be locked to prevent collisions on a microcontroller resource."""

    _locked = False

    def try_lock(self):
        """Attempt to grab the lock. Return True on success, False if the lock is already taken."""
        if self._locked:
            return False
        self._locked = True
        return True

    def unlock(self):
        """Release the lock so others may use the resource."""
        if self._locked:
            self._locked = False


# Create an interface that mimics the Python SMBus API.
class SMBasic(Lockable):
    """
    I2C interface that mimics the Python SMBus API but is implemented with
    pure Python calls to ioctl and direct /dev/i2c device access.
    """

    def __init__(self, bus: int = 1, mux: Union[int, None] = None, channel: int = None, verbose=False) -> None:
        """
        Create a new smbus instance
        Bus is an optional parameter that specifies the I2C bus number to use, default pins on RPi 4b use bus 1
        Using a bus besides 1 requires massaging boot config to add an overlay
        Bullseye method here: https://forums.raspberrypi.com/viewtopic.php?t=271200
        Bookworm method here: (NEED TO ADD GUIDE)

        :param int bus: i2c bus wired with peripherals (default 1)
        :param int mux: hex address of multiplexer (optional, default None)
        :param int channel: port of multiplexer i2c peripheral is attached to (optional, default None)
        :param bool verbose: should we STDOUT the i2c byte traffic?

        :return: None
        """

        assert (
            not ((mux is not None) ^ (channel is not None))
        )

        self.mux = mux
        self.channel = bytearray([1 << channel]) if channel is not None else None

        self.verbose = verbose

        self._device = None
        # if bus is not None:
        self.open(bus)

        if threading is not None:
            self._lock = threading.RLock()

    def __del__(self):
        """
        Clean up any resources used by the SMBus instance.
        """

        self.close()

    def __enter__(self):
        """
        Enter context manager for i2c bus

        :return: Self
        """

        # if mux+channel, lock channel
        if self.mux is not None and self.channel is not None:
            self.write_bytes(addr=self.mux, buf=self.channel, verbose=self.verbose)

            # wait until mux agrees channel is locked
            while ord(self.read_bytes(addr=self.mux, number=1)).to_bytes(1, 'big') != self.channel:

                # reattempt lock channel
                time.sleep(0.05)
                self.write_bytes(addr=self.mux, buf=self.channel, verbose=self.verbose)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit function, ensures resources are cleaned up.
        """

        # if mux+channel, unlock channel
        if self.mux is not None and self.channel is not None:
            # writing no channel resets the channel lock to open
            self.write_bytes(addr=0x70, buf=_MUX_UNLOCK_REGISTER, verbose=self.verbose)

            # wait until mux agrees channel is unlocked
            while ord(self.read_bytes(addr=self.mux, number=1)).to_bytes(1, 'big') != b'\x00':
                time.sleep(0.05)
                # reattempt unlock channel
                self.write_bytes(addr=self.mux, buf=b'\x00', verbose=self.verbose)

        self.close()
        return False  # Don't suppress exceptions.

    def open(self, bus):
        """
        Open the smbus interface on the specified bus
        """
        # Close the device if it's already open.
        if self._device is not None:
            self.close()
        # Try to open the file for the specified bus.  Must turn off buffering
        # or else Python 3 fails (see: https://bugs.python.org/issue20074)
        self._device = open(f"/dev/i2c-{bus}", "r+b", buffering=0)


    def close(self):
        """Close the smbus connection.  You cannot make any other function
        calls on the bus unless open is called!"""
        if self._device is not None:
            self._device.close()
            self._device = None

    def _select_device(self, addr, verbose = False):
        """Set the address of the device to communicate with on the I2C bus."""
        if verbose is True:
            print('selecting device %s' % hex(addr))
        ioctl(self._device.fileno(), _I2C_DEVICE, addr & 0x7F)

    def read_bytes(self, addr, number) -> bytearray:
        """
        read specified number of bytes off the bus
        gotta read your device datasheet to nail the correct payload bytes length

        :param addr: hex or int address of target i2c peripheral
        :param number: expected length of bytes payload

        :return: bytearray of payload if successful, empty bytearray of correct length if not successful
        """
        assert (
            self._device is not None
        ), "Bus must be opened before operations are made against it!"


        self._select_device(addr, verbose=self.verbose)

        def handle_timeout(signum, frame):
            raise TimeoutException()

        signal.signal(signal.SIGALRM, handle_timeout)
        signal.alarm(_I2C_TIMEOUT)

        try:
            result = self._device.read(number)

            if self.verbose is True:
                print('read bytes %s' % result)

            return result

        except TimeoutException:
            print('failed read bytes - addr: %s, mux: %s, channel: %s' % (addr, self.mux, self.channel))
            # self.health_down(_state, 'trouble')
        except OSError as e:
            print('%s %s likely I/O Error during read bytes: %s' % (self.mux, self.channel, e))
        finally:
            signal.alarm(0)

        return bytearray(number)


    def write_bytes(self, addr, buf, verbose = False):
        """Write many bytes to the specified device. buf is a bytearray"""
        assert (
            self._device is not None
        ), "Bus must be opened before operations are made against it!"
        self._select_device(addr, verbose)
        if verbose is True:
            print('writing bytes %s' % buf)

        def handle_timeout(signum, frame):
            raise TimeoutException()

        signal.signal(signal.SIGALRM, handle_timeout)
        signal.alarm(_I2C_TIMEOUT)

        try:
            self._device.write(buf)
        except TimeoutException:
            print('failed write bytes - addr: %s, mux: %s, channel: %s' % (addr, self.mux, self.channel))
            # self.health_down(_state, 'trouble')
        except OSError as e:
            print('%s %s likely I/O Error during write bytes: %s' % (self.mux, self.channel, e))
        finally:
            signal.alarm(0)