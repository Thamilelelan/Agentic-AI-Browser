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
    instead of fragile CSS selectors. Passes our Playwright page to Stagehand's act().
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
        """Initialize Stagehand with supported model via NVIDIA Build (OpenAI-compatible)."""
        if not STAGEHAND_AVAILABLE:
            self.log("[STAGEHAND] Stagehand not available")
            return False
            
        try:
            # Check if we're using a CDP-attached browser
            browser_type = "cdp" if "cdp" in str(self.page.context.browser).lower() else "chromium"
            if browser_type == "cdp":
                self.log("[STAGEHAND] CDP-attached browser detected, Stagehand requires local_browser/browserbase. Falling back to vision pipeline.")
                self._initialized = False
                return False
            
# Create Stagehand instance using local_browser
            from stagehand import local_browser
            chromium_path = "/home/cosmic/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome"
            import os
            if not os.path.exists(chromium_path):
                chromium_path = "/home/cosmic/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell"
            
            self.log(f"Launching browser with Stagehand's local_browser (executable: {chromium_path})...")
            self._stagehand_browser = await local_browser.launch(
                headless=self.page.context.browser._impl_obj._headless if hasattr(self.page.context.browser._impl_obj, '_headless') else True,
                executable_path=chromium_path,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            
            self.stagehand = await Stagehand.create(
                browser=self._stagehand_browser,
                api_key=self.config.api_key,
                api_url="https://integrate.api.nvidia.com",
                model="openai/gpt-4o",
            )
            
            # Get the page from Stagehand's browser context
            pages = await self.stagehand.browser.context.pages()
            if pages:
                self.page = pages[0]
            else:
                # Fallback: create a new page
                self.page = await self.stagehand.browser.context.new_page()
            
            self._initialized = True
            self.log("[STAGEHAND] Initialized successfully (using external page)")
            return True
            
        except Exception as e:
            self.log(f"[STAGEHAND] Initialization failed: {e}. Falling back to vision pipeline.")
            self._initialized = False
            return False
    
    async def act(self, instruction: str, log: Optional[Callable[[str], None]] = None) -> dict:
        """Execute a natural language action via Stagehand using our Playwright page.
        
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
            result = await self.stagehand.act(
                instruction,
                page=self.page,
                model=self._build_model_config(),
                timeout=self.config.timeout,
            )
            
            # Stagehand returns ActResult with data and metadata
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
                    observe_result = await self.stagehand.observe(
                        instruction,
                        page=self.page,
                        model=self._build_model_config(),
                    )
                    actions = observe_result.data if hasattr(observe_result, 'data') else []
                    if actions:
                        # Retry with the observed action
                        retry_result = await self.stagehand.act(
                            actions[0],
                            page=self.page,
                            model=self._build_model_config(),
                        )
                        return {"success": True, "retry": True, "result": str(retry_result)}
                except Exception:
                    pass
            
            return {"success": False, "error": error_msg, "instruction": instruction}
    
    def _build_model_config(self):
        """Build model configuration for Stagehand."""
        from stagehand.client_models import ModelConfig
        return ModelConfig(
            model_name="openai/gpt-4o",
            api_key=self.config.api_key,
        )
    
    async def observe(self, instruction: str) -> list:
        """Observe available actions for an instruction without executing."""
        if not self._initialized:
            return []
            
        try:
            result = await self.stagehand.observe(
                instruction,
                page=self.page,
                model=self._build_model_config(),
            )
            return result.data if hasattr(result, 'data') else []
        except Exception as e:
            self.log(f"[STAGEHAND] observe failed: {e}")
            return []
    
    async def extract(self, instruction: str, schema: Any) -> Any:
        """Extract structured data from the page."""
        if not self._initialized:
            return None
            
        try:
            result = await self.stagehand.extract(
                instruction,
                schema,
                page=self.page,
                model=self._build_model_config(),
            )
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