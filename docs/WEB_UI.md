# Web UI Documentation

## Overview

The `web_ui.py` module provides a Flask-based web interface with Server-Sent Events (SSE) streaming for the RunAgent SuperBrowser. It features a Comet-style chat sidebar UI with real-time agent log streaming.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Web UI (Flask + SSE)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐    ┌──────────────────┐    ┌────────────┐ │
│  │   Sidebar      │    │   Main Pane      │    │  Browser     │
│  │   (Chat)       │    │  (Log View)      │    │  (CDP)       │
│  └────────┬───────┘    └────────┬─────────┘    └──────┬──────┘  │
│           │                     │                      │         │
│           └─────────────────────┼──────────────────────┘         │
│                                 │                                │
│                    ┌────────────▼────────────┐                   │
│                    │      Agent Engine       │                   │
│                    │  (Cognitive + Action)   │                   │
│                    └────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Session Management

```python
@dataclass
class Session:
    sid: str                           # Session ID
    goal: str                          # User goal
    log_queue: queue.Queue             # SSE message queue
    done: bool = False                 # Session complete
    final_answer: str = ""             # Final answer
    status: str = "running"            # running|done|error
    thread: threading.Thread | None    # Background thread
    browser_obj: object = None         # Playwright browser
    playwright_obj: object = None      # Playwright instance
```

### Session Lifecycle

```
POST /api/run  ──► Create Session ──► Start Thread ──► Run Agent
                                      │
                                      ▼
                              SSE Stream (/api/stream/<sid>)
                                      │
                                      ▼
                              Client receives logs
                                      │
                                      ▼
                              "final" event ──► Session done
```

---

## API Endpoints

### `POST /api/run`
Start a new agent run.

**Request**:
```json
{
  "goal": "find price of iPhone 17 Pro on Amazon"
}
```

**Response**:
```json
{
  "sid": "s1786815416346"
}
```

### `GET /api/stream/<sid>`
Server-Sent Events stream for real-time logs.

**Response**: `text/event-stream`
```
data: {"type": "log", "msg": "[ORCHESTRATOR] route=browser..."}
data: {"type": "log", "msg": "[WORKER] click -- ..."}
data: {"type": "final", "answer": "4", "status": "done", "browser_alive": false}
```

**Event Types**:
| Type | Description |
|------|-------------|
| `log` | Agent log message |
| `final` | Session complete with answer |
| `ping` | Heartbeat (every 15s) |

---

### `GET /api/health`
Health check endpoint.

```json
{
  "status": "ok",
  "sessions": 0,
  "browser": "Playwright bundled Chromium (best stealth)",
  "browser_name": "chromium",
  "provider": "nvidia",
  "model": "nvidia/nemotron-3-ultra-550b-a55b",
  "max_steps": 8,
  "status": "ok"
}
```

### `POST /api/close-browser`
Force close all browsers.

```json
{"closed": 0}
```

### `POST /api/continue/<sid>`
Continue an exhausted session with more steps.

---

## Frontend (templates/index.html)

### UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  ██████████████████████████████████████████████████████████████ │
│  █  RunAgent SuperBrowser  autonomous web agent            █    │
│  ██████████████████████████████████████████████████████████████ │
├─────────────────────────────────────────────────────────────────┤
│ SIDEBAR (380px)                    │  MAIN PANE (flex)         │
│ ┌─────────────────────────────┐   │  ┌─────────────────────┐   │
│ │ 🟢 Agent Runtime          │   │  │  ┌─────────────────┐  │   │
│ │    live trace             │   │  │  │  ┌─────────────┐  │   │
│ ├─────────────────────────────┤   │  │  │  ┌─────────┐  │  │   │
│ │ Messages...               │   │  │  │  │  Logs   │  │  │   │
│ │ [User] find price...      │   │  │  │  │         │  │   │
│ │ [Bot] thinking...         │   │  │  │  └─────────┘  │   │
│ │ [Bot] ORCHESTRATOR        │   │  │  │  [Waterfall]  │  │   │
│ │ [Bot] FINAL ANSWER        │   │  │  │                 │  │   │
│ ├─────────────────────────────┤   │  └─────────────────┘   │   │
│ │ [Input] [Send]            │   │                           │   │
│ └─────────────────────────────┘   └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### CSS Design System (Neo-Brutalist)

