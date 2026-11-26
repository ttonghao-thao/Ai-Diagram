"""Regression for collapsed device quantities in initial topology generation."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from app.importer.model_map import parse_style
from app.llm.adapter import OpenAICompatibleAdapter
from app.llm.draft_review import review_draft
from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import GraphDocument

DESCRIPTION = "三台服务器连上联交换机1，两台设备连上联交换机2，交换机1和交换机2连防火墙，防火墙通公网"


def topology(nodes, links=()):
    return {
        "schemaVersion": "1.1", "diagramId": "counted_topology",
        "name": "设备数量回归", "diagramType": "network_topology",
        "nodes": [{"id": id_, "label": label, "kind": kind} for id_, label, kind in nodes],
        "groups": [],
        "edges": [{"id": f"link_{i}", "source": a, "target": b, "kind": kind,
                   "direction": "undirected" if kind == "physical" else "forward"}
                  for i, (a, b, kind) in enumerate(links, 1)],
        "layout": {"algorithm": "layered", "direction": "DOWN", "preserveManualPositions": True},
    }


def diagram_data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def parse(client, text):
    return diagram_data(client.post("/api/v1/diagrams/parse", json={
        "text": text, "diagramType": "network_topology",
    }))


@pytest.mark.parametrize("provider", ["mock", "openai"])
def test_screenshot_text_produces_editable_servers_devices_and_exact_links(app_client, monkeypatch, provider):
    client, app = app_client
    app.state.settings.llm_enabled = True
    if provider == "openai":
        draft = topology([
            ("servers", "三台服务器", "generic"), ("devices", "两台设备", "generic"),
            ("up1", "上联交换机1", "switch"), ("up2", "上联交换机2", "switch"),
            ("fw", "防火墙", "firewall"), ("wan", "公网", "cloud"),
        ], [
            ("servers", "up1", "physical"), ("devices", "up2", "physical"),
            ("up1", "fw", "physical"), ("up2", "fw", "physical"),
            ("fw", "wan", "logical"),
        ])
        adapter = OpenAICompatibleAdapter("https://example.invalid/v1", "", "controlled-draft", max_retries=0)

        async def chat(system, user):
            assert DESCRIPTION in user
            return json.dumps(draft, ensure_ascii=False)

        monkeypatch.setattr(adapter, "_chat", chat)
        monkeypatch.setattr(app.state, "llm_adapter_factory", lambda settings: adapter)

    draft = parse(client, DESCRIPTION)
    assert draft["schemaValid"] and not any(w["requiresConfirmation"] for w in draft["documentWarnings"])
    graph = draft["graph"]
    servers = {"服务器 01", "服务器 02", "服务器 03"}
    devices = {"设备 01", "设备 02"}
    assert len(graph["nodes"]) == 9 and not graph["groups"]
    assert {node["label"] for node in graph["nodes"] if node["kind"] == "server"} == servers
    assert {node["label"] for node in graph["nodes"] if node["kind"] == "generic"} == devices
    assert all(node["properties"]["deviceTypeRaw"] == "设备" for node in graph["nodes"] if node["kind"] == "generic")
    names = {node["id"]: node["label"] for node in graph["nodes"]}
    expected_physical = {frozenset((label, "上联交换机1")) for label in servers} | {
        frozenset((label, "上联交换机2")) for label in devices
    } | {frozenset((label, "防火墙")) for label in ("上联交换机1", "上联交换机2")}
    assert len(graph["edges"]) == 8
    assert {frozenset((names[e["source"]], names[e["target"]])) for e in graph["edges"]
            if e["kind"] == "physical" and e["direction"] == "undirected"} == expected_physical
    assert [(names[e["source"]], names[e["target"]], e["direction"]) for e in graph["edges"]
            if e["kind"] == "logical"] == [("防火墙", "公网", "forward")]
    assert all(not e.get("sourcePort") and not e.get("targetPort") for e in graph["edges"])

    created = diagram_data(client.post("/api/v1/diagrams", json=graph))
    assert created["quality"]["ok"]
    exported = client.get(f'/api/v1/diagrams/{graph["diagramId"]}/export/drawio')
    assert exported.status_code == 200
    cells = ET.fromstring(exported.content).findall("diagram/mxGraphModel/root/mxCell")
    vertices = {cell.get("id"): cell for cell in cells if cell.get("vertex") == "1"}
    assert len(vertices) == 9
    assert {cell.get("value") for cell in vertices.values()} == servers | devices | {
        "上联交换机1", "上联交换机2", "防火墙", "公网",
    }
    assert all(parse_style(cell.get("style"))["shape"] == "mxgraph.cisco.servers.fileserver"
               for cell in vertices.values() if cell.get("value") in servers)
    xml_edges = [cell for cell in cells if cell.get("edge") == "1"]
    assert len(xml_edges) == 8
    assert {frozenset((vertices[e.get("source")].get("value"), vertices[e.get("target")].get("value")))
            for e in xml_edges} == expected_physical | {frozenset(("防火墙", "公网"))}


@pytest.mark.parametrize("number", ["十二", "１２"])
def test_missing_instances_are_filled_once_without_renaming_numbered_devices(number):
    doc = GraphDocument.model_validate(topology([
        ("sw", "三层交换机", "switch"), ("known", "服务器12", "generic"),
    ], [("sw", "known", "physical")]))
    text = f"三层交换机连接{number}台服务器"
    review_draft(text, doc)
    first = doc.model_dump()
    review_draft(text, doc)
    assert doc.model_dump() == first
    assert len(doc.nodes) == 13 and len(doc.edges) == 12
    assert all(node.kind == "server" for node in doc.nodes if node.id != "sw")
    assert doc.nodes[1].id == "known" and doc.nodes[1].label == "服务器12"
    assert all(edge.source == "sw" and edge.kind == "physical" for edge in doc.edges)
    assert not doc.warnings


def test_standalone_counts_create_independent_nodes_without_edges(app_client):
    text = "三台服务器，两台设备"
    client, app = app_client
    app.state.settings.llm_enabled = True
    graph = parse(client, text)["graph"]
    doc = GraphDocument.model_validate(topology([]))
    review_draft(text, doc)
    expected = [("服务器 01", "server"), ("服务器 02", "server"), ("服务器 03", "server"),
                ("设备 01", "generic"), ("设备 02", "generic")]
    assert [(node["label"], node["kind"]) for node in graph["nodes"]] == expected
    assert [(node.label, node.kind) for node in doc.nodes] == expected
    assert graph["edges"] == [] and not doc.edges


def test_counted_device_types_sharing_a_peer_can_use_the_switch_shorthand():
    doc = GraphDocument.model_validate(topology([("sw", "交换机1", "switch")]))
    review_draft("三台服务器和两台设备都连上联交换机1", doc)
    assert len(doc.nodes) == 6 and len(doc.edges) == 5 and not doc.warnings
    assert all(edge.target == "sw" and edge.kind == "physical" for edge in doc.edges)


def test_unmatched_same_type_labels_are_not_duplicated():
    doc = GraphDocument.model_validate(topology([
        ("sw", "核心交换机", "switch"), ("a", "服务器A", "server"), ("b", "服务器B", "server"),
    ], [("a", "sw", "physical"), ("b", "sw", "physical")]))
    review_draft("两台服务器连接核心交换机", doc)
    assert len(doc.nodes) == 3 and len(doc.edges) == 2
    assert any(w.code == "AMBIGUOUS_DEVICE_COUNT" and w.requiresConfirmation for w in doc.warnings)


def test_explicitly_connected_numbered_switches_remain_distinct(app_client):
    client, app = app_client
    app.state.settings.llm_enabled = True
    graph = parse(client, "交换机1连上联交换机1")["graph"]
    assert {node["label"] for node in graph["nodes"]} == {"交换机1", "上联交换机1"}
    assert len(graph["edges"]) == 1 and graph["edges"][0]["source"] != graph["edges"][0]["target"]


@pytest.mark.asyncio
async def test_invalid_model_draft_recovers_only_for_explicit_counted_topology(monkeypatch):
    adapter = OpenAICompatibleAdapter("https://example.invalid/v1", "", "controlled-draft", max_retries=1)
    calls = []

    async def truncated(system, user):
        calls.append(user)
        return '{"schemaVersion":"1.1","nodes":['

    monkeypatch.setattr(adapter, "_chat", truncated)
    result = await adapter.parse_graph(DESCRIPTION, "network_topology")
    review_draft(DESCRIPTION, result)
    assert len(calls) == 2 and len(result.nodes) == 9 and len(result.edges) == 8
    assert any(w.code == "LLM_DRAFT_RECOVERED" for w in result.warnings)
    assert not any(w.requiresConfirmation for w in result.warnings)

    with pytest.raises(ApiException) as failure:
        await adapter.parse_graph("三台服务器连园区里任意一台交换设备", "network_topology")
    assert failure.value.code == ErrorCode.LLM_INVALID_OUTPUT
    assert len(calls) == 4


def test_ambiguous_pairing_and_qualified_switch_reference_do_not_guess_connections(app_client):
    client, app = app_client
    app.state.settings.llm_enabled = True
    parsed = parse(client, "三台服务器连接两台交换机")
    assert len(parsed["graph"]["nodes"]) == 5 and not parsed["graph"]["edges"]
    assert any(w["requiresConfirmation"] for w in parsed["documentWarnings"])

    doc = GraphDocument.model_validate(topology([
        ("servers", "三台服务器", "generic"), ("up", "上联交换机1", "switch"), ("down", "下联交换机1", "switch"),
    ], [("servers", "up", "physical")]))
    review_draft("三台服务器连接交换机1", doc)
    assert len(doc.nodes) == 3 and len(doc.edges) == 1
    assert {w.code for w in doc.warnings if w.requiresConfirmation} == {"AMBIGUOUS_DEVICE_COUNT", "AMBIGUOUS_RELATION"}


def test_ambiguous_or_negated_source_never_expands_a_model_edge():
    for label, statement in [
        ("三台服务器或两台设备", "三台服务器或两台设备连交换机"),
        ("三台服务器", "三台服务器不连交换机"),
    ]:
        doc = GraphDocument.model_validate(topology([
            ("batch", label, "generic"), ("sw", "交换机", "switch"),
        ], [("batch", "sw", "physical")]))
        review_draft(statement, doc)
        assert len(doc.nodes) == 2 and len(doc.edges) == 1
        assert any(w.requiresConfirmation for w in doc.warnings)
