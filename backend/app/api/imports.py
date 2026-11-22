"""Phase 2 API: Desktop .drawio import (preview -> commit) (docs/04 section 1).

The uploaded file is parsed safely, mapped to a semantic graph candidate and
diffed against the current version. Commit stores the uploaded XML verbatim
(the XML is the source of graphical truth) plus the derived graph.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.api.envelope import ok

from app.importer.model_map import diff_graphs, graph_from_cells
from app.importer.xml_parser import parse_drawio_bytes
from app.schemas.api import ApiException, ErrorCode
from app.storage.versions import utc_now

router = APIRouter(prefix="/api/v1")

# In-memory preview tokens (single-process MVP). TTL keeps the store bounded.
_PREVIEW_TTL_SECONDS = 900


class PreviewTokenStore:
    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    def put(self, payload: Dict[str, Any]) -> str:
        self._cleanup()
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
        import time

        now = time.time()
        stale = [t for t, v in self._store.items() if now - v.get("_ts", now) > _PREVIEW_TTL_SECONDS]
        for t in stale:
            self._store.pop(t, None)


def _register_token_store(app) -> None:
    if not hasattr(app.state, "import_tokens"):
        app.state.import_tokens = PreviewTokenStore()


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
    data = await file.read()
    parsed = parse_drawio_bytes(
        data,
        max_cells=state.settings.max_xml_cells,
        max_bytes=state.settings.max_drawio_upload_bytes,
    )
    result = graph_from_cells(parsed, diagram_id, diagram.name, diagram.diagram_type)
    current_graph = state.version_store.read_graph(diagram_id, diagram.current_version)
    from app.schemas.graph import GraphDocument

    old_doc = GraphDocument.model_validate(current_graph)
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
    diff = diff_graphs(old_doc, result.graph)
    warnings = []
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
        "uploadedXml": data,
        "unknownCellCount": len(result.unknown_cells),
        "_ts": __import__("time").time(),
    })
    return ok(request, {
        "diff": diff.to_payload(),
        "warnings": warnings,
        "unknownCellCount": len(result.unknown_cells),
        "cellMappingChanges": result.mapping_changes,
        "requiresConfirmation": requires_confirmation,
        "confirmationToken": token,
        "candidateVersion": diagram.current_version + 1,
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
    # Normalize compressed Desktop saves to uncompressed single-page XML so
    # subsequent AI patch application is never refused on encoding grounds.
    # The semantic content is identical; only the page encoding changes.
    from app.importer.xml_parser import normalize_to_uncompressed

    stored_xml, was_compressed = normalize_to_uncompressed(
        entry["uploadedXml"],
        max_cells=state.settings.max_xml_cells,
        max_bytes=state.settings.max_drawio_upload_bytes,
    )
    row = state.version_store.commit_new_version(
        diagram_id=diagram_id,
        diagram_name=diagram.name,
        diagram_type=diagram.diagram_type,
        graph=entry["graph"],
        drawio_bytes=stored_xml,
        origin="desktop_import",
        expected_base_version=base_version,
        manifest_extra={
            "cellMapping": entry["cellMapping"],
            "unknownCellCount": entry["unknownCellCount"],
            "normalizedFromCompressed": was_compressed,
        },
    )
    return ok(request, {
        "version": {
            "version": row.version, "parentVersion": row.parent_version, "origin": row.origin,
            "sha256": row.sha256, "createdAt": row.created_at,
        },
        "preservedUnknownCells": entry["unknownCellCount"],
        "normalizedFromCompressed": was_compressed,
    })
