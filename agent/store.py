"""
Tiny JSON-backed store -- the app's only durable state.

Open Door is otherwise stateless (runs live in memory and vanish on restart).
This gives it just enough memory to support the user-facing extras: an action
history now, and the errands queue + connected-services list next. One file,
no database, no new dependencies; load-on-read + save-on-write under a lock is
plenty for demo volumes.

The on-disk shape is a single dict with three top-level lists so new features
slot in without migration:
    {"services": [...], "tasks": [...], "history": [...]}
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_PATH = Path(__file__).resolve().parent.parent / "data" / "state.json"
_LOCK = threading.Lock()
_DEFAULT: dict[str, list] = {"services": [], "tasks": [], "history": []}
_HISTORY_CAP = 200  # keep the file small; the full audit trail lives in Sentry


def _load() -> dict:
    try:
        data = json.loads(_PATH.read_text())
        return {**_DEFAULT, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        return {k: list(v) for k, v in _DEFAULT.items()}


def _save(state: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(_PATH)  # atomic-ish: never leave a half-written file


# -- history ----------------------------------------------------------------

def add_history(entry: dict[str, Any]) -> dict:
    """Record one finished run, newest first. Returns the stored entry."""
    with _LOCK:
        state = _load()
        stored = {"id": uuid.uuid4().hex[:8], "at": time.time(), **entry}
        state["history"].insert(0, stored)
        del state["history"][_HISTORY_CAP:]
        _save(state)
        return stored


def list_history() -> list[dict]:
    return _load()["history"]


# -- services + tasks (seeded once) -----------------------------------------

DEFAULT_SERVICES = [
    {"id": "pharmacy", "name": "Pharmacy", "provider": "BayMeds · prescriptions & refills", "icon": "💊",
     "status": "connected", "example_goal": "I need to refill my metformin, I'm out and I can't get to the pharmacy."},
    {"id": "dmv", "name": "DMV", "provider": "registration & licenses", "icon": "🚗",
     "status": "connected", "example_goal": "Renew my car registration before it expires — I can't read the small print on the DMV site."},
    {"id": "utilities", "name": "Utilities", "provider": "bills & payments", "icon": "💡",
     "status": "connected", "example_goal": "Pay my electric bill that's due this week — I can't get to a computer."},
    {"id": "benefits", "name": "Benefits", "provider": "Medicare · SNAP · appeals", "icon": "🏛️",
     "status": "available", "example_goal": "Help me review my Medicare benefits."},
]


def _default_tasks() -> list[dict]:
    now, day = time.time(), 86400
    mk = lambda **k: {"id": uuid.uuid4().hex[:8], "status": "pending", "created_at": now, **k}
    return [
        mk(title="Pay electric bill", service_id="utilities", due=now + 1 * day,
           goal="Pay my electric bill that's due this week — I can't get to a computer."),
        mk(title="Refill metformin", service_id="pharmacy", due=now + 3 * day,
           goal="Refill my metformin prescription, I'm out and can't get to the pharmacy."),
        mk(title="Renew car registration", service_id="dmv", due=now + 14 * day,
           goal="Renew my car registration before it expires."),
    ]


def seed_defaults() -> None:
    """Populate services + example errands on first run, so the queue and
    connections page aren't empty for the demo. No-op once seeded."""
    with _LOCK:
        state = _load()
        changed = False
        if not state["services"]:
            state["services"] = DEFAULT_SERVICES
            changed = True
        if not state["tasks"]:
            state["tasks"] = _default_tasks()
            changed = True
        if changed:
            _save(state)


def list_services() -> list[dict]:
    return _load()["services"]


def add_task(task: dict[str, Any]) -> dict:
    with _LOCK:
        state = _load()
        stored = {"id": uuid.uuid4().hex[:8], "status": "pending", "created_at": time.time(), "due": None, **task}
        state["tasks"].append(stored)
        _save(state)
        return stored


def list_tasks() -> list[dict]:
    """Pending errands first, sorted by urgency (soonest due, then oldest added);
    finished ones after, newest first. Enqueue-to-back, display-by-urgency."""
    tasks = _load()["tasks"]
    far = float("inf")
    pending = sorted((t for t in tasks if t.get("status") == "pending"),
                     key=lambda t: (t.get("due") if t.get("due") is not None else far, t.get("created_at") or 0))
    others = sorted((t for t in tasks if t.get("status") != "pending"),
                    key=lambda t: t.get("created_at") or 0, reverse=True)
    return pending + others


def update_task(task_id: str, **fields: Any) -> dict | None:
    with _LOCK:
        state = _load()
        for t in state["tasks"]:
            if t["id"] == task_id:
                t.update(fields)
                _save(state)
                return t
        return None


def delete_task(task_id: str) -> bool:
    with _LOCK:
        state = _load()
        before = len(state["tasks"])
        state["tasks"] = [t for t in state["tasks"] if t["id"] != task_id]
        if len(state["tasks"]) != before:
            _save(state)
            return True
        return False
