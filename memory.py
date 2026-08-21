"""Structured Ledger + dead-end memory (per RunAgent SuperBrowser §5).

The Ledger is a per-task data structure that holds the goal, plan, recent
actions, facts, dead-ends, and checkpoints. It is the only state shared
between the three cognitive roles (Orchestrator / Planner / Worker).

Key design choice (per paper prediction P2): failures are remembered as
negative landmarks. This is what stops the brain from looping forever on
impossible goals like 'find a PewDiePie video about Gantz' when no such
video exists — the dead-end record surfaces to the brain on the next step
and it can call 'done' with a "not found" answer.
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StepOutcome:
    action: str
    target: str
    success: bool
    url: str
    note: str = ""


@dataclass
class DeadEnd:
    description: str
    url: str
    cause: str  # network | bot_block | stale_selector | not_found | generic
    step: int


class Ledger:
    """Per-task structured memory (paper §5.2).

    Bounded-recent (last 3 actions) + facts dict + dead-end list + checkpoints.
    """

    def __init__(self, goal: str, recent_capacity: int = 3):
        self.goal = goal
        self.plan: list[str] = []
        self.subgoal: Optional[str] = None
        self.recent: deque[StepOutcome] = deque(maxlen=recent_capacity)
        self.facts: dict[str, str] = {}
        self.dead_ends: list[DeadEnd] = []
        self.checkpoints: list[str] = []
        self.episodic: list[str] = []

    # ----- writers -----

    def record_action(self, outcome: StepOutcome):
        self.recent.append(outcome)

    def add_fact(self, key: str, value: str):
        self.facts[key] = value

    def mark_dead_end(self, description: str, url: str, cause: str, step: int):
        de = DeadEnd(description, url, cause, step)
        # Dedupe: don't add the same (url, cause) twice in a row.
        if self.dead_ends and self.dead_ends[-1].url == url and self.dead_ends[-1].cause == cause:
            return
        self.dead_ends.append(de)

    def checkpoint(self, label: str):
        self.checkpoints.append(label)

    def set_subgoal(self, subgoal: str):
        self.subgoal = subgoal

    def set_plan(self, plan: list[str]):
        self.plan = plan

    def note(self, text: str):
        self.episodic.append(text)

    # ----- queries -----

    def has_failed_search(self, query: str) -> bool:
        """True if this exact search query has already returned nothing useful."""
        query_lower = query.lower()
        for de in self.dead_ends:
            if de.cause == "not_found" and query_lower in de.description.lower():
                return True
        return False

    def render_for_worker(self) -> str:
        """Sliced view: only what the operational layer needs (paper §5.5)."""
        recent = "\n".join(
            f"  - {s.action} {s.target!r} -> {'OK' if s.success else 'FAIL'} ({s.note})"
            for s in self.recent
        ) or "  (none)"
        dead = "\n".join(
            f"  - [{de.cause}] {de.description} @ {de.url}"
            for de in self.dead_ends[-5:]
        ) or "  (none)"
        facts = "\n".join(f"  - {k}: {v}" for k, v in list(self.facts.items())[-5:]) or "  (none)"
        return (
            f"GOAL: {self.goal}\n"
            f"SUBGOAL: {self.subgoal or '(unset)'}\n"
            f"RECENT ACTIONS (last 3):\n{recent}\n"
            f"FACTS:\n{facts}\n"
            f"DEAD ENDS (do NOT retry these):\n{dead}\n"
        )

    def render_for_planner(self) -> str:
        """Full Ledger view for the strategic layer."""
        recent = "\n".join(
            f"  step {i}: {s.action} {s.target!r} -> {'OK' if s.success else 'FAIL'}"
            for i, s in enumerate(self.recent)
        ) or "  (none)"
        dead = "\n".join(
            f"  - [{de.cause}] {de.description} @ {de.url}"
            for de in self.dead_ends
        ) or "  (none)"
        facts = "\n".join(f"  - {k}: {v}" for k, v in self.facts.items()) or "  (none)"
        plan = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(self.plan)) or "  (unset)"
        return (
            f"GOAL: {self.goal}\n"
            f"PLAN:\n{plan}\n"
            f"SUBGOAL: {self.subgoal or '(unset)'}\n"
            f"RECENT:\n{recent}\n"
            f"FACTS:\n{facts}\n"
            f"DEAD ENDS:\n{dead}\n"
            f"CHECKPOINTS: {', '.join(self.checkpoints) or '(none)'}\n"
        )
