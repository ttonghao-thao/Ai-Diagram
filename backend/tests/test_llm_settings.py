"""Portal LLM settings persistence, masking, and request-time activation."""
from __future__ import annotations

import json
from stat import S_IMODE

import httpx
from fastapi.testclient import TestClient

from app.llm import adapter
from app.main import create_app
from tests.conftest import load_fixture, make_settings

CONFIG = "/api/v1/settings/llm"
PARSE = "/api/v1/diagrams/parse"
DESCRIPTION = {"text": "核心交换机连接服务器", "diagramType": "network_topology"}


def update(client: TestClient, version: int, **changes):
    return client.patch(CONFIG, json={"baseVersion": version, **changes})


def saved(response):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()["data"]


def test_legacy_settings_are_imported_once_and_key_is_encrypted(tmp_path) -> None:
    legacy = make_settings(
        tmp_path, llm_enabled=True, llm_provider="openai", llm_model="legacy-model",
        llm_base_url="http://legacy.local/v1/", llm_api_key="test-legacy-credential",
    )
    first_app = create_app(legacy)
    with TestClient(first_app) as client:
        initial = saved(client.get(CONFIG))
        assert initial["enabled"] and initial["model"] == "legacy-model"
        assert initial["baseUrl"] == "http://legacy.local/v1"
        assert initial["apiKey"] == "****"
        assert first_app.state.llm_settings.runtime_settings().llm_api_key == legacy.llm_api_key
        changed = saved(update(client, initial["version"], model="portal-model", apiKey="test-portal-credential"))
        assert changed["apiKey"] == "****"
        assert saved(update(client, changed["version"], timeoutSeconds=15, apiKey="****"))["apiKey"] == "****"
    first_app.state.db.close()

    key_path = legacy.storage_root / "llm-settings.key"
    assert S_IMODE(key_path.stat().st_mode) == 0o600
    database_bytes = legacy.database_path.read_bytes()
    assert b"test-portal-credential" not in database_bytes and b"test-legacy-credential" not in database_bytes
    changed_env = make_settings(tmp_path, llm_model="other-env-model", llm_api_key="other-env-key")
    restarted = create_app(changed_env)
    with TestClient(restarted) as client:
        current = saved(client.get(CONFIG))
        assert current["enabled"] and current["model"] == "portal-model"
        assert current["timeoutSeconds"] == 15 and current["apiKey"] == "****"
        assert restarted.state.llm_settings.runtime_settings().llm_api_key == "test-portal-credential"
        cleared = saved(update(client, current["version"], apiKey=None))
        assert cleared["apiKey"] == ""
    restarted.state.db.close()


def test_invalid_settings_and_stale_edits_leave_active_config_unchanged(app_client) -> None:
    client, _ = app_client
    initial = saved(client.get(CONFIG))
    invalid = update(
        client, initial["version"], enabled=True, provider="openai",
        baseUrl="http://user:private-url-password@llm.local/v1", model="test",
        apiKey="private-key\r\ninvalid",
    )
    assert invalid.status_code == 400
    assert "private-url-password" not in invalid.text and "private-key" not in invalid.text
    missing_url = update(client, initial["version"], enabled=True, provider="openai", model="test")
    assert missing_url.status_code == 400
    assert saved(client.get(CONFIG)) == initial

    current = saved(update(client, initial["version"], enabled=True))
    stale = update(client, initial["version"], enabled=False)
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["currentVersion"] == current["version"]
    assert saved(client.get(CONFIG)) == current


def test_parse_and_patch_use_latest_endpoint_model_and_key(app_client, monkeypatch) -> None:
    client, _ = app_client
    graph = load_fixture("network.graph.json")
    request_path = "/api/v1/diagrams/sample_network/patch/preview"
    assert client.post("/api/v1/diagrams", json=graph).status_code == 200
    assert client.post(PARSE, json=DESCRIPTION).status_code == 503

    requests = []
    timeouts = []

    def upstream(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append((str(request.url), payload["model"], request.headers.get("authorization"),
                         payload.get("reasoning_effort")))
        is_patch = payload["messages"][-1]["content"].endswith("核心交换机改名\n")
        result = {"baseVersion": 1, "operations": [
            {"op": "update_node", "id": "core_switch", "changes": {"label": "主交换机"}},
        ]} if is_patch else graph
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})

    client_factory = httpx.AsyncClient

    def model_client(**kwargs):
        timeouts.append(kwargs["timeout"])
        return client_factory(transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr(adapter.httpx, "AsyncClient", model_client)
    initial = saved(client.get(CONFIG))
    current = saved(update(
        client, initial["version"], enabled=True, provider="openai", baseUrl="http://first.local/v1",
        model="first-model", apiKey="test-first-key", timeoutSeconds=8, maxRetries=0,
    ))
    health = client.get("/api/v1/health").json()["data"]["llm"]
    assert health == {"enabled": True, "provider": "openai"}
    assert client.post(PARSE, json=DESCRIPTION).status_code == 200

    current = saved(update(
        client, current["version"], model="second-model", apiKey="test-replacement-key",
        reasoningEffort="none", timeoutSeconds=12,
    ))
    preview = client.post(request_path, json={"instruction": "核心交换机改名"})
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["patch"]["operations"][0]["changes"]["label"] == "主交换机"

    current = saved(update(client, current["version"], baseUrl="http://second.local/v1", apiKey="****"))
    assert current["apiKey"] == ""
    assert client.post(PARSE, json=DESCRIPTION).status_code == 200
    saved(update(client, current["version"], enabled=False))
    assert client.post(PARSE, json=DESCRIPTION).status_code == 503
    assert requests == [
        ("http://first.local/v1/chat/completions", "first-model", "Bearer test-first-key", None),
        ("http://first.local/v1/chat/completions", "second-model", "Bearer test-replacement-key", "none"),
        ("http://second.local/v1/chat/completions", "second-model", None, "none"),
    ]
    assert timeouts == [8, 12, 12]
