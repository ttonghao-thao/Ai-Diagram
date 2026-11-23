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

## 9. Phase 1：完整首次生成工作流（2026-11-21 交付）

> 状态：**后端 API、版本存储、LLM 适配、最小 Web 工作台均已实现并通过自动化测试；docker compose 未在本机验证（无 Docker）**。
> 按用户指示越过"Windows Desktop 人工闸门"继续开发；该闸门仍为 BLOCKED，Phase 1 产物在 Desktop 中的可编辑性沿未验证状态记录。

### 9.1 实现内容（对照 docs/05 Phase 1 任务清单）

| 任务 | 实现 |
|---|---|
| FastAPI（创建/查询/校验/布局/导出/版本列表） | `backend/app/api/diagrams.py`：`POST /api/v1/diagrams`、`GET /api/v1/diagrams/{id}`、`POST /api/v1/diagrams/parse`、`POST .../validate`、`POST .../layout`、`GET .../export/drawio?version=N`、`GET .../versions`、`GET /api/v1/health`；响应封套 `{requestId, data}` / `{requestId, error{code,message,details}}`；`/api/docs` 提供 OpenAPI |
| SQLite + 文件版本快照 | `app/storage/db.py`（projects/diagrams/diagram_versions/ai_jobs 四表）+ `app/storage/versions.py`（`storage/diagrams/<id>/vNNNN/{graph.json, diagram.drawio, manifest.json, patch.json}`，SHA-256，原子 rename 发布，DB 失败回滚目录（V-03），`baseVersion` 乐观锁冲突返回 `VERSION_CONFLICT` 409） |
| 渲染子进程桥接 | `app/services/renderer.py`：argv 数组 + `shell=False` + timeout + 输出大小上限；renderer 的 `ERROR <CODE>` stderr 协议映射为 API 错误码 |
| 最小 React 管理台 | `frontend/`（React 18 + TS + Vite）：生成图纸 / 文本解析 / 校验 Graph / 图纸与版本（列表、版本历史、SHA-256、逐版本下载、基于当前版本重排）。无画布 |
| LLM adapter | `app/llm/adapter.py`：`MockLlmAdapter`（确定性规则解析，动词感知的边类型：读写→dataflow 双向 / 调用→logical 正向 / 设备连接→physical 无向；数量词展开；IP 片段显式不解析并告警）+ `OpenAICompatibleAdapter`（/chat/completions、JSON 约束提示词、Pydantic 校验、最多 LLM_MAX_RETRIES 次修复反馈，超限 `LLM_INVALID_OUTPUT`）；`LLM_ENABLED=false` 时 JSON 路径完整可用（A-01） |
| 不制造事实 | mock 解析器不虚构连接/IP/端口：无端点子句→`AMBIGUOUS_RELATION`（requiresConfirmation=true）且不建边；未知设备→generic+deviceType+`DEVICE_TYPE_GUESSED`；含 IP→`IP_ADDRESSES_NOT_PARSED` |

### 9.2 实际执行的命令与结果

```bash
cd backend && python3 -m pytest         # 55 passed（24 Phase 0/0.5 + 14 Phase 1 API + 17 文本用例）
cd frontend && npm install && npm run build   # 构建成功（151.63 kB JS / 2.21 kB CSS）
cd renderer && npm test                 # 45/45（未受 Phase 1 影响）
python3 -m uvicorn app.main:app ...     # 浏览器端到端冒烟：生成 v1 + 下载 + mock 文本解析（截图见对话记录）
```

Phase 1 闸门"至少 10 个文本用例可生成合法 Graph"：`tests/test_phase1_text_cases.py` 覆盖 12 个正向用例 + 5 个真实错误/边界用例（无设备文本、自环、未知设备、歧义子句、ID 派生），全部通过并作为归档。

### 9.3 端到端冒烟（真实执行）

`LLM_ENABLED=true LLM_PROVIDER=mock uvicorn app.main:app` 启动后浏览器操作：
1. 生成页加载"网络拓扑"示例 → 点击生成 → `已创建 demo_network … v1` + SHA-256 + 下载链接（截图确认）。
2. 文本解析页输入"一台核心交换机连接三台服务器" → 草稿 4 节点/3 边/Schema 合法（截图确认）。
3. `/health` 与 `/api/v1/health` 均报告 rendererAvailable=true、llm enabled(mock)。

### 9.4 决策记录（Phase 1 追加）

