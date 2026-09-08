"""Action layer: Playwright action execution + page perception.

Per RunAgent SuperBrowser §6: actions are simple primitives (navigate / click
/ type / scroll / press / mouseclick) executed against a real Chromium. The
three-tier click cascade (CDP -> Puppeteer -> scripted) is a single Playwright
click in our simplified setup.

Perception: extract_page_context returns title, URL, visible text, and a
shadow-DOM-aware list of interactive elements with valid CSS selectors.

Vision: Set-of-Marks (SoM) annotation and visual grounding per §4.3, §6.1
"""
import json
import base64
from io import BytesIO
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


STEALTH_INIT_SCRIPT = """
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
"""


def create_stealth_page(browser, headless: bool = False):
    context = browser.new_context(
        user_agent=STEALTH_USER_AGENT,
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )
    page = context.new_page()
    page.add_init_script(STEALTH_INIT_SCRIPT)
    return page


def create_stealth_page_firefox(browser):
    """Firefox-friendly variant. Firefox doesn't expose user_agent via
    new_context() and doesn't strip navigator.webdriver the same way —
    stealth is less effective here."""
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )
    page = context.new_page()
    page.set_extra_http_headers({
        "User-Agent": STEALTH_USER_AGENT,
    })
    return page


# ----- Perception ----------------------------------------------------------


_INTERACTIVE_JS = """() => {
    const collectDeep = (root) => {
        const out = [];
        const walk = (node) => {
            try {
                const els = node.querySelectorAll(
                    'a[href], button, input:not([type="hidden"]), select, textarea, ' +
                    '[role="button"], [tabindex]:not([tabindex="-1"])'
                );
                for (const el of els) out.push(el);
            } catch (e) {}
            const all = node.querySelectorAll('*');
            for (const el of all) {
                if (el.shadowRoot) walk(el.shadowRoot);
            }
        };
        walk(root);
        return out;
    };

    const isVisible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
               style.visibility !== 'hidden' && style.display !== 'none';
    };

    const escapeId = (id) => {
        try { return '#' + CSS.escape(id); } catch (e) { return ''; }
    };

    const escapeClass = (cls) => {
        try { return '.' + cls.split(' ').filter(Boolean).map(c => CSS.escape(c)).join('.'); }
        catch (e) { return ''; }
    };

    const escapeAttr = (val) => String(val).replace(/"/g, '\\\\"');

    const makeSelector = (el) => {
        const tag = el.tagName.toLowerCase();
        if (el.id) {
            const s = escapeId(el.id);
            if (s and document.querySelectorAll(s).length === 1) return s;
        }
        if (el.name) {
            const s = tag + '[name="' + escapeAttr(el.name) + '"]';
            if (document.querySelectorAll(s).length === 1) return s;
        }
        if (el.getAttribute('href')) {
            const href = el.getAttribute('href');
            if (href.length < 200) {
                const s = tag + '[href*="' + escapeAttr(href.slice(0, 40)) + '"]';
                try {
                    if (document.querySelectorAll(s).length <= 5) return s;
                } catch (e) {}
            }
        if (typeof el.className === 'string' && el.className.trim()) {
            const cls = el.className.trim().split(/\\s+/).slice(0, 2).join(' ');
            const s = tag + escapeClass(cls);
            try {
                if (document.querySelectorAll(s).length <= 5) return s;
            } catch (e) {}
        }
        return '';
    };

    const allElements = collectDeep(document);
    const results = [];
    const seen = new Set();

    for (const el of allElements) {
        if (!isVisible(el)) continue;

        const tag = el.tagName.toLowerCase();
        const text = (el.innerText or el.value or el.placeholder or el.getAttribute('aria-label') or '').trim().slice(0, 80);
        const selector = makeSelector(el);

        if (!selector) continue;
        if (seen.has(selector)) continue;
        seen.add(selector);

        let roleLabel = '';
        if (tag == 'input') {
            roleLabel = '[' + (el.type or 'text') + ' input]';
        } else if (tag == 'button' or el.getAttribute('role') == 'button') {
            roleLabel = '[button]';
        } else if (tag == 'select') {
            roleLabel = '[dropdown]';
        } else if (tag == 'textarea') {
            roleLabel = '[text area]';
        } else if (tag == 'a') {
            roleLabel = '[link]';
        }

        results.push({
            selector: selector,
            text: text,
            tag: tag,
            href: el.getAttribute('href') or '',
            role: roleLabel
        });

        if (results.length >= 80) break;
    }
    return results;
}
"""


