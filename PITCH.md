# Open Door — recording script & framing

> DEVPOST.md was locked when this was written (likely open in an editor / iCloud sync).
> This is the up-to-date version — record from here, and paste into DevPost / merge into DEVPOST.md.

## The one-liner (lead with the person, not the feature)

> **Open Door is an AI agent that does the bureaucratic errands of daily life for people who can't — homebound, low-vision, elderly — and never spends their money or does anything irreversible without asking, out loud.**

Don't frame it as a to-do list or expense hub: a to-do app makes *you* do the task; Open Door *does it for you, by voice, for someone who can't.* The errands queue / connections / history are proof it's a **platform**, not a one-off — but the hero is **agent + voice + the gate that stops to ask.**

---

## 3-minute pitch script

**(0:00–0:30) The problem.** "Daily life runs on phone trees and web portals. If you're homebound or can't see a screen well, that locks you out of basic things — refilling a prescription, paying a bill. The agents being built today assume you can watch them work. The people who need help most can't."

**(0:30–0:55) The idea.** "Open Door is an agent for the bureaucratic errands of daily life — it keeps your to-do list, talks to you, works the web for you, and never does anything costly or irreversible without asking first, out loud. Let me show you."

**(0:55–2:15) Live demo — open on the Errands tab.**
- "Open Door keeps a to-do list of your daily chores — most urgent first." *(Errands queue visible)*
- "I'll have it pay this pharmacy refill — I can just talk to it." *(Run now, or speak the goal)*
- "It reasons about it — you watch the plan — and it's working the real portal now." *(steps light up; headed Chromium visible)*
- "Here's the moment that matters: it found the real cost, and it stops." *(red gate; the $14 question is spoken aloud)*
- "I answer out loud — yes." *(say "yes")* — "and only now does it submit. And it's logged in History." *(History tab — the record)*
- *(If time: run once and say "no" — "it stops, and tells me nothing was charged.")*

**(2:15–2:45) Why it's more than a demo.** "The gate is structural — the browser is physically parked on the submit button and can't proceed without a spoken yes. Every action is audited in Sentry. And the planner generalizes — here it is reasoning about a DMV renewal." *(DMV card → plan renders)*

**(2:45–3:00) The aspiration.** "This is a hard, unsolved, dignity-level problem. Open Door is our swing at making an agent powerful enough to act — and careful enough to ask first."

### Q&A prep (2 min)
- *"Is the gate real or theater?"* — Structural. The effector can't submit; dispatch only hands it the gated step after a human yes. Declining halts the rest of the plan.
- *"How does it generalize?"* — The planner is general today (shown on DMV); the browse leg is scripted to the demo portal and generalizes via natural-language web navigation next.
- *"Login/credentials?"* — The agent never types passwords (credential rule); the human does a one-time auth handoff for real sites.
- *"Are the portals real?"* — The demo uses a deterministic mock fixture; in production the browse leg drives the real site (Walgreens, your state DMV, your utility company).
- *"Reliability?"* — Self-healing browse, fail-safe halts captured in Sentry, 26 tests, 8/8 live health check.

---

## Where to submit

- **Grand prize (pick ONE):** aim for **Ddoski's World** (real-world impact / social good — best fit for the dignity story + the new Ethical-Considerations and Process criteria). Confirm the track description at the booth/Slack; fall back to whichever maps to impact/social-good, or **Ddoski's Lab** if it's purely technical.
- **Sponsor tracks (select all that apply):** **Best Use of Claude**, **Best Use of Deepgram**, **Best Use of Sentry API** — you use all three live. (No Browserbase track exists this year; it's bonus depth.)

## Recording tips
- Record in 2–3 segments (intro / demo / close), stitch in **iMovie** (or CapCut for captions). Don't chase one perfect take.
- Record the live demo 2–3 times; keep the cleanest run where the gate fires and your spoken "yes" lands.
- **Play app audio through speakers (not headphones)** and screen-record with **QuickTime + mic** — the mic captures both your narration and the app's spoken gate question in one track.
- Run `OPENDOOR_HEADED=1` so the Chromium window is visible parking on the gate.
