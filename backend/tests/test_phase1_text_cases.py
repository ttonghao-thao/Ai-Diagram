"""Phase 1 gate: >=10 text cases must produce schema-valid Graph drafts.

Also archives real error cases (empty/meaningless input, ambiguous endpoints,
fabrication attempts) as explicit assertions, per docs/05 Phase 1 gate and
docs/06 section 5.
"""
from __future__ import annotations

import pytest

from app.llm.adapter import MockLlmAdapter, _infer_kind, _safe_id
from app.schemas.api import ApiException
from app.schemas.graph import GraphDocument

# 10+ structured text cases: (text, diagram_type, expected node count, expected edge count)
TEXT_CASES = [
    ("一台核心交换机连接三台服务器", "network_topology", 4, 3),
    ("外部网络接入防火墙，防火墙连接核心交换机", "network_topology", 3, 2),
    ("防火墙连接路由器，路由器连接云平台", "network_topology", 3, 2),
    ("两台虚拟机连接数据库", "network_topology", 3, 2),
    ("终端设备连接接口网关，接口网关连接内容服务", "business_architecture", 3, 2),
    ("内容服务读写中心内容库", "business_architecture", 2, 1),
    ("第三方业务系统调用接口网关", "business_architecture", 2, 1),
    ("核心交换机连接服务器01、服务器02和服务器03", "network_topology", 4, 3),
    ("路由器连接防火墙", "network_topology", 2, 1),
    ("客户端接入防火墙；防火墙连接服务器", "network_topology", 3, 2),
    ("交换机连接主机", "network_topology", 2, 1),
    ("五台客户端连接接入交换机", "network_topology", 6, 5),
]


@pytest.mark.parametrize("text,diagram_type,expect_nodes,expect_edges", TEXT_CASES)
@pytest.mark.asyncio
async def test_text_case_produces_valid_graph(text, diagram_type, expect_nodes, expect_edges):
    doc = await MockLlmAdapter().parse_graph(text, diagram_type)
    # The draft must be a fully schema-valid GraphDocument.
    assert doc.schemaVersion == "1.0"
    assert doc.diagramType == diagram_type
    assert len(doc.nodes) == expect_nodes, [n.label for n in doc.nodes]
    assert len(doc.edges) == expect_edges
    # Semantic invariants: unique ids, resolvable endpoints.
    ids = [n.id for n in doc.nodes]
    assert len(ids) == len(set(ids))
    id_set = set(ids)
    for edge in doc.edges:
        assert edge.source in id_set and edge.target in id_set
        if edge.kind == "physical":
            assert edge.direction == "undirected"
    # Never fabricate IPs or ports.
    for node in doc.nodes:
        assert not any(isinstance(v, str) and v and v[0].isdigit() for v in node.properties.values())
    for edge in doc.edges:
        assert edge.sourcePort is None and edge.targetPort is None


def test_error_case_no_devices_at_all() -> None:
    """Real error case: text without any device description."""
    import asyncio
    with pytest.raises(ApiException) as exc:
        asyncio.run(MockLlmAdapter().parse_graph("今天天气很好。", "network_topology"))
    assert exc.value.code == "LLM_INVALID_OUTPUT"


def test_error_case_self_loop_is_skipped() -> None:
    """Real edge case: subject == target collapses to no edge."""
    import asyncio
    doc = asyncio.run(MockLlmAdapter().parse_graph("防火墙连接防火墙", "network_topology"))
    assert len(doc.nodes) == 1
    assert doc.edges == []


def test_error_case_device_type_unknown_becomes_generic() -> None:
    import asyncio
    doc = asyncio.run(MockLlmAdapter().parse_graph("核心交换机连接加密机", "network_topology"))
    unknown = next(n for n in doc.nodes if n.label == "加密机")
    assert unknown.kind == "generic"
    assert unknown.properties["deviceType"] == "加密机"
    codes = {w.code for w in doc.warnings}
    assert "DEVICE_TYPE_GUESSED" in codes


def test_error_case_ambiguous_clause_not_rendered() -> None:
    import asyncio
    doc = asyncio.run(MockLlmAdapter().parse_graph("防火墙连接。核心交换机连接服务器", "network_topology"))
    # The ambiguous clause contributes nothing; the valid clause still parses.
    assert len(doc.edges) == 1
    assert any(w.code == "AMBIGUOUS_RELATION" and w.requiresConfirmation for w in doc.warnings)


def test_id_derivation_is_schema_safe_and_deterministic() -> None:
    assert _infer_kind("核心交换机")[0] == "switch"
    assert _infer_kind("神秘盒子")[0] == "generic"
    used: set = set()
    a = _safe_id("防火墙A", used)
    b = _safe_id("防火墙A", used)
    assert a and b and a != b
    # ids must match ^[A-Za-z][A-Za-z0-9_-]{0,63}$
    import re
    pattern = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    for value in (a, b):
        assert pattern.match(value)
