"""Agent engine: wires together the three cognitive roles + Ledger + actions (async version).

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

Vision integration (SeeAct style, §4.3, §6.1):
    - Capture screenshot + Set-of-Marks (SoM) annotation
    - Vision-Language Model grounds action to element ID
    - Execute coordinate-based click via vision_click

Stagehand integration (§4.3, §6.1):
    - Use Stagehand's act() for reliable natural language actions
    - Fallback to vision pipeline if Stagehand unavailable
"""
import os
import tempfile
from dataclasses import dataclass
from typing import Callable

from playwright.async_api import async_playwright

from action_layer import (
    create_stealth_page,
    create_stealth_page_firefox,
    execute_action,
    extract_page_context,
    is_captcha_page,
    build_vision_context,
    extract_elements_with_bbox,
)
from cognitive_layer import (
    run_orchestrator,
    run_planner,
    run_worker_first_step,
    run_worker_next_step,
    run_worker_vision_step,
    run_vision_grounding,
)
from llm_providers import LLMProvider, LLMConfig, create_llm_provider, get_rate_limiter, create_vision_provider
from memory import Ledger, StepOutcome
from stagehand_layer import StagehandLayer, StagehandConfig, STAGEHAND_AVAILABLE
FAILED_CLICK_THRESHOLD = 2
FALLBACK_URLS = [
    "https://duckduckgo.com/",
    "https://www.bing.com/",
    "https://en.wikipedia.org/",
]
VERIFICATION_SEARCH_URL = "https://www.google.com/search?q="  # Google search for verification


