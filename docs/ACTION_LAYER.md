# Action Layer Documentation

## Overview

The `action_layer.py` module handles all browser interactions and page perception. It's the "Body" of the agent - executing actions against a real Chromium browser via Playwright.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Action Layer                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐    ┌───────────────────────────────┐  │
│  │   Perception       │    │      Action Execution           │  │
│  │  (extract_page_    │    │  (execute_action)               │  │
│  │   _context)        │    │  - navigate                     │  │
│  │                    │    │  - click                        │  │
│  │  - Title, URL      │    │  - type                         │  │
│  │  - Visible text    │    │  - scroll                       │  │
│  │  - Interactive     │    │  - press                        │  │
│  │    elements        │    │  - mouseclick                   │  │
│  └─────────────────────┘    └───────────────────────────────┘  │
│  │                        │                                    │
│  │  Shadow DOM Traversal  │    Click Strategies:              │
│  │  - Deep walk          │    1. Direct selector              │
│  │  - Shadow root walk   │    2. get_by_text                   │
│  │  - Visibility filter  │    3. Button/input selectors       │
│  │                        │    4. JavaScript click fallback   │
└─────────────────────────────────────────────────────────────────┘
```

## Perception: `extract_page_context(page)`

Extracts structured page information for the cognitive layer.

### Returns
```python
{
    "title": str,           # Page title
    "url": str,             # Current URL
    "text": str,            # Visible body text (truncated to 4000 chars)
    "interactive": str,     # JSON string of interactive elements
}
```

### Site-Specific Handling

#### YouTube
```python
if "youtube.com" in page.url:
    page.wait_for_timeout(2000)
    # Force a re-layout to ensure shadow roots are attached
    page.evaluate("""() => {
        document.body.style.display = 'none';
        document.body.offsetHeight; // force reflow
        document.body.style.display = '';
    }""")
```

#### Amazon
```python
elif "amazon." in page.url:
    page.wait_for_timeout(4000)
    # Wait for product grid to load
    try:
        page.wait_for_selector('[data-component-type="s-search-result"], .s-result-item, [data-asin], .sg-col-inner', timeout=8000)
    except Exception:
        pass
```

### Interactive Elements Extraction (`_INTERACTIVE_JS`)

The JavaScript runs in-browser to extract all interactive elements with valid CSS selectors.

#### Features:
1. **Deep Shadow DOM Traversal** - Recursively walks shadow roots
2. **Visibility Filtering** - Only visible elements (width/height > 0, visible)
3. **Selector Generation Priority**:
   1. `#id` (if unique)
   2. `tag[name="name"]` (if unique)
   3. `tag[href*="..."]` (href-based, if unique <=5)
   4. `tag.class1.class2` (up to 2 classes)
4. **Deduplication** - By selector
5. **Limit**: 80 elements max

#### Output Format
```json
[
  {
    "selector": "button.a-button-primary",
    "text": "Add to cart",
    "tag": "button",
    "href": "",
    "role": "[button]"
  }
]
```

### Supported Element Types
| Tag | Selector Types | Role Label |
|-----|---------------|------------|
| `a[href]` | id, name, href, class | `[link]` |
| `button` | id, name, class | `[button]` |
| `input` | id, name, class | `[type input]` |
| `select` | id, name, class | `[dropdown]` |
| `textarea` | id, name, class | `[text area]` |
| `[role="button"]` | id, class | `[button]` |
| `[tabindex]` | id, class | varies |

---

## Action Execution

### `execute_action(page, action, log)`

Dispatches to action-specific handlers.

#### Action Types

| Action | Parameters | Description |
|--------|-----------|-------------|
| `navigate` | `url` | Navigate to URL |
| `click` | `selector`, `text` | Click element |
| `type` | `selector`/`input_selector`, `text`, `press_key` | Type text |
| `scroll` | `scroll_pixels` | Scroll down |
| `press` | `press_key` | Press key (Enter, Escape, etc.) |
| `mouseclick` | `x`, `y` | Click at coordinates |
| `search_google` | `query` | Search Google for verification |

---

### Navigation (`navigate`)

```python
page.goto(url, wait_until="domcontentloaded", timeout=15000)
```

**Special Handling**:
- **YouTube**: 5s wait + wait for `ytd-rich-grid-renderer`
- **Other**: 3s wait

---

### Click (`click`)

Multi-strategy click implementation in `_click_via_selector()`:

```python
def _click_via_selector(page, selector: str, text_hint: str = "") -> bool:
    # Strategy 1: Direct selector
    try:
        locator = page.locator(selector)
        if locator.count() > 0:
            # Check if first element is visible
            if page.locator(selector).count() > 0:
                page.locator(selector).first.click(timeout=3000)
                return True
    except Exception:
        pass
    
    # Strategy 2: get_by_text
    if text_hint:
        try:
            page.get_by_text(text_hint, exact=False).first.click(timeout=3000)
            return True
        except Exception:
            pass

    # Strategy 3: Button/input selectors with text
    if text_hint:
        try:
            page.locator(f"button:has-text('{text_hint}'), input[type='button']:has-text('{text_hint}'), input[type='submit']:has-text('{text_hint}'), [role='button']:has-text('{text_hint}')").first.click(timeout=3000)
            return True
        except Exception:
            pass

    # Strategy 4: JavaScript click for non-standard elements
    if text_hint:
        try:
            result = page.evaluate(f"""() => {{
                // Find elements containing the text
                const elements = Array.from(document.querySelectorAll('button, span, div, a, input'));
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
    
    return False
```

