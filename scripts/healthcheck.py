"""
Open Door health check — probes every leg live and prints a pass/fail table.

Run anytime the server is up (incl. the morning of judging):
    python scripts/healthcheck.py

It exercises the REAL legs end to end:
  - Anthropic planner  (one live Claude call -> a gated Plan)
  - Deepgram TTS + STT (synthesize -> transcribe round-trip via the server)
  - Browse + gate      (a full golden run through SSE; submit only after "yes")
  - Sentry             (init live + deliver one test event)

Three things it CAN'T verify for you (a human must): that you actually hear the
audio, that the mic fills the goal box, and that the events show in your Sentry
dashboard. Those are listed at the end.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import httpx  # noqa: E402

BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))


async def check_server(c: httpx.AsyncClient) -> bool:
    try:
        r = await c.get("/")
        record("server reachable", r.status_code == 200, f"http {r.status_code}")
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        record("server reachable", False, f"{type(e).__name__} — is it running? `python -m frontend.server`")
        return False


def check_planner() -> None:
    try:
        from agent.planner import make_plan

        plan = make_plan("I need to refill my metformin, I can't get to the pharmacy.")
        gated = [s for s in plan.steps if s.gated]
        ok = len(plan.steps) >= 3 and len(gated) >= 1
        record("Anthropic planner (live call)", ok, f"{len(plan.steps)} steps, {len(gated)} gated")
    except Exception as e:  # noqa: BLE001
        record("Anthropic planner (live call)", False, f"{type(e).__name__}: {e}")


async def check_deepgram(c: httpx.AsyncClient) -> None:
    try:
        caps = (await c.get("/api/capabilities")).json()
        if not caps.get("deepgram_voice"):
            record("Deepgram voice", False, "capabilities say off (OPENDOOR_SPEAK=real + key?)")
            return
        audio = await c.get("/api/tts", params={"text": "This costs fourteen dollars. Proceed?"})
        tts_ok = audio.status_code == 200 and len(audio.content) > 1000
        record("Deepgram TTS (/api/tts)", tts_ok, f"{len(audio.content)} bytes mp3")
        stt = await c.post("/api/transcribe", content=audio.content)
        text = stt.json().get("transcript", "")
        record("Deepgram STT (/api/transcribe)", bool(text.strip()), repr(text))
    except Exception as e:  # noqa: BLE001
        record("Deepgram voice", False, f"{type(e).__name__}: {e}")


async def check_browse_and_gate(c: httpx.AsyncClient) -> None:
    try:
        import json

        rid = (await c.post("/api/run", json={})).json()["run_id"]  # golden plan, no Anthropic cost
        approved = False
        gate_spoken = False
        final = None
        async with c.stream("GET", f"/api/run/{rid}/events") as r:
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                snap = json.loads(line[5:])
                if snap["awaiting_step_id"] and not approved:
                    gate_spoken = bool(snap.get("gate_question"))
                    await c.post(f"/api/run/{rid}/decision", json={"approved": True})
                    approved = True
                if snap["finished"]:
                    final = snap
                    break
        states = [s["state"] for s in final["plan"]["steps"]]
        submit = next(s for s in final["plan"]["steps"] if (s["args"] or {}).get("action") == "submit_refill")
        record("Browse leg (real Chromium)", "Metformin" in str(submit.get("result")) or submit["state"] == "done",
               f"confirmation {submit['result'].get('confirmation_no', '?')}")
        record("Human gate (pauses + speaks)", gate_spoken, "gate question was spoken")
        record("Full run completes on approve", all(s == "done" for s in states), f"{states}")
    except Exception as e:  # noqa: BLE001
        record("Browse + gate", False, f"{type(e).__name__}: {e}")


def check_sentry() -> None:
    try:
        import agent.observability as obs

        live = obs.init_observability()
        if not live:
            record("Sentry (deliver test event)", False, "init not live (OPENDOOR_SENTRY=1 + valid SENTRY_DSN?)")
            return
        import sentry_sdk

        sentry_sdk.capture_message("opendoor healthcheck")
        client = sentry_sdk.get_client()
        client.flush(timeout=8)
        record("Sentry (deliver test event)", True, "event flushed — verify in dashboard Issues")
    except Exception as e:  # noqa: BLE001
        record("Sentry (deliver test event)", False, f"{type(e).__name__}: {e}")


async def main() -> None:
    print("\nOpen Door health check\n" + "=" * 40)
    async with httpx.AsyncClient(base_url=BASE, timeout=90) as c:
        if not await check_server(c):
            print("\nServer is down — start it, then re-run.")
            return
        check_planner()
        await check_deepgram(c)
        await check_browse_and_gate(c)
    check_sentry()

    print("\n" + "=" * 40)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)} automated checks passed")
    print(
        "\nHuman-verify (can't automate):"
        "\n  • You HEAR the gate question aloud at http://127.0.0.1:8000/"
        "\n  • The 🎙 mic button fills the goal box from your voice"
        "\n  • The events appear in your Sentry dashboard → Issues"
    )
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
