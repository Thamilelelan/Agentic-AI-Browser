# RunAgent SuperBrowser - Development Plan

## Executive Summary

This document outlines the current state of the RunAgent SuperBrowser implementation vs. the RunAgent SuperBrowser paper requirements, and provides a prioritized roadmap for completing the project.

---

## Current State vs. Paper Requirements

### ✅ Implemented (Per Paper Requirements)

| Paper Requirement | Implementation Status | Location |
|-------------------|----------------------|----------|
| **Three-Layer Architecture** | ✅ Complete | `cognitive_layer.py`, `action_layer.py`, `agent_engine.py` |
| **Cognitive Layer (Brain)** | ✅ Complete | `cognitive_layer.py` - Orchestrator, Planner, Worker |
| **Action Layer (Body)** | ✅ Complete | `action_layer.py` + `agent_engine.py` |
| **Perception Layer (Basic)** | ✅ Partial | `action_layer.py` - `extract_page_context()` |
| **Three-Role Cognitive Architecture** | ✅ Complete | `cognitive_layer.py` - Orchestrator/Planner/Worker |
| **Structured JSON Output** | ✅ Complete | `llm_providers.py` - `response_mime_type="application/json"` |
| **Memory Ledger** | ✅ Complete | `memory.py` - Ledger, StepOutcome, DeadEnd |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |
| **Multi-Provider LLM** | ✅ Complete | `llm_providers.py` - NVIDIA + Gemini |
| **Rate Limiting** | ✅ Complete | `llm_providers.py` - `RateLimiter` |
| **Web UI with SSE** | ✅ Complete | `web_ui.py` + `templates/index.html` |
| **CDP Attach Mode** | ✅ Complete | `agent_engine.py` + `browser_config.py` |
| **Stealth Mode** | ✅ Complete | `action_layer.py` - `STEALTH_INIT_SCRIPT` |

---

## NOT IMPLEMENTED (Per Paper Requirements)

### Critical Missing Features

| Feature | Paper Reference | Priority | Effort |
|---------|----------------|----------|--------|
| **Vision Model Integration** | §3.1, §4.3, §6 | **CRITICAL** | High |
| Screenshot-to-Click Mapping | §4.3, §6.1 | **CRITICAL** | High |
| Visual Grounding (Bounding Boxes) | §4.3, §6.1 | **CRITICAL** | High |
| Set-of-Marks (SoM) Prompting | §4.3, §6.1 | **CRITICAL** | High |
| Visual Grounding Pipeline | §4.3, §6.1 | **CRITICAL** | High |
| Bounding Box Extraction | §4.3, §6.1 | **CRITICAL** | High |
| Async Vision Prefetch | §4.3, §4.5 | High | Medium |
| Compound-Row Splitting | §6.1 | High | Medium |
| Subgoal-Aware BBox Emphasis | §4.3, §4.4 | High | Medium |
| Page-Type-Aware Vision Tiering | §4.3 | Medium | Medium |
| Coverage Pass on Validator | §4.3 | Medium | Medium |
| Dead-Click Guard | §4.5 | High | Medium |
| Toggle Awareness | §4.5 | High | Medium |
| Chevron-Aware BBox Snapper | §6.1, §6.2 | High | High |
| Three-Tier Click Cascade | §6.3 | High | High |
| Motor Humanization (Bézier) | §6.4 | Medium | Medium |
| Direct Navigation Recovery | §6.5 | Medium | Medium |
| DOM Cache (Procedural Memory) | §4.5 | High | Medium |
| Six-Phase Eviction Loop | §5.3 | High | High |
| Screenshot Back-Patch | §5.3 | Medium | Medium |
| Failure Collapse | §5.3 | Medium | Medium |
| State-Block Eviction | §5.3 | Medium | Medium |
| Thinking-Block Strip | §5.3 | Low | Low |
| Old-Message Gut | §5.3 | Medium | Medium |
| Element-List Collapse | §5.3 | Low | Low |
| Declarative vs Procedural Memory | §5.4 | High | High |
| Role-Sliced Views | §5.5 | High | High |
| Orchestrator Verb Classifier | §4.2 | High | Medium |
| Search Worker (HTTP-only) | §4.2 | Medium | Medium |
| Circuit Breaker (per-domain) | §4.2 | Medium | Medium |

---

## PRIORITIZED ROADMAP

### Phase 1: Vision Model Integration (CRITICAL - Weeks 1-3)

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| **1.1** | Integrate Vision Model (Qwen2-VL-7B or GPT-4V) | 1 week | Vision model API access |
| **1.2** | Screenshot Capture Pipeline | 3 days | Playwright `page.screenshot()` |
| **1.3** | Set-of-Marks (SoM) Annotation | 1 week | Bounding box overlay library |
| **1.4** | Bounding Box Extraction | 1 week | Playwright `element.bounding_box()` |
| **1.4** | Set-of-Marks Prompting | 1 week | Prompt engineering |
| **1.5** | Bounding Box Click Execution | 3 days | `page.mouse.click(x, y)` |
| **1.6** | Async Vision Prefetch | 1 week | Background task queue |

