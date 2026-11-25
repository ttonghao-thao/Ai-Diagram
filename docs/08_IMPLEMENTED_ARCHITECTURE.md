# 08｜已实现架构（实现侧总览）

## V1.2 运行路径

- 首次生成经 GraphDocument 1.0/1.1 校验和设备标准化后，Renderer 解析 Shape Catalog、用户映射及主题。图标框、标签框与布局框分别测量，ELK 排列后应用显式约束，最终路由和质量检查通过后写入版本。
- Patch 在内存中应用最终语义图，使用 `resolve` 得到受影响样式、坐标和线路。Python 在原始 XML 中更新对应的 cell，生成用于确认的一次性快照。提交时再次核对 `baseVersion`，SQLite 同一事务插入版本索引并推进当前版本。
- Desktop 回导比较图标、原生样式、位置、尺寸、折点与分组。原文件随版本保留，压缩页另存一份原始上传字节，供续编的 XML 采用无压缩页面。
- `visual-state.json` 保存位置、尺寸与样式来源，`quality.json` 保存检查结果。两个文件与 Graph JSON、原始 XML 一同分阶段落盘并记录 SHA-256。历史版本按需读取。
- 工作台的个人素材和偏好使用原 SQLite 实例中的附加表。素材从本地图标目录、官方索引或本地上传读取。官方索引、主题和原生样例预览随程序一起交付。
- 业务与网络继续使用同一套图模型。布局约束、样式和线路检查在 Renderer 内处理。人工样式、折点与未知对象的 XML 保护由原有 Backend 适配边界承担。

下文保留 V1.1 架构记录。新接口和当前实现口径见 [V1.2 实施计划与决策](12_V1_2_IMPLEMENTATION.md)。


> 本文档描述**当前代码的实际架构**；需求与设计决策的权威来源仍是 `docs/00–07` 与 `contracts/*.json`。
> 实现历史与验证记录见 [IMPLEMENTATION_REPORT.md](../IMPLEMENTATION_REPORT.md)。

## 1. 组件与运行形态

```text
Linux 服务器（Docker 或裸机，端口 8000）
├── FastAPI（backend/app/main.py，uvicorn）
│    ├── api/diagrams.py    生成 / 查询 / 校验 / 重排 / 回滚 / 导出 / 版本 / parse
│    ├── api/imports.py     Desktop 回导 preview→commit（一次性令牌）
│    ├── api/patches.py     GraphPatch preview→apply（一次性令牌）
│    ├── schemas/           Pydantic 模型（graph.py=契约镜像；api.py=封套/错误码）
│    ├── graph/validate.py  跨对象语义校验（ID 唯一/端点/组环/物理方向）
│    ├── graph/patch.py     9 操作 Patch 引擎（确认/位置保护/锚点插入）
│    ├── importer/          安全解析 / cell↔graph 映射 / diff / XML 定向编辑
│    ├── llm/               mock（确定性规则）+ OpenAI-compatible（有限修复）
│    ├── services/renderer  渲染子进程桥（argv 数组 / shell=False / 超时 / 输出限）
│    └── storage/           SQLite 元数据 + 文件版本快照（原子 rename）
├── renderer/（TypeScript，构建产物 dist/src/cli.js）
│    ├── ELK.js layered 首次布局（嵌套组，INCLUDE_CHILDREN 正交路由）
│    ├── 网络层级定向（无向边按 公网→路由→防火墙→交换→服务器 排层，仅影响布局）
│    ├── Icon Registry（Cisco / Networks 两套内置主题 + 自定义 SVG 数据 URI）
│    └── drawio XML 写/读器（aiKind/aiDirection 语义标记）
└── frontend/dist（React 静态页，由 FastAPI 挂载；无画布）
```

Windows draw.io Desktop 是**用户本地编辑器**，不属于服务端部署（边界 D-01/D-02）。

## 2. 三条核心数据流

