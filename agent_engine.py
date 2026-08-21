"""Agent engine: wires together the three cognitive roles + Ledger + actions.

Implements Algorithm 1 from RunAgent SuperBrowser (§4.1):

    classify task via Orchestrator
    init Ledger
    for step in 1..MAX_STEPS:
        observe page
        if step % N == 0 OR worker signals done:
            run Planner -> may declare done
        run Worker -> emit 1 action
        execute action, update Ledger
        if captcha: auto-pivot, mark dead_end
"""
import os
import time
from dataclasses import dataclass
from typing import Callable

from playwright.sync_api import sync_playwright

from action_layer import (
    create_stealth_page,
    create_stealth_page_firefox,
    execute_action,
    extract_page_context,
    is_captcha_page,
)
from cognitive_layer import (
    run_orchestrator,
    run_planner,
    run_worker_first_step,
    run_worker_next_step,
)
from llm_providers import LLMProvider, LLMConfig, create_llm_provider, get_rate_limiter
from memory import Ledger, StepOutcome


# Tunables
MAX_STEPS = 8
PLANNER_INTERVAL = 3  # Run planner every N worker steps
FAILED_CLICK_THRESHOLD = 2
FALLBACK_URLS = [
    "https://duckduckgo.com/",
    "https://www.bing.com/",
    "https://en.wikipedia.org/",
]
VERIFICATION_SEARCH_URL = "https://www.google.com/search?q="  # Google search for verification


