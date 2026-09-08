"""LLM Provider Abstraction - supports Gemini, NVIDIA Nemotron, and NVIDIA Vision-Language Models"""
import os
import json
import re
import base64
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
    """NVIDIA Build API - Supports Kimi K3 (multimodal) and other models"""
    
    # Free models on NVIDIA Build with "Free Endpoint" badge
    FREE_MODELS = {
        "kimi-k3": "moonshotai/kimi-k3",  # Multimodal (text + image), ~2.8T, 1M context, Free Endpoint
    }
    
    DEFAULT_MODEL = "moonshotai/kimi-k3"  # Kimi K3 - multimodal, free endpoint
    BASE_URL = "https://integrate.api.nvidia.com/v1"
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: Optional[str] = None):
        self.client = OpenAI(
            base_url=base_url or self.BASE_URL,
            api_key=api_key,
        )
        self.model = model
        self._consecutive_failures = 0
        self._available = None
    
    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        
        try:
            self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=10,
                temperature=1.0,
            )
            self._available = True
            return True
        except Exception as e:
            print(f"[NVIDIA] Availability check failed: {e}")
            self._available = False
            return False
    
    def _build_extra_body(self, config: LLMConfig) -> dict:
        """Build extra body for NVIDIA API - Kimi K3 uses reasoning_effort"""
        return {
            "reasoning_effort": "max" if config.reasoning else "low",
        }
    
    def generate_json(self, prompt: str, config: LLMConfig) -> dict:
        """Generate JSON response using NVIDIA Build API (Kimi K3 etc.) with streaming and retry logic.
        
        Kimi K3 defaults: temperature=1.0, reasoning_effort=max
        JSON output is enforced via response format parsing.
        """
        max_retries = 3
        base_delay = 2.0
        
        temperature = config.temperature if config.temperature != 1.0 else 1.0
        top_p = config.top_p if config.top_p != 0.95 else 0.95
        
        for attempt in range(max_retries):
            try:
                extra_body = self._build_extra_body(config)
                
                print(f"[NVIDIA] Calling API with model={self.model}, prompt_len={len(prompt)}, temp={temperature}, top_p={top_p}, reasoning={config.reasoning} (attempt {attempt + 1}/{max_retries})")
                
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=config.max_tokens,
                    extra_body=extra_body,
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
                
                try:
                    self._consecutive_failures = 0
                    return json.loads(content)
                except json.JSONDecodeError:
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group(0))
                    raise ValueError(f"JSON parse failed: {content[:200]}")
                    
            except Exception as e:
                error_msg = str(e)
                print(f"[NVIDIA] Error (attempt {attempt + 1}/{3}): {error_msg}")
                self._consecutive_failures += 1
                
                if "429" in str(e) or "rate limit" in str(e).lower():
                    wait_time = (2 ** attempt) * 5
                    print(f"[NVIDIA] Rate limited, waiting {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                elif "500" in str(e) or "502" in str(e) or "503" in str(e) or "internal server error" in str(e).lower() or "service temporarily overloaded" in str(e).lower():
                    wait_time = (2 ** attempt) * 3
                    print(f"[NVIDIA] Server error, waiting {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                elif "401" in str(e) or "403" in str(e):
                    raise RuntimeError(f"NVIDIA API authentication failed: {error_msg}")
                elif "404" in str(e) or "not found" in str(e).lower():
                    raise RuntimeError(f"Model not found: {self.model}. Check model name.")
                elif "JSON parse failed" in str(e):
                    raise
                
                if attempt == max_retries - 1:
                    raise RuntimeError(f"NVIDIA API failed after {max_retries} attempts: {error_msg}")
                import time
                time.sleep(base_delay * (attempt + 1))
        
        raise RuntimeError("Max retries exceeded")


class NvidiaVisionProvider(LLMProvider):
    """NVIDIA Build Vision Models - Uses Kimi K3 (multimodal, free endpoint)"""
    
    # Free multimodal vision models on NVIDIA Build
    FREE_MODELS = {
        "kimi-k3": "moonshotai/kimi-k3",  # Multimodal (text + image), ~2.8T, 1M context, Free Endpoint
    }
    
    DEFAULT_MODEL = "moonshotai/kimi-k3"  # Kimi K3 - multimodal, free endpoint
    BASE_URL = "https://integrate.api.nvidia.com/v1"
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: Optional[str] = None):
        self.client = OpenAI(
            base_url=base_url or self.BASE_URL,
            api_key=api_key,
        )
        self.model = model
        self._available = None
    
    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
                temperature=0,
            )
            self._available = True
            return True
        except Exception as e:
            print(f"[NVIDIA VISION] Availability check failed: {e}")
            self._available = False
            return False
    
    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64 for API"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def generate_json(self, prompt: str, config: LLMConfig, image_path: Optional[str] = None) -> dict:
        """Generate JSON response using NVIDIA VLM with optional image"""
        max_retries = 3
        base_delay = 2.0
        
        # Build message content for multimodal (Kimi K3 supports image_url)
        if image_path:
            b64_image = self._encode_image(image_path)
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
                ]
            }]
        else:
            messages = [{"role": "user", "content": prompt}]
        
        for attempt in range(max_retries):
            try:
                print(f"[NVIDIA VISION] Calling API with model={self.model}, prompt_len={len(prompt)}, image={'yes' if image_path else 'no'} (attempt {attempt + 1}/{max_retries})")
                
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=config.temperature,
                    top_p=config.top_p,
                    max_tokens=config.max_tokens,
                    stream=True
                )
                
                content = ""
                for chunk in completion:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content is not None:
                        content += delta.content
                
                print(f"[NVIDIA VISION] Response length: {len(content)}")
                
                if not content:
                    raise Exception("Empty response from NVIDIA VLM API")
                
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group(0))
                    return {"_parse_error": True, "_raw": content[:500]}
                    
            except Exception as e:
                error_msg = str(e)
                print(f"[NVIDIA VISION] Error (attempt {attempt + 1}/{3}): {error_msg}")
                
                if "429" in str(e) or "rate limit" in str(e).lower():
                    wait_time = (2 ** attempt) * 5
                    print(f"[NVIDIA VISION] Rate limited, waiting {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                elif "500" in str(e) or "502" in str(e) or "503" in str(e) or "internal server error" in str(e).lower():
                    wait_time = (2 ** attempt) * 3
                    print(f"[NVIDIA VISION] Server error, waiting {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                elif "401" in str(e) or "403" in str(e):
                    raise RuntimeError(f"NVIDIA VLM API authentication failed: {error_msg}")
                
                if attempt == max_retries - 1:
                    raise RuntimeError(f"NVIDIA VLM API failed after {max_retries} attempts: {error_msg}")
                import time
                time.sleep(base_delay * (attempt + 1))
        
        raise RuntimeError("Max retries exceeded")


class OpenAIVisionProvider(LLMProvider):
    """OpenAI GPT-4o / GPT-4V via OpenAI API - Used in SeeAct paper"""
    
    DEFAULT_MODEL = "gpt-4o"
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.client = OpenAI(api_key=api_key)
        self.model = model
    
    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def generate_json(self, prompt: str, config: LLMConfig, image_path: Optional[str] = None) -> dict:
        max_retries = 3
        base_delay = 2.0
        
        if image_path:
            b64_image = self._encode_image(image_path)
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}", "detail": "high"}}
                ]
            }]
        else:
            messages = [{"role": "user", "content": prompt}]
        
        for attempt in range(max_retries):
            try:
                print(f"[OPENAI VISION] Calling API with model={self.model}, image={'yes' if image_path else 'no'} (attempt {attempt + 1}/{max_retries})")
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=config.temperature,
                    top_p=config.top_p,
                    max_tokens=config.max_tokens,
                    response_format={"type": "json_object"},
                )
                
                content = response.choices[0].message.content or "{}"
                print(f"[OPENAI VISION] Response length: {len(content)}")
                
                if not content:
                    raise Exception("Empty response from OpenAI VLM API")
                
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group(0))
                    return {"_parse_error": True, "_raw": content[:500]}
                    
            except Exception as e:
                error_msg = str(e)
                print(f"[OPENAI VISION] Error (attempt {attempt + 1}/{3}): {error_msg}")
                if attempt == max_retries - 1:
                    raise RuntimeError(f"OpenAI Vision API failed after {max_retries} attempts: {error_msg}")
                import time
                time.sleep(base_delay * (attempt + 1))
        
        raise RuntimeError("Max retries exceeded")


