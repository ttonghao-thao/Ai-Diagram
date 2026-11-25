"""LLM adapters (docs/02 section 5).

Two implementations:
  - MockLlmAdapter: fully deterministic, offline. Rule-based Chinese/English
    clause parsing; never invents connections or IPs; emits explicit warnings.
  - OpenAICompatibleAdapter: POSTs to an OpenAI-compatible /chat/completions
    endpoint with the JSON Schema in the system prompt, validates the output
    against the Pydantic model and retries a bounded number of times
    (LLM_MAX_RETRIES) with repair feedback before failing.

The API key is read from the environment and never logged; ai_jobs records
only request metadata (no raw text, no topology, docs/04 section 6).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Protocol

import httpx
from pydantic import ValidationError

from app.schemas.api import ApiException, ErrorCode
from app.schemas.graph import GraphDocument, GraphWarning
from app.llm.prompts import (
    parse_graph_system_prompt,
    parse_graph_user_prompt,
    propose_patch_system_prompt,
    propose_patch_user_prompt,
    repair_feedback_prompt,
)


class LlmAdapter(Protocol):
    name: str

    async def parse_graph(self, text: str, diagram_type: str) -> GraphDocument: ...

    async def propose_patch(self, instruction: str, graph: GraphDocument, base_version: int) -> Dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Mock adapter: deterministic rule-based extraction.
# ---------------------------------------------------------------------------

_KIND_KEYWORDS: List[tuple] = [
    (re.compile(r"核心交换|交换机|switch", re.I), "switch"),
    (re.compile(r"路由器|router", re.I), "router"),
    (re.compile(r"防火墙|firewall|waf", re.I), "firewall"),
    (re.compile(r"虚拟机|虚机|vm\b", re.I), "vm"),
    (re.compile(r"数据库|内容库|数据库集群|database|db\b", re.I), "database"),
    (re.compile(r"云平台|云端|公有云|私有云|外部网络|互联网|云\b|cloud|internet", re.I), "cloud"),
    (re.compile(r"终端|客户端|工作站|台式机|笔记本|pc\b|client|terminal", re.I), "client"),
    (re.compile(r"服务器|主机|server|host", re.I), "server"),
    (re.compile(r"服务|平台|系统|模块|service|platform|system", re.I), "service"),
]

_PHYSICAL_KINDS = {"switch", "router", "firewall", "server", "vm", "cloud", "client", "database"}

_CONNECT_VERBS = re.compile(
    r"(读写|调用|访问|请求|连接|接入|接到|链接|连着|connected?\s+to|links?\s+to|attach(es|ed)?\s+to)"
)

_CLAUSE_SPLIT = re.compile(r"[。；;！!？?\n\r]+")

# NOTE: \b is unreliable here because Python treats CJK characters as \w, so
# an IP glued to Chinese text ("使用192.0.2.0/24") has no boundary. Explicit
# lookarounds only exclude adjacent digits/dots instead.
_IP_PATTERN = re.compile(r"(?<![\d.])\d{1,3}(\.\d{1,3}){3}(?![\d.])")

_NUMBER_WORDS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _infer_kind(label: str) -> tuple[str, bool]:
    """Returns (kind, guessed). Order matters: more specific patterns first."""
    for pattern, kind in _KIND_KEYWORDS:
        if pattern.search(label):
            return kind, False
    return "generic", True


def _safe_id(base: str, used: set) -> str:
    """Derive a schema-valid id from a label; fall back to sequential ids."""
    ascii_id = re.sub(r"[^A-Za-z0-9_-]", "", base.replace(" ", "_"))
    ascii_id = ascii_id.lstrip("_-0123456789")
    candidate = ascii_id[:63] if ascii_id else ""
    final = candidate or "item"
    seq = 1
    while final in used:
        seq += 1
        final = f"{(candidate or 'item')}_{seq}"
    used.add(final)
    return final


class MockLlmAdapter:
    """Deterministic offline extraction used for demos, tests and CI."""

    name = "mock"

    async def parse_graph(self, text: str, diagram_type: str) -> GraphDocument:
        warnings: List[GraphWarning] = []
        nodes: List[dict] = []
        edges: List[dict] = []
        used_ids: set = set()
        label_to_id: Dict[str, str] = {}

        clauses = [c.strip() for c in _CLAUSE_SPLIT.split(text) if c.strip()]
        node_seq = 0

        def ensure_node(label: str) -> str:
            nonlocal node_seq
            key = label.strip()
            if key in label_to_id:
                return label_to_id[key]
            node_seq += 1
            kind, guessed = _infer_kind(key)
            nid = _safe_id(key, used_ids)
            props: Dict[str, Any] = {}
            if guessed or kind == "generic":
                props["deviceType"] = key
                warnings.append(GraphWarning(
                    code="DEVICE_TYPE_GUESSED",
                    message=f'未识别设备类型"{key}"，已按 generic 记录并保留原始类型',
                    requiresConfirmation=False,
                ))
            nodes.append({"id": nid, "label": key, "kind": kind, "properties": props, "origin": "ai"})
            label_to_id[key] = nid
            return nid

        def expand_count(label: str) -> List[str]:
            """Expand explicit counts ("三台服务器" -> 服务器 01..03)."""
            m = re.match(r"^([一二两三四五六七八九十\d]+)\s*(个|台|套|组|名)?\s*(.+)$", label)
            if not m:
                return [label]
            count = _NUMBER_WORDS.get(m.group(1), None)
            if count is None and m.group(1).isdigit():
                count = int(m.group(1))
            if not count or not (1 <= count <= 20):
                return [label]
            base_label = m.group(3).strip()
            if count == 1:
                return [base_label]
            return [f"{base_label} {i:02d}" for i in range(1, count + 1)]

        for clause in clauses:
            match = _CONNECT_VERBS.search(clause)
            if not match:
                continue
            verb = match.group(1)
            subject = clause[: match.start()].strip(" ，,。和与")
            target_part = clause[match.end():].strip(" ，,。和与")
            if not subject or not target_part:
                warnings.append(GraphWarning(
                    code="AMBIGUOUS_RELATION",
                    message=f"无法确定连接端点，已跳过该句：{clause}",
                    relatedIds=[],
                    requiresConfirmation=True,
                ))
                continue
            targets = [t.strip() for t in re.split(r"[、,，和]|以及|跟|与", target_part) if t.strip()]
            # IP fragments are qualifiers, never device names: drop them with
            # an explicit warning instead of creating bogus nodes.
            usable: List[str] = []
            for target in targets:
                if _IP_PATTERN.search(target):
                    warnings.append(GraphWarning(
                        code="IP_ADDRESSES_NOT_PARSED",
                        message=f"片段包含 IP 地址，未据此创建设备或连接：{target}",
                        requiresConfirmation=False,
                    ))
                    continue
                usable.append(target)
            subjects = expand_count(subject)
            expanded: List[str] = []
            for target in usable:
                expanded.extend(expand_count(target))
            if not expanded or not subjects:
                continue
            for src_label in subjects:
                src_id = ensure_node(src_label)
                for target in expanded:
                    tgt_id = ensure_node(target)
                    if src_id == tgt_id:
                        continue
                    src_kind = next(n["kind"] for n in nodes if n["id"] == src_id)
                    tgt_kind = next(n["kind"] for n in nodes if n["id"] == tgt_id)
                    # Verb-aware relation typing (docs/02: strict separation of
                    # physical links vs access/calls vs data flows).
                    if re.search(r"读写", verb):
                        kind, direction = "dataflow", "bidirectional"
                    elif re.search(r"调用|访问|请求", verb):
                        kind, direction = "logical", "forward"
                    elif (
                        src_kind in _PHYSICAL_KINDS and tgt_kind in _PHYSICAL_KINDS
                        and "service" not in (src_kind, tgt_kind)
                    ):
                        kind, direction = "physical", "undirected"
                    else:
                        kind, direction = "logical", "forward"
                    edge_id = f"link_{len(edges) + 1}"
                    edges.append({
                        "id": edge_id, "source": src_id, "target": tgt_id,
                        "kind": kind, "direction": direction,
                    })

        # IP-like tokens elsewhere in the description are never auto-attached.
        if _IP_PATTERN.search(text):
            warnings.append(GraphWarning(
                code="IP_ADDRESSES_NOT_PARSED",
                message="文本中包含 IP 地址；为避免错误归属，系统不会自动提取 IP，请在设备属性中人工填写",
                requiresConfirmation=False,
            ))

        if not nodes and not warnings:
            raise ApiException(
                ErrorCode.LLM_INVALID_OUTPUT,
                "mock parser could not extract any device or ambiguity from the text",
            )
        # Texts that only produce warnings still yield a valid (empty) draft.

        doc_id = _safe_id("parsed_" + (clauses[0][:20] if clauses else "graph"), set())
        payload = {
            "schemaVersion": "1.0",
            "diagramId": doc_id,
            "name": (clauses[0][:60] if clauses else "解析结果") or "解析结果",
            "diagramType": diagram_type,
            "nodes": nodes,
            "groups": [],
            "edges": edges,
            "layout": {"algorithm": "layered", "direction": "DOWN", "preserveManualPositions": True},
        }
        if warnings:
            payload["warnings"] = [w.model_dump(exclude_none=True) for w in warnings]
        return GraphDocument.model_validate(payload)

    async def propose_patch(self, instruction: str, graph: GraphDocument, base_version: int) -> Dict[str, Any]:
        """Deterministic instruction -> patch. Supported verbs:

        - 新增/添加 <数量><设备> 并连接<目标标签>  -> add_node (+add_edge)
        - 删除<标签>                              -> remove_node (requiresConfirmation+cascade)
        - 重命名<标签>为<新名> / 把<标签>改名为<新名> -> update_node label

        No fabrication: add_edge only targets existing node labels; an
        unmatched target raises AMBIGUOUS_RELATION.
        """
        text = instruction.strip()
        operations: List[Dict[str, Any]] = []
        warnings: List[str] = []

        def find_node(label_part: str):
            exact = next((n for n in graph.nodes if n.label == label_part), None)
            if exact:
                return exact
            matches = [n for n in graph.nodes if label_part and label_part in n.label]
            if len(matches) == 1:
                return matches[0]
            raise ApiException(
                ErrorCode.AMBIGUOUS_RELATION,
                f'目标"{label_part}"匹配到 {len(matches)} 个节点，无法唯一确定' if matches
                else f'未找到目标节点"{label_part}"，不会虚构连接',
                [n.id for n in matches][:10],
            )

        # 1) add nodes (+ optional connection)
        for m in re.finditer(r"(?:新增|添加|加)\s*([一二两三四五六七八九十\d]+)\s*(台|个|套|组)?\s*([^\s，,。；;]+?)(?:并连接|连接到|连接)([^\s，,。；;]+)", text):
            count = _NUMBER_WORDS.get(m.group(1), None)
            if count is None and m.group(1).isdigit():
                count = int(m.group(1))
            if not count or not (1 <= count <= 20):
                continue
            kind_word, target_label = m.group(3), m.group(4)
            target = find_node(target_label)
            kind, guessed = _infer_kind(kind_word)
            # Use the inferred English kind as the id base so CJK device names
            # still produce meaningful schema-valid ids (firewall_1 etc.).
            base_id = _safe_id(kind, {n.id for n in graph.nodes})
            for i in range(1, count + 1):
                node_id = base_id if count == 1 else f"{base_id}_{i}"
                label = kind_word if count == 1 else f"{kind_word} {i:02d}"
                operations.append({
                    "op": "add_node",
                    "id": node_id,
                    "value": {"id": node_id, "label": label, "kind": kind, "origin": "ai",
                              "properties": {"deviceType": kind_word} if guessed or kind == "generic" else {}},
                })
                operations.append({
                    "op": "add_edge",
                    "id": f"link_{node_id}",
                    "value": {"id": f"link_{node_id}", "source": target.id, "target": node_id,
                              "kind": "physical", "direction": "undirected"},
                })

        # 2) remove node
        for m in re.finditer(r"(?:删除|移除)\s*([^\s，,。；;]+)", text):
            target = find_node(m.group(1))
            operations.append({
                "op": "remove_node",
                "id": target.id,
                "cascade": True,
                "requiresConfirmation": True,
            })

        # 3) rename
        for m in re.finditer(r"(?:把|将)?\s*([^\s，,。；;]+?)\s*(?:重命名|改名为|改名为|更名为)\s*(?:为|:|：)?\s*([^\s，,。；;]+)", text):
            target = find_node(m.group(1))
            operations.append({
                "op": "update_node",
                "id": target.id,
                "changes": {"label": m.group(2)},
            })

        if not operations:
            raise ApiException(
                ErrorCode.LLM_INVALID_OUTPUT,
                "mock patch generator could not map the instruction to operations "
                "(supported: 新增N台设备并连接目标 / 删除目标 / 重命名目标为新名)",
            )

        return {
            "baseVersion": base_version,
            "operations": operations[:100],
            "reason": f"mock propose_patch: {text[:200]}",
            "warnings": warnings,
        }


# Field whitelist mirrors contracts/graph.schema.json (additionalProperties:
# false). LLM drafts commonly hallucinate extra keys (e.g. `properties` on
# edges, root-level `notes`); they are dropped before validation instead of
# failing the whole draft. Structural errors still fail normally.
_GRAPH_ROOT_FIELDS = {
    "schemaVersion", "diagramId", "name", "diagramType",
    "nodes", "groups", "edges", "layout", "appearance", "metadata", "warnings",
}
_GRAPH_SECTION_FIELDS = {
    "nodes": {"id", "label", "kind", "groupId", "properties", "geometry",
              "manualLocked", "style", "origin"},
    "edges": {"id", "source", "target", "kind", "direction", "label",
              "sourcePort", "targetPort", "waypoints", "style"},
    "groups": {"id", "label", "parentId", "geometry", "manualLocked", "style"},
}

logger = logging.getLogger(__name__)

# Generic link labels LLMs invent for physical links ("Connection", "Uplink",
# "连接"...). A label the user actually named (Trunk 上联, 千兆光纤) never
# matches: only bare generic words / word combinations are dropped.
_GENERIC_EDGE_LABELS = {
    "connection", "connect", "link", "uplink", "downlink", "cable", "network",
    "internet", "internet connection", "network connection", "physical connection",
    "物理连接", "网络连接", "互联网连接", "连接", "连线", "链路", "上联", "下联", "互联", "相连",
}
_GENERIC_EDGE_LABEL_PATTERN = re.compile(
    r"^(?:物理|网络|互联网|internet\s*|network\s*|physical\s*)*"
    r"(?:connection|connect|link|uplink|连接|连线|链路|上联|下联)$",
    re.I,
)


def is_generic_edge_label(label: Any) -> bool:
    if not isinstance(label, str):
        return False
    text = label.strip().lower()
    if not text:
        return False
    return text in _GENERIC_EDGE_LABELS or bool(_GENERIC_EDGE_LABEL_PATTERN.match(text))


def normalize_llm_graph_draft(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Strip hallucinated extra fields from an LLM graph draft.

    Unknown keys are removed; generic invented labels ("Connection") are
    dropped from physical links. Both are recorded in the log; explicit labels
    and every whitelisted value stay untouched. Stored graphs still pass the
    strict schema.
    """
    out = {k: v for k, v in raw.items() if k in _GRAPH_ROOT_FIELDS}
    dropped_root = set(raw) - set(out)
    if dropped_root:
        logger.info("llm draft: dropped root fields %s", sorted(dropped_root))
    for section, allowed in _GRAPH_SECTION_FIELDS.items():
        items = out.get(section)
        if not isinstance(items, list):
            continue
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                cleaned.append(item)
                continue
            extra = set(item) - allowed
            if extra:
                logger.info("llm draft: dropped %s unexpected fields in %s", len(extra), section)
                item = {k: v for k, v in item.items() if k in allowed}
            item = {key: value for key, value in item.items() if key not in {"style", "geometry", "waypoints", "manualLocked"}}
            if section == "edges" and item.get("kind") == "physical" and is_generic_edge_label(item.get("label")):
                logger.info("llm draft: dropped a generic physical edge label")
                item.pop("label", None)
            cleaned.append(item)
        out[section] = cleaned
    return out


