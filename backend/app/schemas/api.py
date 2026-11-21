"""API envelope schemas: docs/04 section 1.

Success responses carry `requestId` and `data`; errors carry
`error.code`, `error.message` and optional `error.details`.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ApiError(BaseModel):
    requestId: str
    error: ApiErrorBody


class ApiSuccess(BaseModel):
    requestId: str
    data: Dict[str, Any]


def new_request_id() -> str:
    return uuid.uuid4().hex


class ErrorCode:
    SCHEMA_INVALID = "SCHEMA_INVALID"
    GRAPH_INVALID_REFERENCE = "GRAPH_INVALID_REFERENCE"
    GRAPH_DUPLICATE_ID = "GRAPH_DUPLICATE_ID"
    GRAPH_GROUP_CYCLE = "GRAPH_GROUP_CYCLE"
    GRAPH_PHYSICAL_EDGE_DIRECTION = "GRAPH_PHYSICAL_EDGE_DIRECTION"
    AMBIGUOUS_RELATION = "AMBIGUOUS_RELATION"
    DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED = "DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED"
    LAYOUT_CONFLICT = "LAYOUT_CONFLICT"
    DRAWIO_PARSE_FAILED = "DRAWIO_PARSE_FAILED"
    DRAWIO_UNSUPPORTED_CONTENT = "DRAWIO_UNSUPPORTED_CONTENT"
    DRAWIO_UPLOAD_TOO_LARGE = "DRAWIO_UPLOAD_TOO_LARGE"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    DIAGRAM_NOT_FOUND = "DIAGRAM_NOT_FOUND"
    DIAGRAM_ALREADY_EXISTS = "DIAGRAM_ALREADY_EXISTS"
    VERSION_NOT_FOUND = "VERSION_NOT_FOUND"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_INVALID_OUTPUT = "LLM_INVALID_OUTPUT"
    RENDERER_UNAVAILABLE = "RENDERER_UNAVAILABLE"
    RENDERER_FAILED = "RENDERER_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


HTTP_STATUS_BY_CODE = {
    ErrorCode.SCHEMA_INVALID: 400,
    ErrorCode.GRAPH_INVALID_REFERENCE: 400,
    ErrorCode.GRAPH_DUPLICATE_ID: 400,
    ErrorCode.GRAPH_GROUP_CYCLE: 400,
    ErrorCode.GRAPH_PHYSICAL_EDGE_DIRECTION: 400,
    ErrorCode.AMBIGUOUS_RELATION: 422,
    ErrorCode.DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED: 422,
    ErrorCode.LAYOUT_CONFLICT: 409,
    ErrorCode.DRAWIO_PARSE_FAILED: 400,
    ErrorCode.DRAWIO_UNSUPPORTED_CONTENT: 415,
    ErrorCode.DRAWIO_UPLOAD_TOO_LARGE: 413,
    ErrorCode.VERSION_CONFLICT: 409,
    ErrorCode.DIAGRAM_NOT_FOUND: 404,
    ErrorCode.DIAGRAM_ALREADY_EXISTS: 409,
    ErrorCode.VERSION_NOT_FOUND: 404,
    ErrorCode.LLM_UNAVAILABLE: 503,
    ErrorCode.LLM_INVALID_OUTPUT: 502,
    ErrorCode.RENDERER_UNAVAILABLE: 503,
    ErrorCode.RENDERER_FAILED: 502,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ApiException(Exception):
    """Domain error carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    @property
    def status_code(self) -> int:
        return HTTP_STATUS_BY_CODE.get(self.code, 500)


class VersionInfo(BaseModel):
    version: int
    parentVersion: Optional[int] = None
    origin: str
    sha256: str
    createdAt: str
    graphPath: str
    drawioPath: str


class DiagramSummary(BaseModel):
    id: str
    name: str
    diagramType: str
    currentVersion: int
    createdAt: str
    updatedAt: str


class VersionListEntry(BaseModel):
    version: int
    parentVersion: Optional[int]
    origin: str
    sha256: str
    createdAt: str
    hasPatch: bool = False
