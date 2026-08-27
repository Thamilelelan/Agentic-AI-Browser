"""Three-role cognitive layer (per RunAgent SuperBrowser §4.1)."""
import json

from llm_providers import LLMProvider, LLMConfig
from memory import Ledger

PROMPT_VERSION = "2026-08-27.v1"
ALLOWED_ORCH_ROUTE = "browser"
ALLOWED_PLANNER_VERDICTS = {"done", "continue", "abandon"}
ALLOWED_WORKER_ACTIONS = {
    "navigate", "click", "type", "scroll", "press", "mouseclick", "search_google"
}


# ----- Orchestrator --------------------------------------------------------

ORCHESTRATOR_PROMPT = """You are the ORCHESTRATOR of an autonomous web agent.
PROMPT_VERSION: """ + PROMPT_VERSION + """

ROLE:
- You ONLY classify intent and set confidence.
- This runtime currently executes only browser-based flows.
- Therefore route MUST always be "browser".

Task: "{goal}"

Respond with JSON ONLY (no prose, no markdown, no extra keys):
{{"route":"browser","confidence":0.0,"reasoning":"short reason"}}

RULES:
- route must be exactly "browser".
- confidence must be a number in [0,1].
- Keep reasoning concise and factual.
"""


def _as_json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    return {}


def _to_float_0_1(value) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if num < 0:
        return 0.0
    if num > 1:
        return 1.0
    return num


def _normalize_orchestrator(raw: dict) -> dict:
    raw = _as_json_object(raw)
    reasoning = str(raw.get("reasoning", "")).strip() or "Default browser route."
    return {
        "route": ALLOWED_ORCH_ROUTE,
        "confidence": _to_float_0_1(raw.get("confidence", 0.0)),
        "reasoning": reasoning,
    }


def _normalize_planner(raw: dict) -> dict:
    raw = _as_json_object(raw)
    verdict = str(raw.get("verdict", "continue")).strip().lower()
    if verdict not in ALLOWED_PLANNER_VERDICTS:
        verdict = "continue"

    raw_steps = raw.get("next_steps", [])
    if isinstance(raw_steps, list):
        next_steps = [str(s).strip() for s in raw_steps if str(s).strip()][:3]
    else:
        next_steps = []

    reasoning = str(raw.get("reasoning", "")).strip() or "Continue cautiously."
    final_answer = str(raw.get("final_answer", "")).strip()

    if verdict == "continue":
        final_answer = ""
        if not next_steps:
            next_steps = ["Take one safe next step that gathers more evidence."]
    elif not final_answer:
        final_answer = "Insufficient evidence on the visible page to provide a reliable final answer."

    return {
        "verdict": verdict,
        "final_answer": final_answer,
        "next_steps": next_steps,
        "reasoning": reasoning,
    }


def _normalize_worker(raw: dict, default_action: str = "scroll") -> dict:
    raw = _as_json_object(raw)

    action = str(raw.get("action", default_action)).strip().lower()
    if action not in ALLOWED_WORKER_ACTIONS:
        action = default_action

    params = raw.get("parameters", {})
    if not isinstance(params, dict):
        params = {}

    # Backward compatibility with flat key outputs.
    for key in ("url", "selector", "input_selector", "text", "press_key", "scroll_pixels", "x", "y", "query"):
        if key in raw and key not in params:
            params[key] = raw.get(key)

    reasoning = str(raw.get("reasoning", "")).strip() or "Follow safe, single-step action."

    if action == "navigate":
        url = str(params.get("url", "")).strip()
        if not url:
            action = "scroll"
            params = {"scroll_pixels": 500}
        else:
            params = {"url": url}
    elif action in ("click", "type"):
        selector = str(params.get("selector") or params.get("input_selector") or "").strip()
        if not selector:
            action = "scroll"
            params = {"scroll_pixels": 500}
        elif action == "click":
            params = {
                "selector": selector,
                "text": str(params.get("text", "")).strip(),
            }
        else:
            params = {
                "selector": selector,
                "input_selector": selector,
                "text": str(params.get("text", "")).strip(),
                "press_key": str(params.get("press_key", "Enter")).strip() or "Enter",
            }
    elif action == "scroll":
        try:
            pixels = int(params.get("scroll_pixels", 500))
        except (TypeError, ValueError):
            pixels = 500
        params = {"scroll_pixels": max(200, min(2000, pixels))}
    elif action == "press":
        params = {"press_key": str(params.get("press_key", "Enter")).strip() or "Enter"}
    elif action == "mouseclick":
        try:
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
        except (TypeError, ValueError):
            x, y = 0, 0
        params = {"x": max(0, min(1366, x)), "y": max(0, min(768, y))}
    elif action == "search_google":
        query = str(params.get("query", "")).strip()
        if not query:
            action = "scroll"
            params = {"scroll_pixels": 500}
        else:
            params = {"query": query}

    normalized = {
        "action": action,
        "parameters": params,
        "reasoning": reasoning,
    }
    # Engine compatibility keys.
    normalized.update(params)
    return normalized