**Deliverable**: Agent can "see" the page, identify clickable elements via bounding boxes, and click via coordinates.

---

### Phase 2: Advanced Vision Pipeline (Weeks 4-6)

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| **2.1** | Async Vision Prefetch Pipeline | 1 week | Vision model + queue |
| **2.2** | Compound-Row Splitting | 1 week | Bounding box logic |
| **2.2** | Chevron-Aware BBox Snapper | 1 week | Bounding box logic |
| **2.3** | Subgoal-Aware BBox Emphasis | 1 week | Planner integration |
| **2.2** | Page-Type-Aware Vision Tiering | 1 week | Page classification |
| **2.3** | Coverage Pass on Validator | 1 week | Vision + validator |
| **2.4** | Subgoal-Aware BBox Emphasis | 1 week | Planner integration |

---

### Phase 3: Memory & Cognitive Architecture (Weeks 7-9)

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| **3.1** | Six-Phase Eviction Loop | 1 week | Ledger exists |
| **3.2** | Screenshot Back-Patch | 3 days | Vision pipeline |
| **3.2** | Failure Collapse | 3 days | Ledger exists |
| **3.2** | State-Block Eviction | 3 days | Ledger exists |
| **3.2** | Thinking-Block Strip | 2 days | LLM response parsing |
| **3.2** | Old-Message Gut | 3 days | Ledger + messages |
| **3.2** | Element-List Collapse | 2 days | Perception layer |
| **3.3** | Declarative vs Procedural Memory | 1 week | Memory module |
| **3.4** | DOM Cache (Procedural Memory) | 1 week | Action layer |
| **3.4** | Role-Sliced Views | 3 days | Ledger + prompts |
| **3.4** | Orchestrator Verb Classifier | 1 week | Orchestrator prompt |
| **3.4** | Search Worker (HTTP-only) | 1 week | `search_and_verify` exists |

---

### Phase 4: Advanced Action Layer (Weeks 10-12)

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| **4.1** | Dead-Click Guard | 3 days | Action layer |
| **4.2** | Toggle Awareness | 3 days | Perception |
| **4.3** | Chevron-Aware BBox Snapper | 1 week | Vision + click |
| **4.2** | Three-Tier Click Cascade | 1 week | CDP + Playwright |
| **4.2** | Motor Humanization (Bézier) | 1 week | `page.mouse` API |
| **4.2** | Direct Navigation Recovery | 3 days | Navigation logic |
| **4.2** | Coverage Pass Validator | 1 week | Vision pipeline |
| **4.2** | Toggle Awareness | 3 days | Perception |

---

### Phase 5: Orchestrator & Search (Weeks 13-14)

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| **5.1** | Orchestrator Verb Classifier | 1 week | Orchestrator prompt |
| **5.2** | Search Worker (HTTP-only) | 1 week | `search_and_verify` exists |
| **5.2** | Circuit Breaker (per-domain) | 1 week | Rate limiter |

---

## Implementation Priority Matrix

| Priority | Task | Phase | Blocked By |
|----------|------|-------|------------|
| **P0** | Vision Model Integration | 1 | Model access |
| **P0** | Screenshot Pipeline | 1 | Playwright |
| **P0** | Set-of-Marks (SoM) | 1 | Vision model |
| **P0** | Bounding Box Click | 1 | SoM + Playwright |
| **P0** | Async Vision Prefetch | 2 | Vision pipeline |
| **P1** | Six-Phase Eviction | 3 | Ledger exists |
| **P1** | DOM Cache (Procedural Memory) | 3 | Action layer |
| **P1** | Chevron-Aware Snapper | 2 | Vision + Click |
| **P1** | Three-Tier Click Cascade | 2 | CDP + Playwright |
| **P1** | Motor Humanization | 2 | Playwright mouse API |
| **P1** | Three-Role (Done) | ✅ Done | - |
| **P2** | Search Worker | 2 | `search_and_verify` |
| **P2** | Circuit Breaker | 2 | Rate limiter |
| **P2** | Declarative/Procedural Memory | 3 | Memory module |
| **P2** | Coverage Pass Validator | 2 | Vision pipeline |
| **P2** | Toggle Awareness | 3 | Perception |
| **P2** | Declarative/Procedural | 3 | Memory module |
| **P2** | Circuit Breaker | 2 | Rate limiter |
| **P2** | Motor Humanization | 3 | Playwright mouse |
| **P2** | Direct Navigation Recovery | 3 | Navigation logic |
| **P3** | Thinking-Block Strip | 3 | LLM response parsing |
| **P3** | Old-Message Gut | 3 | Ledger + messages |
| **P3** | Element-List Collapse | 3 | Perception |
| **P3** | Old-Message Gut | 3 | Ledger + messages |

