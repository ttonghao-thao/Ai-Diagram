"""Phase 2 acceptance tests: I-01~I-05 (import) and P-01~P-05 (patch).

Also covers XML safety (DOCTYPE/entities, oversized, compressed bombs) and
unknown-cell preservation.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.importer.xml_parser import compress_diagram_content
from app.llm.adapter import MockLlmAdapter
from app.schemas.api import ErrorCode
from tests.conftest import load_fixture


def _create(client) -> None:
    resp = client.post("/api/v1/diagrams", json=load_fixture("network.graph.json"))
    assert resp.status_code == 200, resp.text


def _rendered_xml(client) -> bytes:
    return client.get("/api/v1/diagrams/sample_network/export/drawio?version=1").content


def _modify_desktop_xml(xml: bytes) -> bytes:
    """Simulate Windows Desktop edits on the XML: rename, move, reconnect."""
    tree = ET.ElementTree(ET.fromstring(xml))
    root = tree.getroot()
    for cell in root.iter("mxCell"):
        if cell.get("id") == "n_server_01":
            cell.set("value", "服务器 01（改名）")
            geo = cell.find("mxGeometry")
            geo.set("x", "33")  # new relative position
        if cell.get("id") == "e_core_to_s2":
            cell.set("target", "n_server_01")  # reconnect to server 01
    return ET.tostring(tree.getroot(), encoding="unicode").encode("utf-8")


def _wrap_page(inner_xml: str, compressed: bool = False) -> bytes:
    if compressed:
        # drawio compresses the mxGraphModel element, not the whole mxfile.
        model = "<mxGraphModel" + inner_xml.split("<mxGraphModel", 1)[1].rsplit("</mxGraphModel>", 1)[0] + "</mxGraphModel>"
        content = compress_diagram_content(model)
        doc = f'<diagram id="page-1" name="compressed">{content}</diagram>'
    else:
        model = inner_xml.split("<mxGraphModel", 1)[1].rsplit("</mxGraphModel>", 1)[0]
        doc = f'<diagram id="page-1" name="plain"><mxGraphModel{model}</mxGraphModel>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="ai-diagram-studio" compressed="false">\n'
        f"  {doc}\n"
        "</mxfile>\n"
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# I-series: import
# ---------------------------------------------------------------------------

def test_i01_uncompressed_import_roundtrip_no_diff(app_client) -> None:
    client, _ = app_client
    _create(client)
    xml = _rendered_xml(client)
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("diagram.drawio", xml, "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["diff"]["summary"]["total"] == 0
    assert data["unknownCellCount"] == 0

    commit = client.post("/api/v1/diagrams/sample_network/import/commit",
                         json={"confirmationToken": data["confirmationToken"], "baseVersion": 1})
    assert commit.status_code == 200, commit.text
    assert commit.json()["data"]["version"]["origin"] == "desktop_import"

    # The committed graph matches the v1 graph exactly (positions preserved).
    v1 = client.get("/api/v1/diagrams/sample_network?version=1").json()["data"]["graph"]
    v2 = client.get("/api/v1/diagrams/sample_network?version=2").json()["data"]["graph"]
    assert v1["nodes"] == v2["nodes"]
    assert v2["layout"]["algorithm"] == "manual"  # desktop positions are authoritative


def test_i01_desktop_edits_produce_diff_and_commit(app_client) -> None:
    client, _ = app_client
    _create(client)
    edited = _modify_desktop_xml(_rendered_xml(client))
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("diagram.drawio", edited, "application/xml")},
        data={"baseVersion": 1},
    )
    data = resp.json()["data"]
    diff = data["diff"]
    assert "server_01" in diff["nodeRenamed"][0]["id"]
    assert any(m["id"] == "server_01" for m in diff["nodeMoved"])
    assert any(r["id"] == "core_to_s2" for r in diff["edgeReconnected"])
    assert data["requiresConfirmation"] is True

    commit = client.post("/api/v1/diagrams/sample_network/import/commit",
                         json={"confirmationToken": data["confirmationToken"], "baseVersion": 1})
    assert commit.status_code == 200
    graph = client.get("/api/v1/diagrams/sample_network?version=2").json()["data"]["graph"]
    renamed = next(n for n in graph["nodes"] if n["id"] == "server_01")
    assert renamed["label"] == "服务器 01（改名）"
    edge = next(e for e in graph["edges"] if e["id"] == "core_to_s2")
    assert edge["target"] == "server_01"
    # XML stored verbatim: the edited bytes equal the stored file.
    stored = client.get("/api/v1/diagrams/sample_network/export/drawio?version=2").content
    assert stored == edited


def test_i02_compressed_desktop_xml_import(app_client) -> None:
    client, _ = app_client
    _create(client)
    inner = _rendered_xml(client).decode("utf-8")
    compressed_file = _wrap_page(inner, compressed=True)
    assert b"<mxGraphModel" not in compressed_file.split(b"</mxfile>")[0].split(b"<diagram")[1].split(b">", 1)[1][:40]

    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("compressed.drawio", compressed_file, "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["diff"]["summary"]["total"] == 0

    commit = client.post("/api/v1/diagrams/sample_network/import/commit",
                         json={"confirmationToken": data["confirmationToken"], "baseVersion": 1})
    assert commit.status_code == 200
    assert commit.json()["data"]["normalizedFromCompressed"] is True
    # The stored page is normalized to uncompressed single-page XML so later
    # AI patches are never refused on encoding grounds (P0-1 fix).
    stored = client.get("/api/v1/diagrams/sample_network/export/drawio?version=2").content
    assert b"<mxGraphModel" in stored

    # Dead-end closed: an AI patch applies cleanly on top of the normalized version.
    patch = {
        "baseVersion": 2,
        "operations": [{"op": "update_node", "id": "core_switch", "changes": {"label": "核心交换机（改）"}}],
    }
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 200, preview.text
    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": preview.json()["data"]["confirmationToken"], "baseVersion": 2,
    })
    assert apply.status_code == 200, apply.text


def test_i03_unknown_custom_cell_preserved(app_client) -> None:
    client, _ = app_client
    _create(client)
    xml = _rendered_xml(client).decode("utf-8")
    injected = xml.replace(
        "<mxCell id=\"1\" parent=\"0\" />",
        "<mxCell id=\"1\" parent=\"0\" />\n"
        "        <mxCell id=\"custom_shape\" value=\"自定义对象\" style=\"shape=hexagon;fillColor=#FF0000;\" vertex=\"1\" parent=\"1\">"
        "<mxGeometry x=\"700\" y=\"40\" width=\"120\" height=\"80\" as=\"geometry\" />"
        "</mxCell>",
        1,
    )
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("edited.drawio", injected.encode("utf-8"), "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["unknownCellCount"] == 1
    codes = {w["code"] for w in data["warnings"]}
    assert "UNKNOWN_CELLS_PRESERVED" in codes

    commit = client.post("/api/v1/diagrams/sample_network/import/commit",
                         json={"confirmationToken": data["confirmationToken"], "baseVersion": 1})
    assert commit.status_code == 200
    stored = client.get("/api/v1/diagrams/sample_network/export/drawio?version=2").content
    assert b'id="custom_shape"' in stored  # never dropped

    # A subsequent patch must not touch the unknown cell.
    patch = {
        "baseVersion": 2,
        "operations": [
            {"op": "add_node", "id": "new_srv",
             "value": {"id": "new_srv", "label": "新服务器", "kind": "server"}},
            {"op": "add_edge", "id": "link_new",
             "value": {"id": "link_new", "source": "core_switch", "target": "new_srv",
                       "kind": "physical", "direction": "undirected"}},
        ],
    }
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 200, preview.text
    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": preview.json()["data"]["confirmationToken"], "baseVersion": 2,
    })
    assert apply.status_code == 200, apply.text
    stored3 = client.get("/api/v1/diagrams/sample_network/export/drawio?version=3").content
    assert b'custom_shape' in stored3 and b"shape=hexagon" in stored3
    assert b"n_new_srv" in stored3


def test_i04_multi_page_file_rejected_and_original_untouched(app_client) -> None:
    client, _ = app_client
    _create(client)
    xml = _rendered_xml(client).decode("utf-8")
    model = xml.split("<mxGraphModel", 1)[1].rsplit("</mxGraphModel>", 1)[0]
    multi = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<mxfile host="x" compressed="false">\n'
        f"  <diagram id=\"p1\" name=\"A\"><mxGraphModel{model}</mxGraphModel></diagram>\n"
        f"  <diagram id=\"p2\" name=\"B\"><mxGraphModel{model}</mxGraphModel></diagram>\n"
        "</mxfile>\n"
    ).encode("utf-8")
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("multi.drawio", multi, "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == ErrorCode.DRAWIO_UNSUPPORTED_CONTENT
    versions = client.get("/api/v1/diagrams/sample_network/versions").json()["data"]
    assert versions["currentVersion"] == 1  # original untouched


def test_i05_doctype_entity_rejected(app_client) -> None:
    client, _ = app_client
    _create(client)
    evil = (
        '<?xml version="1.0"?><!DOCTYPE mxfile [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        "<mxfile><diagram id=\"p\" name=\"x\"><mxGraphModel><root>"
        "<mxCell id=\"0\"/><mxCell id=\"1\" parent=\"0\"/><mxCell id=\"n_a\" value=\"&xxe;\" vertex=\"1\"/>"
        "</root></mxGraphModel></diagram></mxfile>"
    ).encode("utf-8")
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("evil.drawio", evil, "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ErrorCode.DRAWIO_PARSE_FAILED
    assert "DOCTYPE" in resp.json()["error"]["message"]


def test_i05_oversized_upload_rejected(app_client, monkeypatch, tmp_path) -> None:
    client, app = app_client
    _create(client)
    monkeypatch.setattr(app.state.settings, "max_drawio_upload_bytes", 64)
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("big.drawio", _rendered_xml(client), "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == ErrorCode.DRAWIO_UPLOAD_TOO_LARGE


def test_i05_compressed_bomb_rejected(app_client) -> None:
    client, _ = app_client
    _create(client)
    # 8000 x ~1KB cells -> ~8MB decompressed, well above the 6MB cap.
    filler = "A" * 1000
    cells = "".join(f"<mxCell id='pad_{i}' value='{filler}'/>" for i in range(8000))
    bomb_xml = f"<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>{cells}</root></mxGraphModel>"
    content = compress_diagram_content(bomb_xml)
    data = (
        f'<?xml version="1.0"?><mxfile><diagram id="p" name="b">{content}</diagram></mxfile>'.encode("utf-8")
    )
    assert len(data) < 10 * 1024 * 1024  # small on disk, huge decompressed
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("bomb.drawio", data, "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code in (413, 415, 400)


def test_import_requires_matching_base_version(app_client) -> None:
    client, _ = app_client
    _create(client)
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("diagram.drawio", _rendered_xml(client), "application/xml")},
        data={"baseVersion": 9},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == ErrorCode.VERSION_CONFLICT


def test_import_commit_rejects_stale_token(app_client) -> None:
    client, _ = app_client
    _create(client)
    resp = client.post("/api/v1/diagrams/sample_network/import/commit",
                       json={"confirmationToken": "nope", "baseVersion": 1})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# P-series: patch
# ---------------------------------------------------------------------------

def _add_two_servers_patch() -> dict:
    return {
        "baseVersion": 1,
        "operations": [
            {"op": "add_node", "id": "srv_new_1",
             "value": {"id": "srv_new_1", "label": "新增服务器 1", "kind": "server", "groupId": "server_zone"}},
            {"op": "add_node", "id": "srv_new_2",
             "value": {"id": "srv_new_2", "label": "新增服务器 2", "kind": "server", "groupId": "server_zone"}},
            {"op": "add_edge", "id": "link_new_1",
             "value": {"id": "link_new_1", "source": "core_switch", "target": "srv_new_1",
                       "kind": "physical", "direction": "undirected"}},
            {"op": "add_edge", "id": "link_new_2",
             "value": {"id": "link_new_2", "source": "core_switch", "target": "srv_new_2",
                       "kind": "physical", "direction": "undirected"}},
        ],
    }


def test_p01_patch_adds_nodes_and_edges_preserving_layout(app_client) -> None:
    client, _ = app_client
    _create(client)
    old_graph = client.get("/api/v1/diagrams/sample_network?version=1").json()["data"]["graph"]
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": _add_two_servers_patch()})
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    # Impacted ids include the patch objects plus their existing endpoint.
    assert set(data["impactedIds"]) == {"srv_new_1", "srv_new_2", "link_new_1", "link_new_2", "core_switch"}
    assert data["requiresConfirmation"] is False
    assert len(data["layoutPlan"]["addedNodes"]) == 2
    assert data["layoutPlan"]["movedNodes"] == []
    assert data["diff"]["summary"]["nodeAdded"] == 2

    # Preview must not change anything.
    assert client.get("/api/v1/diagrams/sample_network/versions").json()["data"]["currentVersion"] == 1

    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": data["confirmationToken"], "baseVersion": 1,
    })
    assert apply.status_code == 200, apply.text
    assert apply.json()["data"]["version"]["origin"] == "ai_patch"

    new_graph = client.get("/api/v1/diagrams/sample_network?version=2").json()["data"]["graph"]
    assert len(new_graph["nodes"]) == 8
    # Old objects keep their exact positions.
    old_pos = {n["id"]: n.get("geometry") for n in old_graph["nodes"]}
    for n in new_graph["nodes"]:
        if n["id"] in old_pos:
            assert n["geometry"] == old_pos[n["id"]], n["id"]
    # New nodes are editable vertices in the XML with correct parent/edges.
    xml = client.get("/api/v1/diagrams/sample_network/export/drawio?version=2").content
    root = ET.fromstring(xml).find("diagram/mxGraphModel/root")
    cells = {c.get("id"): c for c in root.findall("mxCell")}
    assert cells["n_srv_new_1"].get("vertex") == "1"
    assert cells["n_srv_new_1"].get("parent") == "g_server_zone"
    assert cells["e_link_new_1"].get("source") == "n_core_switch"
    assert cells["e_link_new_1"].get("target") == "n_srv_new_1"
    assert "shape=mxgraph.cisco.servers.server_with_router" in cells["n_srv_new_1"].get("style")
    assert "aiKind=server" in cells["n_srv_new_1"].get("style")
    # new edge follows the cisco theme: straight black line, no routing
    assert "strokeColor=#000000" in cells["e_link_new_1"].get("style")
    assert "edgeStyle=orthogonalEdgeStyle" not in cells["e_link_new_1"].get("style")

    # Applying the same token twice fails (one-time consumption).
    again = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": data["confirmationToken"], "baseVersion": 1,
    })
    assert again.status_code == 409


def test_p02_remove_connected_node_requires_confirmation(app_client) -> None:
    client, _ = app_client
    _create(client)
    patch = {"baseVersion": 1, "operations": [{"op": "remove_node", "id": "server_02"}]}
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 422
    assert preview.json()["error"]["code"] == ErrorCode.DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED

    patch["operations"][0]["cascade"] = True
    patch["operations"][0]["requiresConfirmation"] = True
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["requiresConfirmation"] is True
    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": preview.json()["data"]["confirmationToken"], "baseVersion": 1,
    })
    assert apply.status_code == 200
    graph = client.get("/api/v1/diagrams/sample_network?version=2").json()["data"]["graph"]
    assert "server_02" not in {n["id"] for n in graph["nodes"]}
    assert "core_to_s2" not in {e["id"] for e in graph["edges"]}  # cascade removed the edge


def test_p03_edge_reconnection_requires_confirmation(app_client) -> None:
    client, _ = app_client
    _create(client)
    patch = {
        "baseVersion": 1,
        "operations": [{"op": "update_edge", "id": "core_to_s3",
                        "changes": {"target": "server_01", "kind": "dataflow", "direction": "forward"}}],
    }
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 422
    assert preview.json()["error"]["code"] == ErrorCode.DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED

    patch["operations"][0]["requiresConfirmation"] = True
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 200
    summary = preview.json()["data"]["diff"]["summary"]
    assert summary["edgeReconnected"] == 1
    assert summary["edgeKindChanged"] == 1
    assert summary["edgeDirectionChanged"] == 1
    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": preview.json()["data"]["confirmationToken"], "baseVersion": 1,
    })
    assert apply.status_code == 200
    xml = client.get("/api/v1/diagrams/sample_network/export/drawio?version=2").content
    root = ET.fromstring(xml).find("diagram/mxGraphModel/root")
    cell = next(c for c in root.findall("mxCell") if c.get("id") == "e_core_to_s3")
    assert cell.get("target") == "n_server_01"
    # Kind/direction change rebuilds the visual style (P0-2 fix): dataflow
    # arrows replace the physical no-arrow style, markers updated. The
    # network_topology default is the cisco theme (thin black line).
    style = cell.get("style")
    assert "endArrow=block" in style and "startArrow=none" in style
    assert "strokeColor=#000000" in style
    assert "aiKind=dataflow;aiDirection=forward" in style
    assert "edgeStyle=orthogonalEdgeStyle" not in style


def test_p03_endpoint_only_change_refreshes_anchors_keeps_style(app_client) -> None:
    """Pure reconnect keeps the user style (no restyle); cisco-theme edges are
    straight lines, so no anchor keys are added."""
    client, _ = app_client
    _create(client)
    patch = {
        "baseVersion": 1,
        "operations": [{"op": "update_edge", "id": "core_to_s1",
                        "changes": {"target": "server_03"}, "requiresConfirmation": True}],
    }
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 200, preview.text
    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": preview.json()["data"]["confirmationToken"], "baseVersion": 1,
    })
    assert apply.status_code == 200
    xml = client.get("/api/v1/diagrams/sample_network/export/drawio?version=2").content
    root = ET.fromstring(xml).find("diagram/mxGraphModel/root")
    cell = next(c for c in root.findall("mxCell") if c.get("id") == "e_core_to_s1")
    style = cell.get("style")
    assert cell.get("target") == "n_server_03"
    assert "aiKind=physical" in style  # kind untouched -> no restyle
    assert "strokeColor=#000000" in style
    assert "exitX=" not in style and "entryY=" not in style  # straight line: no anchors


def test_p04_locked_object_cannot_be_moved(app_client) -> None:
    client, _ = app_client
    graph = load_fixture("network.graph.json")
    for n in graph["nodes"]:
        if n["id"] == "core_switch":
            n["manualLocked"] = True
    assert client.post("/api/v1/diagrams", json=graph).status_code == 200
    patch = {
        "baseVersion": 1,
        "operations": [{"op": "update_node", "id": "core_switch",
                        "changes": {"geometry": {"x": 500, "y": 100, "width": 150, "height": 60}}}],
    }
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 409
    assert preview.json()["error"]["code"] == ErrorCode.LAYOUT_CONFLICT


def test_p05_preview_does_not_commit_and_apply_enforces_version(app_client) -> None:
    client, _ = app_client
    _create(client)
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview",
                          json={"patch": _add_two_servers_patch()})
    token = preview.json()["data"]["confirmationToken"]
    assert client.get("/api/v1/diagrams/sample_network/versions").json()["data"]["currentVersion"] == 1

    # Advance the diagram with a legitimate new version.
    client.post("/api/v1/diagrams/sample_network/layout", json={"baseVersion": 1})
    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": token, "baseVersion": 2,
    })
    assert apply.status_code == 409  # preview was made against v1


def test_p05_patch_preview_conflicts_on_wrong_base_version(app_client) -> None:
    client, _ = app_client
    _create(client)
    patch = _add_two_servers_patch()
    patch["baseVersion"] = 3
    resp = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == ErrorCode.VERSION_CONFLICT


def test_p01_patch_cannot_change_forbidden_fields(app_client) -> None:
    client, _ = app_client
    _create(client)
    patch = {
        "baseVersion": 1,
        "operations": [{"op": "update_node", "id": "server_01", "changes": {"kind": "router"}}],
    }
    resp = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ErrorCode.SCHEMA_INVALID


def test_p04_layout_conflict_locked_group_full(app_client) -> None:
    """A manualLocked group with no free slot refuses insertion (docs/05 P-04)."""
    client, _ = app_client
    graph = load_fixture("network.graph.json")
    # Shrink the locked group so the three servers leave no free slot inside.
    for g in graph["groups"]:
        if g["id"] == "server_zone":
            g["manualLocked"] = True
            g["geometry"] = {"x": 50, "y": 260, "width": 760, "height": 160}
    assert client.post("/api/v1/diagrams", json=graph).status_code == 200
    patch = {
        "baseVersion": 1,
        "operations": [{"op": "add_node", "id": "crowded",
                        "value": {"id": "crowded", "label": "挤不进", "kind": "server",
                                  "groupId": "server_zone"}}],
    }
    resp = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == ErrorCode.LAYOUT_CONFLICT
    assert "manualLocked" in resp.json()["error"]["message"]


def test_p04_unlocked_group_grows_downward(app_client) -> None:
    """An unlocked full group accepts insertion by growing; members stay put."""
    client, _ = app_client
    graph = load_fixture("network.graph.json")
    for g in graph["groups"]:
        if g["id"] == "server_zone":
            g["geometry"] = {"x": 50, "y": 260, "width": 760, "height": 160}
    assert client.post("/api/v1/diagrams", json=graph).status_code == 200
    old_geo = {n["id"]: n.get("geometry")
               for n in client.get("/api/v1/diagrams/sample_network?version=1").json()["data"]["graph"]["nodes"]}
    patch = {
        "baseVersion": 1,
        "operations": [{"op": "add_node", "id": "crowded",
                        "value": {"id": "crowded", "label": "挤得进（可扩容）", "kind": "server",
                                  "groupId": "server_zone"}}],
    }
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    added = data["layoutPlan"]["addedNodes"][0]
    # The node lands inside (below) the group's box.
    assert added["geometry"]["y"] >= 260
    assert added["geometry"]["x"] >= 50
    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": data["confirmationToken"], "baseVersion": 1,
    })
    assert apply.status_code == 200
    graph2 = client.get("/api/v1/diagrams/sample_network?version=2").json()["data"]["graph"]
    for n in graph2["nodes"]:
        if n["id"] in old_geo and n["id"] != "crowded":
            assert n["geometry"] == old_geo[n["id"]], n["id"]


def test_instruction_based_patch_via_mock(app_client, monkeypatch) -> None:
    client, app = app_client
    _create(client)
    monkeypatch.setattr(app.state, "llm_adapter_factory", lambda settings: MockLlmAdapter())
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={
        "instruction": "新增两台服务器并连接核心交换机",
    })
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["diff"]["summary"]["nodeAdded"] == 2
    assert data["diff"]["summary"]["edgeAdded"] == 2
    apply = client.post("/api/v1/diagrams/sample_network/patch/apply", json={
        "confirmationToken": data["confirmationToken"], "baseVersion": 1,
    })
    assert apply.status_code == 200
    graph = client.get("/api/v1/diagrams/sample_network?version=2").json()["data"]["graph"]
    new_labels = {n["label"] for n in graph["nodes"]}
    assert "服务器 01" in new_labels or any("服务器" in l for l in new_labels)


def test_patch_preview_unknown_instruction_target(app_client, monkeypatch) -> None:
    client, app = app_client
    _create(client)
    monkeypatch.setattr(app.state, "llm_adapter_factory", lambda settings: MockLlmAdapter())
    resp = client.post("/api/v1/diagrams/sample_network/patch/preview", json={
        "instruction": "新增两台服务器并连接不存在的交换机A区",
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ErrorCode.AMBIGUOUS_RELATION


def test_business_edge_kinds_survive_roundtrip(app_client) -> None:
    """P0-3 fix: logical/dataflow edges keep their exact kind/direction after a
    Desktop round-trip (renderer stamps aiKind/aiDirection on every edge)."""
    client, _ = app_client
    assert client.post("/api/v1/diagrams", json=load_fixture("business.graph.json")).status_code == 200
    xml = client.get("/api/v1/diagrams/sample_business/export/drawio?version=1").content
    preview = client.post(
        "/api/v1/diagrams/sample_business/import/drawio",
        files={"file": ("b.drawio", xml, "application/xml")},
        data={"baseVersion": 1},
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["diff"]["summary"]["total"] == 0  # no edgeKindChanged, no drift

    commit = client.post("/api/v1/diagrams/sample_business/import/commit",
                         json={"confirmationToken": data["confirmationToken"], "baseVersion": 1})
    assert commit.status_code == 200
    graph = client.get("/api/v1/diagrams/sample_business?version=2").json()["data"]["graph"]
    kinds = {e["id"]: e["kind"] for e in graph["edges"]}
    assert kinds == {
        "partner_gateway": "logical",
        "gateway_content": "dataflow",
        "content_db": "dataflow",
        "client_gateway": "logical",
    }
    dirs = {e["id"]: e["direction"] for e in graph["edges"]}
    assert dirs["content_db"] == "bidirectional"
    assert dirs["partner_gateway"] == "forward"


def test_desktop_arrow_change_reported_as_kind_change(app_client) -> None:
    """An edge whose arrows were edited directly in Desktop (no aiKind) falls
    back to arrow heuristics AND the resulting kind change is reported in the
    diff instead of silently overwriting the graph."""
    client, _ = app_client
    _create(client)
    xml = ET.fromstring(_rendered_xml(client))
    # Change the actual fields, independent of template key ordering.
    from app.importer.model_map import parse_style

    for cell in xml.findall(".//mxCell[@edge='1']"):
        style = parse_style(cell.get("style"))
        assert style.pop("aiKind") == "physical"
        assert style.pop("aiDirection") == "undirected"
        style.update({"endArrow": "block", "endFill": "1"})
        cell.set("style", "".join(f"{key}={value};" for key, value in style.items()))
    edited = ET.tostring(xml, encoding="utf-8")
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("edited.drawio", edited, "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # The 5 physical edges all became heuristic dataflow edges...
    assert data["diff"]["summary"]["edgeKindChanged"] == 5
    # ...and the change is explicitly visible instead of silent.
    kinds_to = {c["to"] for c in data["diff"]["edgeKindChanged"]}
    assert kinds_to == {"dataflow"}
