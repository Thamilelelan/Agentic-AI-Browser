import json
import os
import re
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from google import genai
from google.genai import types

load_dotenv()
API_KEY = os.getenv("gemini_api_key")

if not API_KEY:
    raise ValueError(
        "Error: gemini_api_key not found in the .env file. "
        "Please create a .env file and add your key."
    )

MAX_STEPS = 8
MODEL_NAME = "gemini-3.5-flash-lite"
RATE_LIMIT_PER_MINUTE = 15
RATE_LIMIT_WINDOW_SECONDS = 60
FAILED_CLICK_THRESHOLD = 2  # give up on a selector after this many failures

STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


class RateLimiter:
    """Token-bucket-ish limiter: enforces N requests per rolling 60-second window."""

    def __init__(self, max_requests, window_seconds):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps = []

    def wait_if_needed(self):
        now = time.time()
        self.timestamps = [
            t for t in self.timestamps
            if now - t < self.window_seconds
        ]

        if len(self.timestamps) >= self.max_requests:
            sleep_for = self.window_seconds - (now - self.timestamps[0])
            if sleep_for > 0:
                print(
                    f"[RATE LIMIT] Hit {self.max_requests} req/{self.window_seconds}s "
                    f"cap. Sleeping {sleep_for:.1f}s..."
                )
                time.sleep(sleep_for)
                now = time.time()
                self.timestamps = [
                    t for t in self.timestamps
                    if now - t < self.window_seconds
                ]

        self.timestamps.append(time.time())


rate_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE, RATE_LIMIT_WINDOW_SECONDS)


def ask_brain(user_goal, page_context):
    print("\n--- COGNITIVE LAYER (Brain Thinking) ---")

    if page_context is None:
        prompt = f"""
        You are the Brain of an autonomous web agent.
        The user wants to achieve this goal: "{user_goal}"

        A page is NOT yet loaded. Determine the best URL to start this task.
        Examples:
        - Searching for a product on Amazon  -> https://www.amazon.in/s?k=product+name
        - General web search                -> https://duckduckgo.com/?q=query+here
        - Specific website                   -> that site's homepage or relevant subpage
        - Tools/widgets (coin flip, calc)    -> https://www.google.com/search?q=flip+a+coin
                                                (or DuckDuckGo if you want to avoid Google)

        IMPORTANT: PREFER DuckDuckGo (https://duckduckgo.com/) for general web searches.
        Google is heavily protected by anti-bot systems and frequently blocks automated
        browsers. Use Google only when you specifically need Google search results or
        widgets (like "flip a coin", calculator, etc.).

        Respond ONLY with a valid JSON object containing:
        - "action": "navigate"
        - "url": the URL to navigate to
        - "reasoning": a brief explanation of why you chose this URL
        """
    else:
        prompt = f"""
        You are the Brain of an autonomous web agent.
        The user's goal is: "{user_goal}"

        You are currently viewing this page:
        ---PAGE CONTEXT---
        Title: {page_context.get('title', 'Unknown')}
        URL: {page_context.get('url', '')}

        Visible text:
        {page_context.get('text', '')[:4000]}

        Interactive elements (clickable / fillable):
        {page_context.get('interactive', 'None found')}
        ---END PAGE CONTEXT---

        You CAN perform these actions:
        - "navigate"   : go to a NEW URL
        - "click"      : click a button or link using one of the selectors from the interactive list
        - "type"       : type text into a search/input field using its selector, optionally press Enter
        - "scroll"     : scroll the page down by a number of pixels
        - "press"      : press a keyboard key (e.g. Enter, Escape)
        - "mouseclick" : click at a specific (x, y) coordinate on the page (last-resort fallback)
        - "done"       : report the final answer

        CRITICAL RULES:
        - A PAGE IS ALREADY LOADED in the browser. You should almost always
          choose "click" or "type" against the current page, NOT "navigate"
          back to a search engine. Only use "navigate" if the current page
          is completely irrelevant to the goal (e.g. a CAPTCHA block, or a
          totally wrong site).
        - Selectors are PAGE-SPECIFIC. A selector that worked on the previous page
          (e.g. search results) will NOT work after navigating to a new page (e.g.
          the video watch page). You MUST re-read the interactive elements list of
          the CURRENT page before deciding the next action.
        - You MUST copy the "selector" value VERBATIM from the interactive elements list.
          DO NOT invent or guess selectors. If a clickable element isn't in the list,
          use "scroll" first to bring more elements into view, then re-evaluate.
        - If you see a search/input box, use "type" to enter the query and press
          Enter — DO NOT construct search URLs manually.
        - If you see the exact product/info you need, use "done".
        - If the current page is a CAPTCHA / "unusual traffic" / "are you a robot"
          / "verify you are human" page (URL contains "/sorry/" or "captcha" or
          page text mentions "unusual traffic" or "automated requests"), DO NOT
          try to solve it. Use "navigate" to switch to a different site that
          doesn't block bots:
            * General web search -> https://duckduckgo.com/
            * Product search     -> https://www.amazon.in/s?k=query
            * Wikipedia          -> https://en.wikipedia.org/wiki/Topic
            * News               -> https://www.bbc.com/  or  https://www.reddit.com/
          NEVER navigate back to Google.com after seeing a CAPTCHA — that will
          keep triggering the block.
        - NEVER click recaptcha or challenge elements.
        - For YouTube: video items are typically inside links with selectors like
          `a#video-title-link`, `a[href*="watch"]`, or `ytd-rich-item-renderer a`.
          Copy whichever selector matches from the interactive list.
        - Only use "mouseclick" when you have tried "click" with a selector and
          it failed. The viewport is 1366x768, so coordinates must be inside that range.

        Respond ONLY with a valid JSON object containing:
        - "action": one of "navigate", "click", "type", "scroll", "press", "mouseclick", "done"
        - "url": the URL (if action is "navigate")
        - "selector": the EXACT selector copied from the interactive list (if action is "click" or "type")
        - "text": the text to type (if action is "type")
        - "press_key": a key like "Enter" (if action is "type" or "press")
        - "scroll_pixels": number of pixels to scroll (if action is "scroll")
        - "x": x coordinate (if action is "mouseclick")
        - "y": y coordinate (if action is "mouseclick")
        - "answer": final answer found on the page (if action is "done")
        - "reasoning": brief explanation of your decision
        """

    try:
        rate_limiter.wait_if_needed()

        client = genai.Client(api_key=API_KEY)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )

        decision = json.loads(response.text)
        print(f"Brain Decision: {json.dumps(decision, indent=2)}\n")
        return decision

    except Exception as e:
        print(f"Error communicating with LLM: {e}")
        return {"action": "done", "answer": "Error: LLM call failed", "reasoning": str(e)}


