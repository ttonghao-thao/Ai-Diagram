"""Phase 2 API: Desktop .drawio import (preview -> commit) (docs/04 section 1).

The uploaded file is parsed safely, mapped to a semantic graph candidate and
diffed against the current version. Commit stores the uploaded XML verbatim
(the XML is the source of graphical truth) plus the derived graph.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.envelope import ok

from app.importer.model_map import diff_graphs, graph_from_cells
from app.importer.visual import cell_mapping, visual_state
from app.importer.xml_parser import normalize_to_uncompressed, parse_drawio_bytes
from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import GraphDocument
from app.services.diagram_changes import require_quality
from app.services.materials import catalog_version, normalize_devices
from app.storage.versions import utc_now

router = APIRouter(prefix="/api/v1")

# In-memory preview tokens (single-process MVP). TTL keeps the store bounded.
_PREVIEW_TTL_SECONDS = 900


class PreviewTokenStore:
    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    def put(self, payload: Dict[str, Any]) -> str:
        self._cleanup()
        while len(self._store) >= 12:
            self._store.pop(next(iter(self._store)))
        token = uuid.uuid4().hex
        self._store[token] = {"createdAt": utc_now(), **payload}
        return token

    def take(self, token: str, diagram_id: str) -> Optional[Dict[str, Any]]:
        """One-time consumption: the token is removed after a successful read."""
        self._cleanup()
        entry = self._store.get(token)
        if entry is None or entry["diagramId"] != diagram_id:
            return None
        del self._store[token]
        return entry

    def peek(self, token: str) -> Optional[Dict[str, Any]]:
        self._cleanup()
        return self._store.get(token)

    def _cleanup(self) -> None:
        now = time.time()
        # Entries without a usable timestamp expire immediately rather than
        # living forever (the old `v.get("_ts", now)` default made the delta 0).
        stale = [
            t for t, v in self._store.items()
            if now - float(v.get("_ts") or 0.0) > _PREVIEW_TTL_SECONDS
        ]
        for t in stale:
            self._store.pop(t, None)


UPLOAD_CHUNK_BYTES = 256 * 1024


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Stream the upload in chunks and refuse as soon as the limit is hit, so
    an oversized body never sits fully in memory (docs/04 section 6)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ApiException(
                ErrorCode.DRAWIO_UPLOAD_TOO_LARGE,
                f"upload exceeds the {max_bytes}-byte limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _register_token_store(app) -> None:
    if not hasattr(app.state, "import_tokens"):
        app.state.import_tokens = PreviewTokenStore()


@router.post("/diagrams/{diagram_id}/import/preview")
@router.post("/diagrams/{diagram_id}/import/drawio")
async def import_preview(
    request: Request,
    diagram_id: str,
    file: UploadFile = File(...),
    baseVersion: int = Form(...),
) -> Dict[str, Any]:
    state = request.app.state
    _register_token_store(request.app)
    diagram = state.db.get_diagram(diagram_id)
    if diagram is None:
        raise ApiException(ErrorCode.DIAGRAM_NOT_FOUND, f"diagram '{diagram_id}' does not exist")
    if baseVersion != diagram.current_version:
        raise ApiException(
            ErrorCode.VERSION_CONFLICT,
            f"baseVersion {baseVersion} does not match current version {diagram.current_version}",
            {"currentVersion": diagram.current_version, "baseVersion": baseVersion},
        )
    data = await _read_upload_limited(file, state.settings.max_drawio_upload_bytes)
    parsed = parse_drawio_bytes(
        data,
        max_cells=state.settings.max_xml_cells,
        max_bytes=state.settings.max_drawio_upload_bytes,
    )
    store = state.version_store
    current_graph = store.read_graph(diagram_id, diagram.current_version)
    old_doc = GraphDocument.model_validate(current_graph)
    old_mapping = cell_mapping(old_doc, store.read_manifest(diagram_id, diagram.current_version).get("cellMapping"))
    result = graph_from_cells(parsed, diagram_id, diagram.name, diagram.diagram_type, old_mapping)
    old_xml, _ = store.read_drawio(diagram_id, diagram.current_version)
    old_parsed = parse_drawio_bytes(old_xml, max_cells=state.settings.max_xml_cells)
    result.graph.schemaVersion = "1.1"
    result.graph.appearance = old_doc.appearance
    result.graph.metadata = dict(old_doc.metadata)
    result.graph.warnings = list(old_doc.warnings)
    result.graph.layout.direction = old_doc.layout.direction
    result.graph.layout.preserveManualPositions = old_doc.layout.preserveManualPositions
    valid_nodes = {node.id for node in result.graph.nodes}
    valid_groups = {group.id for group in result.graph.groups}
    if old_doc.layout.centerNodeId in valid_nodes:
        result.graph.layout.centerNodeId = old_doc.layout.centerNodeId
    def valid_rule(rule):
        ids = {rule.source, rule.target} if rule.type == "relativePosition" else set(rule.nodes)
        return ids <= (valid_nodes | valid_groups if rule.type == "preservePosition" else valid_nodes)
    if old_doc.layout.constraints is not None:
        result.graph.layout.constraints = [rule for rule in old_doc.layout.constraints if valid_rule(rule)]
    # Semantic-only fields (properties/origin/manualLocked) are not stored in
    # draw.io XML; carry them over from the current graph so a Desktop edit
    # cycle never drops e.g. explicit IP annotations (docs/02 section 8).
    old_nodes_by_id = {n.id: n for n in old_doc.nodes}
    for node in result.graph.nodes:
        prev = old_nodes_by_id.get(node.id)
        if prev is None:
            continue
        merged_props = dict(prev.properties or {})
        for key, val in (node.properties or {}).items():
            if key not in merged_props or merged_props[key] in (None, ""):
                merged_props[key] = val
        node.properties = merged_props
        node.origin = prev.origin
        node.manualLocked = prev.manualLocked
    old_groups_by_id = {g.id: g for g in old_doc.groups}
    for group in result.graph.groups:
        prev = old_groups_by_id.get(group.id)
        if prev is not None:
            group.manualLocked = prev.manualLocked
    prior_edges = {edge.id: edge for edge in old_doc.edges}
    for edge in result.graph.edges:
        prev = prior_edges.get(edge.id)
        if prev is None:
            continue
        before = old_parsed.cell_by_id.get(old_mapping.get(edge.id))
        after = parsed.cell_by_id.get(result.graph_id_to_cell.get(edge.id))
        edge.sourcePort, edge.targetPort = prev.sourcePort, prev.targetPort
        edge.style = dict(prev.style)
        if before and after and (before.value or "") == (after.value or ""):
            edge.label = prev.label
        if before and after and (before.geometry.points if before.geometry else []) == (after.geometry.points if after.geometry else []):
            edge.waypoints = prev.waypoints
    normalize_devices(result.graph)
    diff = diff_graphs(old_doc, result.graph)
    visual = visual_state(result.graph, parsed, result.graph_id_to_cell,
                          previous=store.read_artifact(diagram_id, diagram.current_version, "visual-state"),
                          prior_xml=old_parsed, prior_mapping=old_mapping, desktop=True, diff=diff)
    visual["catalogVersion"] = catalog_version()
    stored_xml, was_compressed = normalize_to_uncompressed(
        data, max_cells=state.settings.max_xml_cells, max_bytes=state.settings.max_drawio_upload_bytes,
    )
    report = await run_in_threadpool(
        state.renderer.quality, result.graph.model_dump(exclude_none=True), stored_xml,
        state.materials.renderer_context(result.graph) | {
            "cellMapping": result.graph_id_to_cell,
            "manualStyleIds": [id_ for id_, mark in visual["nodes"].items() if mark["manualStyleLocked"]],
        },
    )
    require_quality(report)
    warnings = []
    if len(result.graph.layout.constraints or ()) < len(old_doc.layout.constraints or ()):
        warnings.append({"code": "LAYOUT_CONSTRAINTS_PRUNED", "message": "已移除引用被删除对象的布局约束",
                         "requiresConfirmation": False})
    if result.unknown_cells:
        warnings.append({
            "code": "UNKNOWN_CELLS_PRESERVED",
            "message": f"发现 {len(result.unknown_cells)} 个未映射对象；它们将被原样保留，不参与语义修改",
            "relatedIds": [u["cellId"] for u in result.unknown_cells][:20],
            "requiresConfirmation": False,
        })
    if result.mapping_changes:
        warnings.append({
            "code": "CELL_ID_REMAPPED",
            "message": f"{len(result.mapping_changes)} 个对象的 cell id 与 graph id 不一致，已按导入映射记录",
            "requiresConfirmation": False,
        })
    if diff.summary()["total"] == 0 and not result.unknown_cells:
        warnings.append({
            "code": "NO_CHANGES_DETECTED",
            "message": "上传文件与当前版本一致，未检测到差异",
            "requiresConfirmation": False,
        })
    requires_confirmation = diff.summary()["nodeRemoved"] > 0 or diff.summary()["edgeRemoved"] > 0 or \
        bool(diff.summary()["edgeReconnected"])
    token = state.import_tokens.put({
        "diagramId": diagram_id,
        "baseVersion": baseVersion,
        "graph": result.graph.model_dump(exclude_none=True),
        "cellMapping": result.graph_id_to_cell,
        "storedXml": stored_xml,
        "sourceXml": data if was_compressed else None,
        "wasCompressed": was_compressed,
        "quality": report,
        "visual": visual,
        "unknownCellCount": len(result.unknown_cells),
        "_ts": time.time(),
    })
    return ok(request, {
        "diff": diff.to_payload(),
        "warnings": warnings,
        "unknownCellCount": len(result.unknown_cells),
        "cellMappingChanges": result.mapping_changes,
        "requiresConfirmation": requires_confirmation,
        "confirmationToken": token,
        "candidateVersion": diagram.current_version + 1,
        "quality": report,
    })


@router.post("/diagrams/{diagram_id}/import/commit")
async def import_commit(request: Request, diagram_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    state = request.app.state
    _register_token_store(request.app)
    token = body.get("confirmationToken")
    base_version = body.get("baseVersion")
    if not token or not isinstance(base_version, int):
        raise ApiException(ErrorCode.SCHEMA_INVALID, "confirmationToken and integer baseVersion are required")
    entry = state.import_tokens.take(token, diagram_id)
    if entry is None:
        raise ApiException(
            ErrorCode.VERSION_CONFLICT,
            "unknown or expired confirmationToken; run the import preview again",
        )
    diagram = state.db.get_diagram(diagram_id)
    if diagram is None or diagram.current_version != base_version or entry["baseVersion"] != base_version:
        raise ApiException(
            ErrorCode.VERSION_CONFLICT,
            f"diagram moved since preview (current v{diagram.current_version if diagram else 'gone'})",
        )
    row = state.version_store.commit_new_version(
        diagram_id=diagram_id,
        diagram_name=diagram.name,
        diagram_type=diagram.diagram_type,
        graph=entry["graph"],
        drawio_bytes=entry["storedXml"],
        origin="desktop_import",
        expected_base_version=base_version,
        visual_state=entry["visual"],
        quality=entry["quality"],
        source_drawio=entry["sourceXml"],
        manifest_extra={
            "cellMapping": entry["cellMapping"],
            "unknownCellCount": entry["unknownCellCount"],
            "normalizedFromCompressed": entry["wasCompressed"],
        },
    )
    return ok(request, {
        "version": {
            "version": row.version, "parentVersion": row.parent_version, "origin": row.origin,
            "sha256": row.sha256, "createdAt": row.created_at,
        },
        "preservedUnknownCells": entry["unknownCellCount"],
        "quality": entry["quality"],
        "normalizedFromCompressed": entry["wasCompressed"],
    })