### Special Handling: Amazon's "Add to Cart"

Amazon uses `<span class="a-button-primary">` with `aria-label="Add to cart"` instead of `<button>`. The JS click strategy handles this.

### Click Strategy for Amazon
```python
# Strategy 4: JavaScript click
result = page.evaluate("""() => {
    const elements = Array.from(document.querySelectorAll('button, span, div, a, input'));
    const target = elements.find(el => el.innerText && el.innerText.includes('{text_hint}'));
    if (target) {{
        target.click();
        return 'clicked';
    }}
    return 'not found';
}}""")
if result == 'clicked':
    return True
```

---

### Typing (`type`)

```python
page.fill(sel, text, timeout=3000)
# Fallback: page.locator(sel).fill(text, timeout=3000)
# Fallback: page.keyboard.type(text, delay=50)
if press_key:
    page.keyboard.press(press_k)
page.wait_for_timeout(2000)
```

---

### Scroll (`scroll`)

```python
page.evaluate(f"window.scrollBy(0, {pixels})")
page.wait_for_timeout(1000)
```

---

### Key Press (`press`)

```python
page.keyboard.press(key)  # Enter, Escape, etc.
page.wait_for_timeout(2000)
```

---

### Mouse Click (`mouseclick`)

```python
page.mouse.click(x, y)
page.wait_for_timeout(2500)
```

---

### Search Google (`search_google`)

```python
def search_and_verify(page, query, log):
    page.goto(f"https://www.google.com/search?q={query.replace(' ', '+')}")
    page.wait_for_timeout(3000)
    page.wait_for_selector('#search, #rso, .g, .tF2Cxc', timeout=8000)
    page.wait_for_timeout(2000)
    return extract_page_context(page).get("text", "")
```

---

## Amazon-Specific Handling

### Amazon "Add to Cart" Button Structure
```html
<span id="a-autoid-1" class="a-button a-button-primary a-button-icon puis-atcb-button">
    <span class="a-button-inner">
        <span class="a-button-text" aria-hidden="true">Add to cart</span>
    </span>
</span>
```

- Not a `<button>` but a `<span>` with `class="a-button-primary"`
- Has `id="a-autoid-1"` (changes per product)
- Has `aria-label="Add to cart"` on parent
- `page.locator("#a-autoid-1").first.click(force=True)` works

### Click Strategy for Amazon
```python
# Strategy 4: JavaScript click
result = page.evaluate("""() => {
    const elements = Array.from(document.querySelectorAll('button, span, div, a, input'));
    const target = elements.find(el => el.innerText && el.innerText.includes('{text_hint}'));
    if (target) {{
        target.click();
        return 'clicked';
    }}
    return 'not found';
}}""")
if result == 'clicked':
    return True
```

### Click Strategy for Amazon
```python
# Strategy 4: JavaScript click
result = page.evaluate("""() => {
    const elements = Array.from(document.querySelectorAll('button, span, div, a, input'));
    const target = elements.find(el => el.innerText && el.innerText.includes('{text_hint}'));
    if (target) {{
        target.click();
        return 'clicked';
    }}
    return 'not found';
}""")
if result == 'clicked':
    return True
```

---

## Amazon-Specific Perception

```python
elif "amazon." in page.url:
    page.wait_for_timeout(4000)
    # Wait for product grid to load
    try:
        page.wait_for_selector('[data-component-type="s-search-result"], .s-result-item, [data-asin], .sg-col-inner', timeout=8000)
    except Exception:
        pass
```

---

## Selectors Generated by `_INTERACTIVE_JS`

For Amazon search results, selectors look like:
```json
{
  "selector": "#a-autoid-1",
  "text": "Add to cart",
  "tag": "span",
  "href": "",
  "role": "[button]"
}
{
  "selector": "a[href*=\"/dp/\"]",
  "text": "Apple iPhone 17 Pro 512 GB",
  "tag": "a",
  "href": "https://www.amazon.in/dp/B0G45X8NCK",
  "role": "[link]"
}
```

---

## Best Practices for Actions

### Clicking
1. Always use `text_hint` with selector
2. Use `force=True` for hidden/overlay elements
3. Try JS click for non-standard elements (spans, divs)

### Typing
1. Prefer `page.fill()` for standard inputs
2. Fallback to `keyboard.type()` for complex inputs
3. Always `press_key="Enter"` for search

### Navigation
1. Use `wait_until="domcontentloaded"` for speed
2. Add explicit waits for dynamic content
3. Use `page.wait_for_selector()` for critical elements

### Error Handling
```python
try:
    page.fill(sel, text, timeout=3000)
except:
    try:
        page.locator(sel).fill(text, timeout=3000)
    except:
        page.keyboard.type(text, delay=50)  # Last resort
```

---

## Debugging Tips

1. **Element not visible**: Use `first.click(force=True, timeout=3000)`
2. **Element not found**: Check `_INTERACTIVE_JS` output for correct selector
3. **Amazon clicks fail**: Use JS click on parent element
4. **Element not visible**: `first.scroll_into_view_if_needed()` then click
5. **Stale element**: Re-fetch selector, increment `failed_selectors` counter

```python
# Debug: Print all interactive elements
interactive = page.evaluate(_INTERACTIVE_JS)
print(json.dumps(json.loads(interactive), indent=2))
```