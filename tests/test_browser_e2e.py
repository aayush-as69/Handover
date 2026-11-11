"""Real-browser walkthrough against a live server (skipped when Chromium is unavailable)."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

PW = "handover123"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def live_server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    db = os.path.join(tempfile.mkdtemp(), "e2e.db")
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "DEMO_MODE": "1", "DEMO_PASSWORD": PW,
           "SECRET_KEY": "e" * 40, "APP_ENV": "development", "COOKIE_SECURE": "false"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
                             "--log-level", "warning"], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            pytest.fail("server did not start")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium unavailable: {exc}")
        yield b
        b.close()


def sign_in(page, base, user):
    page.goto(base + "/login")
    page.fill("input[name=username]", user)
    page.fill("input[name=password]", PW)
    page.click("button:has-text('Sign in')")
    page.wait_for_url(lambda u: "/login" not in u)


def test_reviewer_signs_off_and_viewer_reads_and_acknowledges(live_server, browser):
    base = live_server
    boss = browser.new_context().new_page()
    sign_in(boss, base, "meera")
    boss.goto(base + "/review?status=open&confidence=verified")
    boss.click("table a >> nth=0")
    boss.click("button:has-text('Approve')")
    assert "approved" in boss.content().lower()

    # Before sign-off the viewer sees nothing.
    kabir = browser.new_context().new_page()
    sign_in(kabir, base, "kabir")
    kabir.goto(base + "/handover")
    assert "I have read this handover" not in kabir.content()

    boss.goto(base + "/handover")
    boss.click("text=Sign off handover")
    assert "release 1" in boss.content().lower()

    kabir.goto(base + "/handover")
    assert "I have read this handover" in kabir.content()
    kabir.click("text=I have read this handover")
    assert "You have acknowledged this handover." in kabir.content()

    # A reviewer edit after sign-off makes the release stale for the viewer.
    boss.goto(base + "/review?status=approved")
    boss.click("table a >> nth=0")
    boss.click("text=Reopen")
    kabir.goto(base + "/handover")
    assert "I have read this handover" not in kabir.content()


def test_demo_role_selection_prefills_username_and_password(live_server, browser):
    page = browser.new_page()
    page.goto(live_server + "/login")
    page.locator('[data-demo-user="meera"]').click()
    assert page.locator("#login-username").input_value() == "meera"
    assert page.locator("#login-password").input_value() == PW
    assert page.locator('[data-demo-user="meera"]').get_attribute("aria-pressed") == "true"
    assert "Press Sign in to continue" in page.locator("#demo-selection-status").inner_text()

    # Selecting another member replaces both fields but never submits the form.
    page.locator('[data-demo-user="kabir"]').click()
    assert page.locator("#login-username").input_value() == "kabir"
    assert page.locator("#login-password").input_value() == PW
    assert page.url.endswith("/login")

    # The visitor still explicitly submits the existing CSRF-protected form.
    page.locator("#sign-in-form button[type='submit']").click()
    page.wait_for_url("**/handover")
    assert page.url.endswith("/review") or page.url.endswith("/handover")
    page.close()


def test_review_queue_search_filters_and_restores_claims(live_server, browser):
    page = browser.new_page()
    sign_in(page, live_server, "meera")
    page.goto(live_server + "/review?status=all")
    rows = page.locator("#claims-table-body [data-search-item]")
    original_count = rows.count()
    if original_count == 0:
        pytest.skip("synthetic dataset has no visible claims")
    search = page.locator('[data-live-search][data-search-target="#claims-table-body"]')
    search.fill("no-claim-should-match-this-phrase")
    assert page.locator("#claims-table-body [data-search-item]:visible").count() == 0
    assert page.locator("#claims-table-body [data-search-empty]").is_visible()
    search.fill("")
    assert page.locator("#claims-table-body [data-search-item]:visible").count() == original_count
    assert not page.locator("#claims-table-body [data-search-empty]").is_visible()
    page.close()


def test_mobile_login_layout_and_accessible_fields(live_server, browser):
    page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
    page.goto(live_server + "/login")
    assert page.get_by_role("heading", name="Welcome back.").is_visible()
    assert page.get_by_label("Username").is_visible()
    assert page.get_by_role("textbox", name="Password").is_visible()
    assert page.get_by_role("group", name="Choose a demo account").is_visible()
    dimensions = page.evaluate(
        "() => ({width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth})"
    )
    assert dimensions["scroll"] <= dimensions["width"], dimensions
    page.close()
