"""Flask web UI for the RunAgent SuperBrowser agent.

Architecture:
- POST /api/run   starts an agent run in a background thread, returns a session_id
- GET  /api/stream/<sid>  SSE stream of agent log lines + final answer
- GET  /          renders the chat-style side panel UI (Comet-like)
- POST /api/close-browser  kill the running browser

The agent runs in a worker thread so the UI stays responsive. The browser
itself runs in headless=False mode so you can see it on your desktop while
you chat with the agent.

Usage:
    python web_ui.py                       # bundled Chromium (Gemini)
    python web_ui.py --browser helium      # system Helium
    python web_ui.py --browser chrome      # system Chrome
    python web_ui.py --browser firefox     # system Firefox / Zen
    python web_ui.py --browser cdp         # attach to YOUR already-open browser
    python web_ui.py --port 5001           # different port
"""
import argparse
import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from dotenv import load_dotenv

from agent_engine import EngineConfig, run_session
from browser_config import resolve_browser
from llm_providers import create_llm_provider


load_dotenv()

# Initialize provider based on .env configuration
_PROVIDER_TYPE = os.getenv("api_provider", "gemini").lower()

# CLI args parsed once at import time
_PARSER = argparse.ArgumentParser(add_help=False)
_PARSER.add_argument("--browser", default=os.environ.get("AGENT_BROWSER", "chromium"),
                      help="chromium | helium | chrome | edge | brave | firefox | zen | cdp")
_PARSER.add_argument("--port", type=int, default=int(os.environ.get("AGENT_PORT", "5000")))
_PARSER.add_argument("--max-steps", type=int, default=int(os.environ.get("AGENT_MAX_STEPS", "8")))
_PARSER.add_argument("--model", default=None, help="Model name (defaults based on provider)")
_PARSER.add_argument("--vision", action="store_true", default=True, help="Enable vision grounding (SeeAct style)")
_PARSER.add_argument("--no-vision", action="store_false", dest="vision", help="Disable vision grounding")
_ARGS, _ = _PARSER.parse_known_args()

# Determine default model based on provider
if _ARGS.model is None:
    if _PROVIDER_TYPE == "nvidia":
        _ARGS.model = "nvidia/nemotron-3-ultra-550b-a55b"
    else:
        _ARGS.model = "gemini-3.5-flash-lite"

# Initialize provider based on .env configuration
try:
    _LLM_PROVIDER = create_llm_provider()
except (FileNotFoundError, ValueError) as e:
    print(f"[!] LLM Provider config error: {e}")
    _LLM_PROVIDER = None

try:
    _BROWSER_SPEC = resolve_browser(_ARGS.browser)
except (FileNotFoundError, ValueError) as e:
    print(f"[!] Browser config error: {e}")
    _BROWSER_SPEC = None  # surface in /api/health

app = Flask(__name__)


# ----- Session store --------------------------------------------------------


@dataclass
class Session:
    sid: str
    goal: str
    log_queue: queue.Queue = field(default_factory=queue.Queue)
    done: bool = False
    final_answer: str = ""
    status: str = "running"
    thread: threading.Thread | None = None
    # The Playwright browser object survives after the agent thread exits
    # so the user can keep interacting with the page. Closed by /api/close-browser.
    browser_obj: object = None
    playwright_obj: object = None


SESSIONS: dict[str, Session] = {}
SESSIONS_LOCK = threading.Lock()


def _new_sid() -> str:
    return f"s{int(time.time()*1000)}"


def _log_forwarder(session: Session, log_fn):
    """Adapter: agent_engine.log is `print`-like; we mirror to SSE queue."""
    def _inner(msg: str):
        session.log_queue.put({"type": "log", "msg": msg})
        log_fn(msg)  # also print to server console
    return _inner


