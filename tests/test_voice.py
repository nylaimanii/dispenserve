import time

import pytest

import voice as V
from main import Dispenserve
from memory import MemoryStore
from serial_link import Dispenser
from state import AppState

ALL_LINES = {text for lang in V.LINES.values() for texts in lang.values() for text in texts}


class FakeProcess:
    def poll(self):
        return None

    def terminate(self):
        pass


class Recorder:
    def __init__(self):
        self.played = []

    def __call__(self, args):
        self.played.append(args)
        return FakeProcess()


def test_three_variations_of_each_line_in_every_language():
    assert set(V.LINES) == {"en", "es"}
    for lang in V.LINES.values():
        assert set(lang) == {"scanning", "dispensed", "already_served", "goodbye", "low_stock"}
        assert all(len(texts) == 3 for texts in lang.values())


def test_language_switch_is_safe():
    v = V.Voice(player=Recorder())
    assert v.set_language("es") == "es"
    assert v.set_language("klingon") == "es"   # unknown codes are ignored, voice keeps working
    assert v.set_language("en") == "en"


def test_spanish_lines_are_spoken_when_selected():
    rec = Recorder()
    v = V.Voice(player=rec)
    v._has_say, v._has_afplay = True, False
    v.set_language("es")
    v.say("dispensed")
    assert rec.played[-1][3] in V.LINES["es"]["dispensed"]
    assert rec.played[-1][2] == V.SAY_VOICE_BY_LANG["es"]


def test_elevenlabs_only_ever_receives_the_fixed_lines(tmp_path):
    requests = []

    def synth(api_key, voice_id, model, text):
        requests.append(text)
        return b"ID3fake-mp3"

    v = V.Voice(api_key="k", audio_dir=tmp_path, synth=synth, player=Recorder())
    v._generate_missing()
    assert set(requests) == ALL_LINES and len(requests) == 30   # 2 languages x 5 kinds x 3 variations
    assert len(list(tmp_path.glob("*.mp3"))) == 30
    v._generate_missing()  # cached: nothing is generated twice
    assert len(requests) == 30


def test_say_only_accepts_line_names():
    v = V.Voice(player=Recorder())
    with pytest.raises(ValueError):
        v.say("hello Jane, student 4412")


def test_cached_clip_plays_with_afplay_and_falls_back_to_say(tmp_path):
    rec = Recorder()
    v = V.Voice(api_key="k", audio_dir=tmp_path, synth=lambda *a: b"mp3", player=rec)
    v._has_afplay = v._has_say = True
    text = v.say("dispensed")
    assert rec.played[-1][:3] == ["say", "-v", V.SAY_VOICE] and rec.played[-1][3] == text  # nothing cached yet
    v._generate_missing()
    v.say("dispensed")
    assert rec.played[-1][0] == "afplay" and rec.played[-1][1].endswith(".mp3")


def test_mute_plays_nothing():
    rec = Recorder()
    V.Voice(mute=True, player=rec).say("dispensed")
    assert rec.played == []


def test_scanning_line_is_not_repeated_on_every_hold():
    rec = Recorder()
    v = V.Voice(player=rec)
    v._has_say = True
    v.say("scanning")
    v.say("scanning")
    assert len(rec.played) == 1


def test_app_speaks_results_and_goodbye(person):
    rec = Recorder()
    v = V.Voice(player=rec)
    v._has_say, v._has_afplay = True, False
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False), voice=v, result_seconds=0)
    alice = person()
    app.complete_scan([alice])
    app.person_left()
    app.complete_scan([alice])
    app.person_left()  # no goodbye: nothing was dispensed this time
    spoken = [args[3] for args in rec.played]
    kinds = [next(k for k, texts in V.LINES["en"].items() if t in texts) for t in spoken]
    assert kinds == ["dispensed", "goodbye", "already_served"]


def test_low_stock_is_announced_for_volunteers(person):
    from state import LOW_STOCK

    rec = Recorder()
    v = V.Voice(player=rec)
    v._has_say, v._has_afplay = True, False
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", LOW_STOCK + 1), Dispenser(enabled=False), voice=v, result_seconds=0)
    app.complete_scan([person()])          # drops to exactly LOW_STOCK left
    spoken = [args[3] for args in rec.played]
    assert any(t in V.LINES["en"]["low_stock"] for t in spoken)


def test_language_switch_never_raises_from_the_app():
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 20), Dispenser(enabled=False), voice=None, result_seconds=0)
    assert app.set_language("es") == "en"   # no voice configured: still safe