def run_orchestrator(provider: LLMProvider, goal: str, rate_limiter) -> dict:
    prompt = ORCHESTRATOR_PROMPT.format(goal=goal)
    config = LLMConfig(model="", temperature=0.1, max_tokens=200)
    rate_limiter.wait_if_needed()
    raw = provider.generate_json(prompt, config)
    return _normalize_orchestrator(raw)


# ----- Planner -------------------------------------------------------------

PLANNER_PROMPT = """You are the PLANNER of an autonomous web agent.
PROMPT_VERSION: """ + PROMPT_VERSION + """

ROLE:
- You are the ONLY role allowed to finalize (done/abandon).
- The Worker is action-only and cannot produce final answers.

TASK:
- Evaluate progress from ledger + current page.
- Choose exactly one verdict: done | continue | abandon.

GOAL: {goal}

LEDGER STATE:
{ledger}

CURRENT PAGE:
Title: {title}
URL: {url}
Text snippet: {text_snippet}

WORKER LAST ACTION: {last_action} -> {last_result}

Respond with JSON ONLY (no prose, no markdown, no extra keys):
{{
  "verdict":"done|continue|abandon",
  "final_answer":"required when verdict is done or abandon; else empty string",
  "next_steps":["short step"],
  "reasoning":"short factual reason"
}}

CRITICAL RULES:
- The system currently supports short web navigation tasks, basic click/type/scroll,
  visible-text extraction, and simple dead-end handling.
- Do NOT claim robust autonomous transactions or guaranteed correctness.
- Final answers must be evidence-bound to visible page text.
- If evidence is ambiguous/missing, prefer verdict="continue" with a safe next step.
- If repeatedly blocked or impossible, use verdict="abandon" and explain limits.
- Never speculate or infer unseen facts.
"""


def run_planner(provider: LLMProvider, goal: str, ledger: "Ledger",
                page_context: dict, last_action: dict, last_result: dict,
                rate_limiter) -> dict:
    prompt = PLANNER_PROMPT.format(
        goal=goal,
        ledger=ledger.render_for_planner(),
        title=page_context.get("title", "Unknown"),
        url=page_context.get("url", ""),
        text_snippet=(page_context.get("text") or "")[:1500],
        last_action=json.dumps(last_action),
        last_result=json.dumps(last_result),
    )
    config = LLMConfig(model="", temperature=0.2, max_tokens=600)
    rate_limiter.wait_if_needed()
    raw = provider.generate_json(prompt, config)
    return _normalize_planner(raw)


# ----- Worker --------------------------------------------------------------

