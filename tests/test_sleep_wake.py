import threading

from main import Dispenserve
from memory import MemoryStore
from serial_link import Dispenser
from state import IDLE, SLEEP, AppState


def make_app(use_sensor=True):
    return Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False), use_sensor=use_sensor, result_seconds=0)


def test_board_connect_sleeps_until_someone_is_near():
    app = make_app()
    app.on_connection(True)
    app.tick(None)
    assert not app.awake and app.app_state.state == SLEEP
    app.on_sensor("near")
    app.tick(None)
    assert app.awake and app.app_state.state == IDLE
    app.on_sensor("away")
    app.tick(None)
    assert app.app_state.state == SLEEP


def test_losing_the_board_keeps_the_machine_awake():
    app = make_app()
    app.on_connection(True)
    app.on_connection(False)
    app.tick(None)
    assert app.awake and app.app_state.state == IDLE


def test_no_sensor_flag_ignores_sensor_lines():
    app = make_app(use_sensor=False)
    app.on_connection(True)
    app.on_sensor("away")
    app.tick(None)
    assert app.awake and app.app_state.state == IDLE


def test_scan_result_finishes_before_sleeping(person):
    app = make_app()
    app.result_seconds = 60
    app.complete_scan([person()])
    app.on_sensor("away")
    app.tick(None)
    assert app.app_state.state == "dispensed"  # the result stays up; sleep follows after it


class FakePort:
    """Stands in for the Arduino: answers 'd' with "ok" from another thread."""

    def __init__(self, link):
        self.link = link
        self.written = []

    def write(self, data):
        self.written.append(data)
        if data == b"d":
            threading.Timer(0.05, self.link._handle, args=("ok",)).start()


def test_serial_routes_sensor_lines_and_ok():
    seen = []
    link = Dispenser(enabled=True, on_sensor=seen.append)
    link._serial = FakePort(link)
    link._handle("near")
    link._handle("ready")
    link._handle("away")
    assert seen == ["near", "away"]
    assert link.dispense() is True
    link.show_refused()
    assert link._serial.written == [b"d", b"x"]


def test_serial_marks_jam_when_no_ok(monkeypatch):
    import serial_link

    monkeypatch.setattr(serial_link, "OK_TIMEOUT_S", 0.1)
    link = Dispenser(enabled=True)
    link._serial = type("Silent", (), {"write": lambda self, d: None})()
    assert link.dispense() is False
    assert link.jammed


def test_missing_sensor_keeps_machine_awake():
    app = make_app()
    app.on_connection(True)
    app.on_sensor("nosensor")
    app.tick(None)
    assert app.awake and app.app_state.state == IDLE
    app.on_sensor("away")  # ignored from now on
    assert app.awake
