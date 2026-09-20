"""Spoken kiosk lines: calm, friendly, a few variations each.

The lines are fixed, generic text (below). say() only takes one of the four line names,
so nothing about a person can ever be spoken or sent to ElevenLabs. With
ELEVENLABS_API_KEY, each line is generated once on a background thread and cached as
an mp3 in vision/audio/ (generic audio, not user data). Until a clip is cached, or
without a key, it falls back to macOS `say`. Playback never blocks: it's a subprocess.
"""

import hashlib
import json
import logging
import random
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("dispenserve.voice")

# Fixed, generic lines. Spoken aloud so the machine works for someone who can't read the
# screen, a kid, or anyone who'd rather not squint at an iPad. Spanish is included because
# the people a free food table needs to reach are not all English-first.
LINES = {
    "en": {
        "scanning": [
            "Hold still for a sec.",
            "Just a second, hold still.",
            "Hold still, almost there.",
        ],
        "dispensed": [
            "Here you go, have a good one.",
            "Here you go. Enjoy!",
            "There you go, have a great day.",
        ],
        "already_served": [
            "You've already got yours today. Come back tomorrow.",
            "Looks like you've had yours today. See you tomorrow!",
            "You're all set for today. Come back tomorrow.",
        ],
        "goodbye": [
            "See you tomorrow, thanks for stopping by.",
            "Thanks for stopping by. See you tomorrow!",
            "Take care, see you tomorrow.",
        ],
        "low_stock": [
            "Heads up: this machine is running low and needs a refill.",
            "Volunteer note: only a few items left in this machine.",
            "Running low here. Time for a restock.",
        ],
    },
    "es": {
        "scanning": [
            "Quédate quieto un segundo.",
            "Un segundo, no te muevas.",
            "No te muevas, ya casi está.",
        ],
        "dispensed": [
            "Aquí tienes, que te vaya bien.",
            "Aquí tienes. ¡Que lo disfrutes!",
            "Listo, que tengas un buen día.",
        ],
        "already_served": [
            "Ya recogiste el tuyo hoy. Vuelve mañana.",
            "Parece que ya tomaste el tuyo hoy. ¡Hasta mañana!",
            "Ya estás listo por hoy. Vuelve mañana.",
        ],
        "goodbye": [
            "Hasta mañana, gracias por pasar.",
            "Gracias por pasar. ¡Hasta mañana!",
            "Cuídate, nos vemos mañana.",
        ],
        "low_stock": [
            "Atención: esta máquina se está quedando sin productos.",
            "Nota para el voluntario: quedan pocos productos.",
            "Quedan pocos. Hay que reabastecer.",
        ],
    },
}
LANGUAGES = tuple(LINES)
KINDS = tuple(LINES["en"])

AUDIO_DIR = Path(__file__).resolve().parent / "audio"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
# "Sarah": soft and friendly, and one of the built-in voices a free account can use
# through the API. Voice Library voices need a paid plan (HTTP 402). Override with
# ELEVENLABS_VOICE_ID; Lily (pFZP5JQG7iQjIQuC4Bku) and George (JBFqnCBsd6RMkjVDRZzb) also work.
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_MODEL = "eleven_multilingual_v2"
SAY_VOICE = "Samantha"
SAY_VOICE_BY_LANG = {"en": "Samantha", "es": "Paulina"}  # macOS fallback voices
SCANNING_GAP_S = 8.0  # don't repeat "hold still" on every restarted hold


def clip_path(audio_dir, kind, index, text, voice_id, model):
    digest = hashlib.sha256(f"{voice_id}|{model}|{text}".encode()).hexdigest()[:10]
    return Path(audio_dir) / f"{kind}_{index + 1}_{digest}.mp3"


def elevenlabs_tts(api_key, voice_id, model, text):
    body = {"text": text, "model_id": model, "voice_settings": {"stability": 0.6, "similarity_boost": 0.8, "style": 0.1}}
    req = urllib.request.Request(
        API_URL.format(voice_id=voice_id),
        data=json.dumps(body).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def system_player(args):
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Voice:
    def __init__(self, api_key=None, voice_id=DEFAULT_VOICE_ID, model=DEFAULT_MODEL, audio_dir=AUDIO_DIR,
                 mute=False, synth=elevenlabs_tts, player=system_player, language="en"):
        self.language = language if language in LINES else "en"
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.audio_dir = Path(audio_dir)
        self.mute = mute
        self.synth = synth
        self.player = player
        self._current = None
        self._last_index = {}
        self._last_scanning = 0.0
        self._lock = threading.Lock()
        self._has_afplay = shutil.which("afplay") is not None
        self._has_say = shutil.which("say") is not None
        if mute:
            log.info("voice: muted")
        elif not api_key:
            log.info("voice: ELEVENLABS_API_KEY not set (or --no-elevenlabs), using macOS say")

    def prepare(self):
        """Generate any missing clips in the background. Safe to call without a key."""
        if self.mute or not self.api_key:
            return
        threading.Thread(target=self._generate_missing, name="voice-cache", daemon=True).start()

    def set_language(self, language):
        """Switch spoken language. Unknown codes are ignored, so the kiosk can't break the voice."""
        if language in LINES and language != self.language:
            self.language = language
            log.info("voice: language set to %s", language)
        return self.language

    def _generate_missing(self):
        made = 0
        for lang, kinds in LINES.items():
            for kind, texts in kinds.items():
                for i, text in enumerate(texts):
                    path = clip_path(self.audio_dir, f"{lang}_{kind}", i, text, self.voice_id, self.model)
                    if path.exists():
                        continue
                    try:
                        audio = self.synth(self.api_key, self.voice_id, self.model, text)
                        self.audio_dir.mkdir(parents=True, exist_ok=True)
                        tmp = path.with_suffix(".part")
                        tmp.write_bytes(audio)
                        tmp.replace(path)
                        made += 1
                    except Exception as e:
                        log.warning("voice: ElevenLabs failed for %r (%s); using macOS say for now", text, e)
                        return
        if made:
            log.info("voice: generated %d ElevenLabs clips in %s", made, self.audio_dir)

    def say(self, kind, language=None):
        """Speak one of the fixed lines: scanning, dispensed, already_served, goodbye, low_stock."""
        if kind not in KINDS:
            raise ValueError(f"unknown line {kind!r}")
        lang = language if language in LINES else self.language
        if self.mute:
            return None
        now = time.monotonic()
        if kind == "scanning":
            if now - self._last_scanning < SCANNING_GAP_S:
                return None
            self._last_scanning = now
        texts = LINES[lang][kind]
        choices = [i for i in range(len(texts)) if i != self._last_index.get(kind)] or [0]
        index = random.choice(choices)
        self._last_index[kind] = index
        text = texts[index]

        path = clip_path(self.audio_dir, f"{lang}_{kind}", index, text, self.voice_id, self.model)
        if path.exists() and self._has_afplay:
            args = ["afplay", str(path)]
        elif self._has_say:
            args = ["say", "-v", SAY_VOICE_BY_LANG.get(lang, SAY_VOICE), text]
        else:
            log.info("voice (no audio player): %s", text)
            return text
        with self._lock:
            if self._current is not None and self._current.poll() is None:
                self._current.terminate()  # a new line replaces one that's still playing
            try:
                self._current = self.player(args)
            except Exception as e:
                log.warning("voice: couldn't play audio: %s", e)
        return text