def extract_page_context(page):
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
        interactive = page.evaluate("""() => {
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
            const s = `${tag}[name="${escapeAttr(el.name)}"]`;
            if (document.querySelectorAll(s).length === 1) return s;
        }
        if (el.getAttribute('href')) {
            const href = el.getAttribute('href');
            if (href.length < 200) {
                const s = `${tag}[href*="${escapeAttr(href.slice(0, 40))}"]`;
                try {
                    if (document.querySelectorAll(s).length <= 5) return s;
                } catch (e) {}
            }
        }
        if (typeof el.className === 'string' && el.className.trim()) {
            const cls = el.className.trim().split(/\\s+/).slice(0, 2).join(' ');
            const s = `${tag}${escapeClass(cls)}`;
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
        const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 80);
        const selector = makeSelector(el);

        if (!selector) continue;
        if (seen.has(selector)) continue;
        seen.add(selector);

        let roleLabel = '';
        if (tag === 'input') {
            roleLabel = `[${el.type || 'text'} input]`;
        } else if (tag === 'button' || el.getAttribute('role') === 'button') {
            roleLabel = '[button]';
        } else if (tag === 'select') {
            roleLabel = '[dropdown]';
        } else if (tag === 'textarea') {
            roleLabel = '[text area]';
        } else if (tag === 'a') {
            roleLabel = '[link]';
        }

        results.push({
            selector: selector,
            text: text,
            tag: tag,
            href: el.getAttribute('href') || '',
            role: roleLabel
        });

        if (results.length >= 80) break;
    }
    return results;
}
        """)
        ctx["interactive"] = json.dumps(interactive, indent=2)
    except Exception:
        ctx["interactive"] = "[]"

    return ctx


def element_by_heuristic(page, selector, text_hint=""):
    try:
        count = page.locator(selector).count()
        if count > 0:
            page.locator(selector).first.click(timeout=3000)
            return True
    except Exception:
        pass

    if text_hint:
        try:
            page.get_by_text(text_hint, exact=False).first.click(timeout=3000)
            return True
        except Exception:
            pass

    return False


