"""Resolve which browser to launch based on user-friendly names.

Adds auto-detection for Helium, Chrome, Edge, Brave, Firefox on Linux/Arch.
"""
import os
import shutil
from dataclasses import dataclass


@dataclass
class BrowserSpec:
    browser: str            # 'chromium' | 'firefox' | 'cdp'
    executable_path: str | None
    channel: str | None
    note: str = ""
    cdp_url: str | None = None


def _first_existing(paths: list[str]) -> str | None:
    for p in paths:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


# Known CDP ports people commonly use
_DEFAULT_CDP_URL = "http://localhost:9222"


def resolve_browser(name: str) -> BrowserSpec:
    """Map a friendly browser name to a Playwright launch spec.

    Supported:
      chromium  — Playwright's bundled Chromium (default; no system install)
      helium    — Helium Browser (Arch: /opt/helium-browser-bin/chrome)
      chrome    — Google Chrome stable
      edge      — Microsoft Edge
      brave     — Brave Browser
      chromium-system — any Chromium binary on PATH
      firefox   — Firefox / Zen / LibreWolf (limited stealth)
    """
    name = (name or "chromium").lower().strip()

    if name == "chromium":
        return BrowserSpec("chromium", None, None,
                           "Playwright bundled Chromium (best stealth)")

    if name == "helium":
        path = _first_existing([
            "/opt/helium-browser-bin/chrome",
            "/opt/helium-browser-bin/helium",
            "/usr/bin/helium-browser",
            shutil.which("helium-browser"),
            shutil.which("helium"),
        ])
        if not path:
            raise FileNotFoundError(
                "Helium browser not found. Searched:\n"
                "  /opt/helium-browser-bin/chrome\n"
                "  /usr/bin/helium-browser\n"
                "  $PATH (helium, helium-browser)\n"
                "Install it with: sudo pacman -S helium-browser-bin"
            )
        return BrowserSpec("chromium", path, None,
                           f"Helium at {path}")

    if name == "chrome":
        path = _first_existing([
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/opt/google/chrome/chrome",
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
        ])
        if not path:
            return BrowserSpec("chromium", None, "chrome",
                               "channel='chrome' (Playwright auto-detects)")
        return BrowserSpec("chromium", path, None, f"Chrome at {path}")

    if name == "edge":
        path = _first_existing([
            "/usr/bin/microsoft-edge-stable",
            "/usr/bin/microsoft-edge",
            "/opt/microsoft/msedge/msedge",
            shutil.which("microsoft-edge"),
            shutil.which("microsoft-edge-stable"),
        ])
        if not path:
            return BrowserSpec("chromium", None, "msedge",
                               "channel='msedge'")
        return BrowserSpec("chromium", path, None, f"Edge at {path}")

    if name == "brave":
        path = _first_existing([
            "/usr/bin/brave",
            "/usr/bin/brave-browser",
            "/opt/brave.com/brave/brave",
            shutil.which("brave"),
            shutil.which("brave-browser"),
        ])
        if not path:
            raise FileNotFoundError("Brave not found on system")
        return BrowserSpec("chromium", path, None, f"Brave at {path}")

    if name in ("firefox", "zen", "librewolf"):
        path = _first_existing([
            "/usr/bin/firefox",
            "/usr/bin/zen-browser",
            "/usr/bin/librewolf",
            shutil.which("firefox"),
            shutil.which("zen-browser"),
            shutil.which("librewolf"),
        ])
        if not path:
            raise FileNotFoundError(f"{name} not found on system")
        return BrowserSpec("firefox", path, None, f"{name} at {path}")

    if name == "chromium-system":
        path = _first_existing([
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        ])
        if not path:
            raise FileNotFoundError("No system chromium found")
        return BrowserSpec("chromium", path, None, f"Chromium at {path}")

    if name in ("cdp", "connect", "attach"):
        # Connect to an already-running browser via CDP.
        # User must have started it with: helium --remote-debugging-port=9222
        cdp_url = os.environ.get("CDP_URL", _DEFAULT_CDP_URL)
        return BrowserSpec("cdp", None, None, f"CDP attach at {cdp_url}", cdp_url=cdp_url)

    raise ValueError(
        f"Unknown browser: {name!r}. Supported: "
        "chromium, helium, chrome, edge, brave, firefox, zen, librewolf, chromium-system"
    )
