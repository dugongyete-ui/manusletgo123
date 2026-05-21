from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
import logging

from app.application.services.file_service import FileService
from app.application.errors.exceptions import NotFoundError
from app.interfaces.dependencies import get_file_service, get_current_user, get_optional_current_user, verify_signature
from app.domain.models.user import User
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.file import FileInfoResponse, FileExtractResponse
from app.interfaces.schemas.resource import AccessTokenRequest, SignedUrlResponse
from app.domain.services import file_extractor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

@router.post("", response_model=APIResponse[FileInfoResponse])
async def upload_file(
    file: UploadFile = File(...),
    file_service: FileService = Depends(get_file_service),
    current_user: User = Depends(get_current_user)
) -> APIResponse[FileInfoResponse]:
    """Upload file"""
    # Upload file
    result = await file_service.upload_file(
        file_data=file.file,
        filename=file.filename,
        user_id=current_user.id,
        content_type=file.content_type
    )
    
    return APIResponse.success(await FileInfoResponse.from_file_info(result))

@router.get("/{file_id}")
async def download_file_with_signature(
    file_id: str,
    file_service: FileService = Depends(get_file_service),
    signature: str = Depends(verify_signature),
):
    """Download file with optional access token"""
    
    # Download file (authentication is handled by middleware for non-token requests)
    try:
        file_data, file_info = await file_service.download_file(file_id)
    except FileNotFoundError:
        raise NotFoundError("File not found")
    except PermissionError:
        raise NotFoundError("File not found")  # Don't reveal if file exists but user has no access
    
    # Encode filename properly for Content-Disposition header
    # Use URL encoding for non-ASCII characters to ensure latin-1 compatibility
    import urllib.parse
    encoded_filename = urllib.parse.quote(file_info.filename, safe='')
    
    headers = {
        'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'
    }
    
    return StreamingResponse(
        file_data,
        media_type=file_info.content_type or 'application/octet-stream',
        headers=headers
    )

@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    file_service: FileService = Depends(get_file_service),
    current_user: User = Depends(get_optional_current_user)
):
    """Download file with optional access token"""
    
    # Download file (authentication is handled by middleware for non-token requests)
    try:
        file_data, file_info = await file_service.download_file(file_id, current_user.id if current_user else None)
    except FileNotFoundError:
        raise NotFoundError("File not found")
    except PermissionError:
        raise NotFoundError("File not found")  # Don't reveal if file exists but user has no access
    
    # Encode filename properly for Content-Disposition header
    # Use URL encoding for non-ASCII characters to ensure latin-1 compatibility
    import urllib.parse
    encoded_filename = urllib.parse.quote(file_info.filename, safe='')
    
    headers = {
        'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'
    }
    
    return StreamingResponse(
        file_data,
        media_type=file_info.content_type or 'application/octet-stream',
        headers=headers
    )

@router.post("/{file_id}/extract", response_model=APIResponse[FileExtractResponse])
async def extract_file_text(
    file_id: str,
    file_service: FileService = Depends(get_file_service),
    current_user: User = Depends(get_current_user),
) -> APIResponse[FileExtractResponse]:
    """Extract text content from an uploaded file (PDF, PPTX, DOCX, XLSX, CSV, TXT…).

    The extraction runs entirely on the backend server — no sandbox or AI shell
    commands are needed.  The resulting text can be fed directly into an AI prompt.
    """
    file_info = await file_service.get_file_info(file_id, current_user.id)
    if not file_info:
        raise NotFoundError("File not found")

    if not file_extractor.is_extractable(file_info.filename, file_info.content_type):
        raise NotFoundError(
            f"File type not supported for text extraction: {file_info.content_type}"
        )

    try:
        file_data, _ = await file_service.download_file(file_id, current_user.id)
        raw = file_data.read()
    except Exception as e:
        logger.error(f"Could not download file {file_id} for extraction: {e}")
        raise NotFoundError("File not found")

    try:
        extracted = file_extractor.extract_text(raw, file_info.filename, file_info.content_type)
    except Exception as e:
        logger.error(f"Text extraction failed for {file_id}: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Extraction failed: {str(e)}")

    return APIResponse.success(
        FileExtractResponse(
            file_id=file_id,
            filename=file_info.filename,
            content_type=file_info.content_type,
            extracted_text=extracted,
            char_count=len(extracted),
        )
    )


@router.delete("/{file_id}", response_model=APIResponse[None])
async def delete_file(
    file_id: str,
    file_service: FileService = Depends(get_file_service),
    current_user: User = Depends(get_current_user)
) -> APIResponse[None]:
    """Delete file"""
    success = await file_service.delete_file(file_id, current_user.id)
    if not success:
        raise NotFoundError("File not found")
    return APIResponse.success()

@router.get("/{file_id}/info", response_model=APIResponse[FileInfoResponse])
async def get_file_info(
    file_id: str,
    file_service: FileService = Depends(get_file_service),
    current_user: User = Depends(get_current_user)
) -> APIResponse[FileInfoResponse]:
    """Get file information"""
    file_info = await file_service.get_file_info(file_id, current_user.id)
    if not file_info:
        raise NotFoundError("File not found")
    
    return APIResponse.success(await FileInfoResponse.from_file_info(file_info))


@router.post("/{file_id}/signed-url", response_model=APIResponse[SignedUrlResponse])
async def create_file_signed_url(
    file_id: str,
    request_data: AccessTokenRequest,
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
) -> APIResponse[SignedUrlResponse]:
    """Generate signed URL for file download
    
    This endpoint creates a signed URL that allows temporary access to download
    a specific file without requiring authentication headers.
    """
    
    try:
        # Create signed URL using file service
        signed_url = await file_service.create_signed_url(
            file_id=file_id,
            user_id=current_user.id,
            expire_minutes=request_data.expire_minutes
        )
        
        return APIResponse.success(SignedUrlResponse(
            signed_url=signed_url,
            expires_in=request_data.expire_minutes * 60,
        ))
    except FileNotFoundError:
        raise NotFoundError("File not found")
