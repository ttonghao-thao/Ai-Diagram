"""GraphPatch engine (Phase 2, docs/02 section 6, docs/05 2.2).

preview -> user confirmation -> apply:
  - preview applies operations to an in-memory copy and reports impacted ids,
    warnings, confirmation requirements and a layout plan; storage is untouched;
  - apply re-runs the preview against the CURRENT stored graph (so a stale
    patch cannot apply), then commits atomically with baseVersion checking;
  - destructive operations (remove_*, update_edge endpoint changes) require
    explicit confirmation flags in the patch;
  - manualLocked objects are never moved; impossible insertions raise
    LAYOUT_CONFLICT instead of silently re-laying out the graph.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema
from pydantic import ValidationError

from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import Appearance, Geometry, GraphDocument, GraphEdge, GraphGroup, GraphNode, LayoutSpec, Point

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
_PATCH_SCHEMA = json.loads((_CONTRACTS / "patch.schema.json").read_text(encoding="utf-8"))
_PATCH_VALIDATOR = jsonschema.Draft202012Validator(_PATCH_SCHEMA)

UPDATABLE_NODE_KEYS = {"label", "style", "geometry", "manualLocked", "properties", "groupId"}
UPDATABLE_GROUP_KEYS = {"label", "style", "geometry", "manualLocked", "parentId"}
UPDATABLE_EDGE_KEYS = {"label", "sourcePort", "targetPort", "waypoints", "style"}
EDGE_ENDPOINT_KEYS = {"source", "target", "kind", "direction"}  # reconnect class


def validate_patch_payload(raw: Any) -> Dict[str, Any]:
    """Schema validation against contracts/patch.schema.json + basic rules."""
    if not isinstance(raw, dict):
        raise ApiException(ErrorCode.SCHEMA_INVALID, "patch must be a JSON object")
    errors = sorted(
        _PATCH_VALIDATOR.iter_errors(raw), key=lambda e: list(e.absolute_path)
    )
    if errors:
        raise ApiException(
            ErrorCode.SCHEMA_INVALID,
            "patch failed schema validation (contracts/patch.schema.json)",
            {"errors": [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors[:10]]},
        )
    return raw


@dataclass
class PatchWarning:
    code: str
    message: str
    requiresConfirmation: bool = False
    relatedIds: List[str] = field(default_factory=list)


@dataclass
class LayoutPlan:
    addedNodes: List[Dict[str, Any]] = field(default_factory=list)
    movedNodes: List[Dict[str, Any]] = field(default_factory=list)  # always empty: no auto-move
    strategy: str = "anchor-insert"


@dataclass
class PatchPreview:
    graph: GraphDocument
    impactedIds: List[str]
    warnings: List[PatchWarning]
    requiresConfirmation: bool
    confirmationReasons: List[str]
    layoutPlan: LayoutPlan


def _working_copy(doc: GraphDocument) -> GraphDocument:
    return GraphDocument.model_validate(doc.model_dump())


def _validated_geometry(raw: Any) -> Geometry:
    try:
        return Geometry.model_validate(raw)
    except ValidationError as exc:
        raise ApiException(ErrorCode.SCHEMA_INVALID, "invalid geometry in patch changes",
                           {"errors": [str(e["msg"]) for e in exc.errors()[:5]]})


def _validated_waypoints(raw: Any) -> List[Point]:
    try:
        return [Point.model_validate(p) for p in (raw or [])]
    except ValidationError as exc:
        raise ApiException(ErrorCode.SCHEMA_INVALID, "invalid waypoints in patch changes",
                           {"errors": [str(e["msg"]) for e in exc.errors()[:5]]})


def preview_patch(doc: GraphDocument, patch: Dict[str, Any]) -> PatchPreview:
    """Apply the patch to an in-memory copy; raises ApiException on any rule violation."""
    working = _working_copy(doc)
    warnings: List[PatchWarning] = []
    impacted: List[str] = []
    reasons: List[str] = []
    layout_plan = LayoutPlan()

    node_ids = {n.id for n in working.nodes}
    group_ids = {g.id for g in working.groups}
    edge_ids = {e.id for e in working.edges}

    def require(confirm_flag: bool, reason: str) -> None:
        if not confirm_flag:
            raise ApiException(
                ErrorCode.DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED,
                reason,
                {"confirmationReasons": reasons + [reason]},
            )
        reasons.append(reason)

    for op in patch["operations"]:
        op_name, op_id = op["op"], op["id"]
        value = op.get("value") or {}
        changes = op.get("changes") or {}
        confirm = bool(op.get("requiresConfirmation"))
        cascade = bool(op.get("cascade"))

        if op_name.endswith("_node"):
            if op_name == "add_node":
                if op_id in node_ids or op_id in group_ids or op_id in edge_ids:
                    raise ApiException(ErrorCode.GRAPH_DUPLICATE_ID, f"add_node: id '{op_id}' already exists", {"relatedIds": [op_id]})
                if value.get("id") not in (None, op_id):
                    raise ApiException(ErrorCode.SCHEMA_INVALID, f"add_node: value.id must equal op id '{op_id}'", {"relatedIds": [op_id]})
                node_data = dict(value)
                node_data["id"] = op_id
                node_data.setdefault("origin", "ai")
                try:
                    node = GraphNode.model_validate(node_data)
                except ValidationError as exc:
                    raise ApiException(ErrorCode.SCHEMA_INVALID, f"add_node '{op_id}': invalid node value",
                                       {"errors": [str(e["msg"]) for e in exc.errors()[:5]]})
                working.nodes.append(node)
                node_ids.add(op_id)
                impacted.append(op_id)
            elif op_name == "update_node":
                node = next((n for n in working.nodes if n.id == op_id), None)
                if node is None:
                    raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                       f"update_node: node '{op_id}' does not exist", [op_id])
                bad_keys = set(changes) - UPDATABLE_NODE_KEYS
                if bad_keys:
                    raise ApiException(ErrorCode.SCHEMA_INVALID,
                                       f"update_node: fields {sorted(bad_keys)} cannot be modified", [op_id])
                if "geometry" in changes:
                    if node.manualLocked:
                        raise ApiException(
                            ErrorCode.LAYOUT_CONFLICT,
                            f"node '{op_id}' is manualLocked; its position will not be changed",
                            {"relatedIds": [op_id]},
                        )
                    node.geometry = _validated_geometry(changes["geometry"])
                    layout_plan.movedNodes.append({"id": op_id, "geometry": changes["geometry"]})
                if "groupId" in changes:
                    if changes["groupId"] is not None and changes["groupId"] not in group_ids:
                        raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                           f"update_node: groupId '{changes['groupId']}' does not exist", [op_id])
                    node.groupId = changes["groupId"]
                if "label" in changes:
                    node.label = changes["label"]
                if "style" in changes:
                    node.style = {**(node.style or {}), **changes["style"]}
                if "properties" in changes:
                    node.properties = {**(node.properties or {}), **changes["properties"]}
                if "manualLocked" in changes:
                    node.manualLocked = bool(changes["manualLocked"])
                impacted.append(op_id)
            elif op_name == "remove_node":
                node = next((n for n in working.nodes if n.id == op_id), None)
                if node is None:
                    raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                       f"remove_node: node '{op_id}' does not exist", [op_id])
                attached = [e.id for e in working.edges if e.source == op_id or e.target == op_id]
                if attached:
                    require(
                        confirm or cascade,
                        f"remove_node '{op_id}' is connected to {len(attached)} edge(s): {', '.join(attached)}",
                    )
                    if cascade:
                        working.edges = [e for e in working.edges if e.id not in attached]
                        edge_ids.difference_update(attached)
                        impacted.extend(attached)
                working.nodes = [n for n in working.nodes if n.id != op_id]
                node_ids.discard(op_id)
                impacted.append(op_id)

        elif op_name.endswith("_edge"):
            if op_name == "add_edge":
                if op_id in edge_ids:
                    raise ApiException(ErrorCode.GRAPH_DUPLICATE_ID, f"add_edge: id '{op_id}' already exists", {"relatedIds": [op_id]})
                edge_data = dict(value)
                edge_data["id"] = op_id
                try:
                    edge = GraphEdge.model_validate(edge_data)
                except ValidationError as exc:
                    raise ApiException(ErrorCode.SCHEMA_INVALID, f"add_edge '{op_id}': invalid edge value",
                                       {"errors": [str(e["msg"]) for e in exc.errors()[:5]]})
                if edge.kind == "physical" and edge.direction != "undirected":
                    warnings.append(PatchWarning(
                        code="GRAPH_PHYSICAL_EDGE_DIRECTION",
                        message=f'physical edge "{op_id}" declares a direction; it is rendered undirected',
                        relatedIds=[op_id],
                    ))
                working.edges.append(edge)
                edge_ids.add(op_id)
                impacted.extend([op_id, edge.source, edge.target])
            elif op_name == "update_edge":
                edge = next((e for e in working.edges if e.id == op_id), None)
                if edge is None:
                    raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                       f"update_edge: edge '{op_id}' does not exist", [op_id])
                bad_keys = set(changes) - (UPDATABLE_EDGE_KEYS | EDGE_ENDPOINT_KEYS)
                if bad_keys:
                    raise ApiException(ErrorCode.SCHEMA_INVALID,
                                       f"update_edge: fields {sorted(bad_keys)} cannot be modified", [op_id])
                endpoint_changes = set(changes) & EDGE_ENDPOINT_KEYS
                if endpoint_changes:
                    require(
                        confirm,
                        f"update_edge '{op_id}' changes {', '.join(sorted(endpoint_changes))} (reconnection is high-risk)",
                    )
                if "source" in changes:
                    edge.source = changes["source"]
                if "target" in changes:
                    edge.target = changes["target"]
                if "kind" in changes:
                    edge.kind = changes["kind"]
                if "direction" in changes:
                    edge.direction = changes["direction"]
                if "label" in changes:
                    edge.label = changes["label"]
                if "waypoints" in changes:
                    edge.waypoints = _validated_waypoints(changes["waypoints"])
                if "style" in changes:
                    edge.style = {**(edge.style or {}), **changes["style"]}
                impacted.append(op_id)
            elif op_name == "remove_edge":
                edge = next((e for e in working.edges if e.id == op_id), None)
                if edge is None:
                    raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                       f"remove_edge: edge '{op_id}' does not exist", [op_id])
                require(confirm, f"remove_edge '{op_id}' deletes an existing connection")
                working.edges = [e for e in working.edges if e.id != op_id]
                edge_ids.discard(op_id)
                impacted.append(op_id)

        elif op_name.endswith("_group"):
            if op_name == "add_group":
                if op_id in group_ids or op_id in node_ids:
                    raise ApiException(ErrorCode.GRAPH_DUPLICATE_ID, f"add_group: id '{op_id}' already exists", {"relatedIds": [op_id]})
                group_data = dict(value)
                group_data["id"] = op_id
                try:
                    group = GraphGroup.model_validate(group_data)
                except ValidationError as exc:
                    raise ApiException(ErrorCode.SCHEMA_INVALID, f"add_group '{op_id}': invalid group value",
                                       {"errors": [str(e["msg"]) for e in exc.errors()[:5]]})
                working.groups.append(group)
                group_ids.add(op_id)
                impacted.append(op_id)
            elif op_name == "update_group":
                group = next((g for g in working.groups if g.id == op_id), None)
                if group is None:
                    raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                       f"update_group: group '{op_id}' does not exist", [op_id])
                bad_keys = set(changes) - UPDATABLE_GROUP_KEYS
                if bad_keys:
                    raise ApiException(ErrorCode.SCHEMA_INVALID,
                                       f"update_group: fields {sorted(bad_keys)} cannot be modified", [op_id])
                if "geometry" in changes:
                    if group.manualLocked:
                        raise ApiException(ErrorCode.LAYOUT_CONFLICT,
                                           f"group '{op_id}' is manualLocked; its position will not be changed",
                                           [op_id])
                    group.geometry = _validated_geometry(changes["geometry"])
                    layout_plan.movedNodes.append({"id": op_id, "geometry": changes["geometry"]})
                if "parentId" in changes:
                    group.parentId = changes["parentId"]
                if "label" in changes:
                    group.label = changes["label"]
                if "style" in changes:
                    group.style = {**(group.style or {}), **changes["style"]}
                if "manualLocked" in changes:
                    group.manualLocked = bool(changes["manualLocked"])
                impacted.append(op_id)
            elif op_name == "remove_group":
                group = next((g for g in working.groups if g.id == op_id), None)
                if group is None:
                    raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                       f"remove_group: group '{op_id}' does not exist", [op_id])
                descendants = {op_id}
                for _ in working.groups:
                    found = {g.id for g in working.groups if g.parentId in descendants}
                    if found <= descendants:
                        break
                    descendants.update(found)
                child_nodes = {n.id for n in working.nodes if n.groupId in descendants}
                if child_nodes or len(descendants) > 1:
                    require(confirm and cascade, f"remove_group '{op_id}' would remove group members")
                attached = {e.id for e in working.edges if e.source in child_nodes or e.target in child_nodes}
                working.nodes = [n for n in working.nodes if n.id not in child_nodes]
                working.edges = [e for e in working.edges if e.id not in attached]
                working.groups = [g for g in working.groups if g.id not in descendants]
                node_ids.difference_update(child_nodes)
                group_ids.difference_update(descendants)
                edge_ids.difference_update(attached)
                impacted.extend(sorted(child_nodes | attached | descendants))

        elif op_name in ("update_layout", "update_theme"):
            if op_id != working.diagramId or not changes:
                raise ApiException(ErrorCode.SCHEMA_INVALID, f"{op_name} requires the current diagramId and changes")
            try:
                if op_name == "update_layout":
                    working.layout = LayoutSpec.model_validate(working.layout.model_dump(exclude_none=True) | changes)
                else:
                    current = working.appearance.model_dump(exclude_none=True) if working.appearance else {}
                    working.appearance = Appearance.model_validate(current | changes)
            except ValidationError as exc:
                raise ApiException(ErrorCode.SCHEMA_INVALID, f"{op_name}: invalid changes",
                                   {"errors": [e["msg"] for e in exc.errors()[:5]]}) from exc
            impacted.append(op_id)
        else:  # pragma: no cover - schema enum prevents this
            raise ApiException(ErrorCode.SCHEMA_INVALID, f"unknown operation '{op_name}'")

    working.schemaVersion = "1.1"
    try:
        working = GraphDocument.model_validate(working.model_dump(exclude_none=True))
    except ValidationError as exc:
        raise ApiException(ErrorCode.SCHEMA_INVALID, "patched graph fails schema validation",
                           {"errors": [e["msg"] for e in exc.errors()[:5]]}) from exc
    # Final semantic validation of the working copy.
    from app.graph.validate import collect_graph_issues
    errors, validator_warnings = collect_graph_issues(working)
    if errors:
        raise ApiException(
            errors[0].code,
            f"patched graph fails semantic validation: {errors[0].message}",
            {"errors": [str(i) for i in errors]},
        )
    for w in validator_warnings:
        warnings.append(PatchWarning(code=w.code, message=w.message, relatedIds=w.relatedIds))

    return PatchPreview(
        graph=working,
        impactedIds=list(dict.fromkeys(impacted)),
        warnings=warnings,
        requiresConfirmation=bool(reasons),
        confirmationReasons=reasons,
        layoutPlan=layout_plan,
    )
