"""Map parsed draw.io cells back to the semantic GraphDocument and compute
the diff against the currently stored graph (docs/03 section 5, docs/02 section 8).

The uploaded XML is the source of truth for shapes; the derived graph is the
semantic view used for validation, patching and diffing. Unknown cells are
preserved (never deleted, never converted) and reported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.importer.xml_parser import ParsedCell, ParsedDrawio
from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import GraphDocument

STYLE_KEY_PATTERN = re.compile(r"([A-Za-z0-9_-]+)=([^;]*)")

# Reverse of the Phase 0.5 icon registry (aiKind is authoritative when present).
STENCIL_KIND_MAP = {
    "mxgraph.networks.switch": "switch",
    "mxgraph.networks.router": "router",
    "mxgraph.networks.firewall": "firewall",
    "mxgraph.networks.server": "server",
    "mxgraph.networks.virtual_server": "vm",
    "mxgraph.networks.storage": "database",
    "mxgraph.networks.cloud": "cloud",
    "mxgraph.networks.terminal": "client",
    "process": "service",
    # Cisco theme, including the original server stencil used in older diagrams.
    "mxgraph.cisco.storage.cloud": "cloud",
    "mxgraph.cisco.routers.router": "router",
    "mxgraph.cisco.security.ios_firewall": "firewall",
    "mxgraph.cisco.misc.route_switch_processor": "switch",
    "mxgraph.cisco.servers.fileserver": "server",
    "mxgraph.cisco.servers.server_with_router": "server",
    "mxgraph.cisco.servers.software_based_server": "vm",
    "mxgraph.cisco.storage.relational_database": "database",
    "mxgraph.cisco.computers_and_peripherals.pc": "client",
}


def parse_style(style: Optional[str]) -> Dict[str, str]:
    """Split a drawio style string into keys (later duplicates win)."""
    result: Dict[str, str] = {}
    if not style:
        return result
    for part in style.split(";"):
        if not part:
            continue
        m = STYLE_KEY_PATTERN.match(part)
        if m:
            result[m.group(1)] = m.group(2)
        elif part and "=" not in part:
            # bare flag like swimlane/ellipse — record under its own name
            result[part] = ""
    return result


def _kind_from_style(style: Optional[str]) -> Tuple[str, Optional[str]]:
    """Infer (kind, deviceType) from a style string."""
    keys = parse_style(style)
    ai_kind = keys.get("aiKind")
    device_type = keys.get("aiDeviceType")
    if ai_kind in {"switch", "router", "firewall", "server", "vm", "cloud",
                   "service", "database", "client", "generic"}:
        return ai_kind, device_type
    shape = keys.get("shape", "")
    if shape in STENCIL_KIND_MAP:
        return STENCIL_KIND_MAP[shape], device_type
    if "ellipse" in keys or shape == "ellipse":
        return "cloud", device_type
    if "cylinder" in shape or "cylinder" in keys:
        return "database", device_type
    if shape == "image":
        return "generic", device_type
    return "generic", device_type


def _sanitize_graph_id(raw: str, used: set) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]", "_", raw).strip("_-")
    candidate = candidate.lstrip("0123456789") or "imp"
    candidate = candidate[:63] or "imp"
    final = candidate
    seq = 1
    while final in used:
        seq += 1
        final = f"{candidate[:56]}_{seq}"
    used.add(final)
    return final


@dataclass
class ImportResult:
    graph: GraphDocument
    cell_to_graph_id: Dict[str, str]
    graph_id_to_cell: Dict[str, str]
    unknown_cells: List[Dict[str, Any]]
    mapping_changes: List[str] = field(default_factory=list)


def graph_from_cells(parsed: ParsedDrawio, diagram_id: str, diagram_name: str,
                     diagram_type: str, previous_mapping: Optional[Dict[str, str]] = None) -> ImportResult:
    """Build a GraphDocument draft from parsed cells.

    - `n_`/`g_`/`e_` cell ids keep their stable graph ids;
    - other cells with `aiKind=` (user-copied objects) are imported under
      sanitized new ids (recorded in mapping_changes);
    - truly unknown cells (no mapping, no aiKind) are preserved but excluded
      from the semantic graph.
    """
    reserved = {cell.id[2:] for cell in parsed.cells if re.fullmatch(r"[nge]_[A-Za-z][A-Za-z0-9_-]{0,63}", cell.id)}
    previous = {cell: graph for graph, cell in (previous_mapping or {}).items()}
    used = {"0", "1", *reserved, *previous.values()}
    assigned = set()
    unknown = {}
    nodes: List[Dict[str, Any]] = []
    groups: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    cell_to_graph: Dict[str, str] = {}
    graph_to_cell: Dict[str, str] = {}
    mapping_changes: List[str] = []

    def graph_id_for(cell: ParsedCell, kind: str) -> str:
        existing = previous.get(cell.id)
        if existing and existing not in assigned:
            assigned.add(existing)
            return existing
        prefix = {"node": "n_", "group": "g_", "edge": "e_"}[kind]
        gid = cell.id[2:]
        if cell.id.startswith(prefix) and gid in reserved and gid not in assigned:
            assigned.add(gid)
            return gid
        gid = _sanitize_graph_id(cell.id, used)
        assigned.add(gid)
        mapping_changes.append(f"{cell.id} -> {gid}")
        return gid

    def preserve(cell: ParsedCell) -> None:
        unknown[cell.id] = {"cellId": cell.id, "wrapped": cell.wrapped, "style": cell.style, "preserved": True}

    def parent_group(cell: ParsedCell) -> Optional[str]:
        parent = parsed.cell_by_id.get(cell.parent)
        while parent is not None:
            if parent.id in cell_to_graph and cell_to_graph[parent.id] in group_ids:
                return cell_to_graph[parent.id]
            parent = parsed.cell_by_id.get(parent.parent)
        return None

    # Groups first (they anchor parent-child membership).
    for cell in parsed.cells:
        if cell.id in ("0", "1") or not cell.vertex:
            continue
        style_keys = parse_style(cell.style)
        is_group_cell = cell.id.startswith("g_") or "swimlane" in style_keys
        if not is_group_cell:
            continue
        gid = graph_id_for(cell, "group")
        abs_geo = parsed.absolute_geometry(cell)
        groups.append({
            "id": gid,
            "label": cell.value or gid,
            "geometry": {
                "x": abs_geo["x"] if abs_geo["x"] is not None else 0, "y": abs_geo["y"] if abs_geo["y"] is not None else 0,
                "width": cell.geometry.width if cell.geometry and cell.geometry.width else 100,
                "height": cell.geometry.height if cell.geometry and cell.geometry.height else 60,
            },
            "style": {k: v for k, v in style_keys.items()
                      if k in ("fillColor", "strokeColor", "fontColor") and v},
        })
        cell_to_graph[cell.id] = gid
        graph_to_cell[gid] = cell.id

    group_ids = {group["id"] for group in groups}
    for group in groups:
        parent = parent_group(parsed.cell_by_id[graph_to_cell[group["id"]]])
        if parent:
            group["parentId"] = parent

    for cell in parsed.cells:
        if cell.id in ("0", "1") or not cell.vertex:
            continue
        if cell.id in cell_to_graph:  # already a group
            continue
        style_keys = parse_style(cell.style)
        native = style_keys.get("shape", "")
        if not (cell.id in previous or cell.id.startswith("n_") or "aiKind" in style_keys
                or native in STENCIL_KIND_MAP or native.startswith(("mxgraph.cisco19.", "mxgraph.networks."))
                or native in {"rectangle", "ellipse", "cylinder3", "rhombus", "cloud"}):
            preserve(cell)
            continue
        kind, device_type = _kind_from_style(cell.style)
        gid = graph_id_for(cell, "node")
        abs_geo = parsed.absolute_geometry(cell)
        node: Dict[str, Any] = {
            "id": gid,
            "label": cell.value or gid,
            "kind": kind,
            "properties": {},
            "geometry": {
                "x": abs_geo["x"] if abs_geo["x"] is not None else 0, "y": abs_geo["y"] if abs_geo["y"] is not None else 0,
                "width": cell.geometry.width if cell.geometry and cell.geometry.width else 120,
                "height": cell.geometry.height if cell.geometry and cell.geometry.height else 60,
            },
            "manualLocked": False,
        }
        if device_type:
            node["properties"]["deviceType"] = device_type
        if style_keys.get("aiNetworkRole"):
            node["properties"]["networkRole"] = style_keys["aiNetworkRole"]
        parent = parent_group(cell)
        if parent:
            node["groupId"] = parent
        nodes.append(node)
        cell_to_graph[cell.id] = gid
        graph_to_cell[gid] = cell.id

    node_ids = {node["id"] for node in nodes}
    for cell in parsed.cells:
        if not cell.edge:
            continue
        if cell_to_graph.get(cell.source) not in node_ids or cell_to_graph.get(cell.target) not in node_ids:
            preserve(cell)
            continue
        eid = graph_id_for(cell, "edge")
        style_keys = parse_style(cell.style)
        # Semantic markers stamped by the renderer are authoritative and make
        # edge-type round-trips lossless; arrows remain only as a fallback
        # heuristic for edges drawn directly in Desktop (no aiKind), which
        # cannot distinguish logical/control/dependency — documented limit.
        ai_kind = style_keys.get("aiKind")
        ai_direction = style_keys.get("aiDirection")
        if ai_kind in ("physical", "logical", "dataflow", "control", "dependency"):
            kind = ai_kind
            direction = ai_direction if ai_direction in ("undirected", "forward", "bidirectional") else "undirected"
        elif style_keys.get("endArrow", "none") not in ("none", ""):
            kind = "dataflow"
            direction = "bidirectional" if style_keys.get("startArrow", "none") not in ("none", "") else "forward"
        elif style_keys.get("dashed") == "1":
            kind, direction = "logical", "forward"
        else:
            kind, direction = "physical", "undirected"
        edge: Dict[str, Any] = {
            "id": eid,
            "source": cell_to_graph.get(cell.source, cell.source),
            "target": cell_to_graph.get(cell.target, cell.target),
            "kind": kind,
            "direction": direction,
        }
        label = (cell.value or "").strip()
        if label:
            edge["label"] = label
        if cell.geometry and cell.geometry.points:
            parent = parsed.cell_by_id.get(cell.parent)
            offset = parsed.absolute_geometry(parent) if parent else {}
            edge["waypoints"] = [{"x": p["x"] + (offset.get("x") or 0), "y": p["y"] + (offset.get("y") or 0)}
                                 for p in cell.geometry.points]
        # User-added edges keep orthogonal styling hint in style map
        edges.append(edge)
        cell_to_graph[cell.id] = eid
        graph_to_cell[eid] = cell.id

    for cell in parsed.cells:
        if cell.id not in ("0", "1") and cell.id not in cell_to_graph:
            preserve(cell)

    layout = {"algorithm": "manual", "direction": "DOWN", "preserveManualPositions": True}
    payload = {
        "schemaVersion": "1.0",
        "diagramId": diagram_id,
        "name": diagram_name,
        "diagramType": diagram_type,
        "nodes": nodes,
        "groups": groups,
        "edges": edges,
        "layout": layout,
    }
    try:
        doc = GraphDocument.model_validate(payload)
    except ValidationError as exc:
        raise ApiException(
            ErrorCode.DRAWIO_PARSE_FAILED,
            "imported file does not map to a valid GraphDocument",
            {"errors": [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10]]},
        )
    return ImportResult(
        graph=doc,
        cell_to_graph_id=cell_to_graph,
        graph_id_to_cell=graph_to_cell,
        unknown_cells=list(unknown.values()),
        mapping_changes=mapping_changes,
    )


@dataclass
class GraphDiff:
    nodeAdded: List[str] = field(default_factory=list)
    nodeRemoved: List[str] = field(default_factory=list)
    nodeRenamed: List[Dict[str, Any]] = field(default_factory=list)
    nodeMoved: List[Dict[str, Any]] = field(default_factory=list)
    nodeKindChanged: List[Dict[str, Any]] = field(default_factory=list)
    nodeResized: List[Dict[str, Any]] = field(default_factory=list)
    shapeChanged: List[Dict[str, Any]] = field(default_factory=list)
    styleChanged: List[Dict[str, Any]] = field(default_factory=list)
    membershipChanged: List[Dict[str, Any]] = field(default_factory=list)
    edgeWaypointsChanged: List[Dict[str, Any]] = field(default_factory=list)
    layoutChanged: List[Dict[str, Any]] = field(default_factory=list)
    appearanceChanged: List[Dict[str, Any]] = field(default_factory=list)
    edgeAdded: List[str] = field(default_factory=list)
    edgeRemoved: List[str] = field(default_factory=list)
    edgeReconnected: List[Dict[str, Any]] = field(default_factory=list)
    edgeLabelChanged: List[Dict[str, Any]] = field(default_factory=list)
    edgeKindChanged: List[Dict[str, Any]] = field(default_factory=list)
    edgeDirectionChanged: List[Dict[str, Any]] = field(default_factory=list)
    groupAdded: List[str] = field(default_factory=list)
    groupRemoved: List[str] = field(default_factory=list)
    groupRenamed: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        counts = {key: len(items) for key, items in self.__dict__.items()}
        return dict(counts, total=sum(counts.values()))

    def to_payload(self) -> Dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items()}
        data["summary"] = self.summary()
        return data


def diff_graphs(old: GraphDocument, new: GraphDocument, position_tolerance: float = 0.01) -> GraphDiff:
    diff = GraphDiff()
    old_nodes = {n.id: n for n in old.nodes}
    new_nodes = {n.id: n for n in new.nodes}
    for nid in new_nodes:
        if nid not in old_nodes:
            diff.nodeAdded.append(nid)
            continue
        o, n = old_nodes[nid], new_nodes[nid]
        if o.label != n.label:
            diff.nodeRenamed.append({"id": nid, "from": o.label, "to": n.label})
        if o.geometry and n.geometry:
            if abs(o.geometry.x - n.geometry.x) > position_tolerance or \
               abs(o.geometry.y - n.geometry.y) > position_tolerance:
                diff.nodeMoved.append({
                    "id": nid,
                    "from": {"x": o.geometry.x, "y": o.geometry.y},
                    "to": {"x": n.geometry.x, "y": n.geometry.y},
                })
        if o.geometry and n.geometry and (abs(o.geometry.width - n.geometry.width) > position_tolerance
                                         or abs(o.geometry.height - n.geometry.height) > position_tolerance):
            diff.nodeResized.append({"id": nid, "from": [o.geometry.width, o.geometry.height],
                                     "to": [n.geometry.width, n.geometry.height]})
        if o.groupId != n.groupId:
            diff.membershipChanged.append({"id": nid, "from": o.groupId, "to": n.groupId})
        if o.kind != n.kind:
            diff.nodeKindChanged.append({"id": nid, "from": o.kind, "to": n.kind})
    for nid in old_nodes:
        if nid not in new_nodes:
            diff.nodeRemoved.append(nid)

    old_edges = {e.id: e for e in old.edges}
    new_edges = {e.id: e for e in new.edges}
    for eid in new_edges:
        if eid not in old_edges:
            diff.edgeAdded.append(eid)
            continue
        o, n = old_edges[eid], new_edges[eid]
        if (o.source, o.target) != (n.source, n.target):
            diff.edgeReconnected.append({
                "id": eid,
                "from": {"source": o.source, "target": o.target},
                "to": {"source": n.source, "target": n.target},
            })
        if (o.label or "") != (n.label or ""):
            diff.edgeLabelChanged.append({"id": eid, "from": o.label or "", "to": n.label or ""})
        if (o.waypoints or []) != (n.waypoints or []):
            diff.edgeWaypointsChanged.append({"id": eid})
        if o.kind != n.kind:
            diff.edgeKindChanged.append({"id": eid, "from": o.kind, "to": n.kind})
        if o.direction != n.direction:
            diff.edgeDirectionChanged.append({"id": eid, "from": o.direction, "to": n.direction})
    for eid in old_edges:
        if eid not in new_edges:
            diff.edgeRemoved.append(eid)

    old_groups = {g.id: g for g in old.groups}
    new_groups = {g.id: g for g in new.groups}
    for gid in new_groups:
        if gid not in old_groups:
            diff.groupAdded.append(gid)
        elif old_groups[gid].parentId != new_groups[gid].parentId:
            diff.membershipChanged.append({"id": gid, "from": old_groups[gid].parentId, "to": new_groups[gid].parentId})
        if gid in old_groups and old_groups[gid].label != new_groups[gid].label:
            diff.groupRenamed.append({"id": gid, "from": old_groups[gid].label, "to": new_groups[gid].label})
    for gid in old_groups:
        if gid not in new_groups:
            diff.groupRemoved.append(gid)
    return diff
