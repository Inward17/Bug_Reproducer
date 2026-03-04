"""Central configuration — all settings read from .env file and environment variables."""

import os
from dotenv import load_dotenv

# Load .env file (does NOT override existing env vars, so CLI still works as override)
load_dotenv()

LLM_PROVIDER: str            = os.getenv("LLM_PROVIDER", "ollama")
LLM_MODEL: str               = os.getenv("LLM_MODEL", "qwen2.5-coder:3b")
MAX_ATTEMPTS: int            = int(os.getenv("MAX_ATTEMPTS", "5"))
SANDBOX_TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "60"))
SANDBOX_MEMORY_MB: int       = int(os.getenv("SANDBOX_MEMORY_MB", "512"))
SANDBOX_IMAGE: str           = os.getenv("SANDBOX_IMAGE", "autorepro-sandbox:latest")
DATA_DIR: str                = os.getenv("DATA_DIR", "./data")
LOG_LEVEL: str               = os.getenv("LOG_LEVEL", "INFO")
DEMO_MODE: bool              = os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")

