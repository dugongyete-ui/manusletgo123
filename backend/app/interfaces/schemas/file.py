from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from app.domain.models.file import FileInfo


class FileExtractResponse(BaseModel):
    """Response containing extracted text from a file"""
    file_id: str
    filename: str
    content_type: Optional[str]
    extracted_text: str
    char_count: int


class FileViewRequest(BaseModel):
    """File view request schema"""
    file: str


class FileViewResponse(BaseModel):
    """File view response schema"""
    content: str
    file: str


class FileInfoResponse(BaseModel):
    """File info response schema"""
    file_id: str
    filename: str
    content_type: Optional[str]
    size: Optional[int] = None
    upload_date: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]]
    file_url: Optional[str]
    # Semantic group for UI listing (slides/tables/docs/media/code/archives/
    # other) — set by the files endpoints, absent on older payloads.
    category: Optional[str] = None

    @staticmethod
    async def from_file_info(file_info: FileInfo) -> "FileInfoResponse":
        from app.interfaces.dependencies import get_file_service
        file_service = get_file_service()
        return FileInfoResponse(
            file_id=file_info.file_id,
            filename=file_info.filename,
            content_type=file_info.content_type,
            size=file_info.size,
            upload_date=file_info.upload_date,
            metadata=file_info.metadata,
            file_url=await file_service.create_signed_url(file_info.file_id)
        )
