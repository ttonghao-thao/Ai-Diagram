/**
 * Icon Registry (Phase 0.5): device kind -> professional draw.io icon.
 *
 * Primary sources are draw.io built-in stencil libraries that ship with
 * draw.io Desktop (no online loading at render time). The `mxgraph.networks`
 * shape ids below were verified against drawio v24.7.17:
 *   stencils/networks.xml defines e.g. name="Virtual Server", and
 *   mxStencilRegistry.parseStencilSet registers
 *     packageName + "." + name.toLowerCase().replace(/ /g, '_')
 *   (source: src/main/webapp/js/viewer.min.js, mxStencilRegistry).
 *
 * Custom SVG icons are supported and embedded as base64 data URIs directly in
 * the cell style — draw.io renders them without any network request.
 *
 * All node labels are rendered BELOW the icon (verticalLabelPosition=bottom),
 * so the ELK layout inflates node boxes by LABEL_BAND_HEIGHT to reserve the
 * label area (layout "considers" icon size + device name).
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { ErrorCodes, RenderError } from '../errors.js';
import { NODE_STYLES } from './styles.js';
import type { GraphNode, NodeKind, StyleMap } from '../types.js';

/** Extra vertical space the layout reserves below each icon for its label. */
export const LABEL_BAND_HEIGHT = 24;

const MAX_SVG_BYTES = 64 * 1024;

export interface IconDescriptor {
  /** Professional stencil style (draw.io built-in shape library). */
  stencilStyle: string;
  /** Phase 0 flat style; used for `generic` and as documented fallback. */
  fallbackStyle: string;
  /** Default icon box size (aspect follows the native stencil size). */
  width: number;
  height: number;
  source: 'stencil:mxgraph.networks' | 'builtin:mxgraph' | 'fallback:flat';
}

/** Adds label-below styling shared by every icon style. */
function labelBelow(style: string): string {
  return style + 'verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;';
}

function networksStencil(name: string): string {
  // Verified conversion: packageName '.' + name.toLowerCase().replace(/ /g,'_')
  return `shape=mxgraph.networks.${name};`;
}

/**
 * Icon Registry. Every GraphDocument NodeKind has an entry; unknown device
 * types resolve to the `generic` entry (docs requirement 7).
 */
export const ICON_REGISTRY: Record<NodeKind, IconDescriptor> = {
  // networks.xml: "Switch" (100x29) -> readable 130x48
  switch: {
    stencilStyle: labelBelow(networksStencil('switch')),
    fallbackStyle: labelBelow(NODE_STYLES.switch),
    width: 130, height: 48, source: 'stencil:mxgraph.networks',
  },
  // "Router" (100x29)
  router: {
    stencilStyle: labelBelow(networksStencil('router')),
    fallbackStyle: labelBelow(NODE_STYLES.router),
    width: 130, height: 48, source: 'stencil:mxgraph.networks',
  },
  // "Firewall" (100x100)
  firewall: {
    stencilStyle: labelBelow(networksStencil('firewall')),
    fallbackStyle: labelBelow(NODE_STYLES.firewall),
    width: 90, height: 92, source: 'stencil:mxgraph.networks',
  },
  // "Server" (90x100)
  server: {
    stencilStyle: labelBelow(networksStencil('server')),
    fallbackStyle: labelBelow(NODE_STYLES.server),
    width: 90, height: 96, source: 'stencil:mxgraph.networks',
  },
  // "Virtual Server" (110x120) chosen for VM (desktop VM = Virtual PC, less server-like)
  vm: {
    stencilStyle: labelBelow(networksStencil('virtual_server')),
    fallbackStyle: labelBelow(NODE_STYLES.vm),
    width: 100, height: 108, source: 'stencil:mxgraph.networks',
  },
  // "Storage" (100x100) for database
  database: {
    stencilStyle: labelBelow(networksStencil('storage')),
    fallbackStyle: labelBelow(NODE_STYLES.database),
    width: 90, height: 90, source: 'stencil:mxgraph.networks',
  },
  // "Cloud" (92.1x48.51)
  cloud: {
    stencilStyle: labelBelow(networksStencil('cloud')),
    fallbackStyle: labelBelow(NODE_STYLES.cloud),
    width: 130, height: 72, source: 'stencil:mxgraph.networks',
  },
  // "Terminal" (80x65) for client / 终端
  client: {
    stencilStyle: labelBelow(networksStencil('terminal')),
    fallbackStyle: labelBelow(NODE_STYLES.client),
    width: 100, height: 80, source: 'stencil:mxgraph.networks',
  },
  // Business service: core mxGraph built-in process shape (not a network device).
  service: {
    stencilStyle: labelBelow('shape=process;whiteSpace=wrap;fillColor=#D5E8D4;strokeColor=#82B366;fontColor=#2A4023;'),
    fallbackStyle: labelBelow(NODE_STYLES.service),
    width: 120, height: 64, source: 'builtin:mxgraph',
  },
  // Neutral generic device box (flat style IS the generic device icon).
  generic: {
    stencilStyle: labelBelow(NODE_STYLES.generic),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 120, height: 64, source: 'fallback:flat',
  },
};