def type_into(page, text_selector, text_to_type, press_key):
    try:
        page.fill(text_selector, text_to_type, timeout=3000)
    except Exception:
        try:
            page.locator(text_selector).fill(text_to_type, timeout=3000)
        except Exception:
            print(f"-- ACTION LAYER: Could not fill '{text_selector}' via selector, falling back...")
            found = False
            for attr in ["input[placeholder]", "textarea[placeholder]"]:
                els = page.query_selector_all(attr)
                for elx in els:
                    placeholder = (elx.get_attribute("placeholder") or "").lower()
                    if text_to_type.lower() in placeholder:
                        elx.fill(text_to_type, timeout=2000)
                        found = True
                        break
                if found:
                    break
            if not found:
                page.keyboard.type(text_to_type, delay=50)
                print("-- ACTION LAYER: Typed via keyboard fallback")

    if press_key:
        try:
            page.keyboard.press(press_key)
            print(f"-- ACTION LAYER: Pressed '{press_key}'")
        except Exception as e:
            print(f"-- ACTION LAYER: Failed to press key: {e}")

    page.wait_for_timeout(2000)


def create_stealth_page(browser):
    context = browser.new_context(
        user_agent=STEALTH_USER_AGENT,
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )
    page = context.new_page()

    page.add_init_script("""
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
    """)
    return page