class GeminiVisionProvider(LLMProvider):
    """Google Gemini 1.5 Flash / 2.0 Flash via Google GenAI - Flash-tier models with native bbox output (per RunAgent paper)"""
    
    DEFAULT_MODEL = "gemini-2.0-flash"  # Flash-tier per RunAgent paper recommendation
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        from google import genai
        from google.genai import types
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self._types = types
    
    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def generate_json(self, prompt: str, config: LLMConfig, image_path: Optional[str] = None) -> dict:
        max_retries = 3
        base_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                print(f"[GEMINI VISION] Calling API with model={self.model}, image={'yes' if image_path else 'no'} (attempt {attempt + 1}/{max_retries})")
                
                if image_path:
                    b64_image = self._encode_image(image_path)
                    # Use Part objects for multimodal content (Google GenAI SDK format)
                    contents = [
                        self._types.Part.from_text(text=prompt),
                        self._types.Part.from_bytes(data=base64.b64decode(b64_image), mime_type="image/png")
                    ]
                else:
                    contents = prompt
                
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=self._types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=config.temperature,
                        top_p=config.top_p,
                        max_output_tokens=config.max_tokens,
                    ),
                )
                
                text = response.text or "{}"
                print(f"[GEMINI VISION] Response length: {len(text)}")
                
                if not text:
                    raise Exception("Empty response from Gemini Vision API")
                
                return json.loads(text)
                    
            except Exception as e:
                error_msg = str(e)
                print(f"[GEMINI VISION] Error (attempt {attempt + 1}/{3}): {error_msg}")
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Gemini Vision API failed after {max_retries} attempts: {error_msg}")
                import time
                time.sleep(base_delay * (attempt + 1))
        
        raise RuntimeError("Max retries exceeded")


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


