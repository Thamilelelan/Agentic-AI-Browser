# Cognitive Layer Documentation

## Overview

The `cognitive_layer.py` implements the three-role cognitive architecture from the RunAgent SuperBrowser paper (§4.1):

1. **Orchestrator** - Task classification and routing
2. **Planner** - Progress evaluation and strategic decisions
3. **Worker** - Operational action execution

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Cognitive Layer                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ Orchestrator │    │   Planner    │    │     Worker       │  │
│  │  (Router)    │    │ (Evaluator)  │    │    (Executor)    │  │
│  └──────┬───────┘    └──────┬───────┘    └────────┬──────────┘  │
│         │                   │                   │              │
│         ▼                   ▼                   ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    LLM Provider                           │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Orchestrator (`run_orchestrator`)

**Purpose**: Classifies the user's task and routes to appropriate handler.

**Input**: User goal (string)
**Output**: `{route: "search"|"browser", confidence: float, reasoning: str}`

**Prompt Structure**:
```python
ORCHESTRATOR_PROMPT = """
You are the ORCHESTRATOR of an autonomous web agent.
Classify the user's task into ONE of these routes:

- "search"   : a factual lookup or aggregation (no browser needed)
- "browser"  : anything requiring real interaction (click, type, login, booking)

Respond ONLY with a JSON object:
{"route": "search" | "browser", "confidence": 0.0-1.0, "reasoning": "..."}

Task: "{goal}"
"""
```

**Routing Logic**:
- `search`: Factual lookups, calculations, definitions (no browser needed)
- `browser`: Navigation, clicking, form filling, booking, shopping

**Usage**:
```python
orch = run_orchestrator(provider, goal, rate_limiter)
route = orch.get("route", "browser")
```

---

### 2. Planner (`run_planner`)

**Purpose**: Evaluates progress and decides next steps. The ONLY place "done" can be declared.

**Called**: Every N steps (default 3) OR when worker signals "done"

**Input**: Goal, Ledger, Page Context, Last Action/Result

**Output**:
```json
{
  "verdict": "done" | "continue" | "abandon",
  "final_answer": "answer if done",
  "next_steps": ["step 1", "step 2", ...],
  "reasoning": "explanation"
}
```

**Verdict Types**:
- `done`: Goal achieved, return final_answer
- `continue`: Continue with next_steps
- `abandon`: Impossible task, return explanation

**Critical Rules** (from prompt):
- Multiple "not_found" dead-ends → goal impossible → `done` with honest answer
- Answer visible on page → `done` immediately
- Worker reached goal page → `done`
- Otherwise → `continue` with next_steps

**Prompt Variables**:
```python
prompt = PLANNER_PROMPT.format(
    goal=goal,
    ledger=ledger.render_for_planner(),
    title=page_context.get("title", "Unknown"),
    url=page_context.get("url", ""),
    text_snippet=page_context.get("text", "")[:1500],
    last_action=json.dumps(last_action),
    last_result=json.dumps(last_result),
)
```

**Model Config**:
```python
LLMConfig(model="", temperature=0.3, max_tokens=1000)
```

---

### 3. Worker

#### First Step (`run_worker_first_step`)
- No page loaded yet
- Decides starting URL based on goal
- Rules: Direct site URLs, DuckDuckGo for open searches, NEVER Google

#### Subsequent Steps (`run_worker_next_step`)
- Page IS loaded
- Chooses: navigate, click, type, scroll, press, mouseclick, search_google, done
- **Critical**: Must copy selector VERBATIM from interactive elements list

**Action Space**:
```json
{
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
}
```

**Key Rules for Worker**:
1. Use EXACT selector from interactive list - NO invented selectors
2. Use `search_google` for verification when unsure
3. Quote EXACT text from page for answers
4. Don't hallucinate - report only what's visible
4. YouTube: click home page videos, not /videos tab
5. Empty interactive list = page still loading → wait or scroll

**Search Google Action**:
```json
{
  "action": "search_google",
  "query": "search terms",
  "reasoning": "verify product existence on Google"
}
```

---

## Prompt Engineering

### Prompt Structure
All prompts follow this pattern:
1. Role definition
2. Context (goal, ledger, page state)
3. Action space definition
4. Critical rules
4. JSON schema with double-brace escaping