WORKER_PROMPT_FIRST = """You are the WORKER (operational layer) of an autonomous web agent.
PROMPT_VERSION: """ + PROMPT_VERSION + """

ROLE:
- You can emit ONE action only.
- You cannot finalize the task.

The user wants: "{goal}"

No page is loaded yet. Pick a STARTING URL.

DECISION RULES:
- If the goal involves a SPECIFIC SITE (YouTube, Amazon, GitHub, etc.), go DIRECTLY to that site's URL. Do NOT use a search engine.
- If the goal is "play/watch/find video X on YouTube", go to https://www.youtube.com/results?search_query=X or the channel URL directly.
- If the goal is "find price of X on Amazon", go to https://www.amazon.in/s?k=X
- If you need existence verification, use search_google.
- ONLY use DuckDuckGo (https://duckduckgo.com/) for truly open-ended web searches where no specific site makes sense.
- Do not use unsupported capabilities or multi-step plans.

Respond with JSON ONLY (no prose, no markdown, no extra keys):
{{
  "action":"navigate|search_google",
  "parameters":{{"url":"https://..."}} or {{"query":"..."}},
  "reasoning":"short factual reason"
}}
"""


WORKER_PROMPT_NEXT = """You are the WORKER (operational layer) of an autonomous web agent.
PROMPT_VERSION: """ + PROMPT_VERSION + """

ROLE:
- Emit exactly ONE executable action.
- You are action-only; do not finalize or speculate.

User goal: "{goal}"

A page IS LOADED. You should almost always choose "click" or "type" against the
current page, NOT "navigate" away (unless the current page is irrelevant,
e.g. a CAPTCHA block).

--- LEDGER (sliced view) ---
{ledger}
--- END LEDGER ---

CURRENT PAGE:
Title: {title}
URL: {url}

Visible text:
{text}

Interactive elements (selectors are PAGE-SPECIFIC — re-read on every step):
{interactive}

PLANNER'S GUIDANCE: {next_steps}

Respond with JSON ONLY (no prose, no markdown, no extra keys). CRITICAL: copy the "selector" VERBATIM
from the interactive list above — do NOT invent selectors.

{{
  "action":"navigate|click|type|scroll|press|mouseclick|search_google",
  "parameters":{{}},
  "reasoning":"short factual reason"
}}

Parameter contract by action:
- navigate      -> {{"url":"https://..."}}
- click         -> {{"selector":"...","text":"optional hint"}}
- type          -> {{"selector":"...","input_selector":"...","text":"...","press_key":"Enter"}}
- scroll        -> {{"scroll_pixels":500}}
- press         -> {{"press_key":"Enter"}}
- mouseclick    -> {{"x":0,"y":0}}
- search_google -> {{"query":"..."}}

IMPORTANT:
- If interactive list is empty, or needed element is missing, choose safe fallback: scroll.
- If dead-ends show repeated selector failures, do not retry same selector; switch strategy.
- If unsure, prefer observation-safe actions (scroll/search_google) over risky guesses.
- Never invent selectors, never emit multiple actions, never include unsupported keys.
- Viewport is 1366x768; coordinates for mouseclick must be inside that.
"""


def run_worker_first_step(provider, goal: str, rate_limiter) -> dict:
    prompt = WORKER_PROMPT_FIRST.format(goal=goal)
    config = LLMConfig(model="", temperature=0.1, max_tokens=400)
    rate_limiter.wait_if_needed()
    raw = provider.generate_json(prompt, config)
    return _normalize_worker(raw, default_action="navigate")


def run_worker_next_step(provider, goal: str, ledger, page_context: dict, next_steps: list[str], rate_limiter) -> dict:
    interactive = page_context.get("interactive", "[]")
    if len(interactive) > 4000:
        interactive = interactive[:4000] + "\n... (truncated)"
    prompt = WORKER_PROMPT_NEXT.format(
        goal=goal,
        ledger=ledger.render_for_worker(),
        title=page_context.get("title", "Unknown"),
        url=page_context.get("url", ""),
        text=(page_context.get("text") or "")[:3000],
        interactive=page_context.get("interactive", "[]")[:4000],
        next_steps=" | ".join(next_steps) if next_steps else "(no guidance)",
    )
    config = LLMConfig(model="", temperature=0.1, max_tokens=600)
    rate_limiter.wait_if_needed()
    raw = provider.generate_json(prompt, config)
    return _normalize_worker(raw, default_action="scroll")