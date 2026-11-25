# 04｜API、数据持久化与部署

## 1. API 约定

所有 API 位于 `/api/v1`；JSON 成功响应提供 `requestId` 与 `data`，异常响应提供 `error.code`、`error.message`、可选 `error.details`。修改类操作必须携带 `baseVersion` 并进行服务器版本检查。文件下载使用 streaming，携带合理的文件名、Content-Type 和校验哈希。

| 方法 | 路径 | 目标 | 阶段 |
|---|---|---|---|
| POST | `/diagrams` | 创建图纸及初始版本 | 1 |
| GET | `/diagrams/{id}` | 获取最新图模型/版本信息 | 1 |
| POST | `/diagrams/parse` | 文本 → Graph 草稿，不写入版本 | 1 |
| POST | `/diagrams/{id}/validate` | 对最新/提交图模型做校验 | 1 |
| POST | `/diagrams/{id}/layout` | 首次布局或受控局部布局 | 1/2 |
| GET | `/diagrams/{id}/export/drawio?version=N` | 下载对应原始 `.drawio` | 1 |
| GET | `/diagrams/{id}/versions` | 图纸版本列表 | 1 |
| POST | `/diagrams/{id}/import/drawio` | 上传 Desktop 文件，返回差异预览，不提交 | 2 |
| POST | `/diagrams/{id}/import/commit` | 确认保存回导，创建新版本 | 2 |
| POST | `/diagrams/{id}/patch/preview` | 指令 → Patch + 影响分析，不提交 | 2 |
| POST | `/diagrams/{id}/patch/apply` | 确认应用 Patch，创建新版本 | 2 |
| GET | `/health` | 服务存活/依赖检查 | 1 |
| GET / PATCH | `/settings/llm` | 读取与更新工作台的 LLM 配置 | V1.2 |

### LLM 配置

保持绘图 API、GraphDocument、GraphPatch 及历史图纸版本契约。新增的 LLM 设置表随服务启动创建。已有部署首次启动时导入旧的 `LLM_*` 值，之后新请求使用 SQLite 中的门户配置。

`GET /settings/llm` 返回 `version`、`enabled`、`provider`、`baseUrl`、`model`、`timeoutSeconds`、`maxRetries`、`reasoningEffort`、`privateEndpoint` 和 `apiKey`。已保存的 `apiKey` 返回固定的 `****`，空密钥返回空字符串。

`PATCH /settings/llm` 携带 `baseVersion` 和待更新字段，返回保存后的配置。省略 `apiKey`、传空字符串或 `****` 时保留当前地址的密钥，传 `null` 时清除，传新值时替换。更换服务地址时需要填写该地址的密钥才能携带鉴权。配置版本过期时返回 `409 VERSION_CONFLICT`。

文本解析和 AI 修改在请求开始时读取配置快照。保存后进入的新请求使用新快照，进行中的请求沿用创建时的设置。

## 2. 关键请求示例

文本提取：

```json
{
  "text": "一台核心交换机连接三台服务器",
  "diagramType": "network_topology"
}
```

Patch 预览：

```json
{
  "baseVersion": 2,
  "instruction": "给核心交换机再连接两台服务器，原有设备位置不变"
}
```

预览返回至少 `patch`、`impactedIds`、`requiresConfirmation`、`warnings`，可增加 `layoutPlan`。应用操作需要引用同一预览的 `confirmationToken` 和 `baseVersion`，不能接受客户端随意跳过确认。模型输出不可信，必须由后端验证。

## 3. 建议错误码