async def search_and_verify(page, query: str, log) -> str:
    """Search Google to verify if something exists. Returns the search results text."""
    log(f"[VERIFICATION] Searching Google for: {query}")
    try:
        await page.goto(f"https://www.google.com/search?q={query.replace(' ', '+')}", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)
        # Wait for search results
        try:
            await page.wait_for_selector('#search, #rso, .g, .tF2Cxc', timeout=8000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        text = (await extract_page_context(page)).get("text", "")
        log(f"[VERIFICATION] Search results length: {len(text)} chars")
        return text
    except Exception as e:
        log(f"[VERIFICATION] Search failed: {e}")
        return ""


def _classify_search_intent(text: str) -> bool:
    """Heuristic: if the page text looks like a search-results page and
    contains no obvious answer, the search 'failed'."""
    keywords_no_results = [
        "no results found", "did not match any", "0 results",
        "no videos found", "no posts found", "no matches",
    ]
    text_low = text.lower()
    return any(k in text_low for k in keywords_no_results)


@dataclass
class EngineConfig:
    max_steps: int = 8
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
    # Vision settings
    use_vision: bool = False
    vision_model: str = "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"


async def run_session(
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
    # Use SEPARATE rate limiters for text and vision since they have different limits
    # Text: 1 req/min, Vision: 1 req/2min (free tier NVIDIA Build is very aggressive)
    rate_limiter = get_rate_limiter(config.provider_type)
    vision_rate_limiter = get_rate_limiter("vision")
    ledger = Ledger(goal=goal)
    status = "exhausted"
    final_answer = ""

    # Create vision provider if vision is enabled
    vision_provider = None
    if config.use_vision:
        try:
            vision_provider = create_vision_provider()
            log("[ENGINE] Vision provider initialized")
        except Exception as e:
            log(f"[ENGINE] Failed to create vision provider: {e}. Disabling vision.")
            config.use_vision = False

    async with async_playwright() as p:
        if config.browser == "cdp":
            # Connect to an already-running browser via CDP
            cdp_url = config.executable_path or os.environ.get("CDP_URL", "http://localhost:9222")
            log(f"[CDP] Connecting to {cdp_url} ...")
            browser = await p.chromium.connect_over_cdp(cdp_url)
            # For CDP, we don't control the browser context — it's the user's.
            # Just pick the first context/page or create a new one.
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
                pages = context.pages
                page = pages[0] if pages else await context.new_page()
            else:
                context = await browser.new_context()
                page = await context.new_page()
            # CDP browser is externally managed — don't close it in finally.
            config.keep_browser_open = True
        else:
            log(f"Launching browser with stealth profile...")
            browser = await p.chromium.launch(
                headless=config.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            page = await create_stealth_page(browser, headless=config.headless)

        # Initialize Stagehand layer for reliable browser actions
        stagehand_layer = None
        if STAGEHAND_AVAILABLE:
            stagehand_config = StagehandConfig(
                model_name="moonshotai/kimi-k3",
                api_key=os.getenv("nvidia_api_key", ""),
                base_url="https://integrate.api.nvidia.com/v1",
                timeout=30000,
                enable_cache=False,
            )
            stagehand_layer = StagehandLayer(page, stagehand_config, log)
            initialized = await stagehand_layer.initialize()
            if not initialized:
                log("[STAGEHAND] Initialization failed, falling back to native actions")
                stagehand_layer = None
            else:
                log("[STAGEHAND] Initialized successfully")
        else:
            stagehand_layer = None

        provider_used = config.provider_type
        provider_fallback = False
        
        try:
            status, final_answer, step_count, context = await _run_session_inner(
                p, browser, page, goal, provider, config, rate_limiter,
                vision_provider, vision_rate_limiter, ledger, log, is_continuation, start_context,
                stagehand_layer,
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
                vision_rate_limiter = get_rate_limiter("vision")
                # Retry with Gemini
                status, final_answer, step_count, context = await _run_session_inner(
                    p, browser, page, goal, provider, config, rate_limiter,
                    vision_provider, vision_rate_limiter, ledger, log, is_continuation, start_context,
                    stagehand_layer,
                )
            else:
                raise
        except ValueError as e:
            # Handle JSON parse errors from NVIDIA provider
            if config.provider_type == "nvidia" and "JSON parse failed" in str(e):
                log(f"[ENGINE] NVIDIA JSON parse error: {e}. Falling back to Gemini...")
                provider_used = "gemini"
                provider_fallback = True
                os.environ["api_provider"] = "gemini"
                provider = create_llm_provider()
                rate_limiter = get_rate_limiter("gemini")
                vision_rate_limiter = get_rate_limiter("vision")
                status, final_answer, step_count, context = await _run_session_inner(
                    p, browser, page, goal, provider, config, rate_limiter,
                    vision_provider, vision_rate_limiter, ledger, log, is_continuation, start_context,
                    stagehand_layer,
                )
            else:
                raise
        finally:
            if not config.keep_browser_open:
                try:
                    await browser.close()
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


async def _run_session_inner(p, browser, page, goal, provider, config,
                       rate_limiter, vision_provider, vision_rate_limiter, ledger, log,
                       is_continuation, start_context, stagehand_layer=None):
    """The actual cognitive-action-perception loop, isolated for clarity."""
    status = "exhausted"
    final_answer = ""
    step_count = 0
    context = None

    try:
        # ----- Orchestrator: route the task -----
        if not is_continuation:
            orch = await run_orchestrator(provider, goal, rate_limiter)
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
            decision = await run_worker_first_step(provider, goal, rate_limiter)
            action_type = decision.get("action", "navigate")
            url = decision.get("url", "")
            log(f"[WORKER #1] {action_type} -> {url} "
                f"({decision.get('reasoning', '')})")
            ok, note = await execute_action(
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
        
        # Vision loop detection
        recent_vision_actions: list[tuple] = []  # (element_id, action, text)
        MAX_VISION_REPEATS = 3
        
        for step in range(1, config.max_steps + 1):
            step_count = step
            log(f"\n========== STEP {step}/{config.max_steps} ==========")

            # ----- Perception: extract page context + vision context -----
            context = await extract_page_context(page)
            log(f"-- PERCEPTION: title={context['title']!r} url={context['url']}")
            
            # Build vision context if vision is enabled (for Worker's planning)
            if config.use_vision and vision_provider:
                log("[VISION] Building vision context (screenshot + SoM)...")
                try:
                    vision_context = await build_vision_context(page, goal, ledger.render_for_worker())
                    context["annotated_screenshot_bytes"] = vision_context["annotated_screenshot_bytes"]
                    context["vision_elements"] = vision_context["elements"]
                    context["viewport_width"] = vision_context["viewport_width"]
                    context["viewport_height"] = vision_context["viewport_height"]
                    log(f"[VISION] Found {len(vision_context['elements'])} interactive elements")
                    
                    # DEBUG: Log vision elements with bounding boxes
                    log("[VISION DEBUG] Elements list:")
                    for el in vision_context["elements"]:
                        eid = el.get("id", "?")
                        bbox = el.get("bbox", [0,0,0,0])
                        x, y, w, h = bbox
                        text = el.get("text", "")[:50]
                        role = el.get("role", "")
                        selector = el.get("selector", "")[:60]
                        log(f"  [{eid}] {role} '{text}' @ ({x:.3f},{y:.3f},{w:.3f},{h:.3f}) sel={selector}")
                    
                    # DEBUG: Save annotated screenshot for visual inspection
                    try:
                        import tempfile
                        debug_path = f"/tmp/vision_som_step_{step}.png"
                        with open(debug_path, "wb") as f:
                            f.write(vision_context["annotated_screenshot_bytes"])
                        log(f"[VISION DEBUG] SoM screenshot saved to {debug_path}")
                    except Exception as e:
                        log(f"[VISION DEBUG] Failed to save screenshot: {e}")
                except Exception as e:
                    log(f"[VISION] Failed to build vision context: {e}")
                    config.use_vision = False
            
            # ----- Planner (every N steps, or after Worker 'done') -----
            run_planner_now = (
                step == 1
                or step % 3 == 0
                or last_action.get("action") == "done"
            )
            next_steps: list[str] = []
            if run_planner_now:
                plan = await run_planner(provider, goal, ledger, context, last_action, last_result, rate_limiter)
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
            if config.use_vision and vision_provider and context.get("vision_elements"):
                # Two-step SeeAct: Worker plans → Vision grounds
                log("[WORKER] Planning with vision context...")
                
                # Build interactive elements text for worker
                elements_for_worker = []
                for el in context["vision_elements"]:
                    eid = el.get("id", 0)
                    text = el.get("text", "")[:60]
                    tag = el.get("tag", "")
                    role = el.get("role", "")
                    href = el.get("href", "")[:80]
                    elements_for_worker.append(f"  [{eid}] {role} {tag}: '{text}' {href}")
                interactive_text = "\n".join(elements_for_worker) if elements_for_worker else "  (no interactive elements detected)"
                
                # Step 1: Worker decides action + target_description
                worker_decision = await run_worker_vision_step(
                    provider, goal, ledger, context, next_steps, interactive_text, rate_limiter
                )
                
                action = worker_decision.get("action", "scroll")
                target_description = worker_decision.get("target_description", "")
                v_text = worker_decision.get("text", "")
                press_key = worker_decision.get("press_key", "Enter")
                url = worker_decision.get("url", "")
                reasoning = worker_decision.get("reasoning", "")
                
                log(f"[WORKER] action={action} target='{target_description[:80]}' reasoning={reasoning}")
                
                if action == "done":
                    final_answer = worker_decision.get("answer", reasoning)
                    status = "done"
                    log(f"\n*** AGENT FINAL ANSWER: {final_answer} ***")
                    break
                
                if action == "navigate":
                    decision = {"action": "navigate", "url": url, "reasoning": reasoning}
                elif action == "scroll":
                    decision = {"action": "scroll", "scroll_pixels": 500, "reasoning": reasoning}
                elif action in ("click", "type"):
                    # Use Stagehand for reliable actions when available
                    if stagehand_layer:
                        log(f"[STAGEHAND] Executing {action}: {target_description}")
                        stagehand_result = await stagehand_layer.act(target_description, log=log)
                        if stagehand_result.get("success"):
                            # Stagehand succeeded, create decision to mark as done
                            decision = {
                                "action": action,
                                "stagehand_success": True,
                                "stagehand_result": stagehand_result,
                                "reasoning": reasoning
                            }
                            # Skip vision grounding, Stagehand handled it
                        else:
                            log(f"[STAGEHAND] Failed: {stagehand_result.get('error')}, falling back to vision")
                            # Fall back to vision grounding
                            vision_decision = await run_vision_grounding(
                                vision_provider, 
                                worker_intent=target_description,
                                goal=goal,
                                ledger=ledger,
                                page_context=context,
                                elements=context["vision_elements"],
                                rate_limiter=vision_rate_limiter
                            )
                            element_id = vision_decision.get("element_id", -1)
                            confidence = vision_decision.get("confidence", 0.0)
                            v_reasoning = vision_decision.get("reasoning", "")
                            
                            log(f"[VISION GROUNDING] element_id={element_id} confidence={confidence:.2f} reasoning={v_reasoning}")
                            
                            if element_id >= 0 and element_id < len(context["vision_elements"]) and confidence > 0.3:
                                target = context["vision_elements"][element_id]
                                if action == "click":
                                    decision = {
                                        "action": "vision_click",
                                        "element_id": element_id,
                                        "elements": context["vision_elements"],
                                        "viewport_width": context.get("viewport_width", 1366),
                                        "viewport_height": context.get("viewport_height", 768),
                                        "reasoning": reasoning + " | " + v_reasoning
                                    }
                                elif action == "type":
                                    decision = {
                                        "action": "vision_type",
                                        "element_id": element_id,
                                        "elements": context["vision_elements"],
                                        "viewport_width": context.get("viewport_width", 1366),
                                        "viewport_height": context.get("viewport_height", 768),
                                        "text": v_text,
                                        "press_key": press_key,
                                        "reasoning": reasoning + " | " + v_reasoning
                                    }
                                else:
                                    action = "scroll"
                                    decision = {"action": "scroll", "scroll_pixels": 500, "reasoning": "vision fallback"}
                            else:
                                log(f"[VISION] Low confidence ({confidence:.2f}) or no match - falling back to scroll")
                                action = "scroll"
                                decision = {"action": "scroll", "scroll_pixels": 500, "reasoning": "vision: no confident match"}
                            # No Stagehand, use vision pipeline
                        # Step 2: Vision grounds target_description to element_id
                        log("[VISION] Grounding worker intent to element...")
                        vision_decision = await run_vision_grounding(
                            vision_provider, 
                            worker_intent=target_description,
                            goal=goal,
                            ledger=ledger,
                            page_context=context,
                            elements=context["vision_elements"],
                            rate_limiter=vision_rate_limiter
                        )
                        
                        element_id = vision_decision.get("element_id", -1)
                        confidence = vision_decision.get("confidence", 0.0)
                        v_reasoning = vision_decision.get("reasoning", "")
                        
                        log(f"[VISION GROUNDING] element_id={element_id} confidence={confidence:.2f} reasoning={v_reasoning}")
                        
                        # DEBUG: Show target element details
                        if element_id >= 0 and element_id < len(context["vision_elements"]):
                            target = context["vision_elements"][element_id]
                            log(f"[VISION DEBUG] Target: id={element_id}, selector={target.get('selector','')[:60]}, text='{target.get('text','')[:50]}', role={target.get('role','')}, bbox={target.get('bbox')}")
                        
                        # Vision loop detection
                        vision_action_key = (element_id, action, v_text)
                        recent_vision_actions.append(vision_action_key)
                        if len(recent_vision_actions) > MAX_VISION_REPEATS:
                            recent_vision_actions.pop(0)
                        
                        if recent_vision_actions.count(vision_action_key) >= MAX_VISION_REPEATS:
                            log(f"[VISION LOOP DETECTED] Same action repeated {MAX_VISION_REPEATS}x")
                            action = "scroll"
                            decision = {"action": "scroll", "scroll_pixels": 800, "reasoning": "vision loop break"}
                            recent_vision_actions.clear()
                        elif element_id >= 0 and element_id < len(context["vision_elements"]) and confidence > 0.3:
                            target = context["vision_elements"][element_id]
                            if action == "click":
                                decision = {
                                    "action": "vision_click",
                                    "element_id": element_id,
                                    "elements": context["vision_elements"],
                                    "viewport_width": context.get("viewport_width", 1366),
                                    "viewport_height": context.get("viewport_height", 768),
                                    "reasoning": reasoning + " | " + v_reasoning
                                }
                            elif action == "type":
                                decision = {
                                    "action": "vision_type",
                                    "element_id": element_id,
                                    "elements": context["vision_elements"],
                                    "viewport_width": context.get("viewport_width", 1366),
                                    "viewport_height": context.get("viewport_height", 768),
                                    "text": v_text,
                                    "press_key": press_key,
                                    "reasoning": reasoning + " | " + v_reasoning
                                }
                            else:
                                action = "scroll"
                                decision = {"action": "scroll", "scroll_pixels": 500, "reasoning": "vision fallback"}
                        else:
                            log(f"[VISION] Low confidence ({confidence:.2f}) or no match - falling back to scroll")
                            action = "scroll"
                            decision = {"action": "scroll", "scroll_pixels": 500, "reasoning": "vision: no confident match"}
                                # No Stagehand, use vision pipeline
                    # Step 2: Vision grounds target_description to element_id
                    log("[VISION] Grounding worker intent to element...")
                    vision_decision = await run_vision_grounding(
                        vision_provider, 
                        worker_intent=target_description,
                        goal=goal,
                        ledger=ledger,
                        page_context=context,
                        elements=context["vision_elements"],
                        rate_limiter=vision_rate_limiter
                    )
                    
                    element_id = vision_decision.get("element_id", -1)
                    confidence = vision_decision.get("confidence", 0.0)
                    v_reasoning = vision_decision.get("reasoning", "")
                    
                    log(f"[VISION GROUNDING] element_id={element_id} confidence={confidence:.2f} reasoning={v_reasoning}")
                    
                    # DEBUG: Show target element details
                    if element_id >= 0 and element_id < len(context["vision_elements"]):
                        target = context["vision_elements"][element_id]
                        log(f"[VISION DEBUG] Target: id={element_id}, selector={target.get('selector','')[:60]}, text='{target.get('text','')[:50]}', role={target.get('role','')}, bbox={target.get('bbox')}")
                    
                    # Vision loop detection
                    vision_action_key = (element_id, action, v_text)
                    recent_vision_actions.append(vision_action_key)
                    if len(recent_vision_actions) > MAX_VISION_REPEATS:
                        recent_vision_actions.pop(0)
                    
                    if recent_vision_actions.count(vision_action_key) >= MAX_VISION_REPEATS:
                        log(f"[VISION LOOP DETECTED] Same action repeated {MAX_VISION_REPEATS}x")
                        action = "scroll"
                        decision = {"action": "scroll", "scroll_pixels": 800, "reasoning": "vision loop break"}
                        recent_vision_actions.clear()
                    elif element_id >= 0 and element_id < len(context["vision_elements"]) and confidence > 0.3:
                        target = context["vision_elements"][element_id]
                        if action == "click":
                            decision = {
                                "action": "vision_click",
                                "element_id": element_id,
                                "elements": context["vision_elements"],
                                "viewport_width": context.get("viewport_width", 1366),
                                "viewport_height": context.get("viewport_height", 768),
                                "reasoning": reasoning + " | " + v_reasoning
                            }
                        elif action == "type":
                            decision = {
                                "action": "vision_type",
                                "element_id": element_id,
                                "elements": context["vision_elements"],
                                "viewport_width": context.get("viewport_width", 1366),
                                "viewport_height": context.get("viewport_height", 768),
                                "text": v_text,
                                "press_key": press_key,
                                "reasoning": reasoning + " | " + v_reasoning
                            }
                        else:
                            action = "scroll"
                            decision = {"action": "scroll", "scroll_pixels": 500, "reasoning": "vision fallback"}
                    else:
                        log(f"[VISION] Low confidence ({confidence:.2f}) or no match - falling back to scroll")
                        action = "scroll"
                        decision = {"action": "scroll", "scroll_pixels": 500, "reasoning": "vision: no confident match"}
                else:
                    action = "scroll"
                    decision = {"action": "scroll", "scroll_pixels": 500, "reasoning": "vision fallback"}
            else:
                # Text-based worker (original)
                decision = await run_worker_next_step(provider, goal, ledger, context, next_steps, rate_limiter)
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
                search_results = await search_and_verify(page, query, log)
                ok = bool(search_results)
                note = f"Search results: {search_results[:500]}..." if search_results else "No results found"
            else:
                ok, note = await execute_action(page, decision, log)

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
                text_now = (await extract_page_context(page)).get("text", "")
                if _classify_search_intent(text_now):
                    ledger.mark_dead_end(
                        f"search query {decision.get('url','')[:80]} returned no results",
                        page.url,
                        cause="not_found",
                        step=step,
                    )
                    log("[DEAD-END] Search returned no results — recorded.")

            # ----- Captcha auto-pivot -----
            context_after = await extract_page_context(page)
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
                await page.goto(fb, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)

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

    return status, final_answer, step_count, context