/**
 * Extended device-type aliases (Phase 3 early deliverable): nodes with
 * kind="generic" and properties.deviceType matching one of these keys get
 * the mapped professional stencil WITHOUT any schema change. All shape ids
 * are existing mxgraph.networks members (verified in drawio v24.7.17
 * stencils/networks.xml).
 */
export const ALIAS_REGISTRY: Record<string, IconDescriptor> = {
  // "Wireless Hub" - wireless access point
  access_point: {
    stencilStyle: labelBelow(networksStencil('wireless_hub')),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 110, height: 80, source: 'stencil:mxgraph.networks',
  },
  // "Load Balancer" (100x29)
  load_balancer: {
    stencilStyle: labelBelow(networksStencil('load_balancer')),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 130, height: 48, source: 'stencil:mxgraph.networks',
  },
  // "Modem"
  modem: {
    stencilStyle: labelBelow(networksStencil('modem')),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 110, height: 72, source: 'stencil:mxgraph.networks',
  },
  // "Proxy Server" (103x107)
  proxy: {
    stencilStyle: labelBelow(networksStencil('proxy_server')),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 90, height: 96, source: 'stencil:mxgraph.networks',
  },
  // "Secured" - VPN gateway style locked tunnel
  vpn_gateway: {
    stencilStyle: labelBelow(networksStencil('secured')),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 96, height: 90, source: 'stencil:mxgraph.networks',
  },
  // "Hub"
  hub: {
    stencilStyle: labelBelow(networksStencil('hub')),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 110, height: 70, source: 'stencil:mxgraph.networks',
  },
  // "Mainframe" (80x100)
  mainframe: {
    stencilStyle: labelBelow(networksStencil('mainframe')),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 90, height: 100, source: 'stencil:mxgraph.networks',
  },
  // "Rack"
  rack: {
    stencilStyle: labelBelow(networksStencil('rack')),
    fallbackStyle: labelBelow(NODE_STYLES.generic),
    width: 100, height: 96, source: 'stencil:mxgraph.networks',
  },
};

/** Keys a custom SVG may be registered under (alias names, lowercased). */
function aliasKeys(node: GraphNode): string[] {
  const keys: string[] = [node.kind];
  const deviceType = node.properties?.deviceType;
  if (typeof deviceType === 'string' && deviceType.trim()) {
    keys.push(deviceType.trim().toLowerCase());
  }
  return keys;
}

/**
 * Make a string safe as a drawio style token: style values are split on ';'
 * and parsed as key=value, so separators and whitespace must be replaced.
 * Non-ASCII device names (e.g. Chinese deviceType) are legal and preserved.
 */
export function sanitizeStyleToken(value: string): string {
  return value.replace(/[;=\s]+/g, '-').replace(/[\x00-\x1f\x7f]+/g, '');
}

