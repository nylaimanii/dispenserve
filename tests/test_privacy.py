"""The core privacy promise: face vectors never touch disk and never leave the machine.

Runs a full fake session (scans, matches, dispenses, HTTP polling, clear) and checks:
- no file was opened for writing and no directory created, anywhere (Python audit hooks)
- no new files appeared in the repo or the temp directories
- no network connection went anywhere except this machine
- nothing the HTTP API returns contains a vector or a similarity score
- every telemetry event is exactly {machine_id, bay, event, ts}, with nothing per-person
"""

import datetime
import json
import os
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

from main import Dispenserve, FakeCrowd
from memory import MemoryStore
from serial_link import Dispenser
from server import start_server
from state import AppState
from sinks.base import CallbackSink
from telemetry import EVENTS, FIELDS, Telemetry

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "__pycache__"}
TEMP_DIRS = {Path(tempfile.gettempdir()), Path("/tmp")}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

_recording = threading.Event()
_events = []


def _audit(event, args):
    if not _recording.is_set():
        return
    if event == "open":
        path, mode, flags = args
        if isinstance(path, int):
            return
        wants_write = any(c in mode for c in "wax+") if isinstance(mode, str) else bool(flags & WRITE_FLAGS)
        if wants_write:
            _events.append(("write", str(path)))
    elif event in ("os.mkdir", "os.rename", "os.link", "os.symlink", "shutil.copyfile"):
        _events.append((event, str(args[0])))
    elif event in ("socket.connect", "socket.sendto"):
        address = args[1] if event == "socket.connect" else args[-1]
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in LOOPBACK:
            _events.append((event, host))


sys.addaudithook(_audit)  # audit hooks can't be removed; _recording gates it to the session


def snapshot_repo():
    files = set()
    for root, dirs, names in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        files.update(os.path.join(root, n) for n in names)
    return files


def snapshot_temp():
    entries = set()
    for d in TEMP_DIRS:
        try:
            entries.update(str(p) for p in d.iterdir())
        except OSError:
            pass
    return entries


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as res:
        return res.read().decode()


def run_session():
    """Returns (app, http responses, outcomes, telemetry events that would have left the machine)."""
    outgoing = []
    telemetry = Telemetry("machine-a", sinks=[CallbackSink(outgoing.extend)], batch_size=5, flush_interval=0.05)
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False), telemetry=telemetry, result_seconds=0)
    server = start_server(app, host="127.0.0.1", port=0)
    port = server.server_address[1]
    responses, outcomes = [], []
    try:
        crowd = FakeCrowd(people=4, seed=7)
        for _ in range(12):  # 4 people, so some repeats → already_served
            outcomes.append(app.complete_scan(crowd.hold()).outcome)
            for path in ("/state", "/stats", "/metrics"):
                responses.append(get(port, path))
        app.force_dispense()
        app.restock()
        app.clear_memory()
        responses.append(get(port, "/stats"))
    finally:
        server.shutdown()
        server.server_close()
        telemetry.close()
    return app, responses, outcomes, outgoing


def test_full_session_writes_nothing_and_sends_nothing():
    repo_before, temp_before = snapshot_repo(), snapshot_temp()
    _events.clear()
    _recording.set()
    try:
        app, responses, outcomes, _ = run_session()
    finally:
        _recording.clear()

    assert _events == [], f"disk or network activity during the session: {_events}"
    assert snapshot_repo() - repo_before == set()
    assert snapshot_temp() - temp_before == set()

    # the session really exercised both outcomes: 4 new people, 8 repeats, plus one forced dispense
    assert outcomes.count("dispense") == 4 and outcomes.count("already_served") == 8
    assert app.app_state.stats_json()["dispensed_today"] == 5
    assert len(app.store) == 0  # cleared at the end


def test_api_responses_contain_no_vectors_or_scores():
    _, responses, _, _ = run_session()
    for body in responses:
        payload = json.loads(body)
        _assert_no_face_data(payload)


