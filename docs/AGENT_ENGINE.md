# Agent Engine Documentation

## Overview

The `agent_engine.py` is the core orchestration engine that wires together the three cognitive roles (Orchestrator, Planner, Worker) with the Ledger memory system and Playwright browser automation.

## Main Entry Point: `run_session()`

```python
def run_session(
    goal: str,
    provider: LLMProvider,
    config: EngineConfig,
    log: Callable[[str], None] = print,
    is_continuation: bool = False,
    start_context: dict | None = None,
) -> dict:
```

**Returns**:
```python
{
    "status": "done" | "exhausted" | "blocked" | "error",
    "final_answer": str,
    "ledger": Ledger,
    "steps": int,
    "last_context": dict,
    "provider_used": str,
    "provider_fallback": bool,
}
```

## Session Lifecycle

```
run_session(goal, provider, config)
    │
    ├─► Create Ledger(goal)
    ├─► Launch Browser (CDP or bundled Chromium)
    ├─► Orchestrator: classify task → route
    ├─► If no start_context: Worker #1 picks starting URL
    ├─► FOR step in 1..max_steps:
    │   ├─ Perception: extract_page_context(page)
    │   ├─ Every 3 steps (or after Worker "done"): Planner
    │   ├─ Worker: emits action
    │   ├─ Execute action via Playwright
    │   ├─ Record StepOutcome in Ledger
    │   ├─ Check: not-found, CAPTCHA, dead-ends
    │   └─ Break if verdict="done" or max_steps
    │
    ├─► Return {status, final_answer, ledger, steps, context}
```

## Key Components

### EngineConfig

```python
@dataclass
class EngineConfig:
    max_steps: int = 8                    # Max steps per session
    headless: bool = False                # Visual browser (UI mode)
    rate_limit_per_min: int = 15          # Requests/min
    browser: str = "chromium"             # chromium|helium|chrome|edge|brave|firefox|cdp
    executable_path: str | None = None    # Custom browser path
    channel: str | None = None            # For p.chromium.launch(channel=...)
    keep_browser_open: bool = False       # Keep browser open after session
    model: str = "gemini-3.5-flash-lite"  # Model name
    provider_type: str = "gemini"         # "gemini" | "nvidia"
```

### Browser Selection
```python
browser: str = "chromium"  # chromium|helium|chrome|edge|brave|firefox|zen|cdp
```

| Value | Description |
|-------|-------------|
| `chromium` | Playwright bundled (default) |
| `helium` | Helium Browser (`/opt/helium-browser-bin/chrome`) |
| `chrome` | System Chrome (`channel="chrome"`) |
| `edge` | Microsoft Edge (`channel="msedge"`) |
| `brave` | Brave Browser |
| `firefox` | Firefox/Zen/LibreWolf |
| `chromium-system` | System Chromium on PATH |
| `cdp` | Attach to existing browser via CDP |

### CDP Mode (Attach to Existing Browser)
```python
config = EngineConfig(
    browser="cdp",
    executable_path="http://localhost:9222",  # or CDP_URL env var
)
```
- Connects to existing browser via CDP
- Reuses user's cookies, logins, sessions
- Browser NOT closed after session

---

## Main Loop: `_run_session_inner()`

### Loop Structure
```python
for step in range(1, config.max_steps + 1):
    # 1. PERCEPTION
    context = extract_page_context(page)
    
    # 2. PLANNER (every 3 steps or after worker "done")
    if step == 1 or step % 3 == 0 or last_action == "done":
        plan = run_planner(...)
        if verdict in ("done", "abandon"): break
        next_steps = plan.get("next_steps", [])
    
    # 2. WORKER
    decision = run_worker_next_step(...)
    action = decision.get("action", "navigate")
    
    # Handle search_google action
    if action == "search_google":
        query = decision.get("query", "")
        search_results = search_and_verify(page, query, log)
        ok = bool(search_results)
        note = f"Search results: {search_results[:500]}..."
    else:
        ok, note = execute_action(page, decision, log)
    
    # Record action
    ledger.record_action(StepOutcome(...))
    
    # Check for "not found" pages
    if action == "navigate" and _classify_search_intent(text):
        ledger.mark_dead_end(...)
    
    # CAPTCHA detection & auto-pivot
    if is_captcha_page(context):
        # Pivot to fallback URL (DuckDuckGo → Bing → Wikipedia)
```

### Step Flow
```
STEP N
    │
    ├─► PERCEPTION: extract_page_context()
    │
    ├─► PLANNER (every 3 steps or after "done")
    │    ├─ verdict = "done" → BREAK with answer
    │    └─ verdict = "continue" → next_steps
    │
    ├─► WORKER emits action
    │
    ├─► EXECUTE action
    │    ├─ navigate → page.goto()
    │    ├─ click → _click_via_selector()
    │    ├─ type → page.fill()
    │    ├─ scroll → window.scrollBy()
    │    ├─ press → keyboard.press()
    │    └─ search_google → search_and_verify()
    │
    ├─► Record StepOutcome in Ledger
    ├─► Check: not_found, captcha, dead-ends
    │
    └─► Next iteration or BREAK
```

---

## Key Functions

### `run_session()`
Main entry point. Orchestrates browser lifecycle, provider fallback, and result aggregation.

### `_run_session_inner()`
Core cognitive loop. Contains the main perception-planning-action loop.

