"""
Speak-leg tests — offline only, no Deepgram calls (no credits spent).

Covers backend selection by env and the text-recording execute path. The live
TTS/STT round-trip is verified manually against the real key (it costs credits),
so it's deliberately not in the unit suite.
"""

from __future__ import annotations

from agent.contracts import Effector, Risk, Step
from effectors.mock import MockSpeakBackend
from effectors.speak import DeepgramSpeakBackend, build_speak_backend


def _say(text: str) -> Step:
    return Step(effector=Effector.SPEAK, intent="speak a line", args={"action": "say", "text": text}, risk=Risk.SAFE)


def test_build_speak_backend_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("OPENDOOR_SPEAK", raising=False)
    assert isinstance(build_speak_backend(), MockSpeakBackend)


def test_build_speak_backend_real_needs_key(monkeypatch):
    monkeypatch.setenv("OPENDOOR_SPEAK", "real")
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    # No key -> still mock (don't construct a Deepgram client that would fail).
    assert isinstance(build_speak_backend(), MockSpeakBackend)


def test_build_speak_backend_real_with_key(monkeypatch):
    monkeypatch.setenv("OPENDOOR_SPEAK", "real")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    assert isinstance(build_speak_backend(), DeepgramSpeakBackend)


def test_deepgram_execute_records_text_without_network(monkeypatch):
    """execute() only records what to say -- no Deepgram call -- so the dispatch
    loop never makes network calls; audio is rendered separately via /api/tts."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    backend = DeepgramSpeakBackend()
    step = backend.execute(_say("Your refill is confirmed."))
    assert step.result["spoken"] == "Your refill is confirmed."
    # The gate hook returns the question text too, no network.
    assert backend.speak("Proceed?")["question"] is True
