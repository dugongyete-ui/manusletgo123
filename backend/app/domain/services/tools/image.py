import httpx
from typing import Optional
from app.domain.external.sandbox import Sandbox
from app.domain.services.tools.base import BaseToolkit
from app.domain.models.tool_result import ToolResult
from app.domain.models.image import ImageSearchResults, ImageSearchResultItem, ImageGenerationResult
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
    async def image_generate(
        self,
        prompt: str,
        size: Optional[str] = "1024x1024",
        model: Optional[str] = "flux-schnell",
    ) -> ToolResult:
        """Generate an image using AI based on a text description.
        Use this when the user asks to create, draw, generate, or make an image/picture/illustration.
        Returns a URL to the generated image.

        Args:
            prompt: Detailed description of the image to generate, in English for best results
            size: (Optional) Image size, e.g. "1024x1024", "1792x1024", "1024x1792". Default is "1024x1024"
            model: (Optional) Model to use for generation. Default is "flux-schnell"
        """
        from app.core.config import get_settings
        settings = get_settings()

        api_key = settings.vision_api_key or settings.api_key
        api_base = settings.vision_api_base or settings.api_base or "https://api.openai.com/v1"
        use_model = model or "flux-schnell"

        try:
            async with httpx.AsyncClient(timeout=90, verify=False) as client:
                response = await client.post(
                    f"{api_base.rstrip('/')}/images/generations",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": use_model,
                        "prompt": prompt,
                        "n": 1,
                        "size": size or "1024x1024",
                    },
                )
                response.raise_for_status()
                data = response.json()

            images = data.get("data", [])
            if not images:
                return ToolResult(success=False, message="No image was returned by the API.")

            img = images[0]
            url = img.get("url", "")
            revised_prompt = img.get("revised_prompt")

            if not url:
                return ToolResult(success=False, message="API returned an empty image URL.")

            return ToolResult(
                success=True,
                message=f"Image generated successfully with model '{use_model}'.",
                data=ImageGenerationResult(
                    prompt=prompt,
                    url=url,
                    model=use_model,
                    revised_prompt=revised_prompt,
                ),
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(success=False, message=f"API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            return ToolResult(success=False, message=f"Image generation failed: {str(e)}")

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
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, verify=False) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                image_data = response.content

            result = await self.sandbox.file_upload(image_data, file_path)
            if result and result.success:
                import base64
                import mimetypes
                ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
                mime = mimetypes.types_map.get(f".{ext}", "image/jpeg")
                data_url = f"data:{mime};base64,{base64.b64encode(image_data).decode()}"
                return ToolResult(
                    success=True,
                    message=f"Image saved to {file_path} ({len(image_data)} bytes)",
                    data={"file_path": file_path, "size": len(image_data), "data_url": data_url, "source_url": url},
                )
            return ToolResult(
                success=False,
                message=f"Failed to save image to sandbox: {getattr(result, 'message', 'unknown error')}",
            )
        except Exception as e:
            return ToolResult(success=False, message=str(e))
