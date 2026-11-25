"""Application settings loaded from environment variables (deploy/env.example).

Secrets are injected via environment only; nothing is logged verbatim
(docs/04 section 6). Paths are resolved relative to the repository root so
both `uvicorn app.main:app` (from backend/) and Docker work.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw if raw else default


@dataclass
class Settings:
    llm_enabled: bool = field(default_factory=lambda: _env_bool("LLM_ENABLED", False))
    llm_provider: str = field(default_factory=lambda: _env_str("LLM_PROVIDER", "mock").lower())
    llm_base_url: str = field(default_factory=lambda: _env_str("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: _env_str("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: _env_str("LLM_MODEL", ""))
    llm_timeout_seconds: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT_SECONDS", 60))
    llm_reasoning_effort: str = field(default_factory=lambda: _env_str("LLM_REASONING_EFFORT", ""))
    llm_private_endpoint: bool = field(default_factory=lambda: _env_bool("LLM_PRIVATE_ENDPOINT", False))
    llm_max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 2))

    renderer_cli: Path = field(
        default_factory=lambda: Path(_env_str("RENDERER_CLI", str(REPO_ROOT / "renderer/dist/src/cli.js")))
    )
    renderer_timeout_seconds: int = field(default_factory=lambda: _env_int("RENDERER_TIMEOUT_SECONDS", 60))
    renderer_output_limit_bytes: int = field(default_factory=lambda: _env_int("RENDERER_OUTPUT_LIMIT_BYTES", 8 * 1024 * 1024))

    storage_root: Path = field(
        default_factory=lambda: Path(_env_str("STORAGE_ROOT", str(REPO_ROOT / "storage")))
    )
    database_path: Path = field(
        default_factory=lambda: Path(_env_str("DATABASE_PATH", str(REPO_ROOT / "storage/studio.db")))
    )
    icons_dir: Path = field(
        default_factory=lambda: Path(_env_str("ICONS_DIR", str(REPO_ROOT / "renderer/assets/icons")))
    )

    max_drawio_upload_bytes: int = field(default_factory=lambda: _env_int("MAX_DRAWIO_UPLOAD_BYTES", 10 * 1024 * 1024))
    max_xml_cells: int = field(default_factory=lambda: _env_int("MAX_XML_CELLS", 5000))

    frontend_dist: Path = field(
        default_factory=lambda: Path(_env_str("FRONTEND_DIST", str(REPO_ROOT / "frontend/dist")))
    )

    def ensure_dirs(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
