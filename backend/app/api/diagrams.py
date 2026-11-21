"""Phase 1 API: diagrams, versions, validation, layout, export, parse (docs/04 section 1)."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, ValidationError

from app.api.envelope import ok
from app.graph.errors import GraphValidationError
from app.graph.validate import collect_graph_issues, validate_graph
from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import GraphDocument
from app.storage.versions import utc_now
from app.importer.xml_parser import parse_drawio_bytes
from app.importer.model_map import graph_from_cells

router = APIRouter(prefix="/api/v1")


def parse_and_validate(raw: Dict[str, Any]) -> tuple[GraphDocument, list]:
    """Schema validation (Pydantic) + semantic validation, with API error codes.

    A structurally invalid graph never reaches storage or the renderer.
    """
    try:
        doc = GraphDocument.model_validate(raw)
    except ValidationError as exc:
        raise ApiException(
            ErrorCode.SCHEMA_INVALID,
            "graph failed schema validation",
            {"errors": [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10]]},
        )
    try:
        warnings = validate_graph(doc)
    except GraphValidationError as exc:
        first = exc.issues[0]
        raise ApiException(
            first.code,
            f"graph failed semantic validation: {first.message}",
            {"errors": [str(issue) for issue in exc.issues]},
        )
    return doc, warnings




class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    diagramType: str = Field(pattern="^(network_topology|business_architecture)$")


class ValidateRequest(BaseModel):
    graph: Optional[Dict[str, Any]] = None


class LayoutRequest(BaseModel):
    baseVersion: int = Field(ge=1)



def reconcile_geometry(graph_dict: Dict[str, Any], rendered_xml: bytes) -> Dict[str, Any]:
    """Sync the stored graph's geometry with the actual rendered positions.

    The renderer (ELK) decides final coordinates; without this step the stored
    graph would keep user-supplied placeholders and every re-import would look
    like a full move. Cell mapping is the stable n_/g_ prefix scheme.
    """
    parsed = parse_drawio_bytes(rendered_xml)
    result = graph_from_cells(parsed, graph_dict["diagramId"], graph_dict["name"], graph_dict["diagramType"])
    node_geo = {n.id: n.geometry for n in result.graph.nodes}
    group_geo = {g.id: g.geometry for g in result.graph.groups}
    for node in graph_dict["nodes"]:
        geo = node_geo.get(node["id"])
        if geo is not None:
            node["geometry"] = geo.model_dump()
    for group in graph_dict["groups"]:
        geo = group_geo.get(group["id"])
        if geo is not None:
            group["geometry"] = geo.model_dump()
    return graph_dict



def _get_state(request: Request):
    return request.app.state


def _graph_issues_payload(doc: GraphDocument) -> Dict[str, Any]:
    errors, warnings = collect_graph_issues(doc)
    return {
        "ok": not errors,
        "errors": [{"code": e.code, "message": e.message, "relatedIds": e.relatedIds} for e in errors],
        "warnings": [
            {"code": w.code, "message": w.message, "relatedIds": w.relatedIds, "severity": w.severity}
            for w in warnings
        ],
        # Warnings carried by the document itself (e.g. produced by the LLM
        # adapter); kept separate from validator warnings but always returned.
        "documentWarnings": [
            {
                "code": w.code, "message": w.message, "relatedIds": w.relatedIds or [],
                "requiresConfirmation": w.requiresConfirmation,
            }
            for w in doc.warnings
        ],
    }


@router.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    state = _get_state(request)
    return ok(request, {
        "status": "ok",
        "rendererAvailable": state.renderer.available(),
        "llm": {
            "enabled": state.settings.llm_enabled,
            "provider": state.settings.llm_provider if state.settings.llm_enabled else None,
        },
        "time": utc_now(),
    })


@router.get("/diagrams")
async def list_diagrams(request: Request) -> Dict[str, Any]:
    state = _get_state(request)
    items = [
        {
            "id": d.id, "name": d.name, "diagramType": d.diagram_type,
            "currentVersion": d.current_version, "createdAt": d.created_at, "updatedAt": d.updated_at,
        }
        for d in state.db.list_diagrams()
    ]
    return ok(request, {"diagrams": items})


@router.post("/diagrams")
async def create_diagram(request: Request, graph: Dict[str, Any]) -> Dict[str, Any]:
    """Create a diagram + initial version from a GraphDocument JSON body."""
    state = _get_state(request)
    started = time.time()
    doc, warnings = parse_and_validate(graph)
    if state.db.get_diagram(doc.diagramId) is not None:
        raise ApiException(
            ErrorCode.DIAGRAM_ALREADY_EXISTS,
            f"diagram '{doc.diagramId}' already exists; use a new diagramId or call /layout for a new version",
        )
    render = state.renderer.render(graph)
    state.db.create_diagram(doc.diagramId, doc.name, doc.diagramType, utc_now())
    graph_stored = reconcile_geometry(doc.model_dump(exclude_none=True), render.drawio_bytes)
    row = state.version_store.commit_new_version(
        diagram_id=doc.diagramId,
        diagram_name=doc.name,
        diagram_type=doc.diagramType,
        graph=graph_stored,
        drawio_bytes=render.drawio_bytes,
        origin="initial",
    )
    state.db.record_ai_job(
        request_type="create_diagram", provider="renderer", model=None, status="ok",
        error_code=None, duration_ms=int((time.time() - started) * 1000),
        diagram_id=doc.diagramId, version=row.version, created_at=row.created_at,
    )
    return ok(request, {
        "diagram": {
            "id": doc.diagramId, "name": doc.name, "diagramType": doc.diagramType,
            "currentVersion": row.version,
        },
        "version": {
            "version": row.version, "origin": row.origin, "sha256": row.sha256, "createdAt": row.created_at,
        },
        "warnings": [
            {"code": w.code, "message": w.message, "relatedIds": w.relatedIds, "severity": w.severity}
            for w in warnings
        ] + [
            {"code": w.code, "message": w.message, "relatedIds": w.relatedIds or [], "severity": "warning"}
            for w in doc.warnings
        ] + [{"severity": "warning", "code": i["code"], "message": i["message"], "relatedIds": []} for i in render.warnings],
    })


@router.get("/diagrams/{diagram_id}")
async def get_diagram(request: Request, diagram_id: str, version: Optional[int] = None) -> Dict[str, Any]:
    state = _get_state(request)
    diagram = state.db.get_diagram(diagram_id)
    if diagram is None:
        raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
    v = version if version is not None else diagram.current_version
    if v <= 0:
        raise ApiException(ErrorCode.VERSION_NOT_FOUND, f"diagram '{diagram_id}' has no versions yet")
    graph = state.version_store.read_graph(diagram_id, v)
    row = state.db.get_version(diagram_id, v)
    return ok(request, {
        "diagram": {
            "id": diagram.id, "name": diagram.name, "diagramType": diagram.diagram_type,
            "currentVersion": diagram.current_version, "createdAt": diagram.created_at, "updatedAt": diagram.updated_at,
        },
        "version": {
            "version": row.version, "parentVersion": row.parent_version, "origin": row.origin,
            "sha256": row.sha256, "createdAt": row.created_at,
        },
        "graph": graph,
    })


@router.post("/diagrams/{diagram_id}/validate")
async def validate_diagram(request: Request, diagram_id: str, body: ValidateRequest) -> Dict[str, Any]:
    state = _get_state(request)
    if diagram_id != "-" and state.db.get_diagram(diagram_id) is None:
        raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
    if body.graph is not None:
        doc, _ = parse_and_validate(body.graph)
    else:
        graph = state.version_store.read_graph(diagram_id, state.db.get_diagram(diagram_id).current_version)
        doc, _ = parse_and_validate(graph)
    return ok(request, _graph_issues_payload(doc))


@router.post("/diagrams/{diagram_id}/layout")
async def layout_diagram(request: Request, diagram_id: str, body: LayoutRequest) -> Dict[str, Any]:
    """Re-run the ELK layout on the latest graph and store it as a new version."""
    state = _get_state(request)
    diagram = state.db.get_diagram(diagram_id)
    if diagram is None:
        raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
    graph = state.version_store.read_graph(diagram_id, diagram.current_version)
    doc, warnings = parse_and_validate(graph)
    render = state.renderer.render(graph)
    graph_stored = reconcile_geometry(doc.model_dump(exclude_none=True), render.drawio_bytes)
    row = state.version_store.commit_new_version(
        diagram_id=diagram_id,
        diagram_name=diagram.name,
        diagram_type=diagram.diagram_type,
        graph=graph_stored,
        drawio_bytes=render.drawio_bytes,
        origin="layout",
        expected_base_version=body.baseVersion,
    )
    return ok(request, {
        "version": {
            "version": row.version, "parentVersion": row.parent_version, "origin": row.origin,
            "sha256": row.sha256, "createdAt": row.created_at,
        },
        "warnings": [
            {"code": w.code, "message": w.message, "relatedIds": w.relatedIds, "severity": w.severity}
            for w in warnings
        ],
    })


@router.get("/diagrams/{diagram_id}/versions")
async def list_versions(request: Request, diagram_id: str) -> Dict[str, Any]:
    state = _get_state(request)
    diagram = state.db.get_diagram(diagram_id)
    if diagram is None:
        raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
    versions = [
        {
            "version": v.version, "parentVersion": v.parent_version, "origin": v.origin,
            "sha256": v.sha256, "createdAt": v.created_at, "hasPatch": v.patch_path is not None,
        }
        for v in state.db.list_versions(diagram_id)
    ]
    return ok(request, {"diagramId": diagram_id, "currentVersion": diagram.current_version, "versions": versions})


@router.get("/diagrams/{diagram_id}/export/drawio")
async def export_drawio(request: Request, diagram_id: str, version: Optional[int] = None) -> Response:
    state = _get_state(request)
    diagram = state.db.get_diagram(diagram_id)
    if diagram is None:
        raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
    v = version if version is not None else diagram.current_version
    if v <= 0:
        raise ApiException(ErrorCode.VERSION_NOT_FOUND, f"diagram '{diagram_id}' has no versions yet")
    content, sha256 = state.version_store.read_drawio(diagram_id, v)
    filename = f"{diagram_id}_v{v:04d}.drawio"
    return Response(
        content=content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-SHA256": sha256,
            "X-Diagram-Version": str(v),
        },
    )


@router.post("/diagrams/parse")
async def parse_text(request: Request, body: ParseRequest) -> Dict[str, Any]:
    """Text -> GraphDocument draft via the configured LLM; nothing is stored."""
    state = _get_state(request)
    started = time.time()
    adapter = state.llm_adapter_factory(state.settings)
    provider = adapter.name
    try:
        doc = await adapter.parse_graph(body.text, body.diagramType)
    except ApiException as exc:
        state.db.record_ai_job(
            request_type="parse_graph", provider=provider, model=state.settings.llm_model or None,
            status="error", error_code=exc.code,
            duration_ms=int((time.time() - started) * 1000),
        )
        raise
    state.db.record_ai_job(
        request_type="parse_graph", provider=provider, model=state.settings.llm_model or None,
        status="ok", error_code=None,
        duration_ms=int((time.time() - started) * 1000),
    )
    issues = _graph_issues_payload(doc)
    return ok(request, {
        "graph": doc.model_dump(exclude_none=True),
        "schemaValid": issues["ok"],
        "semanticErrors": issues["errors"],
        "semanticWarnings": issues["warnings"],
        "documentWarnings": issues["documentWarnings"],
    })
