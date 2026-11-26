# 图标主题与自定义 SVG 素材

生成 `.drawio` 时的图标来自 **draw.io Desktop 自带的形状库**（零在线加载、不依赖外部素材），
另外支持放入本地 SVG 做自定义图标。图标名都已对照 drawio v24.7.17 源码核实，并用官方渲染器渲染比对。

## 1. 两套内置主题

| 主题 | 图标库 | 外观 | 默认用于 |
|---|---|---|---|
| `cisco` | draw.io 内置 **Cisco** 库（`mxgraph.cisco.*`） | 实心蓝 `#036897` + 白色线条；连线为细黑直线、无箭头 | **网络拓扑图**（`network_topology`） |
| `networks` | draw.io 内置 **Networks** 库（`mxgraph.networks.*`） | 黑白线稿；连线为正交折线 | 业务架构图，以及显式选择线稿风格的网络图 |

Cisco 主题的设备映射（与 draw.io 自带 Cisco 网络模板同款）：

| 设备类型 | Cisco 形状 | 说明 |
|---|---|---|
| 交换机 | `misc.route_switch_processor` | 库中原名 Route Switch Processor |
| 防火墙 | `security.ios_firewall` | 砖墙 + 四向箭头 |
| 路由器 | `routers.router` | 圆柱四箭头 |
| 服务器 | `servers.fileserver` | 通用单机箱 |
| 云 / 公网 | `storage.cloud` | 白底描边，文字在云内 |
| 数据库 | `storage.relational_database` | 圆柱 |
| 终端 | `computers_and_peripherals.pc` | 台式机 |
| 虚拟机 | `servers.software_based_server` | 库中没有虚拟机专用图标，取最接近的 |

别名设备：`access_point`、`load_balancer`、`vpn_gateway`、`hub` 有 Cisco 图标；
`modem`、`proxy`、`mainframe`、`rack` 库中没有对应形状，自动回退到 Networks 线稿图标；
`generic`（未识别设备）保持中性黄色方框，便于一眼看出“未知类型”。

### 切换主题

```json
// 整张图改回线稿风格（写在顶层）
"metadata": { "iconTheme": "networks" }

// 单个节点切换（写在节点的 style 里，不会输出到 .drawio）
{ "id": "fw", "label": "防火墙", "kind": "firewall", "style": { "iconTheme": "networks" } }
```

## 2. 自定义 SVG 图标（三步）

1. 准备一个 SVG（≤64KB、含 `<svg>`、无 `<script>` / `javascript:`）
2. 按用途命名后放入**本目录**：
   - `<设备别名>.svg` —— 供 `properties.deviceType` 为该别名的节点使用（推荐，不影响其他节点）
   - `<kind>.svg`（如 `switch.svg`）—— 会**覆盖该类型所有节点**的图标（慎用）
3. 重新生成图纸。节点写法：

```json
{"id": "ap1", "label": "无线 AP", "kind": "generic", "properties": {"deviceType": "access_point"}}
```

CLI 也可显式指定目录：`node dist/src/cli.js generate --input x.json --output y.drawio --icons-dir <目录>`

`examples/` 子目录里有三枚项目自绘的渐变风格示例（无线AP / VPN网关 / 入侵检测），
**默认不加载**（子目录会被跳过）；想启用就复制到本目录上一层。它们是当初 Cisco 映射还不存在时的过渡素材，
现在 `access_point`、`vpn_gateway` 已有原生 Cisco 图标，`ids_ips` 仍可用示例或你自己的 SVG。

## 3. 图标解析优先级（从高到低）

1. `node.style.shapeId` 指定的单节点素材，或 `node.style.icon` 指定的内嵌 SVG。
2. 素材库中为当前 `deviceType` 保存的默认映射。
3. 本目录中按 `deviceType` 或 `kind` 匹配的 SVG。
4. 当前主题中按 `deviceType` 或 `kind` 匹配的素材，再回退到内置类型图形。

## 4. 使用第三方素材的许可提醒

任何 SVG 都能直接丢进本目录，但请先核对许可：网上流传的 draw.io 图库包多标注“仅限个人学习”，
Flaticon 等需署名，Cisco 官方图标涉及商标。商用请选 CC0 / MIT / Apache 许可的图标集或自行导出 SVG。
本目录及 `examples/` 内的素材为项目自绘。

## 5. 技术约束

- SVG 嵌入形式是**百分号编码** data URI（`image=data:image/svg+xml,%3Csvg...`），不要用 base64：
  draw.io 的 style 按 `;` 切分，base64 头里的分号会把样式截断成空白图标
- Cisco 图标的颜色来自样式里的 `fillColor`，漏掉会渲染成线稿
- 主题映射在 `renderer/assets/themes/`，统一由 `renderer/src/shapes/resolve.ts` 解析。回导时优先用 `aiKind`，并可识别旧的 `servers.server_with_router` 和新的 `servers.fileserver`。
