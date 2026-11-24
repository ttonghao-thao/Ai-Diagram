# 02｜统一图模型、LLM 与增量修改

## 1. 契约来源

**字段的权威定义**分别是：

- [`../contracts/graph.schema.json`](../contracts/graph.schema.json)：GraphDocument 1.0 / 1.1。
- [`../contracts/patch.schema.json`](../contracts/patch.schema.json)：GraphPatch v1。

本文件解释语义、补充跨对象校验规则，不再维护第二份容易冲突的字段表。

## 2. GraphDocument

V1.2 新写入的图纸版本为 1.1，1.0 文件可读并可用于生成。历史 Graph JSON 和 XML 按既有版本读取。主题优先采用 `appearance.themeId`，其次采用 `metadata.iconTheme`。图纸主题、连接标签和箭头策略始终保留原始边语义。

`layout.constraints` 支持 `sameRank`、`order`、`align`、`relativePosition`、`rank`、`preservePosition`。`star` 可用 `layout.centerNodeId` 指定中心。设备子类型和网络角色通过 `properties.deviceType`、`deviceTypeRaw`、`networkRole`、`tier` 表达，素材通过 `style.shapeId` 引用。冲突约束返回 `LAYOUT_CONFLICT`。

GraphPatch 支持 `update_layout` 与 `update_theme`。两个操作的 `id` 均为当前图纸的 `diagramId`，`changes` 覆盖对应设置。其余 Patch 的实体修改全部应用至内存图后，再解析画法、计算位置和生成预览。


顶层至少包含：`schemaVersion`、`diagramId`、`name`、`diagramType`、`nodes`、`groups`、`edges`、`layout`。图类型仅 `network_topology` 和 `business_architecture`。可选 `metadata` 和 `warnings`。

**Node**：`id`、`label`、`kind`、可选 `groupId`、`properties`、`geometry`、`manualLocked`、`style`、`origin`。支持 switch、router、firewall、server、vm、cloud、service、database、client、generic；不认识的设备使用 generic 并保留原名，不任意改写为其他设备。

**Group**：`id`、`label`、可选 `parentId`、`geometry`、`manualLocked`、`style`；包含关系不放在 Edges 中。支持嵌套，无自引用或组环。

**Edge**：`id`、`source`、`target`、`kind`、`direction`、可选 `label`、`sourcePort`、`targetPort`、`waypoints`、`style`。`kind` 是 `physical|logical|dataflow|control|dependency`，`direction` 是 `undirected|forward|bidirectional`；物理连线默认不代表数据方向。

**Layout**：`algorithm`=`layered|manual`，`direction`=`DOWN|RIGHT|UP|LEFT`，`preserveManualPositions` 布尔值。`geometry` 记录图纸画布的**绝对坐标**；生成组内 cell 时必须转相对坐标。

## 3. 示例与开发入口

网络拓扑 fixture：[`../fixtures/network.graph.json`](../fixtures/network.graph.json)。业务架构 fixture：[`../fixtures/business.graph.json`](../fixtures/business.graph.json)。

```json
{
  "schemaVersion": "1.0",
  "diagramId": "demo_network",
  "name": "示例拓扑",
  "diagramType": "network_topology",
  "nodes": [
    {"id": "sw1", "label": "核心交换机", "kind": "switch"},
    {"id": "srv1", "label": "业务服务器", "kind": "server"}
  ],
  "groups": [],
  "edges": [
    {"id": "l1", "source": "sw1", "target": "srv1", "kind": "physical", "direction": "undirected"}
  ],
  "layout": {"algorithm": "layered", "direction": "DOWN", "preserveManualPositions": true}
}
```

以上关系为示意，并非从用户照片自动提取的真实连接。

## 4. 必须由程序校验的语义约束

仅 JSON Schema 不足以完成以下校验：

1. Node、Group、Edge 的 ID 在整个图中**全局不重复**。
2. Edge.source 与 Edge.target 均引用存在的 Node（MVP 先不允许 Group-Edge）。
3. Node.groupId 与 Group.parentId 指向存在的 Group，且 Group 不形成嵌套循环。
4. 删除 Node 若存在关联 Edge，默认拒绝；删除 Group 不可默默删掉子节点/边。
5. Edge 端点改变（reconnect）属于高风险修改；`update_edge` 改端点必须显式确认。
6. 物理连接、访问/调用、数据流、包含关系严格区分。
7. 不基于布局美观“补齐”未声明的关系，未给定 IP/接口/端口保持为空或缺省。
8. 唯一 ID 不由 `label` 反推；重命名仅改 `label`。

## 5. LLM 的职责与 API

**任务 A：parse_graph**

输入：用户自然语言 + 选定图类型 + 可用 Node kind 列表。输出：GraphDocument 草稿及 warnings/clarifications。通过 Schema 严格验证，不合法则有限次修复，仍失败返回结构化错误。服务器布局器决定坐标。

**任务 B：propose_patch**

输入：用户操作指令 + 最新 GraphDocument（可裁剪不相关属性） + `baseVersion`。输出：GraphPatch（增删改操作），不得重新生成整张图。警告和确认信息由后端校验。

建议适配器接口：

```python
class LlmAdapter(Protocol):
    async def parse_graph(self, text: str, diagram_type: str) -> GraphDocument: ...
    async def propose_patch(self, instruction: str, graph: GraphDocument, base_version: int) -> GraphPatch: ...
```

提供 `mock` 模型、OpenAI-compatible 客户端两种实现；输出 JSON Schema 约束优先，不能用无限重试“修复”错乱结果。

## 6. GraphPatch 原子变更

当前 [`patch.schema.json`](../contracts/patch.schema.json) 约定：`baseVersion`、`operations[]`、可选 `reason`/`warnings`。支持 9 个操作：`add/update/remove_node`、`add/update/remove_edge`、`add/update/remove_group`。

```json
{
  "baseVersion": 2,
  "operations": [
    {"op": "add_node", "id": "server2", "value": {"id": "server2", "label": "服务器02", "kind": "server"}},
    {"op": "add_edge", "id": "link2", "value": {"id": "link2", "source": "sw1", "target": "server2", "kind": "physical", "direction": "undirected"}}
  ]
}
```

服务端采用 **preview → 用户确认（若必要）→ apply**：

- preview 不修改存储；返回 patch、受影响 ID、验证警告、拟执行的布局影响。
- apply 必须核对服务器当前 `baseVersion`，全部操作先应用到内存副本并统一校验，成功后以新版本持久化；任何一步失败不能产生半成品版本。
- 允许语义校验之外的确认规则：删除和重接线的高风险操作、原有连接的不明确变更。
- 如果无法保留已锁定的手工位置，返回 `LAYOUT_CONFLICT`，不得暗中执行全图重排。

## 7. ID 与 XML 对象映射

输出 XML 时建议分别使用 `n_<id>`、`g_<id>`、`e_<id>`；回读需能够识别普通 `mxCell` 与 `UserObject` / `object` 包装。保存稳定 ID ↔ cell ID 映射，记录复制对象可能引起的新 ID。不能仅靠名称配对。

## 8. 需要工程实现者明确的边界

- `patch.schema.json` 的 `value`/`changes` 是允许扩展的字典，但 **后端应按目标对象类型再次严格校验**，不得任意修改禁用字段。
- Graph JSON 是语义层，`.drawio` 是图形层；在 Desktop 回导后，**XML 为当前图形事实来源**，必须把变更同步回 GraphDocument，不能仅导出旧 JSON 重画。
- `manualLocked=true` 仅表达不允许自动移动；导入人工移动后可将对象标记锁定，具体策略应在实现报告中明示并有测试。
