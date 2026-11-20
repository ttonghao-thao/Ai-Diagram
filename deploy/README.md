# deploy/

Phase 0 只包含 `env.example`（Phase 1 LLM/存储配置预留，当前无需填写）。

`compose.yaml` 将随 Phase 1（FastAPI + renderer + 静态前端）一起交付；
服务端不部署 draw.io，Windows draw.io Desktop 始终是用户本地编辑器。
