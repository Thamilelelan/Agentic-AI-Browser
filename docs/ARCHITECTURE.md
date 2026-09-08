# RunAgent SuperBrowser - Architecture Documentation

## Overview

This document describes the architecture of the RunAgent SuperBrowser, an autonomous web agent based on the **RunAgent SuperBrowser** architecture. The system uses an LLM to interpret user intents, determine navigation paths, and execute actions via browser automation.

## High-Level Architecture (with Vision)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RunAgent SuperBrowser                             │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │  Cognitive   │    │   Action     │    │   Perception + Vision    │  │
│  │    Layer     │◄───│    Layer     │───►│     Layer (Eyes)         │  │
│  │   (Brain)    │    │   (Body)     │    │                          │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────┘  │
│         │                   │                   │                      │
│         ▼                   ▼                   ▼                      │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────────────────┐  │
│  │  Orchestrator│    │   Planner    │    │  Worker + Vision       │  │
│  │   (Router)   │    │  (Evaluator) │    │  Grounding             │  │
│  └──────────────┘    └──────────────┘    └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Three-Layer Architecture

### 1. Cognitive Layer (Brain)
- **Location**: `cognitive_layer.py`
- **Responsibility**: Decision making, planning, reasoning
- **Components**:
  - **Orchestrator**: Task classification (search vs browser)
  - **Planner**: Progress evaluation, verdict decisions
  - **Worker**: Action emission (navigate, click, type, scroll, etc.)
  - **Vision Grounding**: SeeAct-style visual decision making (§4.3)

### 2. Action Layer (Body)
- **Location**: `action_layer.py`
- **Responsibility**: Execute actions against real Chromium via Playwright
- **Capabilities**: navigate, click, type, scroll, press, mouseclick, search_google
- **Vision Actions**: vision_click, vision_type (coordinate-based)
- **Features**: Shadow DOM traversal, stealth mode, anti-bot evasion, SoM annotation

### 3. Perception + Vision Layer (Eyes)
- **Location**: `action_layer.py` (`extract_page_context`, `build_vision_context`)
- **Text Perception**: Title, URL, visible text extraction
- **Vision Perception**: Screenshot capture, Set-of-Marks (SoM) annotation, bounding box extraction
- **Shadow DOM**: Deep traversal into shadow roots
- **Interactive Elements**: CSS selector generation with deduplication + normalized bounding boxes

## Multi-Provider LLM Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM Provider Factory                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────────┐     ┌─────────────────────────────┐  │
│   │   NvidiaProvider    │     │      GeminiProvider         │  │
│   │  (Primary)          │     │    (Fallback)               │  │
│   ├─────────────────────┤     ├─────────────────────────────┤  │
│   │ Model: nemotron-3   │     │ Model: gemini-3.5-flash-lite│  │
│   │ Endpoint: integrate │     │ Endpoint: Google GenAI      │  │
│   │ API: nvidia.com/v1  │     │ API: Google GenAI SDK       │  │
│   │ Streaming + Reasoning│     │ Standard JSON output        │  │
│   │ Rate: 30/min        │     │ Rate: 15/min                │  │
│   └─────────────────────┘     └─────────────────────────────┘  │
│                                                                  │
│   Factory: create_llm_provider() reads .env api_provider      │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
User Goal
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  run_session(goal, provider, config)                            │
├─────────────────────────────────────────────────────────────────┤
│  1. Create Ledger (goal, empty plan, empty recent, etc.)       │
│  2. Launch Browser (CDP or bundled Chromium)                   │
│  3. Orchestrator: Classify task → "browser" or "search"        │
│  4. If first step: Worker picks starting URL                   │
│  4. LOOP (max_steps):                                          │
│     │  Perception: extract_page_context(page)                  │
│     │  Planner (every 3 steps): evaluate progress, verdict     │
│     │  Worker: emit action (navigate/click/type/scroll/etc.)   │
│     │  Execute action via Playwright                           │
│     │  Update Ledger with StepOutcome                          │
│     │  Check: captcha, not-found, dead-ends                    │
│     │  Until: verdict="done" or max_steps reached             │
└─────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

