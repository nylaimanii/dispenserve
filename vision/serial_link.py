"""Serial link to the Arduino dispenser. Missing hardware is logged, never fatal."""

import glob
import logging
import threading
import time

log = logging.getLogger("dispenserve.serial")

PORT_PATTERNS = ["/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*"]
BAUD = 9600
RESET_WAIT_S = 2.0  # opening the port resets the uno
OK_TIMEOUT_S = 5.0


def find_port():
    for pattern in PORT_PATTERNS:
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    return None


class Dispenser:
    """Sends 'd' and waits for "ok". Reconnects lazily if the board was unplugged."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self._serial = None
        self._lock = threading.Lock()

    @property
    def connected(self):
        return self._serial is not None

    def _connect(self):
        port = find_port()
        if port is None:
            return False
        import serial  # imported lazily so the rest of the app runs without pyserial

        try:
            conn = serial.Serial(port, BAUD, timeout=OK_TIMEOUT_S)
            time.sleep(RESET_WAIT_S)
            conn.reset_input_buffer()  # drop the "ready" boot line
        except (OSError, serial.SerialException) as e:
            log.warning("could not open %s: %s", port, e)
            return False
        self._serial = conn
        log.info("arduino connected on %s", port)
        return True

    def connect(self):
        if not self.enabled:
            log.info("serial disabled (--no-serial)")
            return False
        with self._lock:
            if self._serial is None and not self._connect():
                log.warning("no arduino found (%s); running without dispenser", ", ".join(PORT_PATTERNS))
            return self._serial is not None

    def dispense(self):
        """Returns True only if the Arduino replied "ok" within 5s."""
        if not self.enabled:
            log.info("dispense (serial disabled, not sent)")
            return False
        with self._lock:
            if self._serial is None and not self._connect():
                log.warning("dispense requested but no arduino connected")
                return False
            try:
                self._serial.reset_input_buffer()
                self._serial.write(b"d")
                deadline = time.monotonic() + OK_TIMEOUT_S
                while time.monotonic() < deadline:
                    line = self._serial.readline().decode(errors="replace").strip()
                    if line == "ok":
                        return True
                log.warning("arduino did not reply ok within %.0fs", OK_TIMEOUT_S)
                return False
            except Exception as e:
                log.warning("serial error, will reconnect on next dispense: %s", e)
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
                return False

    def close(self):
        with self._lock:
            if self._serial is not None:
                self._serial.close()
                self._serial = None
