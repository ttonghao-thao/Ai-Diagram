"""Edit known cells in the original draw.io XML using resolved renderer output."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.importer.model_map import parse_style
from app.importer.xml_parser import guard_no_dtd
from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import GraphDocument

MAX_XML_BYTES = 10 * 1024 * 1024
ROUTE_KEYS = {
    "exitX", "exitY", "exitDx", "exitDy", "exitPerimeter", "entryX", "entryY", "entryDx",
    "entryDy", "entryPerimeter", "edgeStyle", "loopStyle", "orthogonalLoop", "jettySize",
}
EDGE_SEMANTIC_KEYS = {"aiKind", "aiDirection", "dashed", "dashPattern", "startArrow",
                      "endArrow", "startFill", "endFill", "strokeColor", "strokeWidth"}
ICON_KEYS = {"shape", "image", "imageAspect", "aspect", "prIcon", "resIcon", "aiShapeId",
             "fillColor", "strokeColor", "strokeWidth", "points", "sketch", "outlineConnect",
             "pointerEvents", "verticalLabelPosition", "verticalAlign", "labelWidth", "align",
             "spacingTop", "gradientColor", "gradientDirection", "backgroundOutline", "perimeter"}


def _fmt(value: Any) -> str:
    return format(float(value), ".8f").rstrip("0").rstrip(".") or "0"


@dataclass
class XmlEditContext:
    tree: ET.ElementTree
    model: ET.Element
    root_el: ET.Element  # <root>
    cells: Dict[str, ET.Element]  # cell id -> top-level element (mxCell / object / UserObject)


def _inner(el: ET.Element) -> ET.Element:
    return el.find("mxCell") if el.tag in ("object", "UserObject") else el


def load_xml_context(xml_bytes: bytes, max_cells: int = 5000) -> XmlEditContext:
    guard_no_dtd(xml_bytes, MAX_XML_BYTES)
    try:
        tree = ET.ElementTree(ET.fromstring(xml_bytes, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))))
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
    for el in root_el:
        inner = _inner(el)
        cid = (inner.get("id") if inner is not None else None) or el.get("id")
        if cid is None:
            continue
        if cid in cells:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "stored XML has duplicate cell IDs", [cid])
        cells[cid] = el
        count += 1
        if count > max_cells:
            raise ApiException(ErrorCode.DRAWIO_UNSUPPORTED_CONTENT, "stored XML exceeds the cell limit")
    return XmlEditContext(tree=tree, model=model, root_el=root_el, cells=cells)


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
    seen = {cell_id}
    while parent_id and parent_id not in ("0", "1"):
        if parent_id in seen:
            raise ApiException(ErrorCode.DRAWIO_PARSE_FAILED, "XML cell parent cycle")
        seen.add(parent_id)
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


def _style_overlay(previous: str, resolved: str, keys: set[str]) -> str:
    current = parse_style(previous)
    generated = parse_style(resolved)
    for key in keys:
        current.pop(key, None)
    current.update((key, value) for key, value in generated.items() if key in keys)
    return "".join(f"{key}={value};" if value else f"{key};" for key, value in current.items())


def _set_points(ctx: XmlEditContext, inner: ET.Element, points: list) -> None:
    geometry = _ensure_geometry(inner)
    geometry.set("relative", "1")
    for item in geometry.findall("Array"):
        if item.get("as") == "points":
            geometry.remove(item)
    if points:
        origin = _abs_geometry(ctx, inner.get("parent", "1")) or {"x": 0, "y": 0}
        array = ET.SubElement(geometry, "Array", {"as": "points"})
        for point in points:
            ET.SubElement(array, "mxPoint", {
                "x": _fmt(point["x"] - origin["x"]), "y": _fmt(point["y"] - origin["y"]),
            })


def apply_resolved_xml(
    ctx: XmlEditContext, old: GraphDocument, new: GraphDocument, resolved: dict,
    mapper: CellMapper, operations: list, manual: dict, *, restyle=False,
) -> tuple[bytes, set[str]]:
    """Apply the final net change, preserving untouched and unrecognized cells."""
    prior = {obj.id: obj for obj in [*old.nodes, *old.groups, *old.edges]}
    remaining = {obj.id for obj in [*new.nodes, *new.groups, *new.edges]}
    known = set(mapper.map.values())
    unknown = set(ctx.cells) - known - {"0", "1"}
    deletion = {mapper.map[id_] for id_ in set(prior) - remaining if id_ in mapper.map}
    for id_ in unknown:
        cell = _inner(ctx.cells[id_])
        if cell is not None and deletion.intersection(cell.get(key) for key in ("parent", "source", "target")):
            raise ApiException(ErrorCode.UNKNOWN_CELL_LOSS, "不能删除仍被未映射元素引用的图形", [id_])
    for id_ in deletion:
        el = ctx.cells.pop(id_, None)
        if el is not None:
            ctx.root_el.remove(el)
    changes = {}
    for op in operations:
        changes.setdefault(op["id"], {}).update(op.get("changes") or {})

    def element(id_: str, kind: str, label: str) -> tuple[ET.Element, bool]:
        mapped = getattr(mapper, f"{kind}_cell")(id_)
        created = id_ not in prior
        el = ctx.cells.get(mapped)
        if created:
            if el is not None:
                raise ApiException(ErrorCode.GRAPH_DUPLICATE_ID, "新对象与原有 XML ID 冲突", [id_])
            el = ET.SubElement(ctx.root_el, "mxCell", {"id": mapped, "parent": "1"})
            el.set("edge" if kind == "edge" else "vertex", "1")
            _set_label(el, label)
            ctx.cells[mapped] = el
            mapper.register(id_, mapped)
        if el is None:
            raise ApiException(ErrorCode.TOPOLOGY_MISMATCH, "原图缺少 GraphDocument 对应的 cell", [id_])
        return el, created

    moved = set()
    geometry_delta = set()
    group_ids = {group.id: group for group in new.groups}

    def update_vertex(obj, kind: str, parent_id: Optional[str]) -> None:
        old_obj = prior.get(obj.id)
        entry = resolved[kind + "s"][obj.id]
        el, created = element(obj.id, kind, obj.label)
        inner = _inner(el)
        original_parent = inner.get("parent")
        if created or (getattr(old_obj, "groupId" if kind == "node" else "parentId", None) != parent_id):
            inner.set("parent", mapper.group_cell(parent_id) if parent_id else "1")
        if not created and old_obj.label != obj.label:
            _set_label(el, obj.label)
        change = changes.get(obj.id, {})
        locked = manual.get(kind + "s", {}).get(obj.id, {}).get("manualStyleLocked")
        if created or restyle and not locked:
            inner.set("style", entry["style"])
        elif "style" in change or kind == "node" and "properties" in change:
            requested = set(change.get("style") or {})
            if requested & {"shapeId", "shape", "icon", "iconTheme"} or "deviceType" in (change.get("properties") or {}):
                requested |= ICON_KEYS
            if "properties" in change:
                requested |= {"aiDeviceType", "aiNetworkRole"}
            inner.set("style", _style_overlay(inner.get("style", ""), entry["style"], requested))
        elif kind == "node" and old_obj.label != obj.label and not locked and "verticalLabelPosition=bottom" in inner.get("style", ""):
            inner.set("style", _style_overlay(inner.get("style", ""), entry["style"], {"labelWidth"}))
        placement = obj.geometry
        if placement and (created or placement != old_obj.geometry or original_parent != inner.get("parent") or parent_id in moved):
            geo = _ensure_geometry(inner)
            parent_abs = _abs_geometry(ctx, inner.get("parent", "1")) or {"x": 0, "y": 0}
            for key in ("x", "y", "width", "height"):
                value = getattr(placement, key) - (parent_abs.get(key, 0) if key in ('x', 'y') else 0)
                geo.set(key, _fmt(value))
            geometry_delta.add(obj.id)
            if created or not old_obj.geometry or (placement.x, placement.y) != (old_obj.geometry.x, old_obj.geometry.y):
                moved.add(obj.id)

    visited = set()
    def group_first(group) -> None:
        if group.id in visited:
            return
        if group.parentId:
            group_first(group_ids[group.parentId])
        update_vertex(group, "group", group.parentId)
        visited.add(group.id)
    for group in new.groups:
        group_first(group)
    for node in new.nodes:
        update_vertex(node, "node", node.groupId)

    moved_cells = {mapper.map[id_] for id_ in moved}
    for edge in new.edges:
        ent = resolved["edges"][edge.id]
        old_edge = prior.get(edge.id)
        el, created = element(edge.id, "edge", ent["value"])
        inner = _inner(el)
        change = changes.get(edge.id, {})
        reconnected = created or (edge.source, edge.target) != (old_edge.source, old_edge.target)
        recalculate = reconnected or "waypoints" in change or bool({edge.source, edge.target} & geometry_delta)
        mark = manual.get("edges", {}).get(edge.id, {})
        locked = mark.get("manualStyleLocked")
        if reconnected:
            inner.set("source", mapper.node_cell(edge.source))
            inner.set("target", mapper.node_cell(edge.target))
        if restyle or not created and old_edge.label != edge.label:
            _set_label(el, ent["value"])
        if created or restyle and not locked:
            inner.set("style", ent["style"])
        else:
            keys = set(change.get("style") or {})
            if recalculate and not locked:
                keys.update(ROUTE_KEYS - set(edge.style))
            if {"kind", "direction"} & change.keys():
                keys.update(EDGE_SEMANTIC_KEYS)
                if locked:
                    keys.difference_update({"strokeColor", "strokeWidth"})
            if keys:
                inner.set("style", _style_overlay(inner.get("style", ""), ent["style"], keys))
        parent_moved = inner.get("parent") in moved_cells
        if mark.get("pathSource") == "manual" and "waypoints" not in change:
            if parent_moved and edge.waypoints:
                _set_points(ctx, inner, [point.model_dump() for point in edge.waypoints])
        elif created or "waypoints" in change or (restyle or recalculate) and not locked:
            _set_points(ctx, inner, ent.get("waypoints") or [])
    if geometry_delta:
        for key in ("pageWidth", "pageHeight"):
            previous = float(ctx.model.get(key) or 0)
            if resolved[key] > previous:
                ctx.model.set(key, str(resolved[key]))
    out = ET.tostring(ctx.tree.getroot(), encoding="utf-8", xml_declaration=True)
    return out + b"\n", unknown
