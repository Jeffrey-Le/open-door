"""
Core contracts for Open Door.

One Claude planner takes a spoken goal, emits a structured Plan, and dispatches
each Step to one of two effectors: speak (Deepgram) or browse (Browserbase).
The planner is the Anthropic centerpiece; the Plan is a first-class object the
frontend renders directly, so the judge watches the reasoning as data.

Two design rules:
  1. The Plan is serializable and IS the hero UI element.
  2. Effectors share one Protocol; nothing costly/irreversible runs without an
     explicit human yes at the gate -- the care signal, made literal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol
import time
import uuid


class Effector(str, Enum):
    SPEAK = "speak"    # Deepgram: voice in/out -- ESSENTIAL because the user can't read a screen.
                       # Built deep on purpose: the spoken gate confirmations are the critical beat,
                       # which is what clears Deepgram's "essential, not tacked on" bar honestly.
    BROWSE = "browse"  # Browserbase: real portal navigation, recovery, stop-before-submit.
                       # The deep technical leg + the Anthropic technical-depth showcase.


class Risk(str, Enum):
    SAFE = "safe"                  # read-only / reversible: read a page, speak a sentence
    COSTLY = "costly"              # spends money / commits the user: authorize a copay
    IRREVERSIBLE = "irreversible"  # cannot be undone: submit the refill request


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CONFIRM = "awaiting_confirm"  # gated -- UI shows red, waits + SPEAKS the question
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Step:
    effector: Effector
    intent: str                       # "Request a 90-day refill of metformin on the portal"
    args: dict[str, Any] = field(default_factory=dict)
    risk: Risk = Risk.SAFE
    rationale: str = ""               # WHY this effector -- shown to the judge
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    state: StepState = StepState.PENDING
    result: Any = None
    error: str | None = None

    @property
    def gated(self) -> bool:
        return self.risk in (Risk.COSTLY, Risk.IRREVERSIBLE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "effector": self.effector.value, "intent": self.intent,
            "args": self.args, "risk": self.risk.value, "rationale": self.rationale,
            "state": self.state.value, "result": self.result, "error": self.error,
            "gated": self.gated,
        }


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: float = field(default_factory=time.time)

    def current(self) -> Step | None:
        for s in self.steps:
            if s.state not in (StepState.DONE, StepState.SKIPPED, StepState.FAILED):
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "goal": self.goal, "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
        }


class EffectorBackend(Protocol):
    name: Effector
    def execute(self, step: Step) -> Step: ...
