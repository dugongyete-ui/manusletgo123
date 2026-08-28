from typing import Optional, List
from datetime import datetime, UTC
from app.domain.models.project import Project
from app.infrastructure.models.documents import ProjectDocument
import logging

logger = logging.getLogger(__name__)


class MongoProjectRepository:
    """MongoDB implementation of ProjectRepository"""

    async def save(self, project: Project) -> None:
        mongo_project = await ProjectDocument.find_one(
            ProjectDocument.project_id == project.id
        )
        if not mongo_project:
            mongo_project = ProjectDocument.from_domain(project)
            await mongo_project.save()
            return
        mongo_project.update_from_domain(project)
        await mongo_project.save()

    async def find_by_id(self, project_id: str) -> Optional[Project]:
        mongo_project = await ProjectDocument.find_one(
            ProjectDocument.project_id == project_id
        )
        return mongo_project.to_domain() if mongo_project else None

    async def find_by_id_and_user_id(self, project_id: str, user_id: str) -> Optional[Project]:
        mongo_project = await ProjectDocument.find_one(
            ProjectDocument.project_id == project_id,
            ProjectDocument.user_id == user_id,
        )
        return mongo_project.to_domain() if mongo_project else None

    async def find_by_user_id(self, user_id: str) -> List[Project]:
        mongo_projects = await ProjectDocument.find(
            ProjectDocument.user_id == user_id
        ).sort([
            ("is_pinned", -1),
            ("sort_order", 1),
            ("updated_at", -1),
        ]).to_list()
        return [p.to_domain() for p in mongo_projects]

    async def delete(self, project_id: str) -> None:
        mongo_project = await ProjectDocument.find_one(
            ProjectDocument.project_id == project_id
        )
        if mongo_project:
            await mongo_project.delete()

    async def update_pin(self, project_id: str, is_pinned: bool) -> None:
        await ProjectDocument.find_one(
            ProjectDocument.project_id == project_id
        ).update(
            {"$set": {"is_pinned": is_pinned, "updated_at": datetime.now(UTC)}}
        )

    async def update_name(self, project_id: str, name: str, instruction: Optional[str] = None) -> None:
        update: dict = {"$set": {"name": name, "updated_at": datetime.now(UTC)}}
        if instruction is not None:
            update["$set"]["instruction"] = instruction
        await ProjectDocument.find_one(
            ProjectDocument.project_id == project_id
        ).update(update)
