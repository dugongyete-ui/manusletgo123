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
        """Initialize image tool class

        Args:
            sandbox: Sandbox service
        """
        super().__init__()
        self.sandbox = sandbox

    @tool(parse_docstring=True)
    async def image_search_web(
        self,
        query: str,
        count: Optional[int] = 5,
    ) -> ToolResult:
        """Search for images on the web and return a list of image URLs.
        Use this when the user asks to find, search, or look up photos/images.
        After searching, use image_download to save a specific image.

        Args:
            query: Image search query, e.g. "github logo", "cute cat photo", "sunset beach"
            count: (Optional) Number of image results to return, default 5, max 10
        """
        try:
            from duckduckgo_search import DDGS
            max_results = min(int(count or 5), 10)
            with DDGS() as ddgs:
                raw = list(ddgs.images(query, max_results=max_results))
            items = [
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
            return ToolResult(
                success=True,
                message=f"Found {len(items)} images for '{query}'",
                data=ImageSearchResults(query=query, results=items),
            )
        except Exception as e:
            return ToolResult(success=False, message=str(e))

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
            file_path: Absolute path where the image should be saved, e.g. /home/user/github_logo.png
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
