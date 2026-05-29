import httpx
from typing import Optional
from app.domain.external.sandbox import Sandbox
from app.domain.services.tools.base import BaseToolkit
from app.domain.models.tool_result import ToolResult
from app.domain.models.image import ImageSearchResults, ImageSearchResultItem
from langchain.tools import tool


class ImageToolkit(BaseToolkit):
    """Image tool class, providing image search and download functions"""

    name: str = "image"

    def __init__(self, sandbox: Sandbox):
        super().__init__()
        self.sandbox = sandbox

    @tool(parse_docstring=True)
    async def image_search_web(
        self,
        query: str,
        count: Optional[int] = 5,
    ) -> ToolResult:
        """Search for images on the web and return a list of image URLs.
        Use this when the user asks to find, search, or look up photos/images/logos.
        After searching, use image_download to save a specific image.

        Args:
            query: Image search query, e.g. "github logo", "cute cat photo", "sunset beach"
            count: (Optional) Number of image results to return, default 5, max 10
        """
        max_results = min(int(count or 5), 10)

        # Try Tavily first (more reliable, already integrated)
        items = await self._search_tavily(query, max_results)

        # Fall back to DuckDuckGo if Tavily unavailable or returned nothing
        if not items:
            items = await self._search_duckduckgo(query, max_results)

        if items:
            return ToolResult(
                success=True,
                message=f"Found {len(items)} images for '{query}'",
                data=ImageSearchResults(query=query, results=items),
            )
        return ToolResult(
            success=False,
            message=f"No images found for '{query}'. Try a different search query.",
            data=ImageSearchResults(query=query, results=[]),
        )

    async def _search_tavily(self, query: str, max_results: int) -> list:
        """Search images via Tavily (include_images=True). Returns list of ImageSearchResultItem."""
        try:
            from app.core.config import get_settings
            settings = get_settings()
            if not settings.tavily_api_key:
                return []

            from tavily import AsyncTavilyClient
            client = AsyncTavilyClient(api_key=settings.tavily_api_key)
            response = await client.search(
                query=query,
                max_results=max_results,
                include_images=True,
                search_depth="basic",
            )

            images = response.get("images", [])
            items = []
            for img in images:
                if isinstance(img, str):
                    url = img
                    title = ""
                    description = ""
                elif isinstance(img, dict):
                    url = img.get("url", "")
                    title = img.get("description", "")
                    description = img.get("description", "")
                else:
                    continue
                if url:
                    items.append(ImageSearchResultItem(
                        title=title or query,
                        url=url,
                        thumbnail=url,
                        source=url,
                        width=None,
                        height=None,
                    ))
            return items[:max_results]
        except Exception:
            return []

    async def _search_duckduckgo(self, query: str, max_results: int) -> list:
        """Search images via DuckDuckGo as fallback."""
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.images(query, max_results=max_results))
            return [
                ImageSearchResultItem(
                    title=r.get("title", ""),
                    url=r.get("image", ""),
                    thumbnail=r.get("thumbnail", ""),
                    source=r.get("url", ""),
                    width=r.get("width"),
                    height=r.get("height"),
                )
                for r in raw
                if r.get("image")
            ]
        except Exception:
            return []

    @tool(parse_docstring=True)
    async def image_download(
        self,
        url: str,
        file_path: str,
    ) -> ToolResult:
        """Download an image from a URL and save it to the sandbox filesystem.
        Use this after image_search_web to save a specific image so it can be sent to the user.
        Supports JPG, PNG, GIF, WebP, SVG and other image formats.

        Args:
            url: Direct URL of the image to download (from image_search_web results)
            file_path: Absolute path where the image should be saved, e.g. /home/runner/github_logo.png
        """
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                image_data = response.content

            result = await self.sandbox.file_upload(image_data, file_path)
            if result and result.success:
                return ToolResult(
                    success=True,
                    message=f"Image saved to {file_path} ({len(image_data)} bytes)",
                    data={"file_path": file_path, "size": len(image_data)},
                )
            return ToolResult(
                success=False,
                message=f"Failed to save image to sandbox: {getattr(result, 'message', 'unknown error')}",
            )
        except Exception as e:
            return ToolResult(success=False, message=str(e))
