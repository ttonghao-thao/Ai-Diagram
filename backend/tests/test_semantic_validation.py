"""G-02 ~ G-05: cross-object semantic constraints (docs/06 section 2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.graph.errors import GraphErrorCode, GraphValidationError
from app.graph.validate import collect_graph_issues, validate_graph
from app.schemas.graph import GraphDocument

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> GraphDocument:
    raw = json.loads((REPO_ROOT / "fixtures" / name).read_text(encoding="utf-8"))
    return GraphDocument.model_validate(raw)


def _copy(doc: GraphDocument) -> GraphDocument:
    return GraphDocument.model_validate(doc.model_dump())


@pytest.mark.parametrize("fixture_name", ["network.graph.json", "business.graph.json"])
def test_fixtures_pass_semantic_validation_without_warnings(fixture_name: str) -> None:
    doc = _load(fixture_name)
    errors, warnings = collect_graph_issues(doc)
    assert errors == []
    assert warnings == []


def test_g02_duplicate_node_id_rejected() -> None:
    doc = _load("network.graph.json")
    doc.nodes.append(doc.nodes[0].model_copy())
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    assert GraphErrorCode.GRAPH_DUPLICATE_ID in exc.value.codes


def test_g02_duplicate_id_across_entity_types_rejected() -> None:
    doc = _load("network.graph.json")
    doc.groups[0].id = doc.edges[0].id
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    assert GraphErrorCode.GRAPH_DUPLICATE_ID in exc.value.codes


def test_g03_edge_target_missing_rejected() -> None:
    doc = _load("network.graph.json")
    doc.edges[0].target = "ghost_node"
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    assert GraphErrorCode.GRAPH_INVALID_REFERENCE in exc.value.codes


def test_g03_edge_source_missing_rejected() -> None:
    doc = _load("network.graph.json")
    doc.edges[0].source = "ghost_node"
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    assert GraphErrorCode.GRAPH_INVALID_REFERENCE in exc.value.codes


def test_g04_node_group_reference_missing_rejected() -> None:
    doc = _load("network.graph.json")
    doc.nodes[3].groupId = "no_such_zone"
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    assert GraphErrorCode.GRAPH_INVALID_REFERENCE in exc.value.codes


def test_g04_group_parent_reference_missing_rejected() -> None:
    doc = _load("business.graph.json")
    doc.groups[1].parentId = "missing_parent"
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    assert GraphErrorCode.GRAPH_INVALID_REFERENCE in exc.value.codes


def test_g05_group_cycle_rejected() -> None:
    doc = _load("business.graph.json")
    doc.groups[0].parentId = "platform"
    doc.groups[1].parentId = "external"
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    assert GraphErrorCode.GRAPH_GROUP_CYCLE in exc.value.codes


def test_g05_self_parent_group_rejected() -> None:
    doc = _load("business.graph.json")
    doc.groups[0].parentId = doc.groups[0].id
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    assert GraphErrorCode.GRAPH_GROUP_CYCLE in exc.value.codes


def test_physical_edge_with_direction_yields_warning_not_error() -> None:
    doc = _load("network.graph.json")
    doc.edges[0].direction = "forward"
    errors, warnings = collect_graph_issues(doc)
    assert errors == []
    assert len(warnings) == 1
    assert warnings[0].code == GraphErrorCode.GRAPH_PHYSICAL_EDGE_DIRECTION
    assert warnings[0].severity == "warning"


def test_all_errors_collected_in_single_pass() -> None:
    doc = _load("network.graph.json")
    doc.nodes.append(doc.nodes[0].model_copy())
    doc.edges[1].target = "ghost"
    with pytest.raises(GraphValidationError) as exc:
        validate_graph(doc)
    codes = set(exc.value.codes)
    assert GraphErrorCode.GRAPH_DUPLICATE_ID in codes
    assert GraphErrorCode.GRAPH_INVALID_REFERENCE in codes


def test_nested_groups_without_cycle_are_valid() -> None:
    doc = _copy(_load("business.graph.json"))
    doc.groups[1].parentId = "external"
    warnings = validate_graph(doc)
    assert warnings == []
