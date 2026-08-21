# RunAgent SuperBrowser — Final-Year Project

This project is an autonomous web agent built on top of the
**RunAgent SuperBrowser** architecture (arxiv:2606.09399). It uses an LLM as
its "brain" to drive a real Chromium browser via Playwright, and now ships
with a Comet-style chat sidebar UI.

## What's new in this version

- **Three-role cognitive architecture** (Orchestrator → Planner → Worker)
  matching the RunAgent SuperBrowser paper's §4.1.
- **Structured Ledger** with bounded-recent actions, facts, dead-ends, and
  checkpoints (paper §5.2).
- **Dead-end memory** — when the same search query returns "no results"
  twice, the Planner is shown the failure and the Worker can declare the
  goal impossible. Fixes the "PewDiePie Gantz" infinite-loop bug.
- **Comet-style Flask web UI** — chat sidebar that streams the agent's log
  in real time via SSE. Open `http://localhost:5000` and talk to the agent
  while it drives a real browser on your desktop.

## File layout

```
memory.py             # Ledger + StepOutcome + DeadEnd (paper §5.2)
cognitive_layer.py    # Orchestrator / Planner / Worker roles (paper §4.1)
action_layer.py       # Playwright action execution + shadow-DOM perception
agent_engine.py       # Algorithm 1 — main cognitive-action loop
web_ui.py             # Flask app + SSE streaming
templates/index.html  # Comet-style chat sidebar UI

agentic_browser.py    # ORIGINAL single-role script (still works, with Part A fix)
browser_llm.py        # Original v1: navigate-only demo
borwser_unit.py       # Original v0: Playwright hello-world
context.md            # Project context / architecture notes
explanation.md        # Detailed explanation of prompt_browser.py
```

## Running

### 1. Chat sidebar UI (recommended)

```bash
source venv/bin/activate
python web_ui.py                                  # bundled Chromium
python web_ui.py --browser helium                 # Helium Browser (auto-launched)
python web_ui.py --browser chrome --port 5001     # system Chrome, port 5001
python web_ui.py --browser firefox --max-steps 10 # Firefox/Zen
python web_ui.py --browser cdp                    # attach to YOUR already-open browser
# open http://localhost:5000
```

**CDP attach mode (use YOUR browser, not a fresh one):**

```bash
# Terminal 1: Start YOUR browser with remote debugging
helium --remote-debugging-port=9222 --user-data-dir=/tmp/helium-agent
# OR for Chrome: google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-agent

# Terminal 2: Start the agent (it will CONNECT to the running browser)
python web_ui.py --browser cdp
# open http://localhost:5000
```

This lets the agent drive your actual Helium/Chrome window — complete with
your logged-in Gmail, Calendar, extensions, cookies, etc. You just keep
using the browser normally; the agent drives it remotely via CDP.

Supported browsers:

| Flag | Browser | Notes |
|---|---|---|
| `chromium` (default) | Playwright bundled | Best stealth, no system install |
| `helium` | Helium Browser | Auto-launches `/opt/helium-browser-bin/chrome` |
| `chrome` | Google Chrome stable | channel or `/usr/bin/google-chrome*` |
| `edge` | Microsoft Edge | channel or `/usr/bin/microsoft-edge*` |
| `brave` | Brave Browser | `/usr/bin/brave*` |
| `firefox` / `zen` | Firefox / Zen | Limited stealth tricks |
| `chromium-system` | Any Chromium on PATH | `/usr/bin/chromium*` |
| **`cdp` / `connect` / `attach`** | **Your running browser** | Start it yourself with `--remote-debugging-port=9222` |

The browser **stays open after the agent finishes**, so you can interact
with the page (e.g. confirm a calendar invite, double-check the answer).
Click **close browser** in the sidebar when you're done, or hit
`POST /api/close-browser`.

### 2. Terminal script (original)

```bash
source venv/bin/activate
python agentic_browser.py
# type your prompt, watch the browser, press ENTER to close
```

### 3. Engine only (programmatic)