def extract_page_context(page) -> dict:
    ctx = {}
    try:
        ctx["title"] = page.title()
    except Exception:
        ctx["title"] = ""
    try:
        ctx["url"] = page.url
    except Exception:
        ctx["url"] = ""
    try:
        ctx["text"] = page.inner_text("body")
    except Exception:
        ctx["text"] = ""

    try:
        # YouTube needs extra time for shadow DOM to hydrate
        if "youtube.com" in page.url:
            page.wait_for_timeout(2000)
            # Force a re-layout to ensure shadow roots are attached
            page.evaluate("""() => {
                document.body.style.display = 'none';
                document.body.offsetHeight; // force reflow
                document.body.style.display = '';
            }""")
        # Amazon needs extra time for dynamic content
        elif "amazon." in page.url:
            page.wait_for_timeout(4000)
            # Wait for product grid to load
            try:
                page.wait_for_selector('[data-component-type="s-search-result"], .s-result-item, [data-asin], .sg-col-inner', timeout=8000)
            except Exception:
                pass
        interactive = page.evaluate(_INTERACTIVE_JS)
        ctx["interactive"] = json.dumps(interactive, indent=2)
    except Exception as e:
        ctx["interactive"] = "[]  // error: " + str(e)
    return ctx


# ----- Vision (Set-of-Marks) -------------------------------------------------


_INTERACTIVE_WITH_BBOX_JS = """() => {
    const collectDeep = (root) => {
        const out = [];
        const walk = (node) => {
            try {
                const els = node.querySelectorAll(
                    'a[href], button, input:not([type="hidden"]), select, textarea, ' +
                    '[role="button"], [tabindex]:not([tabindex="-1"])'
                );
                for (const el of els) out.push(el);
            } catch (e) {}
            const all = node.querySelectorAll('*');
            for (const el of all) {
                if (el.shadowRoot) walk(el.shadowRoot);
            }
        };
        walk(root);
        return out;
    };

    const isVisible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
               style.visibility !== 'hidden' && style.display !== 'none';
    };

    const escapeId = (id) => {
        try { return '#' + CSS.escape(id); } catch (e) { return ''; }
    };

    const escapeClass = (cls) => {
        try { return '.' + cls.split(' ').filter(Boolean).map(c => CSS.escape(c)).join('.'); }
        catch (e) { return ''; }
    };

    const escapeAttr = (val) => String(val).replace(/"/g, '\\\\"');

    const makeSelector = (el) => {
        const tag = el.tagName.toLowerCase();
        if (el.id) {
            const s = escapeId(el.id);
            if (s && document.querySelectorAll(s).length === 1) return s;
        }
        if (el.name) {
            const s = tag + '[name="' + escapeAttr(el.name) + '"]';
            if (document.querySelectorAll(s).length === 1) return s;
        }
        if (el.getAttribute('href')) {
            const href = el.getAttribute('href');
            if (href.length < 200) {
                const s = tag + '[href*="' + escapeAttr(href.slice(0, 40)) + '"]';
                try {
                    if (document.querySelectorAll(s).length <= 5) return s;
                } catch (e) {}
            }
        }
        if (typeof el.className === 'string' && el.className.trim()) {
            const cls = el.className.trim().split(/\\s+/).slice(0, 2).join(' ');
            const s = tag + escapeClass(cls);
            try {
                if (document.querySelectorAll(s).length <= 5) return s;
            } catch (e) {}
        }
        return '';
    };

    const allElements = collectDeep(document);
    const results = [];
    const seen = new Set();
    let elementId = 0;

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    for (const el of allElements) {
        if (!isVisible(el)) continue;

        const tag = el.tagName.toLowerCase();
        const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 80);
        const selector = makeSelector(el);

        if (!selector) continue;
        if (seen.has(selector)) continue;
        seen.add(selector);

        const rect = el.getBoundingClientRect();
        const x = (rect.left + rect.width / 2) / viewportWidth;
        const y = (rect.top + rect.height / 2) / viewportHeight;
        const width = rect.width / viewportWidth;
        const height = rect.height / viewportHeight;

        if (x < 0 || x > 1 || y < 0 || y > 1 || width < 0.01 || height < 0.01) continue;

        let roleLabel = '';
        if (tag == 'input') {
            roleLabel = '[' + (el.type || 'text') + ' input]';
        } else if (tag == 'button' || el.getAttribute('role') == 'button') {
            roleLabel = '[button]';
        } else if (tag == 'select') {
            roleLabel = '[dropdown]';
        } else if (tag == 'textarea') {
            roleLabel = '[text area]';
        } else if (tag == 'a') {
            roleLabel = '[link]';
        }

        results.push({
            id: elementId,
            selector: selector,
            text: text,
            tag: tag,
            href: el.getAttribute('href') || '',
            role: roleLabel,
            bbox: [x, y, width, height]
        });

        elementId++;
        if (results.length >= 80) break;
    }
    return {elements: results, viewportWidth: viewportWidth, viewportHeight: viewportHeight};
}"""


