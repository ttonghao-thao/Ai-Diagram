# 11｜遗留问题与待办清单

## V1.2 验收与待跟踪事项

| 项目 | 当前结论 | 跟踪 |
|---|---|---|
| 真实模型质量 | 本机 Ollama `qwen3.5:2b` 生成 24/30 可渲染，节点精确率 80.9%，连线 F1 61.9%，Patch 1/3。建议门槛未达到 | 保留固定样本和逐项结果。用目标部署模型复跑，并评估低置信关系复核效果。见 [模型证据](evidence/v1_2_local_qwen_2b.json) |
| Windows draw.io Desktop | 未验证。已执行原生 XML、程序回存和官方 Chrome Viewer 检查 | B-1，按本地 Windows 验收手册执行 |
| Docker Compose 与目标服务器 | 未验证。本机未装 Docker，已验证 FastAPI 与静态工作台启动 | B-2，通过目标服务器部署完成实机闭环 |
| 自动避障 | 使用有限候选路径，密集拓扑仍可能出现碰撞 | 质量报告保留碰撞对象，外观可继续在 Desktop 精修 |
| 组合图形 | 可安全导入并完整导出原生子节点与内部连线 | 整组作为单个 GraphDocument 节点的插入和编辑需要单独往返验收 |
| 素材预览 | 已提供 Cisco Classic 缩略图和 SVG 实时预览。其他原生素材提供可下载的 `.drawio` 预览 | 扩大缩略图覆盖时核对上游及厂商素材许可 |
| 个人素材隔离 | 工作台级 SQLite 持久化，偏好由该实例共享 | 多用户隔离依赖后续身份层 |
| 外部模型数据 | 过滤视觉字段和非必要资产属性，提示词中的显式 IP 会脱敏。仍会提交完成语义解析所需的名称及关系 | 含敏感拓扑的部署使用可信私有模型。S-1 跟踪剩余边界 |
| 版本文件恢复 | 同一请求的写入失败回收暂存目录，SQLite 同事务推进版本 | OS 在目录发布与数据库提交之间中断的孤儿目录需要运维核对 |

下文保留 V1.1 历史台账。


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
| Q-9 | 网络层级定向按**设备类型**排层 | 两台防火墙（如服务器区防火墙）会被排到同一层；核心/接入交换机同为 switch，靠语句顺序区分 | OPEN（低优先；可扩展为 properties.tier 显式层级） |
| Q-10 | 网络拓扑图强制同层按输入顺序（`forceNodeModelOrder`） | 牺牲部分交叉最小化，密集图连线交叉可能略多 | OPEN（取舍记录于报告 §16） |
| Q-11 | Cisco 主题外观细节 | 连线为直线、标签在中点（已加白底保证可读）；组容器仍是实底 swimlane，非参考图的虚线框 | OPEN（外观项） |
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
