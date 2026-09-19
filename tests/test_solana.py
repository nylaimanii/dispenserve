import base64
import datetime
import json
import sys
import time
from pathlib import Path

import pytest

import ledger as L
from main import Dispenserve
from memory import MemoryStore
from serial_link import Dispenser
from state import AppState

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud" / "api"))
import ledger_reader  # noqa: E402

RESTOCK_FIELDS = {"type", "machine_id", "date", "bay", "restocked_qty"}
TOTAL_FIELDS = {"type", "machine_id", "date", "dispensed_total"}


class FakeRPC:
    """Records every transaction that would be sent to devnet."""

    def __init__(self):
        self.sent = []

    def __call__(self, method, params):
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": L.b58encode(bytes(range(32)))}}
        if method == "sendTransaction":
            self.sent.append(base64.b64decode(params[0]))
            return f"sig{len(self.sent)}"
        raise AssertionError(method)


def memo_from_tx(raw):
    """The memo instruction's data is the tail of the transaction."""
    text = raw.decode("utf-8", errors="ignore")
    return json.loads(text[text.index(L.MEMO_PREFIX) + len(L.MEMO_PREFIX):])


def wait_for(fn, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not fn():
        time.sleep(0.02)


def test_records_hold_only_aggregate_fields():
    assert set(L.restock_record("m1", "2026-09-19", "Kit Kat", 18)) == RESTOCK_FIELDS
    assert set(L.daily_total_record("m1", datetime.date(2026, 9, 19), 41)) == TOTAL_FIELDS


@pytest.mark.parametrize("bad", [0.42, [0.1, 0.2], "18", -1, True, None])
def test_quantities_must_be_plain_counts(bad):
    # a float, a list (a vector), text or a flag can never be written on chain
    with pytest.raises(ValueError):
        L.restock_record("m1", "2026-09-19", "Kit Kat", bad)
    with pytest.raises(ValueError):
        L.daily_total_record("m1", "2026-09-19", bad)


def test_bad_dates_and_long_text_rejected():
    with pytest.raises(ValueError):
        L.restock_record("m1", "Sept 19", "Kit Kat", 1)
    with pytest.raises(ValueError):
        L.restock_record("x" * 65, "2026-09-19", "Kit Kat", 1)


def test_devnet_only():
    with pytest.raises(ValueError):
        L.check_devnet("https://api.mainnet-beta.solana.com")
    assert L.check_devnet(L.DEVNET_RPC)


def test_shortvec_and_base58():
    assert L.shortvec(0) == b"\x00" and L.shortvec(127) == b"\x7f"
    assert L.shortvec(128) == b"\x80\x01" and L.shortvec(16384) == b"\x80\x80\x01"
    assert L.b58decode(L.b58encode(b"\0\0hello")) == b"\0\0hello"
    assert L.b58encode(L.b58decode(L.MEMO_PROGRAM_ID)) == L.MEMO_PROGRAM_ID


def test_transaction_is_valid_and_signed():
    solders = pytest.importorskip("solders.transaction")
    kp = L.Keypair.generate()
    raw = L.memo_transaction(kp, L.b58encode(bytes(range(32))), L.memo_text(L.restock_record("m1", "2026-09-19", "Kit Kat", 3)))
    tx = solders.Transaction.from_bytes(raw)
    tx.verify()
    assert str(tx.message.account_keys[1]) == L.MEMO_PROGRAM_ID


def test_keypair_file_roundtrip(tmp_path):
    kp = L.Keypair.generate()
    path = tmp_path / "kp.json"
    path.write_text(kp.to_json())
    assert L.Keypair.load(path).address == kp.address


def test_restock_and_daily_total_from_the_app_put_nothing_personal_on_chain(person):
    rpc = FakeRPC()
    ledger = L.SolanaLedger("library-2f", L.Keypair.generate(), rpc=rpc)
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False), ledger=ledger, result_seconds=0)
    for _ in range(3):
        app.complete_scan([person()])  # three different people
    app.restock()
    app.flush_solana()
    wait_for(lambda: len(rpc.sent) == 2)
    ledger.close()

    restock, total = (memo_from_tx(raw) for raw in rpc.sent)
    assert restock == {"type": "restock", "machine_id": "library-2f", "date": datetime.date.today().isoformat(), "bay": "Kit Kat", "restocked_qty": 3}
    assert total == {"type": "daily_total", "machine_id": "library-2f", "date": datetime.date.today().isoformat(), "dispensed_total": 3}
    # the vectors the app saw never appear in anything sent
    for raw in rpc.sent:
        assert len(raw) < 400  # a 512-float vector couldn't fit


def test_finished_day_writes_its_total(monkeypatch):
    rpc = FakeRPC()
    ledger = L.SolanaLedger("m1", L.Keypair.generate(), rpc=rpc)
    state = AppState("Kit Kat", 24)
    app = Dispenserve(MemoryStore(), state, Dispenser(enabled=False), ledger=ledger, result_seconds=0)
    app.force_dispense()
    state._day = datetime.date(2026, 9, 18)  # pretend the day just ended
    app.close_finished_days()
    wait_for(lambda: len(rpc.sent) == 1)
    ledger.close()
    assert memo_from_tx(rpc.sent[0])["date"] == "2026-09-18"
    assert memo_from_tx(rpc.sent[0])["dispensed_total"] == 1


def test_no_keypair_means_ledger_off():
    assert L.SolanaLedger.from_env("m1", lambda k, d=None: d) is None


def test_fleet_ledger_reader_parses_and_links():
    memo = "[99] " + L.memo_text(L.restock_record("m1", "2026-09-19", "Kit Kat", 5))
    sneaky = "[99] dispenserve:" + json.dumps({"type": "restock", "machine_id": "m1", "date": "2026-09-19", "bay": "x", "restocked_qty": 1, "extra": [0.1] * 512})
    rows = [
        {"signature": "abc", "memo": memo, "blockTime": 1789800000, "err": None},
        {"signature": "def", "memo": sneaky, "blockTime": 1789790000, "err": None},
        {"signature": "ghi", "memo": "[5] hello", "blockTime": 1789780000, "err": None},
    ]
    reader = ledger_reader.LedgerReader(["Addr1"], rpc=lambda m, p: rows)
    records = reader.records()
    assert [r["signature"] for r in records] == ["abc", "def"]
    assert records[0]["explorer_url"] == "https://explorer.solana.com/tx/abc?cluster=devnet"
    assert "extra" not in records[1]  # unknown fields are dropped when reading back, too
