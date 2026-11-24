"""OpenAI-compatible adapter tests — the paths that only a real LLM
deployment exercises (the KeyError: 'code' bug lived here, invisible to
mock-only tests). HTTP is faked at the boundary: _chat monkeypatched or
httpx.AsyncClient replaced."""
from __future__ import annotations

import pytest

from app.llm.adapter import OpenAICompatibleAdapter
from app.llm.prompts import parse_graph_system_prompt, propose_patch_system_prompt
from app.schemas.api import ApiException, ErrorCode

VALID_GRAPH_JSON = (
    '{"schemaVersion":"1.0","diagramId":"t1","name":"测试图","diagramType":"network_topology",'
    '"nodes":[{"id":"n1","label":"核心交换机","kind":"switch"}],"groups":[],"edges":[],'
    '"layout":{"algorithm":"layered","direction":"DOWN","preserveManualPositions":true}}'
)


def _adapter(max_retries: int = 1) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        base_url="https://example.invalid/v1", api_key="k", model="test-model",
        timeout_seconds=5, max_retries=max_retries,
    )


def test_prompt_builders_render_brace_safe() -> None:
    """Regression: .format() on templates with literal JSON braces raised
    KeyError: 'code' on the first real LLM call."""
    system = parse_graph_system_prompt()
    assert "GraphDocument" in system
    assert "AMBIGUOUS_RELATION" in system          # literal brace example survives
    assert '"$defs"' in system or "properties" in system  # schema embedded
    patch_prompt = propose_patch_system_prompt()
    assert "GraphPatch" in patch_prompt and "baseVersion" in patch_prompt


@pytest.mark.asyncio
async def test_parse_graph_happy_path_with_markdown_fence(monkeypatch) -> None:
    adapter = _adapter()
    prompts: list[tuple[str, str]] = []

    async def fake_chat(system: str, user: str) -> str:
        prompts.append((system, user))
        return f"```json\n{VALID_GRAPH_JSON}\n```"

    monkeypatch.setattr(adapter, "_chat", fake_chat)
    doc = await adapter.parse_graph("一台核心交换机", "network_topology")
    assert doc.diagramId == "t1" and doc.nodes[0].kind == "switch"
    assert "一台核心交换机" in prompts[0][1]
    assert "GraphDocument" in prompts[0][0]  # system prompt carries the schema


@pytest.mark.asyncio
async def test_parse_graph_invalid_output_exhausts_retries(monkeypatch) -> None:
    adapter = _adapter(max_retries=1)
    calls: list[str] = []

    async def fake_chat(system: str, user: str) -> str:
        calls.append(user)
        return "这不是 JSON {{{ code }}}"

    monkeypatch.setattr(adapter, "_chat", fake_chat)
    with pytest.raises(ApiException) as exc:
        await adapter.parse_graph("文本", "network_topology")
    assert exc.value.code == ErrorCode.LLM_INVALID_OUTPUT
    assert len(calls) == 2  # initial attempt + one repair round
    assert "校验失败" in calls[1]  # repair feedback attached to the retry


@pytest.mark.asyncio
async def test_parse_graph_recovers_after_repair(monkeypatch) -> None:
    adapter = _adapter(max_retries=1)
    responses = ["garbage {", VALID_GRAPH_JSON]
    calls: list[str] = []

    async def fake_chat(system: str, user: str) -> str:
        calls.append(user)
        return responses.pop(0)

    monkeypatch.setattr(adapter, "_chat", fake_chat)
    doc = await adapter.parse_graph("文本", "network_topology")
    assert doc.diagramId == "t1"
    assert len(calls) == 2 and "校验失败" in calls[1]