# ---------------------------------------------------------------------------
# OpenAI-compatible adapter.
# ---------------------------------------------------------------------------

_IP_CANDIDATE = re.compile(
    r"(?<![a-zA-Z0-9_.:])(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|[a-fA-F0-9]*:[a-fA-F0-9:.]+)(?:/[0-9]{1,3})?(?![a-zA-Z0-9_.:])"
)


def _mask_addresses(text: str, addresses: dict) -> str:
    import ipaddress

    def replace(match):
        address = match.group()
        try:
            ipaddress.ip_interface(address)
        except ValueError:
            return address
        if address not in addresses:
            addresses[address] = f"private_address_{len(addresses) + 1:03d}"
        return addresses[address]
    return _IP_CANDIDATE.sub(replace, text)


def _restore_addresses(obj, addresses: dict):
    if not addresses:
        return
    if isinstance(obj, list):
        for value in obj:
            _restore_addresses(value, addresses)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and key not in {"id", "source", "target", "diagramId", "groupId", "parentId", "centerNodeId"}:
                for address, placeholder in addresses.items():
                    value = value.replace(placeholder, address)
                obj[key] = value
            else:
                _restore_addresses(value, addresses)


class OpenAICompatibleAdapter:
    name = "openai"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        max_retries: int = 2,
        provider_label: str = "openai",
        reasoning_effort: str = "",
        private_endpoint: bool = False,
    ) -> None:
        if not base_url:
            raise ApiException(ErrorCode.LLM_UNAVAILABLE, "LLM_BASE_URL is not configured")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.provider_label = provider_label
        self.reasoning_effort = reasoning_effort
        from urllib.parse import urlparse

        self.private_endpoint = private_endpoint or urlparse(self.base_url).hostname in {"localhost", "127.0.0.1", "::1"}

    async def _chat(self, system_prompt: str, user_prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        url = f"{self.base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 400 and "response_format" in payload:
                    # Some OpenAI-compatible endpoints (seen on qwen/MaaS
                    # channels) reject the response_format parameter; retry
                    # once without it — _extract_json still guards parsing.
                    payload.pop("response_format")
                    resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ApiException(
                ErrorCode.LLM_UNAVAILABLE,
                f"LLM endpoint unreachable: {type(exc).__name__}",
            ) from exc
        if resp.status_code >= 500 or resp.status_code in (401, 403, 429):
            raise ApiException(ErrorCode.LLM_UNAVAILABLE, f"LLM endpoint returned HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise ApiException(ErrorCode.LLM_UNAVAILABLE, f"LLM endpoint returned HTTP {resp.status_code}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise ApiException(ErrorCode.LLM_INVALID_OUTPUT, "LLM response has no choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ApiException(ErrorCode.LLM_INVALID_OUTPUT, "LLM returned empty content")
        return content

    @staticmethod
    def _extract_json(content: str) -> Any:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            if match:
                return json.loads(match.group(0))
            raise

    async def parse_graph(self, text: str, diagram_type: str) -> GraphDocument:
        system_prompt = parse_graph_system_prompt()
        addresses: dict = {}
        sanitized = text if self.private_endpoint else _mask_addresses(text, addresses)
        user_prompt = parse_graph_user_prompt(sanitized, diagram_type)
        feedback = ""
        last_errors: List[str] = []
        for attempt in range(self.max_retries + 1):
            prompt = user_prompt + ("\n\n" + feedback if feedback else "")
            content = await self._chat(system_prompt, prompt)
            try:
                raw = self._extract_json(content)
                if not isinstance(raw, dict):
                    raise ValueError("output is not a JSON object")
                raw = normalize_llm_graph_draft(raw)
                _restore_addresses(raw, addresses)
                doc = GraphDocument.model_validate(raw)
                logger.info("parse_graph ok: %d nodes, %d edges (attempt %d)",
                            len(doc.nodes), len(doc.edges), attempt + 1)
                return doc
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                last_errors = self._format_errors(exc)
                # Metadata only in logs (no raw text/topology, docs/04 section 6).
                logger.warning("parse_graph attempt %d/%d failed: %s",
                               attempt + 1, self.max_retries + 1,
                               "; ".join(last_errors[:5]))
                feedback = repair_feedback_prompt(last_errors)
        raise ApiException(
            ErrorCode.LLM_INVALID_OUTPUT,
            f"LLM output failed schema validation after {self.max_retries + 1} attempts",
            {"errors": last_errors[:10]},
        )

    @staticmethod
    def _format_errors(exc: Any) -> List[str]:
        if isinstance(exc, ValidationError):
            return [f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()][:20]
        return [str(exc)]

    async def propose_patch(self, instruction: str, graph: GraphDocument, base_version: int) -> Dict[str, Any]:
        system_prompt = propose_patch_system_prompt()
        payload = graph.model_dump(exclude_none=True)
        for node in payload["nodes"]:
            node["properties"] = {k: v for k, v in node["properties"].items()
                                  if k in {"deviceType", "networkRole", "tier"}}
        for name in ("nodes", "groups", "edges"):
            for entity in payload[name]:
                for key in ("style", "geometry", "waypoints", "sourcePort", "targetPort"):
                    entity.pop(key, None)
        payload.pop("metadata", None)
        payload.pop("warnings", None)
        graph_json = json.dumps(payload, ensure_ascii=False)
        user_prompt = propose_patch_user_prompt(instruction, graph_json, base_version)
        addresses: dict = {}
        if not self.private_endpoint:
            user_prompt = _mask_addresses(user_prompt, addresses)
        feedback = ""
        last_errors: List[str] = []
        for attempt in range(self.max_retries + 1):
            prompt = user_prompt + ("\n\n" + feedback if feedback else "")
            content = await self._chat(system_prompt, prompt)
            try:
                raw = self._extract_json(content)
                if not isinstance(raw, dict):
                    raise ValueError("output is not a JSON object")
                if raw.get("baseVersion") != base_version:
                    raise ValueError(f"baseVersion must be {base_version}")
                operations = raw.get("operations")
                if not isinstance(operations, list):
                    raise ValueError("operations must be an array")
                _restore_addresses(raw, addresses)
                for operation in operations:
                    if not isinstance(operation, dict):
                        continue
                    for field in ("value", "changes"):
                        obj = operation.get(field)
                        if not isinstance(obj, dict):
                            continue
                        style = obj.pop("style", None)
                        shape = style.get("shapeId") if isinstance(style, dict) else None
                        if operation.get("op") in ("add_node", "update_node") and isinstance(shape, str) and shape and shape in instruction:
                            obj["style"] = {"shapeId": shape}
                        for key in ("geometry", "waypoints"):
                            obj.pop(key, None)
                from app.graph.patch import validate_patch_payload
                return validate_patch_payload(raw)
            except (json.JSONDecodeError, ValueError, ApiException) as exc:
                last_errors = [str(exc)]
                feedback = repair_feedback_prompt(last_errors)
        raise ApiException(
            ErrorCode.LLM_INVALID_OUTPUT,
            f"patch output failed validation after {self.max_retries + 1} attempts",
            {"errors": last_errors[:10]},
        )


def build_adapter(settings) -> LlmAdapter:
    """Factory honoring LLM_ENABLED / LLM_PROVIDER; raises when unusable."""
    if not settings.llm_enabled:
        raise ApiException(
            ErrorCode.LLM_UNAVAILABLE,
            "LLM is disabled (LLM_ENABLED=false); JSON-based generation remains available",
        )
    if settings.llm_provider == "mock":
        return MockLlmAdapter()
    if settings.llm_provider == "openai":
        return OpenAICompatibleAdapter(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            provider_label=f"openai:{settings.llm_model or 'default'}",
            reasoning_effort=settings.llm_reasoning_effort,
            private_endpoint=settings.llm_private_endpoint,
        )
    raise ApiException(ErrorCode.LLM_UNAVAILABLE, f"unknown LLM_PROVIDER '{settings.llm_provider}'")
