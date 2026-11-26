# deploy/

容器制作与部署的完整方案见 [../docs/09_DEPLOYMENT.md](../docs/09_DEPLOYMENT.md)。

已有 `studio-data` 命名卷的部署请先按部署文档迁移数据。新部署可以在本目录用下面的命令启动。

```bash
cp env.example .env
docker compose up -d --build
docker compose ps
```

服务监听 `8000` 端口，`/health` 返回渲染器的可用状态。数据写到宿主机 `/mnt/ai-diagram/data`，日志写到 `/mnt/ai-diagram/logs`。可在 `.env` 中通过 `STUDIO_DATA_DIR` 和 `STUDIO_LOG_DIR` 自定义路径。
