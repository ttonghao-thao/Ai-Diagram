# 09｜部署方案

服务端面向 **Linux（推荐）/ macOS**；Windows 仅承担 draw.io Desktop 人工编辑，不属于部署范围。

## 1. 方式 A：Docker Compose

```bash
git clone https://github.com/ttonghao-thao/Ai-Diagram.git && cd Ai-Diagram/deploy
cp env.example .env          # 按需填写；默认 LLM_ENABLED=false 即可完整使用 JSON 生成
docker compose up -d --build
```

单容器封装 backend、renderer 和 frontend 静态产物。镜像内通过 `npm ci` 安装锁定的依赖并预构建。`docker compose ps` 显示 `healthy` 后，访问 `http://127.0.0.1:8000/health`，预期返回 `{"status":"ok","rendererAvailable":true}`。

| 用途 | 默认宿主机目录 | 容器目录 |
|---|---|---|
| SQLite 和图纸版本快照 | `/mnt/ai-diagram/data` | `/data/storage` |
| 服务日志 `studio.log`、访问日志 `access.log` | `/mnt/ai-diagram/logs` | `/data/logs` |

Compose 会创建缺失的宿主机目录。在 `deploy/.env` 中可用 `STUDIO_DATA_DIR` 和 `STUDIO_LOG_DIR` 覆盖路径，填写 Docker 可写的绝对路径。从仓库根目录执行时，在 `docker compose` 的子命令前加 `--env-file deploy/.env -f deploy/compose.yaml`。日志仍可通过 `docker compose logs studio` 查看。每个日志文件达到 10 MiB 时轮转，保留 3 个轮转文件。访问日志仅记录时间、日志级别和 HTTP 状态。

### 从 `studio-data` 命名卷升级

如果已有部署使用命名卷，从更新后的 `deploy/` 执行以下命令，再启动新版。已有数据需要停服后复制到新 Compose 配置指向的空目录，SQLite 和版本文件一并迁移。

```bash
container_id="$(docker compose ps -aq studio)"
old_volume="$(docker inspect --format '{{range .Mounts}}{{if and (eq .Type "volume") (eq .Destination "/data/storage")}}{{.Name}}{{end}}{{end}}' "$container_id")"
test -n "$old_volume" && docker volume inspect "$old_volume" >/dev/null &&
  docker compose stop studio &&
  docker compose run --rm --no-deps -v "$old_volume:/from:ro" --entrypoint sh studio -ec '
    existing="$(ls -A /data/storage)"
    if [ -n "$existing" ]; then
      echo "目标数据目录已有内容，已停止复制" >&2
      exit 1
    fi
    cp -a /from/. /data/storage/
  '
```

如果旧容器已移除，使用 `docker volume ls --filter label=com.docker.compose.volume=studio-data` 找到属于该部署的卷，将卷名称赋给 `old_volume` 后从 `test -n` 行继续。

复制成功后执行 `docker compose up -d --build`。核对既有图纸及版本能读取和下载，保留旧卷作为回滚备份。复制失败时先核对源卷和目标目录，重试时使用空目标目录。

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
| `STUDIO_DATA_DIR` | `/mnt/ai-diagram/data` | Compose 数据绑定挂载源路径 |
| `STUDIO_LOG_DIR` | `/mnt/ai-diagram/logs` | Compose 日志绑定挂载源路径 |
| `MAX_DRAWIO_UPLOAD_BYTES` / `MAX_XML_CELLS` | 10MB / 5000 | 上传安全上限 |
| `FRONTEND_DIST` | `frontend/dist` | 静态工作台目录 |

> ⚠️ **路径类变量（RENDERER_CLI / STORAGE_ROOT / DATABASE_PATH / FRONTEND_DIST / ICONS_DIR）覆盖时必须使用绝对路径，且容器部署建议保持注释**：compose 的 env_file 会覆盖镜像内置的正确绝对路径，相对路径（如 `./renderer/...`）在容器内不存在——这是首次容器部署失败的根因之一（见 docs/11 B-2 与报告 §12.5）。

## 4. 数据、备份与升级

- 停服后备份整个数据目录。Compose 使用宿主机 `STUDIO_DATA_DIR`，裸机使用 `STORAGE_ROOT`。备份包含 `studio.db` 和 `diagrams/<id>/vNNNN/` 图纸快照。
- 升级代码：停服 → 替换代码 → 重建 renderer/frontend → 启动；历史版本不受影响
- 回滚部署时恢复对应代码和数据目录备份。

## 5. 部署后验证

1. `curl /health` → `rendererAvailable:true`
2. 工作台“生成图纸”加载示例 → 创建 → 下载 `.drawio`
3. 在宿主机数据目录检查 `studio.db` 和 `diagrams/` 版本快照，在日志目录检查 `studio.log` 和 `access.log`。
4. （Windows）draw.io Desktop 打开下载文件，编辑保存后走“导入回导”页
5. 完整验收步骤见 [docs/10_VERIFICATION_MANUAL.md](10_VERIFICATION_MANUAL.md)

## 6. 已知部署限制

- Compose 的构建、启动、宿主机挂载和旧卷迁移已在隔离的 Linux arm64 Docker 环境验证。目标服务器未验证。
- 预览令牌存进程内存：多 worker / 多实例部署会令预览-应用跨进程失败（docs/11 O-3），单 worker 部署最稳
- 无身份鉴权：仅限受控内网，勿直接暴露公网（docs/04 §6）
