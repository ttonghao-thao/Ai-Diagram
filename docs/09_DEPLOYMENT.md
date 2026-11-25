# 09｜部署方案

服务端面向 **Linux（推荐）/ macOS**；Windows 仅承担 draw.io Desktop 人工编辑，不属于部署范围。

## 1. 方式 A：Docker Compose

```bash
git clone https://github.com/ttonghao-thao/Ai-Diagram.git && cd Ai-Diagram/deploy
cp env.example .env          # 按需填写；默认 LLM_ENABLED=false 即可完整使用 JSON 生成
docker compose up --build
curl http://127.0.0.1:8000/health   # {"status":"ok","rendererAvailable":true}
```

- 单容器封装 backend + renderer + frontend 静态产物；镜像内 `npm ci` 锁定依赖并预构建
- 数据持久化：命名卷 `studio-data` → 容器内 `/data/storage`（SQLite + 逐版本快照）
- 健康检查：镜像 `HEALTHCHECK` 与 compose `healthcheck` 均探测 `/health`
- **实机验证状态（2026-11-23 第二次更新）**：compose 首次实机构建成功后，运行时暴露 `.dockerignore` 缺陷——先发现裸名 `storage` 误排除 `backend/app/storage/`（已修），用户 `--no-cache` 重跑后又证明**前导 `/` 锚定在旧版 Docker 同样失效（匹配前剥掉斜杠）**。最终方案：`.dockerignore` 彻底不按目录名排除（只允许 `**/<工具目录>` 与 `*.后缀` 形态，并有守卫测试禁止回归），运行时目录改由容器内 `STORAGE_ROOT=/data/storage` 卷承载、不入镜像。**请再次重跑**：`docker compose down && docker compose build --no-cache && docker compose run --rm --no-deps studio ls /studio/backend/app/storage && docker compose up -d`，然后 `curl /health` 确认

## 2. 方式 B：裸机部署（已在开发机验证的路径）

前置：Node ≥ 20、Python ≥ 3.9。

```bash
git clone https://github.com/ttonghao-thao/Ai-Diagram.git && cd Ai-Diagram
(cd renderer && npm install && npm run build)     # 必须先构建
(cd frontend && npm install && npm run build)     # 可选，不构建则仅 API
(cd backend && pip install -r requirements.txt)
LLM_ENABLED=false python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend
```

生产建议：`nohup`/systemd 托管 uvicorn；如需多 worker，注意预览令牌存于进程内存（见 docs/11），单 worker 最稳。

## 3. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_ENABLED` / `LLM_PROVIDER` | false / mock | provider = mock 或 openai；关闭时 JSON 生成完整可用 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 空 | OpenAI-compatible；key 只走环境变量 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | 60 / 2 | 模型调用超时与修复轮数 |
| `RENDERER_CLI` | `renderer/dist/src/cli.js` | 渲染器 CLI 位置 |
| `RENDERER_TIMEOUT_SECONDS` / `RENDERER_OUTPUT_LIMIT_BYTES` | 60 / 8MB | 子进程超时与输出上限 |
| `ICONS_DIR` | `renderer/assets/icons` | 自定义 SVG 图标目录 |
| `STORAGE_ROOT` / `DATABASE_PATH` | `./storage` | 版本快照根 / SQLite 路径 |
| `MAX_DRAWIO_UPLOAD_BYTES` / `MAX_XML_CELLS` | 10MB / 5000 | 上传安全上限 |
| `FRONTEND_DIST` | `frontend/dist` | 静态工作台目录 |

> ⚠️ **路径类变量（RENDERER_CLI / STORAGE_ROOT / DATABASE_PATH / FRONTEND_DIST / ICONS_DIR）覆盖时必须使用绝对路径，且容器部署建议保持注释**：compose 的 env_file 会覆盖镜像内置的正确绝对路径，相对路径（如 `./renderer/...`）在容器内不存在——这是首次容器部署失败的根因之一（见 docs/11 B-2 与报告 §12.5）。
| `FRONTEND_DIST` | `frontend/dist` | 静态工作台目录 |

## 4. 数据、备份与升级

- 备份 = 备份 `STORAGE_ROOT` 整个目录（含 `studio.db` 与 `diagrams/<id>/vNNNN/` 快照）；版本文件只增不改，增量备份即可
- 升级代码：停服 → 替换代码 → 重建 renderer/frontend → 启动；历史版本不受影响
- 回滚部署 = 回滚代码 + 恢复 `STORAGE_ROOT` 备份

## 5. 部署后验证

1. `curl /health` → `rendererAvailable:true`
2. 工作台“生成图纸”加载示例 → 创建 → 下载 `.drawio`
3. （Windows）draw.io Desktop 打开下载文件，编辑保存后走“导入回导”页
4. 完整验收步骤见 [docs/10_VERIFICATION_MANUAL.md](10_VERIFICATION_MANUAL.md)

## 6. 已知部署限制

- compose 路径：构建已实机通过；运行时待重跑确认（首跑缺陷已修，见 §1 声明）；裸机路径已验证
- 预览令牌存进程内存：多 worker / 多实例部署会令预览-应用跨进程失败（docs/11 O-3），单 worker 部署最稳
- 无身份鉴权：仅限受控内网，勿直接暴露公网（docs/04 §6）
