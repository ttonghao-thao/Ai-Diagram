"""P1 hardening tests: streaming-limit upload, full-file DOCTYPE guard,
version rollback, manualLocked preservation across import, and TS<->Python
style-template consistency (behavioral sync check)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.importer.model_map import graph_from_cells
from app.importer.xml_parser import parse_drawio_bytes
from app.schemas.api import ApiException, ErrorCode
from tests.conftest import REPO_ROOT, load_fixture, make_settings


# ---------------------------------------------------------------------------
# Security hardening
# ---------------------------------------------------------------------------

def test_doctype_declared_after_4k_is_rejected(app_client) -> None:
    """The guard scans the WHOLE document: a DOCTYPE hidden past the first
    4 KiB (the old windowed check) must be rejected (P1 fix)."""
    client, _ = app_client
    _create(client)
    evil = (
        b'<?xml version="1.0"?><!--' + b"x" * 5000 + b"-->"
        b'<!DOCTYPE mxfile [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b'<mxfile><diagram id="p" name="x"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="n_a" value="plain" vertex="1" parent="1"/>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )
    assert evil.index(b"<!DOCTYPE") > 4096  # past the old window
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("evil.drawio", evil, "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ErrorCode.DRAWIO_PARSE_FAILED


def test_oversized_upload_is_refused_during_streaming(app_client, monkeypatch) -> None:
    """The limit is enforced chunk-by-chunk while streaming, so an oversized
    body is refused without being fully buffered."""
    client, app = app_client
    _create(client)
    monkeypatch.setattr(app.state.settings, "max_drawio_upload_bytes", 1024)
    big = _rendered_xml(client) * 20  # ~100 KB, far above the 1 KB limit
    resp = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("big.drawio", big, "application/xml")},
        data={"baseVersion": 1},
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == ErrorCode.DRAWIO_UPLOAD_TOO_LARGE


# ---------------------------------------------------------------------------
# Version rollback (docs/04 section 5.5)
# ---------------------------------------------------------------------------

def test_rollback_creates_new_version_and_keeps_history(app_client) -> None:
    client, _ = app_client
    _create(client)
    client.post("/api/v1/diagrams/sample_network/layout", json={"baseVersion": 1})
    v1_bytes = client.get("/api/v1/diagrams/sample_network/export/drawio?version=1").content

    resp = client.post("/api/v1/diagrams/sample_network/rollback",
                       json={"targetVersion": 1, "baseVersion": 2})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["version"]["version"] == 3
    assert data["version"]["origin"] == "rollback"
    assert data["rolledBackTo"] == 1

    # v3 carries v1's exact artifact bytes; v1/v2 files are untouched.
    v3_bytes = client.get("/api/v1/diagrams/sample_network/export/drawio?version=3").content
    assert v3_bytes == v1_bytes
    versions = client.get("/api/v1/diagrams/sample_network/versions").json()["data"]["versions"]
    assert [(v["version"], v["origin"]) for v in versions] == \
        [(1, "initial"), (2, "layout"), (3, "rollback")]


def test_rollback_conflict_and_missing_target(app_client) -> None:
    client, _ = app_client
    _create(client)
    stale = client.post("/api/v1/diagrams/sample_network/rollback",
                        json={"targetVersion": 1, "baseVersion": 5})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == ErrorCode.VERSION_CONFLICT
    missing = client.post("/api/v1/diagrams/sample_network/rollback",
                          json={"targetVersion": 99, "baseVersion": 1})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == ErrorCode.VERSION_NOT_FOUND


# ---------------------------------------------------------------------------
# Locking strategy (docs/02 section 8) — explicit and tested
# ---------------------------------------------------------------------------

def test_import_preserves_manual_lock_flag(app_client) -> None:
    """Strategy (documented in report §12): manualLocked is an explicit
    semantic field carried over from the current graph for surviving objects;
    Desktop moves do NOT auto-lock, unlocking stays a user decision."""
    client, _ = app_client
    graph = load_fixture("network.graph.json")
    for n in graph["nodes"]:
        if n["id"] == "core_switch":
            n["manualLocked"] = True
    assert client.post("/api/v1/diagrams", json=graph).status_code == 200

    xml = _rendered_xml(client)
    preview = client.post(
        "/api/v1/diagrams/sample_network/import/drawio",
        files={"file": ("d.drawio", xml, "application/xml")},
        data={"baseVersion": 1},
    )
    assert preview.status_code == 200
    commit = client.post("/api/v1/diagrams/sample_network/import/commit",
                         json={"confirmationToken": preview.json()["data"]["confirmationToken"],
                               "baseVersion": 1})
    assert commit.status_code == 200
    graph2 = client.get("/api/v1/diagrams/sample_network?version=2").json()["data"]["graph"]
    by_id = {n["id"]: n for n in graph2["nodes"]}
    assert by_id["core_switch"]["manualLocked"] is True   # explicit lock survives
    assert by_id["server_01"]["manualLocked"] is False    # no auto-locking


# ---------------------------------------------------------------------------
# TS <-> Python template sync (behavioral + static)
# ---------------------------------------------------------------------------

def _render_single_kind(kind: str) -> bytes:
    graph = {
        "schemaVersion": "1.0",
        "diagramId": "sync_check",
        "name": "同步检查",
        "diagramType": "network_topology",
        "nodes": [{"id": "n1", "label": "节点", "kind": kind}],
        "groups": [],
        "edges": [],
        "layout": {"algorithm": "layered", "direction": "DOWN", "preserveManualPositions": True},
    }
    out = Path("/tmp") / f"sync_{kind}.drawio"
    subprocess.run(
        ["node", str(REPO_ROOT / "renderer/dist/src/cli.js"),
         "generate", "--input", "/dev/stdin", "--output", str(out)],
        input=json.dumps(graph).encode(), check=True, capture_output=True,
    )
    return out.read_bytes()


def test_every_node_kind_roundtrips_through_importer(tmp_path) -> None:
    """Behavioral sync check: what the TypeScript renderer stamps (aiKind)
    must be restored by the Python importer for all ten kinds."""
    kinds = ["switch", "router", "firewall", "server", "vm", "cloud",
             "service", "database", "client", "generic"]
    for kind in kinds:
        xml = _render_single_kind(kind)
        parsed = parse_drawio_bytes(xml)
        result = graph_from_cells(parsed, "sync_check", "同步检查", "network_topology")
        assert result.graph.nodes[0].kind == kind, kind
        assert result.unknown_cells == []


def test_stencil_ids_match_between_ts_and_python() -> None:
    """Static sync check: the mxgraph.networks shape ids in the TypeScript
    registry and the Python XML-edit templates must be identical sets."""
    import re

    ts = (REPO_ROOT / "renderer/src/shapes/iconRegistry.ts").read_text(encoding="utf-8")
    py = (REPO_ROOT / "backend/app/importer/xml_edit.py").read_text(encoding="utf-8")
    # TS builds styles via networksStencil('name'); Python inlines the full id.
    ts_ids = set(re.findall(r"networksStencil\('([a-z_]+)'\)", ts))
    py_ids = set(re.findall(r"mxgraph\.networks\.([a-z_]+)", py))
    assert ts_ids == py_ids, f"drift: ts={sorted(ts_ids)} py={sorted(py_ids)}"
    assert len(ts_ids) >= 8  # the eight device stencils

    # Cisco theme: TS builds "shape=mxgraph.cisco.<section>.<name>" through
    # ciscoStencil('<section>.<name>'); Python inlines the full ids.
    ts_cisco = set(re.findall(r"ciscoStencil\('([a-z0-9_]+\.[a-z0-9_]+)'", ts))
    py_cisco = set(re.findall(r'_cisco\("([a-z0-9_]+\.[a-z0-9_]+)"', py))
    assert ts_cisco == py_cisco, f"cisco drift: ts={sorted(ts_cisco)} py={sorted(py_cisco)}"
    assert {"misc.route_switch_processor", "security.ios_firewall",
            "servers.server_with_router", "storage.cloud"} <= ts_cisco


def _create(client) -> None:
    resp = client.post("/api/v1/diagrams", json=load_fixture("network.graph.json"))
    assert resp.status_code == 200


def _rendered_xml(client) -> bytes:
    return client.get("/api/v1/diagrams/sample_network/export/drawio?version=1").content


def test_make_settings_helper_importable():
    """Guard against accidental removal of shared fixtures used above."""
    s = make_settings(Path("/tmp"))
    assert s.max_drawio_upload_bytes > 0
