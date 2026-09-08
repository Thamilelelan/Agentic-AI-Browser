# LLM Providers Documentation

## Overview

The `llm_providers.py` module provides an abstraction layer for LLM providers, supporting **NVIDIA Nemotron 3 Ultra** (primary), **Google Gemini** (fallback), and **NVIDIA Vision-Language Models** (vision grounding). The factory function `create_llm_provider()` reads the `.env` file to determine which provider to use.

## Provider Interface

All providers implement the `LLMProvider` abstract base class:

```python
class LLMProvider(ABC):
    @abstractmethod
    def generate_json(self, prompt: str, config: LLMConfig) -> dict:
        """Generate a JSON response from the LLM."""
        pass
```

## NvidiaProvider (Primary - Nemotron 3 Ultra)

### Configuration
- **Model**: `nvidia/nemotron-3-ultra` (550B total, 55B active)
- **Endpoint**: `https://integrate.api.nvidia.com/v1`
- **Architecture**: Hybrid Mamba-2 + MoE + Attention with Multi-Token Prediction
- **Context Length**: Up to 1M tokens
- **Rate Limit**: 30 requests/minute

### Key Features

1. **Streaming with Reasoning**
   - Uses streaming API for real-time response
   - Extracts `reasoning_content` from delta objects
   - Combines reasoning + content for full context

2. **Reasoning Support**
   - `enable_thinking`: Enables chain-of-thought reasoning
   - `reasoning_budget`: Token budget for reasoning (max_tokens when enabled)
   - Returns reasoning content separately for debugging

3. **Retry Logic with Exponential Backoff**
   - Max 3 retries
   - Exponential backoff: 2s, 4s, 8s for rate limits (429)
   - 3s, 6s, 9s for server errors (5xx)
   - 401/403: No retry (auth errors)
   - 429: Exponential backoff (5s, 10s, 20s)
   - 5xx: Exponential backoff (3s, 6s, 12s)

4. **Streaming Response Processing**
   - Extracts `reasoning_content` from delta objects
   - Combines reasoning + content for full response
   - JSON parsing with fallback extraction

### Configuration
```python
config = LLMConfig(
    model="nvidia/nemotron-3-ultra",
    max_tokens=16000,
    temperature=1.0,
    top_p=0.95,
    reasoning=True,           # Enable thinking
    medium_effort=False       # Medium reasoning effort
)
```

### API Call Structure
```python
completion = client.chat.completions.create(
    model="nvidia/nemotron-3-ultra",
    messages=[{"role": "user", "content": prompt}],
    temperature=config.temperature,
    top_p=config.top_p,
    max_tokens=config.max_tokens,
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": config.reasoning,
            "force_nonempty_content": True
        },
        "reasoning_budget": config.max_tokens if config.reasoning else 0,
    },
    stream=True
)
```

### Response Processing
```python
# Streaming response processing
reasoning_content = ""
content = ""
for chunk in completion:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    reasoning = getattr(delta, "reasoning_content", None)
    if reasoning:
        reasoning_content += reasoning
    if delta.content is not None:
        content += delta.content

# Combine reasoning + content
full_text = content
if reasoning_content:
    full_text = f"<reasoning>{reasoning_content}</reasoning>\n{content}"

# Parse JSON from content
try:
    return json.loads(content)
except json.JSONDecodeError:
    # Extract JSON from text
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))
```

### Error Handling
- **401/403**: Raise `RuntimeError` (auth errors, not retried)
- **429**: Rate limited - exponential backoff (5s, 10s, 20s)
- **5xx**: Server error - exponential backoff (3s, 6s, 12s)
- **404**: Model not found - raise `RuntimeError`
- **Max Retries**: 3 attempts with exponential backoff

### Rate Limiting
- **NVIDIA**: 30 requests/minute (rolling 60s window)
- Implemented via `RateLimiter` class with sliding window

---

## NvidiaVisionProvider (Vision-Language Model)

### Configuration
- **Model**: `nvidia/llama-3.1-nemotron-nano-vl-8b-v1` (8B params)
- **Endpoint**: `https://integrate.api.nvidia.com/v1` (same as Nemotron)
- **Architecture**: CRadioV2-H vision encoder + LLaMA-3.1-8B-Instruct
- **Context Length**: 16K tokens (input + output)
- **Input**: Text + Image (base64 encoded)
- **Rate Limit**: 10 requests/minute (conservative)

### Key Features
1. **Multi-modal Input**: Accepts text + image (PNG/JPEG) via base64
2. **Set-of-Marks (SoM) Grounding**: Designed for SeeAct-style vision grounding
3. **Document Intelligence**: Optimized for OCR, chart/table reading, UI element detection
4. **Structured Output**: JSON response with element_id, action, text, reasoning

### Usage with Vision Grounding (SeeAct Style)
```python
from llm_providers import create_vision_provider, get_vision_rate_limiter
from cognitive_layer import run_vision_grounding

vision_provider = create_vision_provider()
vision_rate_limiter = get_vision_rate_limiter()

# Build vision context (screenshot + SoM annotations)
vision_context = build_vision_context(page, goal, ledger.render_for_worker())

# Run vision grounding
decision = run_vision_grounding(
    vision_provider, goal, ledger, 
    {"annotated_screenshot_bytes": vision_context["annotated_screenshot_bytes"],
     "vision_elements": vision_context["elements"],
     "viewport_width": vision_context["viewport_width"],
     "viewport_height": vision_context["viewport_height"]},
    vision_context["elements"],
    vision_rate_limiter
)

# decision = {"element_id": 5, "action": "click", "text": "", "reasoning": "..."}
```

