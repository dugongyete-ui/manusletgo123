from pydantic import BaseModel, Field
from typing import List, Optional


class ImageSearchResultItem(BaseModel):
    title: str = Field(default="", description="Image title")
    url: str = Field(..., description="Direct image URL")
    thumbnail: str = Field(default="", description="Thumbnail URL")
    source: str = Field(default="", description="Source website URL")
    width: Optional[int] = None
    height: Optional[int] = None


class ImageSearchResults(BaseModel):
    query: str = Field(..., description="Original search query")
    results: List[ImageSearchResultItem] = Field(default_factory=list)


class ImageGenerationResult(BaseModel):
    prompt: str = Field(..., description="The prompt used to generate the image")
    url: str = Field(..., description="URL of the generated image")
    model: str = Field(default="flux-schnell", description="Model used for generation")
    revised_prompt: Optional[str] = Field(default=None, description="Revised prompt if provided by API")
