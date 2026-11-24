"""V1.2 API round-trip and material-library regression tests."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from app.importer.model_map import parse_style
from app.services.materials import MaterialService
from tests.conftest import load_fixture

DIAGRAM = "/api/v1/diagrams/v12_network"


def data(response, status=200):
    assert response.status_code == status, response.text
    return response.json()["data"]


def create(client, graph=None):
    return data(client.post("/api/v1/diagrams", json=graph or load_fixture("v1_2_network.graph.json")))


def cells(xml):
    root = ET.fromstring(xml).find("diagram/mxGraphModel/root")
    return root, {cell.get("id"): cell for cell in root.findall("mxCell")}


def preview(client, operations, version=1):
    response = client.post(DIAGRAM + "/patch/preview",
                           json={"patch": {"baseVersion": version, "operations": operations}})
    return data(response)


def apply(client, change, version=1):
    return data(client.post(DIAGRAM + "/patch/apply",
                            json={"baseVersion": version, "confirmationToken": change["confirmationToken"]}))


def test_t10_final_topology_places_new_node_right_of_peers(app_client):
    client, app = app_client
    first = create(client)
    assert first["quality"]["ok"]
    before = data(client.get(DIAGRAM))["graph"]
    changes = [
        {"op": "add_edge", "id": "srv4_link", "value": {
            "source": "internal_fw", "target": "srv4", "direction": "undirected", "kind": "physical",
        }},
        {"op": "add_node", "id": "srv4", "value": {"label": "服务器 04", "kind": "server", "groupId": "servers"}},
        {"op": "update_layout", "id": "v12_network", "changes": {"constraints": [
            {"type": "relativePosition", "source": "srv4", "target": "srv3", "position": "right"},
            {"type": "sameRank", "nodes": ["srv3", "srv4"]},
        ]}},
    ]
    change = preview(client, changes)
    assert change["quality"]["ok"]
    assert change["layoutPlan"]["movedNodes"] == []
    assert apply(client, change)["version"]["version"] == 2
    after = data(client.get(DIAGRAM))["graph"]
    seen = {node["id"]: node["geometry"] for node in after["nodes"]}
    assert all(seen[node["id"]] == node["geometry"] for node in before["nodes"])
    assert seen["srv4"]["x"] > seen["srv3"]["x"]
    assert seen["srv4"]["y"] == seen["srv3"]["y"]
    assert seen["srv4"]["width"] == seen["srv3"]["width"]
    assert seen["srv4"]["height"] == seen["srv3"]["height"]
    _, xml = cells(client.get(DIAGRAM + "/export/drawio").content)
    assert parse_style(xml["n_srv4"].get("style"))["shape"] == parse_style(xml["n_srv3"].get("style"))["shape"]
    version = app.state.version_store.version_dir("v12_network", 2)
    assert {"graph.json", "diagram.drawio", "manifest.json", "patch.json", "quality.json", "visual-state.json"} <= {
        path.name for path in version.iterdir()
    }
    assert app.state.db.get_version("v12_network", 2).patch_path == str(version / "patch.json")


def test_t11_t12_explicit_shape_and_theme_modify_editable_xml(app_client):
    client, _ = app_client
    create(client)
    changed = preview(client, [{"op": "update_node", "id": "srv1", "changes": {
        "style": {"shapeId": "cisco.routers.router", "strokeColor": "#777777"},
    }}])
    assert changed["diff"]["shapeChanged"] == [{"id": "srv1", "from": "cisco.servers.server_with_router",
                                              "to": "cisco.routers.router"}]
    apply(client, changed)
    updated = preview(client, [{"op": "update_theme", "id": "v12_network", "changes": {
        "themeId": "networks", "edgeLabelPolicy": "all", "edgeRouting": "orthogonal",
    }}], version=2)
    apply(client, updated, version=2)
    _, xml = cells(client.get(DIAGRAM + "/export/drawio").content)
    assert parse_style(xml["n_srv1"].get("style"))["shape"] == "mxgraph.cisco.routers.router"
    assert parse_style(xml["n_srv2"].get("style"))["shape"] == "mxgraph.networks.server"
    assert xml["e_backbone"].get("value") == "万兆主干"
    assert data(client.get(DIAGRAM))["visualState"]["themeId"] == "networks"


def test_t15_t18_desktop_changes_survive_global_relayout(app_client):
    client, app = app_client
    create(client)
    xml = ET.fromstring(client.get(DIAGRAM + "/export/drawio").content)
    root = xml.find("diagram/mxGraphModel/root")
    core = root.find("mxCell[@id='n_core']")
    core.set("style", core.get("style") + "fontSize=17;strokeColor=#C96320;")
    geo = core.find("mxGeometry")
    geo.set("x", str(float(geo.get("x")) + 36))
    geo.set("width", str(float(geo.get("width")) + 12))
    changed_edge = root.find("mxCell[@id='e_backbone']/mxGeometry")
    for child in list(changed_edge):
        changed_edge.remove(child)
    array = ET.SubElement(changed_edge, "Array", {"as": "points"})
    ET.SubElement(array, "mxPoint", {"x": "351", "y": "199"})
    native = ET.SubElement(root, "mxCell", {"id": "decoration", "parent": "1", "vertex": "1",
                                           "style": "shape=hexagon;fillColor=#AA6633;"})
    ET.SubElement(native, "mxGeometry", {"x": "780", "y": "560", "width": "32", "height": "32", "as": "geometry"})
    imported = data(client.post(DIAGRAM + "/import/preview", files={"file": ("editor.drawio", ET.tostring(xml))},
                                data={"baseVersion": 1}))
    assert imported["unknownCellCount"] == 1
    assert imported["diff"]["nodeResized"][0]["id"] == "core"
    assert imported["diff"]["styleChanged"][0]["id"] == "core"
    assert imported["diff"]["edgeWaypointsChanged"] == [{"id": "backbone"}]
    data(client.post(DIAGRAM + "/import/commit", json={
        "baseVersion": 1, "confirmationToken": imported["confirmationToken"],
    }))
    after_import = data(client.get(DIAGRAM))
    visual = after_import["visualState"]
    assert visual["nodes"]["core"]["manualStyleLocked"]
    assert visual["nodes"]["core"]["positionSource"] == "manual"
    assert visual["nodes"]["core"]["sizeSource"] == "manual"
    assert visual["edges"]["backbone"]["pathSource"] == "manual"
    assert after_import["graph"]["edges"][1]["label"] == "万兆主干"
    reflow = data(client.post(DIAGRAM + "/layout", json={"baseVersion": 2, "direction": "UP"}))
    assert reflow["quality"]["ok"]
    _, saved = cells(client.get(DIAGRAM + "/export/drawio").content)
    assert saved["n_core"].get("style") == core.get("style")
    assert saved["n_core"].find("mxGeometry").attrib == geo.attrib
    assert saved["e_backbone"].find("mxGeometry/Array/mxPoint").attrib == {"x": "351", "y": "199"}
    assert ET.tostring(saved["decoration"]) == ET.tostring(native)
    artifact = app.state.version_store.read_artifact("v12_network", 3, "quality")
    assert artifact and artifact["ok"]


def test_t19_concurrent_layout_only_one_publishes(app_client):
    client, app = app_client
    create(client)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda direction: client.post(
            DIAGRAM + "/layout", json={"baseVersion": 1, "direction": direction}
        ).status_code, ["DOWN", "UP"]))
    assert sorted(results) == [200, 409]
    assert [row.version for row in app.state.db.list_versions("v12_network")] == [1, 2]


def test_t20_read_legacy_version_verbatim_and_create_additive_1_1(app_client):
    client, app = app_client
    graph = load_fixture("network.graph.json")
    app.state.version_store.commit_new_version(
        diagram_id=graph["diagramId"], diagram_name=graph["name"], diagram_type=graph["diagramType"],
        graph=graph, drawio_bytes=b"<archival-bytes/>", origin="initial",
    )
    read = data(client.get("/api/v1/diagrams/sample_network?version=1"))
    assert read["graph"] == graph and read["visualState"] is None
    assert client.get("/api/v1/diagrams/sample_network/export/drawio?version=1").content == b"<archival-bytes/>"
    graph["diagramId"] = "legacy_input"
    create(client, graph)
    assert data(client.get("/api/v1/diagrams/legacy_input"))["graph"]["schemaVersion"] == "1.1"


def test_personal_library_search_svg_import_and_combo_roundtrip(app_client):
    client, app = app_client
    search = data(client.get("/api/v1/shapes/search", params={"q": "核心交换机"}))
    assert any(item["id"] == "cisco.misc.route_switch_processor" for item in search["items"])
    assert len(data(client.get("/api/v1/themes"))["themes"]) >= 4
    native = client.get("/api/v1/shapes/cisco.misc.route_switch_processor/thumbnail")
    assert native.status_code == 200 and native.content.startswith(b"\x89PNG")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 20"><rect width="60" height="20"/></svg>'
    uploaded = data(client.post("/api/v1/shapes/import", files={"file": ("symbol.svg", svg)}, data={"kind": "svg"}))
    asset = uploaded["items"][0]
    aid = asset["id"]
    assert asset["nativeWidth"] / asset["nativeHeight"] == 3
    assert client.get(f"/api/v1/shapes/{aid}/preview").content == svg
    prefs = {"favorites": [aid], "mappings": {"layer3_switch": aid}}
    data(client.put("/api/v1/preferences/shapes", json=prefs))
    assert MaterialService(app.state.db).preferences() == prefs
    create(client)
    _, rendered = cells(client.get(DIAGRAM + "/export/drawio").content)
    assert parse_style(rendered["n_core"].get("style"))["shape"] == "image"
    malformed = client.post("/api/v1/shapes/import",
                            files={"file": ("bad.svg", b"<svg><g onload='alert(1)'/></svg>")},
                            data={"kind": "svg"})
    assert malformed.status_code == 415

    model = """<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>
      <mxCell id="2" vertex="1" style="shape=rectangle;" parent="1">
        <mxGeometry x="5" y="20" width="30" height="40" as="geometry"/></mxCell>
      <mxCell id="3" vertex="1" style="shape=ellipse;" parent="1">
        <mxGeometry x="90" y="20" width="30" height="40" as="geometry"/></mxCell>
      <mxCell id="4" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell>
      </root></mxGraphModel>"""
    library = ET.Element("mxlibrary")
    library.text = json.dumps([{"title": "组合", "xml": model}])
    combo = data(client.post("/api/v1/shapes/import", files={"file": ("symbols.xml", ET.tostring(library))},
                             data={"kind": "library"}))["items"][0]
    assert combo["assetType"] == "cell_template" and not combo["usable"]
    exported = client.post("/api/v1/shapes/export", json={"ids": [aid, combo["id"]]})
    assert exported.status_code == 200
    restored = data(client.post("/api/v1/shapes/import", files={"file": ("restored.xml", exported.content)},
                                data={"kind": "library"}))
    assert [row["id"] for row in restored["items"]] == [aid, combo["id"]]
    assert ET.fromstring(restored["items"][1]["xml"]).find("root/mxCell[@id='4']").get("target") == "3"


def test_unverified_model_link_warns_before_generation(app_client, monkeypatch):
    from app.schemas.graph import GraphDocument

    client, app = app_client
    graph = load_fixture("v1_2_network.graph.json")
    graph["nodes"][2]["properties"]["ip"] = "192.0.2.98"

    class DraftProvider:
        name = "openai"

        async def parse_graph(self, text, diagram_type):
            return GraphDocument.model_validate(graph)

    monkeypatch.setattr(app.state, "llm_adapter_factory", lambda settings: DraftProvider())
    parsed = data(client.post("/api/v1/diagrams/parse", json={
        "text": "公网连接边界防火墙。", "diagramType": "network_topology",
    }))
    flags = {tuple(warning["relatedIds"] or []) for warning in parsed["documentWarnings"]
             if warning["requiresConfirmation"]}
    assert ("internet",) not in flags and ("backbone",) in flags
    assert "ip" not in parsed["graph"]["nodes"][2]["properties"]
