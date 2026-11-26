"""Cisco icon theme (default for network_topology) on the backend side:
rendered output, importer reverse mapping, and theme-aware directed XML edits."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from app.importer.model_map import STENCIL_KIND_MAP, _kind_from_style, parse_style
from tests.conftest import load_fixture


def _cells(xml: bytes) -> dict:
    root = ET.fromstring(xml).find("diagram/mxGraphModel/root")
    return {c.get("id"): c for c in root.findall("mxCell")}


def test_network_diagram_renders_with_cisco_icons_and_straight_edges(app_client) -> None:
    client, _ = app_client
    assert client.post("/api/v1/diagrams", json=load_fixture("network.graph.json")).status_code == 200
    cells = _cells(client.get("/api/v1/diagrams/sample_network/export/drawio?version=1").content)
    assert "shape=mxgraph.cisco.misc.route_switch_processor" in cells["n_core_switch"].get("style")
    assert "shape=mxgraph.cisco.security.ios_firewall" in cells["n_firewall"].get("style")
    assert "shape=mxgraph.cisco.storage.cloud" in cells["n_wan"].get("style")
    assert parse_style(cells["n_server_01"].get("style"))["shape"] == "mxgraph.cisco.servers.fileserver"
    # public network sits on top, servers on the bottom row
    geo = {k: v.find("mxGeometry") for k, v in cells.items() if k.startswith("n_")}
    abs_y = {k: float(g.get("y")) + (float(cells["g_server_zone"].find("mxGeometry").get("y")) if k.startswith("n_server") else 0)
             for k, g in geo.items()}
    assert abs_y["n_wan"] < abs_y["n_firewall"] < abs_y["n_core_switch"] < abs_y["n_server_01"]
    edge = cells["e_wan_to_fw"].get("style")
    assert "edgeStyle=orthogonalEdgeStyle" not in edge and "exitX=" not in edge
    assert "endArrow=none" in edge and "strokeColor=#000000" in edge


def test_business_diagram_keeps_its_own_theme(app_client) -> None:
    client, _ = app_client
    assert client.post("/api/v1/diagrams", json=load_fixture("business.graph.json")).status_code == 200
    cells = _cells(client.get("/api/v1/diagrams/sample_business/export/drawio?version=1").content)
    assert "shape=process" in cells["n_gateway"].get("style")
    assert "mxgraph.cisco" not in cells["n_database"].get("style")
    assert any(f"edgeStyle={mode}" in cells["e_gateway_content"].get("style")
               for mode in ("orthogonalEdgeStyle", "segmentEdgeStyle"))


def test_metadata_can_opt_a_network_diagram_out_of_cisco(app_client) -> None:
    client, _ = app_client
    graph = load_fixture("network.graph.json")
    graph["metadata"] = {"iconTheme": "networks"}
    graph["diagramId"] = "line_art_network"
    assert client.post("/api/v1/diagrams", json=graph).status_code == 200
    cells = _cells(client.get("/api/v1/diagrams/line_art_network/export/drawio?version=1").content)
    assert "shape=mxgraph.networks.firewall" in cells["n_firewall"].get("style")
    assert "mxgraph.cisco" not in cells["n_core_switch"].get("style")


def test_importer_maps_cisco_stencils_back_to_kinds() -> None:
    assert _kind_from_style("shape=mxgraph.cisco.misc.route_switch_processor;aiKind=generic")[0] == "generic"
    # without aiKind the reverse map identifies the device from the stencil
    for style, kind in [
        ("sketch=0;shape=mxgraph.cisco.routers.router;", "router"),
        ("shape=mxgraph.cisco.security.ios_firewall;", "firewall"),
        ("shape=mxgraph.cisco.misc.route_switch_processor;", "switch"),
        ("shape=mxgraph.cisco.servers.fileserver;", "server"),
        ("shape=mxgraph.cisco.servers.server_with_router;", "server"),
        ("shape=mxgraph.cisco.storage.cloud;", "cloud"),
    ]:
        assert _kind_from_style(style)[0] == kind, style
    assert len(STENCIL_KIND_MAP) >= 16


def test_directed_edits_follow_theme_and_overrides(app_client) -> None:
    client, _ = app_client
    graph = load_fixture("network.graph.json")
    graph["metadata"] = {"iconTheme": "networks"}
    assert client.post("/api/v1/diagrams", json=graph).status_code == 200
    patch = {"baseVersion": 1, "operations": [
        {"op": "add_node", "id": "extra", "value": {"label": "新增服务器", "kind": "server",
                                                   "style": {"iconTheme": "cisco"}}}
    ]}
    preview = client.post("/api/v1/diagrams/sample_network/patch/preview", json={"patch": patch})
    assert preview.status_code == 200, preview.text
    token = preview.json()["data"]["confirmationToken"]
    applied = client.post("/api/v1/diagrams/sample_network/patch/apply",
                          json={"confirmationToken": token, "baseVersion": 1})
    assert applied.status_code == 200, applied.text
    cells = _cells(client.get("/api/v1/diagrams/sample_network/export/drawio?version=2").content)
    assert "shape=mxgraph.networks.server" in cells["n_server_01"].get("style")
    assert parse_style(cells["n_extra"].get("style"))["shape"] == "mxgraph.cisco.servers.fileserver"
    assert "iconTheme" not in cells["n_extra"].get("style")