/**
 * Builds the `shape=image;...` style for an embedded SVG data URI.
 *
 * The URI MUST be the percent-encoded form (`data:image/svg+xml,%3Csvg...`).
 * drawio style strings are split on ';', so the base64 form
 * (`...;base64,xxx`) is truncated at the first `;` and renders blank (root
 * cause found via viewer rendering test). drawio itself embeds SVG images in
 * the percent-encoded form and special-cases it in postProcessCellStyle.
 */
export function svgImageStyle(dataUri: string): string {
  if (!dataUri.startsWith('data:image/svg+xml,')) {
    throw new RenderError(
      ErrorCodes.DRAWIO_UNSUPPORTED_CONTENT,
      'custom icon must be a percent-encoded SVG data URI (data:image/svg+xml,...); base64 form is truncated by drawio style parsing',
    );
  }
  return labelBelow(`shape=image;imageAspect=0;aspect=fixed;image=${dataUri};`);
}

/** Canonical percent-encoded SVG data URI (safe inside drawio style strings). */
export function svgToDataUri(svg: string): string {
  return 'data:image/svg+xml,' + encodeURIComponent(svg);
}

/** Decode a canonical (or legacy base64) SVG data URI back to SVG text. */
export function dataUriToSvg(dataUri: string): string {
  if (dataUri.startsWith('data:image/svg+xml;base64,')) {
    return Buffer.from(dataUri.slice('data:image/svg+xml;base64,'.length), 'base64').toString('utf8');
  }
  if (dataUri.startsWith('data:image/svg+xml,')) {
    return decodeURIComponent(dataUri.slice('data:image/svg+xml,'.length));
  }
  throw new RenderError(ErrorCodes.DRAWIO_UNSUPPORTED_CONTENT, 'unsupported SVG data URI form');
}

function isSvgDataUri(value: string): boolean {
  return value.startsWith('data:image/svg+xml,') || value.startsWith('data:image/svg+xml;base64,');
}

export interface ResolvedIcon {
  style: string;
  width: number;
  height: number;
  /** How the icon was resolved (for tests and reports). */
  resolvedBy: 'node-style' | 'custom-svg' | 'alias-stencil' | 'kind-stencil' | 'generic';
}

/**
 * Resolve the icon for a node.
 * Order: node.style.icon (data URI) -> custom SVG by kind/deviceType alias ->
 * registry stencil by deviceType alias -> registry stencil by kind -> generic.
 */
export function resolveNodeIcon(
  node: GraphNode,
  customIcons?: ReadonlyMap<string, string>,
): ResolvedIcon {
  const styleOverrides: StyleMap = { ...(node.style ?? {}) };
  // `icon` is a dedicated key (data URI), not a generic drawio style override.
  const inlineIcon = styleOverrides.icon;
  delete styleOverrides.icon;

  const deviceTypeRaw = node.properties?.deviceType;
  const deviceType = typeof deviceTypeRaw === 'string' ? deviceTypeRaw.trim() : '';
  const aliases = aliasKeys(node);

  const infoKeys: string[] = [`aiKind=${sanitizeStyleToken(node.kind)}`];
  if (deviceType) {
    infoKeys.push(`aiDeviceType=${sanitizeStyleToken(deviceType)}`);
  }
  const infoStyle = infoKeys.map((key) => key + ';').join('');

  const finish = (baseStyle: string, width: number, height: number, resolvedBy: ResolvedIcon['resolvedBy']): ResolvedIcon => {
    const parts = [baseStyle.endsWith(';') ? baseStyle : baseStyle + ';'];
    parts.push(infoStyle);
    for (const [k, v] of Object.entries(styleOverrides)) {
      const key = k.replace(/[;=\s]/g, '');
      if (!key) continue;
      parts.push(`${key}=${String(v).replace(/[;\r\n]/g, ' ').trim()};`);
    }
    return { style: parts.join(''), width, height, resolvedBy };
  };

  // 1. Per-node data URI icon (node.style.icon). Base64 forms are
  //    canonicalized to the percent-encoded form (see svgImageStyle note).
  if (typeof inlineIcon === 'string' && isSvgDataUri(inlineIcon)) {
    return finish(svgImageStyle(svgToDataUri(dataUriToSvg(inlineIcon))), 100, 80, 'node-style');
  }
  // 2. Custom SVG by kind or deviceType alias.
  if (customIcons) {
    for (const key of aliases) {
      const uri = customIcons.get(key);
      if (uri) {
        return finish(svgImageStyle(svgToDataUri(dataUriToSvg(uri))), 100, 80, 'custom-svg');
      }
    }
  }
  // 3. Registry stencil via deviceType alias: extended aliases first
  //    (AP/LB/modem/proxy/VPN/hub/mainframe/rack), then kind-named aliases
  //    (e.g. a generic node typed "firewall").
  if (deviceType) {
    const alias = deviceType.toLowerCase();
    const extended = ALIAS_REGISTRY[alias];
    if (extended) {
      return finish(extended.stencilStyle, extended.width, extended.height, 'alias-stencil');
    }
    const kindAlias = alias as NodeKind;
    if (kindAlias !== node.kind && kindAlias in ICON_REGISTRY) {
      const desc = ICON_REGISTRY[kindAlias];
      return finish(desc.stencilStyle, desc.width, desc.height, 'alias-stencil');
    }
  }
  // 4. Registry stencil by kind.
  const desc = ICON_REGISTRY[node.kind];
  if (desc) {
    return finish(desc.stencilStyle, desc.width, desc.height, 'kind-stencil');
  }
  // 5. Unknown kind -> generic icon, original type kept via aiDeviceType.
  const generic = ICON_REGISTRY.generic;
  return finish(generic.stencilStyle, generic.width, generic.height, 'generic');
}