### `_run_session_inner()` - Key Variables
| Variable | Purpose |
|----------|---------|
| `context` | Current page context (title, url, text, interactive) |
| `last_action` | Previous action dict |
| `last_result` | Previous action result {success, note} |
| `failed_selectors` | Failed selector → failure count |
| `captcha_count` | CAPTCHA encounter count |
| `failed_selectors` | selector → failure count |

### Helper Functions

#### `_classify_search_intent(text)`
Detects "no results" pages:
```python
keywords = ["no results found", "did not match any", "0 results",
            "no videos found", "no posts found", "no matches"]
return any(k in text.lower() for k in keywords)
```

#### `search_and_verify(page, query, log)`
```python
def search_and_verify(page, query: str, log) -> str:
    """Search Google to verify existence. Returns search results text."""
    page.goto(f"https://www.google.com/search?q={query.replace(' ', '+')}")
    page.wait_for_timeout(3000)
    page.wait_for_selector('#search, #rso, .g, .tF2Cxc', timeout=8000)
    page.wait_for_timeout(2000)
    text = extract_page_context(page).get("text", "")
    return text
```

#### `is_captcha_page(ctx)`
```python
def is_captcha_page(ctx):
    url = ctx.get("url", "").lower()
    text = (ctx.get("text") or "").lower()
    return (
        "/sorry/" in url or "captcha" in url
        or "unusual traffic" in text
        or "automated requests" in text
        or "are you a robot" in text
        or "verify you are human" in text
        or "recaptcha" in text
    )
```

---

## Configuration Tuning

### For NVIDIA (High Rate Limit)
```python
config = EngineConfig(
    max_steps=20,        # More steps for complex tasks
    provider_type="nvidia",
    rate_limit_per_min=30,
)
```

### For Gemini (Lower Rate Limit)
```python
config = EngineConfig(
    max_steps=8,
    provider_type="gemini",
    rate_limit_per_min=15,
)
```

### Headless vs Visual
```python
# Headless (CI/CD)
config = EngineConfig(headless=True, keep_browser_open=False)

# Visual debugging (UI mode)
config = EngineConfig(headless=False, keep_browser_open=True)
```

### Browser Selection
```python
config = EngineConfig(
    browser="cdp",              # Attach to existing browser
    executable_path="http://localhost:9222",  # CDP URL
)
```

---

## Result Structure

```python
{
    "status": "done" | "exhausted" | "blocked" | "error",
    "final_answer": "The answer to the user's goal",
    "ledger": Ledger,           # Full memory state
    "steps": 5,                 # Steps taken
    "last_context": {...},      # Final page context
    "provider_used": "nvidia|gemini",
    "provider_fallback": True/False,
}
```

### Status Values
| Status | Meaning |
|--------|---------|
| `done` | Goal achieved (Planner or Worker declared done) |
| `exhausted` | Max steps reached without completion |
| `blocked` | CAPTCHA/block encountered twice |
| `error` | Unhandled exception |

---

## Extending the Engine

### Adding New Actions
1. Add action to `WORKER_PROMPT_NEXT` JSON schema
2. Add case in `execute_action()` in `action_layer.py`
3. Update `_run_session_inner()` execution logic

### Adding New Browser
1. Add to `browser_config.py` `resolve_browser()`
2. Add launch logic in `run_session()`

### Adding New Cognitive Role
1. Add function in `cognitive_layer.py`
2. Call in `_run_session_inner()` loop
3. Update `EngineConfig` if needed

### Custom Rate Limiting
```python
config = EngineConfig(
    rate_limit_per_min=30,  # Override default
    provider_type="nvidia",
)
```

---

## Debugging

### Enable Verbose Logging
```python
def verbose_log(msg):
    print(f"[DEBUG {time.time()}] {msg}")

run_session(goal, provider, config, log=verbose_log)
```

### Debug Log Output
```
[ORCHESTRATOR] route=browser confidence=0.95 reason=...
[WORKER #1] navigate -> https://...
-- ACTION LAYER: Navigating to https://...
-- PERCEPTION: title='...' url=...
[PLANNER] verdict=continue reasoning=...
[WORKER] click -- Click button to add to cart
-- ACTION LAYER: Clicking 'button:has-text("Add to cart")'
-- PERCEPTION: title='...' url=...
[PLANNER] verdict=done reasoning=...
*** AGENT FINAL ANSWER: Item added to cart ***
```

---

## Performance Tuning

| Setting | Value | Impact |
|---------|-------|--------|
| `max_steps` | 8-20 | More steps = thorough but slower |
| `PLANNER_INTERVAL` | 3 | Lower = more planning |
| `FAILED_CLICK_THRESHOLD` | 2 | Lower = faster skip |
| `rate_limit_per_min` | 15/30 | Higher = faster but risk 429 |
| `headless=False` | Visual debugging | Slower but visible |

### For Complex Tasks (20+ steps)
```python
config = EngineConfig(
    max_steps=20,
    planner_interval=4,      # Plan less frequently
    failed_click_threshold=3,  # More tolerance
    rate_limit_per_min=30,     # NVIDIA limit
)
```

---

## Testing

```python
# Unit test engine
from agent_engine import EngineConfig, run_session
from llm_providers import create_llm_provider

provider = create_llm_provider()
config = EngineConfig(max_steps=3, headless=True)
result = run_session("what is 2+2", provider, config, log=print)
assert result["status"] == "done"
assert "4" in result["final_answer"]
```