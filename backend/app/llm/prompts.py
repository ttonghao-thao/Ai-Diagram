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

from app.services.materials import device_aliases, theme_catalog

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def graph_schema_text() -> str:
    return (_CONTRACTS / "graph.schema.json").read_text(encoding="utf-8")


PARSE_GRAPH_SYSTEM_PROMPT = """你是一个严格的网络/业务拓扑结构化助手。把用户的自然语言描述转换成一个符合下方 JSON Schema 的 GraphDocument。

硬性规则：
1. 只输出一个 JSON 对象（GraphDocument），不要输出任何解释、Markdown 或代码块。
2. 不得虚构文中没有声明的物理连接、IP 地址、接口与端口；业务属性仅在用户明确给出时添加；可以另外填写已识别的 deviceType、deviceTypeRaw、networkRole、tier。
3. 无法识别的设备类型使用 kind="generic"，并把用户原词放入 properties.deviceTypeRaw。分开表达设备子类型与网络角色。
4. 关系类型：网络设备之间的"连接"用 kind="physical"、direction="undirected"；系统间调用/访问用 kind="logical"、direction="forward"；数据读写用 kind="dataflow"。
5. 对描述含糊、无法确定端点的句子：不要生成边，而是在 warnings 中加入 {code: "AMBIGUOUS_RELATION", message, requiresConfirmation: true}。
6. 未识别的设备类型在 warnings 中加入 {code: "DEVICE_TYPE_GUESSED", message, requiresConfirmation: false}。
7. 不要发明 groups（除非用户明确描述了分区/区域及其成员）；diagramId 由用户描述生成合法 id（^[A-Za-z][A-Za-z0-9_-]{0,63}$）；默认 layout.algorithm="layered"、direction="DOWN"、preserveManualPositions=true。仅在用户明确要求时设置其他策略与方向。
8. schemaVersion 固定为 "1.1"；nodes/groups/edges 必须存在（可为空数组）；所有 id 全局唯一。
9. 字段白名单：node 只允许 id/label/kind/groupId/properties/geometry/manualLocked/style/origin；edge 只允许 id/source/target/kind/direction/label/sourcePort/targetPort/waypoints/style（**边没有 properties 字段**）；group 只允许 id/label/parentId/geometry/manualLocked/style；顶层只允许 schemaVersion/diagramId/name/diagramType/nodes/groups/edges/layout/appearance/metadata/warnings。不要添加任何白名单之外的字段（如 explanation、notes）。
10. 语言一致：label、name、连线 label 必须使用用户输入的原文语言和原文措辞。用户写“核心交换机”就写“核心交换机”，不要翻译成 Core Switch。
11. 连线标签：物理连线（kind="physical"）默认不写 label；只有用户明确说出了链路名称、带宽或用途时才填写。不要添加 Connection、Uplink、连接、上联 之类自行编造的泛称标签。

12. 仅从明确描述提取布局约束 sameRank、order、align、relativePosition、rank、preservePosition，使用实际节点 ID，不能编造坐标、宽高、线路折点、原生 Shape ID、style、XML、厂商或型号。
13. 主题与连线偏好用 appearance，允许主题：{themes}。标准设备子类型：{devices}。
14. 物理链路的隐藏箭头或标签是视觉配置，不改变已有实体、方向和连接事实。
15. 明确的设备数量必须逐台输出。例如“三台服务器连交换机1”输出服务器 01、02、03 三个 kind="server" 节点，各有一条到交换机1的物理边。“两台设备”输出设备 01、02 两个 kind="generic" 节点，保留原始类型“设备”。“交换机1”中的数字是编号。连接两端都有多台且未说明配对时，使用 AMBIGUOUS_RELATION 警告。“通公网”表达可达性，使用 logical 边。

JSON Schema（GraphDocument 1.1）：
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
    return (PARSE_GRAPH_SYSTEM_PROMPT.replace("{schema}", graph_schema_text())
            .replace("{themes}", ", ".join(theme_catalog()))
            .replace("{devices}", ", ".join(device_aliases())))


PROPOSE_PATCH_SYSTEM_PROMPT = """你是一个拓扑增量修改助手。根据用户指令和当前 GraphDocument 输出一个符合下方 JSON Schema 的 GraphPatch。

硬性规则：
1. 只输出一个 JSON 对象（GraphPatch），不得重新生成整张图。
2. baseVersion 必须等于用户提供的版本号。
3. 不得虚构设备、连接、IP；新增边必须引用已存在或本次新增的节点 id。
4. 删除有关联边的节点时必须设置 cascade=true 或 requiresConfirmation=true。
5. operations 中 add_node 的 value 必须是完整的节点对象（含 id/label/kind）；update_node 的 changes 只允许改 label/style/geometry/manualLocked/properties/groupId。
6. 对破坏性操作（remove_*、update_edge 改端点）设置 requiresConfirmation=true。
7. 使用 update_layout 表达算法、方向和相对布局约束，使用 update_theme 表达主题、线路和标签偏好，id 是当前 diagramId。两者仅改用户明确指定的选项。
8. 不生成坐标、XML、图像数据、底层样式或 Shape ID。只有用户给出确切素材 ID 时可以原样传递 style.shapeId，由本地素材目录校验。

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
