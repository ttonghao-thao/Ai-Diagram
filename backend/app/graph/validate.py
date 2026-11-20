"""Semantic validation of a GraphDocument (docs/02 section 4).

Structural rules (field types, enums, id patterns, item limits) are enforced
by the Pydantic schema in app/schemas/graph.py; this module implements the
cross-object constraints and returns machine-readable issues.
"""
from __future__ import annotations

from typing import List, Tuple

from app.graph.errors import GraphErrorCode, GraphValidationError, ValidationIssue, issue
from app.schemas.graph import GraphDocument


def collect_graph_issues(doc: GraphDocument) -> Tuple[List[ValidationIssue], List[ValidationIssue]]:
    """Run all semantic checks.

    Returns (errors, warnings). IDs must be globally unique across nodes,
    groups and edges; edge endpoints must reference existing nodes; group
    membership must form a forest (no cycles); physical edges must not imply
    a data direction.
    """
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []

    # 1. Global id uniqueness across all entity types (docs/02 section 4.1).
    seen: dict = {}
    duplicates: dict = {}
    for entity_type, items in (("node", doc.nodes), ("group", doc.groups), ("edge", doc.edges)):
        for obj in items:
            if obj.id in seen:
                duplicates.setdefault(obj.id, [seen[obj.id]]).append(entity_type)
            else:
                seen[obj.id] = entity_type
    for dup_id, types in duplicates.items():
        errors.append(issue(
            GraphErrorCode.GRAPH_DUPLICATE_ID,
            f'id "{dup_id}" is used by multiple objects ({", ".join(types)}); '
            "ids must be globally unique across nodes, groups and edges",
            [dup_id],
        ))

    node_ids = {n.id for n in doc.nodes}
    group_ids = {g.id for g in doc.groups}

    # 2. Edge endpoints must reference existing nodes (MVP: no group edges).
    for edge in doc.edges:
        missing = [pid for pid in (edge.source, edge.target) if pid not in node_ids]
        if missing:
            errors.append(issue(
                GraphErrorCode.GRAPH_INVALID_REFERENCE,
                f'edge "{edge.id}" references missing node(s): {", ".join(missing)}',
                [edge.id, *missing],
            ))

    # 3. Node.groupId / Group.parentId must reference existing groups.
    for node in doc.nodes:
        if node.groupId and node.groupId not in group_ids:
            errors.append(issue(
                GraphErrorCode.GRAPH_INVALID_REFERENCE,
                f'node "{node.id}" references missing group "{node.groupId}"',
                [node.id, node.groupId],
            ))
    for group in doc.groups:
        if group.parentId and group.parentId not in group_ids:
            errors.append(issue(
                GraphErrorCode.GRAPH_INVALID_REFERENCE,
                f'group "{group.id}" references missing parent group "{group.parentId}"',
                [group.id, group.parentId],
            ))

    # 4. Group nesting must not form cycles (including self-parents).
    group_by_id = {g.id: g for g in doc.groups}
    state: dict = {}  # id -> "visiting" | "done"
    stack: List[str] = []

    def visit(group_id: str) -> None:
        if state.get(group_id) == "done":
            return
        if state.get(group_id) == "visiting":
            start = stack.index(group_id) if group_id in stack else 0
            cycle = stack[start:] + [group_id]
            errors.append(issue(
                GraphErrorCode.GRAPH_GROUP_CYCLE,
                "group nesting forms a cycle: " + " -> ".join(cycle),
                cycle,
            ))
            state[group_id] = "done"
            return
        state[group_id] = "visiting"
        stack.append(group_id)
        parent = group_by_id[group_id].parentId
        # Missing parents are reported by the reference check above; cycle
        # detection only walks groups that actually exist.
        if parent and parent in group_by_id:
            visit(parent)
        stack.pop()
        state[group_id] = "done"

    for group in doc.groups:
        visit(group.id)

    # 5. Physical links do not imply a data direction (docs/02, docs/05 0.2).
    for edge in doc.edges:
        if edge.kind == "physical" and edge.direction != "undirected":
            warnings.append(issue(
                GraphErrorCode.GRAPH_PHYSICAL_EDGE_DIRECTION,
                f'physical edge "{edge.id}" declares direction "{edge.direction}"; '
                "physical links do not imply a data direction, so it is rendered undirected",
                [edge.id],
                severity="warning",
            ))

    return errors, warnings


def validate_graph(doc: GraphDocument) -> List[ValidationIssue]:
    """Validate a graph document.

    Raises GraphValidationError if any error-severity issue exists and
    returns the warnings otherwise. An invalid graph never reaches rendering.
    """
    errors, warnings = collect_graph_issues(doc)
    if errors:
        raise GraphValidationError(errors)
    return warnings
