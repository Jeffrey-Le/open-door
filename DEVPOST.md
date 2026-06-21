# Open Door

**Care, made legible. An AI agent that does the bureaucratic and physical errands of daily life for people who can't — and never does anything costly or irreversible without asking first.**

---

## Inspiration

Daily life now runs on phone trees and web portals. If you're homebound, low-vision, low-literacy, or elderly, that quietly locks you out of basic dignity-level tasks: refilling a prescription, renewing a registration, paying a bill. Existing tools assume you can see a screen and supervise an agent the whole way. The people who most need help are the ones those tools were never built for.

Open Door is our swing at that gap: an agent that **talks to you, works the web for you, and stops to ask — out loud — before it ever spends your money or does something it can't undo.**

## What it does

You say what you need ("I need to refill my metformin, I can't get to the pharmacy"). Open Door:

1. **Plans it out loud.** One Claude call turns your spoken goal into a visible, ordered plan — each step labeled with which "body" handles it and why.
2. **Works the portal for you.** A real browser navigates the pharmacy site, finds the prescription, and reads the actual out-of-pocket cost off the page.
3. **Stops at the gate.** Before the one irreversible step — submitting the refill — it **speaks the cost aloud** ("This will charge you $14 and submit your refill. Should I go ahead?") and waits. You answer **by voice** — "yes" or "no."
4. **Only then acts.** On "yes," it submits and reads back the confirmation. On "no," it stops cold and tells you nothing was charged.

The plan is the hero of the screen: steps light up as they run, the gated step pauses **red**, and the question is spoken — so a person who can't see or touch the screen can complete a real, costly action entirely by voice.

## How we built it

The architecture is built around **seams** — every external service is swappable, so the whole thing runs offline against mocks and flips to live with one env var.

- **Planner (Anthropic, Claude Opus 4.8)** — the centerpiece. A strict-JSON planner with adaptive thinking, defensive parsing, and a content-guard that retries if the spoken wording reads like a stage direction instead of real speech. It generalizes: give it a DMV renewal or a utility bill and it produces a correct, gated plan.
- **Browse leg (Browserbase + Playwright)** — drives a real Chromium through the portal. Local by default (free), **Browserbase cloud with one env flag** — same Playwright code over CDP. Self-healing navigation so the run survives messy pages. *Stop-before-submit is structural*: the effector never decides to submit; it only clicks the button when dispatch hands it the gated step, which only happens after a human "yes."
- **Speak leg (Deepgram)** — both directions. **TTS (Aura)** voices the gate question and every spoken line; **STT (Nova)** hears your goal at intake *and your yes/no at the gate*. The spoken confirmation is load-bearing, not decoration.
- **Dispatch + the human gate** — a pausable state machine: it physically parks the browser on the irreversible button and refuses to proceed until a human decides. Negative answers win on ambiguity — it never proceeds unless it clearly heard "yes." Declining skips the rest of the plan so it can never falsely report success.
- **Observability (Sentry)** — every effector is instrumented; every gate leaves a breadcrumb of exactly what the human approved. We exercised it for real (killed the portal mid-browse and watched the capture land), because un-triggered observability doesn't count.
- **Frontend** — a single-page hero UI streaming live state over Server-Sent Events (push on change, not polling), plus a connected-services landing that frames Open Door as a platform for all of daily life's errands.

22 regression tests, an 8/8 live health check, and an offline-first build kept it honest.

## Challenges we ran into

- **Making spoken output sound human.** The planner kept reading step *descriptions* aloud ("Confirm which pharmacy holds their prescription"). We fixed it with a sharper prompt plus a deterministic guard that detects stage-direction phrasing and retries for real second-person speech.
- **Generalist planner vs. scripted hands.** The planner imagines portal features (home delivery) the mock fixture doesn't have. We made the browse leg self-heal and tolerant so any goal completes rather than timing out.
- **A "no" that still said yes.** Early on, declining the gate still ran the downstream "all done" steps. We made declining halt the plan — the bug that most violated our own thesis, and the one we're proudest to have caught.

## Accomplishments we're proud of

The **spoken safety gate** — the agent parks on the irreversible button and asks aloud, and you answer aloud. It's a small thing that makes a powerful agent *safe to hand to someone who can't supervise it*. That's the whole point.

## What we learned

Building a careful agent is mostly about designing where it **stops**, not where it acts. The seams and the gate were more engineering than the "doing" — and that's the right ratio for something that spends a vulnerable person's money.

## What's next

Generalize the browse leg to natural-language web navigation so it handles any real portal (the planner already generalizes); add real account connections per service; a pending-errands queue and an in-app action history.

## Built with

Python · FastAPI · Server-Sent Events · Anthropic Claude (Opus 4.8) · Deepgram (Aura TTS + Nova STT) · Browserbase + Playwright · Sentry · conda

---

## How it maps to the judging criteria

- **Application** — a real, unsolved, dignity-level problem for a population current tools ignore.
- **Functionality/Quality** — every leg live and verified; a legible UI; resilient to failure.
- **Creativity** — the differentiated idea isn't "a web agent," it's the **spoken human gate before anything irreversible**.
- **Technical Complexity** — live LLM planning, real + cloud browser automation, two-way voice, SSE, a pausable gate state machine, triggered observability.
- **Ethical Considerations (new)** — the design *is* the ethics argument: over-gating costly/irreversible actions, the credential rule (the agent never types your password), never shipping PII to Sentry, fail-safe-and-tell-the-human. Load-bearing, not bolted on.
- **Brainstorming & Process (new)** — seam-based, offline-first build; a deliberate cut of the robot leg to go deep on three; documented design decisions; 22 tests. The opposite of a vibe-coded wrapper.

---

## 3-minute pitch script

**(0:00–0:30) The problem.** "Daily life runs on phone trees and web portals. If you're homebound or can't see a screen well, that locks you out of basic things — refilling a prescription, paying a bill. The agents being built today assume you can watch them work. The people who need help most can't."

**(0:30–1:00) The idea.** "Open Door does the legwork *and* talks to you — and it never does anything costly or irreversible without asking you first, out loud. Let me show you."

**(1:00–2:15) Live demo (Pharmacy card → Run).**
- "I'll just say what I need." *(speak the goal)*
- "It reasons about it — you can watch the plan." *(steps light up)*
- "It's working the real pharmacy portal right now." *(headed browser visible)*
- "Here's the moment that matters: it found the real cost, and it stops." *(red gate; the $14 question is spoken)*
- "I answer out loud." *(say "yes")* — "and only now does it submit."
- *(Optionally run once and say "no" — "and it stops, and tells me nothing was charged.")*

**(2:15–2:45) Why it's more than a demo.** "The gate is structural — the browser is parked on the submit button and physically can't proceed without a spoken yes. Every action is audited in Sentry. And the planner generalizes — here it is reasoning about a DMV renewal." *(DMV card → plan renders)*

**(2:45–3:00) The aspiration.** "This is a hard, unsolved, dignity-level problem. Open Door is our swing at making an agent powerful enough to act — and careful enough to ask first."

### Q&A prep (2 min)
- *"Is the gate real or theater?"* — Structural. The effector can't submit; dispatch only hands it the gated step after a human yes. Decline halts the plan.
- *"How does it generalize?"* — Planner is general today (shown on DMV); the browse leg is scripted to the demo portal and generalizes via natural-language navigation next.
- *"What about login/credentials?"* — The agent never types passwords (credential rule); the human does a one-time auth handoff for real sites.
- *"Reliability?"* — Self-healing browse, fail-safe halts captured in Sentry, 22 tests, 8/8 live health check.
