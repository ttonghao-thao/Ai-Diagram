# IMPLEMENTATION_REPORT — Phase 0

> 状态：**Phase 0 自动化部分已完成并通过测试；Windows draw.io Desktop 人工闸门 = BLOCKED（等待用户验证）**。
> 报告日期：2026-11-21。实现环境：macOS (darwin 27.2.0, arm64)、Node v22.22.1、Python 3.9.6。
> 未在本机执行的能力一律标注"未验证"，没有"已通过"的虚构记录。

## 1. 本阶段实现范围

Phase 0 目标（docs/05）：**无 LLM、无 Web、无 GPU** 的确定性路径 `Graph JSON → 语义校验 → ELK.js 布局 → .drawio 原生 XML`。

| 任务项 | 状态 | 说明 |
|---|---|---|
| 0.1 目录初始化（backend/renderer/frontend/deploy/scripts） | ✅ 完成 | frontend 仅占位说明，Phase 1 实现 |
| 0.1 运行版本与锁定依赖 | ✅ 完成 | Node ≥20（实测 v22.22.1）；Python ≥3.9（实测 3.9.6）；依赖精确版本锁定 |
| 0.1 `.env.example` 与 mock 配置 | ✅ 完成 | `deploy/env.example`，Phase 0 无需 LLM 配置 |
| 0.1 `python scripts/validate_fixtures.py` 执行记录 | ✅ 完成 | 见 §3.4 |
| 0.2 Pydantic 图模型（对应 graph.schema.json） | ✅ 完成 | `backend/app/schemas/graph.py` |
| 0.2 语义校验（全局 ID 唯一、端点存在、组有效/无环、物理线方向） | ✅ 完成 | `backend/app/graph/validate.py` + renderer 侧同规则实现 |
| 0.2 非法 Graph 明确错误码、不生成图纸 | ✅ 完成 | CLI 校验失败退出码 1 且不写输出文件（有测试） |
| 0.3 Renderer CLI 对任意合法 Graph JSON 工作 | ✅ 完成 | 无 fixture 硬编码；合成 100 节点图、嵌套组测试均走同一管线 |
| 0.3 网络拓扑布局（层级 + 正交 + 标签空间） | ✅ 完成（外观待 Desktop 人工确认） | ELK layered DOWN + 正交路由；尺寸由标签估算或保留传入尺寸 |
| 0.3 业务架构布局（容器分组 + 跨组连线） | ✅ 完成（外观待 Desktop 人工确认） | swimlane 组容器 + ELK INCLUDE_CHILDREN 层级布局 |
| 0.3 嵌套组绝对/相对坐标转换 | ✅ 完成 | 绝对→相对导出、相对→绝对回读，往返误差 ≤1px 有自动化测试 |
| 0.3 稳定 ID、真实顶点/边/组、正确父子与端点引用 | ✅ 完成 | `n_/g_/e_` 映射；引用完整性有测试 |
| 0.3 XML escaping / 中文 / 样式回归测试 | ✅ 完成 | `& < > "` + 中文标签往返测试 |
| **Phase 0 闸门：两份 fixture 经自研 renderer 生成 out/*.drawio** | ✅ 完成 | 见 §3.1，产物已提交 |
| **Phase 0 闸门：Windows draw.io Desktop 手工实测** | ⛔ **BLOCKED** | 本机为 macOS；等待用户按 §5 步骤执行 |
| **Phase 0 闸门：IMPLEMENTATION_REPORT.md** | ✅ 本文档 | |

## 2. 交付物与目录

```text
backend/
  pyproject.toml                  # pytest 配置（pythonpath/testpaths），依赖声明 pydantic>=2.7,<3
  app/schemas/graph.py            # GraphDocument v1 Pydantic 模型（extra=forbid，与 contracts 同构）
  app/graph/errors.py             # 错误码 + ValidationIssue + GraphValidationError
  app/graph/validate.py           # 跨对象语义校验（收集全部错误，不短路）
  tests/test_schema_models.py     # G-01 + 结构违规
  tests/test_semantic_validation.py  # G-02~G-05 + 物理方向警告
  tests/test_render_output.py     # X-01/X-02（ElementTree 标准解析器复验 out/*.drawio）
renderer/
  package.json / tsconfig.json    # 精确锁定：elkjs 0.12.1、fast-xml-parser 5.12.1、typescript 5.9.3、@types/node 22.20.5
  src/types.ts                    # schema 镜像类型 + n_/g_/e_ cell id 函数
  src/validate.ts                 # renderer 侧 schema+语义校验（与 Python 错误码一致）
  src/shapes/styles.ts            # kind→draw.io 样式（内置可移植形状）、边方向箭头规则、标签尺寸估算
  src/layout/elkLayout.ts         # ELK layered（含嵌套组）→ 绝对坐标；manual 模式
  src/drawio/xmlWriter.ts         # 未压缩单页 mxfile 序列化（组内相对坐标转换）
  src/drawio/xmlReader.ts         # Phase 0 只读校验/往返测试用解析器（压缩页/多页显式拒绝）
  src/cli.ts                      # generate / validate 命令，退出码 0/1/2
  test/*.test.ts                  # 30 个测试（结构、转义、往返、CLI、性能）
out/network.drawio                # 交付物：network.graph.json 生成
out/business.drawio               # 交付物：business.graph.json 生成
deploy/env.example                # Phase 1 配置预留（LLM_*、RENDERER_*、存储路径）
frontend/README.md                # Phase 1 占位
```

## 3. 实际执行的命令与结果

### 3.1 生成两张交付图（自研 renderer，无 fixture 硬编码）

```bash
cd renderer && npm run generate:all
```

实际输出：

```text
OK generated ../out/network.drawio (diagram "示例：核心交换机与三台服务器"): 7 cells, 5 edges, page 900x645, 55ms
OK generated ../out/business.drawio (diagram "示例：业务平台分区架构"): 8 cells, 4 edges, page 900x600, 60ms
```

```bash
cd renderer && npm run validate:network && npm run validate:business
```

```text
OK ../out/network.drawio: 14 cells (7 vertices incl. 1 groups, 5 edges), page 900x645, name "示例：核心交换机与三台服务器"
OK ../out/business.drawio: 14 cells (8 vertices incl. 3 groups, 4 edges), page 900x600, name "示例：业务平台分区架构"
```

生成内容要点：层级自上而下（外部网络→防火墙→核心交换机→服务器区）；服务器为 swimlane 组内子对象（相对坐标）；物理连线 `endArrow=none` 无方向箭头；跨组边由 ELK 生成正交弯点写入 `<Array as="points">`。

交付物 SHA-256（生成时刻，供 Windows 侧传输后比对）：

```text
e678318d0a1559c79cb846c6857a70d233a8533ea4487de017f960931a5878fd  out/network.drawio
d9e4be24dc54679cecec78eda0d9f901712ff1701e181d03521607e23e494caf  out/business.drawio
```

### 3.2 renderer 测试（node:test）

```bash
cd renderer && npm test
```

```text
# tests 30  # pass 30  # fail 0  # skipped 0
```

覆盖：G-02~G-05 错误码（TS 侧）、X-01 XML 可解析、X-02 vertex/edge 标志与引用完整性、X-03 中文与 `& < > "` 转义往返、X-04 嵌套组三层坐标往返 ≤1px（layered 与 manual 两种模式）、X-05 性能、CLI 集成（非法输入退出码 1 且不写文件、用法错误退出码 2）。

### 3.3 backend 测试（pytest）

```bash
cd backend && python3 -m pytest
```

```text
24 passed in 0.07s
```

覆盖：G-01（fixtures 对 `contracts/graph.schema.json` 的 Draft 2020-12 校验 + Pydantic 解析）、G-02 全局重复 ID（同类与跨类型）、G-03 端点不存在、G-04 groupId/parentId 不存在、G-05 组环/自环、物理方向警告、结构违规（版本号、ID 正则、空标签、未知 kind、非正 geometry、多余字段）、X-01/X-02（用标准库 ElementTree 复验 out/ 交付物，含组相对坐标断言）。

### 3.4 交付包素材自检（开发前验证）

```bash
python3 scripts/validate_fixtures.py
```

```text
PASS graph: network.graph.json: 6 nodes, 5 edges
PASS graph: business.graph.json: 5 nodes, 4 edges
PASS drawio XML: network.drawio: 14 cells
NOTE: Windows draw.io Desktop open/edit/save test still required.
```

> 注意：`scripts/verify_package.py` 校验的是**原始交付 ZIP 的文件清单与 SHA-256**。开发新增 backend/、renderer/、out/ 等目录后，该脚本按设计将不再通过（文件清单必然变化），不影响 `validate_fixtures.py`。这是预期行为，不是缺陷。

### 3.5 X-05 性能实测（100 节点 / 150 边，5 组，网络拓扑，DOWN 正交）

```text
# PERF X-05: layout=250.8ms serialize=0.6ms total=251ms (100 nodes / 150 edges, page 1434x9224)
```

单机实测值（macOS arm64, Node v22.22.1），未做内存采样；该合成图分层极深（每组 20 节点纵向链），页面高度偏大属正常。**未验证项**：更大规模（≥300 节点）、内存峰值、并发渲染。

## 4. 实现决策记录（需要用户知晓）

| # | 决策 | 原因与影响 |
|---|---|---|
| D-P0-1 | `layout.algorithm=layered` 时 **ELK 决定全部位置**；传入 geometry 只取 width/height 作为固定尺寸，x/y 不参与布局 | 符合 AGENTS/D-04"首次布局用 ELK.js"；fixture 的预设坐标是手绘参考，不是布局真值。`algorithm=manual` 时传入的绝对坐标原样保留（有测试） |
| D-P0-2 | 物理边（kind=physical）无论 direction 如何，渲染一律无箭头；direction≠undirected 时返回 `GRAPH_PHYSICAL_EDGE_DIRECTION` **警告** | 对 docs/02"物理连线默认不代表数据方向"与 docs/05 0.2"物理线不含默认方向约束"的实现解释：渲染层强制无方向 + 校验层告警。若需要硬错误可一行改动 |
| D-P0-3 | 单撇号 `'` 在 XML 属性中不转义（属性一律双引号包裹），`& < > "` 转义 | 与 draw.io 自身序列化行为一致；XML 规范中单引号在双引号属性内合法 |
| D-P0-4 | Edge cell 一律 `parent="1"`（根层），waypoints 用绝对坐标 | 与 fixtures/network.drawio 预制样例一致；draw.io 对父层为根的边用绝对坐标空间 |
| D-P0-5 | 画布归一化仅用于 layered 模式（内容左上角对齐 40px 边距）；manual 模式不平移 | 手工坐标必须逐像素保留（docs/03 §6） |
| D-P0-6 | Phase 0 用普通 `mxCell` 承载对象（不写 `UserObject`/object 包装）；properties（如 IP）暂不写入 XML 可见属性 | 预制样例即此形态，Desktop 兼容风险最低；Phase 2 导入器必须同时识别两种包装（docs/03 §4），届时再决定是否为属性增加 UserObject |
| D-P0-7 | renderer 内部重复实现校验（与 Python 同规则同错误码） | docs/01 架构中 renderer 接收"受校验数据"，但 CLI 独立运行时必须自防御；两侧一致性由相同错误码测试保障。代价：双份实现需同步维护，已在此记录 |
| D-P0-8 | `renderer validate` 遇到多页/压缩页直接报 `DRAWIO_UNSUPPORTED_CONTENT` | V1 范围（docs/03 §3）只生成未压缩单页；显式拒绝优于静默容错，Phase 2 放开 |
| D-P0-9 | 未指定的 `sourcePort/targetPort` 不生成端口锚点 | 不编造物理接口（D-09）；属性文本亦不渲染在图上，避免泄密与噪声 |

## 5. 需要 Windows 用户手工验证的操作步骤（Phase 0 闸门）

**以下步骤尚未执行，Phase 0 人工闸门状态 = BLOCKED。** 请在 Windows 机器上按序执行并回填 §6 模板。

1. 把本目录同步到 Windows 机器（或仅拷贝 `out/network.drawio`、`out/business.drawio` 两个文件）。
2. 安装/打开 **draw.io Desktop**（记录其版本号），分别打开两张文件。
   - [ ] network.drawio：云/防火墙/核心交换机/服务器区各对象**可单独选中、拖动**；物理线无箭头。
   - [ ] business.drawio：三个 swimlane 分区可整体拖动，组内节点可拖动，数据库为圆柱形；跨组连线带箭头（接口调用=虚线，内容读写=双向）。
3. 在 network.drawio 中：改一个节点名称 → 拖到新坐标 → 改一条边的端点 → 保存。
4. 在 business.drawio 中：拖动分组容器 → 修改一个跨组连线的端点 → 保存。
5. 检查保存后的文件仍能再次正常打开（无对象丢失、无样式丢失）。
6. 记录 Windows 版本、Desktop 版本、两个文件的 SHA-256、异常现象与截图。

> 若第 3~5 步全部正常，Phase 0 人工闸门即可标记 PASS，方可进入 Phase 1（FastAPI + 版本存储 + 最小 Web 台）。

### 手工验收记录模板（回填处）

```text
验收时间：
Windows 系统版本：
draw.io Desktop 版本：
测试文件：out/network.drawio / out/business.drawio
文件 SHA-256：
  network.drawio:
  business.drawio:
生成命令：cd renderer && npm run generate:all（Node v22.22.1, elkjs 0.12.1）
测试项：打开 / 拖动 / 重命名 / 改线 / 保存 / 重新打开
结果：BLOCKED（等待 Windows Desktop 手工验证）
观察与错误：
是否丢失节点、样式、连接：
验收人：
```

## 6. 已知限制与风险（诚实清单）

1. **Desktop 兼容性未验证**：本机无 Windows draw.io Desktop，所有"可编辑性"结论仅基于 XML 结构正确性、预制样例形态一致性（同一 mxfile/mxGraphModel/swimlane/正交边结构）与 docs 参考格式，不构成 Desktop 实测通过。
2. **ELK 正交路由不保证无交叉**：密集拓扑（尤其跨组多边）可能出现线路交叉或绕行，人工精修属预期工作流（docs/03 §1 明示）。
3. **组标题超长可能溢出 swimlane 标题栏**：ELK 按子节点内容定组宽，长标题（>组宽）会被截断显示；Phase 0 未做标题宽度补偿。
4. **尺寸估算是启发式**：无 geometry 的节点按 CJK/ASCII 宽度估算，极长标签会在 max 340px 处截断换行；带 geometry 的节点尺寸原样保留。
5. **双份校验实现**（Python/TS）需同步维护；当前由相同错误码的测试对齐。
6. **verify_package.py 按设计失效**（见 §3.4），后续阶段如需包完整性自检应另建基于新清单的脚本。
7. X-05 未记录内存占用；X-04 的 ≤1px 实际做到 0px（纯浮点换算），1px 为容差上限。

## 7. 遗留问题 / 下一阶段入口

- Phase 1（等待 Windows 闸门反馈后开始）：FastAPI（/api/v1 全套）、SQLite+文件版本快照、最小 React 台、LLM adapter（mock + OpenAI-compatible）、A-01~A-03/V-01~V-03 测试。
- Phase 2 入口依赖本阶段产物：`out/*.drawio` 的结构、cell id 映射（n_/g_/e_）与未压缩格式即回导解析器的输入契约。
- 建议改进（不阻塞）：把 `renderer validate` 升级为可校验"任意系统生成文件"（含 manifest 对比）；为 ELK 增加 `elk.layered.considerModelOrder` 调参以减少边交叉。

## 8. Phase 0.5：专业设备图标支持（2026-11-21 追加交付）

> 状态：**自动化测试全部通过 + 渲染复现已完成；Windows Desktop 人工闸门仍为 BLOCKED（与 Phase 0 闸门一并验证）**。
> 未重构 Phase 0 架构：Graph JSON、ELK.js 布局管线与 XML 序列化结构不变，Icon Registry 为纯增量模块。

### 8.1 实现内容

| 要求 | 实现 |
|---|---|
| Icon Registry | `renderer/src/shapes/iconRegistry.ts`：NodeKind → 图标描述（stencil 样式 / 兜底样式 / 默认尺寸 / 来源） |
| 优先原生形状与专业 stencil | 8 类设备全部映射到 draw.io 内置 `mxgraph.networks` stencil（Desktop 自带，无外链），`service` 用核心库 `shape=process`，`generic` 用中性平面设备盒 |
| 自定义 SVG、零在线加载 | 本地目录 `renderer/assets/icons/<名称>.svg`（kind 或 deviceType 别名）或节点级 `style.icon`；内嵌为 style 中的 data URI，无任何运行时网络请求；≤64KB、拒绝 `<script>`/`javascript:` |
| 布局考虑图标尺寸/设备名称/端口 | ELK 节点盒 = 图标盒 + 24px 标签带（标签画在图标下方 `verticalLabelPosition=bottom`）；无 geometry 时按 registry 默认尺寸并按设备名宽度加宽；连线按布局几何计算**固定方向锚点**（exitX/exitY/entryX/entryY，指向目标一侧），连接端点显式可控；Graph JSON 中的 sourcePort/targetPort 仍不映射为固定坐标（不编造端口，见 §4 D-P0-9） |
| 无法识别设备类型 | kind=`generic` → 通用设备盒图标；`properties.deviceType` 原值保留在 style 中（`aiDeviceType=<原值>`），同时每个节点写入 `aiKind=<kind>`，便于 Desktop 样式面板查看与 Phase 2 差异识别；deviceType 若恰与 registry 键同名则升级为对应专业图标 |
| 不重构 | Graph JSON schema 零改动；ELK 管线只换尺寸来源函数；XML 结构（mxfile/mxGraphModel/swimlane 组/边 parent=1）不变 |

### 8.2 Stencil 名称的权威验证（不凭记忆）

形状标识符取自 drawio v24.7.17 源码（jsdelivr CDN 可达，GitHub 直连超时）：

- `stencils/networks.xml`（57 个形状）含 "Switch"、"Router"、"Firewall"、"Server"、"Virtual Server"、"Storage"、"Cloud"、"Terminal" 等；
- `mxStencilRegistry.parseStencilSet`（viewer.min.js）：注册名 = `packageName + "." + name.toLowerCase().replace(/ /g, "_")`；
- 最终映射：switch→`mxgraph.networks.switch`、router→`.router`、firewall→`.firewall`、server→`.server`、vm→`.virtual_server`（备选 Virtual PC，选 Virtual Server 因其更贴近主机虚拟化）、database→`.storage`、cloud→`.cloud`、client→`.terminal`。

### 8.3 渲染复现与一个关键根因修复

用在线 viewer.diagrams.net（纯客户端渲染，内容为虚构样例）对生成文件做了可视化复现：

1. `mxgraph.networks` stencil 全部正确渲染：云朵、砖墙火焰防火墙、交换机机箱、机架服务器；标签在图标下方；组与正交连线正常。
2. **发现并修复**：自定义 SVG 以 base64 data URI 嵌入时图标**空白**。根因（有源码证据）：draw.io 的 style 字符串解析按 `;` 切分（`mxGraph.getCellStyle`），`...;base64,xxx` 中的分号把样式值截断为 `data:image/svg+xml`（复现：渲染出的 `<image>` href 恰为 18 字符）。修复：`svgImageStyle` 改用 draw.io 自家图片管线偏好的**百分号编码**形式 `data:image/svg+xml,%3Csvg...`（不含 `;`，`postProcessCellStyle` 有对应分支）；`node.style.icon` 的 base64 输入会被规范化为该形式。复现修复后打印机 SVG 图标正常渲染。
3. 防御性收紧：`svgImageStyle` 现在拒绝 base64/非 SVG 的 image 值并给出解释性错误。

### 8.4 实际执行的测试

```bash
cd renderer && npm test          # 45/45 通过（较 Phase 0 新增 15 个 iconRegistry 测试）
cd backend && python3 -m pytest  # 24/24 通过（对重新生成的 out/*.drawio 复验）
npm run generate:all             # 两张交付图以专业图标重新生成
```

新增测试覆盖：registry 全 kind 覆盖与尺寸正值；8 类 stencil 标识符与权威名称一致；sanitize 规则（保留中文设备名）；generic+deviceType 保留原类型；deviceType 别名升级图标；自定义 SVG 目录加载/内嵌（断言 `data:image/svg+xml,` 形式且**不含 `;base64,`**）；恶意 SVG（script/javascript:/非 SVG/超 64KB）拒绝；标签带预留（layered 下几何高度=图标高度）；生成的 XML 含 aiKind/aiDeviceType/固定锚点且可回读。

### 8.5 交付物（已更新，SHA-256 覆盖 §3.1 旧值）

```text
7e6031f886595535015912e99989bbe2c6e28e9dcec98dcf475e584f75fbb9e2  out/network.drawio
5980068c5c7cec317e8a31167987e1ca0f106d3f07949113bccd09f1fe8b0e2c  out/business.drawio
```

### 8.6 决策记录（Phase 0.5 追加）

| # | 决策 | 说明 |
|---|---|---|
| D-P05-1 | 自定义 SVG 嵌入统一为百分号编码 data URI | §8.3 根因；base64 形式会被 style 解析截断 |
| D-P05-2 | 所有节点标签画在图标下方，ELK 高度加 24px 标签带 | 统一美学与布局预留；标签带不写入 XML 几何（仅布局内部） |
| D-P05-3 | 边使用固定方向锚点（按布局几何推导），不再完全浮动 | 满足"考虑连接端口"且首版路由更可预期；Phase 2 如需用户级端口映射另行设计 |
| D-P05-4 | `aiKind`/`aiDeviceType` 写入 style 字符串 | 保留原始设备类型信息、辅助 Phase 2 差异；为自管命名空间，值经 sanitize（`;=` 与控制符替换） |
| D-P05-5 | vm 映射 `virtual_server` 而非 `virtual_pc` | 语义接近服务器虚拟化；可在 registry 一行调整 |

### 8.7 Windows 手工验收增补项（并入 §5 步骤执行）

- [ ] network.drawio：云=云朵、防火墙=砖墙火焰、核心交换机=机箱面板、三台服务器=机架服务器图标；图标可**拖动/缩放**（Ctrl+滚轮或右键编辑尺寸）；连线仍正确吸附图标轮廓。
- [ ] business.drawio：数据库=存储阵列图标、终端=终端设备图标、服务=流程框；组容器拖动时组内图标随动。
- [ ] 任一节点 Edit Style 中可见 `aiKind=...`（generic 节点还有 `aiDeviceType=...`）。
- [ ] 修改图标尺寸后保存再打开，形状不变形、标签不丢。
