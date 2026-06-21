"""
The demo host: FastAPI server that renders the Plan as the hero UI and drives it.

Responsibilities, all thin:
  - Serve the single-file frontend (frontend/index.html) and the mock pharmacy
    portal (portal/mock_pharmacy.html) so the whole demo is self-contained.
  - Start a run (golden plan offline; real planner when ANTHROPIC_API_KEY is set)
    and drive it step-by-step in the background so steps visibly light up.
  - Pause at gates: the run sits in AWAITING_CONFIRM until POST /decision, and
    the UI lights that step RED and SPEAKS the question.

State reaches the UI by Server-Sent Events: the server PUSHES a snapshot only
when state actually changes (a step ran, a gate opened, the run finished),
instead of the browser polling on a timer. One open stream per viewer, a handful
of events per run -- not hundreds of GETs. The snapshot is exactly Plan.to_dict()
plus gate context: the judge watches the agent's reasoning as data, no second
source of truth. (A GET snapshot endpoint remains for tests and as a fallback.)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

# Load secrets/config from .env into the environment BEFORE importing the agent
# modules -- some (e.g. observability) read their flags at import time, so this
# has to happen first. No-op if python-dotenv or the file is absent.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from agent import store
from agent.contracts import Plan
from agent.demo import build_registry, golden_plan
from agent.dispatch import AWAITING, DONE, FAILED, Runner
from agent.observability import init_observability
from effectors.speak import build_speak_backend

# App-level speak backend for the audio endpoints (Deepgram when OPENDOOR_SPEAK
# =real + key; else mock, and the frontend falls back to browser Web Speech).
SPEAK = build_speak_backend()
_TTS_AVAILABLE = hasattr(SPEAK, "synthesize")

ROOT = Path(__file__).resolve().parent.parent
STEP_GLOW_SECONDS = 0.9  # pause between steps so each visibly runs in the UI


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.seed_defaults()  # services + example errands on first run
    app.state.sentry_live = init_observability()  # no-op unless OPENDOOR_SENTRY=1
    planner = "live (ANTHROPIC_API_KEY set)" if os.environ.get("ANTHROPIC_API_KEY") else "golden-plan fallback"
    browse = os.environ.get("OPENDOOR_BROWSE", "mock")
    print(f"[open door] planner={planner}  browse={browse}  sentry={'live' if app.state.sentry_live else 'stub'}")
    yield


app = FastAPI(title="Open Door", lifespan=lifespan)


@dataclass
class Run:
    """One in-flight plan execution. Holds the runner, the gate signal, the SSE
    subscribers to fan state out to, and a single-thread executor so all ticks
    for this run share one OS thread (required for the sync-Playwright browse
    leg: its browser/page is thread-bound and must persist across steps)."""
    runner: Runner
    decision_event: asyncio.Event = field(default_factory=asyncio.Event)
    finished: bool = False
    failed: bool = False
    task_id: str | None = None  # set when this run was launched from an errand
    _subscribers: set[asyncio.Queue] = field(default_factory=set)
    executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="run")
    )

    @property
    def plan(self) -> Plan:
        return self.runner.plan

    def snapshot(self) -> dict:
        """The single payload the UI renders: the plan as data, plus gate context."""
        awaiting = self.runner.awaiting_step
        return {
            "plan": self.plan.to_dict(),
            "finished": self.finished,
            "failed": self.failed,
            "awaiting_step_id": awaiting.id if awaiting else None,
            # The exact sentence to speak at the gate (TTS'd client-side; swap to
            # Deepgram audio when the key is present).
            "gate_question": (awaiting.args or {}).get("confirm_prompt") if awaiting else None,
        }

    def subscribe(self) -> asyncio.Queue:
        """Register an SSE listener. Seeds it with the current snapshot so a
        late joiner renders immediately rather than waiting for the next change."""
        q: asyncio.Queue = asyncio.Queue()
        q.put_nowait(self.snapshot())
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self) -> None:
        """Push the current snapshot to every listener. Called only on state
        change, so each run produces a handful of events, not a polling storm."""
        snap = self.snapshot()
        for q in list(self._subscribers):
            q.put_nowait(snap)


RUNS: dict[str, Run] = {}


def _build_plan(goal: str | None) -> Plan:
    """Live planner when a goal AND ANTHROPIC_API_KEY are present; otherwise the
    offline golden plan. Planner failures fall back to the golden plan so the
    demo never hard-fails on a bad model response -- the Plan shape is identical."""
    if goal and goal.strip() and os.environ.get("ANTHROPIC_API_KEY"):
        from agent.planner import make_plan  # lazy: offline path needs no SDK

        try:
            return make_plan(goal.strip())
        except Exception as exc:  # noqa: BLE001 -- resilience over strictness for the demo
            print(f"[planner] live plan failed ({exc!r}); falling back to golden plan")
    return golden_plan()


def _build_runner(goal: str | None = None) -> Runner:
    """A plan (live or golden) + the env-selected registry (mock, or a live
    Chromium when OPENDOOR_BROWSE=real)."""
    return Runner(_build_plan(goal), build_registry())


def _history_entry(run: Run) -> dict:
    """Summarize a finished run for the in-app history (the person-facing audit
    trail; Sentry holds the developer-facing one)."""
    plan = run.plan
    declined = any(isinstance(s.result, dict) and s.result.get("declined") for s in plan.steps)
    outcome = "failed" if run.failed else ("declined" if declined else "done")
    submit = next((s for s in plan.steps if isinstance(s.result, dict) and s.result.get("confirmation_no")), None)
    gated = next((s for s in plan.steps if s.gated), None)
    gate_decision = "none"
    if gated is not None:
        if isinstance(gated.result, dict) and gated.result.get("declined"):
            gate_decision = "declined"
        elif gated.state.value == "done":
            gate_decision = "approved"
    return {
        "goal": plan.goal,
        "outcome": outcome,
        "confirmation_no": submit.result.get("confirmation_no") if submit else None,
        "gate_decision": gate_decision,
        "steps": [s.intent for s in plan.steps],
    }


async def _drive(run: Run) -> None:
    """Advance the plan in the background, pausing at gates for a human yes.
    Each tick runs on the run's single worker thread (off the event loop) so the
    sync-Playwright browse leg works and its page persists across steps. A
    snapshot is published after every transition, so viewers see each step light
    up, the gate open, and the run finish -- without polling."""
    loop = asyncio.get_running_loop()
    try:
        while True:
            outcome = await loop.run_in_executor(run.executor, run.runner.tick)
            run.publish()  # state changed -> notify viewers
            if outcome == AWAITING:
                await run.decision_event.wait()
                run.decision_event.clear()
                continue
            if outcome in (DONE, FAILED):
                run.finished = True
                run.failed = outcome == FAILED
                # Persist the history record BEFORE announcing "finished", so the
                # record exists the instant the UI (or History tab) looks for it.
                entry = _history_entry(run)
                await asyncio.to_thread(store.add_history, entry)
                if run.task_id:  # mark the originating errand done/declined/failed
                    await asyncio.to_thread(
                        store.update_task, run.task_id,
                        status=entry["outcome"], confirmation_no=entry.get("confirmation_no"),
                    )
                run.publish()
                break
            await asyncio.sleep(STEP_GLOW_SECONDS)  # let the step glow before the next
    finally:
        # Release the browser (if the live browse leg was used), then the thread.
        await loop.run_in_executor(run.executor, run.runner.registry.close)
        run.executor.shutdown(wait=False)


@app.post("/api/run")
async def start_run(payload: dict | None = None) -> JSONResponse:
    # Optional spoken/typed goal -> live planner; absent -> golden plan.
    body = payload if isinstance(payload, dict) else {}
    goal = body.get("goal")
    run_id = uuid.uuid4().hex[:8]
    run = Run(runner=_build_runner(goal), task_id=body.get("task_id"))
    RUNS[run_id] = run
    asyncio.create_task(_drive(run))
    return JSONResponse({"run_id": run_id, "plan": run.plan.to_dict()})


@app.get("/api/services")
async def services() -> JSONResponse:
    return JSONResponse({"services": store.list_services()})


@app.get("/api/tasks")
async def tasks() -> JSONResponse:
    return JSONResponse({"tasks": store.list_tasks()})


@app.post("/api/tasks")
async def create_task(payload: dict) -> JSONResponse:
    task = store.add_task({
        "title": (payload.get("title") or "Errand").strip(),
        "goal": (payload.get("goal") or "").strip(),
        "service_id": payload.get("service_id"),
        "due": payload.get("due"),
    })
    return JSONResponse(task)


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> JSONResponse:
    if not store.delete_task(task_id):
        raise HTTPException(404, "no such task")
    return JSONResponse({"ok": True})


@app.get("/api/run/{run_id}/events")
async def stream_run(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream of state changes for one run. The browser opens this once and
    renders each pushed snapshot; the server sends an event only when something
    changes, then closes the stream when the run finishes."""
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "no such run")

    async def gen():
        q = run.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    snap = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # comment frame; keeps proxies open
                    continue
                yield f"data: {json.dumps(snap)}\n\n"
                if snap["finished"]:
                    break
        finally:
            run.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/run/{run_id}")
