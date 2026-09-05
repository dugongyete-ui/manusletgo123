from fastapi import APIRouter
from . import session_routes, file_routes, auth_routes, config_routes, project_routes, library_routes
from . import knowledge_routes, scheduled_task_routes, agent_profile_routes, community_routes

def create_api_router() -> APIRouter:
    """Create and configure the main API router"""
    api_router = APIRouter()

    @api_router.api_route("/health", methods=["GET", "HEAD"], tags=["health"])
    async def health_check():
        """Lightweight health endpoint for uptime monitoring (e.g., UptimeRobot)."""
        return {"status": "ok"}

    # Include all sub-routers
    api_router.include_router(session_routes.router)
    api_router.include_router(file_routes.router)
    api_router.include_router(auth_routes.router)
    api_router.include_router(config_routes.router)
    api_router.include_router(project_routes.router)
    api_router.include_router(library_routes.router)
    api_router.include_router(knowledge_routes.router)
    api_router.include_router(scheduled_task_routes.router)
    api_router.include_router(agent_profile_routes.router)
    api_router.include_router(community_routes.router)

    return api_router

# Create the main router instance
router = create_api_router()