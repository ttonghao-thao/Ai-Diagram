# 03｜ELK 布局与 draw.io XML 双向适配

这是本项目**主要工程难点**，与 LLM 模块解耦。

## 1. 首次布局职责

- ELK.js `layered` 模式，网络拓扑默认从上到下、正交路由；业务架构先考虑嵌套组及跨组边。
- 根据图类型提供样式与层级模板。网络建议云/出口→防火墙→核心→接入→服务器；但**位置模板不是业务事实**，不可凭模板补造 Edge。
- 用文字长度、图标尺寸和标签预留空间估算节点的 `width/height`；保留人工传入的尺寸。
- 采用正交线路径并尽量减少交叉；不能承诺所有密集拓扑绝无交叉。
- 复杂的 nested-group/cross-hierarchy 路由必须用真实用例验证，不可凭算法名称推定支持任意情况。

## 2. 坐标模型（必须统一）

**GraphDocument 内永远以画布绝对坐标保存 `geometry`。**

- ELK.js 嵌套节点坐标与父组相关，需要沿层级累计为绝对值。
- draw.io 组内 cell 的 `mxGeometry x/y` 是相对所属容器，因此导出时要做 `childAbs - parentAbs`。
- 回导按相反方向恢复绝对坐标。用嵌套组固定样例验证往返误差小于等于 1 px。
- 边转折点、线标签与端口锚点分别处理，不要把 waypoints 当成节点坐标。

## 3. 输出 `.drawio` 格式

输出 UTF-8、**未压缩**的单页 `<mxfile>` XML 作为首版默认格式（压缩页导入在 Phase 2 完成）。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="ai-diagram-studio" compressed="false">
  <diagram id="page-1" name="网络拓扑">
    <mxGraphModel dx="0" dy="0" grid="1" gridSize="10" page="1" pageWidth="1600" pageHeight="900">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="n_sw1" value="交换机" vertex="1" parent="1"
                style="rounded=1;whiteSpace=wrap;html=1;">
          <mxGeometry x="180" y="50" width="140" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="n_srv1" value="服务器" vertex="1" parent="1"
                style="rounded=1;whiteSpace=wrap;html=1;">
          <mxGeometry x="180" y="200" width="140" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="e_link1" edge="1" parent="1" source="n_sw1" target="n_srv1"
                style="edgeStyle=orthogonalEdgeStyle;endArrow=none;">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

实现要求：

1. 真实的 Group、Node 和 Edge 都是独立的可选中/可编辑对象，不能合并成静态图片。
2. Node 使用 `vertex=1`，Edge 使用 `edge=1`，source/target 对应真实 cell ID；分组使用 group cell，父子关系正确。
3. 文字经 XML escape；`&`、`<`、`>`、双引号、中文测试要覆盖；style 字符串的内容同样需安全处理。
4. 尽可能使用 draw.io Desktop 自带图形和可移植样式，不能依赖外链在线图片。
5. `fixtures/network.drawio` 只是**预制示例**，不是已交付的 renderer 输出；Codex 必须从 graph fixtures 生成新文件。

参考：[draw.io diagram generation](https://www.drawio.com/docs/reference/diagram-generation/)、[draw.io file format](https://github.com/jgraph/drawio/wiki/File-Format)。

## 4. 保留可逆元数据

- cell ID 固定映射：`n_<nodeId>`、`g_<groupId>`、`e_<edgeId>`。
- 可通过普通 `mxCell` 以及 `UserObject`/`object` 包装附带图模型标识、设备类型、属性；保持兼容 Desktop 的实际保存行为。
- 需要保存对象原始样式、位置和未知属性，避免从服务器 Schema 重新编排导致丢失。
- 任何不认识的 cell 必须在 XML AST 中保持，或标记 `UNRECOGNIZED_CELL` 后限制危险编辑，**不得静默删除**。

## 5. Desktop 回导解析

Phase 2 的导入器至少覆盖：

- 本系统生成的未压缩单页 `mxGraphModel`。
- draw.io Desktop 可能保存的压缩 `diagram` 内容：Base64 + raw DEFLATE + URI 编码形式；必须通过测试 fixture 检查实现。
- `UserObject`/普通 `mxCell`，节点/组的 geometry、style、labels，边的 source/target、waypoints。
- 手工新增、删除、重命名、移动、改线、修改样式；识别变更并输出 Diff。
- 多页文件处理：首版可以提示暂不支持修改并保留原文件；不能悄悄丢弃后续页。

### 回导后的图与原始文件同步

上传 → 解析 XML（安全）→ 与当前版本 Graph + XML 比较 → 预览 Diff → 用户确认 → 创建新版本。导入之前**不能**覆盖服务器当前最新图。未知对象保留其 XML；如自动更新与未知对象冲突，应拒绝操作而不是简化为通用矩形。

## 6. 位置保护与局部布局

顺序为：

1. 已存在的节点和边：优先沿用用户保存的坐标、样式与 waypoints。
2. 新节点：按用户指定 group / 邻接节点定位空白区域，可使用锚点、矩形碰撞检测。
3. 新 Edge：只为新边计算路径，尽量避免与现有对象重叠。
4. 如果无法安全插入：扩容画布/组（需保留相关对象）、产生 `LAYOUT_CONFLICT` 或要求用户允许局部重排。
5. 非必要不要重新序列化全部 XML；更改某个对象时只更新对应 cell。

**不要假定 ELK.js 能直接冻结所有旧节点并自动给出理想的局部重排。** 它主要用于首次布局；保留人工布局需要开发自己的增量策略。

## 7. 文件解析安全

- 禁止外部实体、DTD 以及外部资源抓取；限制最大文件字节数、最大解压字节、页数、节点数量和递归深度。
- 不执行导入的 HTML、脚本或其他可执行内容；返回预览时做好编码，避免 XSS。
- 使用成熟 XML 解析库；压缩失败、恶意内容、未知多页行为返回明确错误，不破坏存储。

## 8. Phase 0 CLI 合约（建议）

```bash
renderer generate --input fixtures/network.graph.json --output out/network.drawio
renderer generate --input fixtures/business.graph.json --output out/business.drawio
renderer validate --input out/network.drawio
```

具体命令名称由 Codex 选定并写进 README，但必须满足：可批量运行、错误时非零退出码、输入/输出与具体 fixture 名无关。最后仍须真实 Windows draw.io Desktop 验收。