def extract_elements_with_bbox(page) -> dict:
    """Extract interactive elements with bounding boxes from page.
    Returns dict with elements list and viewport dimensions."""
    try:
        result = page.evaluate(_INTERACTIVE_WITH_BBOX_JS)
        return result
    except Exception as e:
        return {"elements": [], "viewportWidth": 1366, "viewportHeight": 768, "error": str(e)}


def take_screenshot(page, path: Optional[str] = None, timeout: int = 60000) -> bytes:
    """Take screenshot and return as bytes. Optionally save to path."""
    screenshot_bytes = page.screenshot(type="png", timeout=timeout)
    if path:
        with open(path, "wb") as f:
            f.write(screenshot_bytes)
    return screenshot_bytes


def draw_som_annotations(
    screenshot_bytes: bytes,
    elements: list[dict],
    output_path: Optional[str] = None
) -> bytes:
    """Draw Set-of-Marks (SoM) annotations on screenshot.
    
    Draws numbered bounding boxes on each interactive element.
    Returns annotated image as bytes.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("PIL not available. Install with: pip install pillow")
    
    img = Image.open(BytesIO(screenshot_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    width, height = img.size
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except Exception:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
    
    colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
        (255, 0, 255), (0, 255, 255), (255, 128, 0), (128, 0, 255),
    ]
    
    for i, el in enumerate(elements):
        bbox = el.get("bbox", [0, 0, 0, 0])
        x, y, w, h = bbox
        
        left = int((x - w/2) * width)
        top = int((y - h/2) * height)
        right = int((x + w/2) * width)
        bottom = int((y + h/2) * height)
        
        left = max(0, min(left, width - 1))
        top = max(0, min(top, height - 1))
        right = max(0, min(right, width))
        bottom = max(0, min(bottom, height))
        
        if right <= left or bottom <= top:
            continue
        
        color = colors[i % len(colors)]
        element_id = el.get("id", i)
        
        draw.rectangle([left, top, right, bottom], outline=color, width=3)
        
        label = str(element_id)
        if font:
            text_bbox = draw.textbbox((left, top), label, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
            draw.rectangle(
                [left, top - text_h - 4, left + text_w + 8, top],
                fill=color
            )
            draw.text((left + 4, top - text_h - 2), label, fill=(255, 255, 255), font=font)
        else:
            draw.rectangle([left, top - 20, left + 20, top], fill=color)
            draw.text((left + 4, top - 18), label, fill=(255, 255, 255))
    
    output = BytesIO()
    img.save(output, format="PNG")
    result_bytes = output.getvalue()
    
    if output_path:
        img.save(output_path)
    
    return result_bytes


def build_vision_context(page, goal: str, ledger_text: str = "") -> dict:
    """Build complete vision context: screenshot + SoM + elements list."""
    screenshot_bytes = take_screenshot(page, timeout=60000)
    extraction = extract_elements_with_bbox(page)
    elements = extraction.get("elements", [])
    viewport_width = extraction.get("viewportWidth", 1366)
    viewport_height = extraction.get("viewportHeight", 768)
    
    annotated_screenshot = draw_som_annotations(screenshot_bytes, elements)
    
    elements_desc = []
    for el in elements:
        eid = el.get("id", 0)
        text = el.get("text", "")[:60]
        tag = el.get("tag", "")
        role = el.get("role", "")
        href = el.get("href", "")[:80]
        elements_desc.append(f"  [{eid}] {role} {tag}: '{text}' {href}")
    
    elements_text = "\n".join(elements_desc) if elements_desc else "  (no interactive elements detected)"
    
    prompt = f"""You are the VISION GROUNDING module of an autonomous web agent (SeeAct / RunAgent style).

User Goal: "{goal}"

{ledger_text}

CURRENT PAGE - Set-of-Marks Annotated:
The screenshot has numbered bounding boxes on interactive elements.

INTERACTIVE ELEMENTS:
{elements_text}

