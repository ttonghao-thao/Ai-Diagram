# frontend/

Phase 1 最小 React + TypeScript 管理台（docs/01 section 6），**不含图形画布**：
图形精修在 Windows draw.io Desktop 中完成。

- 生成图纸：粘贴/加载 Graph JSON 示例 → 创建图纸 + v1 → 下载 `.drawio`
- 文本解析：自然语言 → Graph 草稿（需 LLM_ENABLED=true；mock 或 OpenAI-compatible）
- 校验 Graph：结构 + 语义校验，返回错误码与警告
- 图纸与版本：列表、版本历史、SHA-256、逐版本下载、基于当前版本的 ELK 重排

```bash
npm install
npm run dev        # 开发模式（代理 /api 到 127.0.0.1:8000）
npm run build      # 产物输出 dist/，由 FastAPI 静态挂载
```
