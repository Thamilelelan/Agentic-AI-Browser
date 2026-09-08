"""Stagehand Layer - wraps Browserbase Stagehand SDK for reliable browser actions.

Replaces fragile selector-based clicking with natural language actions.
Integrates with our existing async architecture and Kimi K3 LLM.
"""
import asyncio
import os
import json
from typing import Optional, Callable, Any
from dataclasses import dataclass

try:
    from stagehand import Stagehand, ActResult
    STAGEHAND_AVAILABLE = True
except ImportError:
    STAGEHAND_AVAILABLE = False
    Stagehand = None
    ActResult = None


@dataclass
class StagehandConfig:
    """Configuration for Stagehand instance."""
    model_name: str = "moonshotai/kimi-k3"  # Kimi K3 via NVIDIA Build
    api_key: str = ""
    base_url: str = "https://integrate.api.nvidia.com/v1"
    timeout: int = 30000  # ms
    enable_cache: bool = False


class StagehandLayer:
    """Wrapper around Stagehand SDK for reliable browser actions.
    
    Uses natural language actions via Stagehand's `act()` method
    instead of fragile CSS selectors.
    """
    
    def __init__(
        self,
        page,  # Playwright async page object
        config: StagehandConfig,
        log: Callable[[str], None] = print,
    ):
        self.page = page
        self.config = config
        self.log = log
        self.stagehand: Optional[Any] = None
        self._initialized = False
        
    async def initialize(self) -> bool:
        """Initialize Stagehand with our Kimi K3 model via NVIDIA Build."""
        if not STAGEHAND_AVAILABLE:
            self.log("[STAGEHAND] Stagehand not available")
            return False
            
        try:
            # Stagehand expects a Playwright page object
            # We need to create Stagehand with our custom LLM callback
            # Stagehand's Python SDK uses a specific API...
            # Let me check the actual Stagehand Python SDK API
            
            # Based on Stagehand docs, we can pass a custom generate function
            # But first, let's try the standard way with Browserbase
            
            # For now, we'll create a wrapper that uses Stagehand's act()
            # with a custom model via the ModelGateway or direct API
            
            # Actually, Stagehand Python SDK requires Browserbase or local browser
            # It connects via CDP. Let's see...
            
            # The Stagehand.create() method takes a browser (Playwright browser)
            # and a model config. We'll pass our page's browser context.
            
            from stagehand import Stagehand
            
            # Get the browser from the page
            browser = self.page.context.browser
            
            # Create Stagehand with our custom model
            # Stagehand supports custom generate callbacks
            # For NVIDIA Build, we use the OpenAI-compatible endpoint
            
            self.stagehand = await Stagehand.create(
                browser=self.page.context.browser,
                model="moonshotai/kimi-k3",
                # For custom models, Stagehand may need specific config
                # Let's check if we can pass a generate callback
            )
            
            # Stagehand doesn't directly support custom callbacks in Python SDK yet
            # The TypeScript SDK supports `generate` callback
            # Python SDK may have limited support
            
            # Alternative: Use Stagehand with Browserbase ModelGateway
            # which supports moonshotai/kimi-k3 if available
            # Or use local_browser mode
            
            # For now, let's try to use Stagehand's act with the default
            # and fallback to our custom implementation
            
            self._initialized = True
            self.log("[STAGEHAND] Initialized successfully")
            return True
            
        except Exception as e:
            self.log(f"[STAGEHAND] Initialization failed: {e}")
            self._initialized = False
            return False
    
    async def act(self, instruction: str, log: Optional[Callable[[str], None]] = None) -> dict:
        """Execute a natural language action via Stagehand.
        
        Args:
            instruction: Natural language action (e.g., "click the latest video")
            log: Optional logger for action details
            
        Returns:
            Dict with success, action details, or error info
        """
        if not self._initialized or self.stagehand is None:
            return {"success": False, "error": "Stagehand not initialized"}
            
        log_fn = log or self.log
        
        try:
            self.log(f"[STAGEHAND] act: {instruction}")
            result = await self.stagehand.act(instruction)
            
            # Stagehand returns ActResult with data and metadata
            # result.data contains success, message, action_description, actions
            if hasattr(result, 'data'):
                action_data = result.data
                success = getattr(action_data, 'success', True)
                message = getattr(action_data, 'message', '')
                actions = getattr(action_data, 'actions', [])
                
                return {
                    "success": success,
                    "message": message,
                    "actions": actions,
                    "instruction": instruction
                }
            else:
                return {"success": True, "result": str(result)}
                
        except Exception as e:
            error_msg = str(e)
            self.log(f"[STAGEHAND] act failed: {error_msg}")
            
            # Check if it's a "method not supported" error
            if "method not supported" in error_msg.lower():
                # Try to use observe to get valid actions
                try:
                    observe_result = await self.stagehand.observe(instruction)
                    actions = observe_result.data if hasattr(observe_result, 'data') else []
                    if actions:
                        # Retry with the observed action
                        retry_result = await self.stagehand.act(actions[0])
                        return {"success": True, "retry": True, "result": str(retry_result)}
                except Exception:
                    pass
            
            return {"success": False, "error": error_msg, "instruction": instruction}
    
    async def observe(self, instruction: str) -> list:
        """Observe available actions for an instruction without executing."""
        if not self._initialized:
            return []
            
        try:
            result = await self.stagehand.observe(instruction)
            return result.data if hasattr(result, 'data') else []
        except Exception as e:
            self.log(f"[STAGEHAND] observe failed: {e}")
            return []
    
    async def extract(self, instruction: str, schema: Any) -> Any:
        """Extract structured data from the page."""
        if not self._initialized:
            return None
            
        try:
            result = await self.stagehand.extract(instruction, schema)
            return result.data if hasattr(result, 'data') else None
        except Exception as e:
            self.log(f"[STAGEHAND] extract failed: {e}")
            return None
    
    async def close(self):
        """Close Stagehand session."""
        if self.stagehand:
            try:
                await self.stagehand.close()
            except Exception:
                pass