| # | 决策 | 说明 |
|---|---|---|
| D-P1-1 | 创建图纸直接接收 GraphDocument JSON（而非仅文本） | docs/04 的 parse 端点独立存在；JSON 直达路径即 D-07 确定性路径 |
| D-P1-2 | `POST /diagrams/{id}/layout` 以新版本落盘（origin=layout）而非仅返回预览 | Phase 1 无局部修改，整图重排 = 新版本；`baseVersion` 必填并做 409 检查 |
| D-P1-3 | ai_jobs 只记录请求元数据（类型/提供商/状态/耗时/错误码），不记录原文与拓扑 | docs/04 §6 日志红线 |
| D-P1-4 | mock 解析器的边类型按动词区分（读写=数据流双向、调用=逻辑正向、连接=物理无向） | 确定性可测试；真实模型接入后由提示词约束（`llm/prompts.py`） |
| D-P1-5 | `documentWarnings` 与校验器警告在 API 分列返回 | LLM 产生的 warning（歧义/未知设备/IP）与语义校验警告来源不同，前端分别着色 |
| D-P1-6 | compose/Dockerfile 已编写但未在本机执行 | 本机无 Docker；启动命令、卷挂载与构建步骤经人工核对，标记"未验证"，见 §9.5 |

### 9.5 Phase 1 已知限制

1. **docker compose up --build 未实际执行**（本机无 Docker）；`deploy/Dockerfile`（node:20-bookworm-slim + python3）与 `deploy/compose.yaml` 仅为交付物。
2. 文本解析质量为 mock 基线：复杂句式/嵌套分区不做承诺（docs/06 §5 的语义质量评估属后续基准工作）。
3. 前端"重新布局"在并发修改下可能返回 409（乐观锁按设计生效，UI 提示错误码）。
4. LLM 兼容端点的 `response_format=json_object` 依赖服务商支持；不支持时由 JSON 提取兜底 + 有限重试。

## 10. Phase 2：Desktop 回导与 AI 增量修改（2026-11-21 交付）

> 状态：**安全导入器、Diff、GraphPatch 引擎、预览/确认/原子应用、XML 定向编辑、前端两个新页签均已实现并通过自动化测试**；真实 Windows Desktop 上传回导仍属 BLOCKED 人工闸门（本阶段用"模拟桌面修改的 XML"完成自动化与 API 级验证）。

### 10.1 实现内容（对照 docs/05 Phase 2 任务清单）

| 任务 | 实现 |
|---|---|
| 2.1 安全解析未压缩与压缩页 | `app/importer/xml_parser.py`：压缩页按 drawio v24.7.17 `Graph.compress/decompress` 源码确认的管线解码（`encodeURIComponent(xml) → deflateRaw → base64`，Python 侧 `quote(safe="!~*'()") + zlib(wbits=-15) + b64`）；**解压后大小上限 6MB（流式解压防炸弹）**；上传 ≤10MB；DOCTYPE/ENTITY 一律拒绝；多页文件 → `DRAWIO_UNSUPPORTED_CONTENT`（415），原文件不动 |
| 2.1 识别 mxCell/object/UserObject 等 | `object`/`UserObject` 包装：外层 id/label + 内层 mxCell 合并解析；`aiKind`/`aiDeviceType` 样式键反推设备类型；未知 cell（无 n_/g_/e_ 前缀且无 aiKind）收集为 unknown 列表，**原样保留不删除不转换** |
| 2.1 差异预览 | `model_map.diff_graphs`：节点增删/改名/移动/类型变化，边增删/重接/标签变化，组增删/改名，附 summary 计数 |
| 2.1 baseVersion + preview→commit | `POST /import/drawio`（multipart+baseVersion）→ 一次性 confirmationToken（内存 TTL 15min）；`POST /import/commit` 重新核对当前版本后提交；**提交时上传的 XML 原样存储**（XML=图形事实源），派生 graph 为语义视图；语义-only 字段（properties/origin/manualLocked）从当前版本为存活节点保留（桌面改名/移动不会丢 IP 标注） |
| 2.2 Patch 9 种操作 | `app/graph/patch.py`：先经 `contracts/patch.schema.json`（jsonschema Draft 2020-12）校验，再逐操作语义校验；add/update/remove × node/edge/group；全部操作先应用到内存副本并整体校验，失败不产生半成品 |
| 2.2 破坏性确认 | remove_node 有关联边 → 需 `requiresConfirmation` 或 `cascade`；remove_edge/update_edge 改端点/类型 → 需 `requiresConfirmation`；remove_group 非空 → 需确认+cascade；缺确认 → `DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED`（422） |
| 2.2 位置保护 | `manualLocked` 对象的 geometry 更新 → `LAYOUT_CONFLICT`（409）；新增组内成员时：组内锚点插入，未锁定的满组向下扩容（成员不动），锁定满组 → `LAYOUT_CONFLICT`；根级节点锚点邻近插入 + 画布向下扩容；从不自动全图重排（`layoutPlan.movedNodes` 恒为空） |
| 2.2 定向 XML 修改 | `app/importer/xml_edit.py`：只改动受影响 cell（绝对→相对坐标换算走 XML 父链）；新增节点样式复用 Phase 0.5 stencil 模板 + aiKind；边按 kind/direction 生成箭头与固定锚点；未知 cell 与其他用户样式逐字节保留；graphId↔cellId 映射存入 manifest（导入重映射场景） |
| API | `POST /api/v1/diagrams/{id}/import/drawio`、`/import/commit`、`/patch/preview`、`/patch/apply`；apply 需一次性令牌 + baseVersion 双重核对，令牌预览后重放/版本推进 → 409 |
| mock propose_patch | 支持"新增N台设备并连接目标 / 删除目标 / 重命名目标为新名"；目标按 label 精确→包含匹配，命中多个或未命中 → `AMBIGUOUS_RELATION`（不虚构连接）；新增节点 id 用推断出的英文 kind 作基名（firewall_1 等） |
| 前端 | 新增"导入回导"页（选图纸→上传→差异表+警告→确认提交）与"AI 修改"页（指令→预览（确认要求/受影响对象/警告/布局计划/差异）→确认应用→下载新版本） |

