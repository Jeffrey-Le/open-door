"""
The browse leg: real web navigation with Playwright (Browserbase-ready).

This is Open Door's deep technical leg. It drives an actual Chromium through the
pharmacy portal -- sign in, find the prescription, read the real out-of-pocket
cost, and (only past the human gate) submit the irreversible refill. It returns
the SAME result shapes as effectors/mock.py, so dispatch, the gate, and the UI
never know whether they're talking to the mock or the real browser.

Two design points the project leans on:

  - OPEN SEAM TO BROWSERBASE. By default this launches a local Chromium (free,
    no key, great for dev + offline demo). If BROWSERBASE_API_KEY is set it
    instead connects over CDP to a Browserbase cloud session -- same Playwright
    code drives both. Local today, cloud by flipping one env var. No refactor.

  - STOP BEFORE SUBMIT. The backend will navigate and read freely (safe steps),
    but the submit click only happens when dispatch hands it the gated step --
    and dispatch only does that after a human yes. The effector itself never
    decides to submit.

Lifecycle: one backend instance per run holds a live page across that run's
browse steps; the registry calls close() when the run ends. Because Playwright's
sync API cannot run on an asyncio event-loop thread, the server drives each run's
ticks on a dedicated worker thread (see frontend/server.py).
"""

from __future__ import annotations

import os

from agent.contracts import Effector, Step
from agent.observability import instrument_step

# Default target is the mock portal the server hosts at /portal. Override with
# OPENDOOR_PORTAL_URL to point at a different (or real) site.
DEFAULT_PORTAL_URL = os.environ.get("OPENDOOR_PORTAL_URL", "http://127.0.0.1:8000/portal")

# How long to wait for a screen transition before treating the page as misbehaving.
_NAV_TIMEOUT_MS = 8000


def _action(step: Step) -> str:
    """Same resolution as the mock: explicit args['action'], else keyword match,
    so a loosely-specified plan from the planner still drives the real browser."""
    a = (step.args or {}).get("action")
    if a:
        return str(a)
    intent = step.intent.lower()
    if "submit" in intent or "finaliz" in intent or "place" in intent:
        return "submit_refill"
    if "cost" in intent or "price" in intent or "copay" in intent or "availab" in intent:
        return "check_refill"
    if "find" in intent or "look up" in intent or "search" in intent or "locate" in intent:
        return "find_prescription"
    return "open_portal"


