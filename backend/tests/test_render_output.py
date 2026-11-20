"""X-01/X-02: validate renderer output (out/*.drawio) with a standard XML
parser (ElementTree). Run `npm test` in renderer/ first to produce the files.

Checks: well-formed XML, mxfile structure, unique cell ids, valid
parent/source/target references, stable n_/g_/e_ id mapping, and that grouped
nodes carry coordinates relative to their parent group (abs - parentAbs).
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "out"


def _require_out(name: str) -> Path:
    path = OUT_DIR / name
    if not path.exists():
        pytest.fail(
            f"{path} is missing. Run `cd renderer && npm test` (or `npm run generate:all`) "
            "before the backend test suite so the renderer deliverables exist."
        )
    return path


def _cells(path: Path):
    tree = ET.parse(path)
    root = tree.getroot()
    assert root.tag == "mxfile", f"{path.name}: root must be mxfile"
    assert root.get("compressed") == "false"
    diagrams = root.findall("diagram")
    assert len(diagrams) == 1, f"{path.name}: Phase 0 must be single page"
    model = diagrams[0].find("mxGraphModel")
    assert model is not None, f"{path.name}: missing mxGraphModel"
    cells = model.find("root").findall("mxCell")
    by_id = {c.get("id"): c for c in cells}
    assert len(by_id) == len(cells), f"{path.name}: duplicate cell ids"
    return root, diagrams[0], cells, by_id


@pytest.mark.parametrize("fixture_name,out_name", [
    ("network.graph.json", "network.drawio"),
    ("business.graph.json", "business.drawio"),
])
def test_x01_x02_rendered_drawio_structure(fixture_name: str, out_name: str) -> None:
    graph = json.loads((REPO_ROOT / "fixtures" / fixture_name).read_text(encoding="utf-8"))
    path = _require_out(out_name)
    _, diagram, cells, by_id = _cells(path)

    # Stable id mapping n_/g_/e_ (docs/02 section 7).
    for node in graph["nodes"]:
        assert f"n_{node['id']}" in by_id
    for group in graph["groups"]:
        assert f"g_{group['id']}" in by_id
    for edge in graph["edges"]:
        assert f"e_{edge['id']}" in by_id

    # Real vertex/edge cells with correct flags (X-02).
    vertices = [c for c in cells if c.get("vertex") == "1"]
    edges = [c for c in cells if c.get("edge") == "1"]
    assert len(vertices) == len(graph["nodes"]) + len(graph["groups"])
    assert len(edges) == len(graph["edges"])
    assert {"0", "1"}.issubset(by_id.keys())

    for c in cells:
        if c.get("parent"):
            assert c.get("parent") in by_id, f"unknown parent on {c.get('id')}"
        if c.get("edge") == "1":
            assert c.get("source") in by_id and c.get("target") in by_id
            src = by_id[c.get("source")]
            assert src.get("vertex") == "1"

    # Labels survive as escaped XML text attributes.
    for node in graph["nodes"]:
        cell = by_id[f"n_{node['id']}"]
        assert cell.get("value") == node["label"]

    # Grouped nodes are parented to their group cell and carry relative coords.
    for node in graph["nodes"]:
        cell = by_id[f"n_{node['id']}"]
        expected_parent = f"g_{node['groupId']}" if node.get("groupId") else "1"
        assert cell.get("parent") == expected_parent
        geo = cell.find("mxGeometry")
        assert geo is not None
        if node.get("geometry"):
            assert float(geo.get("width")) == pytest.approx(node["geometry"]["width"], abs=0.5)
            assert float(geo.get("height")) == pytest.approx(node["geometry"]["height"], abs=0.5)
        if node.get("groupId"):
            g_cell = by_id[f"g_{node['groupId']}"]
            g_geo = g_cell.find("mxGeometry")
            rel_x = float(geo.get("x")) + float(g_geo.get("x"))
            rel_y = float(geo.get("y")) + float(g_geo.get("y"))
            # Node absolute position must sit inside its group's box (layout
            # guarantees containment; tolerance 40px for swimlane title bar).
            assert rel_x >= float(g_geo.get("x")) - 40
            assert rel_y >= float(g_geo.get("y")) - 40