### 10.2 实际执行的命令与结果

```bash
cd backend && python3 -m pytest      # 76 passed（24 Phase 0/0.5 + 31 Phase 1 + 21 Phase 2）
cd renderer && npm test              # 45/45（未受影响）
# API 级全链路（curl，真实执行）：
# v1 initial → patch preview/apply → v2 ai_patch → 模拟桌面修改 → import preview/commit → v3 desktop_import
# → 指令 patch → v4 ai_patch；版本链 [(1,initial),(2,ai_patch),(3,desktop_import),(4,ai_patch)]
# 浏览器 UI：AI 修改页 预览→应用 截图确认；重复指令正确返回 GRAPH_DUPLICATE_ID 错误面板
```

### 10.3 测试覆盖（docs/06 §3 对应）

| 编号 | 结果 | 说明 |
|---|---|---|
| I-01 | ✅ | 未压缩回读：diff=0 + 提交后 v2 graph 与 v1 一致；桌面模拟修改（改名/移动/重接）diff 正确且 XML 原样存储 |
| I-02 | ✅ | 压缩页按 drawio 管线解码（测试内用同管线构造压缩文件，断言往返） |
| I-03 | ✅ | 未知自定义 cell：警告 `UNKNOWN_CELLS_PRESERVED`；提交与后续 Patch 应用后 `custom_shape` 仍逐字存在 |
| I-04 | ✅ | 多页文件 415 拒绝，current_version 不变 |
| I-05 | ✅ | DOCTYPE/ENTITY 400 拒绝；超大上传 413；压缩炸弹（~8MB 解压）413/415 拒绝 |
| P-01 | ✅ | 新增 2 节点 2 边：旧对象几何逐项不变；XML 新 cell parent=g_server_zone、stencil 样式、aiKind；令牌一次性 |
| P-02 | ✅ | 删除有关联边节点：未确认 422；确认+cascade 后边级联移除 |
| P-03 | ✅ | 重接线未确认 422；确认后 XML target 更新 |
| P-04 | ✅ | manualLocked 节点移动 → 409 `LAYOUT_CONFLICT`；锁定满组插入 → 409；未锁满组向下扩容且成员不动 |
| P-05 | ✅ | 预览不落库；令牌在版本推进后 apply → 409；baseVersion 不符 → 409 |
| 补充 | ✅ | patch.schema.json 非法结构 400；禁改字段（kind 等）400；mock 指令目标歧义 422 |

### 10.4 决策记录（Phase 2 追加）

