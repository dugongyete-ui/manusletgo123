from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import logging
import asyncio
import os

from app.core.config import get_settings
from app.infrastructure.storage.mongodb import get_mongodb
from app.infrastructure.storage.redis import get_redis
from app.interfaces.dependencies import get_agent_service
from app.interfaces.api.routes import router
from app.infrastructure.logging import setup_logging
from app.interfaces.errors.exception_handlers import register_exception_handlers
from app.infrastructure.models.documents import AgentDocument, SessionDocument, UserDocument
from beanie import init_beanie

# Initialize logging system
setup_logging()
logger = logging.getLogger(__name__)

# Load configuration
settings = get_settings()

# Startup readiness flag — True once MongoDB + Redis are fully initialized
_app_ready = False


async def _init_databases() -> None:
    """Initialize MongoDB/Beanie and Redis in the background so uvicorn
    starts accepting requests (and healthchecks) immediately."""
    global _app_ready
    try:
        logger.info("Background DB init — connecting to MongoDB…")
        await get_mongodb().initialize()
        await init_beanie(
            database=get_mongodb().client[settings.mongodb_database],
            document_models=[AgentDocument, SessionDocument, UserDocument],
        )
        logger.info("Successfully initialized Beanie")
    except Exception as exc:
        logger.error(f"MongoDB/Beanie initialization failed: {exc}")
        return

    try:
        await get_redis().initialize()
        logger.info("Successfully initialized Redis")
    except Exception as exc:
        logger.error(f"Redis initialization failed: {exc} — continuing without Redis")

    _app_ready = True
    logger.info("Application fully ready — all services initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup - Dzeck AI Agent initializing")

    # Kick off DB init as a background task so the server starts immediately
    # and Replit's healthcheck can reach /health right away.
    asyncio.create_task(_init_databases())

    try:
        yield
    finally:
        logger.info("Application shutdown - Dzeck AI Agent terminating")
        await get_mongodb().shutdown()
        await get_redis().shutdown()

        logger.info("Cleaning up AgentService instance")
        try:
            await asyncio.wait_for(get_agent_service().shutdown(), timeout=30.0)
            logger.info("AgentService shutdown completed successfully")
        except asyncio.TimeoutError:
            logger.warning("AgentService shutdown timed out after 30 seconds")
        except Exception as exc:
            logger.error(f"Error during AgentService cleanup: {str(exc)}")


app = FastAPI(title="Dzeck AI Agent", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register exception handlers
register_exception_handlers(app)

# Register routes
app.include_router(router, prefix="/api/v1")


# Health check — returns 200 immediately; reports readiness in body
@app.get("/health")
async def health_check():
    """Lightweight health endpoint — always 200 so deployment healthchecks pass."""
    return {"status": "ok", "ready": _app_ready}


# Serve compiled Vue frontend in production (when frontend/dist exists)
_frontend_dist = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "../../frontend/dist")
)

if os.path.exists(_frontend_dist):
    _assets_dir = os.path.join(_frontend_dist, "assets")
    if os.path.exists(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        target = os.path.join(_frontend_dist, full_path)
        if full_path and os.path.isfile(target):
            return FileResponse(target)
        return FileResponse(os.path.join(_frontend_dist, "index.html"))
else:
    from fastapi.responses import JSONResponse

    @app.get("/", include_in_schema=False)
    async def health_root():
        return JSONResponse({"status": "ok", "ready": _app_ready, "msg": "Dzeck backend running — frontend not built yet"})