def search_and_verify(page, query: str, log) -> str:
    """Search Google to verify if something exists. Returns the search results text."""
    log(f"[VERIFICATION] Searching Google for: {query}")
    search_url = VERIFICATION_SEARCH_URL + query.replace(" ", "+")
    try:
        page.goto(f"https://www.google.com/search?q={query.replace(' ', '+')}", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        # Wait for search results
        try:
            page.wait_for_selector('#search, #rso, .g, .tF2Cxc', timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        text = extract_page_context(page).get("text", "")
        log(f"[VERIFICATION] Search results length: {len(text)} chars")
        return text
    except Exception as e:
        log(f"[VERIFICATION] Search failed: {e}")
        return ""


@dataclass
class EngineConfig:
    max_steps: int = MAX_STEPS
    headless: bool = False
    rate_limit_per_min: int = 15
    # Browser selection. 'chromium' (default) uses Playwright's bundled build.
    # 'helium', 'chrome', 'edge', 'brave' use system-installed browsers.
    # 'firefox' uses Firefox (loses some stealth tricks).
    browser: str = "chromium"
    executable_path: str | None = None  # auto-detected if browser != 'chromium'
    channel: str | None = None  # for p.chromium.launch(channel=...)
    # If True, the engine does NOT close the browser in its finally block —
    # useful for the web UI where you want to keep interacting with the page.
    keep_browser_open: bool = False
    # Model name (passed to cognitive layer)
    model: str = "gemini-3.5-flash-lite"
    # Provider type for rate limiting
    provider_type: str = "gemini"


def _classify_search_intent(text: str) -> bool:
    """Heuristic: if the page text looks like a search-results page and
    contains no obvious answer, the search 'failed'."""
    keywords_no_results = [
        "no results found", "did not match any", "0 results",
        "no videos found", "no posts found", "no matches",
    ]
    text_low = text.lower()
    return any(k in text_low for k in keywords_no_results)


def run_session(
    goal: str,
    provider: LLMProvider,
    config: EngineConfig,
    log: Callable[[str], None] = print,
    is_continuation: bool = False,
    start_context: dict | None = None,
) -> dict:
    """Run one full session and return:
       {status: "done"|"exhausted"|"blocked"|"error",
        final_answer: str,
        ledger: Ledger,
        steps: int,
        browser_obj, playwright_obj (only if keep_browser_open=True)}
    """
    rate_limiter = get_rate_limiter(config.provider_type)
    ledger = Ledger(goal=goal)
    status = "exhausted"
    final_answer = ""

    with sync_playwright() as p:
        if config.browser == "cdp":
            # Connect to an already-running browser via CDP
            cdp_url = config.executable_path or os.environ.get("CDP_URL", "http://localhost:9222")
            log(f"[CDP] Connecting to {cdp_url} ...")
            browser = p.chromium.connect_over_cdp(cdp_url)
            # For CDP, we don't control the browser context — it's the user's.
            # Just pick the first context/page or create a new one.
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
                pages = context.pages
                page = pages[0] if pages else context.new_page()
            else:
                context = browser.new_context()
                page = context.new_page()
            # CDP browser is externally managed — don't close it in finally.
            config.keep_browser_open = True
        else:
            log(f"Launching browser with stealth profile...")
            browser = p.chromium.launch(
                headless=config.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            page = create_stealth_page(browser, headless=config.headless)

        provider_used = config.provider_type
        provider_fallback = False
        
        try:
            status, final_answer, step_count, context = _run_session_inner(
                p, browser, page, goal, provider, config, rate_limiter,
                ledger, log, is_continuation, start_context,
            )
        except Exception as e:
            # Check if we should fallback from NVIDIA to Gemini
            # Fall back on any error when using NVIDIA, including auth errors
            if config.provider_type == "nvidia":
                log(f"[ENGINE] NVIDIA provider failed: {e}. Falling back to Gemini...")
                provider_used = "gemini"
                provider_fallback = True
                # Create Gemini provider
                os.environ["api_provider"] = "gemini"
                provider = create_llm_provider()
                rate_limiter = get_rate_limiter("gemini")
                # Retry with Gemini
                status, final_answer, step_count, context = _run_session_inner(
                    p, browser, page, goal, provider, config, rate_limiter,
                    ledger, log, is_continuation, start_context,
                )
            else:
                raise
        finally:
            if not config.keep_browser_open:
                try:
                    browser.close()
                    log("Browser closed.")
                except Exception:
                    pass
            else:
                log("[UI mode] Browser left open. Close it manually when done.")

    result = {
        "status": status,
        "final_answer": final_answer,
        "ledger": ledger,
        "steps": step_count,
        "last_context": context,
        "provider_used": provider_used,
        "provider_fallback": provider_fallback,
    }

    return result


def _run_session_inner(p, browser, page, goal, provider, config,
                       rate_limiter, ledger, log,
                       is_continuation, start_context):
    """The actual cognitive-action-perception loop, isolated for clarity."""
    status = "exhausted"
    final_answer = ""
    step_count = 0
    context = None

    try:
        # ----- Orchestrator: route the task -----
        if not is_continuation:
            orch = run_orchestrator(provider, goal, rate_limiter)
            route = orch.get("route", "browser")
            log(f"[ORCHESTRATOR] route={route} "
                f"confidence={orch.get('confidence', '?')} "
                f"reason={orch.get('reasoning', '')}")
            if route == "search":
                log("[ORCHESTRATOR] Lightweight search routing not "
                    "implemented; opening browser.")
            ledger.note(f"orchestrator: route={route}")

        # ----- Page state: either reuse (continuation) or pick starting URL -----
        context = start_context
        last_action = {"action": "(none)"}
        last_result = {"success": True, "note": "session start"}
        failed_selectors: dict[str, int] = {}
        captcha_count = 0

        if context is None:
            # First worker step: pick a starting URL
            decision = run_worker_first_step(provider, goal, rate_limiter)
            action_type = decision.get("action", "navigate")
            url = decision.get("url", "")
            log(f"[WORKER #1] {action_type} -> {url} "
                f"({decision.get('reasoning', '')})")
            ok, note = execute_action(
                page, {"action": "navigate", "url": url}, log
            )
            last_action = {"action": "navigate", "url": url}
            last_result = {"success": ok, "note": note}
            ledger.record_action(StepOutcome(
                action="navigate", target=url, success=ok,
                url=url, note=note,
            ))

        # ----- Main cognitive-action-perception loop -----
        step_count = 0
        for step in range(1, config.max_steps + 1):
            step_count = step
            log(f"\n========== STEP {step}/{config.max_steps} ==========")

            context = extract_page_context(page)
            log(f"-- PERCEPTION: title={context['title']!r} url={context['url']}")

            # ----- Planner (every N steps, or after Worker 'done') -----
            run_planner_now = (
                step == 1
                or step % 3 == 0
                or last_action.get("action") == "done"
            )
            next_steps: list[str] = []
            if run_planner_now:
                plan = run_planner(provider, goal, ledger, context, last_action, last_result, rate_limiter)
                verdict = plan.get("verdict", "continue")
                log(f"[PLANNER] verdict={verdict} "
                    f"reasoning={plan.get('reasoning', '')}")
                if verdict in ("done", "abandon"):
                    final_answer = plan.get(
                        "final_answer",
                        "Goal could not be completed within the step budget."
                    )
                    status = "done" if verdict == "done" else "abandoned"
                    log(f"\n*** AGENT FINAL ANSWER: {final_answer} ***")
                    break
                next_steps = plan.get("next_steps", []) or []
                ledger.set_subgoal(plan.get("reasoning", ""))

            # ----- Worker: emit one action -----
            decision = run_worker_next_step(provider, goal, ledger, context, next_steps, rate_limiter)
            action = decision.get("action", "navigate")
            log(f"[WORKER] {action} -- {decision.get('reasoning', '')}")

            # Worker can also declare done (with an answer)
            if action == "done":
                final_answer = decision.get(
                    "answer",
                    decision.get("reasoning", "Goal achieved.")
                )
                status = "done"
                log(f"\n*** AGENT FINAL ANSWER: {final_answer} ***")
                break

            # ----- Throttle failed selectors -----
            if action == "click":
                sel = decision.get("selector", "")
                if sel and failed_selectors.get(sel, 0) >= 2:
                    log(f"[SKIP] '{sel}' failed "
                        f"{failed_selectors[sel]}x — asking worker to retry")
                    ledger.mark_dead_end(
                        f"click selector '{sel}' kept failing",
                        context.get("url", ""),
                        cause="stale_selector",
                        step=step,
                    )
                    last_action = {"action": "click", "selector": sel}
                    last_result = {"success": False, "note": "skipped (too many failures)"}
                    continue

            # ----- Execute -----
            if action == "search_google":
                query = decision.get("query", "")
                log(f"[VERIFICATION] Searching Google for: {query}")
                search_results = search_and_verify(page, query, log)
                ok = bool(search_results)
                note = f"Search results: {search_results[:500]}..." if search_results else "No results found"
            else:
                ok, note = execute_action(page, decision, log)

            last_action = {
                "action": action,
                "selector": decision.get("selector", ""),
                "url": decision.get("url", ""),
                "text": decision.get("text", ""),
            }
            last_result = {"success": ok, "note": note}

            if action == "click" and not ok:
                sel = decision.get("selector", "")
                failed_selectors[sel] = failed_selectors.get(sel, 0) + 1
            if action == "navigate":
                failed_selectors.clear()

            ledger.record_action(StepOutcome(
                action=action,
                target=decision.get("selector") or decision.get("url") or "",
                success=ok,
                url=context.get("url", ""),
                note=note,
            ))

            # ----- Not-found detection -----
            if action == "navigate":
                text_now = extract_page_context(page).get("text", "")
                if _classify_search_intent(text_now):
                    ledger.mark_dead_end(
                        f"search query {decision.get('url','')[:80]} returned no results",
                        page.url,
                        cause="not_found",
                        step=step,
                    )
                    log("[DEAD-END] Search returned no results — recorded.")

            # ----- Captcha auto-pivot -----
            context_after = extract_page_context(page)
            if is_captcha_page(context_after):
                captcha_count += 1
                log(f"[CAPTCHA] block #{captcha_count} — pivoting")
                ledger.mark_dead_end(
                    "captcha / bot-block page",
                    page.url,
                    cause="bot_block",
                    step=step,
                )
                if captcha_count >= 2:
                    status = "blocked"
                    final_answer = "Blocked by repeated CAPTCHA. Try a different site."
                    break
                fb = FALLBACK_URLS[(captcha_count - 1) % len(FALLBACK_URLS)]
                page.goto(fb, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)

        else:
            # Loop completed without break → ask user if they want to continue
            if not final_answer:
                final_answer = "Reached max steps without a final answer."
            
            # Check if user wants to continue (only in non-headless mode)
            if not config.headless:
                status = "exhausted"
                final_answer += "\n\n[Press ENTER to continue with more steps, or type 'q' to quit]"
                # The web_ui will handle the continue logic

    except Exception as e:
        log(f"[engine error] {e}")
        raise
        final_answer = f"Engine error: {e}"

    return status, final_answer, step_count, context