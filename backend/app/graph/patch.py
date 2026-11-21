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

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import jsonschema
from pydantic import ValidationError

from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import Geometry, GraphDocument, GraphEdge, GraphGroup, GraphNode, Point

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
_PATCH_SCHEMA = json.loads((_CONTRACTS / "patch.schema.json").read_text(encoding="utf-8"))
_PATCH_VALIDATOR = jsonschema.Draft202012Validator(_PATCH_SCHEMA)

UPDATABLE_NODE_KEYS = {"label", "style", "geometry", "manualLocked", "properties", "groupId"}
UPDATABLE_GROUP_KEYS = {"label", "style", "geometry", "manualLocked"}
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


def _node_boxes(doc: GraphDocument) -> List[Tuple[float, float, float, float]]:
    boxes: List[Tuple[float, float, float, float]] = []
    for n in doc.nodes:
        if n.geometry:
            boxes.append((n.geometry.x, n.geometry.y, n.geometry.width, n.geometry.height))
    for g in doc.groups:
        if g.geometry:
            boxes.append((g.geometry.x, g.geometry.y, g.geometry.width, g.geometry.height))
    return boxes


def _overlaps(box: Tuple[float, float, float, float], others, margin: float = 20.0) -> bool:
    x, y, w, h = box
    for ox, oy, ow, oh in others:
        if x < ox + ow + margin and ox < x + w + margin and y < oy + oh + margin and oy < y + h + margin:
            return True
    return False


# Default icon box sizes mirrored from renderer iconRegistry (Phase 0.5).
DEFAULT_NODE_SIZES = {
    "switch": (130, 48), "router": (130, 48), "firewall": (90, 92), "server": (90, 96),
    "vm": (100, 108), "database": (90, 90), "cloud": (130, 72), "client": (100, 80),
    "service": (120, 64), "generic": (120, 64),
}


