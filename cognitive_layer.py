"""Three-role cognitive layer (per RunAgent SuperBrowser §4.1).

- Orchestrator: classifies the task, decides whether to open a browser or
  answer from a lightweight fetch. For now we always route to the browser.
- Planner: runs every N steps. The ONLY place 'done' can be declared.
- Worker: emits one concrete action per step (navigate / click / type /
  scroll / press / mouseclick).
"""
import json
from dataclasses import dataclass

from llm_providers import LLMProvider, LLMConfig, create_llm_provider, get_rate_limiter
from memory import Ledger


# ----- Orchestrator --------------------------------------------------------

ORCHESTRATOR_PROMPT = """You are the ORCHESTRATOR of an autonomous web agent.
Classify the user's task into ONE of these routes:

- "search"   : a factual lookup or aggregation (no browser needed)
- "browser"  : anything requiring real interaction (click, type, login, booking)

Respond ONLY with a JSON object:
{{"route": "search" | "browser", "confidence": 0.0-1.0, "reasoning": "..."}}

Task: "{goal}"
"""


def run_orchestrator(provider: LLMProvider, goal: str, rate_limiter) -> dict:
    prompt = ORCHESTRATOR_PROMPT.format(goal=goal)
    config = LLMConfig(model="", temperature=0.1, max_tokens=500)
    return provider.generate_json(prompt, config)


# ----- Planner -------------------------------------------------------------

PLANNER_PROMPT = """You are the PLANNER of an autonomous web agent (RunAgent SuperBrowser).
The Worker is about to take the next action. Your job is to evaluate PROGRESS
and decide:
  - is the goal achieved? -> emit "done" with a final_answer
  - is the goal UNREACHABLE? (dead-ends show repeated failures, no path forward)
    -> emit "done" with a final_answer that explains what could not be found
  - otherwise, emit "continue" and tell the Worker what to do next

GOAL: {goal}

LEDGER STATE:
{ledger}

CURRENT PAGE:
Title: {title}
URL: {url}
Text snippet: {text_snippet}

WORKER JUST EXECUTED: {last_action} -> {last_result}

Respond ONLY with a valid JSON object:
{{
  "verdict": "done" | "continue" | "abandon",
  "final_answer": "the answer to the user's goal (if verdict=done)",
  "next_steps": ["short instruction 1", "short instruction 2", ...],
  "reasoning": "1-2 sentences explaining your decision"
}}

CRITICAL RULES:
- If the dead-ends list shows multiple "not_found" entries for the SAME goal
  query, the goal is likely impossible. Set verdict="done" with an honest
  final_answer like: "Could not find a PewDiePie video about Gantz on YouTube
  or DuckDuckGo after multiple search attempts."
- If the page text already contains the answer (price, name, value), set
  verdict="done" immediately with that value as the answer.
- If the worker just successfully reached a page that clearly matches the
  goal (e.g. the exact product, the exact article, the exact video), set
  verdict="done".
- Only set verdict="continue" if there is a plausible next action that
  moves toward the goal.
"""


def run_planner(provider: LLMProvider, goal: str, ledger: "Ledger",
                page_context: dict, last_action: dict, last_result: dict,
                rate_limiter) -> dict:
    import json
    prompt = PLANNER_PROMPT.format(
        goal=goal,
        ledger=ledger.render_for_planner(),
        title=page_context.get("title", "Unknown"),
        url=page_context.get("url", ""),
        text_snippet=(page_context.get("text") or "")[:1500],
        last_action=json.dumps(last_action),
        last_result=json.dumps(last_result),
    )
    config = LLMConfig(model="", temperature=0.3, max_tokens=1000)
    return provider.generate_json(prompt, config)


# ----- Worker --------------------------------------------------------------

WORKER_PROMPT_FIRST = """You are the WORKER (operational layer) of an autonomous web agent.
The user wants: "{goal}"

No page is loaded yet. Pick a STARTING URL.

DECISION RULES:
- If the goal involves a SPECIFIC SITE (YouTube, Amazon, GitHub, etc.), go DIRECTLY to that site's URL. Do NOT use a search engine.
- If the goal is "play/watch/find video X on YouTube", go to https://www.youtube.com/results?search_query=X or the channel URL directly.
- If the goal is "find price of X on Amazon", go to https://www.amazon.in/s?k=X
- ONLY use DuckDuckGo (https://duckduckgo.com/) for truly open-ended web searches where no specific site makes sense.
- NEVER use Google — it blocks automated browsers.

Respond ONLY with JSON:
{
  "action": "navigate",
  "url": "https://...",
  "reasoning": "short explanation"
}
"""


