# 自定义 SVG 图标目录（Phase 0.5 Icon Registry）

把本设备类型专属的 SVG 图标放在本目录，命名为 `<设备类型>.svg`（小写），
renderer 生成时自动读取并**内嵌**为 style 中的 data URI——运行时零在线加载。

## 命名与匹配

- `switch.svg` → 覆盖 `kind: "switch"` 的图标
- `printer.svg` → 供 `kind: "generic"` 且 `properties.deviceType: "printer"` 的节点使用
  （即"设备别名"：JSON Schema 中未识别的设备类型一律记为 generic，原始类型放 deviceType）

优先级：`node.style.icon`（单节点内嵌 data URI）> 本目录按 kind > 本目录按 deviceType >
Icon Registry 内置 stencil（mxgraph.networks 等）> generic 兜底。

## SVG 要求（违反将拒绝生成）

- 单文件 ≤ 64 KB；必须是 `<svg>` 文档
- 不得包含 `<script>`、`javascript:` 等可执行内容
- 建议自带 `viewBox` 与合适的宽高比；渲染时缩放到节点几何尺寸

## 技术说明（重要）

嵌入形式为**百分号编码** data URI：`image=data:image/svg+xml,%3Csvg...`。
不要使用 base64 形式（`...;base64,xxx`）：draw.io 的 style 解析按 `;` 切分，
base64 头部中的分号会截断样式值导致图标空白（该根因已通过渲染复现与修复，
详见 IMPLEMENTATION_REPORT.md Phase 0.5）。
