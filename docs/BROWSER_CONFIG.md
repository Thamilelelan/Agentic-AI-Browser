# Browser Configuration Documentation

## Overview

The `browser_config.py` module handles browser resolution and specification for the RunAgent SuperBrowser. It maps user-friendly browser names to Playwright launch configurations, supporting both bundled browsers and system-installed browsers.

## BrowserSpec

```python
@dataclass
class BrowserSpec:
    browser: str            # 'chromium' | 'firefox' | 'cdp'
    executable_path: str | None
    channel: str | None     # For p.chromium.launch(channel=...)
    note: str = ""          # Human-readable description
    cdp_url: str | None = None  # For CDP attach mode
```

## Supported Browsers

| Flag | Browser | Resolution | Notes |
|------|---------|-----------|-------|
| `chromium` | Playwright bundled | No system install needed | Best stealth |
| `helium` | Helium Browser | `/opt/helium-browser-bin/chrome` | Arch/CachyOS package |
| `chrome` | Google Chrome | `channel="chrome"` or `/usr/bin/google-chrome*` |
| `edge` | Microsoft Edge | `channel="msedge"` or `/usr/bin/microsoft-edge*` |
| `brave` | Brave Browser | `/usr/bin/brave*` |
| `firefox` | Firefox/Zen/LibreWolf | `/usr/bin/firefox` etc. |
| `chromium-system` | System Chromium | `/usr/bin/chromium*` |
| `cdp` | Attach to running browser | Requires `--remote-debugging-port=9222` |

---

## Resolution Logic

```python
def resolve_browser(name: str) -> BrowserSpec:
    name = (name or "chromium").lower().strip()
    
    if name == "chromium":
        return BrowserSpec("chromium", None, None, "Playwright bundled Chromium")
    
    elif name == "helium":
        path = _first_existing([
            "/opt/helium-browser-bin/chrome",
            "/opt/helium-browser-bin/helium",
            "/usr/bin/helium-browser",
            shutil.which("helium-browser"),
            shutil.which("helium"),
        ])
        if not path:
            raise FileNotFoundError("Helium not found. Install: sudo pacman -S helium-browser-bin")
        return BrowserSpec("chromium", path, None, f"Helium at {path}")
    
    elif name == "chrome":
        path = _first_existing([
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/opt/google/chrome/chrome",
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
        ])
        if not path:
            return BrowserSpec("chromium", None, "chrome", "channel='chrome'")
        return BrowserSpec("chromium", path, None, f"Chrome at {path}")
    
    elif name == "edge":
        path = _first_existing([...])
        # Similar to Chrome
        
    elif name == "brave":
        path = _first_existing([...])
        if not path:
            raise FileNotFoundError("Brave not found on system")
        return BrowserSpec("chromium", path, None, f"Brave at {path}")
    
    elif name in ("firefox", "zen", "librewolf"):
        path = _first_existing([
            "/usr/bin/firefox",
            "/usr/bin/zen-browser",
            "/usr/bin/librewolf",
            shutil.which("firefox"),
            shutil.which("zen-browser"),
            shutil.which("librewolf"),
        ])
        return BrowserSpec("firefox", path, None, f"{name} at {path}")
    
    elif name == "chromium-system":
        path = _first_existing([...])
        if not path:
            raise FileNotFoundError("No system chromium found")
        return BrowserSpec("chromium", path, None, f"Chromium at {path}")
    
    elif name in ("cdp", "connect", "attach"):
        cdp_url = os.environ.get("CDP_URL", "http://localhost:9222")
        return BrowserSpec("cdp", None, None, f"CDP attach at {cdp_url}", cdp_url=cdp_url)
    
    raise ValueError(f"Unknown browser: {name}")
```

---

## Browser Launch Configurations

### Bundled Chromium (Default)
```python
browser = p.chromium.launch(
    headless=False,
    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
)
page = create_stealth_page(browser)
```

### System Browser with Channel
```python
browser = p.chromium.launch(
    headless=False,
    channel="chrome",  # or "msedge", "brave"
    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
)
```

### System Browser with Executable Path
```python
browser = p.chromium.launch(
    headless=False,
    executable_path="/usr/bin/google-chrome-stable",
    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
)
```

### Firefox
```python
browser = p.firefox.launch(
    headless=False,
    executable_path="/usr/bin/firefox",
    args=["--disable-blink-features=AutomationControlled"]
)
page = create_stealth_page_firefox(browser)
```

### CDP Attach Mode
```python
cdp_url = config.executable_path or os.environ.get("CDP_URL", "http://localhost:9222")
browser = p.chromium.connect_over_cdp(cdp_url)

# Reuse existing context/page
contexts = browser.contexts
if contexts:
    context = contexts[0]
    pages = context.pages
    page = pages[0] if pages else context.new_page()
else:
    context = browser.new_context()
    page = context.new_page()

# CDP browser is externally managed - don't close
config.keep_browser_open = True
```

---

## CDP Attach Mode (Attach to Running Browser)

### Prerequisites
```bash
# Start browser with remote debugging
/opt/helium-browser-bin/helium --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/helium-browser"
```

### Agent Connection
```bash
python web_ui.py --browser cdp
# or
python web_ui.py --browser cdp --port 5000
```

### How It Works
1. User starts their browser with `--remote-debugging-port=9222`
2. Agent connects via `p.chromium.connect_over_cdp("http://localhost:9222")`
3. Reuses existing browser context/pages (preserves cookies, logins)
4. Agent drives the existing browser window
10. Browser stays open after session (`keep_browser_open = True`)