1. **首次生成**：`Graph JSON → Pydantic 校验 → 语义校验 → 渲染子进程（ELK 布局 + XML 序列化）→ reconcile_geometry（把真实渲染坐标写回语义图）→ 原子提交 vNNNN`
   - 网络拓扑图布局时，**无向连线按设备层级定向**（仅喂给布局引擎，语义图的 source/target 不变）：
     云/公网 0 → 出口路由 1 → 防火墙 2 → 交换机 3 → 服务器/数据库/终端 4，层级高者在上；
     同层设备按输入顺序从左到右；有向连线保持声明方向
2. **Desktop 回导**：`上传 → 流式分块限流 → 安全解析（全文件 DOCTYPE 拒绝/解压上限）→ cell↔graph 映射（aiKind 反推）→ 与当前版本 diff → 令牌预览 → commit：压缩页规范化 + XML 原样入库 + 语义字段（properties/origin/manualLocked）保留`
3. **AI 增量修改**：`指令（mock/OpenAI）或 patch JSON → patch.schema 校验 → preview（内存副本逐操作应用 + 破坏性确认 + 锚点插入）→ 一次性令牌 → apply：对当前版本 XML 重放 preview + 定向编辑（仅触点 cell）→ 原子提交`

## 3. 关键约定

- **cell id 映射**：系统对象固定 `n_/g_/e_` 前缀；Desktop 复制产生的异名 cell 以 `imp_` 重映射并写入 manifest `cellMapping`
- **图标主题**：网络拓扑图默认 `cisco`（draw.io 内置 Cisco 库，实心蓝；细黑直线无箭头连线），
  业务架构图用 `networks`（线稿 + 正交折线）；`metadata.iconTheme` 可整图切换，`node.style.iconTheme` 可单节点切换
- **语义标记**：节点/边样式携带 `aiKind`（边另带 `aiDirection`），回导以此无损还原类型；箭头启发式仅为 Desktop 手绘边的回退
- **坐标模型**：语义图恒为绝对坐标；XML 组内 cell 相对父容器；两侧换算走父链
- **版本模型**：只增不改；回滚 = 创建指向目标内容的新版本（origin=rollback）；所有修改类操作携带 baseVersion 乐观锁，冲突返回 409 `VERSION_CONFLICT`
- **存储布局**：`storage/diagrams/<id>/vNNNN/{graph.json, diagram.drawio, manifest.json[, patch.json]}`；上传回导的 XML **原样入库**（压缩页先规范化），XML 为图形事实源

**LLM 草稿清洗**（适配器内，校验之前）：剔除白名单外的字段（如边上的 `properties`）；
去掉物理连线上模型自编的泛称标签（Connection / 连接 / 上联），用户明确命名的标签（Trunk 上联、千兆光纤）保留。
提示词约束：标签使用用户原文语言、物理连线默认不加标签、字段白名单。

## 4. 安全机制（已实现）

上传分块流式读取且超限即断；全文件 DOCTYPE/ENTITY 拒绝；解压后大小上限（防炸弹）；页数/单元数/文件大小限制；渲染子进程 argv 数组 + `shell=False` + 超时 + 输出上限；LLM key 仅环境变量注入；`ai_jobs` 只记元数据不记原文；下载流式并带 `X-Content-SHA256`。**未做**：身份鉴权（限受控内网使用，docs/04 §6）。

## 5. API 一览（/api/v1）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /diagrams | GraphDocument → 创建图纸 + v1 |
| GET | /diagrams、/diagrams/{id} | 列表 / 详情（?version=N） |
| POST | /diagrams/parse | 文本 → Graph 草稿（需 LLM） |
| POST | /diagrams/{id}/validate、/layout、/rollback | 校验 / 重排（新版本）/ 回滚（新版本） |
| GET | /diagrams/{id}/versions、/export/drawio?version=N | 版本列表 / 流式下载 |
| POST | /diagrams/{id}/import/drawio、/import/commit | 回导预览 / 确认提交 |
| POST | /diagrams/{id}/patch/preview、/patch/apply | Patch 预览 / 确认应用 |
| GET | /health、/api/v1/health | 存活与依赖检查 |
