#!/usr/bin/env python3
"""Validate deliverable contract fixtures. This is not a draw.io Desktop compatibility test."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/graph.schema.json").read_text(encoding="utf-8"))


def validate_graph(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(SCHEMA).iter_errors(data))
    assert not errors, f"{path.name}: {errors}"
    all_ids = [it["id"] for key in ("nodes", "groups", "edges") for it in data[key]]
    assert len(set(all_ids)) == len(all_ids), "duplicate id across graph entity types"
    node_ids = {n["id"] for n in data["nodes"]}
    group_ids = {g["id"] for g in data["groups"]}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in data["edges"])
    assert all(not n.get("groupId") or n["groupId"] in group_ids for n in data["nodes"])
    assert all(not g.get("parentId") or g["parentId"] in group_ids for g in data["groups"])
    print(f"PASS graph: {path.name}: {len(node_ids)} nodes, {len(data['edges'])} edges")


def validate_drawio(path: Path) -> None:
    tree = ET.parse(path)
    assert tree.getroot().tag == "mxfile"
    cells = tree.findall(".//mxCell")
    ids = {c.attrib["id"] for c in cells if "id" in c.attrib}
    assert {"0", "1"}.issubset(ids)
    assert len(ids) == len([c for c in cells if "id" in c.attrib])
    assert any(c.get("vertex") == "1" for c in cells)
    assert any(c.get("edge") == "1" for c in cells)
    for c in cells:
        if c.get("edge") == "1":
            assert c.get("source") in ids and c.get("target") in ids
        if c.get("parent"):
            assert c.get("parent") in ids
    print(f"PASS drawio XML: {path.name}: {len(cells)} cells")


if __name__ == "__main__":
    Draft202012Validator.check_schema(SCHEMA)
    for fixture in sorted((ROOT / "fixtures").rglob("*.graph.json")):
        validate_graph(fixture)
    validate_drawio(ROOT / "fixtures/network.drawio")
    print("NOTE: Windows draw.io Desktop open/edit/save test still required.")
