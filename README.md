# AI Diagram Studio — Codex 工程实施包

**V1.2 · 文字或 Graph JSON → 可编辑 `.drawio` → Desktop 编辑 → 回导与增量修改**

FastAPI 编排 GraphDocument、GraphPatch 和版本持久化。TypeScript Renderer 使用官方素材索引和主题配置决定图标、布局与线路，输出 draw.io 原生 XML。React 工作台提供图纸生成、主题、个人素材、回导、质量报告与版本下载。

最新实施与边界见 [V1.2 实施计划与决策](docs/12_V1_2_IMPLEMENTATION.md)，逐项验收见 [验证手册](docs/10_VERIFICATION_MANUAL.md)。Windows Desktop 和服务器部署的实机验收状态见 [遗留问题](docs/11_OPEN_ISSUES.md)。

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

## 本地运行

需要 Python 3.9+ 和 Node.js 20+。默认关闭 LLM，Graph JSON 路径可直接使用。以下命令以仓库根目录为工作目录。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix renderer ci
npm --prefix renderer run build
npm --prefix frontend ci
npm --prefix frontend run build
LLM_ENABLED=true LLM_PROVIDER=mock .venv/bin/python -m uvicorn app.main:app --app-dir backend
```

访问 `http://127.0.0.1:8000/`。真实 LLM 配置见 [deploy/env.example](deploy/env.example)。受控部署的 Docker Compose 配置见 [docs/09_DEPLOYMENT.md](docs/09_DEPLOYMENT.md)。

```bash
.venv/bin/python scripts/validate_fixtures.py
npm --prefix renderer test
.venv/bin/python -m pytest backend/tests
node renderer/dist/src/cli.js generate --input fixtures/v1_2_network.graph.json --output out/v1_2_network.drawio
node renderer/dist/src/cli.js quality --input fixtures/v1_2_network.graph.json --drawio out/v1_2_network.drawio --output /tmp/diagram-quality.json
```

使用 [V1.2 网络样例](out/v1_2_network.drawio)检查双防火墙分层、服务器区嵌套分组、编号顺序和原生 Cisco 图标。素材配置和更新流程见 [素材目录说明](renderer/assets/catalogs/README.md)。

## 文件目录

```text
AI_Diagram_Studio_Codex_Package/
├── README.md                    # 唯一总入口
├── AGENTS.md                    # Codex 项目工作规约
├── CODEX_START_PROMPT.md        # 可直接粘贴到 Codex
├── docs/                        # 00→07，按开发阅读顺序排列
├── contracts/
│   ├── graph.schema.json        # GraphDocument 1.0 / 1.1
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
