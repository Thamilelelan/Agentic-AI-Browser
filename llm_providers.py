"""LLM Provider Abstraction - supports Gemini and NVIDIA Nemotron"""
import os
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from google import genai
from google.genai import types
from openai import OpenAI


@dataclass
class LLMConfig:
    model: str
    max_tokens: int = 16000
    temperature: float = 1.0
    top_p: float = 0.95
    reasoning: bool = False
    medium_effort: bool = False


class LLMProvider(ABC):
    @abstractmethod
    def generate_json(self, prompt: str, config: LLMConfig) -> dict:
        pass


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-3.5-flash-lite"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate_json(self, prompt: str, config: LLMConfig) -> dict:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=config.temperature,
                    top_p=config.top_p,
                    max_output_tokens=config.max_tokens,
                ),
            )
            text = response.text or "{}"
            return json.loads(text)
        except Exception as e:
            return {"_parse_error": True, "_raw": str(e)}


class NvidiaProvider(LLMProvider):
    """NVIDIA Nemotron 3 Ultra via NVIDIA Build API (OpenAI-compatible)"""
    
    DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
    BASE_URL = "https://integrate.api.nvidia.com/v1"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: Optional[str] = None):
        self.client = OpenAI(
            base_url=base_url or self.BASE_URL,
            api_key=api_key,
        )
        self.model = model
        self._consecutive_failures = 0
        self._available = None  # None = not tested, True = available, False = unavailable

    def is_available(self) -> bool:
        """Check if NVIDIA API is accessible (cached after first check)"""
        if self._available is not None:
            return self._available
        
        try:
            # Quick test with minimal request
            self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
                temperature=0,
            )
            self._available = True
            return True
        except Exception as e:
            print(f"[NVIDIA] Availability check failed: {e}")
            self._available = False
            return False

    def _build_extra_body(self, config: LLMConfig) -> dict:
        """Build extra body for NVIDIA API with reasoning support"""
        return {
            "chat_template_kwargs": {"enable_thinking": config.reasoning},
            "reasoning_budget": config.max_tokens if config.reasoning else 0,
        }

    def generate_json(self, prompt: str, config: LLMConfig) -> dict:
        """Generate JSON response using NVIDIA Nemotron 3 Ultra with streaming and retry logic"""
        max_retries = 3
        base_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                extra_body = self._build_extra_body(config)
                
                print(f"[NVIDIA] Calling API with model={self.model}, prompt_len={len(prompt)} (attempt {attempt + 1}/{max_retries})")
                
                # Use streaming for better handling of large responses
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=config.temperature,
                    top_p=config.top_p,
                    max_tokens=config.max_tokens,
                    extra_body={
                        "chat_template_kwargs": {"enable_thinking": config.reasoning},
                        "reasoning_budget": config.max_tokens if config.reasoning else 0,
                    },
                    stream=True
                )
                
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
                
                full_text = content
                if reasoning_content:
                    full_text = f"<reasoning>{reasoning_content}</reasoning>\n{content}"
                
                print(f"[NVIDIA] Response length: {len(full_text)}, reasoning: {len(reasoning_content)}")
                
                if not full_text:
                    raise Exception("Empty response from NVIDIA API")
                
                # Try to parse JSON from the response
                try:
                    self._consecutive_failures = 0
                    return json.loads(content)
                except json.JSONDecodeError:
                    # Try to extract JSON from the response
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group(0))
                    return {"_parse_error": True, "_raw": content[:500]}
                    
            except Exception as e:
                error_msg = str(e)
                print(f"[NVIDIA] Error (attempt {attempt + 1}/{3}): {error_msg}")
                self._consecutive_failures += 1
                
                # Check for specific error types
                if "429" in str(e) or "rate limit" in str(e).lower():
                    wait_time = (2 ** attempt) * 5  # Exponential backoff
                    print(f"[NVIDIA] Rate limited, waiting {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                elif "500" in str(e) or "502" in str(e) or "503" in str(e) or "internal server error" in str(e).lower():
                    wait_time = (2 ** attempt) * 3
                    print(f"[NVIDIA] Server error, waiting {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                elif "401" in str(e) or "403" in str(e):
                    raise RuntimeError(f"NVIDIA API authentication failed: {error_msg}")
                
                if attempt == max_retries - 1:
                    return {"_parse_error": True, "_raw": f"NVIDIA API failed after {max_retries} attempts: {error_msg}"}
                import time
                time.sleep(base_delay * (attempt + 1))
        
        return {"_parse_error": True, "_raw": "Max retries exceeded"}


def create_llm_provider() -> LLMProvider:
    """Factory function - reads .env and returns appropriate provider"""
    provider_type = os.getenv("api_provider", "nvidia").lower()  # Default to NVIDIA
    
    if provider_type == "nvidia":
        api_key = os.getenv("nvidia_api_key")
        if not api_key:
            raise ValueError("NVIDIA provider selected but nvidia_api_key not set in .env")
        model = os.getenv("nvidia_model", "nvidia/nemotron-3-ultra-550b-a55b")
        return NvidiaProvider(api_key=api_key, model=model)
    
    elif provider_type == "gemini":
        api_key = os.getenv("gemini_api_key")
        if not api_key:
            raise ValueError("Gemini provider selected but gemini_api_key not set in .env")
        model = os.getenv("gemini_model", "gemini-3.5-flash-lite")
        return GeminiProvider(api_key=api_key, model=model)
    
    else:
        raise ValueError(f"Unknown api_provider: {provider_type}. Use 'gemini' or 'nvidia'")


# Rate limiter (shared)
import time

class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps = []

    def wait_if_needed(self):
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < self.window_seconds]
        
        if len(self.timestamps) >= self.max_requests:
            sleep_for = self.window_seconds - (now - self.timestamps[0])
            if sleep_for > 0:
                print(f"[RATE LIMIT] Hit {self.max_requests} req/{self.window_seconds}s cap. Sleeping {sleep_for:.1f}s...")
                time.sleep(sleep_for)
                now = time.time()
                self.timestamps = [t for t in self.timestamps if now - t < self.window_seconds]
        
        self.timestamps.append(time.time())


# Global rate limiter (configured per provider)
def get_rate_limiter(provider_type: str) -> RateLimiter:
    if provider_type == "nvidia":
        # NVIDIA Build API has different limits
        return RateLimiter(max_requests=30, window_seconds=60)
    return RateLimiter(max_requests=15, window_seconds=60)