### CDP URL Configuration
```bash
# Default
CDP_URL=http://localhost:9222

# Custom port
CDP_URL=http://localhost:9223 python web_ui.py --browser cdp

# Environment variable takes precedence over --browser cdp default
```

---

## Browser Resolution Priority

### Helium Browser (Arch/CachyOS)
```bash
# Package: helium-browser-bin (AUR)
# Binary: /opt/helium-browser-bin/chrome
# Wrapper: /usr/bin/helium-browser
```

### Google Chrome
```bash
# Preferred locations (in order):
1. /usr/bin/google-chrome-stable
2. /usr/bin/google-chrome
3. /opt/google/chrome/chrome
4. which google-chrome
```

### Microsoft Edge
```bash
1. /usr/bin/microsoft-edge-stable
2. /usr/bin/microsoft-edge
3. /opt/microsoft/msedge/msedge
```

### Brave Browser
```bash
1. /usr/bin/brave
2. /usr/bin/brave-browser
3. /opt/brave.com/brave/brave
```

### Firefox / Zen Browser / LibreWolf
```bash
1. /usr/bin/firefox
2. /usr/bin/zen-browser
3. /usr/bin/librewolf
```

### System Chromium
```bash
1. /usr/bin/chromium
2. /usr/bin/chromium-browser
3. /snap/bin/chromium
```

---

## Stealth Configuration

All browser launches include stealth measures:

```python
launch_kwargs = {
    "headless": config.headless,
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ],
}
if config.executable_path:
    launch_kwargs["executable_path"] = config.executable_path
if config.channel:
    launch_kwargs["channel"] = config.channel
```

### Stealth Page Configuration
```python
def create_stealth_page(browser, headless=False):
    context = browser.new_context(
        user_agent=STEALTH_USER_AGENT,
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )
    page = context.new_page()
    page.add_init_script(STEALTH_INIT_SCRIPT)
    return page
```

### Stealth Init Script
```javascript
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(parameters)
);

window.chrome = { runtime: {} };
```

---

## Browser Selection Guide

| Use Case | Recommended Browser | Command |
|----------|---------------------|---------|
| Maximum stealth | `chromium` (bundled) | `python web_ui.py` |
| Your logged-in session | `cdp` + Helium | `helium --remote-debugging-port=9222` |
| Chrome with profiles | `chrome` | `python web_ui.py --browser chrome` |
| Firefox testing | `firefox` | `python web_ui.py --browser firefox` |
| Maximum compatibility | `chromium` | Default |

---

## Environment Variables

```bash
# CDP Connection
CDP_URL=http://localhost:9222

# Browser Selection
AGENT_BROWSER=cdp|helium|chrome|edge|firefox|chromium

# Port
AGENT_PORT=5000

# Steps
AGENT_MAX_STEPS=20

# Model (provider-specific)
AGENT_MODEL=nvidia/nemotron-3-ultra-550b-a55b
```

---

## Troubleshooting

### Helium Not Found
```
FileNotFoundError: Helium browser not found. Searched:
  /opt/helium-browser-bin/chrome
  /usr/bin/helium-browser
  $PATH (helium, helium-browser)
Install it with: sudo pacman -S helium-browser-bin
```

### CDP Connection Refused
```
Error: connect ECONNREFUSED ::1:9222
```
**Fix**: Ensure browser is running with `--remote-debugging-port=9222`

### CDP Version Mismatch
```
Error: Protocol version mismatch
```
**Fix**: Match Playwright version to browser version, or use bundled Chromium.

### Permission Denied
```
Error: Permission denied: /opt/helium-browser-bin/chrome
```
**Fix**: `chmod +x /opt/helium-browser-bin/chrome`

---

## CDP Attach Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        User's Machine                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐     ┌──────────────────┐                   │
│  │   Helium/Chrome │     │  Agent Process   │                   │
│  │  (User Browser) │     │  (web_ui.py)     │                   │
│  │                 │     │                  │                   │
│  │ --remote-       │     │                  │                   │
│  │ debugging-port= │     │  p.chromium.     │                   │
│  │ 9222            │────►│ connect_over_cdp │                   │
│  │                 │     │ ("http://         │                   │
│  │  [User Profile] │     │  localhost:9222) │                   │
│  │  [Cookies]      │     │        │         │                   │
│  │  [Logins]       │     │        ▼         │                   │
│  │  [History]      │     │  browser.contexts[0]                 │
│  │                 │     │        │         │                   │
│  └─────────────────┘     │  context.pages[0]  │                   │
│                          │        │         │                   │
│                          │        ▼         │                   │
│                          │  page.goto()     │                   │
│                          │  page.click()    │                   │
│                          │  page.fill()     │                   │
│                          └──────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

## Environment Variables

```bash
# CDP Connection
CDP_URL=http://localhost:9222

# Browser Selection
AGENT_BROWSER=cdp|helium|chrome|edge|firefox|chromium

# Port
AGENT_PORT=5000

# Steps
AGENT_MAX_STEPS=20

# Model (provider-specific)
AGENT_MODEL=nvidia/nemotron-3-ultra-550b-a55b
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `connect ECONNREFUSED` | Browser not started | Start browser with `--remote-debugging-port=9222` |
| `Protocol version mismatch` | Version mismatch | Match Playwright to browser version |
| `Permission denied` | Binary not executable | `chmod +x /opt/helium-browser-bin/chrome` |
| `No contexts found` | No browser windows open | Open a tab in the browser first |
| `Protocol version mismatch` | Playwright/browser mismatch | Use bundled Chromium or match versions |