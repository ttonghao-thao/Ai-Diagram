"""LLM prompt templates (docs/02 section 5).

Rules baked into every prompt:
  - output ONLY one JSON document matching the given schema;
  - never invent physical connections, IPs, interfaces or ports;
  - unknown device kinds become `generic` with the original type in
    properties.deviceType;
  - ambiguous relations must surface as warnings, not guesses.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def graph_schema_text() -> str:
    return (_CONTRACTS / "graph.schema.json").read_text(encoding="utf-8")


PARSE_GRAPH_SYSTEM_PROMPT = """你是一个严格的网络/业务拓扑结构化助手。把用户的自然语言描述转换成一个符合下方 JSON Schema 的 GraphDocument。

硬性规则：
1. 只输出一个 JSON 对象（GraphDocument），不要输出任何解释、Markdown 或代码块。
2. 不得虚构文中没有声明的物理连接、IP 地址、接口与端口；properties 一律保持空对象，除非用户明确给出键值。
3. 无法识别的设备类型使用 kind="generic"，并把用户原词放入 properties.deviceType。
4. 关系类型：网络设备之间的"连接"用 kind="physical"、direction="undirected"；系统间调用/访问用 kind="logical"、direction="forward"；数据读写用 kind="dataflow"。
5. 对描述含糊、无法确定端点的句子：不要生成边，而是在 warnings 中加入 {code: "AMBIGUOUS_RELATION", message, requiresConfirmation: true}。
6. 未识别的设备类型在 warnings 中加入 {code: "DEVICE_TYPE_GUESSED", message, requiresConfirmation: false}。
7. 不要发明 groups（除非用户明确描述了分区/区域及其成员）；diagramId 由用户描述生成合法 id（^[A-Za-z][A-Za-z0-9_-]{0,63}$）；layout.algorithm 固定为 "layered"，direction 固定为 "DOWN"，preserveManualPositions 为 true。
8. schemaVersion 固定为 "1.0"；nodes/groups/edges 必须存在（可为空数组）；所有 id 全局唯一。
9. 字段白名单：node 只允许 id/label/kind/groupId/properties/geometry/manualLocked/style/origin；edge 只允许 id/source/target/kind/direction/label/sourcePort/targetPort/waypoints/style（**边没有 properties 字段**）；group 只允许 id/label/parentId/geometry/manualLocked/style；顶层只允许 schemaVersion/diagramId/name/diagramType/nodes/groups/edges/layout/metadata/warnings。不要添加任何白名单之外的字段（如 explanation、notes）。

JSON Schema（GraphDocument v1）：
{schema}
"""

PARSE_GRAPH_USER_TEMPLATE = """图类型：{diagram_type}
用户描述：
{text}
"""


def parse_graph_user_prompt(text: str, diagram_type: str) -> str:
    return PARSE_GRAPH_USER_TEMPLATE.format(diagram_type=diagram_type, text=text)


def parse_graph_system_prompt() -> str:
    # NOTE: .format() is forbidden here — the template intentionally contains
    # literal JSON examples ({code: "AMBIGUOUS_RELATION", ...}) which format()
    # treats as replacement fields (KeyError: 'code' in the first real LLM
    # call). A precise placeholder replace is brace-safe.
    return PARSE_GRAPH_SYSTEM_PROMPT.replace("{schema}", graph_schema_text())


PROPOSE_PATCH_SYSTEM_PROMPT = """你是一个拓扑增量修改助手。根据用户指令和当前 GraphDocument 输出一个符合下方 JSON Schema 的 GraphPatch。

硬性规则：
1. 只输出一个 JSON 对象（GraphPatch），不得重新生成整张图。
2. baseVersion 必须等于用户提供的版本号。
3. 不得虚构设备、连接、IP；新增边必须引用已存在或本次新增的节点 id。
4. 删除有关联边的节点时必须设置 cascade=true 或 requiresConfirmation=true。
5. operations 中 add_node 的 value 必须是完整的节点对象（含 id/label/kind）；update_node 的 changes 只允许改 label/style/geometry/manualLocked/properties/groupId。
6. 对破坏性操作（remove_*、update_edge 改端点）设置 requiresConfirmation=true。

JSON Schema（GraphPatch v1）：
{schema}
"""


def propose_patch_system_prompt() -> str:
    # See parse_graph_system_prompt: brace-safe placeholder substitution.
    return PROPOSE_PATCH_SYSTEM_PROMPT.replace(
        "{schema}", (_CONTRACTS / "patch.schema.json").read_text(encoding="utf-8")
    )


def propose_patch_user_prompt(instruction: str, graph_json: str, base_version: int) -> str:
    return (
        f"当前版本：{base_version}\n"
        f"当前 GraphDocument：\n{graph_json}\n\n"
        f"用户修改指令：{instruction}\n"
    )


def repair_feedback_prompt(errors: List[str]) -> str:
    """Feedback used for bounded self-repair attempts."""
    return (
        "你上一次输出的 JSON 校验失败。请根据以下错误修正后，重新只输出一个完整的 JSON 对象：\n"
        + "\n".join(f"- {e}" for e in errors)
    )