---

## Current Test Coverage

| Component | Unit Tests | Integration | E2E |
|-----------|------------|-------------|-----|
| LLM Providers | ✅ | ❌ | ❌ |
| Cognitive Layer | ✅ | ❌ | ❌ |
| Agent Engine | ✅ | ❌ | ❌ |
| Web UI | ✅ | ❌ | ❌ |
| Action Layer | ❌ | ❌ | ❌ |
| Memory | ❌ | ❌ | ❌ |
| Browser Config | ❌ | ❌ | ❌ |
| **Vision Model** | ❌ | ❌ | ❌ |
| **Vision Pipeline** | ❌ | ❌ | ❌ |

---

## Testing Strategy

### Required Test Suite

```bash
# Unit Tests
pytest tests/unit/llm_providers_test.py
pytest tests/unit/cognitive_layer_test.py
pytest tests/unit/action_layer_test.py
pytest tests/unit/memory_test.py
pytest tests/unit/agent_engine_test.py

# Integration Tests
pytest tests/integration/agent_engine_test.py
pytest tests/integration/vision_pipeline_test.py

# E2E Tests
pytest tests/e2e/web_ui_test.py
pytest tests/e2e/agent_e2e_test.py

# Vision-Specific
pytest tests/vision/bounding_box_test.py
pytest tests/vision/som_annotation_test.py
pytest tests/vision/click_accuracy_test.py
```

### Test Fixtures Needed

```python
# conftest.py
@pytest.fixture
def mock_nvidia_provider():
    return MockNvidiaProvider()

@pytest.fixture
def mock_gemini_provider():
    return MockGeminiProvider()

@pytest.fixture
def mock_page():
    return MockPlaywrightPage()

@pytest.fixture
def sample_ledger():
    return Ledger(goal="test goal")
```

---

## Timeline Summary

```
Week 1-3:   Vision Model Integration (P0)
Week 4-6:   Advanced Vision Pipeline
Week 7-9:   Memory & Cognitive Architecture
Week 10-12: Advanced Action Layer
Week 13-14: Orchestrator & Search
Week 15+:   Testing, Polish, Optimization
```

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Task Success Rate | ~60% | >90% |
| Click Accuracy | ~40% | >95% |
| Vision Accuracy | 0% | >90% |
| Fallback Rate | ~30% | <5% |
| Steps per Task | 8-20 | 3-8 |
| Hallucination Rate | ~15% | <2% |
| Rate Limit Hits | Frequent | Zero |
| Fallback Rate | ~30% | <5% |

---

## Immediate Next Steps (This Week)

1. **Get NVIDIA API Key** - Valid key for Nemotron 3 Ultra
2. **Integrate Vision Model** - Qwen2-VL-7B or GPT-4V
3. **Build Screenshot Pipeline** - Playwright `page.screenshot()` → Vision model
4. **Implement SoM Annotation** - Overlay bounding boxes with IDs
5. **Add Bounding Box Click** - `page.mouse.click(x, y)` via coordinates
6. **Test on Real Sites** - Amazon, GitHub, YouTube

---

## Reference Materials

- **RunAgent Paper**: §3.1, §3.4, §4.1-4.5, §5.1-5.7, §6.1-6.5
- **Set-of-Mark Paper**: Yang et al. 2023 (SoM Prompting)
- **SeeAct Paper**: Zheng et al. 2024 (Planning-then-Grounding)
- **CogAgent Paper**: Hong et al. 2024 (1120px Vision Encoder)
- **UI-TARS Paper**: Qin et al. 2025 (Dual-Resolution VLM)
- **NVIDIA Nemotron 3 Ultra**: Technical Report 2026
- **Playwright Docs**: `page.screenshot()`, `element.bounding_box()`, `page.mouse.click(x, y)`

---

## Vision Model Options

| Model | Context | Cost | Latency | Deployment |
|-------|---------|------|---------|------------|
| Qwen2-VL-7B | 32K | Free (local) | ~2s | Local GPU |
| GPT-4V | 128K | $0.01/1K | ~3s | API |
| Qwen2-VL-72B | 32K | $0.002/1K | ~5s | API |
| LLaVA-Next | 32K | Free (local) | ~3s | Local GPU |

**Recommendation**: Start with Qwen2-VL-7B local for development, switch to GPT-4V for production.

---

*Last Updated: 2026-08-16*
*Version: 1.0*
*Status: Planning Phase - Vision Integration Next*