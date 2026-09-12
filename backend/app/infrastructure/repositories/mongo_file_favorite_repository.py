from typing import Set
from datetime import datetime, UTC
from app.infrastructure.models.documents import FileFavoriteDocument
import logging

logger = logging.getLogger(__name__)


class MongoFileFavoriteRepository:
    """MongoDB implementation of FileFavoriteRepository (library file favorites)."""

    async def set_favorite(self, user_id: str, file_id: str, is_favorite: bool) -> None:
        if is_favorite:
            existing = await FileFavoriteDocument.find_one(
                FileFavoriteDocument.user_id == user_id,
                FileFavoriteDocument.file_id == file_id,
            )
            if not existing:
                await FileFavoriteDocument(user_id=user_id, file_id=file_id).save()
        else:
            favorites = FileFavoriteDocument.find(
                FileFavoriteDocument.user_id == user_id,
                FileFavoriteDocument.file_id == file_id,
            )
            async for favorite in favorites:
                await favorite.delete()

    async def list_favorite_file_ids(self, user_id: str) -> Set[str]:
        favorites = FileFavoriteDocument.find(
            FileFavoriteDocument.user_id == user_id
        )
        result: Set[str] = set()
        async for favorite in favorites:
            result.add(favorite.file_id)
        return result
