"""Shared API envelope helper (docs/04 section 1)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Request


def ok(request: Request, data: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap route payloads into the requestId/data envelope."""
    return {"requestId": getattr(request.state, "requestId", "") or "-", "data": data}
