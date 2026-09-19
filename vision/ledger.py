"""Public donor ledger on Solana devnet, written with the Memo program.

Donors can see their money turn into restocks without any student ever appearing on
chain. Only two kinds of record are ever written, each as a small JSON memo:

    restock      {type, machine_id, date, bay, restocked_qty}
    daily_total  {type, machine_id, date, dispensed_total}

Nothing else can be written: record_restock() and record_daily_total() build the memo
from those fields only, and validate their types. Devnet only.

Transactions are built and signed here directly (a legacy transaction with one Memo
instruction, signed with ed25519) so there's no heavy Solana SDK dependency.
Sending happens on a background thread and never blocks the camera loop.

Setup (see README):
    .venv/bin/python vision/ledger.py --new-keypair ~/.config/dispenserve/devnet.json
    .venv/bin/python vision/ledger.py --airdrop      # 1 devnet SOL, free
    .venv/bin/python vision/ledger.py --balance
"""

import argparse
import base64
import datetime
import json
import logging
import os
import queue
import re
import threading
import urllib.request
from pathlib import Path

log = logging.getLogger("dispenserve.solana")

DEVNET_RPC = "https://api.devnet.solana.com"
MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
MEMO_PREFIX = "dispenserve:"
EXPLORER_TX = "https://explorer.solana.com/tx/{sig}?cluster=devnet"
EXPLORER_ADDRESS = "https://explorer.solana.com/address/{addr}?cluster=devnet"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


# --- encoding ------------------------------------------------------------------


def b58encode(data):
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58_ALPHABET[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + out


def b58decode(text):
    n = 0
    for ch in text:
        n = n * 58 + B58_ALPHABET.index(ch)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(text) - len(text.lstrip("1"))) + body


def shortvec(n):
    """Solana's compact-u16 length prefix."""
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


# --- records -------------------------------------------------------------------


def _text(value, field):
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError(f"{field} must be a short string")
    return value


