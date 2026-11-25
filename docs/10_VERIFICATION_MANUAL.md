# 10｜验证手册

## V1.2 验证命令

在仓库根目录运行。

```bash
npm --prefix renderer test
.venv/bin/python -m pytest backend/tests
npm --prefix frontend run build
.venv/bin/python scripts/validate_fixtures.py
.venv/bin/python scripts/benchmark_v1_2.py
```

使用配置好的 OpenAI-compatible 服务运行固定的 30 条生成和 3 条 Patch 样本。独立评估脚本通过 `LLM_*` 获取本次测试配置，门户服务使用 SQLite 中保存的配置。模型评估独立记录 Schema 合法率、节点和连线的精确率与召回率、素材匹配和运行耗时。

```bash
.venv/bin/python scripts/verify_v1_2_model.py --output /tmp/v1_2_model_report.json
```

- 确定性验收覆盖 V1.2 的 T01–T20，其中 Desktop 编辑通过程序构造的回存文件测试。原生 Cisco 图形另在 Chrome 中使用官方只读 Viewer 及固定版本 stencil 测试渲染。
- 在真实 Windows Desktop 打开 [V1.2 网络样例](../out/v1_2_network.drawio)，继续执行本手册的打开、拖动、改样式、改折点、保存、回导和再次打开流程。记录 Desktop 版本、SHA-256 与截图。
- 使用 React 工作台验证文本草稿、下载、主题、素材检索、收藏、默认映射、SVG 预览与素材库导出。部署实机验收仍按 [部署文档](09_DEPLOYMENT.md)执行。


分两部分：**自动化验证**（可在任何开发机重复）与 **Windows Desktop 人工验收**（必须在真实 Windows 环境，当前 BLOCKED）。

## 1. 自动化验证

前置：Node ≥ 20、Python ≥ 3.9；首次需 `cd renderer && npm install`、`cd frontend && npm install`、`pip install -r backend/requirements.txt`。

```bash
# ① 素材契约自检（输入 fixtures + 预制 XML）
python3 scripts/validate_fixtures.py
# 预期：3 行 PASS + "NOTE: Windows draw.io Desktop ... still required"

# ② 渲染器套件（构建 + 64 个测试，并产出 out/*.drawio 交付物）
cd renderer && npm test
# 预期：# tests 64 / # pass 64 / # fail 0

# ③ 后端套件（108 个测试：校验 + API + 回导/Patch + 加固 + 主题同步）
cd ../backend && python3 -m pytest
# 预期：108 passed

# ④ 交付物复验（标准 XML 解析器）
python3 -m pytest tests/test_render_output.py
# 预期：全部 passed（要求 ② 已执行，out/ 存在）
```

测试与文档需求的对应：G-01~G-05（语义校验）、X-01~X-05（XML/转义/往返/性能）、A-01~A-03（生成路径）、V-01~V-03（版本事务）、I-01~I-05（回导与安全）、P-01~P-05（Patch）；另有 12 个文本用例与 P1 加固/同步测试。

### API 级全链路脚本（可选，验证 v1→v2→v3）

```bash
# 服务启动后，在门户「LLM 配置」启用 Mock 并保存：
# 1. POST /api/v1/diagrams 提交 fixtures/network.graph.json        → v1 initial
# 2. POST /api/v1/diagrams/{id}/patch/preview {"instruction":"新增两台服务器并连接核心交换机"}
# 3. POST /api/v1/diagrams/{id}/patch/apply {confirmationToken, baseVersion} → v2 ai_patch
# 4. 下载 v2，在 XML 上手工改名/移动（模拟 Desktop）再走 import preview→commit → v3 desktop_import
# 5. GET /api/v1/diagrams/{id}/versions 断言 [(1,initial),(2,ai_patch),(3,desktop_import)]
```

## 2. Windows Desktop 人工验收（BLOCKED——必须真实执行）

环境要求：真实 Windows + 已安装 draw.io Desktop（记录版本号）。

### 2.1 首次生成验收（Phase 0 闸门）

1. 从工作台（或 `out/` 目录）取得 `network.drawio`、`business.drawio`，核对 SHA-256 与报告 §11.4 一致
2. 打开后逐项确认：
   - [ ] 所有节点/分组/连线可**单独选中、拖动、缩放**；无对象合并为图片
   - [ ] 图标：网络拓扑图为 draw.io 内置 Cisco 风格（实心蓝：交换机=Route Switch Processor、防火墙=砖墙+箭头、服务器=塔式、云=白底描边）；业务架构图为线稿风格
   - [ ] 网络图连线为细黑直线、无箭头无标签；层级自上而下为 公网→防火墙→核心交换机→服务器；业务图逻辑线虚线带箭头、数据流双向
   - [ ] 中文标签完整显示于图标下方，无截断乱码
3. 编辑并保存：改一个节点名 → 拖动位置 → 改一条连线端点 → 保存 → 重新打开无丢失

### 2.2 回导闭环验收（Phase 2 闸门）

1. 工作台“导入回导”页上传刚保存的文件 → 检查差异表包含改名/移动/重接项
2. 确认提交 → “图纸与版本”页确认新版本 origin=desktop_import
3. “AI 修改”页输入 `新增两台服务器并连接核心交换机` → 预览（受影响对象/差异）→ 确认应用 → 下载新版本
4. 重新在 Desktop 打开新版本：[ ] 仅新增了目标对象，旧对象位置未变；[ ] 新服务器图标正确且可编辑
5. 压缩页专项：在 Desktop 用“另存为”或让 Desktop 产生压缩保存 → 回导 → 确认提示“规范化” → 再执行一次 AI 修改应成功（不得被拒绝）

### 2.3 回滚验收

- [ ] “图纸与版本”页对历史版本点“回滚到此版本” → 生成 origin=rollback 的新版本 → 下载内容与目标版本一致 → 历史版本仍全部可下载

### 2.4 记录模板（回填到 IMPLEMENTATION_REPORT.md §6）

```text
验收时间 / Windows 版本 / draw.io Desktop 版本 / 文件 SHA-256
测试项：打开 / 拖动 / 缩放 / 重命名 / 改线 / 保存 / 回导 / AI 修改 / 回滚 / 压缩页专项
结果：PASS / FAIL / BLOCKED
观察与错误、是否丢失节点样式连接、验收人
```

**规则**：任何一项未真实执行，总闸门保持 BLOCKED，不得写 PASS。
