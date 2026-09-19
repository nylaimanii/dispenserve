"""Serial link to the Arduino dispenser. Missing hardware is logged, never fatal.

One background thread owns the port: it connects (and reconnects if the board is
unplugged), reads every line, and routes them:
    "ok"            -> wakes up the dispense() that's waiting for it
    "near" / "away" -> on_sensor callback (ultrasonic presence)
    "nosensor"      -> on_sensor callback (the sensor never echoed at boot)
    "ready"         -> the board (re)booted
"""

import glob
import logging
import threading
import time

log = logging.getLogger("dispenserve.serial")

PORT_PATTERNS = ["/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*"]
BAUD = 9600
RESET_WAIT_S = 2.0  # opening the port resets the uno
OK_TIMEOUT_S = 8.0  # a dispense takes ~4.9s (sweeps at 1 degree / 10ms)
RECONNECT_EVERY_S = 3.0
SENSOR_LINES = ("near", "away", "nosensor")


def find_port():
    for pattern in PORT_PATTERNS:
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    return None


class Dispenser:
    """Sends 'd' and waits for "ok"; sends 'x' for the red LED. Reports sensor lines.

    on_sensor(line): called with "near" / "away" from the reader thread.
    on_connection(connected): called when the board connects or goes away.
    """

    def __init__(self, enabled=True, on_sensor=None, on_connection=None):
        self.enabled = enabled
        self.on_sensor = on_sensor
        self.on_connection = on_connection
        self.jammed = False  # last dispense got no "ok"
        self._serial = None
        self._write_lock = threading.Lock()
        self._dispense_lock = threading.Lock()
        self._ok = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    @property
    def connected(self):
        return self._serial is not None

    def start(self):
        if not self.enabled:
            log.info("serial disabled (--no-serial)")
            return
        self._thread = threading.Thread(target=self._run, name="serial-reader", daemon=True)
        self._thread.start()

    def _open(self):
        port = find_port()
        if port is None:
            return None
        import serial  # imported lazily so the rest of the app runs without pyserial

        try:
            conn = serial.Serial(port, BAUD, timeout=0.5)
        except (OSError, serial.SerialException) as e:
            log.warning("could not open %s: %s", port, e)
            return None
        log.info("arduino connected on %s", port)
        return conn

    def _run(self):
        warned = False
        while not self._stop.is_set():
            conn = self._open()
            if conn is None:
                if not warned:
                    log.warning("no arduino found (%s); running without dispenser", ", ".join(PORT_PATTERNS))
                    warned = True
                self._stop.wait(RECONNECT_EVERY_S)
                continue
            warned = False
            self._serial = conn
            self._notify_connection(True)
            try:
                while not self._stop.is_set():
                    line = conn.readline().decode(errors="replace").strip()
                    if line:
                        self._handle(line)
            except Exception as e:
                if not self._stop.is_set():
                    log.warning("arduino disconnected: %s", e)
            finally:
                self._serial = None
                try:
                    conn.close()
                except Exception:
                    pass
                self._notify_connection(False)

    def _handle(self, line):
        if line == "ok":
            self._ok.set()
        elif line in SENSOR_LINES:
            if self.on_sensor is not None:
                self.on_sensor(line)
        elif line == "ready":
            log.info("arduino ready")
        else:
            log.debug("arduino: %s", line)

    def _notify_connection(self, connected):
        if self.on_connection is not None:
            try:
                self.on_connection(connected)
            except Exception:
                log.exception("connection callback failed")

    def _write(self, data):
        conn = self._serial
        if conn is None:
            return False
        with self._write_lock:
            try:
                conn.write(data)
                return True
            except Exception as e:
                log.warning("serial write failed: %s", e)
                return False

    def dispense(self):
        """Returns True only if the Arduino replied "ok" within the timeout."""
        if not self.enabled:
            log.info("dispense (serial disabled, not sent)")
            return False
        with self._dispense_lock:
            if self._serial is None:
                log.warning("dispense requested but no arduino connected")
                return False
            self._ok.clear()
            if not self._write(b"d"):
                return False
            if self._ok.wait(OK_TIMEOUT_S):
                self.jammed = False
                return True
            self.jammed = True
            log.warning("arduino did not reply ok within %.0fs (jam or power problem?)", OK_TIMEOUT_S)
            return False

    def show_refused(self):
        """Red LED for 3s. Fire and forget."""
        if self.enabled:
            self._write(b"x")

    def close(self):
        self._stop.set()
        conn = self._serial
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
