"""Phase 1 acceptance tests: A-01~A-03 (generation paths) and V-01~V-03 (versioning)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.llm.adapter import MockLlmAdapter
from app.schemas.api import ApiException, ErrorCode
from tests.conftest import load_fixture


# ---------------------------------------------------------------------------
# A-series: generation paths
# ---------------------------------------------------------------------------

def test_a01_llm_disabled_json_generation_full_flow(app_client) -> None:
    client, _ = app_client
    graph = load_fixture("network.graph.json")

    resp = client.post("/api/v1/diagrams", json=graph)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requestId"]
    data = body["data"]
    assert data["diagram"]["id"] == "sample_network"
    assert data["diagram"]["currentVersion"] == 1
    assert data["version"]["origin"] == "initial"
    assert data["version"]["sha256"]

    # Export the initial version and verify it is a real .drawio file.
    export = client.get("/api/v1/diagrams/sample_network/export/drawio")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/xml")
    assert export.headers["content-disposition"].startswith('attachment; filename="sample_network_v0001.drawio"')
    assert export.headers["X-Content-SHA256"] == data["version"]["sha256"]
    assert export.content.startswith(b"<?xml")
    assert b"<mxfile" in export.content

    # Version listing shows exactly one version.
    versions = client.get("/api/v1/diagrams/sample_network/versions").json()["data"]
    assert versions["currentVersion"] == 1
    assert len(versions["versions"]) == 1


def test_a01_health_reports_renderer_and_llm_state(app_client) -> None:
    client, _ = app_client
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    data = health.json()["data"]
    assert data["status"] == "ok"
    assert data["rendererAvailable"] is True
    assert data["llm"]["enabled"] is False


def test_a02_llm_invalid_output_is_rejected_and_writes_nothing(app_client, monkeypatch, tmp_path) -> None:
    client, app = app_client
    graph = load_fixture("business.graph.json")
    assert client.post("/api/v1/diagrams", json=graph).status_code == 200

    def broken_factory(settings):
        class Broken:
            name = "mock"

            async def parse_graph(self, text, diagram_type):
                raise ApiException(ErrorCode.LLM_INVALID_OUTPUT, "simulated invalid output")

            async def propose_patch(self, instruction, graph_doc, base_version):
                raise ApiException(ErrorCode.LLM_INVALID_OUTPUT, "simulated invalid output")

        return Broken()

    monkeypatch.setattr(app.state, "llm_adapter_factory", broken_factory)
    resp = client.post("/api/v1/diagrams/parse", json={"text": "一台核心交换机连接三台服务器", "diagramType": "network_topology"})
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == ErrorCode.LLM_INVALID_OUTPUT

    # Nothing was written: still exactly one diagram with one version.
    diagrams = client.get("/api/v1/diagrams").json()["data"]["diagrams"]
    assert len(diagrams) == 1
    versions = client.get("/api/v1/diagrams/sample_business/versions").json()["data"]
    assert len(versions["versions"]) == 1


def test_a02_parse_disabled_llm_returns_llm_unavailable(app_client) -> None:
    client, _ = app_client
    resp = client.post("/api/v1/diagrams/parse", json={"text": "一台核心交换机", "diagramType": "network_topology"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ErrorCode.LLM_UNAVAILABLE


def test_a03_mock_parse_ambiguous_relation_warns_without_fabricating_edges(app_client, monkeypatch) -> None:
    client, app = app_client
    monkeypatch.setattr(app.state, "llm_adapter_factory", lambda settings: MockLlmAdapter())

    resp = client.post("/api/v1/diagrams/parse", json={
        "text": "服务器连接到网络。", "diagramType": "network_topology",
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    # The clause "服务器连接到网络" resolves "网络" to the cloud kind, so it is
    # a parseable edge; use a genuinely endpoint-less clause instead:
    resp2 = client.post("/api/v1/diagrams/parse", json={
        "text": "服务器连接。", "diagramType": "network_topology",
    })
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]
    ambiguous = [w for w in data2["documentWarnings"] if w["code"] == "AMBIGUOUS_RELATION"]
    assert ambiguous and ambiguous[0]["requiresConfirmation"] is True
    # The ambiguous clause produced no fabricated edges.
    assert data2["graph"]["edges"] == []


def test_a03_mock_parse_never_invents_ips_or_connections(app_client, monkeypatch) -> None:
    client, app = app_client
    monkeypatch.setattr(app.state, "llm_adapter_factory", lambda settings: MockLlmAdapter())
    resp = client.post("/api/v1/diagrams/parse", json={
        "text": "一台核心交换机连接三台服务器，服务器使用192.0.2.0/24网段。",
        "diagramType": "network_topology",
    })
    assert resp.status_code == 200
    graph = resp.json()["data"]["graph"]
    assert len(graph["nodes"]) == 4  # 1 switch + 3 servers
    assert len(graph["edges"]) == 3
    for edge in graph["edges"]:
        assert edge["kind"] == "physical"
        assert edge["direction"] == "undirected"
    for node in graph["nodes"]:
        assert set(node["properties"]) <= {"deviceType", "deviceTypeRaw", "networkRole", "tier"}
        assert not any("192.0.2" in str(v) for v in node["properties"].values())
    ip_warnings = [w for w in resp.json()["data"]["documentWarnings"] if w["code"] == "IP_ADDRESSES_NOT_PARSED"]
    assert ip_warnings, "presence of IPs must produce an explicit non-parsed warning"


def test_a03_unknown_device_type_kept_as_generic_with_device_type(app_client, monkeypatch) -> None:
    client, app = app_client
    monkeypatch.setattr(app.state, "llm_adapter_factory", lambda settings: MockLlmAdapter())
    resp = client.post("/api/v1/diagrams/parse", json={
        "text": "核心交换机连接一台激光打印机。", "diagramType": "network_topology",
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    printer = next(n for n in data["graph"]["nodes"] if "打印机" in n["label"])
    assert printer["kind"] == "generic"
    assert printer["properties"]["deviceType"] == "激光打印机"
    guessed = [w for w in data["documentWarnings"] if w["code"] == "DEVICE_TYPE_GUESSED"]
    assert guessed


# ---------------------------------------------------------------------------
# V-series: version transactions
# ---------------------------------------------------------------------------

def _create_sample(client) -> None:
    graph = load_fixture("network.graph.json")
    resp = client.post("/api/v1/diagrams", json=graph)
    assert resp.status_code == 200


def test_v01_new_version_does_not_overwrite_v1(app_client) -> None:
    client, _ = app_client
    _create_sample(client)
    v1_bytes = client.get("/api/v1/diagrams/sample_network/export/drawio?version=1").content
    v1_manifest = json.loads(
        (client.app.state.version_store.version_dir("sample_network", 1) / "manifest.json").read_text(encoding="utf-8")
    )

    resp = client.post("/api/v1/diagrams/sample_network/layout", json={"baseVersion": 1})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["version"]["version"] == 2
    assert data["version"]["parentVersion"] == 1

    # v1 files untouched.
    store = client.app.state.version_store
    v1_dir = store.version_dir("sample_network", 1)
    assert (v1_dir / "diagram.drawio").read_bytes() == v1_bytes
    v1_manifest_after = json.loads((v1_dir / "manifest.json").read_text(encoding="utf-8"))
    assert v1_manifest_after == v1_manifest
    assert v1_manifest_after["version"] == 1
    # Both versions exist with distinct hashes (ELK re-layout may shift coords).
    v2_bytes = client.get("/api/v1/diagrams/sample_network/export/drawio?version=2").content
    assert v2_bytes.startswith(b"<?xml")
    versions = client.get("/api/v1/diagrams/sample_network/versions").json()["data"]["versions"]
    assert [v["version"] for v in versions] == [1, 2]


def test_v02_stale_base_version_conflict(app_client) -> None:
    client, _ = app_client
    _create_sample(client)
    client.post("/api/v1/diagrams/sample_network/layout", json={"baseVersion": 1})
    resp = client.post("/api/v1/diagrams/sample_network/layout", json={"baseVersion": 1})
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == ErrorCode.VERSION_CONFLICT
    assert body["error"]["details"]["currentVersion"] == 2


def test_v03_write_failure_does_not_advance_current_version(app_client, monkeypatch) -> None:
    client, app = app_client
    _create_sample(client)
    store = app.state.version_store

    def broken_insert(row):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(store.db, "insert_version", broken_insert)
    resp = client.post("/api/v1/diagrams/sample_network/layout", json={"baseVersion": 1})
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == ErrorCode.INTERNAL_ERROR

    # Recovery: the published directory was removed; DB unchanged.
    assert not store.version_dir("sample_network", 2).exists()
    assert store.db.get_diagram("sample_network").current_version == 1
    assert store.db.get_latest_version("sample_network").version == 1

    # The store remains usable afterwards.
    monkeypatch.undo()
    ok_resp = client.post("/api/v1/diagrams/sample_network/layout", json={"baseVersion": 1})
    assert ok_resp.status_code == 200
    assert ok_resp.json()["data"]["version"]["version"] == 2


# ---------------------------------------------------------------------------
# Errors and envelope shape
# ---------------------------------------------------------------------------

def test_create_duplicate_diagram_returns_409(app_client) -> None:
    client, _ = app_client
    _create_sample(client)
    resp = client.post("/api/v1/diagrams", json=load_fixture("network.graph.json"))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == ErrorCode.DIAGRAM_ALREADY_EXISTS


def test_invalid_graph_is_rejected_by_api(app_client) -> None:
    client, _ = app_client
    graph = load_fixture("network.graph.json")
    graph["nodes"][0]["label"] = ""  # schema violation
    resp = client.post("/api/v1/diagrams", json=graph)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ErrorCode.SCHEMA_INVALID
    # No storage was created.
    assert client.get("/api/v1/diagrams").json()["data"]["diagrams"] == []


def test_diagram_not_found(app_client) -> None:
    client, _ = app_client
    resp = client.get("/api/v1/diagrams/missing_diagram")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == ErrorCode.DIAGRAM_NOT_FOUND
    export = client.get("/api/v1/diagrams/missing_diagram/export/drawio")
    assert export.status_code == 404


def test_error_envelope_carries_request_id(app_client) -> None:
    client, _ = app_client
    resp = client.get("/api/v1/diagrams/missing")
    assert resp.headers.get("x-request-id")
    assert resp.json()["requestId"] == resp.headers["x-request-id"]
