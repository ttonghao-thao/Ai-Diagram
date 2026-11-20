"""G-01: both fixtures validate against contracts/graph.schema.json and the
Pydantic model; structural violations must raise pydantic ValidationError."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.schemas.graph import GraphDocument

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO_ROOT / "contracts/graph.schema.json").read_text(encoding="utf-8"))


def _load_fixture(name: str) -> dict:
    return json.loads((REPO_ROOT / "fixtures" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture_name", ["network.graph.json", "business.graph.json"])
def test_g01_fixtures_pass_json_schema_and_pydantic(fixture_name: str) -> None:
    raw = _load_fixture(fixture_name)
    schema_errors = list(Draft202012Validator(SCHEMA).iter_errors(raw))
    assert not schema_errors, [e.message for e in schema_errors]
    doc = GraphDocument.model_validate(raw)
    assert doc.schemaVersion == "1.0"
    assert doc.nodes, "fixture should contain nodes"


def test_schema_version_mismatch_rejected() -> None:
    raw = _load_fixture("network.graph.json")
    raw["schemaVersion"] = "2.0"
    with pytest.raises(ValidationError):
        GraphDocument.model_validate(raw)


def test_bad_id_pattern_rejected() -> None:
    raw = _load_fixture("network.graph.json")
    raw["nodes"][0]["id"] = "9bad id"
    with pytest.raises(ValidationError):
        GraphDocument.model_validate(raw)


def test_empty_label_rejected() -> None:
    raw = _load_fixture("network.graph.json")
    raw["nodes"][0]["label"] = ""
    with pytest.raises(ValidationError):
        GraphDocument.model_validate(raw)


def test_unknown_node_kind_rejected() -> None:
    raw = _load_fixture("network.graph.json")
    raw["nodes"][0]["kind"] = "spaceship"
    with pytest.raises(ValidationError):
        GraphDocument.model_validate(raw)


def test_non_positive_geometry_rejected() -> None:
    raw = _load_fixture("network.graph.json")
    raw["nodes"][0]["geometry"] = {"x": 0, "y": 0, "width": 0, "height": 40}
    with pytest.raises(ValidationError):
        GraphDocument.model_validate(raw)


def test_unknown_extra_field_rejected() -> None:
    raw = _load_fixture("network.graph.json")
    raw["nodes"][0]["colorHint"] = "red"
    with pytest.raises(ValidationError):
        GraphDocument.model_validate(raw)


def test_physical_edge_must_be_undirected_in_schema_shape() -> None:
    """direction enum still accepts the value; the semantic layer warns (see
    test_semantic_validation.py). Here we only pin the schema's field set."""
    raw = _load_fixture("network.graph.json")
    doc = GraphDocument.model_validate(raw)
    assert all(e.kind == "physical" and e.direction == "undirected" for e in doc.edges)
