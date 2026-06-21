"""
Dispatch: the execution loop and the human gate.

This is where a Plan becomes actions. It walks the steps in order, hands each to
its effector via the registry (a lookup, never an if/else over effector types --
the seam stays open), and -- the load-bearing part -- STOPS at any costly or
irreversible step and refuses to run it until a human says yes.

The gate is modeled as an explicit pause, not a blocking input() call, so the
SAME runner drives both the CLI (synchronous yes/no) and the web demo
(asynchronous: UI lights the step red, SPEAKS the question, waits for a click or
a spoken yes, then resumes). Every gate is wrapped in the Sentry breadcrumbs
from observability.py, so the audit trail records exactly what the human was
asked and what they decided.

Two ways to drive it:
  - run_to_completion(runner, confirm=fn): synchronous, for CLI/tests.
  - Runner.tick() + Runner.provide_decision(yes): step-wise, for the server.
"""

from __future__ import annotations

from typing import Callable

from agent.contracts import Effector, Plan, Step, StepState
from agent.observability import instrument_step, record_gate, record_gate_decision
from effectors.base import EffectorRegistry


# What a single tick did, so the server knows whether to keep going, pause for a
# human, or stop. (Plain strings keep it serializable for the frontend.)
RAN = "ran"            # a step executed (safe step, or a confirmed gated step)
AWAITING = "awaiting"  # paused at a gate; needs provide_decision()
DONE = "done"          # no steps left
FAILED = "failed"      # a step raised; run halts safely


class Runner:
    """Drives one Plan through its steps, pausing at gates for a human yes.

    The runner never runs a gated step on its own initiative: it sets the step
    to AWAITING_CONFIRM, speaks the question, and waits. Only provide_decision()
    can release it -- approve to execute, decline to skip.
    """

    def __init__(self, plan: Plan, registry: EffectorRegistry) -> None:
        self.plan = plan
        self.registry = registry
        # decision for the step currently awaiting confirmation, if any
        self._pending_decision: bool | None = None

    # -- introspection the server/UI uses -----------------------------------

    @property
    def awaiting_step(self) -> Step | None:
        for s in self.plan.steps:
            if s.state is StepState.AWAITING_CONFIRM:
                return s
        return None

    def next_step(self) -> Step | None:
        """The first step not yet in a terminal state."""
        return self.plan.current()

    # -- the gate -----------------------------------------------------------

    def gate_question(self, step: Step) -> str:
        """The sentence spoken at the gate. Explicit text in args wins; else a
        plain-language default built from the step so the gate is self-contained
        even if the planner didn't add a preceding speak step."""
        args = step.args or {}
        if args.get("confirm_prompt"):
            return str(args["confirm_prompt"])
        cost = args.get("cost") or args.get("copay")
        lead = f"This will {step.intent[0].lower()}{step.intent[1:]}"
        if cost:
            lead += f", costing {cost}"
        return lead + ". Should I go ahead?"

    def provide_decision(self, approved: bool) -> None:
        """Record the human's yes/no for the step currently at the gate."""
        if self.awaiting_step is None:
            raise RuntimeError("provide_decision() called but no step is awaiting confirmation")
        self._pending_decision = approved

    # -- the loop -----------------------------------------------------------

    def tick(self) -> str:
        """Advance the plan by at most one observable transition. Returns one of
        RAN / AWAITING / DONE / FAILED. The server calls this in a loop, pausing
        whenever it returns AWAITING."""
        # 1. Release a step whose decision just arrived.
        awaiting = self.awaiting_step
        if awaiting is not None:
            if self._pending_decision is None:
                return AWAITING  # still waiting on the human
            approved = self._pending_decision
            self._pending_decision = None
            record_gate_decision(awaiting, approved)
            if not approved:
                awaiting.state = StepState.SKIPPED
                awaiting.result = {"declined": True}
                # Declining a gated action invalidates the rest of the plan: later
                # steps (and their spoken "all done" lines) assume it happened.
                # Skip them so we NEVER falsely report success after a "no".
                for s in self.plan.steps:
                    if s.state is StepState.PENDING:
                        s.state = StepState.SKIPPED
                return RAN
            return self._execute(awaiting)

        # 2. Otherwise pick up the next pending step.
        step = self.next_step()
        if step is None:
            return DONE

        # 3. Gate it if costly/irreversible: speak the question, then pause.
        if step.gated:
            return self._open_gate(step)

        # 4. Safe step: just run it.
        return self._execute(step)

    def _open_gate(self, step: Step) -> str:
        step.state = StepState.AWAITING_CONFIRM
        question = self.gate_question(step)
        step.args = {**(step.args or {}), "confirm_prompt": question}
        with record_gate(step):
            # Voice the question now, through the speak backend, so the gate is
            # spoken whether or not the plan included a preceding speak step.
            speak = self.registry.get(Effector.SPEAK) if Effector.SPEAK in self.registry else None
            if speak is not None and hasattr(speak, "speak"):
                step.result = {"asked": speak.speak(question)}
        return AWAITING

    def _execute(self, step: Step) -> str:
        step.state = StepState.RUNNING
        try:
            self.registry.execute(step)
        except Exception as exc:  # halt safely; observability already captured it
            step.state = StepState.FAILED
            step.error = f"{type(exc).__name__}: {exc}"
            return FAILED
        step.state = StepState.DONE
        return RAN


def run_to_completion(
    runner: Runner,
    confirm: Callable[[Step], bool],
    max_ticks: int = 1000,
) -> Plan:
    """Synchronous driver for CLI/tests: runs ticks until DONE/FAILED, calling
    `confirm(step)` whenever the runner pauses at a gate."""
    for _ in range(max_ticks):
        outcome = runner.tick()
        if outcome is AWAITING:
            runner.provide_decision(confirm(runner.awaiting_step))
            continue
        if outcome in (DONE, FAILED):
            return runner.plan
    raise RuntimeError("run_to_completion exceeded max_ticks (possible loop)")