def _assert_no_face_data(value, path="$"):
    if isinstance(value, dict):
        for key, v in value.items():
            assert "score" not in key.lower() and "embedding" not in key.lower() and "vector" not in key.lower(), path + "." + key
            _assert_no_face_data(v, f"{path}.{key}")
    elif isinstance(value, list):
        assert not (len(value) > 16 and all(isinstance(x, (int, float)) for x in value)), f"{path} looks like a vector"
        for i, v in enumerate(value):
            _assert_no_face_data(v, f"{path}[{i}]")


def test_telemetry_is_anonymous_counts_only():
    _, _, outcomes, outgoing = run_session()
    # every event in the session left as telemetry: 4 new + 1 forced dispense, 8 repeats, 1 restock
    assert [e["event"] for e in outgoing].count("dispensed") == 5
    assert [e["event"] for e in outgoing].count("already_served") == 8
    assert [e["event"] for e in outgoing].count("restocked") == 1
    for event in outgoing:
        assert tuple(event) == FIELDS  # exactly these keys, nothing else
        assert event["machine_id"] == "machine-a"
        assert event["bay"] == "Kit Kat"
        assert event["event"] in EVENTS
        datetime.datetime.fromisoformat(event["ts"])
        assert all(isinstance(v, str) and len(v) <= 64 for v in event.values())
    # nothing distinguishes one person's events from another's
    assert len({json.dumps({k: v for k, v in e.items() if k != "ts"}) for e in outgoing}) == 3


def test_every_integration_together_sends_no_face_data():
    """A full session with every integration on (fake transports), under the audit hooks."""
    import base64

    import insights as insights_mod
    import ledger as ledger_mod
    import voice as voice_mod
    from sinks.snowflake_sink import SnowflakeSink

    outgoing = []  # every payload that would leave the laptop, as text

    class Capture:
        def cursor(self):
            return self

        def executemany(self, sql, rows):
            outgoing.append(json.dumps(rows))

        def close(self):
            pass

        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def rpc(method, params):
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": ledger_mod.b58encode(bytes(32))}}
        outgoing.append(base64.b64decode(params[0]).decode("utf-8", errors="ignore"))
        return "sig"

    def gemini(url, headers, body):
        outgoing.append(json.dumps(body))
        return {"candidates": [{"content": {"parts": [{"text": "Restock soon. Kit Kat is going fast."}]}}]}

    class Proc:
        def poll(self):
            return 0

        def terminate(self):
            pass

    spoken = []
    from sinks.tiger_sink import TigerSink

    sinks = [TigerSink("unused", connect=Capture), SnowflakeSink({"account": "a", "table": "EVENTS"}, connect=Capture)]
    telemetry = Telemetry("machine-a", sinks=sinks, batch_size=5, flush_interval=0.05)
    ledger = ledger_mod.SolanaLedger("machine-a", ledger_mod.Keypair.generate(), rpc=rpc)
    voice = voice_mod.Voice(api_key=None, player=lambda args: spoken.append(args) or Proc())
    voice._has_say, voice._has_afplay = True, False
    state = AppState("Kit Kat", 24)
    app = Dispenserve(MemoryStore(), state, Dispenser(enabled=False), telemetry=telemetry, ledger=ledger, voice=voice, result_seconds=0)
    app.insights = insights_mod.Insights(state, api_key="k", transport=gemini)
    crowd = FakeCrowd(people=4, seed=11)

    repo_before, temp_before = snapshot_repo(), snapshot_temp()
    _events.clear()
    _recording.set()
    try:
        for _ in range(10):
            app.complete_scan(crowd.hold())
            app.person_left()
        app.restock()
        app.flush_solana()
        app.insights_json()
        import time as _time

        _time.sleep(0.4)
        telemetry.close()
        ledger.close()
    finally:
        _recording.clear()

    assert _events == [], f"disk or network activity during the session: {_events}"
    assert snapshot_repo() - repo_before == set()
    assert snapshot_temp() - temp_before == set()
    assert len(outgoing) >= 4  # tiger, snowflake, 2 solana memos, gemini
    blob = "\n".join(outgoing)
    for person in crowd.people:
        for decimals in (3, 4, 6):
            assert f"{person[0]:.{decimals}f}" not in blob
            assert f"{person[1]:.{decimals}f}" not in blob
    assert all(args[3] in {t for texts in voice_mod.LINES.values() for t in texts} for args in spoken)
