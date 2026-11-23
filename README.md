# AI Diagram Studio — Codex 工程实施包

> **交付类型：需求/架构/数据契约/测试样例/开发指令**，不是已完成的可运行产品。  
> **版本：v1.1（2026-11-21）**  
> **唯一实现目标：文字或 Graph JSON → 可编辑 `.drawio` → Windows draw.io Desktop 人工编辑 → 回导 → AI 局部修改。**

## 30 秒了解项目

系统接收用户的文字描述或节点与关联关系，使用 LLM 提取结构化图模型；使用 ELK.js 自动安排位置及路径；生成 **draw.io 原生 XML `.drawio` 文件**，在 **Windows draw.io Desktop** 中直接打开编辑。人工保存后可将图纸上传，系统识别更改并支持 AI 增量修改。**服务端不安装 draw.io，也不新建 Web 画布编辑器。**

- **已有的**：设计文件、JSON Schema、结构化测试样例、预制 `.drawio` 示例、校验工具。
- **Codex 要开发的**：FastAPI、LLM 适配、图模型与 Patch 引擎、ELK.js 布局、draw.io XML 双向适配、轻量 Web 工作台、版本持久化、测试。
- **不在本次范围**：PPT 导出、亿图图示 `.eddx`、多模态图片还原、Windows 自动同步程序、在线绘图编辑器。

## 阅读顺序（只有这一套）

| 顺序 | 文件 | 职责 |
|---|---|---|
| 1 | [docs/00_SCOPE_AND_DECISIONS.md](docs/00_SCOPE_AND_DECISIONS.md) | 目标、MVP 边界、技术决策、待评估事项 |
| 2 | [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) | 组件、部署、运行流程、前端界面 |
| 3 | [docs/02_GRAPH_AND_PATCH.md](docs/02_GRAPH_AND_PATCH.md) | 图模型、校验、LLM 输入输出、Graph Patch |
| 4 | [docs/03_DRAWIO_ADAPTER.md](docs/03_DRAWIO_ADAPTER.md) | ELK、XML 生成和回读、坐标、未知对象处理 |
| 5 | [docs/04_API_AND_STORAGE.md](docs/04_API_AND_STORAGE.md) | REST API、数据库、版本、文件安全 |
| 6 | [docs/05_IMPLEMENTATION_TASKS.md](docs/05_IMPLEMENTATION_TASKS.md) | 任务顺序、阶段闸门、任务完成定义 |
| 7 | [docs/06_TEST_ACCEPTANCE.md](docs/06_TEST_ACCEPTANCE.md) | 自动化测试及 Windows Desktop 验收 |
| 8 | [docs/07_RISKS_AND_OPEN_QUESTIONS.md](docs/07_RISKS_AND_OPEN_QUESTIONS.md) | 风险、未知点、延后事项 |

**规范优先级：**`docs/00_SCOPE_AND_DECISIONS.md`（边界）→ `contracts/*.json`（数据字段）→ 其余 `docs/*.md`（实现细节）。如冲突，Codex 记录冲突并提出最小修正，不静默变更要求。

## 让 Codex 开始

1. 解压完整 ZIP 至一个新的工作目录，例如 `ai-diagram-studio/`。
2. 在该目录启动 Codex，先读取根目录 [`AGENTS.md`](AGENTS.md)。
3. 将 [`CODEX_START_PROMPT.md`](CODEX_START_PROMPT.md) 内容粘贴到 Codex。
4. **只允许先做 Phase 0**：Graph JSON → ELK → `.drawio`；无需 LLM、网页、GPU。
5. Windows 上使用 draw.io Desktop 真正打开、编辑、保存一次，并反馈测试结果；通过后再做 Phase 1/2。

**开发前的素材验证：**

```bash
python -m pip install jsonschema
python scripts/validate_fixtures.py
```

上述检查仅验证 JSON、XML 的结构与引用关系，**不代表 Desktop 兼容性已通过**。

## Phase 0 / 0.5 / 1 / 2 实现与运行命令（2026-11-21）

确定性管线 `Graph JSON → 语义校验 → ELK.js 布局 → .drawio` 已实现并全部通过自动化测试；
Phase 0.5 追加**专业设备图标**（内置 `mxgraph.networks` stencil + 本地自定义 SVG，零在线加载）；
Phase 1 交付 **FastAPI + SQLite/文件版本快照 + LLM（mock/OpenAI-compatible）+ 最小 React 工作台**；
Phase 2 交付 **Desktop 回导（安全解析/压缩页/Diff/未知对象保留）+ GraphPatch 增量修改（预览→确认→原子应用、位置保护、XML 定向编辑）**。
**Windows draw.io Desktop 人工闸门为 BLOCKED，等待实测**。完整状态见 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)；
实现架构见 [docs/08](docs/08_IMPLEMENTED_ARCHITECTURE.md)，部署方案见 [docs/09](docs/09_DEPLOYMENT.md)，
验证手册见 [docs/10](docs/10_VERIFICATION_MANUAL.md)，遗留问题台账见 [docs/11](docs/11_OPEN_ISSUES.md)。