def run_one_session(page, user_goal, start_context=None):
    """Run a single agentic session with at most MAX_STEPS steps.

    Reuses the given Playwright `page` — does NOT launch a new browser.
    The page state (URL, DOM) at entry is preserved and the agent picks
    up from there.

    `start_context` is the page context from the previous session (if any).
    When supplied, the brain is told a page is already loaded and should NOT
    re-navigate to a search engine — it should pick a click/type action
    against the current page.

    Returns a tuple (status, final_answer, last_context) where status is one of:
      - "done"      : brain explicitly produced a final answer
      - "exhausted" : MAX_STEPS reached without the brain saying done
      - "blocked"   : captcha/block detected too many times
    `last_context` is the final page context extracted at the end of the
    session — passed forward to the next session so the brain resumes from
    the current page instead of re-navigating.
    """
    context = start_context
    captcha_count = 0
    failed_selectors = {}
    final_answer = None
    status = "exhausted"
    # Part A: dead-end tracking — stop looping when the goal is unreachable
    not_found_signatures: list[str] = []
    same_query_repeats = 0
    last_query_signature = ""

    for step in range(1, MAX_STEPS + 1):
        print(f"\n{'='*50}")
        print(f"STEP {step}/{MAX_STEPS}")
        print(f"{'='*50}")

        decision = ask_brain(user_goal, context)

        action = decision.get("action", "navigate")

        if action == "done":
            final_answer = decision.get(
                "answer",
                decision.get("reasoning", "Goal achieved.")
            )
            print(f"\n*** AGENT FINAL ANSWER: {final_answer} ***")
            status = "done"
            break

        if action == "navigate":
            url = decision.get("url")
            if url:
                print(f"-- ACTION LAYER: Navigating to {url}")
                failed_selectors.clear()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"-- ACTION LAYER: Navigation failed: {e}")
                # Part A: detect "no results" pages and break the loop
                try:
                    new_text = page.inner_text("body").lower()
                    no_results_markers = [
                        "no results found", "did not match any", "0 results",
                        "no videos found", "no posts found", "no matches",
                        "make sure all words are spelled correctly",
                    ]
                    if any(m in new_text for m in no_results_markers):
                        not_found_signatures.append(url[:80])
                        print(f"[DEAD-END] Page reports no results for: {url}")
                except Exception:
                    pass

        elif action == "click":
            selector = decision.get("selector", "")
            text_hint = decision.get("text", "")
            print(f"-- ACTION LAYER: Clicking '{selector}'")

            if selector and failed_selectors.get(selector, 0) >= FAILED_CLICK_THRESHOLD:
                print(
                    f"  [SKIP] Selector '{selector}' has failed "
                    f"{failed_selectors[selector]} times already. "
                    "Brain should choose a different selector next step."
                )
                continue

            success = element_by_heuristic(page, selector, text_hint)
            if success:
                print("  Click successful.")
                failed_selectors[selector] = 0
                page.wait_for_timeout(2500)
            else:
                failed_selectors[selector] = failed_selectors.get(selector, 0) + 1
                print(
                    f"  Click failed — selector not found on page. "
                    f"(failure #{failed_selectors[selector]} for this selector)"
                )

        elif action == "type":
            input_selector = decision.get("selector", "")
            text_to_type = decision.get("text", "")
            press_k = decision.get("press_key", None)
            print(f"-- ACTION LAYER: Typing '{text_to_type}' into '{input_selector}'")
            type_into(page, input_selector, text_to_type, press_k)

        elif action == "scroll":
            pixels = decision.get("scroll_pixels", 500)
            print(f"-- ACTION LAYER: Scrolling {pixels}px")
            page.evaluate(f"window.scrollBy(0, {pixels})")
            page.wait_for_timeout(1000)

        elif action == "press":
            key = decision.get("press_key", "Enter")
            print(f"-- ACTION LAYER: Pressing '{key}'")
            page.keyboard.press(key)
            page.wait_for_timeout(2000)

        elif action == "mouseclick":
            x = decision.get("x", 0)
            y = decision.get("y", 0)
            print(f"-- ACTION LAYER: Mouse-clicking at ({x}, {y})")
            try:
                page.mouse.click(x, y)
                page.wait_for_timeout(2500)
                print("  Mouse click successful.")
            except Exception as e:
                print(f"  Mouse click failed: {e}")

        context = extract_page_context(page)
        print(f"-- PERCEPTION LAYER: Page title -> {context['title']}")
        print(f"-- PERCEPTION LAYER: URL -> {context['url']}")
        print(f"-- PERCEPTION LAYER: Extracted {len(context.get('text', ''))} chars")

        current_url = context.get("url", "").lower()
        page_text = context.get("text", "").lower()
        is_captcha = (
            "/sorry/" in current_url
            or "captcha" in current_url
            or "unusual traffic" in page_text
            or "automated requests" in page_text
            or "are you a robot" in page_text
            or "verify you are human" in page_text
            or "recaptcha" in page_text
        )

        if is_captcha:
            captcha_count += 1
            print(f"[BLOCK DETECTED] Site returned a CAPTCHA/anti-bot page. "
                  f"Auto-pivoting away. (count={captcha_count})")
            if captcha_count >= 2:
                print("[BLOCK DETECTED] Multiple blocks — aborting retries.")
                status = "blocked"
                break
            fallback_urls = [
                "https://duckduckgo.com/",
                "https://www.bing.com/",
                "https://en.wikipedia.org/",
            ]
            fb = fallback_urls[(captcha_count - 1) % len(fallback_urls)]
            print(f"[BLOCK DETECTED] Auto-navigating to {fb}")
            try:
                page.goto(fb, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                context = extract_page_context(page)
            except Exception as e:
                print(f"[BLOCK DETECTED] Fallback navigation failed: {e}")

        # Part A: if we've hit 2+ no-results pages, the goal is unreachable.
        # Force a final answer instead of looping forever.
        if len(not_found_signatures) >= 2:
            print("[DEAD-END] Multiple no-results pages — goal is unreachable.")
            final_answer = (
                f"Could not achieve the goal: '{user_goal}'. "
                f"Searched {len(not_found_signatures)} queries that all "
                f"returned no results. The requested item likely does not exist."
            )
            status = "done"
            break

    if status == "exhausted":
        print("\n*** AGENT: Reached max steps. Asking brain for final analysis...")
        context = context or extract_page_context(page)
        final_decision = ask_brain(user_goal, context)
        final_answer = final_decision.get(
            "answer",
            "Unable to determine final answer within the step budget."
        )
        print(f"*** AGENT FINAL ANSWER: {final_answer}")

    return status, final_answer, context


def run_agentic_browser(user_goal):
    """Top-level entry: owns the Playwright context, runs sessions in a loop.

    Launches the browser ONCE at the start. Each session reuses the same
    browser window and page — the agent picks up from wherever the previous
    session left off. Pressing 'c' at the prompt just gives the agent more
    steps without opening a new browser window.
    """
    print("-" * 50)
    print(f"AGENT GOAL: {user_goal}")
    print("-" * 50)

    with sync_playwright() as p:
        print("Launching Chromium browser with stealth profile...")
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        page = create_stealth_page(browser)

        last_context = None
        is_continuation = False

        try:
            while True:
                start_ctx = last_context if is_continuation else None
                status, final_answer, last_context = run_one_session(
                    page, user_goal, start_context=start_ctx
                )

                print("\n" + "-" * 50)
                print(f"*** SESSION ENDED (status={status})")
                print(f"*** FINAL ANSWER: {final_answer}")
                print("-" * 50)
                choice = input(
                    "Press ENTER to close the browser, or type 'c' (continue) "
                    "to give the agent more steps: "
                ).strip().lower()

                if choice != "c":
                    break
                print(
                    "[USER] Continuing the agent run in the same browser window "
                    "with a fresh step budget...\n"
                )
                is_continuation = True
                time.sleep(1)
        finally:
            print("-" * 40)
            try:
                input("REVIEW MODE: Press ENTER in this terminal to close the browser...")
                print("-" * 40)
                browser.close()
                print("Browser closed.")
            except (KeyboardInterrupt, EOFError):
                print("\nInterrupted — closing browser.")
                try:
                    browser.close()
                except Exception:
                    pass
            except Exception as e:
                print(f"Browser close skipped: {e}")


if __name__ == "__main__":
    user_prompt = input("What do you want the browser agent to do? ").strip()
    if user_prompt:
        run_agentic_browser(user_prompt)
    else:
        print("No prompt entered. Exiting.")