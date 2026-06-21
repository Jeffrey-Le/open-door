"""
The speak leg: real voice via Deepgram (TTS out + STT in).

This is the leg that clears Deepgram's "essential, not tacked on" bar: the
person can't read the screen, so the cost and the gate question are *spoken*,
and their goal is *heard*. Both directions are real:

  - TTS (out): synthesize() turns the gate's "this costs $14, proceed?" -- and
    every spoken step -- into audio the browser plays. Replaces the browser's
    built-in Web Speech voice with Deepgram's.
  - STT (in): transcribe() turns recorded intake audio into the transcript the
    planner decomposes into a Plan.

Design notes:
  - This backend is used for the HTTP audio endpoints (/api/tts, /api/transcribe).
    The dispatch loop itself still records *what* to say as text (MockSpeakBackend);
    rendering it to audio is a frontend concern that calls /api/tts. That keeps
    "what to say" (plan/gate) cleanly separate from "make sound" (Deepgram).
  - Lazy client + lazy import so nothing here runs unless the speak leg is on
    (OPENDOOR_SPEAK=real + DEEPGRAM_API_KEY), keeping the offline path keyless.
"""

from __future__ import annotations

import os

from agent.contracts import Effector, Step
from agent.observability import instrument_step
from effectors.mock import MockSpeakBackend, _action

# Deepgram voice + STT model. Aura-2 Thalia is a warm, clear English voice that
# suits reading costs and confirmations to someone who can't see the screen.
DEFAULT_TTS_VOICE = os.environ.get("OPENDOOR_TTS_VOICE", "aura-2-thalia-en")
DEFAULT_STT_MODEL = os.environ.get("OPENDOOR_STT_MODEL", "nova-3")


class DeepgramSpeakBackend:
    """Live Deepgram backend: TTS for spoken output, STT for spoken intake."""

    name = Effector.SPEAK

    def __init__(self, api_key: str | None = None, voice: str | None = None, stt_model: str | None = None) -> None:
        self.api_key = api_key or os.environ["DEEPGRAM_API_KEY"]
        self.voice = voice or DEFAULT_TTS_VOICE
        self.stt_model = stt_model or DEFAULT_STT_MODEL
        self._client = None

    def _dg(self):
        if self._client is None:
            from deepgram import DeepgramClient

            self._client = DeepgramClient(api_key=self.api_key)
        return self._client

    # -- TTS out -----------------------------------------------------------

    def synthesize(self, text: str) -> bytes:
        """Render text to MP3 audio bytes via Deepgram Aura. Used by /api/tts."""
        chunks = self._dg().speak.v1.audio.generate(text=text, model=self.voice, encoding="mp3")
        return b"".join(chunks)

    # -- STT in ------------------------------------------------------------

    def transcribe(self, audio: bytes) -> str:
        """Transcribe recorded intake audio to text via Deepgram Nova. Used by
        /api/transcribe. Returns the best transcript (empty string if none)."""
        resp = self._dg().listen.v1.media.transcribe_file(
            request=audio, model=self.stt_model, smart_format=True, punctuate=True
        )
        try:
            return resp.results.channels[0].alternatives[0].transcript or ""
        except (AttributeError, IndexError, TypeError):
            return ""

    # -- effector contract (text only; audio is rendered via /api/tts) -----

    @instrument_step
    def execute(self, step: Step) -> Step:
        action = _action(step)
        if action == "listen":
            step.result = {"transcript": (step.args or {}).get("expect", "")}
        else:
            spoken = MockSpeakBackend.text_for(step)
            step.result = {"spoken": spoken, "question": action == "ask_confirm"}
        return step

    def speak(self, text: str) -> dict:
        """Gate hook: record the question text (audio is fetched via /api/tts)."""
        return {"spoken": text, "question": True}


def build_speak_backend():
    """The app-level speak backend for the audio HTTP endpoints. Deepgram when
    OPENDOOR_SPEAK=real + a key is present; otherwise the mock (frontend then
    falls back to the browser's built-in Web Speech voice)."""
    if os.environ.get("OPENDOOR_SPEAK", "").lower() in ("real", "deepgram") and os.environ.get("DEEPGRAM_API_KEY"):
        return DeepgramSpeakBackend()
    return MockSpeakBackend()