```css
:root {
  --bg: #0a0a0a;
  --panel: #161922;
  --panel-2: #1c2030;
  --border: #262a36;
  --fg: #e6e8ee;
  --muted: #8a92a6;
  --accent: #ffff00;      /* Neon yellow */
  --accent-2: #5ee0c1;    /* Teal */
  --user: #2a3550;
  --bot: #1d2333;
  --danger: #ff6b6b;
  --ok: #5ee0c1;
}
```

**Typography**:
- Display: `Space Grotesk` (geometric, technical)
- Body: `DM Sans` (clean, readable)
- Mono: `JetBrains Mono` (code/logs)

**Visual Style**:
- 0 border-radius (sharp corners)
- Hard shadows: `4px 4px 0 0 var(--border)`
- Thick borders: 2px solid
- Hover: translate(-1px, -1px) + shadow shift

---

## SSE Streaming Protocol

### Event Format
```
data: {"type": "log", "msg": "[ORCHESTRATOR] route=browser..."}
data: {"type": "log", "msg": "[WORKER] click -- ..."}
data: {"type": "final", "answer": "4", "status": "done", "browser_alive": false}
```

### Client Implementation
```javascript
const evtSource = new EventSource(`/api/stream/${sid}`);

evtSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    
    if (data.type === "log") {
        appendLog(data.msg);
    } else if (data.type === "final") {
        showFinalAnswer(data.answer, data.status);
        sendBtn.disabled = false;
        evtSource.close();
    }
};

evtSource.onerror = () => {
    // Reconnect logic
};
```

---

## CLI Arguments

```bash
python web_ui.py [OPTIONS]

Options:
  --browser BROWSER     chromium | helium | chrome | edge | brave | firefox | zen | cdp
  --port PORT           Port (default: 5000)
  --max-steps N         Max steps per session (default: 8)
  --model MODEL         Model name (default: provider-specific)
```

### Browser Options

| Flag | Browser | Notes |
|------|---------|-------|
| `chromium` | Playwright bundled | Best stealth |
| `helium` | Helium Browser | `/opt/helium-browser-bin/chrome` |
| `chrome` | Google Chrome | `channel="chrome"` |
| `edge` | Microsoft Edge | `channel="msedge"` |
| `brave` | Brave Browser | |
| `firefox` | Firefox/Zen | Limited stealth |
| `cdp` | Attach to existing | Requires `--remote-debugging-port=9222` |

---

## SSE Streaming Protocol

### Event Types

```json
// Log entry
{"type": "log", "msg": "[ORCHESTRATOR] route=browser..."}

// Final answer
{"type": "final", "answer": "4", "status": "done", "browser_alive": false}

// Heartbeat
{"type": "ping", "data": {}}
```

### Client Implementation
```javascript
const evtSource = new EventSource(`/api/stream/${sid}`);

evtSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    
    if (data.type === "log") {
        appendLog(data.msg);
    } else if (data.type === "final") {
        showFinalAnswer(data.answer, data.status);
        sendBtn.disabled = false;
        evtSource.close();
        evtSource = null;
    }
};

evtSource.onerror = () => {
    // Reconnect logic
};
```

---

## Session Management

### Session Object
```python
@dataclass
class Session:
    sid: str                    # Unique session ID
    goal: str                   # User goal
    log_queue: queue.Queue      # SSE message queue
    done: bool = False          # Session complete
    final_answer: str = ""      # Final answer
    status: str = "running"     # running|done|error
    thread: threading.Thread | None  # Background thread
    browser_obj: object = None  # Playwright browser
    playwright_obj: object = None  # Playwright instance
```

