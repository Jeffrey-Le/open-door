"""
Offline demo wiring: a known-good Plan + a mock registry, no keys required.

This is the regression anchor the README asks for ("keep one labeled end-to-end
scenario green") and the thing the frontend drives before the live planner is
wired. The plan is the metformin-refill golden scenario from planner.py, in the
concrete arg vocabulary the effectors understand.

When ANTHROPIC_API_KEY is present, the server can instead call the real planner
(agent.planner) to produce this Plan from a spoken goal; the shape is identical,
so nothing downstream changes.
"""

from __future__ import annotations

import os

from agent.contracts import Effector, Plan, Risk, Step
from effectors.base import EffectorRegistry
from effectors.mock import MockBrowseBackend, MockSpeakBackend


def golden_plan() -> Plan:
    """The metformin refill, fully specified. Mirrors GOLDEN_EXAMPLE's shape:
    confirm details -> look up -> check cost -> SPEAK the cost -> GATED submit
    -> confirm done. The single gated step is the irreversible submit."""
    return Plan(
        goal="Refill my metformin prescription — I'm out and can't get to the pharmacy.",
        steps=[
            Step(
                effector=Effector.SPEAK,
                intent="Confirm this is the metformin 500 mg refill you mean",
                args={"action": "say", "text": "I'll refill your Metformin 500 milligram prescription. One moment."},
                risk=Risk.SAFE,
                rationale="You can't see the screen, so I confirm out loud which prescription before touching the portal.",
            ),
            Step(
                effector=Effector.BROWSE,
                intent="Open the pharmacy portal and find the metformin prescription",
                args={"action": "find_prescription", "name": "metformin"},
                risk=Risk.SAFE,
                rationale="Reading the portal is reversible; no need to interrupt you for a read-only lookup.",
            ),
            Step(
                effector=Effector.BROWSE,
                intent="Check refill availability and the out-of-pocket cost",
                args={"action": "check_refill"},
                risk=Risk.SAFE,
                rationale="I need the real cost and any cheaper option before I can ask you honestly.",
            ),
            Step(
                effector=Effector.SPEAK,
                intent="State the cost and the cheaper mail-order option",
                args={
                    "action": "say",
                    "text": (
                        "Your metformin is in stock. Picking it up today costs $14. "
                        "There's also a mail-order option for $6, but it takes 5 to 7 days."
                    ),
                },
                risk=Risk.SAFE,
                rationale="The cost and the tradeoff must be spoken plainly so you decide with full information.",
            ),
            Step(
                effector=Effector.BROWSE,
                intent="Submit the refill request on the portal",
                args={
                    "action": "submit_refill",
                    "cost": "$14.00",
                    "confirm_prompt": "I'm about to submit your metformin refill for $14 pickup today. Should I go ahead?",
                },
                risk=Risk.IRREVERSIBLE,
                rationale="Submitting can't be undone and spends your money — I stop and wait for your yes.",
            ),
            Step(
                effector=Effector.SPEAK,
                intent="Confirm the refill is placed and give the pickup details",
                args={"action": "say", "text": "Done. Your refill is confirmed and will be ready today by 5 PM at BayMeds on 14th and Oak."},
                risk=Risk.SAFE,
                rationale="You can't read the confirmation screen, so I read the result back to you.",
            ),
        ],
    )


def mock_registry() -> EffectorRegistry:
    """A registry wired to the offline mock backends. Swap either entry for a
    live backend (browse.py / speak.py) to go live -- nothing else changes."""
    reg = EffectorRegistry()
    reg.register(MockBrowseBackend())
    reg.register(MockSpeakBackend())
    return reg


def build_registry() -> EffectorRegistry:
    """The registry the server uses, selected by env so going live is config:

      OPENDOOR_BROWSE=real  -> drive a real Chromium via effectors/browse.py
                               (local + free; Browserbase if its key is set)
      (default / anything else) -> the offline MockBrowseBackend

    Speak stays mocked until the Deepgram leg lands; same pattern will apply.
    Each registered backend is the open seam in action -- one line to swap.
    """
    reg = EffectorRegistry()
    if os.environ.get("OPENDOOR_BROWSE", "").lower() in ("real", "cloud", "browserbase"):
        from effectors.browse import BrowseBackend  # imported lazily: only needs

        reg.register(BrowseBackend())               # playwright when actually used
    else:
        reg.register(MockBrowseBackend())
    reg.register(MockSpeakBackend())
    return reg
