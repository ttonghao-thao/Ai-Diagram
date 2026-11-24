"""Track visual provenance while keeping native style and geometry in XML."""
from __future__ import annotations

from typing import Optional

from app.importer.model_map import GraphDiff, parse_style
from app.importer.xml_parser import ParsedDrawio
from app.schemas.graph import GraphDocument


def cell_mapping(graph: GraphDocument, mapping: Optional[dict] = None) -> dict:
    supplied = mapping or {}
    return {obj.id: supplied.get(obj.id, prefix + obj.id)
            for prefix, objects in (("n_", graph.nodes), ("g_", graph.groups), ("e_", graph.edges))
            for obj in objects}


def shape_ref(style: dict) -> Optional[str]:
    native = style.get("shape", "")
    if not native.startswith("mxgraph."):
        return style.get("aiShapeId") if native == "image" else None
    identifier = native.removeprefix("mxgraph.")
    variant = style.get("prIcon") or style.get("resIcon")
    return identifier + "--" + variant.removeprefix("mxgraph.") if variant else identifier


def visual_state(
    graph: GraphDocument, parsed: ParsedDrawio, mapping: dict, *,
    previous: Optional[dict] = None, prior_xml: Optional[ParsedDrawio] = None,
    prior_mapping: Optional[dict] = None, desktop=False, operations=(), diff: Optional[GraphDiff] = None,
) -> dict:
    prior = previous or {}
    old_map = prior_mapping or {}
    changes = {}
    for op in operations:
        changes.setdefault(op["id"], {}).update(op.get("changes") or {})
    visual = {
        "themeId": (graph.appearance.themeId if graph.appearance else None) or graph.metadata.get("iconTheme")
        or ("cisco" if graph.diagramType == "network_topology" else "business"),
        "catalogVersion": "2026-11.1",
        "nodes": {}, "groups": {}, "edges": {},
    }
    for name in ("nodes", "groups", "edges"):
        for obj in getattr(graph, name):
            ident = obj.id
            new_cell = parsed.cell_by_id.get(mapping[ident])
            if new_cell is None:
                continue
            old_cell = prior_xml.cell_by_id.get(old_map.get(ident)) if prior_xml else None
            old_mark = prior.get(name, {}).get(ident, {})
            before, after = parse_style(old_cell.style if old_cell else None), parse_style(new_cell.style)
            has_style_delta = old_cell is not None and before != after
            shape = shape_ref(after)
            if diff is not None and has_style_delta:
                if shape_ref(before) != shape or before.get("image") != after.get("image"):
                    diff.shapeChanged.append({"id": ident, "from": shape_ref(before), "to": shape})
                keys = [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]
                diff.styleChanged.append({"id": ident, "keys": keys})
            mark = {}
            manual = (desktop and (not old_cell or has_style_delta)) or "style" in changes.get(ident, {})
            mark["styleSource"] = "user" if manual else old_mark.get("styleSource", "unknown" if old_cell else "auto")
            mark["manualStyleLocked"] = bool(old_mark.get("manualStyleLocked") or manual)
            if name != "edges":
                initial = "unknown" if old_cell else "auto"
                moved = resized = desktop and not old_cell
                if desktop and old_cell:
                    p = prior_xml.absolute_geometry(old_cell)
                    q = parsed.absolute_geometry(new_cell)
                    moved = p != q
                    if old_cell.geometry and new_cell.geometry:
                        resized = (old_cell.geometry.width, old_cell.geometry.height) != (new_cell.geometry.width, new_cell.geometry.height)
                explicit = "geometry" in changes.get(ident, {})
                mark["positionSource"] = "manual" if moved or explicit or obj.manualLocked else old_mark.get("positionSource", initial)
                mark["sizeSource"] = "manual" if resized or explicit or obj.manualLocked else old_mark.get("sizeSource", initial)
                if shape:
                    mark["shapeId"] = shape
            else:
                had_points = old_cell.geometry.points if old_cell and old_cell.geometry else []
                current_points = new_cell.geometry.points if new_cell.geometry else []
                if desktop and had_points != current_points or "waypoints" in changes.get(ident, {}) or obj.waypoints:
                    mark["pathSource"] = "manual"
                else:
                    mark["pathSource"] = old_mark.get("pathSource", "unknown" if old_cell else "auto")
            visual[name][ident] = mark
    return visual