确定性管线 `Graph JSON → 语义校验 → ELK.js 布局 → .drawio` 已实现并全部通过自动化测试；
Phase 0.5 追加了**专业设备图标**（内置 `mxgraph.networks` stencil + 本地自定义 SVG，零在线加载）。
**Windows draw.io Desktop 人工闸门为 BLOCKED，等待实测**。完整状态见 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)；
实现架构见 [docs/08](docs/08_IMPLEMENTED_ARCHITECTURE.md)，部署方案见 [docs/09](docs/09_DEPLOYMENT.md)，
验证手册见 [docs/10](docs/10_VERIFICATION_MANUAL.md)，遗留问题台账见 [docs/11](docs/11_OPEN_ISSUES.md)。

```bash
# 1) 素材自检
python3 scripts/validate_fixtures.py

# 2) Renderer：Graph JSON -> ELK.js -> 可编辑 .drawio（无 LLM/网络/GPU 依赖）
cd renderer
npm install          # 首次；依赖精确锁定（elkjs 0.12.1 / fast-xml-parser 5.12.1 / typescript 5.9.3）
npm test             # 构建 + 45 个自动化测试，并产出 out/network.drawio、out/business.drawio
npm run generate:all # 生成两张交付图（专业设备图标）
node dist/src/cli.js generate --input ../fixtures/templates/enterprise_network.graph.json --output ../out/enterprise_network.drawio  # 组网图模板
node dist/src/cli.js generate --input ../fixtures/network.graph.json --output ../out/network.drawio
node dist/src/cli.js generate --input <graph.json> --output <file.drawio> --icons-dir <自定义SVG目录>
node dist/src/cli.js validate  --input ../out/network.drawio

# 3) 图模型与语义校验 + Phase 1 API（FastAPI + SQLite + LLM mock）
cd ../backend && python3 -m pytest   # 87 个测试（G/X + A/V + 文本用例 + I/P + P1 加固/同步）

# 4) Web 工作台（Phase 1/2：生成 / 解析 / 校验 / 版本 / 导入回导 / AI 修改）
cd ../frontend && npm install && npm run build     # 产物由 FastAPI 静态挂载
cd .. && LLM_ENABLED=true LLM_PROVIDER=mock python3 -m uvicorn app.main:app --app-dir backend
#   打开 http://127.0.0.1:8000/ （生成 / 文本解析 / 校验 / 版本与下载）

# 5) Docker（未在本机验证）
cd deploy && cp env.example .env && docker compose up --build
```

实现目录：`backend/`（Pydantic 模型 + 语义校验 + FastAPI + 版本存储 + LLM adapter）、
`renderer/`（TypeScript 渲染器 CLI + 图标注册表 + `assets/icons/` 自定义 SVG 目录）、
`frontend/`（React 最小工作台，无画布）、`out/`（Phase 0 两张交付图）、
`deploy/`（env.example / Dockerfile / compose.yaml）。

## 文件目录

```text
AI_Diagram_Studio_Codex_Package/
├── README.md                    # 唯一总入口
├── AGENTS.md                    # Codex 项目工作规约
├── CODEX_START_PROMPT.md        # 可直接粘贴到 Codex
├── docs/                        # 00→07，按开发阅读顺序排列
├── contracts/
│   ├── graph.schema.json        # GraphDocument v1
│   └── patch.schema.json        # GraphPatch v1
├── fixtures/
│   ├── network.graph.json       # 网络拓扑语义样例
│   ├── business.graph.json      # 业务架构语义样例
│   ├── network.drawio           # 预制 XML 示例；非生成器运行结果
│   └── reference_images/        # 用户原始示例照片，仅作外观参考
├── scripts/
│   └── validate_fixtures.py     # 交付包静态自检
└── PACKAGE_MANIFEST.json        # 文件清单与 SHA-256（自检生成）
```

## 关键事实与限制

- `.drawio` 不是静态图片；XML 描述节点、分组、连线、文字和坐标。
- `fixtures/network.drawio` 是 **预先准备的最小格式样例**，不能用它冒充 Codex 实现的生成器成果。
- 原始参考照片中的设备名称/IP/线条可能存在辨识困难；**不是机器可自动判定的真值数据**。结构化样例采用虚构信息和文档测试 IP。
- 亿图图示 `.eddx` 仅在先前讨论中被评估，**未正式替换 draw.io**。

## 技术依据

- [draw.io XML 生成参考](https://www.drawio.com/docs/reference/diagram-generation/)
- [draw.io 文件格式说明](https://github.com/jgraph/drawio/wiki/File-Format)
- [ELK Layered 算法参考](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html)