/** Rough CJK-aware label width, shared with the flat-style size estimator. */
export function measureLabelWidth(label: string): number {
  let cjk = 0;
  let ascii = 0;
  for (const ch of label) {
    if (/[\u2E80-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/.test(ch)) {
      cjk += 1;
    } else {
      ascii += 1;
    }
  }
  return 13 * cjk + 7 * ascii;
}

/**
 * Icon box size for a node: explicit geometry wins; otherwise registry
 * defaults widened (never narrowed) to fit the device name.
 */
export function resolveNodeSize(node: GraphNode): { width: number; height: number } {
  if (node.geometry && node.geometry.width > 0 && node.geometry.height > 0) {
    return { width: node.geometry.width, height: node.geometry.height };
  }
  const icon = resolveNodeIcon(node);
  const labelWidth = measureLabelWidth(node.label) + 24;
  return {
    width: Math.max(icon.width, Math.min(Math.ceil(labelWidth), 300)),
    height: icon.height,
  };
}

/**
 * Load custom SVG icons from a directory: `<name>.svg` registers the icon
 * under the lowercased file name (kind or deviceType alias). Files are read
 * from local disk and embedded as data URIs — never loaded at runtime.
 */
export function loadCustomIcons(dir: string): Map<string, string> {
  const icons = new Map<string, string>();
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return icons;
  }
  for (const entry of entries) {
    if (!entry.toLowerCase().endsWith('.svg')) continue;
    const file = join(dir, entry);
    if (!statSync(file).isFile()) continue;
    const raw = readFileSync(file, 'utf8');
    const bytes = Buffer.byteLength(raw, 'utf8');
    if (bytes > MAX_SVG_BYTES) {
      throw new RenderError(
        ErrorCodes.DRAWIO_UNSUPPORTED_CONTENT,
        `custom icon ${entry} is ${bytes} bytes, exceeds the ${MAX_SVG_BYTES}-byte limit`,
      );
    }
    if (!/<svg[\s>]/i.test(raw)) {
      throw new RenderError(ErrorCodes.DRAWIO_UNSUPPORTED_CONTENT, `custom icon ${entry} is not an SVG document`);
    }
    if (/<script[\s>]/i.test(raw) || /javascript:/i.test(raw)) {
      throw new RenderError(ErrorCodes.DRAWIO_UNSUPPORTED_CONTENT, `custom icon ${entry} contains executable content`);
    }
    const name = entry.slice(0, -4).toLowerCase();
    icons.set(name, svgToDataUri(raw));
  }
  return icons;
}
