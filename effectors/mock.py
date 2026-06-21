"""
Mock effectors: run the whole pipeline offline, with no keys.

These stand in for the live Browserbase/Deepgram backends and return the SAME
result shapes, so dispatch, the gate, and the frontend can be built and demoed
before any API key exists -- and so swapping in the live backend changes nothing
downstream. They also double as the deterministic backends for tests.

ACTION VOCABULARY (shared with the live backends so they're interchangeable)
---------------------------------------------------------------------------
browse step args: {"action": ...}
  open_portal       -> {"screen": "list"}
  find_prescription -> {"found": true, "name", "supply", "refills_remaining"}
  check_refill      -> {"availability", "copay", "cheaper_option", "cost_note"}
  submit_refill     -> {"confirmation_no", "ready_by", "cost"}   # IRREVERSIBLE

speak step args: {"action": ...}
  say        -> {"spoken": <text>}                  # TTS out
  ask_confirm-> {"spoken": <text>, "question": true}# TTS the gate question
  listen     -> {"transcript": <text>}              # STT in

Unknown/absent action falls back to keyword-matching the step.intent so a
loosely-specified plan from the planner still runs.
"""

from __future__ import annotations

from agent.contracts import Effector, Step
from agent.observability import instrument_step


# Single fixture patient + prescription, mirroring portal/mock_pharmacy.html so
# the mock browse leg and the real one tell the same story in the demo.
_FIXTURE_RX = {
    "name": "Metformin 500 mg",
    "supply": "90-day",
    "refills_remaining": 2,
}
_FIXTURE_REFILL = {
    "availability": "In stock — ready in 2 hours",
    "copay": "$14.00",
    "cheaper_option": "90-day mail-order is $6.00 but takes 5–7 days",
    "cost_note": (
        "In-store pickup today is $14.00. A 90-day mail-order supply would cost "
        "$6.00, but takes 5–7 days to arrive."
    ),
}


def _action(step: Step) -> str:
    """Resolve the action from args, falling back to keywords in the intent."""
    a = (step.args or {}).get("action")
    if a:
        return str(a)
    intent = step.intent.lower()
    if "submit" in intent or "finaliz" in intent or "place" in intent:
        return "submit_refill"
    if "cost" in intent or "price" in intent or "copay" in intent or "availab" in intent:
        return "check_refill"
    if "find" in intent or "look up" in intent or "search" in intent or "locate" in intent:
        return "find_prescription"
    if "sign in" in intent or "log in" in intent or "open" in intent or "portal" in intent:
        return "open_portal"
    if "listen" in intent or "ask" in intent and "?" in step.intent:
        return "listen"
    return "say"


class MockBrowseBackend:
    """Deterministic stand-in for the Browserbase leg. Same result shapes as
    effectors/browse.py so dispatch/UI never know the difference."""

    name = Effector.BROWSE

    @instrument_step
    def execute(self, step: Step) -> Step:
        action = _action(step)
        if action == "open_portal":
            step.result = {"screen": "list", "signed_in_as": "Rosa Delgado"}
        elif action == "find_prescription":
            step.result = {"found": True, **_FIXTURE_RX}
        elif action == "check_refill":
            step.result = dict(_FIXTURE_REFILL)
        elif action == "submit_refill":
            # The IRREVERSIBLE action. Reached only after a confirmed gate.
            step.result = {
                "confirmation_no": "BM472913",
                "ready_by": "Today, by 5:00 PM",
                "cost": _FIXTURE_REFILL["copay"],
                "pickup": "BayMeds — 14th & Oak",
            }
        else:
            step.result = {"note": f"mock browse no-op for action {action!r}"}
        return step


class MockSpeakBackend:
    """Deterministic stand-in for the Deepgram leg. `say`/`ask_confirm` capture
    what was 'spoken' (the frontend renders it and can TTS it client-side);
    `listen` returns a canned transcript so intake works with no mic/key."""

    name = Effector.SPEAK

    # Canned replies for `listen`, so an offline run still flows. Keyed loosely.
    _CANNED_TRANSCRIPT = "Yes, go ahead."

    @instrument_step
    def execute(self, step: Step) -> Step:
        action = _action(step)
        if action == "listen":
            text = (step.args or {}).get("expect", self._CANNED_TRANSCRIPT)
            step.result = {"transcript": text}
        else:
            spoken = self.text_for(step)
            step.result = {"spoken": spoken, "question": action == "ask_confirm"}
        return step

    @staticmethod
    def text_for(step: Step) -> str:
        """The words to speak for a speak step -- ONLY the spoken text the planner
        provided (args.text / args.spoken). Never falls back to `intent`, which is
        a description of the step, not something to read aloud. Empty -> silent."""
        args = step.args or {}
        return str(args.get("text") or args.get("spoken") or "")

    def speak(self, text: str) -> dict:
        """Direct TTS used by the gate to voice the confirmation question,
        independent of any plan step. Live backend overrides with real audio."""
        return {"spoken": text, "question": True}
