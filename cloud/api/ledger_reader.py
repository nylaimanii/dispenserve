"""Reads the public donor ledger back from Solana devnet for GET /ledger.

Every dispenserve machine writes restock and daily-total memos from its own wallet
(vision/ledger.py). This asks devnet for recent transactions from those wallets and
returns the memos with explorer links, so anyone can verify them independently.
"""

import datetime
import json
import threading
import time
import urllib.request

DEVNET_RPC = "https://api.devnet.solana.com"
MEMO_PREFIX = "dispenserve:"
EXPLORER_TX = "https://explorer.solana.com/tx/{sig}?cluster=devnet"
CACHE_SECONDS = 30


def parse_memo(memo):
    """RPC memo fields look like '[97] dispenserve:{...}'."""
    if not memo or MEMO_PREFIX not in memo:
        return None
    try:
        record = json.loads(memo.split(MEMO_PREFIX, 1)[1])
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("type") not in ("restock", "daily_total"):
        return None
    allowed = {"restock": ("type", "machine_id", "date", "bay", "restocked_qty"),
               "daily_total": ("type", "machine_id", "date", "dispensed_total")}[record["type"]]
    return {k: record[k] for k in allowed if k in record}


def http_rpc(url):
    def call(method, params):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as res:
            reply = json.loads(res.read())
        if "error" in reply:
            raise RuntimeError(reply["error"].get("message", str(reply["error"])))
        return reply["result"]

    return call


class LedgerReader:
    def __init__(self, addresses, rpc_url=DEVNET_RPC, rpc=None):
        self.addresses = [a.strip() for a in addresses if a.strip()]
        self.rpc = rpc or http_rpc(rpc_url)
        self._cache = (0.0, None)
        self._lock = threading.Lock()

    def records(self, limit=25):
        with self._lock:
            fetched_at, cached = self._cache
            if cached is not None and time.monotonic() - fetched_at < CACHE_SECONDS:
                return cached
        out = []
        for address in self.addresses:
            for item in self.rpc("getSignaturesForAddress", [address, {"limit": limit}]):
                record = parse_memo(item.get("memo"))
                if record is None or item.get("err") is not None:
                    continue
                block_time = item.get("blockTime")
                out.append({
                    **record,
                    "signature": item["signature"],
                    "signer": address,
                    "block_time": None if block_time is None else datetime.datetime.fromtimestamp(block_time, datetime.timezone.utc).isoformat(),
                    "explorer_url": EXPLORER_TX.format(sig=item["signature"]),
                })
        out.sort(key=lambda r: r["block_time"] or "", reverse=True)
        out = out[:limit]
        with self._lock:
            self._cache = (time.monotonic(), out)
        return out


def example_records(today):
    """Clearly marked sample records for --fake demos. No explorer links, since they aren't on chain."""
    rows = []
    for i, (machine, bay, qty, total) in enumerate([
        ("student-union", "Pretzels", 18, 41), ("library-2f", "Kit Kat", 20, 33), ("rec-center", "Protein Bar", 12, 9),
    ]):
        day = (today - datetime.timedelta(days=i)).isoformat()
        rows.append({"type": "restock", "machine_id": machine, "date": day, "bay": bay, "restocked_qty": qty,
                     "signature": None, "explorer_url": None, "example": True})
        rows.append({"type": "daily_total", "machine_id": machine, "date": day, "dispensed_total": total,
                     "signature": None, "explorer_url": None, "example": True})
    return rows