### Thread Lifecycle
```python
def _run_agent_thread(session: Session):
    config = EngineConfig(
        model=_ARGS.model,
        max_steps=_ARGS.max_steps,
        headless=False,
        keep_browser_open=True,  # UI: leave browser open so user can interact
    )
    if _BROWSER_SPEC:
        config.browser = _BROWSER_SPEC.browser
        config.executable_path = _BROWSER_SPEC.executable_path or _BROWSER_SPEC.cdp_url
        config.channel = _BROWSER_SPEC.channel
        session.log_queue.put({
            "type": "log",
            "msg": f"[boot] using {_BROWSER_SPEC.note}",
        })
    else:
        session.log_queue.put({
            "type": "log",
            "msg": "[boot] browser spec missing — engine will fall back to bundled chromium",
        })

    try:
        result = run_session(
            goal=session.goal,
            provider=provider,
            config=config,
            log=_log_forwarder(session, print),
        )
        session.final_answer = result["final_answer"]
        session.status = result["status"]
        session.browser_obj = result.get("browser_obj")
        session.playwright_obj = result.get("playwright_obj")
    except Exception as e:
        session.final_answer = f"Engine error: {e}"
        session.status = "error"
        session.log_queue.put({"type": "log", "msg": f"[ERROR] {e}"})
    finally:
        session.done = True
        session.log_queue.put({
            "type": "final",
            "answer": session.final_answer,
            "status": session.status,
            "browser_alive": session.browser_obj is not None,
        })
```

---

## SSE Stream Format

### Message Types

```json
// Log entry
{"type": "log", "msg": "[ORCHESTRATOR] route=browser..."}

// Final answer
{"type": "final", "answer": "4", "status": "done", "browser_alive": false}

// Heartbeat
{"type": "ping", "data": {}}
```

### Client Handling
```javascript
evtSource.onmessage = (e) => {
    try {
        const data = JSON.parse(e.data);
        
        if (data.type === "log") {
            // Append to log view
            addLogEntry(data.msg);
        } else if (data.type === "final") {
            // Show final answer
            showFinalAnswer(data.answer, data.status);
            sendBtn.disabled = false;
            evtSource.close();
            evtSource = null;
        }
    } catch (err) {
        console.error(err);
    }
};

evtSource.onerror = () => {
    // Reconnect logic
};
```

---

## Session Management

### Session Object
```python
@dataclass
class Session:
    sid: str                    # Unique session ID
    goal: str                   # User goal
    log_queue: queue.Queue      # SSE message queue
    done: bool = False          # Session complete
    final_answer: str = ""      # Final answer
    status: str = "running"     # running|done|error
    thread: threading.Thread | None  # Background thread
    browser_obj: object = None  # Playwright browser
    playwright_obj: object = None  # Playwright instance
```

### Thread Lifecycle
```python
def _run_agent_thread(session: Session):
    config = EngineConfig(
        model=_ARGS.model,
        max_steps=_ARGS.max_steps,
        headless=False,
        keep_browser_open=True,  # UI: leave browser open so user can interact
    )
    if _BROWSER_SPEC:
        config.browser = _BROWSER_SPEC.browser
        config.executable_path = _BROWSER_SPEC.executable_path or _BROWSER_SPEC.cdp_url
        config.channel = _BROWSER_SPEC.channel
        session.log_queue.put({
            "type": "log",
            "msg": f"[boot] using {_BROWSER_SPEC.note}",
        })
    else:
        session.log_queue.put({
            "type": "log",
            "msg": "[boot] browser spec missing — engine will fall back to bundled chromium",
        })

    try:
        result = run_session(
            goal=session.goal,
            provider=provider,
            config=config,
            log=_log_forwarder(session, print),
        )
        session.final_answer = result["final_answer"]
        session.status = result["status"]
        session.browser_obj = result.get("browser_obj")
        session.playwright_obj = result.get("playwright_obj")
    except Exception as e:
        session.final_answer = f"Engine error: {e}"
        session.status = "error"
        session.log_queue.put({"type": "log", "msg": f"[ERROR] {e}"})
    finally:
        session.done = True
        session.log_queue.put({
            "type": "final",
            "answer": session.final_answer,
            "status": session.status,
            "browser_alive": session.browser_obj is not None,
        })
```

