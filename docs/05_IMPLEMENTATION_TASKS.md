# 05｜Codex 分阶段任务（唯一任务清单）

> 按 Phase 0 → 1 → 2 执行。每阶段先实现最小功能，执行测试、保存报告；阶段闸门不通过时不得继续堆叠功能。每阶段至少一个可独立检查的提交。

## Phase 0｜先完成确定性可编辑绘图（无 LLM / 无 Web）

### 0.1 初始化与依赖

- [ ] 建立 `backend/`、`renderer/`、`frontend/`、`deploy/`、`scripts/`，可在本阶段只实际开发 `renderer/` 和图模型校验部分。
- [ ] 明确 Node/Python 运行版本、锁定依赖及格式化、类型检查、测试命令。
- [ ] 增加 `.env.example` 和 mock 配置；完全离线的 Graph→XML 路径可运行。
- [ ] 运行 `python scripts/validate_fixtures.py`，保留执行记录。

### 0.2 统一图模型与关系校验

- [ ] 实现与 `contracts/graph.schema.json` 对应的 Pydantic 类型。
- [ ] 实现全局 ID 唯一、边端点存在、group 有效/无环、物理线不含默认方向等约束。
- [ ] 非法 Graph 应提供明确错误码，不生成错误图纸。

### 0.3 ELK Renderer 与 XML 输出

- [ ] Renderer CLI 对任意合法 Graph JSON 工作，不硬编码 fixture ID、名称、坐标。
- [ ] 网络拓扑自动布局：层级 + 正交连接 + 设备标签空间。
- [ ] 业务架构自动布局：容器分组、子模块位置和跨组连线。
- [ ] 正确实现嵌套组绝对/相对坐标转换。
- [ ] 生成的 `.drawio` 拥有稳定 ID、真实顶点/边/组、正确父子和 source/target 引用。
- [ ] XML escaping、中文、样式、端点与父组的回归测试。

### Phase 0 闸门

- [ ] `network.graph.json` → `out/network.drawio`；`business.graph.json` → `out/business.drawio`，都来自 **Codex 自行实现的 renderer**。
- [ ] 自动化 XML、Graph 引用、嵌套组测试通过。
- [ ] **Windows draw.io Desktop 手工实测**：打开两份新文件、移动节点、改文字、改线、保存；记录版本与观察结果。
- [ ] `IMPLEMENTATION_REPORT.md` 写清已完成/未完成、测试命令、失败风险、截图或手工报告。

> 如果当前环境不能打开 Windows draw.io Desktop，必须明确将人工闸门标记为“等待用户测试”，不得声称已通过。正式进入 Phase 1 前需获取该项反馈。

## Phase 1｜完整首次生成工作流

- [ ] 开发 FastAPI：创建图纸、查询、验证、首次布局、导出文件和版本列表。
- [ ] SQLite + 文件版本快照（Graph + XML + manifest + SHA-256）；原子保存，不覆盖历史版本。
- [ ] 最小 React 管理台：文本/JSON 输入、图类型选择、警告显示、下载、版本查询。
- [ ] LLM adapter：mock + OpenAI-compatible 可配置接口；JSON Schema 约束 + 后端校验 + 有限次修复。
- [ ] 文字生成应返回完整合法 Graph 草稿、warnings/clarifications；不制造不存在的物理连接/IP。
- [ ] LLM 关闭时 JSON 生成路径依然完整运行。

### Phase 1 闸门

- [ ] 至少 10 个文本用例可生成合法 Graph，真实错误案例归档。
- [ ] Browser → API → Graph → ELK → `.drawio` → Windows Desktop 的首次生成链路成功。
- [ ] API/存储自动化测试与启动命令可复现。

## Phase 2｜Desktop 回导与 AI 增量修改（V1 必做）

### 2.1 文件回读与差异

- [ ] 安全解析未压缩与压缩 `diagram` 页。
- [ ] 识别普通 `mxCell`、`UserObject`/`object`、Group/Node/Edge、geometry、labels、style、waypoints。
- [ ] 未知自定义 cell 保留原始 XML 或中止不安全修改。
- [ ] 对 Desktop 手工移动/重命名/改线/新增/删除对象生成差异预览。
- [ ] 导入前检查 `baseVersion`，先 preview 后 commit。

### 2.2 GraphPatch 与布局保护

- [ ] Patch 9 种操作：节点/边/组 add/update/remove；schema + 语义校验、原子应用。
- [ ] 删除关联节点、删除组、重接边等破坏性操作经确认。
- [ ] 局部新增用锚点插入 + 碰撞检测，不隐式移动 `manualLocked` 原节点。
- [ ] 在当前原始 XML AST 上定向修改，保留未受影响和未知 cell。
- [ ] `VERSION_CONFLICT`、`LAYOUT_CONFLICT` 和解析错误返回明确错误码。

### Phase 2 闸门

- [ ] Windows 下载图纸→人工移动、改名、改线→上传→预览并提交回导→AI 增加服务器→下载再次打开，全流程跑通。
- [ ] 已锁定/无关对象未被擅自移动；连接与用户样式保留。
- [ ] 压缩 XML、多页拒绝保护、恶意上传、失效版本与未知对象测试通过。

## 最终交付

- [ ] `docker compose up --build` 或等价简化启动流程，含 `.env.example`、mock 演示。
- [ ] API 文档、数据契约、Renderer CLI 帮助与真实示例。
- [ ] 自动化测试命令、Windows Desktop 手工记录、失败用例清单。
- [ ] `IMPLEMENTATION_REPORT.md`：实现范围、实际测试、限制、后续建议。

## Phase 3｜以后再做（不阻塞 V1）

Excel/CSV 导入、更多拓扑图标、复杂局部路由、PPTX/VSDX/EDDX 研究、多模态图片还原、Windows 自动同步助手、多人协作。