def _run_agent_thread(session: Session, continue_from: dict = None):
    # Select model based on provider
    if _PROVIDER_TYPE == "nvidia":
        default_model = "nvidia/nemotron-3-ultra-550b-a55b"
        # NVIDIA has higher rate limit (40/min), allow more steps
        default_max_steps = 20
    else:
        default_model = "gemini-3.5-flash-lite"
        # Gemini has lower rate limit (15/min), fewer steps
        default_max_steps = 8
    
    config = EngineConfig(
        model=_ARGS.model if _ARGS.model != "gemini-3.5-flash-lite" else default_model,
        max_steps=_ARGS.max_steps if _ARGS.max_steps != 8 else default_max_steps,
        headless=False,
        keep_browser_open=True,  # UI: leave browser open so user can interact
        provider_type=_PROVIDER_TYPE,
        use_vision=_ARGS.vision,  # Enable vision grounding (SeeAct style)
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
        from llm_providers import create_llm_provider, get_rate_limiter
        from agent_engine import run_session
        
        provider = create_llm_provider()
        rate_limiter = get_rate_limiter(_PROVIDER_TYPE)
        
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


# ----- Routes ---------------------------------------------------------------


app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True)
    goal = (data.get("goal") or "").strip()
    if not goal:
        return jsonify({"error": "empty goal"}), 400
    if _LLM_PROVIDER is None:
        return jsonify({"error": "LLM provider not configured. Check .env for api_provider and API keys."}), 500

    sid = f"s{int(time.time()*1000)}"
    session = Session(sid=sid, goal=goal)
    with SESSIONS_LOCK:
        SESSIONS[sid] = session

    session.thread = threading.Thread(
        target=_run_agent_thread, args=(session,), daemon=True,
    )
    session.thread.start()
    return jsonify({"sid": sid})


@app.route("/api/stream/<sid>")
def api_stream(sid: str):
    with SESSIONS_LOCK:
        session = SESSIONS.get(sid)
    if session is None:
        return jsonify({"error": "unknown session"}), 404

    def event_stream():
        while True:
            try:
                item = session.log_queue.get(timeout=15)
            except queue.Empty:
                # heartbeat
                yield "event: ping\ndata: {}\n\n"
                if session.done:
                    break
                continue
            yield f"data: {json.dumps(item)}\n\n"
            if item.get("type") == "final":
                break

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok" if _BROWSER_SPEC else "browser-error",
        "sessions": len(SESSIONS),
        "browser": _BROWSER_SPEC.note if _BROWSER_SPEC else "not found",
        "browser_name": _ARGS.browser,
        "provider": _PROVIDER_TYPE,
        "model": _ARGS.model,
        "max_steps": _ARGS.max_steps,
    })


@app.route("/api/close-browser", methods=["POST"])
def api_close_browser():
    """Close any browser held alive by any session. Idempotent."""
    closed = 0
    for sid, sess in list(SESSIONS.items()):
        if sess.browser_obj is not None:
            try:
                sess.browser_obj.close()
                closed += 1
            except Exception:
                pass
            sess.browser_obj = None
    return jsonify({"closed": closed})


@app.route("/api/continue/<sid>", methods=["POST"])
def api_continue(sid: str):
    """Continue an exhausted session with more steps."""
    with SESSIONS_LOCK:
        session = SESSIONS.get(sid)
    if session is None:
        return jsonify({"error": "unknown session"}), 404
    
    if session.browser_obj is None:
        return jsonify({"error": "browser not available"}), 400
    
    # Restart the agent thread with the same browser
    session.done = False
    session.final_answer = ""
    session.status = "running"
    while not session.log_queue.empty():
        try:
            session.log_queue.get_nowait()
        except queue.Empty:
            break
    
    session.thread = threading.Thread(
        target=_run_agent_thread, args=(session, None), daemon=True,
    )
    session.thread.start()
    
    return jsonify({"status": "continuing", "sid": sid})


if __name__ == "__main__":
    print("RunAgent SuperBrowser UI starting on "
          f"http://localhost:{_ARGS.port}")
    if _BROWSER_SPEC:
        print(f"  browser : {_BROWSER_SPEC.note}")
    else:
        print("  browser : [ERROR] could not resolve browser — see above")
    print(f"  provider: {_PROVIDER_TYPE}")
    print(f"  model   : {_ARGS.model}")
    print(f"  steps   : {_ARGS.max_steps}")
    print(f"  vision  : {'enabled' if _ARGS.vision else 'disabled'}")
    app.run(host="0.0.0.0", port=_ARGS.port, debug=False, threaded=True)