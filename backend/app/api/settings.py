"""Manage shared workbench LLM settings without returning credentials."""
from fastapi import APIRouter, Request, Response

from app.api.envelope import ok
from app.llm.settings import LlmSettingsUpdate

router = APIRouter(prefix="/api/v1/settings/llm")


@router.get("")
def get_llm_settings(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return ok(request, request.app.state.llm_settings.current().public_fields())


@router.patch("")
def update_llm_settings(request: Request, response: Response, body: LlmSettingsUpdate) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return ok(request, request.app.state.llm_settings.update(body).public_fields())