---

## SSE Stream Format

### Message Types

```json
// Log entry
{"type": "log", "msg": "[ORCHESTRATOR] route=browser..."}

// Final answer
{"type": "final", "answer": "4", "status": "done", "browser_alive": false}

// Heartbeat
{"type": "ping", "data": {}}
```

### Client Handling
```javascript
evtSource.onmessage = (e) => {
    try {
        const data = JSON.parse(e.data);
        
        if (data.type === "log") {
            // Append to log view
            addLogEntry(data.msg);
        } else if (data.type === "final") {
            thinkingEl.classList.add("final");
            thinkingEl.innerHTML =
              `<div class="role">final answer · status=${escapeHtml(data.status)}</div>` +
              escapeHtml(data.answer || "(no answer)");
            setStatus(
              data.browser_alive ? "done · browser open" : `done · ${data.status}`,
              data.status === "blocked" ? "blocked" :
              data.status === "error"   ? "error"   : "done"
            );
            sendBtn.disabled = false;
            evtSource.close();
            evtSource = null;
        }
    } catch (err) {
        console.error(err);
    }
};
```

---

## Browser Integration

### CDP Attach Mode
```bash
# Terminal 1: Start browser with remote debugging
/opt/helium-browser-bin/helium --remote-debugging-port=9222 \
  --user-data-dir=/tmp/helium-agent

# Terminal 2: Start agent
python web_ui.py --browser cdp
```

### Browser Spec Resolution
```python
def resolve_browser(name: str) -> BrowserSpec:
    # helium -> /opt/helium-browser-bin/chrome
    # chrome -> channel="chrome"
    # edge -> channel="msedge"
    # firefox -> firefox
    # cdp -> connect_over_cdp("http://localhost:9222")
```

---

## Rate Limiting

```python
def get_rate_limiter(provider_type: str) -> RateLimiter:
    if provider_type == "nvidia":
        return RateLimiter(max_requests=30, window_seconds=60)
    return RateLimiter(max_requests=15, window_seconds=60)
```

---

## Deployment

### Development
```bash
source venv/bin/activate
python web_ui.py --browser cdp --port 5000
```

### Production (Gunicorn)
```bash
gunicorn -w 4 -b 0.0.0.0:5000 web_ui:app
```

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "web_ui.py", "--port", "5000"]
```

---

## Security Considerations

1. **API Keys**: Never logged, stored in `.env`
2. **CORS**: Not configured (add for production)
3. **Rate Limiting**: Per-provider limits enforced
4. **Session Isolation**: Each session has isolated browser
5. **Input Validation**: Goal sanitized (stripped, length checked)
6. **No Code Execution**: Agent only drives browser, no eval()

---

## Monitoring

### Health Check
```bash
curl http://localhost:5000/api/health
```
```json
{
  "status": "ok",
  "sessions": 2,
  "browser": "Helium at /opt/helium-browser-bin/chrome",
  "browser_name": "helium",
  "model": "nvidia/nemotron-3-ultra-550b-a55b",
  "provider": "nvidia",
  "max_steps": 20,
  "status": "ok"
}
```

### Logs
```bash
# View logs
tail -f logs/app.log

# Structured logging
{"timestamp": "2026-08-15T23:01:10", "level": "INFO", "msg": "[ORCHESTRATOR] route=browser..."}
```