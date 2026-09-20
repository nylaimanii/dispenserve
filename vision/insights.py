"""Restock recommendations for staff, from Gemini or from plain arithmetic.

PRIVACY: individuals are never sent to Gemini. The only thing ever sent is the
aggregate snapshot built in aggregate_snapshot(): items left per bay, how many items
were dispensed in each hour today, and today's unique-visitor count. No faces, vectors,
images, scores, timestamps of individual visits, or anything about a person.

GET /insights returns a 2 sentence recommendation. Results are cached for 10 minutes
and refreshed on a background thread, so a request never waits on Gemini. With no
GEMINI_API_KEY (or --no-gemini, or any Gemini error) it falls back to a rule-based
run-out estimate.
"""

import datetime
import json
import logging
import threading
import time
import urllib.request

log = logging.getLogger("dispenserve.insights")

CACHE_SECONDS = 10 * 60
DEFAULT_MODEL = "gemini-flash-latest"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RATE_WINDOW_HOURS = 3
LOW_ITEMS = 3


def aggregate_snapshot(app_state, now=None):
    """The complete input to Gemini: counts only."""
    now = now or datetime.datetime.now()
    stats = app_state.stats_json()
    return {
        "local_time": now.strftime("%H:%M"),
        "bays": [{"name": b["name"], "items_left": int(b["remaining"]), "capacity": int(b["capacity"])} for b in stats["bays"]],
        "dispensed_per_hour_today": {f"{h:02d}:00": int(n) for h, n in app_state.hourly_today().items()},
        "unique_people_today": int(stats["unique_today"]),
    }


def recent_rate(snapshot):
    """Items per hour over the last few full hours plus the current one."""
    counts = list(snapshot["dispensed_per_hour_today"].values())[-(RATE_WINDOW_HOURS + 1):]
    if not counts:
        return 0.0
    now_minutes = int(snapshot["local_time"].split(":")[1])
    hours = (len(counts) - 1) + max(now_minutes, 1) / 60
    return sum(counts) / hours


def rule_based(snapshot):
    rate = recent_rate(snapshot)
    parts = []
    for bay in snapshot["bays"]:
        left = bay["items_left"]
        if left == 0:
            parts.append(f"{bay['name']} is empty and needs a restock now.")
        elif rate <= 0:
            parts.append(f"{bay['name']} has {left} of {bay['capacity']} left with no recent dispenses, so no restock is needed yet.")
        else:
            hours = left / rate
            if hours > 12:
                parts.append(f"{bay['name']} has {left} left and is going slowly (about {rate:.1f} per hour). No restock needed today.")
                continue
            when = "within the hour" if hours < 1 else f"in about {hours:.0f} hour{'s' if round(hours) != 1 else ''}"
            urgency = "Restock soon." if hours < 3 or left <= LOW_ITEMS else "No rush yet."
            parts.append(f"{bay['name']} has {left} left and is going at about {rate:.1f} per hour, so it runs out {when}. {urgency}")
    return " ".join(parts) or "No bays reported."


def build_prompt(snapshot):
    return (
        "You help campus staff keep a free snack dispenser stocked for college students. "
        "Here are today's anonymous aggregate numbers for one machine, as JSON:\n"
        f"{json.dumps(snapshot, sort_keys=True)}\n"
        "Write exactly 2 short, plain sentences for staff: when each bay will likely run out at "
        "the current pace, and what they should do. No preamble, no lists, no markdown."
    )


def http_transport(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:  # generous: the demo may be on a phone hotspot
        return json.loads(res.read())


def ask_gemini(api_key, model, prompt, transport=http_transport):
    reply = transport(
        API_URL.format(model=model),
        {"Content-Type": "application/json", "x-goog-api-key": api_key},
        {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024}},
    )
    parts = reply["candidates"][0]["content"]["parts"]
    text = " ".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise ValueError("empty response")
    return text


class Insights:
    def __init__(self, app_state, api_key=None, model=DEFAULT_MODEL, transport=http_transport, cache_seconds=CACHE_SECONDS):
        self.app_state = app_state
        self.api_key = api_key
        self.model = model
        self.transport = transport
        self.cache_seconds = cache_seconds
        self._cached = None
        self._fetched_at = 0.0
        self._refreshing = False
        self._lock = threading.Lock()
        if not api_key:
            log.info("insights: GEMINI_API_KEY not set (or --no-gemini), using the rule-based estimate")

    def get(self):
        """Never blocks on Gemini: returns the cached answer and refreshes it in the background."""
        with self._lock:
            fresh = self._cached is not None and time.monotonic() - self._fetched_at < self.cache_seconds
            start_refresh = not fresh and not self._refreshing and self.api_key
            if start_refresh:
                self._refreshing = True
            cached = self._cached
        if start_refresh:
            threading.Thread(target=self._refresh, name="insights", daemon=True).start()
        if cached is not None and (fresh or self.api_key):
            return cached
        return self._result(rule_based(aggregate_snapshot(self.app_state)), "rules")

    def _refresh(self):
        snapshot = aggregate_snapshot(self.app_state)
        prompt = build_prompt(snapshot)
        result = None
        for attempt in (1, 2):  # a single 503 or slow response shouldn't drop the card to the estimate
            try:
                result = self._result(ask_gemini(self.api_key, self.model, prompt, self.transport), "gemini")
                break
            except Exception as e:
                log.warning("insights: Gemini attempt %d failed (%s)", attempt, e)
                if attempt == 1:
                    time.sleep(2)
        if result is None:
            log.warning("insights: using the rule-based estimate")
            result = self._result(rule_based(snapshot), "rules")
        with self._lock:
            self._cached, self._fetched_at, self._refreshing = result, time.monotonic(), False

    @staticmethod
    def _result(text, source):
        return {"text": text, "source": source, "generated_at": datetime.datetime.now().isoformat(timespec="seconds")}