WORKER_PROMPT_NEXT = """You are the WORKER (operational layer) of an autonomous web agent.
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

Respond ONLY with a valid JSON object. CRITICAL: copy the "selector" VERBATIM
from the interactive list above — do NOT invent selectors.

{
  "action": "navigate" | "click" | "type" | "scroll" | "press" | "mouseclick" | "done",
  "url": "URL (if navigate)",
  "selector": "selector from list (if click or type)",
  "input_selector": "selector (if type)",
  "text": "text to type (if type)",
  "press_key": "Enter (if type or press)",
  "scroll_pixels": 500,
  "x": 0, "y": 0,
  "answer": "final answer (if action=done)",
  "reasoning": "short explanation"
}

IMPORTANT:
- If dead-ends show repeated failures for the same query, call action="done"
  with an honest "could not find X" answer. Do NOT loop.
- If you see the exact info you need on the page (price, name, link), call
  action="done" with that as the answer.
- REPORT ONLY WHAT YOU SEE: When answering, quote the EXACT text from the page
  (product titles, prices, snippets). Do NOT infer, assume, or hallucinate.
  If the search results show "iPhone 17 Pro" but the user asked for "iPhone 16 Pro",
  report exactly: "Search results show iPhone 17 Pro at ₹X. iPhone 16 Pro does not
  appear in the visible results." Do NOT say the product "doesn't exist" — only
  report what the page actually shows.
- For YouTube videos: selectors look like `a#video-title-link`,
  `a[href*="watch?v=..."]`, or inside `ytd-rich-grid-renderer`/`ytd-rich-item-renderer`.
  **On channel pages (@user), latest videos are usually visible on the home page —
  click them directly. Do NOT go to /videos tab unless no video links are visible.**
  **If interactive list is empty on YouTube, the page is still loading — wait or scroll.**
- Viewport is 1366x768; coordinates for mouseclick must be inside that.
"""


def run_worker_first_step(provider, goal: str, rate_limiter) -> dict:
    prompt = """You are the WORKER (operational layer) of an autonomous web agent.
The user wants: "{goal}"

No page is loaded yet. Pick a STARTING URL.

DECISION RULES:
- If the goal involves a SPECIFIC SITE (YouTube, Amazon, GitHub, etc.), go DIRECTLY to that site's URL. Do NOT use a search engine.
- If the goal is "play/watch/find video X on YouTube", go to https://www.youtube.com/results?search_query=X or the channel URL directly.
- If the goal is "find price of X on Amazon", go to https://www.amazon.in/s?k=X
- If you need to VERIFY if something exists (product, price, info), use "search_google" action with a query to search Google and verify.
- ONLY use DuckDuckGo (https://duckduckgo.com/) for truly open-ended web searches where no specific site makes sense.
- NEVER use Google directly for navigation — it blocks automated browsers.

Respond ONLY with JSON:
{{
  "action": "navigate" | "search_google",
  "url": "https://...",  (if navigate)
  "query": "search query",  (if search_google)
  "reasoning": "short explanation"
}}""".format(goal=goal)
    config = LLMConfig(model="", temperature=0.3, max_tokens=500)
    return provider.generate_json(prompt, config)


def run_worker_next_step(provider, goal: str, ledger, page_context: dict, next_steps: list[str], rate_limiter) -> dict:
    interactive = page_context.get("interactive", "[]")
    if len(interactive) > 4000:
        interactive = interactive[:4000] + "\n... (truncated)"
    prompt = """You are the WORKER (operational layer) of an autonomous web agent.
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

Respond ONLY with a valid JSON object. CRITICAL: copy the "selector" VERBATIM
from the interactive list above — do NOT invent selectors.

{{
{{
  "action": "navigate" | "click" | "type" | "scroll" | "press" | "mouseclick" | "search_google" | "done",
  "url": "URL (if navigate)",
  "query": "search query (if search_google)",
  "selector": "selector from list (if click or type)",
  "input_selector": "selector (if type)",
  "text": "text to type (if type)",
  "press_key": "Enter (if type or press)",
  "scroll_pixels": 500,
  "x": 0, "y": 0,
  "answer": "final answer (if action=done)",
  "reasoning": "short explanation"
}}

IMPORTANT:
- If you are unsure whether a product/item exists, use "search_google" action with a query to verify before concluding.
- When using "search_google", provide a "query" field with the search terms.
- If search results confirm something doesn't exist, report that honestly with the search results.
- If dead-ends show repeated failures for the same query, call action="done"
  with an honest "could not find X" answer. Do NOT loop.
- If you see the exact info you need on the page (price, name, link), call
  action="done" with that as the answer.
- REPORT ONLY WHAT YOU SEE: When answering, quote the EXACT text from the page
  (product titles, prices, snippets). Do NOT infer, assume, or hallucinate.
  If the search results show "iPhone 17 Pro" but the user asked for "iPhone 16 Pro",
  report exactly: "Search results show iPhone 17 Pro at ₹X. iPhone 16 Pro does not
  appear in the visible results." Do NOT say the product "doesn't exist" — only
  report what the page actually shows.
- FOR CLICKING: Use the EXACT "selector" value from the interactive elements list above.
  Do NOT invent selectors like "button:has-text('...')" — they will fail.
  The "selector" field in the interactive list is a valid CSS selector that will work.
- For typing: use the exact "input_selector" from the interactive list.
- If the interactive list is empty or the element you need isn't listed, use "scroll" or "search_google" instead of guessing.
- For YouTube videos: selectors look like `a#video-title-link`,
  `a[href*="watch?v=..."]`, or inside `ytd-rich-grid-renderer`/`ytd-rich-item-renderer`.
  **On channel pages (@user), latest videos are usually visible on the home page —
  click them directly. Do NOT go to /videos tab unless no video links are visible.**
  **If interactive list is empty on YouTube, the page is still loading — wait or scroll.**
- Viewport is 1366x768; coordinates for mouseclick must be inside that.
""".format(
        goal=goal,
        ledger=ledger.render_for_worker(),
        title=page_context.get("title", "Unknown"),
        url=page_context.get("url", ""),
        text=(page_context.get("text") or "")[:3000],
        interactive=page_context.get("interactive", "[]")[:4000],
        next_steps=" | ".join(next_steps) if next_steps else "(no guidance)",
    )
    config = LLMConfig(model="", temperature=0.3, max_tokens=1000)
    return provider.generate_json(prompt, config)