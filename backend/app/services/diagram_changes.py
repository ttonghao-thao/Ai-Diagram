"""Prepare an immutable, quality-checked change against a stored diagram version."""
from __future__ import annotations

from dataclasses import dataclass

from app.importer.model_map import diff_graphs
from app.importer.visual import cell_mapping, visual_state
from app.importer.xml_edit import CellMapper, apply_resolved_xml, load_xml_context
from app.importer.xml_parser import parse_drawio_bytes
from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import Geometry, GraphDocument
from app.services.materials import catalog_version, normalize_devices


@dataclass
class PreparedChange:
    graph: GraphDocument
    xml: bytes
    mapping: dict
    visual: dict
    quality: dict
    diff: dict
    renderer_warnings: list[dict]


def require_quality(report: dict) -> None:
    if report["ok"]:
        return
    first = next((issue for issue in report["issues"] if issue["severity"] == "error"), None)
    raise ApiException(first["code"] if first else ErrorCode.RENDERER_FAILED,
                       first["message"] if first else "图纸质量检查失败", {"quality": report})


def _constraint_ids(rule) -> set[str]:
    return {rule.source, rule.target} if rule.type == "relativePosition" else set(rule.nodes)


def prepare_change(
    state, diagram_id: str, version: int, old: GraphDocument, new: GraphDocument,
    operations: list, *, scope="local", movable=(), preserve_styles=True, preserve_positions=True,
    explicit_layout=False,
) -> PreparedChange:
    store = state.version_store
    original, _ = store.read_drawio(diagram_id, version)
    parsed = parse_drawio_bytes(original, max_cells=state.settings.max_xml_cells)
    ctx = load_xml_context(original, max_cells=state.settings.max_xml_cells)
    mapping = cell_mapping(old, store.read_manifest(diagram_id, version).get("cellMapping"))
    mapper = CellMapper(mapping, old)
    previous = store.read_artifact(diagram_id, version, "visual-state") or visual_state(
        old, parsed, mapping, prior_xml=parsed, prior_mapping=mapping,
    )
    normalize_devices(new)
    rendering = new.model_copy(deep=True)
    old_ids = {obj.id for obj in [*old.nodes, *old.groups]}
    old_nodes = {node.id: node for node in old.nodes}
    old_groups = {group.id: group for group in old.groups}
    edited_layout = explicit_layout or any(op["op"] == "update_layout" for op in operations)
    edited_theme = not preserve_styles or any(op["op"] == "update_theme" for op in operations)
    changed = {}
    for op in operations:
        changed.setdefault(op["id"], {}).update(op.get("changes") or {})
    movable_ids = set(movable)
    if edited_layout and not movable_ids:
        movable_ids.update(id_ for rule in rendering.layout.constraints or () for id_ in _constraint_ids(rule))
    if edited_layout and scope == "local" and not movable_ids and not operations:
        raise ApiException(ErrorCode.SCHEMA_INVALID, "局部布局需要 nodeIds 或布局约束")
    if not edited_layout and rendering.layout.constraints:
        additions = {node.id for node in new.nodes if node.id not in old_nodes}
        rendering.layout.constraints = [rule for rule in rendering.layout.constraints
                                        if rule.type == "preservePosition" or _constraint_ids(rule) & additions]

    # Containers with unknown children cannot translate without moving them.
    protected_ancestors = set()
    unknown_ids = set(parsed.cell_by_id) - set(mapping.values()) - {"0", "1"}
    unknown_boxes = []
    for id_ in unknown_ids:
        cell = parsed.cell_by_id[id_]
        parent = cell.parent
        while parent and parent not in protected_ancestors:
            protected_ancestors.add(parent)
            ancestor = parsed.cell_by_id.get(parent)
            parent = ancestor.parent if ancestor else None
        if cell.vertex and cell.geometry and not cell.geometry.relative and cell.geometry.width and cell.geometry.height:
            origin = parsed.absolute_geometry(cell)
            if origin["x"] is not None and origin["y"] is not None:
                unknown_boxes.append(dict(origin, width=cell.geometry.width, height=cell.geometry.height))
    for group in rendering.groups:
        if group.id in old_groups and mapping.get(group.id) in protected_ancestors:
            if group.geometry and old_groups[group.id].geometry and (group.geometry.x, group.geometry.y) != (
                old_groups[group.id].geometry.x, old_groups[group.id].geometry.y
            ):
                raise ApiException(ErrorCode.LAYOUT_CONFLICT, "不能移动包含未知图形的分组", [group.id])
            group.manualLocked = True

    protected = {}
    resize = []
    original_pinned = {id_ for rule in rendering.layout.constraints or () if rule.type == "preservePosition" for id_ in rule.nodes}
    for section, prior in (("nodes", old_nodes), ("groups", old_groups)):
        for obj in getattr(rendering, section):
            old_obj = prior.get(obj.id)
            mark = previous[section].get(obj.id, {})
            if not old_obj or not old_obj.geometry:
                continue
            pinned = obj.id in original_pinned or mapping.get(obj.id) in protected_ancestors or (
                preserve_positions and (old_obj.manualLocked or mark.get("positionSource") == "manual")
            )
            if pinned and obj.geometry != old_obj.geometry:
                raise ApiException(ErrorCode.LOCKED_POSITION_CHANGED, "受保护的几何位置不能修改", [obj.id])
            if pinned:
                obj.manualLocked = True
                protected[obj.id] = old_obj.geometry.model_dump()
            elif not preserve_positions:
                obj.manualLocked = False
            if section == "nodes" and not pinned and not mark.get("manualStyleLocked") and mark.get("sizeSource") == "auto":
                style = changed.get(obj.id, {}).get("style") or {}
                props = changed.get(obj.id, {}).get("properties") or {}
                if edited_theme or set(style) & {"shapeId", "shape", "icon", "iconTheme"} or "deviceType" in props:
                    resize.append(obj.id)
    rendering.layout.preserveManualPositions = True
    if edited_layout and scope == "global" and rendering.layout.algorithm == "manual":
        rendering.layout.algorithm = "layered"

    groups = {group.id: group for group in rendering.groups}
    affected_groups = set()
    for node in rendering.nodes:
        if node.id in old_ids and node.id not in changed and node.id not in movable_ids:
            continue
        parent = node.groupId
        while parent:
            affected_groups.add(parent)
            parent = groups[parent].parentId

    context = state.materials.renderer_context(rendering) | {
        "scope": scope, "movable": sorted(movable_ids), "unknownBoxes": unknown_boxes,
        "affectedGroups": sorted(affected_groups), "resize": resize,
        "reposition": sorted(set(movable) - set(protected)) if explicit_layout and scope == "local" else [],
    }
    resolved = state.renderer.resolve(rendering.model_dump(exclude_none=True), context)
    for section in ("nodes", "groups"):
        for obj in getattr(new, section):
            geometry = resolved[section][obj.id].get("geometry")
            if geometry:
                obj.geometry = Geometry.model_validate(geometry)

    manual = previous
    if not preserve_styles:
        # A direct reset can clear style protection. User waypoints survive.
        manual = {section: {ident: mark | {"manualStyleLocked": False} for ident, mark in previous[section].items()}
                  for section in ("nodes", "groups", "edges")}
    xml, unknown = apply_resolved_xml(ctx, old, new, resolved, mapper, operations, manual, restyle=edited_theme)
    new_mapping = cell_mapping(new, mapper.map)
    after = parse_drawio_bytes(xml, max_cells=state.settings.max_xml_cells)
    diff = diff_graphs(old, new)
    if edited_layout and old.layout != new.layout:
        diff.layoutChanged.append({"from": old.layout.model_dump(exclude_none=True), "to": new.layout.model_dump(exclude_none=True)})
    if old.appearance != new.appearance:
        diff.appearanceChanged.append({"from": old.appearance.model_dump(exclude_none=True) if old.appearance else {},
                                       "to": new.appearance.model_dump(exclude_none=True) if new.appearance else {}})
    visual = visual_state(new, after, new_mapping, previous=previous, prior_xml=parsed, prior_mapping=mapping,
                          operations=operations, diff=diff)
    visual["themeId"] = resolved["theme"]["id"]
    visual["catalogVersion"] = catalog_version()
    report = state.renderer.quality(new.model_dump(exclude_none=True), xml, context | {
        "cellMapping": new_mapping, "unknownIds": sorted(unknown), "protectedGeometry": protected,
        "manualStyleIds": [ident for category in ("nodes", "groups", "edges")
                           for ident, value in visual[category].items() if value.get("manualStyleLocked")],
    })
    require_quality(report)
    return PreparedChange(new, xml, new_mapping, visual, report, diff.to_payload(), resolved["warnings"])
