"""
Store tests — offline, isolated to a tmp file (no API, no shared state).

Locks the urgency ordering and the seed/update behavior the errands queue and
history depend on.
"""

from __future__ import annotations

import time

from agent import store


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_PATH", tmp_path / "state.json")


def test_history_newest_first(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    store.add_history({"goal": "a", "outcome": "done"})
    store.add_history({"goal": "b", "outcome": "declined"})
    hist = store.list_history()
    assert [h["goal"] for h in hist] == ["b", "a"]  # newest first


def test_tasks_sorted_by_urgency(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    now = time.time()
    store.add_task({"title": "late", "due": now + 10 * 86400})
    store.add_task({"title": "soon", "due": now + 1 * 86400})
    store.add_task({"title": "nodue", "due": None})
    titles = [t["title"] for t in store.list_tasks()]
    assert titles == ["soon", "late", "nodue"]  # soonest due first, no-due last


def test_completed_task_sorts_after_pending(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    now = time.time()
    done = store.add_task({"title": "done-one", "due": now + 1 * 86400})
    store.add_task({"title": "still-pending", "due": now + 5 * 86400})
    store.update_task(done["id"], status="done")
    tasks = store.list_tasks()
    assert tasks[0]["title"] == "still-pending"   # pending first
    assert tasks[-1]["status"] == "done"          # finished after


def test_seed_defaults_is_idempotent(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    store.seed_defaults()
    n_services, n_tasks = len(store.list_services()), len(store.list_tasks())
    assert n_services > 0 and n_tasks > 0
    store.seed_defaults()  # second call must not duplicate
    assert len(store.list_services()) == n_services
    assert len(store.list_tasks()) == n_tasks