def _anchor_geometry(doc: GraphDocument, node_id: str, edges: List[GraphEdge]) -> Dict[str, Any]:
    """Find a free rectangle near an adjacent node (anchor insert, docs/03 §6).

    Group members are placed INSIDE their group's box: a full unlocked group
    grows downward (members untouched), a full locked group raises
    LAYOUT_CONFLICT instead of moving locked objects. Root-level nodes fall
    back to free space below the content (canvas growth).
    """
    neighbors = [e.source for e in edges if e.target == node_id] + \
                [e.target for e in edges if e.source == node_id]
    boxes = _node_boxes(doc)
    node = next(n for n in doc.nodes if n.id == node_id)
    if node.geometry is not None:
        size = {"width": node.geometry.width, "height": node.geometry.height}
    else:
        w, h = DEFAULT_NODE_SIZES.get(node.kind, (120, 64))
        size = {"width": w, "height": h}

    if node.groupId:
        group = next(g for g in doc.groups if g.id == node.groupId)
        if group.geometry is None:
            raise ApiException(
                ErrorCode.LAYOUT_CONFLICT,
                f"group '{group.id}' has no geometry; cannot place '{node_id}' inside it",
                {"relatedIds": [group.id, node_id]},
            )
        gbox = (group.geometry.x, group.geometry.y, group.geometry.width, group.geometry.height)
        inner_boxes = []
        for n in doc.nodes:
            if n.id != node_id and n.groupId == group.id and n.geometry:
                inner_boxes.append((n.geometry.x, n.geometry.y, n.geometry.width, n.geometry.height))
        bottom = max((b[1] + b[3] for b in inner_boxes), default=gbox[1] + 48)
        right = max((b[0] + b[2] for b in inner_boxes), default=gbox[0] + 20)
        first = inner_boxes[0] if inner_boxes else None
        candidates = [
            (right + 24, first[1] if first else gbox[1] + 48),
            (first[0] if first else gbox[0] + 20, bottom + 24),
        ]
        for x, y in candidates:
            candidate = (x, y, size["width"], size["height"])
            inside = (x >= gbox[0] + 8 and y >= gbox[1] + 8 and
                      x + size["width"] <= gbox[0] + gbox[2] - 8 and
                      y + size["height"] <= gbox[1] + gbox[3] - 8)
            if inside and not _overlaps(candidate, inner_boxes):
                return {"x": x, "y": y, "width": size["width"], "height": size["height"]}
        if group.manualLocked:
            raise ApiException(
                ErrorCode.LAYOUT_CONFLICT,
                f"group '{group.id}' is manualLocked and has no free slot; node '{node_id}' "
                "cannot be inserted without moving locked objects (no automatic re-layout performed)",
                {"relatedIds": [group.id, node_id]},
            )
        # Grow the group downward; member positions stay untouched.
        return {"x": gbox[0] + 24, "y": bottom + 24, "width": size["width"], "height": size["height"]}

    # Root-level nodes: anchor near a connected node, else below the content.
    offsets = [(140, 0), (-140, 0), (0, 110), (0, -110), (140, 110), (-140, -110), (280, 0), (0, 220)]
    for nid in neighbors:
        n = next((n for n in doc.nodes if n.id == nid), None)
        if n and n.geometry:
            ax, ay = n.geometry.x, n.geometry.y
            for dx, dy in offsets:
                candidate = (ax + dx, ay + dy, size["width"], size["height"])
                if not _overlaps(candidate, boxes):
                    return {"x": ax + dx, "y": ay + dy, "width": size["width"], "height": size["height"]}
    # Generic free spot: scan below/right of content bounds.
    max_y = max((b[1] + b[3] for b in boxes), default=0)
    max_x = max((b[0] + b[2] for b in boxes), default=0)
    for row in range(0, 12):
        y = max_y + 60 + row * (size["height"] + 40)
        for col in range(0, 6):
            x = 40 + col * (size["width"] + 60)
            candidate = (x, y, size["width"], size["height"])
            if not _overlaps(candidate, boxes):
                return {"x": x, "y": y, "width": size["width"], "height": size["height"]}
    raise ApiException(
        ErrorCode.LAYOUT_CONFLICT,
        f"cannot insert node '{node_id}' without moving or overlapping existing objects; "
        "no automatic re-layout was performed",
    )


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

    def ids_of_value(value: Any) -> Set[str]:
        """Node/edge ids referenced by a patch value/changes payload."""
        refs: Set[str] = set()
        if isinstance(value, dict):
            for key in ("source", "target", "groupId", "parentId"):
                v = value.get(key)
                if isinstance(v, str):
                    refs.add(v)
        return refs

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
                if node_data.get("groupId") and node_data["groupId"] not in group_ids:
                    raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                       f"add_node: groupId '{node_data['groupId']}' does not exist", [op_id])
                node_data.setdefault("origin", "ai")
                try:
                    node = GraphNode.model_validate(node_data)
                except ValidationError as exc:
                    raise ApiException(ErrorCode.SCHEMA_INVALID, f"add_node '{op_id}': invalid node value",
                                       {"errors": [str(e["msg"]) for e in exc.errors()[:5]]})
                if node.geometry is None:
                    # Anchor placement happens on a doc that already has this node
                    # without geometry; assign id first so edges can reference it.
                    working.nodes.append(node)
                    geo = _anchor_geometry(working, op_id, working.edges)
                    node.geometry = _validated_geometry(geo)
                    layout_plan.addedNodes.append({"id": op_id, "geometry": geo})
                else:
                    if _overlaps(
                        (node.geometry.x, node.geometry.y, node.geometry.width, node.geometry.height),
                        [b for b in _node_boxes(working) if b != (node.geometry.x, node.geometry.y,
                                                                 node.geometry.width, node.geometry.height)],
                    ):
                        warnings.append(PatchWarning(
                            code="INSERTED_NODE_OVERLAPS",
                            message=f"新节点 {op_id} 的显式坐标与现有对象重叠，未自动避让",
                            relatedIds=[op_id],
                        ))
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
                if "groupId" in changes and changes["groupId"] is not None:
                    if changes["groupId"] not in group_ids:
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
                for key in ("source", "target"):
                    if edge_data.get(key) not in node_ids:
                        raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                           f"add_edge '{op_id}': {key} '{edge_data.get(key)}' is not a node", [op_id])
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
                    if changes["source"] not in node_ids:
                        raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                           f"update_edge: source '{changes['source']}' is not a node", [op_id])
                    edge.source = changes["source"]
                if "target" in changes:
                    if changes["target"] not in node_ids:
                        raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                           f"update_edge: target '{changes['target']}' is not a node", [op_id])
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
                if group_data.get("parentId") and group_data["parentId"] not in group_ids:
                    raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                       f"add_group: parentId '{group_data['parentId']}' does not exist", [op_id])
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
                child_nodes = [n.id for n in working.nodes if n.groupId == op_id]
                child_groups = [g.id for g in working.groups if g.parentId == op_id]
                if child_nodes or child_groups:
                    require(
                        confirm and cascade,
                        f"remove_group '{op_id}' would drop {len(child_nodes)} node(s) and {len(child_groups)} sub-group(s)",
                    )
                    if cascade:
                        for nid in list(child_nodes):
                            attached = [e.id for e in working.edges if e.source == nid or e.target == nid]
                            working.edges = [e for e in working.edges if e.id not in attached]
                            impacted.extend(attached)
                            working.nodes = [n for n in working.nodes if n.id != nid]
                            node_ids.discard(nid)
                            impacted.append(nid)
                        for gid in child_groups:
                            working.groups = [g for g in working.groups if g.id != gid]
                            group_ids.discard(gid)
                            impacted.append(gid)
                working.groups = [g for g in working.groups if g.id != op_id]
                group_ids.discard(op_id)
                impacted.append(op_id)
        else:  # pragma: no cover - schema enum prevents this
            raise ApiException(ErrorCode.SCHEMA_INVALID, f"unknown operation '{op_name}'")

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
