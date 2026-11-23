# 11｜遗留问题与待办清单

> 2026-11-22 全量评审后建立；已完成项移入 [IMPLEMENTATION_REPORT.md](../IMPLEMENTATION_REPORT.md) §11（P0 三项）。
> 状态：OPEN / BLOCKED / WONTFIX（本轮）。

## 阻塞级

| ID | 问题 | 影响 | 状态 |
|---|---|---|---|
| B-1 | **Windows draw.io Desktop 人工验收未执行**（Phase 0 起继承的闸门） | 全部"可编辑性"结论仍属结构推断；真实 Desktop 保存格式/行为未实测 | BLOCKED——按 docs/10 §2 清单执行 |
| B-2 | Docker/compose 路径实机验证 | 首次实机（2026-11-23）连环诊断，**最终根因是 `.gitignore` 裸名 `storage/` 把 `backend/app/storage/` 代码包排除在 Git 之外**——服务器克隆的仓库里根本没有该目录（dockerignore 两轮修复均是对着幻影打拳，但顺带把容器构建正确性也加固了）。已修复：gitignore 锚定为 `/storage/`、`/data/`，缺失文件补交，四个缺失的 `__init__.py` 补齐，守卫测试 `test_git_tracks_all_runtime_packages` 防回归 | 待服务器 `git pull` 后重建确认运行时 |

## 安全与规约（评审 P1 剩余）

| ID | 问题 | 说明 | 状态 |
|---|---|---|---|
| S-1 | LLM 提示词未脱敏：propose_patch 将完整 Graph（含 properties 中的 IP）发送至 OpenAI-compatible 端点 | docs/07 P1 风险"外部 LLM 处理内部拓扑"；建议发送前剥离/占位化 properties，或强制私有模型 | OPEN |
| S-2 | 无身份鉴权 | docs/04 §6 声明限受控内网；公网部署前必须补 | OPEN（声明性） |
| S-3 | 边类型箭头启发式回退仍可能误判 Desktop 手绘边的 logical/control/dependency | 有 `aiKind` 标记后仅影响手绘边；diff 已显式上报 | OPEN（低危，已缓解） |

## 功能缺口（V1 边缘 / V2 候选）

| ID | 问题 | 说明 | 状态 |
|---|---|---|---|
| F-1 | Edge label 重叠与密集拓扑线路交叉 | ELK 不保证无交叉；人工精修属预期工作流 | WONTFIX（按设计） |
| F-2 | 超长组标题可能溢出 swimlane 标题栏 | 未做标题宽度补偿 | OPEN（低优先） |
| F-3 | Excel/CSV 批量导入、多模态还原；~~图标库扩展~~（2026-11-23 已部分交付：SVG 素材通道+默认素材、8 个设备别名、组网图模板，见报告 §13） | 剩余：更多图标/模板、流程图与组织结构图类型 | OPEN（Phase 3） |
| F-4 | AI 语义质量评估（docs/06 §5：20 结构化样例 + 30–80 自然语言变体的 precision/recall） | 当前仅 12 个 mock 用例，真实模型基线未建 | OPEN——接入真实 LLM 后执行 |

## 工程质量

| ID | 问题 | 说明 | 状态 |
|---|---|---|---|
| Q-1 | 双份/三份实现需人工同步（校验 TS↔Python、样式模板、默认尺寸） | 已有静态+行为同步测试兜底（tests/test_phase_p1.py），仍建议长期收敛为单一来源 | OPEN（低优先） |
| Q-2 | 前端零自动化测试 | 依赖人工 + 后端集成测试 | OPEN |
| Q-3 | 预览令牌存进程内存：重启失效、多 worker/多实例不可用 | 单 worker 部署最稳；多实例需外置存储 | OPEN |
| Q-4 | 锚点插入 O(n²)（大图 patch 变慢） | 5000 cell 上限内可接受 | OPEN（低优先） |
| Q-5 | `ai_jobs` 只增不清；无查询端点 | 长期膨胀 | OPEN |
| Q-6 | mock `parse_graph` 生成的节点 id 可读性差（item/item_2；patch 侧已改用英文 kind） | 不影响正确性 | OPEN |
| Q-7 | `/validate` 用 diagram id `"-"` 占位、`projects` 表无 CRUD | 接口语义洁癖项 | OPEN |
| Q-8 | Docker/compose 未实测（同 B-2） | — | 同 B-2 |

## 已明确不做（WONTFIX，含理由）

| ID | 项 | 理由 |
|---|---|---|
| W-1 | 服务端部署 draw.io / Web 画布编辑器 / Windows 自动同步 | AGENTS.md 硬性边界 D-01/D-02 |
| PPTX/VSDX/EDDX 输出 | docs/00 §5 明确排除 |
| 任意第三方 .drawio 完整无损回读 | docs/07 §2 明确"确认之前不得声称支持"；V1 只保证本系统生成文件及其 Desktop 回存版本 |