def create_vision_provider() -> LLMProvider:
    """Factory function - creates vision provider based on env config"""
    vision_provider_type = os.getenv("vision_provider", "gemini").lower()
    
    if vision_provider_type == "openai":
        api_key = os.getenv("openai_api_key")
        if not api_key:
            raise ValueError("OpenAI vision provider requires openai_api_key in .env")
        model = os.getenv("openai_vision_model", "gpt-4o")
        return OpenAIVisionProvider(api_key=api_key, model=model)
    
    elif vision_provider_type == "gemini":
        api_key = os.getenv("gemini_api_key")
        if not api_key:
            raise ValueError("Gemini vision provider requires gemini_api_key in .env")
        model = os.getenv("gemini_vision_model", "gemini-2.0-flash")
        return GeminiVisionProvider(api_key=api_key, model=model)
    
    elif vision_provider_type == "nvidia":
        api_key = os.getenv("nvidia_api_key")
        if not api_key:
            raise ValueError("NVIDIA vision provider requires nvidia_api_key in .env")
        model = os.getenv("nvidia_vision_model", "moonshotai/kimi-k3")  # Free multimodal vision
        return NvidiaVisionProvider(api_key=api_key, model=model)
    
    else:
        raise ValueError(f"Unknown vision_provider: {vision_provider_type}. Use 'openai', 'gemini', or 'nvidia'")


def get_vision_rate_limiter() -> RateLimiter:
    """Rate limiter for vision model - more conservative"""
    return RateLimiter(max_requests=10, window_seconds=60)


# Rate limiter (shared)
import time

class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60, initial_delay: float = 1.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps = []
        self.initial_delay = initial_delay
        self._first_call = True

    def wait_if_needed(self):
        import time
        if self._first_call:
            self._first_call = False
            if self.initial_delay > 0:
                time.sleep(self.initial_delay)
        
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
        # NVIDIA Build FREE tier - EXTREMELY conservative
        # Free tier has very aggressive limits, especially on vision
        # Use 1 req/min for text, 1 req/2min for vision
        return RateLimiter(max_requests=1, window_seconds=60, initial_delay=3.0)
    elif provider_type == "vision":
        # Vision model - extremely conservative for free tier
        return RateLimiter(max_requests=1, window_seconds=120, initial_delay=5.0)
    return RateLimiter(max_requests=5, window_seconds=60, initial_delay=2.0)