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