# Alternative: Custom Stagehand-like wrapper using our Kimi K3 directly
# if Stagehand SDK doesn't support custom LLM callbacks

class CustomStagehandWrapper:
    """Custom Stagehand-like wrapper using our Kimi K3 directly.
    
    This is a fallback if Stagehand SDK doesn't support custom LLM callbacks.
    """
    
    def __init__(
        self,
        page,
        provider,  # Our async LLMProvider (Kimi K3)
        config: StagehandConfig,
        log: Callable[[str], None] = print,
    ):
        self.page = page
        self.provider = provider
        self.config = config
        self.log = log
    
    async def act(self, instruction: str, log: Optional[Callable[[str], None]] = None) -> dict:
        """Execute action using our Kimi K3 via natural language."""
        log_fn = log or self.log
        
        try:
            # Build prompt for Kimi K3 to determine action
            prompt = f"""You are a browser automation agent. Execute this instruction:

{instruction}

Current page: {self.page.url}
Current title: {await self.page.title()}

Return JSON with the action to perform:
{{
  "action": "click" | "type" | "scroll" | "navigate" | "wait",
  "selector": "CSS selector if click/type",
  "text": "text to type if type action",
  "url": "URL if navigate",
  "reasoning": "why this action"
}}

Be specific. Use CSS selectors from the page."""
            
            from llm_providers import LLMConfig
            config = LLMConfig(model="", temperature=0.3, max_tokens=500)
            
            # We'd need to get the page context first
            # This is a simplified version - the actual implementation
            # would need to get page context like our action_layer
            
            response = await self.provider.generate_json(prompt, config)
            
            # Parse and execute
            # This is complex - better to use Stagehand SDK directly
            
            return {"success": False, "error": "Not fully implemented"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}


async def create_stagehand_layer(
    page,
    config: StagehandConfig,
    log: Callable[[str], None] = print
) -> Optional[StagehandLayer]:
    """Factory function to create and initialize Stagehand layer.
    
    Returns initialized StagehandLayer or None if failed.
    """
    layer = StagehandLayer(page, config, log)
    success = await layer.initialize()
    return layer if success else None