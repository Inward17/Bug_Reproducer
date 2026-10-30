"""Central configuration — all settings read from .env file and environment variables."""

import os

from dotenv import load_dotenv

# Load .env file (does NOT override existing env vars, so CLI still works as override)
load_dotenv()


def _flag(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


LLM_PROVIDER: str            = os.getenv("LLM_PROVIDER", "ollama")
LLM_MODEL: str               = os.getenv("LLM_MODEL", "qwen2.5-coder:3b")
BEDROCK_MODEL: str           = os.getenv("BEDROCK_MODEL", LLM_MODEL)
ANTHROPIC_MODEL: str         = os.getenv("ANTHROPIC_MODEL", LLM_MODEL)
GOOGLE_MODEL: str            = os.getenv("GOOGLE_MODEL", LLM_MODEL)
OLLAMA_MODEL: str            = os.getenv("OLLAMA_MODEL", LLM_MODEL)
MAX_ATTEMPTS: int            = int(os.getenv("MAX_ATTEMPTS", "5"))
SANDBOX_TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "60"))
SANDBOX_MEMORY_MB: int       = int(os.getenv("SANDBOX_MEMORY_MB", "512"))
SANDBOX_IMAGE: str           = os.getenv("SANDBOX_IMAGE", "autorepro-sandbox:latest")
SANDBOX_PIDS_LIMIT: int      = int(os.getenv("SANDBOX_PIDS_LIMIT", "256"))
# Read-only rootfs + tmpfs for the sandbox. Off by default because it depends on the
# Chromium build's scratch paths; turn it on and run the demo once to confirm.
SANDBOX_READ_ONLY: bool      = _flag("SANDBOX_READ_ONLY")
DATA_DIR: str                = os.getenv("DATA_DIR", "./data")
LOG_LEVEL: str               = os.getenv("LOG_LEVEL", "INFO")
DEMO_MODE: bool              = _flag("DEMO_MODE")

# ── Access control ──────────────────────────────────────────────────────────
# Empty API_KEY leaves the API open, which is only safe on localhost. Set it (and a
# real CORS origin list) before exposing the service.
API_KEY: str                 = os.getenv("API_KEY", "").strip()
CORS_ORIGINS: list[str]      = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

# Allow targets on private/loopback addresses. True suits local development and the
# bundled demo server; set it to false for any deployment reachable from outside.
# Link-local and cloud metadata addresses are refused either way.
ALLOW_PRIVATE_TARGETS: bool  = _flag("ALLOW_PRIVATE_TARGETS", "true")

# Cap on sandbox containers running at once, so a burst of jobs can't exhaust the host.
MAX_CONCURRENT_SANDBOXES: int = int(os.getenv("MAX_CONCURRENT_SANDBOXES", "4"))