1. **Three-Role Cognitive Architecture**: Separates strategic (Orchestrator/Planner) from operational (Worker) reasoning
2. **Structured Ledger**: Bounded recent history (3 steps) + persistent facts + dead-ends
3. **Provider Abstraction**: Pluggable LLM providers with automatic fallback
4. **CDP Attach Mode**: Reuse existing browser sessions (cookies, logins preserved)
5. **Stealth Mode**: Anti-detection via navigator.webdriver hiding, realistic UA
6. **Streaming LLM Responses**: NVIDIA Nemotron streaming with reasoning extraction
7. **Rate Limiting**: Per-provider rate limiting (NVIDIA: 30/min, Gemini: 15/min)
8. **Auto-fallback**: NVIDIA → Gemini on any error (commented out, ready to enable)
9. **Structured Output**: JSON-only LLM responses via mime-type enforcement
9. **Rate Limiting**: Token bucket implementation per provider

## File Structure

```
fyproject/
├── agent_engine.py        # Main orchestration engine
├── cognitive_layer.py     # Three-role cognitive architecture
├── action_layer.py        # Playwright actions + perception
├── llm_providers.py       # LLM provider abstraction (NVIDIA + Gemini)
├── memory.py              # Ledger, StepOutcome, DeadEnd
├── action_layer.py        # Playwright actions + perception
├── browser_config.py      # Browser resolution (Helium, Chrome, CDP, etc.)
├── web_ui.py              # Flask + SSE web interface
├── web_ui.py              # Flask + SSE web interface
├── templates/index.html   # Neo-brutalist UI with SSE streaming
├── .env                   # API keys (gemini_api_key, nvidia_api_key)
├── context.md             # Project context
├── requirements.txt       # Dependencies
└── docs/                  # This documentation
```

## Sequence Diagram: Task Execution

```
User          Web UI           Agent Engine          LLM Provider       Browser
  │              │                  │                   │               │
  │───goal─────►│                  │                   │               │
  │             │───POST /api/run──►│                   │               │
  │             │◄───{sid}──────────│                   │               │
  │             │                   │                   │               │
  │             │                   │───run_session()──►│               │
  │             │                   │                   │               │
  │             │                   │──────────────────►│ Launch Browser│
  │             │                   │                   │               │
  │             │                   │                   │──────────────►│
  │             │                   │                   │               │
  │             │                   │◄────page object───│               │
  │             │                   │                   │               │
  │             │                   │                   │               │
  │             │◄───SSE stream─────│                   │               │
  │             │                   │                   │               │
  ▼             ▼                   ▼                   ▼               ▼
```

## Configuration

### Environment Variables (.env)
```bash
# Provider Selection (nvidia | gemini)
api_provider=nvidia

# NVIDIA Build API
nvidia_api_key=your_nvidia_build_api_key
nvidia_model=nvidia/nemotron-3-ultra-550b-a55b

# Google Gemini (fallback)
gemini_api_key=your_google_api_key
gemini_model=gemini-3.5-flash-lite

# Optional: Custom browser
AGENT_BROWSER=cdp|helium|chrome|firefox|chromium
AGENT_PORT=5000
AGENT_MAX_STEPS=20
```

### Browser Options
| Name | Description | Executable Path |
|------|-------------|-----------------|
| `chromium` | Playwright bundled (default) | bundled |
| `helium` | Helium Browser | `/opt/helium-browser-bin/chrome` |
| `chrome` | Google Chrome | auto-detected |
| `edge` | Microsoft Edge | auto-detected |
| `brave` | Brave Browser | auto-detected |
| `firefox` | Firefox/Zen | auto-detected |
| `cdp` | Attach to existing browser | CDP endpoint |

### CDP Mode (Attach to Running Browser)
```bash
# Terminal 1: Start browser with CDP
/opt/helium-browser-bin/helium --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/helium-browser"

# Terminal 2: Start agent
python web_ui.py --browser cdp
```

## Rate Limiting

| Provider | Requests/Minute | Window |
|----------|-----------------|--------|
| NVIDIA | 30 | 60 seconds |
| Gemini | 15 | 60 seconds |

## Error Handling & Fallback

- **NVIDIA 401/403**: Authentication error → raise (not retried)
- **NVIDIA 429/5xx**: Retry with exponential backoff (max 3 attempts)
- **NVIDIA 401/403/5xx/429**: Auto-fallback to Gemini (commented out, ready to enable)
- **JSON Parse Errors**: Extracted from response text using regex
- **Max Retries**: 3 attempts with exponential backoff

## Security Considerations

- API keys stored in `.env` (not committed)
- Stealth mode: `navigator.webdriver` hidden, realistic UA
- CDP mode reuses existing browser (preserves cookies/sessions)
- No secrets in logs (API keys redacted)
- Rate limiting prevents API abuse