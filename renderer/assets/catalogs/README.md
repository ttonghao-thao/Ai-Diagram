# 素材目录与主题

`drawio-search-index.json` 是本地关键词索引，包含 2,289 个经过筛选的官方原生形状和样式变体。目录记录 Shape ID、绘制样式、尺寸和别名。上游提交、SHA-256 和许可说明在 [manifest.json](manifest.json)。原生样式由 draw.io Desktop 的内置库绘制。

- `network.json` 覆盖 12 个 Cisco Classic 索引项的中文别名、原始 stencil 尺寸及默认外观。
- `device-aliases.json` 将中英文设备名映射到标准子类型、一级 `kind` 和常见网络角色。
- [主题目录](../themes)保存设备映射、线条策略、文字、分组与绘图间距。主题包括 Cisco Classic、Networks、Modern、Telecom 和 Business。
- [预览目录](../previews)中的 Cisco 缩略图来自可编辑样例单元的实际 Viewer 渲染。SVG 上传使用原文件预览，更多原生形状可下载 `.drawio` 预览。
- 个人素材保存在现有 SQLite 数据库中。支持 SVG、draw.io `mxlibrary` 与通过 `cellId` 提取的历史节点。组合模板可保留内部结构并导出。合格的单节点素材支持设备默认映射。

从固定上游下载 `shape-search/search-index.json` 后，运行下面的命令重建索引。

```bash
python3 scripts/update_shape_catalog.py /path/to/search-index.json
```

更新时同时核对 `manifest.json`、上游许可证、样式变体和不同 Desktop 版本的可用性。用离线 Chrome 和固定版本 Viewer 重建缩略图。

```bash
python3 scripts/render_classic_previews.py --viewer /path/to/viewer-static.min.js \
  --stencils /path/to/stencils/cisco --chrome /path/to/chrome
```

来源及许可说明见 [drawio-mcp](https://github.com/jgraph/drawio-mcp) 和 [draw.io](https://github.com/jgraph/drawio/blob/v24.7.17/README.md)。
