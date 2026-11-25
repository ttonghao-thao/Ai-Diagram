# Codex 开发规约（项目根目录）

## 任务目标

根据 `docs/` 和 `contracts/` 实现：文字或 Graph JSON → 可编辑 `.drawio` → Windows draw.io Desktop 编辑 → 回导 → AI 增量修改。

## 开始前必须读取

1. `README.md`
2. `docs/00_SCOPE_AND_DECISIONS.md`
3. `docs/01_ARCHITECTURE.md` ~ `docs/07_RISKS_AND_OPEN_QUESTIONS.md`
4. `contracts/graph.schema.json`、`contracts/patch.schema.json`
5. `fixtures/network.graph.json`、`fixtures/business.graph.json`、`fixtures/network.drawio`

## 硬性边界

- Windows draw.io Desktop 是用户电脑上的独立编辑器；不得假定服务器能操控其 GUI。
- 服务器 **不** 部署 draw.io，**不** 创建全功能 Web 画布编辑器，**不**开发 PPTX / EDDX 输出。
- LLM 仅产出 GraphDocument、GraphPatch；不能让 LLM 生成 `.drawio` XML 或替代布局算法。
- 首次布局用 ELK.js；手工移动后的图优先保留原位置，不擅自重排已锁定对象。
- XML 与语义图模型必须并存；未知/自定义 cell 不得被静默丢弃。
- 不编造物理连接、IP 地址、接口与端口；有歧义时给出 warning/clarification。
- 支持 `mock` 与 OpenAI-compatible LLM；在没有模型/GPU 的情况下可以运行确定性绘图和测试。

## 工作顺序

1. 先实现 `docs/05_IMPLEMENTATION_TASKS.md` 的 Phase 0；通过测试和 Windows 手工闸门再进入 Phase 1。
2. 每阶段提供真实命令、改动文件清单、实际执行的测试结果、遗留问题。
3. 创建并持续维护 `IMPLEMENTATION_REPORT.md`。未经验证的能力标记为“未验证”，绝不写“已通过”。
4. 改动 Schema 或 API 之前先说明兼容性影响，同时更新文档、fixtures 和测试。

## 安全与质量

- 原生 `.drawio` 原始文件按版本快照保存，不覆盖历史文件；修改需 `baseVersion` 乐观锁。
- XML 禁用外部实体，限制文件/页数/节点/解压体积；用户输入不可拼接 Shell。
- 默认不在日志中记录完整内部网络拓扑、IP、账号凭据或 API 密钥。LLM 密钥通过门户配置，加密保存，API 仅返回掩码。
- 确保 schema 校验、graph 校验、文件往返、压缩页面、版本冲突、未知 cell、坐标稳定等自动化测试。
