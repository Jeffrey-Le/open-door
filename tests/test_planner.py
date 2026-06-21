"""
Planner tests — fully offline, no API key, no tokens spent.

These exercise the defensive JSON parsing and Plan-building that turn a model
response into a validated Plan, plus a stubbed end-to-end make_plan() with a
fake client. This is the regression harness the README asks for: iterate the
planner against the golden scenario without burning credits.
"""

from __future__ import annotations

import json

import pytest

from agent.contracts import Effector, Risk
from agent.planner import make_plan, parse_plan_json, plan_from_dict

# A well-formed planner output matching the golden metformin scenario.
GOLDEN_JSON = {
    "goal": "Refill my metformin prescription.",
    "steps": [
        {"effector": "speak", "intent": "Confirm the metformin refill", "risk": "safe", "rationale": "confirm aloud"},
        {"effector": "browse", "intent": "Find the prescription", "risk": "safe", "rationale": "read-only"},
        {"effector": "browse", "intent": "Check the cost", "risk": "safe", "rationale": "need real price"},
        {"effector": "speak", "intent": "State the $14 cost and ask to proceed", "risk": "safe", "rationale": "spoken gate"},
        {"effector": "browse", "intent": "Submit the refill", "args": {"action": "submit_refill"}, "risk": "irreversible", "rationale": "cannot undo"},
        {"effector": "speak", "intent": "Confirm it's done", "risk": "safe", "rationale": "read result back"},
    ],
}


# -- defensive parsing ------------------------------------------------------

def test_parse_clean_json():
    assert parse_plan_json(json.dumps(GOLDEN_JSON))["goal"].startswith("Refill")


def test_parse_strips_markdown_fences():
    fenced = "```json\n" + json.dumps(GOLDEN_JSON) + "\n```"
    assert parse_plan_json(fenced)["steps"][0]["effector"] == "speak"


def test_parse_extracts_object_from_surrounding_prose():
    noisy = "Sure! Here is the plan:\n" + json.dumps(GOLDEN_JSON) + "\nLet me know if that works."
    assert len(parse_plan_json(noisy)["steps"]) == 6


def test_parse_raises_on_unrecoverable():
    with pytest.raises(json.JSONDecodeError):
        parse_plan_json("this is not json at all")


# -- Plan building + validation --------------------------------------------

def test_plan_from_dict_builds_validated_plan():
    plan = plan_from_dict(GOLDEN_JSON)
    assert plan.goal.startswith("Refill")
    assert len(plan.steps) == 6
    assert plan.steps[0].effector is Effector.SPEAK
    # The golden shape has exactly one gated, irreversible step.
    gated = [s for s in plan.steps if s.gated]
    assert len(gated) == 1 and gated[0].risk is Risk.IRREVERSIBLE


def test_plan_from_dict_rejects_bad_effector():
    bad = {"goal": "x", "steps": [{"effector": "teleport", "intent": "?", "risk": "safe"}]}
    with pytest.raises(ValueError):
        plan_from_dict(bad)


def test_plan_from_dict_rejects_empty_steps():
    with pytest.raises(ValueError):
        plan_from_dict({"goal": "x", "steps": []})


# -- make_plan() with a fake client (no real API call) ----------------------

class _FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text

class _FakeResp:
    def __init__(self, text): self.content = [_FakeBlock(text)]

class _FakeMessages:
    def __init__(self, replies): self._replies = list(replies); self.calls = 0
    def create(self, **kwargs):
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return _FakeResp(reply)

class _FakeClient:
    def __init__(self, replies): self.messages = _FakeMessages(replies)


def test_make_plan_parses_model_output():
    client = _FakeClient([json.dumps(GOLDEN_JSON)])
    plan = make_plan("refill my metformin", client=client, model="test")
    assert len(plan.steps) == 6
    assert client.messages.calls == 1


def test_make_plan_retries_once_on_malformed_then_succeeds():
    client = _FakeClient(["not json", json.dumps(GOLDEN_JSON)])
    plan = make_plan("refill my metformin", client=client, model="test")
    assert len(plan.steps) == 6
    assert client.messages.calls == 2  # retried exactly once


def test_make_plan_raises_after_exhausting_retries():
    client = _FakeClient(["nope", "still nope"])
    with pytest.raises(ValueError):
        make_plan("refill my metformin", client=client, model="test")
