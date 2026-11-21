"""Shared fixtures: app factory with temp storage + real renderer CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, REPO_ROOT
from app.main import create_app


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        llm_enabled=False,
        llm_provider="mock",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
        llm_timeout_seconds=5,
        llm_max_retries=1,
        renderer_cli=REPO_ROOT / "renderer/dist/src/cli.js",
        renderer_timeout_seconds=60,
        renderer_output_limit_bytes=8 * 1024 * 1024,
        storage_root=tmp_path / "storage",
        database_path=tmp_path / "storage/studio.db",
        icons_dir=REPO_ROOT / "renderer/assets/icons",
        max_drawio_upload_bytes=10 * 1024 * 1024,
        max_xml_cells=5000,
        frontend_dist=tmp_path / "frontend-dist-missing",
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def app_client(tmp_path):
    app = create_app(make_settings(tmp_path))
    return TestClient(app), app


def load_fixture(name: str) -> dict:
    return json.loads((REPO_ROOT / "fixtures" / name).read_text(encoding="utf-8"))
