"""Phase 2 API: GraphPatch preview/apply (docs/04 section 1-2).

preview  -> patch validation + in-memory application + impact/warnings/layout
apply    -> one-time confirmationToken + baseVersion re-check + directed XML
            edit + atomic version commit (origin=ai_patch)
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.envelope import ok

from app.api.imports import PreviewTokenStore
from app.graph.patch import preview_patch, validate_patch_payload
from app.services.diagram_changes import prepare_change
from app.schemas.api import ApiException, ErrorCode

router = APIRouter(prefix="/api/v1")


class PatchPreviewRequest(BaseModel):
    instruction: Optional[str] = Field(default=None, max_length=2000)
    patch: Optional[Dict[str, Any]] = None


class PatchApplyRequest(BaseModel):
    confirmationToken: str
    baseVersion: int = Field(ge=1)


def _register_token_store(app) -> None:
    if not hasattr(app.state, "patch_tokens"):
        app.state.patch_tokens = PreviewTokenStore()


def _current_doc(request: Request, diagram_id: str):
    state = request.app.state
    diagram = state.db.get_diagram(diagram_id)
    if diagram is None:
        raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
    from app.schemas.graph import GraphDocument

    graph = state.version_store.read_graph(diagram_id, diagram.current_version)
    return diagram, GraphDocument.model_validate(graph)


@router.post("/diagrams/{diagram_id}/patch/preview")
async def patch_preview(request: Request, diagram_id: str, body: PatchPreviewRequest) -> Dict[str, Any]:
    state = request.app.state
    _register_token_store(request.app)
    diagram, doc = _current_doc(request, diagram_id)
    started = time.time()

    if body.patch is not None:
        patch = validate_patch_payload(body.patch)
        provider = "client"
    elif body.instruction:
        adapter = state.llm_adapter_factory(state.settings)
        provider = adapter.name
        try:
            patch = await adapter.propose_patch(body.instruction, doc, diagram.current_version)
        except ApiException as exc:
            state.db.record_ai_job(
                request_type="propose_patch", provider=provider, model=state.settings.llm_model or None,
                status="error", error_code=exc.code, duration_ms=int((time.time() - started) * 1000),
                diagram_id=diagram_id, version=diagram.current_version,
            )
            raise
        patch = validate_patch_payload(patch)
    else:
        raise ApiException(ErrorCode.SCHEMA_INVALID, "provide either 'instruction' or 'patch'")

    if patch.get("baseVersion") != diagram.current_version:
        raise ApiException(
            ErrorCode.VERSION_CONFLICT,
            f"patch baseVersion {patch.get('baseVersion')} does not match current version {diagram.current_version}",
            {"currentVersion": diagram.current_version},
        )

    preview = preview_patch(doc, patch)
    layout_changes = [op for op in patch["operations"] if op["op"] == "update_layout"]
    scope = "global" if any((op.get("changes") or {}).keys() & {"algorithm", "direction", "centerNodeId"}
                            for op in layout_changes) else "local"
    prepared = await run_in_threadpool(
        prepare_change, state, diagram_id, diagram.current_version, doc, preview.graph,
        patch["operations"], scope=scope, preserve_positions=preview.graph.layout.preserveManualPositions if layout_changes else True,
    )
    original = {item.id: item for item in [*doc.nodes, *doc.groups]}
    preview.layoutPlan.addedNodes = [{"id": node.id, "geometry": node.geometry.model_dump()}
                                     for node in prepared.graph.nodes if node.id not in original and node.geometry]
    preview.layoutPlan.movedNodes = [
        {"id": item.id, "geometry": item.geometry.model_dump()}
        for item in [*prepared.graph.nodes, *prepared.graph.groups] if item.geometry and item.id in original
        and original[item.id].geometry and (item.geometry.x, item.geometry.y) != (
            original[item.id].geometry.x, original[item.id].geometry.y
        )
    ]
    preview.layoutPlan.strategy = "global-reflow" if scope == "global" else "anchor-insert"
    layout_plan = {
        "strategy": preview.layoutPlan.strategy,
        "addedNodes": preview.layoutPlan.addedNodes,
        "movedNodes": preview.layoutPlan.movedNodes,
    }

    if body.instruction:
        state.db.record_ai_job(
            request_type="propose_patch", provider=provider, model=state.settings.llm_model or None,
            status="ok", error_code=None, duration_ms=int((time.time() - started) * 1000),
            diagram_id=diagram_id, version=diagram.current_version,
        )

    token = state.patch_tokens.put({
        "diagramId": diagram_id,
        "baseVersion": diagram.current_version,
        "patch": patch,
        "prepared": prepared,
        "layoutPlan": layout_plan,
        "impactedIds": preview.impactedIds,
        "_ts": time.time(),
    })
    return ok(request, {
        "patch": patch,
        "impactedIds": preview.impactedIds,
        "requiresConfirmation": preview.requiresConfirmation,
        "confirmationReasons": preview.confirmationReasons,
        "warnings": [
            {"code": w.code, "message": w.message, "relatedIds": w.relatedIds,
             "requiresConfirmation": w.requiresConfirmation}
            for w in preview.warnings
        ] + prepared.renderer_warnings,
        "layoutPlan": layout_plan,
        "diff": prepared.diff,
        "quality": prepared.quality,
        "confirmationToken": token,
    })


@router.post("/diagrams/{diagram_id}/patch/apply")
async def patch_apply(request: Request, diagram_id: str, body: PatchApplyRequest) -> Dict[str, Any]:
    state = request.app.state
    _register_token_store(request.app)
    diagram, _ = _current_doc(request, diagram_id)

    entry = state.patch_tokens.take(body.confirmationToken, diagram_id)
    if entry is None:
        raise ApiException(
            ErrorCode.VERSION_CONFLICT,
            "unknown or expired confirmationToken; run the patch preview again",
        )
    if entry["baseVersion"] != body.baseVersion or diagram.current_version != body.baseVersion:
        raise ApiException(
            ErrorCode.VERSION_CONFLICT,
            f"diagram moved since preview (current v{diagram.current_version})",
            {"currentVersion": diagram.current_version, "previewedBaseVersion": entry["baseVersion"]},
        )

    patch = entry["patch"]
    prepared = entry["prepared"]
    row = state.version_store.commit_new_version(
        diagram_id=diagram_id,
        diagram_name=diagram.name,
        diagram_type=diagram.diagram_type,
        graph=prepared.graph.model_dump(exclude_none=True),
        drawio_bytes=prepared.xml,
        origin="ai_patch",
        patch=patch,
        expected_base_version=body.baseVersion,
        manifest_extra={"cellMapping": prepared.mapping},
        visual_state=prepared.visual,
        quality=prepared.quality,
    )
    return ok(request, {
        "version": {
            "version": row.version, "parentVersion": row.parent_version, "origin": row.origin,
            "sha256": row.sha256, "createdAt": row.created_at,
        },
        "impactedIds": entry["impactedIds"],
        "layoutPlan": entry["layoutPlan"],
        "quality": prepared.quality,
    })