### API Call Structure (with Image)
```python
import base64

with open("screenshot.png", "rb") as f:
    b64_image = base64.b64encode(f.read()).decode("utf-8")

completion = client.chat.completions.create(
    model="nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
        ]
    }],
    temperature=0.3,
    top_p=0.95,
    max_tokens=1000,
    stream=True
)
```

### Error Handling
- **401/403**: Raise `RuntimeError` (auth errors)
- **429**: Rate limited - exponential backoff
- **5xx**: Server error - exponential backoff
- **Max Retries**: 3 attempts

### Rate Limiting
- **Vision**: 10 requests/minute (conservative for multi-modal)

---

## GeminiProvider (Fallback)

### Configuration
- **Model**: `gemini-3.5-flash-lite`
- **SDK**: `google-genai` (Google GenAI SDK)
- **Rate Limit**: 15 requests/minute
- **Response Format**: JSON-only via `response_mime_type="application/json"`

### API Call
```python
response = client.models.generate_content(
    model=self.model,
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=config.temperature,
        top_p=config.top_p,
        max_output_tokens=config.max_tokens,
    ),
)
```

### JSON Enforcement
Uses `response_mime_type="application/json"` to enforce JSON output, avoiding parse errors.

---

## Factory Functions

### Main LLM Provider
```python
def create_llm_provider() -> LLMProvider:
    provider_type = os.getenv("api_provider", "nvidia").lower()
    
    if provider_type == "nvidia":
        api_key = os.getenv("nvidia_api_key")
        if not api_key:
            raise ValueError("NVIDIA provider selected but nvidia_api_key not set in .env")
        model = os.getenv("nvidia_model", "nvidia/nemotron-3-ultra")
        return NvidiaProvider(api_key=api_key, model=model)
    
    elif provider_type == "gemini":
        api_key = os.getenv("gemini_api_key")
        if not api_key:
            raise ValueError("Gemini provider selected but gemini_api_key not set in .env")
        model = os.getenv("gemini_model", "gemini-3.5-flash-lite")
        return GeminiProvider(api_key=api_key, model=model)
    
    else:
        raise ValueError(f"Unknown api_provider: {provider_type}. Use 'gemini' or 'nvidia'")
```

### Vision Provider
```python
def create_vision_provider() -> LLMProvider:
    """Factory function - creates NVIDIA Vision-Language Model provider"""
    api_key = os.getenv("nvidia_api_key")
    if not api_key:
        raise ValueError("Vision provider requires nvidia_api_key in .env")
    model = os.getenv("nvidia_vision_model", "nvidia/llama-3.1-nemotron-nano-vl-8b-v1")
    return NvidiaVisionProvider(api_key=api_key, model=model)
```

### Rate Limiters
```python
def get_rate_limiter(provider_type: str) -> RateLimiter:
    if provider_type == "nvidia":
        return RateLimiter(max_requests=30, window_seconds=60)
    elif provider_type == "vision":
        return RateLimiter(max_requests=10, window_seconds=60)
    return RateLimiter(max_requests=15, window_seconds=60)
```

---

## Configuration (LLMConfig)

```python
@dataclass
class LLMConfig:
    model: str
    max_tokens: int = 16000
    temperature: float = 1.0
    top_p: float = 0.95
    reasoning: bool = False
    medium_effort: bool = False
```

### Usage in Cognitive Layer
```python
config = LLMConfig(
    model="",
    temperature=0.3,
    max_tokens=1000,
    reasoning=True,        # Enable thinking for NVIDIA
    medium_effort=False    # Optional medium reasoning
)
```

---

## Environment Variables

```bash
# Primary provider
api_provider=nvidia          # or "gemini"

# NVIDIA Nemotron 3 Ultra
nvidia_api_key=your_nvidia_build_api_key
nvidia_model=nvidia/nemotron-3-ultra

# NVIDIA Vision (optional)
nvidia_vision_model=nvidia/llama-3.1-nemotron-nano-vl-8b-v1

# Gemini (fallback)
gemini_api_key=your_google_api_key
gemini_model=gemini-3.5-flash-lite

# Optional model override
AGENT_MODEL=nvidia/nemotron-3-ultra
```

---

## Testing

```bash
# Test NVIDIA provider
python3 -c "
import os
os.environ['api_provider'] = 'nvidia'
os.environ['nvidia_api_key'] = 'your_key'
from llm_providers import create_llm_provider
provider = create_llm_provider()
print(provider.generate_json('Say hello', LLMConfig(model='', max_tokens=100)))
"

# Test Vision provider
python3 -c "
import os
os.environ['nvidia_api_key'] = 'your_key'
from llm_providers import create_vision_provider
provider = create_vision_provider()
print(provider.generate_json('Describe this image', LLMConfig(model='', max_tokens=100), image_path='test.png'))
"

# Test Gemini
os.environ['api_provider'] = 'gemini'
os.environ['gemini_api_key'] = 'your_key'
provider = create_llm_provider()
result = provider.generate_json('Say hello', LLMConfig(model='', max_tokens=100))
```