| # | 决策 | 说明 |
|---|---|---|
| D-P2-1 | 提交回导时**上传 XML 原样入库**，派生 graph 仅作语义视图 | docs/02 §8：XML 是图形事实源；确保未知对象与用户样式零损耗 |
| D-P2-2 | 语义-only 字段（properties/origin/manualLocked）跨桌面回导保留 | XML 不承载这些字段，不做保留会导致 IP 标注等语义数据在正常桌面循环中丢失 |
| D-P2-3 | 创建/重排后用渲染输出的真实几何**回写存储 graph**（reconcile_geometry） | 否则存储 graph 保留占位坐标，回导 diff 会显示全量移动；同时保证锚点插入基于真实位置 |
| D-P2-4 | Patch 应用 = 预览重放 + 定向 XML 编辑 + 原子提交 | 预览令牌一次性消费；apply 时对当前版本重新跑 preview，杜绝"预览后图已变"的陈旧应用 |
| D-P2-5 | 根级无空位时允许画布向下扩容，锁定满组才 LAYOUT_CONFLICT | docs/03 §6 允许"扩容画布/组（需保留相关对象）"；冲突语义收敛到"无法不动锁定对象" |
| D-P2-6 | Python 侧节点/边样式模板与 TS iconRegistry 重复一份 | 定向编辑不经过 ELK 渲染器；两份模板同为 mxgraph.networks 权威映射，报告中声明同步义务（与 D-P0-7 同类） |
| D-P2-7 | 预览令牌存内存（TTL 15min、一次性） | 单进程 MVP；多实例部署需改外部存储，已在限制中记录 |

### 10.5 Phase 2 已知限制

1. **真实 Windows Desktop 上传回导未执行**（闸门 BLOCKED 继承）；自动化以模拟桌面修改的 XML 覆盖。
2. ~~压缩页 Patch 拒绝~~ 已在评审修复（§11 P0-1）中解决：导入提交时压缩页规范化为未压缩入库。导入仍不支持多页（显式拒绝）。
3. 令牌存内存：重启服务后未消费的预览令牌失效（客户端需重新预览）。
4. `renderer validate` 未接入导入流程的结构预检（导入走 Python 解析器自校验，二者规则一致但实现独立）。
5. Diff 为字段级摘要，不含样式级细粒度（style 变更未逐键对比）。

## 11. 评审修复（Phase 2.1，2026-11-22）

对项目目标与实现进行全面评审后，修复了三个 P0 级正确性缺陷（均为"语义图 ↔ 图形层"双向保真问题）。修复前后的行为对照与证据：

### 11.1 P0-1：压缩页回导后 AI 修改被永久卡死

- **原缺陷**：导入提交将上传 XML 原样入库，若 Desktop 保存出压缩页，后续所有 Patch 应用因"压缩页不支持编辑"被拒绝，用户无出路。
- **修复**：导入提交时经 `normalize_to_uncompressed`（xml_parser.py）把压缩页解码为未压缩单页入库（语义不变，仅编码规范化），manifest 记录 `normalizedFromCompressed`；commit 响应新增该字段。
- **测试**：I-02 改写——压缩回导后断言入库为未压缩，并**在其上继续完成一次 Patch 应用**（闭合卡死链路）。

### 11.2 P0-2：`update_edge` 改类型后 XML 样式不同步

- **原缺陷**：patch 允许改边的 kind/direction（语义层更新），但 XML 定向编辑不重写 style，下载图纸的箭头/虚线仍是旧类型。
- **修复**：xml_edit.py 的 update_edge 在 kind/direction 变化时按模板重建样式（含 `aiKind/aiDirection` 标记与锚点）；**仅端点变化**时只刷新 exitX/entryX 等锚点键、保留用户其余样式。
- **测试**：P-03 扩展（物理→dataflow：断言 `endArrow=block`、`strokeColor=#4A7E53`、标记更新）；新增"纯端点变更保留样式、锚点仍在"用例。

### 11.3 P0-3：边类型回导静默退化

- **原缺陷**：renderer 不在边样式上写语义标记，回导走箭头启发式，logical/control/dependency 全部退化为 dataflow，且 diff 不比较边类型 → 类型丢失既发生又不可见。
- **修复**：① renderer `composeEdgeStyle` 为每条边写入 `aiKind=<kind>;aiDirection=<direction>`；② 导入侧优先读取这两个标记（箭头启发式仅作为 Desktop 手绘边的回退，报告中声明其局限）；③ `diff_graphs` 新增 `edgeKindChanged`/`edgeDirectionChanged` 并计入 summary。
- **测试**：业务图 fixture 回导 diff=0 且四种边 kind/direction 逐项保留；"Desktop 手绘箭头（无标记）"场景的启发式回退结果以 `edgeKindChanged` 显式上报。

### 11.4 交付物与测试

`out/*.drawio` 已用修复后 renderer 重新生成（边样式新增语义标记，SHA-256 取代 §8.5 旧值）：

```text
3d25698b562f2dc996238876f722f0ec0520901e408232499e180ee9b27c394e  out/network.drawio
ee97759678844175bd499ae2d67d375ffae055480f041683bb21cbdb58d06b99  out/business.drawio
```