### Double-Brace Escaping
All JSON in prompts uses `{{` and `}}` for literal braces:
```python
prompt = """Respond ONLY with JSON:
{
  "action": "navigate",
  "url": "https://..."
}"""
```

### Variable Injection
Uses Python `.format()` with named placeholders:
```python
prompt = PROMPT.format(
    goal=goal,
    ledger=ledger.render_for_worker(),
    title=page_context.get("title", "Unknown"),
    ...
)
```

---

## Three-Role Interaction Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Orchestrator │───►│   Planner   │───►│   Worker    │
│  (Route)    │    │  (Evaluate) │    │  (Execute)  │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                  │                   │
       ▼                  ▼                   ▼
  route=search/      verdict=done/         action=navigate/
  browser            continue/             click/type/
                    abandon                 search_google
                                                  │
                                                  ▼
                                           ┌─────────────┐
                                           │   Ledger    │
                                           │  (Memory)   │
                                           └─────────────┘
```

---

## Rate Limiting Integration

Each cognitive function uses the rate limiter:
```python
rate_limiter.wait_if_needed()
response = provider.generate_json(prompt, config)
```

Provider-specific limits:
- NVIDIA: 30 req/min
- Gemini: 15 req/min

---

## Vision Grounding (SeeAct Style) — RunAgent §4.3

The cognitive layer includes vision grounding for visual decision-making using Set-of-Marks (SoM) prompting.

### `run_vision_grounding(vision_provider, goal, ledger, page_context, elements, rate_limiter) -> dict`

Runs vision grounding using SeeAct-style prompting with annotated screenshot.

**Parameters:**
- `vision_provider`: NvidiaVisionProvider instance
- `goal`: User goal string
- `ledger`: Ledger instance for memory context
- `page_context`: Dict with `annotated_screenshot_bytes`, `vision_elements`, viewport dims
- `elements`: List of interactive elements with bounding boxes
- `rate_limiter`: Vision rate limiter

**Returns:**
```python
{
    "element_id": 5,      # Selected element ID from SoM list
    "action": "click",    # "click" | "type" | "scroll" | "done"
    "text": "search",     # Text to type (if action="type")
    "reasoning": "..."    # Explanation
}
```

### Vision Grounding Prompt

```
You are the VISION GROUNDING module of an autonomous web agent (SeeAct / RunAgent style).

User Goal: "{goal}"

{ledger_text}

CURRENT PAGE - Set-of-Marks Annotated:
The screenshot has numbered bounding boxes on interactive elements.

INTERACTIVE ELEMENTS:
{elements_text}

TASK: Analyze the screenshot and the element list. Choose the SINGLE best element ID to interact with to make progress towards the goal.

RESPOND WITH JSON ONLY:
{
  "element_id": <number>,
  "action": "click" | "type" | "scroll" | "done",
  "text": "text to type (if type)",
  "reasoning": "brief explanation of why this element"
}

RULES:
- Pick element_id from the list above ONLY (must be a valid ID shown)
- If goal is achieved (answer visible on page), use element_id: -1, action: "done", text: "exact answer from page"
- If no suitable element, use element_id: -1, action: "scroll"
- For typing: action="type" with text field
- Prefer click on buttons/links, type on inputs
- If multiple similar elements, pick the one most relevant to goal
```

### `parse_vision_response(response) -> dict`

Validates and parses vision model response with fallback to scroll.

```python
# Handles parse errors gracefully
if response.get("_parse_error"):
    return {"element_id": -1, "action": "scroll", "text": "", "reasoning": "Vision parse error"}
```

### Integration Flow

```
Perception (action_layer.build_vision_context)
    │
    ▼
Cognitive Layer (run_vision_grounding)
    │  - Saves screenshot to temp file
    │  - Calls VLM with annotated screenshot + element list
    │  - Parses response
    ▼
Action Layer (execute_action with vision_click/vision_type)
    │  - Converts element_id to coordinates
    │  - Executes click/type at bbox center
    ▼
Ledger Update (records vision-grounded action)
```

### Usage in Agent Engine

```python
# In _run_session_inner (agent_engine.py)
if config.use_vision and vision_provider and context.get("vision_elements"):
    vision_decision = run_vision_grounding(
        vision_provider, goal, ledger, context, 
        context["vision_elements"], vision_rate_limiter
    )
    # Convert to executable action...
```