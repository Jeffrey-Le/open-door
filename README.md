# Open Door

An AI agent that does bureaucratic and logistical legwork for people who can't
easily do it themselves — homebound, low-vision, low-literacy, or elderly people
locked out of the phone trees and web portals that now run daily life.

One Claude planner takes a spoken goal, decomposes it into a visible plan,
chooses the right "body" for each step, and **stops to ask before anything
costly or irreversible**. Care made legible: powerful enough to act, careful
enough to ask first.

**Flagship demo:** a homebound patient refills a prescription by voice. The
agent confirms details aloud, navigates the pharmacy portal, surfaces the real
out-of-pocket cost, and pauses for a spoken yes before submitting.

---

## Prize strategy (why the project is shaped this way)

| Track | Fit | Role |
|---|---|---|
| **Anthropic** (primary) | Health/access, Claude Code, biggest swing at a hard human problem, care over polish | The spine. The visible-reasoning planner IS the pitch. |
| **Deepgram** (Switch 2) | Voice essential, not tacked on | Deep leg. User can't read the screen → spoken gate confirmations are load-bearing. |
| **Sentry** (Switch 2) | Reliability + observability of real-world actions | Audit trail of every action the agent takes. Must be *exercised*, not just wired. |
| **Browserbase** (bonus) | Web agent on their platform | Deep technical leg + Anthropic technical-depth showcase. |

No robot leg — deliberately cut so three legs go deep instead of four going
shallow. The `Effector` Protocol leaves the seam **open** to add one later
(lab/v2) with zero refactor: add an enum entry + one backend class.

---

## What's already built (the load-bearing contracts)

- `agent/contracts.py` — `Plan` / `Step` / `Risk` / `Effector` / `EffectorBackend`.
  The Plan is a first-class serializable object; the frontend renders it directly.
  Three-way risk gating (safe / costly / irreversible). Effectors are a Protocol
  so backends are swappable and extensible.
- `agent/planner.py` — the Anthropic centerpiece: system prompt + strict-JSON
  schema + the golden "metformin refill" regression example. Effectors are a
  *menu* the model picks from (open seam). Forces honest rationale + over-gating.
- `agent/observability.py` — the Sentry seam. Stubbed; enable with
  `OPENDOOR_SENTRY=1` + `SENTRY_DSN`. Wraps effector execution and the human gate.

## What to build in Claude Code (in order, against live keys)

1. **`effectors/browse.py` (Browserbase) — build & test FIRST.** Your deep
   technical leg. Real portal navigation, recovery when a page misbehaves,
   stop-before-submit. Stand up a mock pharmacy portal in `portal/` to test
   offline (reuse the mock-portal pattern). Decorate `execute` with
   `@instrument_step`.
2. **`effectors/speak.py` (Deepgram).** STT for intake, **TTS for the spoken
   gate confirmations** — build BOTH directions; the spoken "this costs $X,
   proceed?" is what clears Deepgram's "essential" bar. Start from their 40-min
   starter app.
3. **`agent/dispatch.py` + execution loop.** A *lookup over registered
   effectors* (keeps the seam open — no hardcoded if/else). Wraps the gate with
   `record_gate` / `record_gate_decision`. Pauses at gated steps for a yes.
4. **`frontend/` — the hero UI.** Render `Plan.to_dict()`: steps light up as
   they run, gated steps pause **red** and the question is **spoken**, results
   fill in. This is the screenshot-worthy element.

## Before the demo
- Iterate the planner prompt OFFLINE against `GOLDEN_EXAMPLE` to save credits.
  ($25 total — budget it; use a cheaper model while iterating, strongest for the
  demo run.)
- Parse the planner's JSON defensively (strip fences, retry once on malformed).
- **Exercise Sentry once for real** — kill the mock portal mid-browse, confirm
  the capture lands in your dashboard. Un-triggered observability doesn't win.
- Keep one labeled end-to-end scenario green as a regression anchor.

## Pitch (what you say when judges walk up)
> Open Door handles the bureaucratic and physical errands of daily life for
> people who can't — it talks to you, works the web for you — and it never does
> anything costly or irreversible without asking you first.

Lead with **aspiration**: this is a hard, unsolved, dignity-level problem.
Anthropic said effort and ambition matter more than outcome — so frame the swing.

## Env
```
ANTHROPIC_API_KEY=...
BROWSERBASE_API_KEY=...
DEEPGRAM_API_KEY=...
OPENDOOR_SENTRY=1        # optional
SENTRY_DSN=...           # if OPENDOOR_SENTRY=1
```
