"""Directed XML editing for GraphPatch application (docs/03 section 6).

Only cells affected by the patch are touched; unknown/unmapped cells and all
other user styling survive byte-for-byte. The semantic graph holds absolute
coordinates, while mxGeometry inside groups is parent-relative, so every
geometry write converts abs -> rel via the parent chain read from the XML.

The graphId->cellId mapping comes from the version manifest (import commit
stores it; renderer-built files use the stable n_/g_/e_ prefixes).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.importer.xml_parser import _DOCTYPE_PATTERN
from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import GraphDocument

# Node icon templates mirroring renderer/src/shapes/iconRegistry.ts (verified
# mxgraph.networks ids). Documented duplication, kept in sync manually.
NODE_STYLES = {
    "switch": "shape=mxgraph.networks.switch;",
    "router": "shape=mxgraph.networks.router;",
    "firewall": "shape=mxgraph.networks.firewall;",
    "server": "shape=mxgraph.networks.server;",
    "vm": "shape=mxgraph.networks.virtual_server;",
    "database": "shape=mxgraph.networks.storage;",
    "cloud": "shape=mxgraph.networks.cloud;",
    "client": "shape=mxgraph.networks.terminal;",
    "service": "shape=process;whiteSpace=wrap;fillColor=#D5E8D4;strokeColor=#82B366;fontColor=#2A4023;",
    "generic": "whiteSpace=wrap;html=1;rounded=1;fillColor=#FFF2CC;strokeColor=#D6B656;fontColor=#4A3B00;",
}

EDGE_BASE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"

GROUP_STYLE = (
    "swimlane;html=1;startSize=32;horizontal=1;rounded=1;fillColor=#F4F7FA;"
    "strokeColor=#9DB4C8;fontColor=#33506B;swimlaneFillColor=#FBFDFE;"
)

MAX_XML_BYTES = 10 * 1024 * 1024


def _fmt(n: Any) -> str:
    n = float(n)
    return str(int(n)) if n.is_integer() else str(round(n, 2))


def _node_style(node: Any) -> str:
    kind = node.kind if isinstance(node.kind, str) else "generic"
    base = NODE_STYLES.get(kind, NODE_STYLES["generic"])
    parts = [base, "verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;", f"aiKind={kind};"]
    device_type = (node.properties or {}).get("deviceType")
    if device_type:
        parts.append(f"aiDeviceType={device_type};")
    return "".join(parts)


def _anchor_fragment(src_geo: Optional[Dict[str, Any]], tgt_geo: Optional[Dict[str, Any]]) -> str:
    """Fixed directional connection anchors derived from endpoint geometries."""
    if not src_geo or not tgt_geo or src_geo.get("x") is None or tgt_geo.get("x") is None:
        return ""
    dx = (tgt_geo["x"] + tgt_geo["width"] / 2) - (src_geo["x"] + src_geo["width"] / 2)
    dy = (tgt_geo["y"] + tgt_geo["height"] / 2) - (src_geo["y"] + src_geo["height"] / 2)
    if dx == 0 and dy == 0:
        return ""
    if abs(dx) > abs(dy):
        if dx > 0:
            return "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
        return "exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;"
    if dy > 0:
        return "exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;"
    return "exitX=0.5;exitY=0;exitDx=0;exitDy=0;entryX=0.5;entryY=1;entryDx=0;entryDy=0;"


def _edge_style(kind: str, direction: str, src_geo: Optional[Dict[str, Any]],
                tgt_geo: Optional[Dict[str, Any]]) -> str:
    parts = [EDGE_BASE_STYLE]
    if kind == "physical":
        parts.append("strokeColor=#536D83;strokeWidth=1.5;startArrow=none;startFill=0;endArrow=none;endFill=0;")
    elif kind == "logical":
        parts.append("dashed=1;strokeColor=#6C8EBF;strokeWidth=1.2;startArrow=none;startFill=0;endArrow=block;endFill=1;")
    elif kind == "dataflow":
        parts.append("strokeColor=#4A7E53;strokeWidth=1.2;startArrow=none;startFill=0;endArrow=block;endFill=1;")
    elif kind == "control":
        parts.append("dashed=1;strokeColor=#B85450;strokeWidth=1.2;startArrow=none;startFill=0;endArrow=block;endFill=1;")
    else:
        parts.append("dashed=1;dashPattern=1 3;strokeColor=#8A8A8A;strokeWidth=1;startArrow=none;startFill=0;endArrow=block;endFill=1;")
    if direction == "bidirectional" and kind != "physical":
        parts.append("startArrow=block;startFill=1;")
    # Semantic markers keep edge types lossless across Desktop round-trips.
    parts.append(f"aiKind={kind};aiDirection={direction};")
    parts.append(_anchor_fragment(src_geo, tgt_geo))
    return "".join(parts)


_EDGE_ANCHOR_KEYS = ("exitX", "exitY", "exitDx", "exitDy", "entryX", "entryY", "entryDx", "entryDy")


def _refresh_edge_anchors(inner: ET.Element, src_geo: Optional[Dict[str, Any]],
                          tgt_geo: Optional[Dict[str, Any]]) -> None:
    """Replace the anchor keys in an existing edge style, keeping user keys."""
    style = inner.get("style") or ""
    kept = [p for p in style.split(";") if p and not p.startswith(_EDGE_ANCHOR_KEYS)]
    fragment = _anchor_fragment(src_geo, tgt_geo)
    if fragment:
        kept.append(fragment.rstrip(";"))
    inner.set("style", ";".join(kept) + ";")


@dataclass
class XmlEditContext:
    tree: ET.ElementTree
    root_el: ET.Element  # <root>
    cells: Dict[str, ET.Element]  # cell id -> top-level element (mxCell / object / UserObject)


def _inner(el: ET.Element) -> ET.Element:
    return el.find("mxCell") if el.tag in ("object", "UserObject") else el


def load_xml_context(xml_bytes: bytes, max_cells: int = 5000) -> XmlEditContext:
    if len(xml_bytes) > MAX_XML_BYTES:
        raise ApiException(ErrorCode.DRAWIO_UPLOAD_TOO_LARGE, "stored XML exceeds the size limit")
    if _DOCTYPE_PATTERN.search(xml_bytes[:4096]):
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "stored XML declares DOCTYPE/ENTITY; refusing to edit")
    try:
        tree = ET.ElementTree(ET.fromstring(xml_bytes))
    except ET.ParseError as exc:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, f"stored XML is not well-formed: {exc}") from exc
    root_el_tree = tree.getroot()
    if root_el_tree.tag == "mxfile":
        diagrams = root_el_tree.findall("diagram")
        if len(diagrams) != 1:
            raise ApiException(
                ErrorCode.DRAWIO_UNSUPPORTED_CONTENT,
                f"stored file has {len(diagrams)} pages; patching multi-page files is not supported",
            )
        diagram = diagrams[0]
        if diagram.get("compressed") == "true" or (diagram.find("mxGraphModel") is None and (diagram.text or "").strip()):
            raise ApiException(
                ErrorCode.DRAWIO_UNSUPPORTED_CONTENT,
                "stored file page is compressed; patching compressed pages is not supported",
            )
        model = diagram.find("mxGraphModel")
    elif root_el_tree.tag == "mxGraphModel":
        model = root_el_tree
    else:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "stored XML root must be mxfile or mxGraphModel")
    if model is None or model.find("root") is None:
        raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "stored XML has no mxGraphModel/root")
    root_el = model.find("root")
    cells: Dict[str, ET.Element] = {}
    count = 0
    for el in list(root_el):
        cid = el.get("id")
        if cid is None and el.tag in ("object", "UserObject"):
            inner = el.find("mxCell")
            cid = inner.get("id") if inner is not None else None
        if cid is None:
            continue
        cells[cid] = el
        count += 1
        if count > max_cells:
            raise ApiException(ErrorCode.DRAWIO_UNSUPPORTED_CONTENT, "stored XML exceeds the cell limit")
    return XmlEditContext(tree=tree, root_el=root_el, cells=cells)


def _abs_geometry(ctx: XmlEditContext, cell_id: str) -> Optional[Dict[str, float]]:
    el = ctx.cells.get(cell_id)
    if el is None:
        return None
    inner = _inner(el)
    geo = inner.find("mxGeometry") if inner is not None else None
    if geo is None or geo.get("x") is None or geo.get("y") is None:
        return None
    x, y = float(geo.get("x")), float(geo.get("y"))
    parent_id = inner.get("parent") if inner is not None else None
    while parent_id and parent_id not in ("0", "1"):
        pel = ctx.cells.get(parent_id)
        if pel is None:
            break
        pinner = _inner(pel)
        pgeo = pinner.find("mxGeometry") if pinner is not None else None
        if pgeo is not None and pgeo.get("x") is not None and pgeo.get("y") is not None:
            x += float(pgeo.get("x"))
            y += float(pgeo.get("y"))
        parent_id = pinner.get("parent") if pinner is not None else None
    w = float(geo.get("width")) if geo.get("width") else 0.0
    h = float(geo.get("height")) if geo.get("height") else 0.0
    return {"x": x, "y": y, "width": w, "height": h}


def _set_label(el: ET.Element, label: str) -> None:
    if el.tag in ("object", "UserObject"):
        el.set("label", label)
    else:
        el.set("value", label)


def _ensure_geometry(inner: ET.Element) -> ET.Element:
    geo = inner.find("mxGeometry")
    if geo is None:
        geo = ET.SubElement(inner, "mxGeometry")
        geo.set("as", "geometry")
    return geo


def _remove_element(ctx: XmlEditContext, el: ET.Element) -> None:
    for other in list(ctx.cells):
        if ctx.cells[other] is el:
            del ctx.cells[other]
    ctx.root_el.remove(el)


class CellMapper:
    """graph id -> cell id, from the manifest mapping or stable prefixes."""

    def __init__(self, mapping: Optional[Dict[str, str]], graph: GraphDocument) -> None:
        if mapping:
            self.map = dict(mapping)
        else:
            self.map = {}
            for n in graph.nodes:
                self.map[n.id] = f"n_{n.id}"
            for g in graph.groups:
                self.map[g.id] = f"g_{g.id}"
            for e in graph.edges:
                self.map[e.id] = f"e_{e.id}"

    def cell_id(self, graph_id: str) -> str:
        return self.map.get(graph_id, f"n_{graph_id}")

    def node_cell(self, graph_id: str) -> str:
        return self.map.get(graph_id, f"n_{graph_id}")

    def group_cell(self, graph_id: str) -> str:
        return self.map.get(graph_id, f"g_{graph_id}")

    def edge_cell(self, graph_id: str) -> str:
        return self.map.get(graph_id, f"e_{graph_id}")

    def register(self, graph_id: str, cell_id: str) -> None:
        self.map[graph_id] = cell_id


def _node_geo(node: Any) -> Optional[Dict[str, Any]]:
    geo = node.geometry
    if geo is None:
        return None
    return {"x": geo.x, "y": geo.y, "width": geo.width, "height": geo.height}


def _group_abs_from_xml(ctx: XmlEditContext, mapper: CellMapper, group_id: Optional[str]) -> Dict[str, float]:
    if not group_id:
        return {"x": 0.0, "y": 0.0}
    abs_geo = _abs_geometry(ctx, mapper.group_cell(group_id))
    if abs_geo and abs_geo["x"] is not None:
        return {"x": abs_geo["x"], "y": abs_geo["y"]}
    return {"x": 0.0, "y": 0.0}


def apply_patch_to_xml(
    xml_bytes: bytes,
    old_graph: GraphDocument,
    new_graph: GraphDocument,
    applied_ops: List[Dict[str, Any]],
    mapping: Optional[Dict[str, str]] = None,
    max_cells: int = 5000,
) -> bytes:
    """Apply a validated patch to stored XML; returns the new XML bytes."""
    ctx = load_xml_context(xml_bytes, max_cells=max_cells)
    mapper = CellMapper(mapping, old_graph)
    new_nodes = {n.id: n for n in new_graph.nodes}
    new_groups = {g.id: g for g in new_graph.groups}
    new_edges = {e.id: e for e in new_graph.edges}

    for op in applied_ops:
        op_name, op_id = op["op"], op["id"]
        value = op.get("value") or {}
        changes = op.get("changes") or {}

        if op_name == "add_node":
            node = new_nodes[op_id]
            cell_id = mapper.node_cell(op_id)
            if cell_id in ctx.cells:
                raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED,
                                   f"add_node: cell '{cell_id}' already exists in the XML", [op_id])
            parent_cell = mapper.group_cell(node.groupId) if node.groupId else "1"
            inner = ET.Element("mxCell", {
                "id": cell_id,
                "value": node.label,
                "style": _node_style(node),
                "vertex": "1",
                "parent": parent_cell,
            })
            geo = ET.SubElement(inner, "mxGeometry", {"as": "geometry"})
            parent_abs = _group_abs_from_xml(ctx, mapper, node.groupId)
            geo.set("x", _fmt(node.geometry.x - parent_abs["x"]))
            geo.set("y", _fmt(node.geometry.y - parent_abs["y"]))
            geo.set("width", _fmt(node.geometry.width))
            geo.set("height", _fmt(node.geometry.height))
            ctx.root_el.append(inner)
            mapper.register(op_id, cell_id)

        elif op_name == "update_node":
            cell_id = mapper.node_cell(op_id)
            el = ctx.cells.get(cell_id)
            if el is None:
                raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                   f"update_node: XML cell '{cell_id}' not found (stale mapping?)", [op_id])
            node = new_nodes[op_id]
            if "label" in changes:
                _set_label(el, node.label)
            if "style" in changes:
                inner = _inner(el)
                existing = dict(kv.split("=", 1) for kv in (inner.get("style") or "").split(";") if "=" in kv)
                for k, v in (changes.get("style") or {}).items():
                    existing[str(k)] = str(v)
                inner.set("style", ";".join(f"{k}={v}" for k, v in existing.items()) + ";")
            if "geometry" in changes and node.geometry:
                inner = _inner(el)
                geo = _ensure_geometry(inner)
                parent_abs = _group_abs_from_xml(ctx, mapper, node.groupId)
                geo.set("x", _fmt(node.geometry.x - parent_abs["x"]))
                geo.set("y", _fmt(node.geometry.y - parent_abs["y"]))
                geo.set("width", _fmt(node.geometry.width))
                geo.set("height", _fmt(node.geometry.height))
            if "groupId" in changes:
                inner = _inner(el)
                new_parent = mapper.group_cell(node.groupId) if node.groupId else "1"
                inner.set("parent", new_parent)
                geo = _ensure_geometry(inner)
                parent_abs = _group_abs_from_xml(ctx, mapper, node.groupId)
                geo.set("x", _fmt(node.geometry.x - parent_abs["x"]))
                geo.set("y", _fmt(node.geometry.y - parent_abs["y"]))

        elif op_name == "remove_node":
            cell_id = mapper.node_cell(op_id)
            el = ctx.cells.get(cell_id)
            if el is not None:
                _remove_element(ctx, el)
            for edge in old_graph.edges:
                if edge.source == op_id or edge.target == op_id:
                    eel = ctx.cells.get(mapper.edge_cell(edge.id))
                    if eel is not None:
                        _remove_element(ctx, eel)

        elif op_name == "add_edge":
            edge = new_edges[op_id]
            src = new_nodes[edge.source]
            tgt = new_nodes[edge.target]
            cell_id = mapper.edge_cell(op_id)
            inner = ET.Element("mxCell", {
                "id": cell_id,
                "value": edge.label or "",
                "style": _edge_style(edge.kind, edge.direction, _node_geo(src), _node_geo(tgt)),
                "edge": "1",
                "parent": "1",
                "source": mapper.node_cell(edge.source),
                "target": mapper.node_cell(edge.target),
            })
            geo = ET.SubElement(inner, "mxGeometry", {"relative": "1", "as": "geometry"})
            if edge.waypoints:
                arr = ET.SubElement(geo, "Array", {"as": "points"})
                for p in edge.waypoints:
                    ET.SubElement(arr, "mxPoint", {"x": _fmt(p["x"]), "y": _fmt(p["y"])})
            ctx.root_el.append(inner)
            mapper.register(op_id, cell_id)

        elif op_name == "update_edge":
            cell_id = mapper.edge_cell(op_id)
            el = ctx.cells.get(cell_id)
            if el is None:
                raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                   f"update_edge: XML cell '{cell_id}' not found", [op_id])
            inner = _inner(el)
            edge = new_edges[op_id]
            if "label" in changes:
                _set_label(el, edge.label or "")
            if "source" in changes:
                inner.set("source", mapper.node_cell(edge.source))
            if "target" in changes:
                inner.set("target", mapper.node_cell(edge.target))
            if "kind" in changes or "direction" in changes:
                # Semantic type changed: rebuild the visual style from the
                # template (this edge's arrow/dash/color tweaks are reset) so
                # the XML stays consistent with the graph (docs/02 section 8).
                src = new_nodes[edge.source]
                tgt = new_nodes[edge.target]
                inner.set("style", _edge_style(edge.kind, edge.direction, _node_geo(src), _node_geo(tgt)))
            elif "source" in changes or "target" in changes:
                # Endpoints moved to different nodes: refresh only the anchor
                # keys, keeping the rest of the user's style untouched.
                _refresh_edge_anchors(inner, _node_geo(new_nodes[edge.source]), _node_geo(new_nodes[edge.target]))
            if "waypoints" in changes:
                geo = _ensure_geometry(inner)
                for arr in list(geo.findall("Array")):
                    if arr.get("as") == "points":
                        geo.remove(arr)
                if edge.waypoints:
                    arr = ET.SubElement(geo, "Array", {"as": "points"})
                    for p in edge.waypoints:
                        ET.SubElement(arr, "mxPoint", {"x": _fmt(p["x"]), "y": _fmt(p["y"])})

        elif op_name == "remove_edge":
            el = ctx.cells.get(mapper.edge_cell(op_id))
            if el is not None:
                _remove_element(ctx, el)

        elif op_name == "add_group":
            group = new_groups[op_id]
            cell_id = mapper.group_cell(op_id)
            inner = ET.Element("mxCell", {
                "id": cell_id,
                "value": group.label,
                "style": GROUP_STYLE,
                "vertex": "1",
                "parent": mapper.group_cell(group.parentId) if group.parentId else "1",
            })
            geo = ET.SubElement(inner, "mxGeometry", {"as": "geometry"})
            if group.geometry:
                geo.set("x", _fmt(group.geometry.x))
                geo.set("y", _fmt(group.geometry.y))
                geo.set("width", _fmt(group.geometry.width))
                geo.set("height", _fmt(group.geometry.height))
            else:
                geo.set("x", "40")
                geo.set("y", "40")
                geo.set("width", "300")
                geo.set("height", "160")
            ctx.root_el.append(inner)
            mapper.register(op_id, cell_id)

        elif op_name == "update_group":
            el = ctx.cells.get(mapper.group_cell(op_id))
            if el is None:
                raise ApiException(ErrorCode.GRAPH_INVALID_REFERENCE,
                                   f"update_group: XML cell for '{op_id}' not found", [op_id])
            group = new_groups[op_id]
            if "label" in changes:
                _set_label(el, group.label)
            if "geometry" in changes and group.geometry:
                geo = _ensure_geometry(_inner(el))
                geo.set("x", _fmt(group.geometry.x))
                geo.set("y", _fmt(group.geometry.y))
                geo.set("width", _fmt(group.geometry.width))
                geo.set("height", _fmt(group.geometry.height))

        elif op_name == "remove_group":
            cascade = bool(op.get("cascade"))
            if cascade:
                member_ids = [n.id for n in old_graph.nodes if n.groupId == op_id]
                child_groups = [g.id for g in old_graph.groups if g.parentId == op_id]
                for nid in member_ids:
                    el = ctx.cells.get(mapper.node_cell(nid))
                    if el is not None:
                        _remove_element(ctx, el)
                for edge in old_graph.edges:
                    if edge.source in member_ids or edge.target in member_ids:
                        eel = ctx.cells.get(mapper.edge_cell(edge.id))
                        if eel is not None:
                            _remove_element(ctx, eel)
                for gid in child_groups:
                    gel = ctx.cells.get(mapper.group_cell(gid))
                    if gel is not None:
                        _remove_element(ctx, gel)
            el = ctx.cells.get(mapper.group_cell(op_id))
            if el is not None:
                _remove_element(ctx, el)

    ET.indent(ctx.tree, space="  ")
    out = ET.tostring(ctx.tree.getroot(), encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + out + "\n").encode("utf-8")
