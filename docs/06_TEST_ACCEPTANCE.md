# 06｜测试计划与验收记录

## 1. 当前交付包能验证什么

当前 ZIP 提供：`contracts/*.json`、`fixtures/*.json`、`fixtures/network.drawio` 和 `scripts/validate_fixtures.py`。这些只能验证**输入契约和预制 XML 的基本结构**，不能证明 Codex 未来生成的文件能在 Windows Desktop 编辑。测试结果请以实际运行记录为准。

安装开发时所需的最小校验依赖并执行：

```bash
python -m pip install jsonschema
python scripts/validate_fixtures.py
```

## 2. Phase 0 自动化测试（建议最小集合）

| 编号 | 测试 | 预期结果 |
|---|---|---|
| G-01 | 网络、业务 fixtures 对 Schema | 均通过 |
| G-02 | 重复 Node/Edge/Group ID | 拒绝，`GRAPH_DUPLICATE_ID` |
| G-03 | 不存在的 Edge.source / target | 拒绝 |
| G-04 | 不存在的 groupId / parentId | 拒绝 |
| G-05 | 嵌套分组循环 | 拒绝，`GRAPH_GROUP_CYCLE` |
| X-01 | 两份图经 renderer CLI 输出 XML | 均可由标准 XML 解析器读取 |
| X-02 | 节点 `vertex=1`、边 `edge=1` | 引用/父子关系有效 |
| X-03 | 中文及 `& < > "` | 文字无截断、XML 合法 |
| X-04 | 嵌套 Group 子节点 | 绝对坐标↔相对坐标往返误差 ≤1 px |
| X-05 | 100 节点/150 边布局 | 记录实测耗时/内存；不虚报性能 |

**注意**：`fixtures/network.drawio` 是预制最小结构示例，不能替代 X-01 中 Codex 自动生成的文件。

## 3. Phase 1 / 2 自动化测试

| 编号 | 测试 | 预期结果 |
|---|---|---|
| A-01 | `LLM_ENABLED=false` + Graph JSON | 可生成并下载 `.drawio` |
| A-02 | LLM 输出非法 JSON | 校验失败、返回错误，不写入版本 |
| A-03 | 物理连接含歧义 | warnings/clarifications；不擅自补线 |
| V-01 | 导出版本 v1 后再提交 v2 | v1 文件未被覆盖 |
| V-02 | 使用旧 baseVersion | 返回 409 `VERSION_CONFLICT` |
| V-03 | 写文件失败或提交失败 | current_version 不推进 |
| I-01 | 未压缩 XML 回读 | Node/Group/Edge 和位置恢复 |
| I-02 | Desktop 压缩 XML 回读 | 能安全解压、正确解码 |
| I-03 | 未知自定义 cell | 原 XML 保留或安全拒绝，不被删除 |
| I-04 | 多页文件 | 不支持时明确拒绝，原文件不丢失 |
| I-05 | XML 外部实体、超大压缩内容 | 拒绝，禁止访问外部资源 |
| P-01 | Patch 新增节点与连线 | 新对象可编辑，旧布局保留 |
| P-02 | 删除有关联 Edge 的 Node | 需要显式处理或确认 |
| P-03 | 重接线但未确认 | 拒绝修改 |
| P-04 | 移动手工锁定对象的布局计划 | 拒绝或产生冲突提示 |
| P-05 | 预览不提交 | 项目版本不变化 |

## 4. Windows draw.io Desktop 手工验收（必做）

只在**真正 Windows 安装的 draw.io Desktop** 上验证；自动 XML 解析通过不能算此项通过。

1. 从 Codex 生成的 `out/network.drawio` 打开，确认交换机、服务器和线条都是独立对象。
2. 改一个节点名称，拖到新坐标，并修改一条边的端点；保存文件。
3. 将文件上传到 Web 工作台，检查 Diff 中包含改名、位置与端点变化。
4. 确认导入，输入“新增两台服务器并连接核心交换机，其余位置不变”。
5. 检查 Patch 是否只修改目标对象，下载第二版并重新打开。
6. 对业务架构图重复检查分组容器拖动、跨组连线和文本属性。
7. 记录 draw.io Desktop 版本、操作系统版本、文件 SHA-256、观察现象、通过/失败截图。

### 手工验收记录模板

```text
验收时间：
Windows 系统版本：
draw.io Desktop 版本：
测试文件：network.drawio / business.drawio
生成命令：
测试项：打开 / 拖动 / 重命名 / 改线 / 保存 / 回导 / 再次修改
结果：PASS / FAIL / BLOCKED
观察与错误：
是否丢失节点、样式、连接：
验收人：
```

若未执行，请写 **BLOCKED（等待 Windows Desktop 手工验证）**，不得写 PASS。

## 5. AI 语义质量评估

采用至少 20 个结构化样例（网络与业务各 10），随后增加 30–80 个自然语言变体；分别统计：

- Graph Schema 合法率（**建议目标** ≥99%，非现成模型实测）。
- Node precision/recall，Edge precision/recall，分组完整性。
- 未经描述就添加物理连接的错误数量（目标 0）。
- 无关对象改动数、锁定对象位置变化数（目标 0）。
- 模型、提示词版本、响应耗时、失败原因；禁止无限修复循环。

原始参考图两张只作为外观参照，线条和文字模糊部分需人工确认，不当作无误差的 ground truth。

## 6. 验收规则

- Phase 0：结构化输入→程序生成可编辑 XML + Windows Desktop 手工通过。
- Phase 1：自然语言生成/JSON 生成 + 版本管理 + 最小 Web 工作台。
- Phase 2：回导与增量续编 + 旧布局保护 + 版本冲突 + 未知对象安全。
- 最终：可重复启动、可复现测试、完整 `IMPLEMENTATION_REPORT.md`、未通过项和风险公开。
