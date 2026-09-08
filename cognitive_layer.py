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
    rate_limiter.wait_if_needed()
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
    rate_limiter.wait_if_needed()
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
    rate_limiter.wait_if_needed()
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
    rate_limiter.wait_if_needed()
    return provider.generate_json(prompt, config)


def run_worker_vision_step(provider, goal: str, ledger, page_context: dict, next_steps: list[str], interactive_text: str, rate_limiter) -> dict:
    """Worker with vision context - plans action + target_description for vision grounding."""
    ledger_text = ledger.render_for_worker()
    
    prompt = WORKER_VISION_PROMPT.format(
        goal=goal,
        ledger=ledger_text,
        title=page_context.get("title", "Unknown"),
        url=page_context.get("url", ""),
        text=(page_context.get("text") or "")[:3000],
        interactive=interactive_text[:4000],
        next_steps=" | ".join(next_steps) if next_steps else "(no guidance)",
    )
    config = LLMConfig(model="", temperature=0.3, max_tokens=1000)
    rate_limiter.wait_if_needed()
    return provider.generate_json(prompt, config)


# ----- Vision Grounding (SeeAct style) ---------------------------------------

# The vision grounding follows SeeAct "Planning-then-Grounding":
# 1. Worker (strong LLM) decides: action type + target description (WHAT to click)
# 2. Vision (VLM) maps target description to element_id (WHERE to click)
# This separates reasoning from visual grounding.

VISION_GROUNDING_PROMPT = """You are the VISION GROUNDING module of an autonomous web agent (SeeAct / RunAgent style).

Your job: Map the WORKER'S INTENT to the exact element ID on the annotated screenshot.

WORKER'S INTENT: {worker_intent}

CURRENT PAGE CONTEXT:
URL: {page_url}
Title: {page_title}

CURRENT PAGE - Set-of-Marks Annotated:
The screenshot has numbered bounding boxes on interactive elements.

INTERACTIVE ELEMENTS:
{elements_text}

TASK: Find the element that BEST MATCHES the worker's intent. Return its element_id.

RESPOND WITH JSON ONLY:
{{
  "element_id": <number>,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation linking worker intent to this element"
}}

RULES:
- Pick element_id from the list above ONLY (must be a valid ID shown)
- If NO element matches the worker's intent, use element_id: -1, confidence: 0.0
- If goal is achieved (answer visible on page per worker intent), use element_id: -1, confidence: 1.0, reasoning: "goal achieved"
- Match by: text content, role (button/link/input), visual position, element type
- Prefer exact text matches > partial matches > role matches
- If multiple candidates, pick the one most relevant to worker's intent
"""


# Worker's VISION-AWARE prompt - plans with visual understanding
WORKER_VISION_PROMPT = """You are the WORKER (operational layer) of an autonomous web agent.
You have access to VISION - you can see the annotated screenshot with numbered elements.

User goal: "{goal}"

--- LEDGER (sliced view) ---
{ledger}
--- END LEDGER ---

CURRENT PAGE:
Title: {title}
URL: {url}

Visible text snippet:
{text}

INTERACTIVE ELEMENTS (from SoM annotation):
{interactive}

PLANNER'S GUIDANCE: {next_steps}

You are about to act on THIS page. Decide the NEXT ACTION.

Think step by step:
1. What is the current page? (check URL + title)
2. What does the goal require? 
3. What should I do NOW to make progress?
4. Which element on the page matches that?

RESPOND WITH JSON ONLY:
{{
  "action": "click" | "type" | "scroll" | "navigate" | "done",
  "target_description": "natural language description of WHAT to interact with (e.g., 'the play button on the MKBHD video', 'the search input box', 'the first video link')",
  "text": "text to type (if type)",
  "press_key": "Enter (if type)",
  "url": "URL (if navigate)",
  "reasoning": "1-2 sentences: why this action, why this target"
}}

CRITICAL RULES:
- target_description MUST be specific enough for vision to find it visually
- For "click": describe the element (text, role, position) - NOT the selector
- For "type": describe the input field + what text to type
- For "navigate": provide full URL
- For "done": provide exact answer in reasoning
- If page is wrong for goal → navigate to correct site
- If input already has text → don't retype, press Enter or click search
- Use ONLY information visible on current page
"""


def run_vision_grounding(
    vision_provider,
    worker_intent: str,
    goal: str,
    ledger,
    page_context: dict,
    elements: list[dict],
    rate_limiter
) -> dict:
    """Run vision grounding using SeeAct-style Set-of-Marks prompting.
    
    Takes the annotated screenshot and element list, maps worker's intent to element_id.
    Returns dict with element_id, confidence, reasoning.
    """
    ledger_text = ledger.render_for_worker()
    
    elements_desc = []
    for el in elements:
        eid = el.get("id", 0)
        text = el.get("text", "")[:60]
        tag = el.get("tag", "")
        role = el.get("role", "")
        href = el.get("href", "")[:80]
        bbox = el.get("bbox", [0,0,0,0])
        elements_desc.append(f"  [{eid}] {role} {tag}: '{text}' {href} @bbox({bbox[0]:.2f},{bbox[1]:.2f},{bbox[2]:.2f},{bbox[3]:.2f})")
    
    elements_text = "\n".join(elements_desc) if elements_desc else "  (no interactive elements detected)"
    
    # Add current page context
    page_url = page_context.get("url", "unknown")
    page_title = page_context.get("title", "unknown")
    
    prompt = VISION_GROUNDING_PROMPT.format(
        worker_intent=worker_intent,
        goal=goal,
        ledger_text=ledger_text,
        elements_text=elements_text,
        page_url=page_url,
        page_title=page_title
    )
    
    config = LLMConfig(
        model="",
        temperature=0.3,
        max_tokens=1000
    )
    
    import tempfile
    import os
    
    annotated_screenshot = page_context.get("annotated_screenshot_bytes")
    
    if annotated_screenshot:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(annotated_screenshot)
            temp_path = f.name
        
        try:
            rate_limiter.wait_if_needed()
            response = vision_provider.generate_json(prompt, config, image_path=temp_path)
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
    else:
        rate_limiter.wait_if_needed()
        response = vision_provider.generate_json(prompt, config)
    
    return parse_vision_response(response)


def parse_vision_response(response: dict) -> dict:
    """Parse and validate vision grounding response."""
    if response.get("_parse_error"):
        return {"element_id": -1, "action": "scroll", "text": "", "reasoning": "Vision parse error"}
    
    element_id = response.get("element_id", -1)
    action = response.get("action", "click")
    text = response.get("text", "")
    reasoning = response.get("reasoning", "")
    
    if not isinstance(element_id, int):
        element_id = -1
    if action not in ["click", "type", "scroll", "done"]:
        action = "click"
    
    return {
        "element_id": element_id,
        "action": action,
        "text": text,
        "reasoning": reasoning
    }