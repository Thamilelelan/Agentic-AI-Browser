#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognitive_layer import _normalize_orchestrator, _normalize_planner, _normalize_worker


def test_orchestrator_contract_normalization():
    out = _normalize_orchestrator({"route": "search", "confidence": 9, "reasoning": "x"})
    assert out["route"] == "browser"
    assert out["confidence"] == 1.0
    assert out["reasoning"] == "x"


def test_planner_contract_fallbacks():
    out = _normalize_planner({"verdict": "unknown", "next_steps": "bad"})
    assert out["verdict"] == "continue"
    assert isinstance(out["next_steps"], list)
    assert out["next_steps"]


def test_worker_rejects_done_and_missing_parameters():
    out = _normalize_worker({"action": "done", "reasoning": "finish"})
    assert out["action"] == "scroll"
    assert out["scroll_pixels"] >= 200


def test_worker_accepts_parameters_contract():
    out = _normalize_worker({
        "action": "click",
        "parameters": {"selector": "#cta", "text": "Buy now"},
        "reasoning": "click target",
    })
    assert out["action"] == "click"
    assert out["selector"] == "#cta"
    assert out["parameters"]["selector"] == "#cta"