```python
from agent_engine import EngineConfig, run_session
from browser_config import resolve_browser

spec = resolve_browser("helium")
config = EngineConfig(
    model="gemini-3.5-flash-lite",
    max_steps=8,
    headless=False,
    browser=spec.browser,
    executable_path=spec.executable_path,
    keep_browser_open=True,   # don't auto-close
)
result = run_session(
    goal="find the price of iPhone 16 Pro on Amazon India",
    api_key="...",
    config=config,
    log=print,
)
print(result["final_answer"])
# result["browser_obj"], result["playwright_obj"] are still alive
```

## Architecture (per RunAgent SuperBrowser paper)

```
User prompt ──► Orchestrator (classify: search vs browser)
                       │
                       ▼
                  Ledger (goal, plan, recent[3], facts, dead_ends)
                       │
                       ▼  loop (max MAX_STEPS):
                  Perception (shadow-DOM interactive list + text)
                       │
                       ▼ every N=3 steps:
                  Planner (verdict: done | continue | abandon)
                       │
                       ▼
                  Worker (emit 1 action: navigate/click/type/scroll/press)
                       │
                       ▼
                  Action layer (Playwright + stealth Chromium)
                       │
                       ▼
                  update Ledger ────► back to Perception
```

When the Worker or Planner declares `done`, the loop breaks and the final
answer is returned. If the page is a CAPTCHA, the engine auto-pivots to
DuckDuckGo → Bing → Wikipedia. If 2+ searches return no results, the
Planner is shown the dead-ends and can declare the goal impossible.

## Why the dead-end memory matters

This is what makes the agent *stop looping* on impossible tasks. Example:

- User: "play the PewDiePie video about Gantz"
- Worker navigates to DuckDuckGo search → page says "no results found"
- Engine records a `DeadEnd(cause="not_found", url=...)` in the Ledger
- Worker keeps trying YouTube search → no results
- After 2 not-found dead-ends, the Planner's prompt shows them
- Planner declares `verdict="done"` with an honest answer:
  *"Could not find a PewDiePie video about Gantz after multiple searches."*

Without the Ledger, the previous script kept searching DuckDuckGo/YouTube
forever. The paper's **prediction P2** ("failures should be remembered as
negative landmarks") is operationalized by this design.

## Stealth

`action_layer.create_stealth_page()` strips `navigator.webdriver`, fakes
plugins/languages, and overrides the `notifications` permissions query. This
reduces — but doesn't eliminate — bot detection. Pair with `T3_PERSIST_PROFILE=1`
in a `.env` for warm-cookie profiles on hard targets (per the SuperBrowser
repo).

## Rate limiting

The Gemini free tier allows ~15 req/min on flash-lite. `RateLimiter` in
`agent_engine.py` enforces this with a rolling 60s window. If you hit the
cap, the engine prints `[RATE LIMIT] Sleeping Xs…` and pauses.

## Known limitations

- Vision pipeline is simplified: we use shadow-DOM scraping, not a true
  vision model with bounding boxes. (Paper §4.3 — out of scope for FY project.)
- No chevron-aware bbox snapper (paper §6.1).
- No persistent cookie profiles across sessions.
- No three-tier click cascade (CDP→Puppeteer→scripted) — single Playwright click.

These are explicit follow-ups per `context.md` "Next Development Milestones".

## Browser Stealth

`action_layer.py` uses a stealth profile that:

- Strips `navigator.webdriver`
- Fakes `navigator.plugins`, `navigator.languages`
- Overrides `notifications` permissions query
- Adds `window.chrome = { runtime: {} }`
- Uses realistic User-Agent + viewport (1366×768)

Works best with **Chromium-based browsers** (Helium, Chrome, Edge, Brave).
Firefox/ZEN share the same engine but lack some CDP stealth hooks — you'll
get more captchas and less reliable clicks.

## Reference

- Paper: https://arxiv.org/abs/2606.09399
- Authors' repo: https://github.com/runagent-dev/runagent-superbrowser
