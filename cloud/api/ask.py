"""'Ask about this machine': a plain-English answer built from anonymous aggregates only.

PRIVACY: the only thing this file can send to Gemini is the `facts` dict assembled by
app.py — stock levels, counts per machine and forecasts. There is no per-person data in
the database, so there is none to send. Without a key (or if Gemini fails) it answers
from the same numbers with plain arithmetic, so the dashboard never breaks.
"""

import json
import logging
import os
import urllib.request

log = logging.getLogger("fleet.ask")

# per-model daily quota on the free tier, so the model is configurable
MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-flash-latest"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_QUESTION = 300


def build_prompt(question, facts):
    return (
        "You help staff who run free snack machines for college students. "
        "Answer their question in at most 3 short sentences, using only these anonymous numbers:\n"
        f"{json.dumps(facts, sort_keys=True, default=str)}\n\n"
        f"Question: {question}\n"
        "Use the forecast (hours_left, runs_out_at, rate_per_hour) and the impact counts to give the "
        "best estimate you can, and say what the staff member should do. Only say the numbers can't "
        "answer if nothing in them is relevant. No markdown, no preamble."
    )


def ask_gemini(api_key, prompt, transport=None):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512}}
    if transport is not None:
        reply = transport(API_URL.format(model=MODEL), {"x-goog-api-key": api_key}, body)
    else:
        req = urllib.request.Request(API_URL.format(model=MODEL), data=json.dumps(body).encode(),
                                     headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as res:
            reply = json.loads(res.read())
    parts = reply["candidates"][0]["content"]["parts"]
    text = " ".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise ValueError("empty response")
    return text


def plain_answer(facts):
    """No key, or Gemini is down: answer from the numbers directly."""
    impact = facts.get("impact", {})
    soonest = next((b for b in facts.get("forecast", []) if b.get("hours_left") is not None), None)
    parts = [f"{impact.get('people_today', 0)} people served today, {impact.get('items_all_time', 0)} items all time "
             f"across {impact.get('machines', 0)} machine(s)."]
    if soonest:
        parts.append(f"{soonest['machine_id']} · {soonest['bay']} runs out soonest, in about "
                     f"{soonest['hours_left']:.0f} hours ({soonest['remaining']} left).")
    return " ".join(parts)


def answer_question(question, facts, api_key, transport=None):
    question = (question or "").strip()[:MAX_QUESTION]
    if not question:
        return {"answer": plain_answer(facts), "source": "numbers", "question": question}
    if api_key:
        try:
            return {"answer": ask_gemini(api_key, build_prompt(question, facts), transport),
                    "source": "gemini", "question": question}
        except Exception as e:
            log.warning("ask: Gemini failed (%s), answering from the numbers", e)
    return {"answer": plain_answer(facts), "source": "numbers", "question": question}
