# deploy/

容器制作与部署的完整方案见 [../docs/09_DEPLOYMENT.md](../docs/09_DEPLOYMENT.md)。
本目录只放部署物料：`Dockerfile`、`compose.yaml`、`env.example`。

快速启动（2026-11-23 实机两连修：.dockerignore 按目录名排除在旧版 Docker 不可靠，已改为仅安全形态并有守卫测试；**重跑前务必 `docker builder prune -f` 清缓存**）：

```bash
cp env.example .env          # 新部署的运行限额，模型配置在门户填写
docker compose up --build    # 端口 8000；数据持久化于命名卷 studio-data
curl http://127.0.0.1:8000/health
```

要点：

- 镜像单容器封装 backend（uvicorn）+ renderer（Node 子进程）+ frontend 静态产物；镜像内已执行 `npm ci`（锁定 package-lock.json）并预构建 renderer/frontend
- `.dockerignore`（仓库根）排除 `.git`、`node_modules`、`dist`、`storage`、`out`、`.env` 等
- `HEALTHCHECK` 与 compose `healthcheck` 都打 `/health`，`rendererAvailable` 由后端探测渲染器 CLI 是否存在
- 版本数据（SQLite + 逐版本快照）全部在 `/data/storage`，升级镜像不丢数据；备份 = 备份该卷
- 启动后在「LLM 配置」保存模型参数。已有部署首次升级会导入旧环境配置，密钥加密文件也保存在数据卷中。
