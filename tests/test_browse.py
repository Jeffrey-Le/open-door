"""
Integration test for the live browse leg.

Drives a real Chromium through the mock pharmacy portal loaded as a file:// fixture
(no server needed), exercising the same flow the demo uses: ensure signed in ->
find prescription -> read the real cost -> submit. Skips cleanly if Playwright or
its browser binary isn't installed, so the unit suite still runs anywhere.

This is the regression anchor for the deep technical leg: if a selector in
portal/mock_pharmacy.html drifts, this goes red before the demo does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.contracts import Effector, Risk, Step

playwright = pytest.importorskip("playwright.sync_api")

PORTAL = (Path(__file__).resolve().parent.parent / "portal" / "mock_pharmacy.html").as_uri()


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _browser_available(), reason="Chromium not installed (run: playwright install chromium)"
)


@pytest.fixture
def backend():
    from effectors.browse import BrowseBackend

    b = BrowseBackend(portal_url=PORTAL)
    yield b
    b.close()


def _step(action: str, **args) -> Step:
    risk = Risk.IRREVERSIBLE if action == "submit_refill" else Risk.SAFE
    return Step(effector=Effector.BROWSE, intent=action, args={"action": action, **args}, risk=risk)


def test_browse_drives_portal_end_to_end(backend):
    # find prescription (self-ensures sign-in first)
    found = backend.execute(_step("find_prescription", name="metformin")).result
    assert found["found"] is True
    assert "Metformin" in found["name"]

    # read the real out-of-pocket cost from the DOM
    refill = backend.execute(_step("check_refill")).result
    assert refill["copay"] == "$14.00"
    assert "mail-order" in refill["cost_note"].lower()

    # submit (the irreversible action) and read the confirmation back
    confirm = backend.execute(_step("submit_refill")).result
    assert confirm["confirmation_no"].startswith("BM")
    assert confirm["cost"] == "$14.00"


def test_find_prescription_self_ensures_signin(backend):
    """The browse leg must work even though the golden plan has no explicit
    open_portal step -- find_prescription signs in on its own."""
    result = backend.execute(_step("find_prescription")).result
    assert result["found"] is True
