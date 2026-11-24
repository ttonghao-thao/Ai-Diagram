# V1.2 专业图形生成实施计划

设计来源为 《Ai-Diagram 专业图形生成能力升级设计方案 V1.2》，实施基线为 `0885845982ffc5279976ec8e0080ae59b5b923fb`。

| 阶段 | 交付 | 验证记录 |
|---|---|---|
| 1 | 兼容 GraphDocument 1.0/1.1、GraphPatch 与 Prompt | Python、TS、JSON Schema 同步及历史读写 |
| 2 | 固定上游素材索引、主题、设备规范化、统一样式解析 | Cisco 原生素材、尺寸和增量一致性 |
| 3 | 网络角色和约束、分组和星形布局、线路由、质量报告 | 典型拓扑、冲突、人工折点和规模测试 |
| 4 | 导入、局部修改、重排、视觉状态与版本原子性 | API 闭环、未知 cell、样式与坐标保护 |
| 5 | 个人素材、主题与布局工作台、示例和交付 | 构建、浏览器、验收台账、远端 main |

## 兼容性与实施口径

- 新写版本使用 1.1，存量 1.0 快照继续按原版本读取。输入 1.0 仍可生成，旧主题字段继续生效。现有 REST 路径和响应保留，新增字段为可选。
- 保持 FastAPI、Renderer、ELK.js、SQLite 与原始 XML 边界。Renderer 统一决定生成样式，Python 对已有 XML 定向编辑。
- 个人素材和偏好先按单实例工作台持久化。可导入、导出保真的组合素材，只有通过完整往返的单图形可直接放置。
- 实际 Windows draw.io Desktop、真实模型和服务器部署分别记录证据。待确认决定进入遗留台账。

## 实施决定

- V1.2 的普通设备顺序由 ELK 决定。显式顺序与同类编号由后置约束处理。V1.0 路径延续已有同层顺序设置。直接在 compound 子布局强制模型顺序曾导致 ELK 抛错，嵌套组排序通过后置规则验收。
- 典型角色包括 `internet`、`perimeter_security`、`core`、`aggregation`、`access`、`internal_security` 和 `endpoint`。显式 `rank` 或 `tier` 优先。外层连线保留原始源、目标和逻辑方向。
- `sameRank` 以当前布局方向的层级轴对齐。和绝对轴排序冲突时返回 `LAYOUT_CONFLICT`，避免隐式搬动锁定对象。局部布局使用 `nodeIds` 或受影响的布局约束。
- 图标、标签和外接框单独测量，样式快照记录来源。用户已通过 XML 调整的图标和宽高优先从版本保留。
- Cisco Classic 的 12 项本地缩略图由固定官方 Viewer 及原生 stencil 渲染。目录其余原生项提供下载式预览。SVG 输入走本地校验，组合模板支持可保真的库导入和导出。
- 新建版本的快照文件包含 `visual-state.json` 和 `quality.json`。未知 XML 保留在原始文件中。涉及已删对象仍被未知 cell 引用时阻止提交。
- 物理链接核对以识别到的原文端点为依据，不能确认时需要人工检查 Graph 草稿。该检查采用保守规则，代词、省略和数量表达可能进入复核。Graph JSON 保留人工确认后直接生成的入口。

## API 增量

| 路径 | 新能力 |
|---|---|
| `POST /api/v1/diagrams/parse` | 可选 `appearance`，`algorithm` 和 `direction`，返回 1.1 草稿 |
| `POST /api/v1/diagrams/{id}/layout` | `scope`、`algorithm`、`direction`、`nodeIds`、`preserveStyles`、`preserveLockedPositions` |
| `POST /api/v1/diagrams/{id}/quality` | 查询指定或当前版本的报告 |
| `POST /api/v1/diagrams/{id}/import/preview` | 和原 `/import/drawio` 一样生成预览，增加样式、大小和折点差异 |
| `GET /api/v1/shapes/search`、`GET /api/v1/shapes/{id}` | 查询离线素材及详情 |
| `POST /api/v1/shapes/import`、`/extract`、`/export` | 导入 SVG 或素材库，从图纸提取节点和导出素材库 |
| `GET /api/v1/themes`、`GET /api/v1/themes/{id}` | 浏览绘图主题 |
| `GET/PUT /api/v1/preferences/shapes` | 持久化设备默认映射和收藏 |

图纸、素材与主题的待验证事项见 [遗留问题](11_OPEN_ISSUES.md)。执行记录见 [实施报告](../IMPLEMENTATION_REPORT.md) 第 17 节。