def _count(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _date(value):
    value = value.isoformat() if isinstance(value, datetime.date) else value
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError("date must be YYYY-MM-DD")
    return value


def restock_record(machine_id, date, bay, restocked_qty):
    return {
        "type": "restock",
        "machine_id": _text(machine_id, "machine_id"),
        "date": _date(date),
        "bay": _text(bay, "bay"),
        "restocked_qty": _count(restocked_qty, "restocked_qty"),
    }


def daily_total_record(machine_id, date, dispensed_total):
    return {
        "type": "daily_total",
        "machine_id": _text(machine_id, "machine_id"),
        "date": _date(date),
        "dispensed_total": _count(dispensed_total, "dispensed_total"),
    }


def memo_text(record):
    return MEMO_PREFIX + json.dumps(record, separators=(",", ":"), sort_keys=True)


def parse_memo(memo):
    """Pulls a dispenserve record out of an RPC memo field like '[97] dispenserve:{...}'."""
    if not memo or MEMO_PREFIX not in memo:
        return None
    try:
        record = json.loads(memo.split(MEMO_PREFIX, 1)[1])
    except ValueError:
        return None
    return record if isinstance(record, dict) and record.get("type") in ("restock", "daily_total") else None


# --- keys and transactions -------------------------------------------------------


class Keypair:
    def __init__(self, seed32):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        self._key = Ed25519PrivateKey.from_private_bytes(seed32)
        self.public = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self._seed = seed32

    @property
    def address(self):
        return b58encode(self.public)

    def sign(self, message):
        return self._key.sign(message)

    @classmethod
    def load(cls, path):
        """solana-keygen format: a JSON array of 64 bytes (32 secret seed + 32 public)."""
        raw = bytes(json.loads(Path(path).expanduser().read_text()))
        if len(raw) != 64:
            raise ValueError("keypair file must hold 64 bytes")
        kp = cls(raw[:32])
        if kp.public != raw[32:]:
            raise ValueError("keypair file's public key doesn't match its secret")
        return kp

    @classmethod
    def generate(cls):
        return cls(os.urandom(32))

    def to_json(self):
        return json.dumps(list(self._seed + self.public))


def memo_transaction(keypair, recent_blockhash, text):
    """A signed legacy transaction: one Memo instruction, signed by the payer."""
    data = text.encode("utf-8")
    message = (
        bytes([1, 0, 1])  # 1 signature required, 0 read-only signed, 1 read-only unsigned (memo program)
        + shortvec(2)
        + keypair.public
        + b58decode(MEMO_PROGRAM_ID)
        + b58decode(recent_blockhash)
        + shortvec(1)  # one instruction
        + bytes([1])  # program: account index 1 (memo)
        + shortvec(1)
        + bytes([0])  # accounts: the payer, so the memo shows who signed it
        + shortvec(len(data))
        + data
    )
    return shortvec(1) + keypair.sign(message) + message


# --- RPC -------------------------------------------------------------------------


def http_rpc(url):
    def call(method, params):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as res:
            reply = json.loads(res.read())
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error'].get('message', reply['error'])}")
        return reply["result"]

    return call


def check_devnet(url):
    if "devnet" not in url and not url.startswith(("http://127.0.0.1", "http://localhost")):
        raise ValueError(f"refusing non-devnet Solana RPC {url!r}: dispenserve only writes to devnet")
    return url


class SolanaLedger:
    """Queues ledger records and writes them as memos on a background thread."""

    def __init__(self, machine_id, keypair, rpc=None, rpc_url=DEVNET_RPC):
        self.machine_id = machine_id
        self.keypair = keypair
        self.rpc = rpc or http_rpc(check_devnet(rpc_url))
        self.sent = []  # (record, signature) for this session, shown in logs only
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="solana", daemon=True)
        self._thread.start()
        log.info("solana: writing donor ledger to devnet as %s", EXPLORER_ADDRESS.format(addr=keypair.address))

    @classmethod
    def from_env(cls, machine_id, env):
        path = env("SOLANA_KEYPAIR_PATH")
        if not path:
            log.info("solana: SOLANA_KEYPAIR_PATH not set, donor ledger off")
            return None
        try:
            keypair = Keypair.load(path)
            return cls(machine_id, keypair, rpc_url=env("SOLANA_RPC_URL", DEVNET_RPC))
        except Exception as e:
            log.warning("solana: donor ledger off, could not load keypair: %s", e)
            return None

    def record_restock(self, date, bay, restocked_qty):
        record = restock_record(self.machine_id, date, bay, restocked_qty)
        self._queue.put(record)
        return record

    def record_daily_total(self, date, dispensed_total):
        record = daily_total_record(self.machine_id, date, dispensed_total)
        self._queue.put(record)
        return record

    def send(self, record):
        """Writes one record. Returns the transaction signature."""
        blockhash = self.rpc("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
        tx = memo_transaction(self.keypair, blockhash, memo_text(record))
        return self.rpc("sendTransaction", [base64.b64encode(tx).decode(), {"encoding": "base64", "preflightCommitment": "confirmed"}])

    def _run(self):
        while True:
            record = self._queue.get()
            if record is None:
                return
            try:
                sig = self.send(record)
                self.sent.append((record, sig))
                log.info("solana: %s written: %s", record["type"], EXPLORER_TX.format(sig=sig))
            except Exception as e:
                log.warning("solana: could not write %s (%s)", record["type"], e)

    def close(self, timeout=10):
        self._queue.put(None)
        self._thread.join(timeout)


# --- command line ------------------------------------------------------------------


def main(argv=None):
    import config

    config.load_dotenv()
    parser = argparse.ArgumentParser(description="dispenserve Solana devnet ledger tools")
    parser.add_argument("--new-keypair", metavar="PATH", help="create a devnet keypair file (won't overwrite)")
    parser.add_argument("--airdrop", action="store_true", help="request 1 free devnet SOL for SOLANA_KEYPAIR_PATH")
    parser.add_argument("--balance", action="store_true", help="show the devnet balance")
    args = parser.parse_args(argv)

    if args.new_keypair:
        path = Path(args.new_keypair).expanduser()
        if path.exists():
            raise SystemExit(f"{path} already exists, not overwriting")
        path.parent.mkdir(parents=True, exist_ok=True)
        kp = Keypair.generate()
        path.write_text(kp.to_json())
        path.chmod(0o600)
        print(f"wrote {path}\naddress: {kp.address}\nadd to .env:  SOLANA_KEYPAIR_PATH={path}")
        return

    path = config.env("SOLANA_KEYPAIR_PATH")
    if not path:
        raise SystemExit("set SOLANA_KEYPAIR_PATH in .env first (or run --new-keypair)")
    kp = Keypair.load(path)
    rpc = http_rpc(check_devnet(config.env("SOLANA_RPC_URL", DEVNET_RPC)))
    print("address:", kp.address, "\n        ", EXPLORER_ADDRESS.format(addr=kp.address))
    if args.airdrop:
        try:
            sig = rpc("requestAirdrop", [kp.address, 1_000_000_000])
            print("airdrop requested:", EXPLORER_TX.format(sig=sig))
        except Exception as e:
            print(f"airdrop failed ({e}). The public faucet rate-limits often; use https://faucet.solana.com "
                  f"(pick devnet, paste {kp.address}) and run --balance after.")
    if args.balance or not args.airdrop:
        lamports = rpc("getBalance", [kp.address])["value"]
        print(f"balance: {lamports / 1e9:.4f} devnet SOL (~{lamports // 5000} memos)")


if __name__ == "__main__":
    main()
