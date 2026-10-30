"""FastAPI app, middleware, CORS, and lifespan hooks."""

from contextlib import asynccontextmanager
from pathlib import Path

import docker
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router
from utils import config
from utils.logger import get_logger

log = get_logger(__name__)


def _docker_status() -> tuple[bool, str | None]:
    """Ping the Docker daemon. Returns (ok, error)."""
    if config.DEMO_MODE:
        return True, None
    try:
        docker.from_env().ping()
        return True, None
    except Exception as e:
        return False, str(e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify Docker daemon is reachable and create data directories."""
    ok, error = _docker_status()
    log.info("docker_daemon_ok") if ok else log.warning("docker_daemon_unavailable", error=error)
    if not config.API_KEY and config.CORS_ORIGINS == ["*"]:
        log.warning("api_open_to_any_origin",
                    hint="Set API_KEY and a concrete CORS_ORIGINS list before exposing this service")
    Path(config.DATA_DIR, "jobs").mkdir(parents=True, exist_ok=True)
    Path(config.DATA_DIR, "artifacts").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AutoRepro", version="1.0.0", lifespan=lifespan)

# No cross-origin access by default: the bundled UI is served from this same origin.
# Set CORS_ORIGINS to a comma-separated list to allow a separately hosted frontend.
if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

app.include_router(router)

# Mount static files (CSS, JS)
static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Return one readable message instead of Pydantic's raw error array.

    Clients rendered the array as "[object Object]".
    """
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", ()) if part != "body") or "request"
    return JSONResponse(
        status_code=422,
        content={"detail": {
            "code": "VALIDATION_ERROR",
            "message": f"{field}: {first.get('msg', 'is invalid')}",
            "errors": [{"field": ".".join(str(p) for p in e.get("loc", ()) if p != "body"),
                        "message": e.get("msg", "")} for e in exc.errors()],
        }},
    )


@app.get("/")
async def root():
    """Serve the frontend SPA."""
    return FileResponse(str(static_dir / "index.html"))


@app.get("/health")
async def health():
    """Health check — reports whether the sandbox runtime is actually reachable."""
    ok, error = _docker_status()
    body = {
        "status": "ok" if ok else "degraded",
        "docker": "ok" if ok else "unavailable",
        "demo_mode": config.DEMO_MODE,
        "llm_provider": config.LLM_PROVIDER,
    }
    if error:
        body["docker_error"] = error
    return JSONResponse(status_code=200 if ok else 503, content=body)