TASK: Analyze the screenshot and the element list. Choose the SINGLE best element ID to interact with to make progress towards the goal.

RESPOND WITH JSON ONLY:
{{
  "element_id": <number>,
  "action": "click" | "type" | "scroll" | "done",
  "text": "text to type (if type)",
  "reasoning": "brief explanation of why this element"
}}

CRITICAL RULES:
- Pick element_id from the list above ONLY (must be a valid ID shown)
- If goal is achieved (answer visible on page), use element_id: -1, action: "done", text: "exact answer from page"
- If no suitable element, use element_id: -1, action: "scroll"
- For typing: action="type" with text field
- Prefer click on buttons/links, type on inputs
- If multiple similar elements, pick the one most relevant to goal

DOMAIN-SPECIFIC GUIDANCE:
- YouTube: "play video" or "watch" → go to youtube.com, search channel/video, click video link
- MKBHD / Marques Brownlee: YouTube channel @mkbhd, latest videos on homepage or /videos tab
- Amazon: product search → type in #twotabsearchtextbox, press Enter, click result link
- Google Search: type in search box, press Enter
- If on wrong site for goal (e.g., Amazon when goal is YouTube), navigate to correct site first
- Don't type same text repeatedly - if input already has text, click search button or press Enter
- Look at URL and page title to understand where you are
"""
    
    return {
        "screenshot_bytes": screenshot_bytes,
        "annotated_screenshot_bytes": annotated_screenshot,
        "elements": elements,
        "viewport_width": viewport_width,
        "viewport_height": viewport_height,
        "prompt": prompt
    }


# ----- Action execution ----------------------------------------------------


def _click_via_selector(page, selector: str, text_hint: str = "") -> bool:
    """Simple, reliable click strategy - just use the selector with force click."""
    # Strategy 1: Try the provided selector directly
    try:
        locator = page.locator(selector)
        if locator.count() > 0:
            first = locator.first
            if first.is_visible():
                first.click(timeout=3000)
                return True
            else:
                # Try force click for hidden/overlapped elements
                first.click(force=True, timeout=3000)
                return True
    except Exception:
        pass
    
    # Strategy 2: If we have a text hint but selector failed, try JavaScript click
    if text_hint:
        try:
            result = page.evaluate(f"""() => {{
                // Find elements containing the text
                const elements = Array.from(document.querySelectorAll('a, button, span, div, input, button'));
                const target = elements.find(el => el.innerText && el.innerText.includes('{text_hint}'));
                if (target) {{
                    target.click();
                    return 'clicked';
                }}
                return 'not found';
            }}""")
            if result == 'clicked':
                return True
        except Exception:
            pass
    
    # Strategy 5: For YouTube/video links - extract href and navigate directly
    if text_hint and ("youtube.com" in page.url or "youtu.be" in page.url):
        try:
            # Try to find the link element and extract its href
            result = page.evaluate(f"""() => {{
                // Find link elements containing the text
                const elements = Array.from(document.querySelectorAll('a[href]'));
                const target = elements.find(el => el.innerText && el.innerText.includes('{text_hint}'));
                if (target && target.href) {{
                    return target.href;
                }}
                return null;
            }}""")
            if result and result.startswith('http'):
                # Navigate directly to the video URL
                log(f"[VERIFICATION] Navigating directly to video URL: {result}")
                page.goto(result, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                return True
        except Exception:
            pass
    
    return False
def execute_action(page, action: dict, log) -> tuple[bool, str]:
    """Run one action. Returns (success, result_note)."""
    kind = action.get("action", "")
    if kind == "navigate":
        url = action.get("url", "")
        if not url:
            return False, "navigate without url"
        log("-- ACTION LAYER: Navigating to " + url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            # Extra wait for dynamic sites (YouTube, SPA)
            if "youtube.com" in url or "youtu.be" in url:
                page.wait_for_timeout(5000)  # YouTube needs time for dynamic content
                # Wait for at least one video element to appear
                try:
                    page.wait_for_selector('ytd-rich-grid-renderer, ytd-video-renderer, #contents', timeout=8000)
                except Exception:
                    pass
            else:
                page.wait_for_timeout(3000)
            return True, "navigated to " + page.url
        except Exception as e:
            return False, "navigation failed: " + str(e)

    elif kind == "click":
        selector = action.get("selector", "")
        text_hint = action.get("text", "")
        log("-- ACTION LAYER: Clicking '" + selector + "'")
        ok = _click_via_selector(page, selector, text_hint)
        if ok:
            page.wait_for_timeout(2500)
            return True, "click ok"
        return False, "selector '" + selector + "' not found"

    elif kind == "type":
        sel = action.get("selector", "") or action.get("input_selector", "")
        text = action.get("text", "")
        press_k = action.get("press_key")
        log("-- ACTION LAYER: Typing '" + text + "' into '" + sel + "'")
        try:
            page.fill(sel, text, timeout=3000)
        except Exception:
            try:
                page.locator(sel).fill(text, timeout=3000)
            except Exception:
                page.keyboard.type(text, delay=50)
                log("-- ACTION LAYER: Typed via keyboard fallback")
        if press_k:
            try:
                page.keyboard.press(press_k)
            except Exception:
                pass
        page.wait_for_timeout(2000)
        return True, "typed '" + text + "'"

    elif kind == "scroll":
        pixels = int(action.get("scroll_pixels", 500))
        log("-- ACTION LAYER: Scrolling " + str(pixels) + "px")
        page.evaluate("window.scrollBy(0, " + str(pixels) + ")")
        page.wait_for_timeout(1000)
        return True, "scrolled " + str(pixels) + "px"

    elif kind == "press":
        key = action.get("press_key", "Enter")
        log("-- ACTION LAYER: Pressing '" + key + "'")
        page.keyboard.press(key)
        page.wait_for_timeout(2000)
        return True, "pressed " + key

    elif kind == "mouseclick":
        x = int(action.get("x", 0))
        y = int(action.get("y", 0))
        log("-- ACTION LAYER: Mouse-clicking at (" + str(x) + ", " + str(y) + ")")
        try:
            page.mouse.click(x, y)
            page.wait_for_timeout(2500)
            return True, "mouse click successful"
        except Exception as e:
            return False, "mouse click failed: " + str(e)

    elif kind == "vision_click":
        # Vision-grounded click using element_id and bounding box
        element_id = action.get("element_id", -1)
        elements = action.get("elements", [])
        viewport_width = action.get("viewport_width", 1366)
        viewport_height = action.get("viewport_height", 768)
        
        if element_id < 0 or element_id >= len(elements):
            return False, f"Invalid element_id: {element_id}"
        
        target = elements[element_id]
        bbox = target.get("bbox", [0, 0, 0, 0])
        x, y, w, h = bbox
        
        click_x = int(x * viewport_width)
        click_y = int(y * viewport_height)
        
        log(f"-- ACTION LAYER: Vision click element [{element_id}] at ({click_x}, {click_y}) - {target.get('role','')} '{target.get('text','')[:40]}'")
        
        try:
            page.mouse.click(click_x, click_y)
            page.wait_for_timeout(2500)
            return True, f"vision click ok on element [{element_id}]"
        except Exception as e:
            return False, f"vision click failed: {str(e)}"

    elif kind == "vision_type":
        # Vision-grounded type using element_id
        element_id = action.get("element_id", -1)
        text = action.get("text", "")
        press_k = action.get("press_key")
        elements = action.get("elements", [])
        viewport_width = action.get("viewport_width", 1366)
        viewport_height = action.get("viewport_height", 768)
        
        if element_id < 0 or element_id >= len(elements):
            return False, f"Invalid element_id: {element_id}"
        
        target = elements[element_id]
        selector = target.get("selector", "")
        
        log(f"-- ACTION LAYER: Vision type into element [{element_id}] ({selector})")
        
        try:
            page.fill(selector, text, timeout=3000)
        except Exception:
            try:
                page.locator(selector).fill(text, timeout=3000)
            except Exception:
                bbox = target.get("bbox", [0, 0, 0, 0])
                x, y, w, h = bbox
                click_x = int(x * viewport_width)
                click_y = int(y * viewport_height)
                page.mouse.click(click_x, click_y)
                page.wait_for_timeout(500)
                page.keyboard.type(text, delay=50)
                log("-- ACTION LAYER: Typed via keyboard fallback after vision click")
        
        if press_k:
            try:
                page.keyboard.press(press_k)
            except Exception:
                pass
        page.wait_for_timeout(2000)
        return True, f"vision typed '{text}' into element [{element_id}]"

    return False, "unknown action: " + kind


def is_captcha_page(ctx: dict) -> bool:
    url = ctx.get("url", "").lower()
    text = (ctx.get("text") or "").lower()
    return (
        "/sorry/" in url
        or "captcha" in url
        or "unusual traffic" in text
        or "automated requests" in text
        or "are you a robot" in text
        or "verify you are human" in text
        or "recaptcha" in text
    )