| 错误码 | 场景 |
|---|---|
| `SCHEMA_INVALID` | JSON 结构或字段不合法 |
| `GRAPH_INVALID_REFERENCE` | 引用不存在的节点或组 |
| `GRAPH_DUPLICATE_ID` | 图对象 ID 重复 |
| `GRAPH_GROUP_CYCLE` | 嵌套组引用成环 |
| `AMBIGUOUS_RELATION` | 边类型或端点不明确 |
| `DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED` | 删除、重接线等高风险行为未确认 |
| `LAYOUT_CONFLICT` | 无法在保持人工布局的前提下插入 |
| `DRAWIO_PARSE_FAILED` | XML 无法解析 |
| `DRAWIO_UNSUPPORTED_CONTENT` | 文件内容不在 V1 安全支持范围 |
| `DRAWIO_UPLOAD_TOO_LARGE` | 文件体积超限 |
| `VERSION_CONFLICT` | baseVersion 过期，HTTP 409 |
| `LLM_UNAVAILABLE` | 模型服务不可访问 |
| `LLM_INVALID_OUTPUT` | 输出反复不符合约束 |

## 4. 数据库存储

使用 SQLite 即可满足单机 MVP；未来可迁移 PostgreSQL。建议表：

```text
projects(id, name, created_at, updated_at)
diagrams(id, project_id, name, diagram_type, current_version, created_at, updated_at)
diagram_versions(
  id, diagram_id, version, parent_version, graph_path, drawio_path,
  patch_path, manifest_path, sha256, origin, created_at
)
ai_jobs(id, diagram_id, version, request_type, model, status, error_code, duration_ms, created_at)
```

每个图纸版本至少保存：

```text
storage/diagrams/<diagram-id>/
  v0001/
    graph.json         # 语义图模型
    diagram.drawio     # 完整的原始 XML，可再次下载
    manifest.json      # 版本、父版本、SHA-256、来源、告警
  v0002/
    graph.json
    diagram.drawio
    manifest.json
    patch.json         # 如果该版本由 AI Patch 产生
```

XML 与 Graph **双重存储**是必要条件：用户桌面上的样式和坐标可能无法完全表达在简化 Graph 中；不能仅存 JSON 重新生成并覆盖人工编辑。

## 5. 版本事务要求

1. 读取 current_version，核对 `baseVersion`，不一致则 HTTP 409。
2. 计算新 Graph / XML 到内存或临时路径，完成语义校验、XML 校验和差异审查。
3. 写入新版本临时目录，计算 SHA-256，确认完整性。
4. 原子 rename 到版本路径，数据库事务推进 current_version；任何失败不得修改已有版本。对数据库/文件系统提交间隙的异常做恢复处理。
5. 永不直接覆盖 `v0001`；回滚通过创建指向目标内容的新版本实现。

## 6. 安全边界

- 服务器只接收用户上传的 `.drawio`，限制文件大小、页数、解压后体积和复杂度，防止解压炸弹。
- 禁用外部实体和外部资源访问；客户端传来的 XML/HTML 不在服务端执行。
- Renderer 调用使用参数数组 + `shell=False` + timeout + 最大输出；不能拼接用户命令。
- LLM 接口地址、key 不写入 Git；日志默认不保留原始网络拓扑或 IP 清单。
- 未来正式部署需增加身份鉴权和项目级权限控制；首版仅适用于受控内网环境，不应直接暴露公网且无鉴权。

## 7. 建议新仓库目录（由 Codex 实现）

```text
ai-diagram-studio/
  AGENTS.md
  README.md
  docs/
  contracts/
  fixtures/
  backend/
    app/
      main.py
      api/
      schemas/
      graph/{validate.py,patch.py,diff.py}
      llm/{adapter.py,prompts.py}
      importer/
      storage/
      services/
    tests/
    pyproject.toml
  renderer/
    src/{layout/,drawio/,shapes/,cli.ts}
    tests/
    package.json
    package-lock.json
  frontend/
    src/{pages/,components/,api/}
    package.json
  deploy/{compose.yaml,env.example}
  scripts/
  IMPLEMENTATION_REPORT.md
```

注意：当前交付包**尚不包含**上述应用实现目录，Codex 负责创建。不要把它误称为一键部署的成品。
