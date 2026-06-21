# Open Door

**An AI agent that does the bureaucratic errands of daily life for people who can't — and never spends their money or does anything irreversible without asking first, out loud.**

Daily life now runs on phone trees and web portals. If you're homebound, low-vision, low-literacy, or elderly, that quietly locks you out of basic, dignity-level tasks: refilling a prescription, renewing a registration, paying a bill. Tools built for general users assume you can see a screen and supervise an agent the whole way — the people who most need help are the ones they were never built for.

Open Door takes a spoken goal, decomposes it into a visible plan, works the web on your behalf, and **stops to ask — by voice — before anything costly or irreversible.** Care made legible: powerful enough to act, careful enough to ask first.

> **Flagship demo:** a homebound patient refills a prescription by voice. The agent confirms details aloud, navigates the pharmacy portal, reads the real out-of-pocket cost off the page, and pauses for a spoken "yes" before submitting.

---

## How it works

A single Claude planner turns a spoken goal into a structured `Plan`. Each step is dispatched to an **effector** — a swappable "body" — and the run pauses at a human gate before any costly or irreversible action.

| Leg | What it does | Powered by |
|---|---|---|
| **Plan** | Decomposes the goal into a visible, ordered plan; tags each step's risk; writes the spoken lines | Claude (Anthropic) |
| **Browse** | Drives a real browser through the portal: read the page, find the item, surface the real cost, submit | Playwright (local) / Browserbase (cloud) |
| **Speak** | Voices the gate question and reads results aloud (TTS); hears the goal and the yes/no answer (STT) | Deepgram (Aura + Nova) |
| **Gate** | Pauses at any costly/irreversible step and refuses to proceed without an explicit human "yes" | dispatch state machine |
| **Observe** | Captures every effector failure and records what the human approved at each gate | Sentry |

Two design rules hold the whole thing together:

1. **The Plan is a first-class, serializable object** — the frontend renders it directly, so you watch the agent's reasoning as live data.
2. **Effectors share one Protocol** and are resolved by a registry lookup (never an `if/else`), so mock and live backends are interchangeable and a new leg is one `register()` call. Going live is configuration, not a refactor.

The gate is **structural, not cosmetic**: the browse effector never decides to submit — it only clicks the irreversible button when dispatch hands it the gated step, which dispatch does only after a human yes. Declining halts the rest of the plan, so it can never falsely report success.

---

## Try it out

### Prerequisites
- Python 3.11 (conda recommended)

### 1. Set up the environment
```bash
conda env create -f environment.yml
conda activate opendoor
python -m playwright install chromium      # for the real browse leg
```
<details><summary>Prefer a plain venv?</summary>

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```
</details>

### 2. Run it — no API keys needed
```bash
python -m frontend.server
```
Open **http://127.0.0.1:8000** and click **Plan & run**. Out of the box it runs **fully offline**: a deterministic golden plan, mock effectors, and the browser's built-in voice. To use a **real local browser** against the bundled mock pharmacy portal (still no key required), set `OPENDOOR_BROWSE=real`.

### 3. Go live (optional)
Copy the template and fill in whichever keys you have:
```bash
cp .env.example .env
```
```ini
ANTHROPIC_API_KEY=...     # live planner (real goal -> real plan)
DEEPGRAM_API_KEY=...      # real voice in + out
OPENDOOR_SPEAK=real
BROWSERBASE_API_KEY=...   # cloud browser (optional; local needs no key)
BROWSERBASE_PROJECT_ID=...
OPENDOOR_SENTRY=1         # observability (optional)
SENTRY_DSN=...
```
Restart the server. `.env` is loaded automatically and is gitignored — keys never get committed. Each leg degrades gracefully: with no key, it falls back to the offline path for that leg.

### 4. Verify
```bash
pytest                          # 26 offline tests (no keys, no network)
python scripts/healthcheck.py   # live end-to-end probe of every leg (needs keys)
```

---

## Configuration

All optional; set in `.env` or the environment.

| Variable | Effect |
|---|---|
| `OPENDOOR_BROWSE` | `real` = local Chromium · `cloud` = Browserbase · unset = offline mock |
| `OPENDOOR_HEADED=1` | Show the Chromium window during a run (default headless) |
| `OPENDOOR_SPEAK=real` | Use Deepgram voice (TTS+STT); otherwise the browser's Web Speech |
| `OPENDOOR_SENTRY=1` | Enable Sentry (requires `SENTRY_DSN`) |
| `OPENDOOR_PLANNER_MODEL` | Override the planner model (default `claude-opus-4-8`) |

---

## Project structure

```
agent/
  contracts.py      Plan / Step / Risk / Effector / EffectorBackend
  planner.py        the Claude planner: prompt, defensive JSON parsing, retries
  dispatch.py       execution loop + the pausable human gate
  observability.py  Sentry seam (instrument effectors + record gate decisions)
  store.py          JSON-backed persistence (services, errands, history)
  demo.py           the golden plan + env-selected effector registry
effectors/
  base.py           the effector registry (the open seam, in code)
  browse.py         Playwright/Browserbase web navigation
  speak.py          Deepgram TTS + STT
  mock.py           offline mock backends
frontend/
  server.py         FastAPI host: drives runs, streams state over SSE
  index.html        the hero UI: live plan, spoken gate, errands, history
portal/
  mock_pharmacy.html  deterministic test fixture for the browse leg
tests/                26 tests, all offline
scripts/healthcheck.py
```

---

## Status & what's next

All four legs are live and verified, with persistence, an urgency-ordered errands queue, a connected-services view, and an in-app action history. The planner already generalizes to new errands (e.g. a DMV renewal); the browse leg is scripted to the demo portal today. The clear next steps are generalizing the browse leg to natural-language navigation of arbitrary real portals, real per-service account connections, and an interactive "clarify" step that collects missing details mid-plan.

Built for the AI Hackathon 2026 with Claude, Deepgram, Browserbase, and Sentry.