class BrowseBackend:
    """Live Playwright backend for the BROWSE effector. One per run."""

    name = Effector.BROWSE

    def __init__(self, portal_url: str | None = None) -> None:
        self.portal_url = portal_url or DEFAULT_PORTAL_URL
        self._pw = None       # the Playwright context manager handle
        self._browser = None  # the Browser (local) or connection (Browserbase)
        self._page = None     # the live page, persisted across this run's steps
        self._opened = False  # whether we've reached the signed-in screen yet

    # -- browser lifecycle --------------------------------------------------

    def _ensure_page(self):
        """Lazily start the browser + page on first use. Local Chromium unless a
        Browserbase key is present, in which case connect to a cloud session."""
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        # Cloud is opt-in via OPENDOOR_BROWSE=cloud (explicit, not key-presence)
        # so a Browserbase key sitting in .env never silently routes the demo to
        # the cloud / spends credits. Local Chromium stays the default.
        use_cloud = os.environ.get("OPENDOOR_BROWSE", "").lower() in ("cloud", "browserbase")
        if use_cloud:
            # --- BROWSERBASE SEAM (cloud browser) ------------------------------
            # Create a session via the Browserbase SDK, then drive it with the
            # exact same Playwright code over CDP. Same selectors, same flow.
            from browserbase import Browserbase

            bb = Browserbase(api_key=os.environ["BROWSERBASE_API_KEY"])
            session = bb.sessions.create(project_id=os.environ["BROWSERBASE_PROJECT_ID"])
            self._browser = self._pw.chromium.connect_over_cdp(session.connect_url)
            context = self._browser.contexts[0]
            self._page = context.pages[0] if context.pages else context.new_page()
        else:
            # --- LOCAL CHROMIUM (default: free, no key) ------------------------
            headed = os.environ.get("OPENDOOR_HEADED") == "1"
            self._browser = self._pw.chromium.launch(headless=not headed)
            self._page = self._browser.new_page()
        self._page.set_default_timeout(_NAV_TIMEOUT_MS)
        return self._page

    def close(self) -> None:
        """Tear down the browser at run end. Safe to call more than once."""
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            self._page = self._browser = self._pw = None

    # -- the effector contract ---------------------------------------------

    @instrument_step
    def execute(self, step: Step) -> Step:
        page = self._ensure_page()
        action = _action(step)
        if action == "open_portal":
            step.result = self._open_portal(page, step)
        elif action == "find_prescription":
            step.result = self._find_prescription(page, step)
        elif action == "check_refill":
            step.result = self._check_refill(page)
        elif action == "submit_refill":
            step.result = self._submit_refill(page)  # IRREVERSIBLE -- post-gate only
        else:
            step.result = {"note": f"browse no-op for action {action!r}"}
        return step

    # -- portal flow (selectors mirror portal/mock_pharmacy.html) -----------

    def _ensure_portal(self, page, url: str | None = None) -> None:
        """Make sure we're on the signed-in prescriptions screen before acting.
        Idempotent, so any browse step works whether or not a prior step opened
        the portal -- and it doubles as recovery if the page lost its place."""
        if self._opened and page.is_visible("#screen-list"):
            return
        page.goto(url or self.portal_url, wait_until="domcontentloaded")
        # Per the credential rule, Open Door does NOT type credentials. The mock
        # treats sign-in as pre-authenticated; a real portal would have the human
        # complete login. We only advance past the pre-authed sign-in screen.
        page.click("#signin-btn")
        page.wait_for_selector("#screen-list", state="visible")
        self._opened = True

    def _open_portal(self, page, step: Step) -> dict:
        self._ensure_portal(page, (step.args or {}).get("url"))
        return {"screen": "list", "signed_in_as": page.inner_text(".crumb").strip()}

    def _find_prescription(self, page, step: Step) -> dict:
        self._ensure_portal(page, (step.args or {}).get("url"))
        name = (step.args or {}).get("name", "metformin")
        page.fill("#rx-search", name)
        # This mock fixture holds ONE prescription (metformin). If the requested
        # drug filtered it out of view, clear the search so we still open the
        # prescription that exists rather than timing out. (A real portal would
        # have the actual drug; this keeps the demo resilient to any goal.)
        card = page.query_selector("#rx-metformin")
        if not card or not card.is_visible():
            page.fill("#rx-search", "")
        card = page.wait_for_selector("#rx-metformin", state="visible")
        rx_name = card.query_selector(".name").inner_text().strip()
        meta = card.query_selector(".meta").inner_text().strip()
        page.click("#open-metformin")
        page.wait_for_selector("#screen-refill", state="visible")
        return {"found": True, "name": rx_name, "meta": meta}

    def _ensure_refill_screen(self, page) -> None:
        """Make sure we're on the refill-detail screen before reading the cost or
        submitting. If an earlier (mis-routed) step reset the page, navigate back:
        sign in -> find metformin -> open its refill. Idempotent recovery, so the
        core refill still completes even when the plan has stray steps the mock
        portal doesn't support."""
        if self._opened and page.is_visible("#screen-refill"):
            return
        self._ensure_portal(page)  # gets us to the signed-in list screen if needed
        page.fill("#rx-search", "metformin")
        page.wait_for_selector("#rx-metformin", state="visible")
        page.click("#open-metformin")
        page.wait_for_selector("#screen-refill", state="visible")

    def _check_refill(self, page) -> dict:
        self._ensure_refill_screen(page)
        page.wait_for_selector("#copay", state="visible")
        return {
            "availability": page.inner_text("#availability").strip(),
            "copay": page.inner_text("#copay").strip(),
            "cost_note": page.inner_text("#cost-note").strip(),
        }

    def _submit_refill(self, page) -> dict:
        # The IRREVERSIBLE action. Reached only because dispatch handed us the
        # gated step, which it does only after a human yes.
        self._ensure_refill_screen(page)
        page.click("#refill-submit")
        page.wait_for_selector("#screen-confirm", state="visible")
        rows = self._read_rows(page, "#screen-confirm")
        return {
            "confirmation_no": page.inner_text("#confirm-no").strip(),
            "cost": rows.get("Cost", ""),
            "ready_by": rows.get("Ready", ""),
            "pickup": rows.get("Pickup", ""),
        }

    @staticmethod
    def _read_rows(page, container: str) -> dict[str, str]:
        """Map each .row's label (.k) to its value (.v) in a container, so we
        read fields by name rather than by brittle positional selectors."""
        out: dict[str, str] = {}
        for row in page.query_selector_all(f"{container} .row"):
            k = row.query_selector(".k")
            v = row.query_selector(".v")
            if k and v:
                out[k.inner_text().strip()] = v.inner_text().strip()
        return out
