#!/usr/bin/env python3
"""
Unit tests for the RunAgent SuperBrowser project.
Tests critical functionality without requiring browser connections.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_layer import _click_via_selector, extract_page_context, execute_action
from cognitive_layer import run_orchestrator, run_planner, run_worker_first_step, run_worker_next_step
from memory import Ledger, StepOutcome, DeadEnd
from llm_providers import LLMConfig, create_llm_provider, get_rate_limiter, RateLimiter
from agent_engine import EngineConfig, run_session
from browser_config import resolve_browser


class TestLLMConfig:
    def test_llm_config_creation(self):
        config = LLMConfig(model="test-model", max_tokens=100, temperature=0.5)
        assert config.model == "test-model"
        assert config.max_tokens == 100
        assert config.temperature == 0.5
        assert config.top_p == 0.95
        assert config.reasoning is False
        assert config.medium_effort is False

    def test_llm_config_defaults(self):
        config = LLMConfig(model="test-model")
        assert config.max_tokens == 16000
        assert config.temperature == 1.0
        assert config.top_p == 0.95
        assert config.reasoning is False
        assert config.medium_effort is False


class TestLLMProviders:
    def test_gemini_provider_creation(self):
        # This would require actual API key, so we test the structure
        from llm_providers import GeminiProvider
        assert hasattr(GeminiProvider, 'generate_json')
    
    def test_nvidia_provider_creation(self):
        from llm_providers import NvidiaProvider
        assert hasattr(NvidiaProvider, 'generate_json')
        assert hasattr(NvidiaProvider, 'is_available')
        assert hasattr(NvidiaProvider, '_build_extra_body')

    def test_create_llm_provider_factory(self):
        import os
        os.environ['api_provider'] = 'gemini'
        os.environ['gemini_api_key'] = 'test-key'
        provider = create_llm_provider()
        assert provider is not None
        
        os.environ['api_provider'] = 'nvidia'
        os.environ['nvidia_api_key'] = 'test-key'
        provider = create_llm_provider()
        assert provider is not None


class TestRateLimiter:
    def test_rate_limiter_basic(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for i in range(5):
            limiter.wait_if_needed()
        assert len(limiter.timestamps) == 5
    
    def test_rate_limiter_wait(self):
        import time
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        start = time.time()
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        limiter.wait_if_needed()  # This should wait
        elapsed = time.time() - start
        assert elapsed >= 1.0  # Should have waited at least 1 second


class TestLedger:
    def test_ledger_creation(self):
        ledger = Ledger(goal="test goal")
        assert ledger.goal == "test goal"
        assert len(ledger.recent) == 0
        assert len(ledger.facts) == 0
        assert len(ledger.dead_ends) == 0
    
    def test_record_action(self):
        ledger = Ledger(goal="test")
        from memory import StepOutcome
        outcome = StepOutcome(action="navigate", target="https://example.com", success=True, url="https://example.com", note="test")
        ledger.record_action(outcome)
        assert len(ledger.recent) == 1
        assert ledger.recent[0].action == "navigate"
    
    def test_dead_end_tracking(self):
        ledger = Ledger(goal="test")
        ledger.mark_dead_end("test failure", "https://example.com", "not_found", 1)
        assert len(ledger.dead_ends) == 1
        assert ledger.dead_ends[0].cause == "not_found"
        
        # Test deduplication
        ledger.mark_dead_end("test failure again", "https://example.com", "not_found", 2)
        assert len(ledger.dead_ends) == 1  # Should not duplicate
    
    def test_facts(self):
        ledger = Ledger(goal="test")
        ledger.add_fact("price", "$100")
        assert ledger.facts["price"] == "$100"
    
    def test_has_failed_search(self):
        ledger = Ledger(goal="test")
        ledger.mark_dead_end("search failed for test query", "https://example.com", "not_found", 1)
        assert ledger.has_failed_search("test query") is True
        assert ledger.has_failed_search("other query") is False

    def test_render_for_worker(self):
        ledger = Ledger(goal="test goal")
        from memory import StepOutcome
        ledger.record_action(StepOutcome(action="click", target="button", success=True, url="https://example.com", note="clicked"))
        ledger.record_action(StepOutcome(action="type", target="input", success=False, url="https://example.com", note="failed"))
        ledger.add_fact("price", "$100")
        ledger.mark_dead_end("failed", "https://example.com", "not_found", 1)
        output = ledger.render_for_worker()
        assert "GOAL: test" in output
        assert "FAIL" in output
        assert "$100" in output


class TestActionLayer:
    def test_extract_page_context(self):
        # This would require a mock page object
        pass
    
    def test_click_via_selector_logic(self):
        # Test the logic without browser
        pass


class TestCognitiveLayer:
    def test_orchestrator_prompt(self):
        from cognitive_layer import ORCHESTRATOR_PROMPT
        assert "ORCHESTRATOR" in ORCHESTRATOR_PROMPT
        assert "search" in ORCHESTRATOR_PROMPT
        assert "browser" in ORCHESTRATOR_PROMPT
    
    def test_planner_prompt(self):
        from cognitive_layer import PLANNER_PROMPT
        assert "PLANNER" in PLANNER_PROMPT
        assert "verdict" in PLANNER_PROMPT
        assert "done" in PLANNER_PROMPT
        assert "continue" in PLANNER_PROMPT
    
    def test_worker_prompts(self):
        from cognitive_layer import WORKER_PROMPT_FIRST, WORKER_PROMPT_NEXT
        import inspect
        from cognitive_layer import run_worker_first_step
        assert "navigate" in WORKER_PROMPT_FIRST
        assert "click" in WORKER_PROMPT_NEXT
        # search_google is in the run_worker_first_step function's prompt
        source = inspect.getsource(run_worker_first_step)
        assert "search_google" in source


class TestAgentEngine:
    def test_engine_config(self):
        config = EngineConfig(model="test-model", max_steps=5, headless=True, provider_type="nvidia")
        assert config.max_steps == 5
        assert config.headless is True
        assert config.provider_type == "nvidia"
        assert config.model == "test-model"
    
    def test_engine_config_defaults(self):
        config = EngineConfig()
        assert config.max_steps == 8
        assert config.provider_type == "gemini"
        assert config.model == "gemini-3.5-flash-lite"


class TestBrowserConfig:
    def test_resolve_browser_chromium(self):
        from browser_config import resolve_browser
        spec = resolve_browser("chromium")
        assert spec.browser == "chromium"
        assert spec.executable_path is None
        assert spec.channel is None
    
    def test_resolve_browser_helium(self):
        from browser_config import resolve_browser
        spec = resolve_browser("helium")
        assert spec.browser == "chromium"
        assert spec.executable_path is not None
    
    def test_resolve_browser_cdp(self):
        from browser_config import resolve_browser
        spec = resolve_browser("cdp")
        assert spec.browser == "cdp"
        assert spec.cdp_url is not None


class TestMemory:
    def test_step_outcome(self):
        from memory import StepOutcome
        outcome = StepOutcome(action="click", target="button", success=True, url="https://example.com", note="test")
        assert outcome.action == "click"
        assert outcome.target == "button"
        assert outcome.success is True
    
    def test_dead_end(self):
        from memory import DeadEnd
        de = DeadEnd("test", "https://example.com", "not_found", 1)
        assert de.description == "test"
        assert de.url == "https://example.com"
        assert de.cause == "not_found"
        assert de.step == 1


class TestLLMConfig:
    def test_defaults(self):
        config = LLMConfig(model="test-model")
        assert config.model == "test-model"
        assert config.max_tokens == 16000
        assert config.temperature == 1.0
        assert config.top_p == 0.95
        assert config.reasoning is False
        assert config.medium_effort is False


class TestAgentEngine:
    def test_engine_config_creation(self):
        config = EngineConfig(
            model="test-model",
            max_steps=5,
            headless=False,
            provider_type="nvidia",
            rate_limit_per_min=20
        )
        assert config.model == "test-model"
        assert config.max_steps == 5
        assert config.provider_type == "nvidia"
        assert config.rate_limit_per_min == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])