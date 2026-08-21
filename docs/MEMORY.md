# Memory (Ledger) Documentation

## Overview

The `memory.py` module implements the **Structured Ledger** - the agent's memory system based on the RunAgent SuperBrowser paper (§5). It provides bounded working memory with structured storage for facts, dead-ends, checkpoints, and recent actions.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Ledger                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐            │
│  │   Recent    │  │    Facts     │  │   Dead Ends  │            │
│  │  (deque 3)  │  │  (dict)      │  │   (list)     │            │
│  └─────────────┘  └─────────────┘  └──────────────┘            │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐            │
│  │ Checkpoints │  │  Subgoal    │  │   Plan       │            │
│  │   (list)    │  │  (string)   │  │   (list)     │            │
│  └─────────────┘  └─────────────┘  └──────────────┘            │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Episodic Notes                          │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Data Structures

### StepOutcome
```python
@dataclass
class StepOutcome:
    action: str           # Action taken (navigate, click, type, etc.)
    target: str           # Target (URL, selector, text)
    success: bool         # Whether action succeeded
    url: str              # Page URL at time of action
    note: str = ""        # Additional notes
```

### DeadEnd
```python
@dataclass
class DeadEnd:
    description: str      # Human-readable description
    url: str              # URL where dead end occurred
    cause: str            # network | bot_block | stale_selector | not_found | generic
    step: int             # Step number when dead end occurred
```

---

## Ledger Class

### Initialization
```python
ledger = Ledger(goal="find price of iPhone 17 Pro on Amazon", recent_capacity=3)
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `goal` | `str` | Immutable user goal |
| `plan` | `list[str]` | High-level plan steps |
| `subgoal` | `str` | Current subgoal |
| `recent` | `deque[StepOutcome]` | Bounded deque (maxlen=3) |
| `facts` | `dict[str, str]` | Key-value fact store |
| `dead_ends` | `list[DeadEnd]` | Failed attempts log |
| `checkpoints` | `list[str]` | Progress milestones |
| `episodic` | `list[str]` | Free-form notes |

---

## Writers (Mutation Methods)

### `record_action(outcome: StepOutcome)`
Appends to recent deque (auto-evicts oldest when > 3).

### `add_fact(key: str, value: str)`
Stores a fact in the facts dictionary.

### `mark_dead_end(description: str, url: str, cause: str, step: int)`
Records a dead end. **Deduplicates**: won't add duplicate (url, cause) pairs consecutively.

```python
ledger.mark_dead_end(
    "search query 'iphone 17 pro' returned no results",
    "https://www.amazon.in/s?k=iphone+17+pro",
    cause="not_found",
    step=1
)
```

### `checkpoint(label: str)`
Records a progress milestone.

### `set_subgoal(subgoal: str)`
Sets current subgoal.

### `set_plan(plan: list[str])`
Sets the high-level plan.

### `note(text: str)`
Adds free-form episodic note.

---

## Queries (Read Methods)

### `has_failed_search(query: str) -> bool`
Checks if exact search query already returned nothing useful.

```python
if ledger.has_failed_search("iphone 17 pro amazon"):
    # Don't retry same query
```

### `render_for_worker() -> str`
Sliced view for operational layer (Worker). Shows:
- Goal
- Subgoal
- Last 3 actions (OK/FAIL)
- Facts (last 5)
- Dead ends (last 5)

**Example Output**:
```
GOAL: find price of iPhone 17 Pro on Amazon
SUBGOAL: navigate to product page and click add to cart
RECENT ACTIONS (last 3):
  - navigate 'https://www.amazon.in/s?k=iphone+17+pro' -> OK ()
  - click 'button:has-text("Add to cart")' -> FAIL (selector 'button:has-text("Add to cart")' not found)
  - click 'button:has-text("Add to cart")' -> FAIL (selector 'button:has-text("Add to cart")' not found)
FACTS:
  - price: ₹1,50,900
DEAD ENDS (do NOT retry these):
  - [stale_selector] click selector 'button:has-text("Add to cart")' kept failing @ https://www.amazon.in/s?k=iphone+17+pro
  - [stale_selector] click selector 'button:has-text("Add to cart")' kept failing @ https://www.amazon.in/s?k=iphone+17+pro
```

### `render_for_planner() -> str`
Full Ledger view for strategic layer. Includes:
- Goal
- Plan
- Subgoal
- Recent actions (all)
- All facts
- All dead ends
- Checkpoints

---

## Integration with Cognitive Roles

### Worker View (`render_for_worker()`)
Minimal context for operational decisions:
- Goal + Subgoal
- Last 3 actions (success/fail)
- Key facts
- Dead ends scoped to current URL

### Planner View (`render_for_planner()`)
Full Ledger view for strategic layer:
- Full plan
- All recent actions with step numbers
- All facts
- All dead ends
- Checkpoints

---

## Dead End Classification

| Cause | Description | Example |
|-------|-------------|---------|
| `network` | Network error | DNS timeout, connection refused |
| `bot_block` | CAPTCHA/bot detection | Cloudflare, /sorry/ page |
| `stale_selector` | Selector no longer works | Amazon changed button class |
| `not_found` | Search returned no results | "0 results found" |
| `postcondition_miss` | Expected outcome missing | Clicked but no cart update |
| `policy_block` | Site policy blocks action | Login required, geo-block |
| `rate_limit` | Rate limited by site | 429 Too Many Requests |
| `generic` | Unclassified | Unknown failure |

### Deduplication Logic
```python
def mark_dead_end(self, description, url, cause, step):
    if self.dead_ends and self.dead_ends[-1].url == url and self.dead_ends[-1].cause == cause:
        return  # Skip duplicate
    self.dead_ends.append(DeadEnd(description, url, cause, step))
```

---

## Integration with Cognitive Roles

### In Agent Engine
```python
ledger = Ledger(goal=goal)
ledger.record_action(StepOutcome(
    action="click",
    target="button:has-text('Add to cart')",
    success=False,
    url="https://amazon.in/...",
    note="selector not found"
))

ledger.mark_dead_end(
    "click selector 'button:has-text(\"Add to cart\")' kept failing",
    "https://amazon.in/...",
    cause="stale_selector",
    step=3
)

# Check before retrying
if ledger.has_failed_search("iphone 17 pro amazon"):
    # Don't retry same search
    pass
```

### In Planner Prompt
```python
prompt = PLANNER_PROMPT.format(
    ledger=ledger.render_for_planner(),
    ...
)
```

### In Worker Prompt
```python
prompt = WORKER_PROMPT_NEXT.format(
    ledger=ledger.render_for_worker(),
    ...
)
```

---

## Serialization

Ledger is JSON-serializable via `dataclasses.asdict()`:

```python
import dataclasses
import json

json.dumps(dataclasses.asdict(ledger))
```

---

## Design Principles

1. **Bounded Growth**: Recent actions capped at 3, preventing context explosion
2. **Failure as Learning**: Dead ends are first-class memories, not errors
3. **Strategic vs Operational**: Planner sees full context, Worker sees minimal
4. **Persistence**: Facts/Dead-ends survive across steps, recent actions rotate
4. **Deduplication**: Prevents infinite retry loops on same failure