async def get_run(run_id: str) -> JSONResponse:
    """Point-in-time snapshot. Fallback for clients without SSE, and what the
    test suite uses to assert state without holding a stream open."""
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return JSONResponse(run.snapshot())


@app.post("/api/run/{run_id}/decision")
async def decide(run_id: str, body: dict) -> JSONResponse:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    if run.runner.awaiting_step is None:
        raise HTTPException(409, "run is not at a gate")
    approved = bool(body.get("approved"))
    run.runner.provide_decision(approved)
    run.decision_event.set()
    return JSONResponse({"ok": True, "approved": approved})


# -- voice: Deepgram TTS out + STT in ---------------------------------------

@app.get("/api/history")
async def history() -> JSONResponse:
    """Past runs, newest first — the person-facing record of what Open Door did."""
    return JSONResponse({"history": store.list_history()})


@app.get("/api/capabilities")
async def capabilities() -> JSONResponse:
    """Lets the UI know whether real Deepgram voice is available, so it can show
    the mic button and prefer Deepgram audio over the browser's Web Speech voice."""
    return JSONResponse({"deepgram_voice": _TTS_AVAILABLE})


@app.get("/api/tts")
async def tts(text: str) -> Response:
    """Speak `text` as audio (Deepgram Aura). 501 when the speak leg is off, so
    the frontend falls back to the browser's built-in voice."""
    if not _TTS_AVAILABLE:
        raise HTTPException(501, "Deepgram TTS not enabled")
    audio = await asyncio.to_thread(SPEAK.synthesize, text)
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/transcribe")
async def transcribe(request: Request) -> JSONResponse:
    """Transcribe posted intake audio (Deepgram Nova) into a goal transcript."""
    if not hasattr(SPEAK, "transcribe"):
        raise HTTPException(501, "Deepgram STT not enabled")
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "no audio")
    transcript = await asyncio.to_thread(SPEAK.transcribe, audio)
    return JSONResponse({"transcript": transcript})


# -- static: the hero UI and the mock portal --------------------------------

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/portal")
async def portal() -> FileResponse:
    return FileResponse(ROOT / "portal" / "mock_pharmacy.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