@pytest.mark.asyncio
async def test_chat_retries_without_response_format_on_400(monkeypatch) -> None:
    """Some OpenAI-compatible endpoints (qwen/MaaS channels) reject
    response_format; _chat must retry once without it."""
    import app.llm.adapter as adapter_mod

    payloads: list[dict] = []

    class FakeResp:
        def __init__(self, status: int) -> None:
            self.status_code = status

        def json(self) -> dict:
            return {"choices": [{"message": {"content": VALID_GRAPH_JSON}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            payloads.append(dict(json))  # snapshot: _chat pops keys in place
            # First call: 400 (endpoint rejects response_format); second: 200.
            return FakeResp(400 if len(payloads) == 1 else 200)

    monkeypatch.setattr(adapter_mod.httpx, "AsyncClient", FakeClient)
    adapter = _adapter()
    content = await adapter._chat("sys", "usr")
    assert content == VALID_GRAPH_JSON
    assert "response_format" in payloads[0]
    assert "response_format" not in payloads[1]


@pytest.mark.asyncio
async def test_chat_unavailable_on_5xx(monkeypatch) -> None:
    import app.llm.adapter as adapter_mod

    class FakeResp:
        status_code = 503

        def json(self) -> dict:
            return {}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            return FakeResp()

    monkeypatch.setattr(adapter_mod.httpx, "AsyncClient", FakeClient)
    with pytest.raises(ApiException) as exc:
        await _adapter()._chat("sys", "usr")
    assert exc.value.code == ErrorCode.LLM_UNAVAILABLE


def test_normalize_strips_hallucinated_fields() -> None:
    """Regression of the live qwen failure: edges with `properties` and
    root-level notes must be cleaned, whitelisted content untouched."""
    from app.llm.adapter import normalize_llm_graph_draft

    raw = {
        "schemaVersion": "1.0", "diagramId": "t1", "name": "n", "diagramType": "network_topology",
        "nodes": [{"id": "n1", "label": "服务器", "kind": "server", "notes": "x"}],
        "groups": [],
        "edges": [{"id": "e1", "source": "n1", "target": "n1", "kind": "physical",
                   "direction": "undirected", "properties": {"ip": "192.0.2.1"}}],
        "layout": {"algorithm": "layered", "direction": "DOWN", "preserveManualPositions": True},
        "notes": "model explanation",
    }
    out = normalize_llm_graph_draft(raw)
    assert "notes" not in out
    assert "notes" not in out["nodes"][0]
    assert "properties" not in out["edges"][0]
    assert out["nodes"][0]["kind"] == "server"  # whitelisted content intact


@pytest.mark.asyncio
async def test_parse_graph_tolerates_extra_fields(monkeypatch) -> None:
    """End-to-end regression of the production failure: the model returned
    edges[].properties and the draft must still validate after cleanup."""
    raw_with_extras = (
        '{"schemaVersion":"1.0","diagramId":"q1","name":"qwen草稿","diagramType":"network_topology",'
        '"nodes":[{"id":"sw","label":"核心交换机","kind":"switch"},'
        '{"id":"s1","label":"服务器1","kind":"server"}],'
        '"edges":[{"id":"l1","source":"sw","target":"s1","kind":"physical",'
        '"direction":"undirected","properties":{"bandwidth":"1G"}}],'
        '"groups":[],"layout":{"algorithm":"layered","direction":"DOWN","preserveManualPositions":true},'
        '"notes":"这是我的解释"}'
    )
    adapter = _adapter()
    calls: list[str] = []

    async def fake_chat(system: str, user: str) -> str:
        calls.append(user)
        return raw_with_extras

    monkeypatch.setattr(adapter, "_chat", fake_chat)
    doc = await adapter.parse_graph("一台核心交换机连接一台服务器", "network_topology")
    assert len(doc.nodes) == 2 and len(doc.edges) == 1
    assert doc.edges[0].properties is None if hasattr(doc.edges[0], "properties") else True
    assert len(calls) == 1  # cleaned on first attempt: no repair round needed


def test_parse_prompt_states_edge_field_whitelist() -> None:
    """The prompt must tell the model edges carry no properties field."""
    system = parse_graph_system_prompt()
    assert "边没有 properties 字段" in system
    assert "字段白名单" in system


def test_generic_physical_link_labels_are_dropped_explicit_ones_kept() -> None:
    """Live qwen output invented 'Connection' / 'Uplink' labels on physical
    links. Generic labels are removed; anything the user actually named and
    labels on non-physical edges are untouched."""
    from app.llm.adapter import is_generic_edge_label, normalize_llm_graph_draft

    for generic in ["Connection", "Uplink", "Internet Connection", "连接", "上联", "物理链路", "NETWORK LINK"]:
        assert is_generic_edge_label(generic), generic
    for explicit in ["Trunk 上联", "千兆光纤", "出口链路", "读写", "专线", "", None]:
        assert not is_generic_edge_label(explicit), explicit

    draft = {
        "schemaVersion": "1.0", "diagramId": "t", "name": "t", "diagramType": "network_topology",
        "nodes": [
            {"id": "sw", "label": "核心交换机", "kind": "switch"},
            {"id": "s1", "label": "服务器 1", "kind": "server"},
            {"id": "db", "label": "数据库", "kind": "database"},
        ],
        "groups": [],
        "edges": [
            {"id": "e1", "source": "sw", "target": "s1", "kind": "physical", "direction": "undirected", "label": "Connection"},
            {"id": "e2", "source": "sw", "target": "s1", "kind": "physical", "direction": "undirected", "label": "Trunk 上联"},
            {"id": "e3", "source": "s1", "target": "db", "kind": "dataflow", "direction": "bidirectional", "label": "连接"},
        ],
        "layout": {"algorithm": "layered", "direction": "DOWN", "preserveManualPositions": True},
    }
    out = normalize_llm_graph_draft(draft)
    edges = {e["id"]: e for e in out["edges"]}
    assert "label" not in edges["e1"]                      # invented generic label removed
    assert edges["e2"]["label"] == "Trunk 上联"              # explicit label kept
    assert edges["e3"]["label"] == "连接"                    # non-physical edge: kept


def test_parse_prompt_requires_user_language_and_no_physical_labels() -> None:
    system = parse_graph_system_prompt()
    assert "原文语言" in system and "Core Switch" in system
    assert "物理连线" in system and "默认不写 label" in system
