# 自定义 SVG 图标目录（生成阶段素材通道）

把 SVG 图标放在本目录，**生成 `.drawio` 时即内嵌为 data URI**——运行时零在线加载、不依赖 Desktop。
当前默认素材为**项目自绘原创**（蓝色渐变风格，可自由修改/替换，无第三方许可问题）：
`access_point.svg`（无线AP）、`vpn_gateway.svg`（VPN 网关）、`ids_ips.svg`（入侵检测）。

## 快速上手（三步）

1. 准备一个 SVG 文件（≤64KB、含 `<svg>`、无 `<script>`/`javascript:`）
2. 按用途命名后放入本目录：
   - `<设备别名>.svg` —— 供 `properties.deviceType` 为该别名的节点使用（推荐，不改变类型默认外观）
   - `<kind>.svg`（如 `switch.svg`）—— 会**覆盖该类型所有节点**的默认 stencil（慎用）
3. 重新生成图纸即可，例如：

```json
{"id": "ap1", "label": "无线 AP", "kind": "generic",
 "properties": {"deviceType": "access_point"}}
```

CLI 也可显式指定目录：`node dist/src/cli.js generate --input x.json --output y.drawio --icons-dir <目录>`

## 图标解析优先级（从高到低）

1. `node.style.icon`（单节点内嵌 data URI）
2. 本目录按 `kind` 匹配的 SVG
3. 本目录按 `deviceType` 别名匹配的 SVG
4. **扩展别名表**（`ALIAS_REGISTRY`，draw.io 内置 stencil）：
   `access_point`→wireless_hub、`load_balancer`、`modem`、`proxy`→proxy_server、
   `vpn_gateway`→secured、`hub`、`mainframe`、`rack`
5. 按 `deviceType` 命中十种基础类型（如 deviceType="firewall" → 防火墙 stencil）
6. 按 `kind` 的默认 stencil → `generic` 兜底

## 使用第三方素材（如网上的图库包）

任何 SVG 都能直接丢进来（按上述命名规则）。注意核对素材许可：
例如 CSDN 流传的 `draw_io-master.zip` 图库标注"仅限个人学习"；Flaticon 等需署名；
商用请选用 CC0/MIT/Apache 许可的图标集，或自行导出 SVG。本目录内置素材为项目原创，无此顾虑。

## 技术约束（重要）

- 嵌入形式为**百分号编码** data URI：`image=data:image/svg+xml,%3Csvg...`
  不要改回 base64——drawio 的 style 解析按 `;` 切分，base64 头部的分号会把样式截断成空白图标
  （该根因已实测复现并修复，见 IMPLEMENTATION_REPORT.md §8.3）
- 建议 SVG 自带 `viewBox`；渲染时缩放到节点几何尺寸
- 别名与 stencil 的映射在 `renderer/src/shapes/iconRegistry.ts`（TS）与
  `backend/app/importer/xml_edit.py`（Python 镜像）两处维护，
  由 `tests/test_phase_p1.py::test_stencil_ids_match_between_ts_and_python` 保证同步
