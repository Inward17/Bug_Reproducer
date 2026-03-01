"""FastAPI app, middleware, CORS, and lifespan hooks."""

import docker
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api.routes import router
from utils import config
from utils.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify Docker daemon is reachable and create data directories."""
    try:
        docker.from_env().ping()
        log.info("docker_daemon_ok")
    except Exception as e:
        log.warning("docker_daemon_unavailable", error=str(e))
    Path(config.DATA_DIR, "jobs").mkdir(parents=True, exist_ok=True)
    Path(config.DATA_DIR, "artifacts").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AutoRepro", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

# Mount static files (CSS, JS)
static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    """Serve the frontend SPA."""
    return FileResponse(str(static_dir / "index.html"))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
