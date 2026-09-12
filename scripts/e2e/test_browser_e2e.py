#!/usr/bin/env python3
"""E2E verification of the browser tool fixes (Pattern A / C / D) against a
real Chrome instance over CDP — replicating the exact failing scenarios from
the QA report (dropdown / login flows).

Requirements:
  * Chrome running with --remote-debugging-port=8222 (see e2e_supervisord.conf)
  * the local test pages served on :8900:
      cd scripts/e2e/browser_test_page && python3 -m http.server 8900
  * backend Python deps importable (repo venv)

Run from the repo root:
    python3 scripts/e2e/test_browser_e2e.py
"""
import asyncio
import faulthandler
import os
import sys
import pathlib

# Dump all thread tracebacks if the run stalls (event-loop deadlock detection).
faulthandler.dump_traceback_later(110, exit=True)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))

from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser

CDP = os.environ.get("E2E_CDP", "http://localhost:8222")
BASE = os.environ.get("E2E_TEST_PAGE", "http://localhost:8900/index.html")

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    detail = detail or ""
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""), flush=True)


async def step(coro_factory, timeout=60):
    """Run a tool call with a hard timeout so hangs are diagnosed, not fatal."""
    return await asyncio.wait_for(coro_factory(), timeout=timeout)


async def main():
    b = BrowserUseBrowser(CDP)

    # ── 1. navigate + view ────────────────────────────────────────────────
    nav = await step(lambda: b.navigate(BASE))
    record("navigate", nav.success, (nav.message or ""))
    view = await step(lambda: b.view_page())
    elems = (view.data or {}).get("interactive_elements", []) if view.data else []
    record("view_page has interactive elements", len(elems) > 0, f"{len(elems)} elements")

    select_idx = None
    btn_idx = None
    input_idx = None
    for e in elems:
        if "<select>" in e:
            select_idx = int(e.split(":")[0])
        if "<button>" in e and "login" in e.lower():
            btn_idx = int(e.split(":")[0])
        if "<input" in e:
            input_idx = int(e.split(":")[0])
    record("select index found", select_idx is not None, f"select={select_idx} button={btn_idx} input={input_idx}")

    # ── 2. Pattern A: get_select_options (was: CDP -32000 fail) ──────────
    if select_idx is not None:
        r = await step(lambda: b.get_select_options(select_idx))
        opts = (r.data or {}).get("options", []) if r.success else []
        record(
            "get_select_options returns native options",
            r.success and len(opts) >= 3,
            (r.message or "")[:90],
        )

    # ── 3. Pattern A: select_by_text (smart_select strategy 1) ───────────
    if select_idx is not None:
        r = await step(lambda: b.select_by_text(select_idx, "Option 2"))
        record("select_by_text 'Option 2'", r.success, (r.message or "")[:90])

    # ── 4. Pattern A: verify_value (was: CDP -32000 fail) ────────────────
    if select_idx is not None:
        r = await step(lambda: b.verify_value(select_idx, "Option 2"))
        record("verify_value after select", r.success, (r.message or "")[:90])

    # ── 5. Pattern A: click on submit button (was: all 3 strategies fail)
    if input_idx is not None:
        import time as _time
        print(f"[TS {_time.time():.1f}] before input", flush=True)
        r = await step(lambda: b.input("tomsmith", press_enter=False, index=input_idx))
        print(f"[TS {_time.time():.1f}] input returned", flush=True)
        record("input into username field", r.success, (r.message or "")[:90])
        print(f"[TS {_time.time():.1f}] before click", flush=True)
    if btn_idx is not None:
        r = await step(lambda: b.click(index=btn_idx), timeout=60)
        record("click Login button", r.success, (r.message or "")[:90])
        w = await step(
            lambda: b.wait_for_element(selector="#flash", text="You logged into a secure area!", timeout=5),
            timeout=20,
        )
        record("post-click flash message appeared", w.success, (w.message or "")[:90])

    # ── 6. Pattern D: console_exec with BARE JS (was: rejected) ──────────
    r = await step(lambda: b.console_exec("console.log('TEST_LOG_ALPHA'); console.warn('TEST_WARN_BETA'); 'exec-ok'"))
    record("console_exec with bare JS (auto-wrap)", r.success, str((r.data or {}).get("result"))[:60])

    # ── 7. Pattern C: console_view (was: always []) ───────────────────────
    r = await step(lambda: b.console_view())
    logs = (r.data or {}).get("logs", []) if r.success else []
    joined = " ".join(str(l) for l in logs)
    record(
        "console_view captures logs",
        r.success and "TEST_LOG_ALPHA" in joined and "TEST_WARN_BETA" in joined,
        f"{len(logs)} entries incl. PAGE_LOADED_MARKER={'PAGE_LOADED_MARKER' in joined}",
    )
    r = await step(lambda: b.console_view(max_lines=2))
    logs = (r.data or {}).get("logs", []) if r.success else []
    record("console_view max_lines=2", r.success and len(logs) == 2, f"{len(logs)} lines")

    # ── 8. Pattern D: back/forward then view (was: Empty DOM tree) ───────
    nav2 = await step(lambda: b.navigate(BASE.replace("index.html", "page2.html")))
    record("navigate to page 2", nav2.success, (nav2.message or "")[:60])
    back = await step(lambda: b.go_back(), timeout=45)
    record("go_back", back.success, (back.message or "")[:60])
    view = await step(lambda: b.view_page())
    content = (view.data or {}).get("content", "") if view.data else ""
    elems = (view.data or {}).get("interactive_elements", []) if view.data else []
    record(
        "view_page right after go_back is NOT empty",
        bool(content.strip()) or len(elems) > 0,
        f"content_len={len(content)} elems={len(elems)}",
    )
    fwd = await step(lambda: b.go_forward(), timeout=45)
    view = await step(lambda: b.view_page())
    content = (view.data or {}).get("content", "") if view.data else ""
    elems = (view.data or {}).get("interactive_elements", []) if view.data else []
    record(
        "view_page right after go_forward is NOT empty",
        fwd.success and (bool(content.strip()) or len(elems) > 0),
        f"content_len={len(content)} elems={len(elems)}",
    )

    await b.cleanup()

    failed = [n for n, ok, _ in results if not ok]
    print()
    print(f"TOTAL: {len(results)}  PASS: {sum(1 for _, ok, _ in results if ok)}  FAIL: {len(failed)}")
    if failed:
        print("FAILED:", failed)
        sys.stdout.flush()
        os._exit(1)
    print("ALL BROWSER E2E CHECKS PASSED")
    sys.stdout.flush()
    os._exit(0)


asyncio.run(main())
