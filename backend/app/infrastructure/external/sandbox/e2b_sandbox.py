import asyncio
import os
import logging
from typing import Optional
from e2b import Sandbox as E2BSandboxSDK
from app.domain.external.sandbox import Sandbox, Browser
from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser
from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class E2BSandbox(Sandbox):
    """E2B Sandbox implementation that replaces DockerSandbox."""
    
    def __init__(self, e2b_sandbox: E2BSandboxSDK):
        self.e2b_sandbox = e2b_sandbox
        self._id = e2b_sandbox.sandbox_id
        # E2B provides public URLs for exposed ports
        # Port 8080 is our FastAPI app, 9222 is Chrome CDP
        self._ip = e2b_sandbox.get_host(8080)
        self._cdp_url = f"http://{e2b_sandbox.get_host(9222)}"
        logger.info(f"E2B Sandbox created: {self.id}, Hostname: {self.ip}")

    async def destroy(self) -> bool:
        """Destroy E2B sandbox"""
        try:
            await asyncio.to_thread(self.e2b_sandbox.kill)
            return True
        except Exception as e:
            logger.error(f"Failed to destroy E2B sandbox: {str(e)}")
            return False

    async def get_browser(self) -> Browser:
        """Get browser instance connected to E2B sandbox"""
        settings = get_settings()
        engine = (settings.browser_engine or "browser_use").lower().strip()
        if engine == "browser_use":
            return BrowserUseBrowser(self.cdp_url)
        return PlaywrightBrowser(self.cdp_url)

    @classmethod
    async def create(cls) -> Sandbox:
        """Create a new E2B sandbox instance using our custom template"""
        settings = get_settings()
        api_key = os.getenv("E2B_API_KEY")
        # Template ID yang baru saja kita bangun
        template_id = "efb1pjfnzc3d7di190ms" 
        
        logger.info(f"Creating E2B sandbox from template: {template_id}")
        e2b_sandbox = await asyncio.to_thread(
            E2BSandboxSDK.create,
            template=template_id,
            api_key=api_key
        )
        return cls(e2b_sandbox)

    @property
    def id(self) -> str:
        return self._id

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def cdp_url(self) -> str:
        return self._cdp_url

    @classmethod
    async def get(cls, id: str) -> Sandbox:
        """Connect to an existing E2B sandbox"""
        api_key = os.getenv("E2B_API_KEY")
        e2b_sandbox = await asyncio.to_thread(
            E2BSandboxSDK.connect,
            sandbox_id=id,
            api_key=api_key
        )
        return cls(e2b_sandbox)
