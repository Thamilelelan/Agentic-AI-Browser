# RunAgent SuperBrowser - Documentation

## Documentation Index

| File | Description |
|------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, data flow, and design decisions |
| [LLM_PROVIDERS.md](LLM_PROVIDERS.md) | NVIDIA Nemotron & Gemini provider details |
| [COGNITIVE_LAYER.md](COGNITIVE_LAYER.md) | Three-role cognitive architecture (Orchestrator/Planner/Worker) |
| [AGENT_ENGINE.md](AGENT_ENGINE.md) | Agent engine, session management, configuration |
| [ACTION_LAYER.md](ACTION_LAYER.md) | Browser actions, perception, click strategies |
| [MEMORY.md](MEMORY.md) | Ledger, dead-end memory, structured memory |
| [WEB_UI.md](WEB_UI.md) | Flask + SSE web interface, Comet-style UI |
| [BROWSER_CONFIG.md](BROWSER_CONFIG.md) | Browser resolution, CDP attach, stealth mode |
| [README.md](README.md) | This file |

---

## Quick Start

### Prerequisites
```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# For Helium browser (Arch/CachyOS)
sudo pacman -S helium-browser-bin
```

### Environment Setup
```bash
# Create .env file
cat > .env << EOF
api_provider=nvidia
nvidia_api_key=your_nvidia_build_api_key
gemini_api_key=your_google_api_key  # Optional fallback
EOF
```

### Run the Agent

```bash
# Terminal 1: Start Helium with remote debugging
/opt/helium-browser-bin/helium --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/helium-browser"

# Terminal 2: Start the agent UI
source venv/bin/activate
python web_ui.py --browser cdp

# Open http://localhost:5000 in your browser
```

---

## Project Structure

```
fyproject/
├── agent_engine.py          # Main orchestration engine
├── cognitive_layer.py       # Three-role cognitive architecture
├── action_layer.py          # Playwright actions + perception
├── llm_providers.py         # NVIDIA + Gemini providers
├── memory.py                # Ledger, dead-end memory
├── action_layer.py          # Playwright actions + perception
├── browser_config.py        # Browser resolution & CDP
├── web_ui.py                # Flask + SSE web interface
├── templates/index.html     # Neo-brutalist UI
├── .env                     # API keys
├── context.md               # Project context
├── docs/                    # This documentation
├── screenshots/             # Screenshots
├── venv/                    # Virtual environment
└── .env                     # API keys
```

---

## Key Features

### Multi-Provider LLM System
- **NVIDIA Nemotron 3 Ultra** (Primary) - 550B params, 1M context, agentic reasoning
- **Gemini 3.5 Flash Lite** (Fallback) - Fast, reliable fallback
- Automatic fallback on NVIDIA errors (401, 429, 5xx)
- Per-provider rate limiting (NVIDIA: 30/min, Gemini: 15/min)

### Three-Role Cognitive Architecture
1. **Orchestrator** - Routes task (search vs browser)
2. **Planner** - Evaluates progress, declares "done"
3. **Worker** - Executes actions (navigate, click, type, scroll, search_google)

### CDP Attach Mode
- Connects to your existing Helium/Chrome browser
- Preserves cookies, logins, sessions
- You keep using your browser while agent works

### Neo-Brutalist UI
- Dark theme with amber accent
- Comet-style chat sidebar
- Live SSE streaming logs
- Network waterfall log view
- Role-color-coded messages

### Smart Click Handling
- Multi-strategy click (CSS → text → JS)
- Amazon "Add to cart" span buttons
- Shadow DOM traversal
- Force click for hidden elements

### Smart Verification
- `search_google` action for fact-checking
- Google search → result analysis
- Automatic dead-end detection
- Dead-end memory prevents loops

---

## Quick Commands

```bash
# Start with Helium (CDP)
/opt/helium-browser-bin/helium --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/helium-browser"
python web_ui.py --browser cdp

# With Chrome
python web_ui.py --browser chrome

# With Firefox
python web_ui.py --browser firefox

# Custom port
python web_ui.py --port 5001

# Custom steps
python web_ui.py --max-steps 20
```

---

## Environment Variables

```bash
# Required
api_provider=nvidia              # or "gemini"
nvidia_api_key=your_nvidia_key

# Optional
gemini_api_key=your_key          # Fallback
api_provider=nvidia              # or "gemini"
nvidia_model=nvidia/nemotron-3-ultra-550b-a55b
gemini_model=gemini-3.5-flash-lite
```

---

## Example Goals

```bash
# E-commerce
"add iphone 17 pro to cart on amazon"
"find price of MacBook Pro M3 on apple.com"
"buy wireless headphones under 5000 on flipkart"

# Research
"search google to verify if iphone 17 pro exists on amazon"
"find price of RTX 4090 on newegg"
"compare prices of MacBook Pro M3 on amazon vs bestbuy"

# Automation
"login to github and create a repo named test"
"fill google form at url with data from csv"
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `connect ECONNREFUSED` | Start browser with `--remote-debugging-port=9222` |
| `401 Unauthorized` | Check NVIDIA API key in `.env` |
| `401/403` on NVIDIA | Falls back to Gemini automatically |
| `429 Rate Limited` | Wait or reduce request rate |
| `connect ECONNREFUSED` | Start browser with `--remote-debugging-port=9222` |
| `Fontconfig warning` | Cosmetic, ignore |

---

## License

MIT License - See LICENSE file for details.