"""
Regression anchor: the labeled metformin scenario, kept green.

These run fully offline (mock effectors, no keys) and lock the two properties
that matter most: the plan completes when approved, and -- the load-bearing one
-- nothing costly/irreversible runs without an explicit human yes.
"""

from __future__ import annotations

import pytest

from agent.contracts import Effector, Risk, StepState
from agent.demo import golden_plan, mock_registry
from agent.dispatch import AWAITING, DONE, Runner, run_to_completion


def _run(approve: bool):
    plan = golden_plan()
    runner = Runner(plan, mock_registry())
    run_to_completion(runner, confirm=lambda step: approve)
    return plan


def test_golden_plan_completes_when_approved():
    plan = _run(approve=True)
    assert all(s.state is StepState.DONE for s in plan.steps)
    submit = next(s for s in plan.steps if s.args.get("action") == "submit_refill")
    assert submit.result["confirmation_no"]  # the irreversible action actually ran


def test_decline_skips_the_irreversible_step():
    plan = _run(approve=False)
    submit = next(s for s in plan.steps if s.args.get("action") == "submit_refill")
    assert submit.state is StepState.SKIPPED
    assert submit.result == {"declined": True}
    # Nothing irreversible happened...
    assert not any(
        s.result and isinstance(s.result, dict) and s.result.get("confirmation_no")
        for s in plan.steps
    )
    # ...AND the downstream steps (e.g. the "all done" confirmation) are skipped,
    # never run -- so we can't falsely tell the person it succeeded after a "no".
    assert plan.steps[-1].state is StepState.SKIPPED


def test_gate_pauses_before_executing_irreversible():
    """The runner must NOT execute a gated step until a decision is provided."""
    plan = golden_plan()
    runner = Runner(plan, mock_registry())
    # Tick until we hit the gate.
    seen_awaiting = False
    for _ in range(100):
        out = runner.tick()
        if out == AWAITING:
            seen_awaiting = True
            break
    assert seen_awaiting, "run should pause at the gate"
    gated = runner.awaiting_step
    assert gated is not None and gated.risk is Risk.IRREVERSIBLE
    assert gated.state is StepState.AWAITING_CONFIRM
    assert gated.result is None or "confirmation_no" not in (gated.result or {})
    # The gate question was composed and is available to speak.
    assert gated.args["confirm_prompt"].endswith("Should I go ahead?")


def test_gate_question_includes_cost():
    plan = golden_plan()
    runner = Runner(plan, mock_registry())
    while runner.tick() != AWAITING:
        pass
    assert "$14" in runner.awaiting_step.args["confirm_prompt"]


def test_registry_is_a_lookup_not_hardcoded():
    """The seam stays open: a new effector is one register() call, and a
    missing one raises a clear error rather than silently no-opping."""
    from effectors.base import EffectorRegistry

    reg = mock_registry()
    assert Effector.SPEAK in reg and Effector.BROWSE in reg
    empty = EffectorRegistry()
    with pytest.raises(LookupError):
        empty.get(Effector.BROWSE)


def test_failed_step_halts_safely():
    """If an effector raises, the run stops and the step is marked FAILED."""
    plan = golden_plan()
    reg = mock_registry()

    class Boom:
        name = Effector.BROWSE
        def execute(self, step):
            raise RuntimeError("portal relayouted")

    reg.register(Boom())
    runner = Runner(plan, reg)
    out = None
    for _ in range(100):
        out = runner.tick()
        if out in (DONE, "failed"):
            break
        if out == AWAITING:
            runner.provide_decision(True)
    assert any(s.state is StepState.FAILED for s in plan.steps)
    failed = next(s for s in plan.steps if s.state is StepState.FAILED)
    assert "portal relayouted" in failed.error
