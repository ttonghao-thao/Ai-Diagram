# 复制以下内容交给 Codex

请以当前解压目录为一个全新项目 `ai-diagram-studio`，严格阅读 `README.md`、`AGENTS.md` 和 `docs/00` 至 `docs/07`，再读取 `contracts/*.json`、`fixtures/*`。

目标是：**文字描述或 Graph JSON → LLM（可选）结构化提取 → ELK.js 布局 → `.drawio` 原生可编辑 XML → Windows draw.io Desktop 人工修改 → 上传回导 → Graph Patch 局部修改并重新下载。**

要求：
1. **只先实现 Phase 0**，不接 LLM、不实现 Web UI；从 `fixtures/network.graph.json` 与 `fixtures/business.graph.json` 分别生成可编辑 `.drawio`；代码中实现实际生成算法，不允许硬编码输出 fixture。
2. 采用 Python FastAPI/Pydantic v2（未来服务主架构）、TypeScript/Node.js + ELK.js（布局及 XML 适配），采用最简单的单体仓库结构，锁定依赖和可重复运行命令。Phase 0 可以先不启动 API。
3. LLM 只输出受 Schema 约束的 GraphDocument/GraphPatch，绝不直接写图 XML，也不得虚构设备连接或 IP。
4. Windows draw.io Desktop 是外部编辑器；服务端不要部署 draw.io、PPT、亿图图示，不增加本地同步 Agent。
5. 原始 XML、Graph JSON 与版本快照并存；Phase 2 必须支持回导、未知对象保留、位置保护、Patch 预览/确认和冲突检测。
6. 以 `docs/05_IMPLEMENTATION_TASKS.md` 为唯一任务清单，使用 `docs/06_TEST_ACCEPTANCE.md` 验收；每阶段生成 `IMPLEMENTATION_REPORT.md`，不要把未执行的人工 Desktop 验收写成成功。

现在请：先输出一个简短分阶段执行计划、预计目录结构、Phase 0 技术风险与运行命令；随后**直接实现 Phase 0 并运行可运行的测试**。交付生成的两张 `.drawio`、测试结果、剩余问题及需要我在 Windows 上手工验证的操作步骤。Phase 0 人工 Desktop 验收未完成前，不要自动开始 Phase 1。
