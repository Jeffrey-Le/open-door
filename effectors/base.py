"""
Effector registry: the open seam, in code.

The planner picks an effector *by name* (Effector enum); dispatch looks the
backend up here. Adding a third body later (a robot, a phone-call leg) is one
`register()` call plus one backend class -- no if/else chain to edit, nothing in
the execution loop changes. That is the "swappable, extensible" promise from
contracts.py made concrete.

A backend is anything satisfying the EffectorBackend Protocol: it carries a
`name: Effector` and an `execute(step) -> Step`. Mock backends (effectors/mock.py)
and live backends (effectors/browse.py, effectors/speak.py) are interchangeable
here, so the whole pipeline runs offline against mocks and flips to live by
registering a different backend -- config, not refactor.
"""

from __future__ import annotations

from agent.contracts import Effector, EffectorBackend, Step


class EffectorRegistry:
    """A name -> backend lookup. Dispatch holds one of these."""

    def __init__(self) -> None:
        self._backends: dict[Effector, EffectorBackend] = {}

    def register(self, backend: EffectorBackend) -> EffectorBackend:
        """Register (or replace) the backend for an effector. Returns it, so it
        doubles as a decorator-ish one-liner at wiring time."""
        self._backends[backend.name] = backend
        return backend

    def get(self, effector: Effector) -> EffectorBackend:
        try:
            return self._backends[effector]
        except KeyError:
            raise LookupError(
                f"No backend registered for effector {effector.value!r}. "
                f"Registered: {[e.value for e in self._backends]}"
            ) from None

    def execute(self, step: Step) -> Step:
        """Dispatch one step to its backend. The backend is responsible for its
        own instrumentation (the @instrument_step decorator on execute)."""
        return self.get(step.effector).execute(step)

    def close(self) -> None:
        """Release any backend that holds resources (e.g. the browse leg's live
        browser). Backends without a close() are left alone. Idempotent."""
        for backend in self._backends.values():
            closer = getattr(backend, "close", None)
            if callable(closer):
                closer()

    def __contains__(self, effector: Effector) -> bool:
        return effector in self._backends