回归：backend **79 passed**（+3：业务往返、端点变更锚点、启发式 diff 检测）；renderer **45/45**（含新断言）；`validate_fixtures.py` PASS。

### 11.5 评审中确认、本次未修（待排期）

按优先级：上传先读后限（内存 DoS 面）→ DOCTYPE 全文扫描 → 流式下载 → 版本回滚端点 → 导入后自动锁定策略声明 → 重复实现对照测试 → frontend lockfile/npm ci → 前端自动化。详见评审记录。

## 12. P1 加固与文档体系（2026-11-23）

### 12.1 评审 P1 项修复（对照评审记录）

| 项 | 修复 | 验证 |
|---|---|---|
| 上传先读后限（内存 DoS 面） | `imports.py::_read_upload_limited`：256KB 分块流式读取，超限立即 413，不再全量缓冲 | 大文件（~100KB vs 1KB 限制）流式拒绝测试 |
| DOCTYPE 检查只扫首尾窗口 | 新增共用 `guard_no_dtd`（xml_parser.py），全文正则扫描；parse/normalize/xml_edit 三处统一接入 | DOCTYPE 藏于 5KB 注释之后 → 400 拒绝（旧窗口检查会放过） |
| 下载非流式 | export 改 `StreamingResponse`，256KB 分块读盘，保留 Content-Disposition/X-Content-SHA256 | 既有导出测试全部保持通过 |
| Dockerfile frontend 未锁依赖 | frontend 补交 package-lock.json 并改 `npm ci`；新增仓库根 `.dockerignore`；镜像/Compose 增加 HEALTHCHECK | 静态核对（无 Docker 实机，维持"未验证"声明） |
| PreviewTokenStore 清理失效 | `_ts` 缺失按 0 处理立即过期（旧默认值使差值恒 0） | 代码审查确认 |
| 版本回滚缺失（docs/04 §5.5 / docs/01 §6） | `POST /diagrams/{id}/rollback {targetVersion, baseVersion}`：创建 origin=rollback 新版本指向目标内容，历史不动；前端版本页新增"回滚到此版本" | 新端点测试：回滚成功（v3=回滚，v1 字节不变，链完整）、409 过期、404 目标不存在 |
| 重排无二次确认 | 前端"重新布局"增加 confirm 弹窗（提示手工位置丢失、可回滚） | 前端构建通过 |
| 锁定策略未声明（docs/02 §8） | 策略明示：manualLocked 为显式语义字段，跨回导保留；Desktop 移动不自动锁定，解锁是用户决定 | 新增导入保留 manualLocked 的断言测试 |
| 双实现漂移无检测 | 新增 tests/test_phase_p1.py 同步测试：静态（TS networksStencil 参数 vs Python mxgraph.networks 清单一致）+ 行为（10 种 kind 渲染→导入全保真） | 8/8 通过 |

### 12.2 文档体系

新增实现侧文档四份（需求侧 docs/00–07 保持原样）：

- [docs/08_IMPLEMENTED_ARCHITECTURE.md](docs/08_IMPLEMENTED_ARCHITECTURE.md)：实际架构、三条核心数据流、关键约定、安全机制、API 一览
- [docs/09_DEPLOYMENT.md](docs/09_DEPLOYMENT.md)：Docker 与裸机两条部署路径、环境变量表、备份/升级、已知限制
- [docs/10_VERIFICATION_MANUAL.md](docs/10_VERIFICATION_MANUAL.md)：自动化验证命令与预期输出 + Windows Desktop 人工验收清单（含压缩页专项）+ 记录模板
- [docs/11_OPEN_ISSUES.md](docs/11_OPEN_ISSUES.md)：遗留问题台账（阻塞/安全/功能/工程四类 + WONTFIX 理由）

### 12.3 回归

backend **87 passed**（79 + 8 个 P1 测试）；renderer **45/45**；`validate_fixtures.py` PASS。

### 12.4 容器部署首次实机记录（2026-11-23，用户环境）

- `docker compose up --build`：**镜像构建成功**（160.2s，前端/渲染器 npm ci + 构建均通过）
- 运行时失败：`ModuleNotFoundError: No module named 'app.storage'`
- 根因：`.dockerignore` 裸名模式 `storage` 在 Docker 的匹配规则下命中任意层级，误排除 `backend/app/storage/` 代码包
- 修复：运行时数据目录锚定为 `/storage`、`/data`、`/out`；新增 `tests/test_dockerignore_guard.py`（模拟 dockerignore 匹配语义，断言全部 backend/frontend/renderer 运行时文件不被排除、数据目录仍被排除）
- 状态：待用户重跑确认运行时（docs/09、docs/11 B-2 已同步更新）
