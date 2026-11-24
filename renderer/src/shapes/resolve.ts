import { deviceTypeOf, networkRoleOf, shapeCatalog, themeOf, themes, type ShapeAsset, type Theme } from './catalog.js';
import { dataUriToSvg, measureLabelWidth, resolveNodeIcon, sanitizeStyleToken, svgImageStyle, svgToDataUri } from './iconRegistry.js';
import { inspectSvg } from './svg.js';
import { composeEdgeStyle, composeStyle, GROUP_STYLE } from './styles.js';
import type { Geometry, GraphDocument, GraphEdge, GraphNode, GraphWarning, Point, StyleMap } from '../types.js';

export interface Size { width: number; height: number }
export type Routing = 'auto' | 'straight' | 'orthogonal';
export interface ResolvedShape {
  nodeId: string;
  shapeId: string | null;
  resolvedBy: string;
  themeId: string;
  style: string;
  iconSize: Size;
  labelSize: Size;
  layoutSize: Size;
  preserveAspectRatio: boolean;
  geometry?: Geometry;
}
export interface ResolvedEdge {
  style: string;
  value: string;
  routing: Routing;
  waypoints?: Point[];
}
export interface ResolveOptions {
  customIcons?: ReadonlyMap<string, string>;
  personalShapes?: Record<string, ShapeAsset>;
  preferences?: Record<string, string>;
  resize?: string[];
}
export interface ResolvedDrawing {
  theme: Theme;
  nodes: Record<string, ResolvedShape>;
  groups: Record<string, { style: string; geometry?: Geometry }>;
  edges: Record<string, ResolvedEdge>;
  warnings: GraphWarning[];
}

const styleKeys = new Set([
  'align', 'aspect', 'dashed', 'dashPattern', 'opacity', 'fillColor', 'fillOpacity', 'fontColor', 'fontSize',
  'fontStyle', 'fontFamily', 'gradientColor', 'html', 'labelBackgroundColor', 'labelBorderColor',
  'labelPosition', 'labelWidth', 'rounded', 'rotation', 'shadow', 'spacing', 'spacingTop', 'spacingBottom',
  'spacingLeft', 'spacingRight', 'strokeColor', 'strokeOpacity', 'strokeWidth', 'verticalAlign',
  'verticalLabelPosition', 'whiteSpace', 'startSize', 'horizontal', 'swimlaneFillColor',
  'startArrow', 'endArrow', 'startFill', 'endFill', 'entryX', 'entryY', 'exitX', 'exitY',
  'entryDx', 'entryDy', 'exitDx', 'exitDy', 'entryPerimeter', 'exitPerimeter',
]);

export function safeStyle(overrides: StyleMap | undefined): StyleMap {
  return Object.fromEntries(Object.entries(overrides ?? {}).filter(([key, value]) =>
    styleKeys.has(key) && (typeof value !== 'string' || /^[\w#., +%-]{1,100}$/.test(value))));
}

function shapeRef(style: string): string | null {
  return /(?:^|;)shape=mxgraph\.([^;]+);/.exec(style)?.[1] ?? null;
}

function iconSvg(raw: string): { style: string; size: Size } {
  const { width, height } = inspectSvg(raw);
  const scale = 100 / Math.max(width, height);
  return { style: svgImageStyle(svgToDataUri(raw)), size: { width: width * scale, height: height * scale } };
}

function resolveNode(node: GraphNode, theme: Theme, options: ResolveOptions, warnings: GraphWarning[]): ResolvedShape {
  const localTheme = typeof node.style?.iconTheme === 'string' ? themes.get(node.style.iconTheme) ?? theme : theme;
  const device = deviceTypeOf(node);
  const role = networkRoleOf(node);
  const findShape = (id: string) => options.personalShapes?.[id] ?? shapeCatalog().get(id);
  const requested = node.style?.shapeId ?? (typeof node.style?.shape === 'string' && node.style.shape.startsWith('mxgraph.') ? node.style.shape : undefined);
  let asset: ShapeAsset | undefined;
  let source = 'theme';
  let custom: ReturnType<typeof iconSvg> | undefined;
  if (typeof requested === 'string') {
    asset = findShape(requested.replace(/^mxgraph\./, ''));
    if (!asset || asset.assetType === 'cell_template') {
      warnings.push({ code: 'INVALID_SHAPE', message: '所选素材不可作为单节点放置，已用主题素材', relatedIds: [node.id], requiresConfirmation: false });
      asset = undefined;
    } else source = 'explicit';
  }
  const inline = node.style?.icon;
  if (!asset && typeof inline === 'string') {
    custom = iconSvg(dataUriToSvg(inline));
    source = 'explicit';
  }
  if (!asset && !custom) {
    const preferred = Object.hasOwn(options.preferences ?? {}, device) ? options.preferences?.[device] : undefined;
    if (preferred) asset = findShape(preferred);
    if (asset?.assetType === 'cell_template') asset = undefined;
    if (asset) source = 'preference';
  }
  if (!asset && !custom) {
    const uri = options.customIcons?.get(device) ?? options.customIcons?.get(node.kind);
    if (uri) {
      custom = iconSvg(dataUriToSvg(uri));
      source = 'custom-svg';
    }
  }
  if (!asset && !custom) {
    const mapped = [device, node.kind].find((entry) => Object.hasOwn(localTheme.devices, entry));
    if (mapped) asset = shapeCatalog().get(localTheme.devices[mapped]);
  }
  if (asset?.svg) custom = iconSvg(asset.svg);
  const fallback = resolveNodeIcon({ ...node, style: {}, properties: device ? { deviceType: device } : {} }, { theme: localTheme.baseTheme });
  const shapeId = asset?.id ?? (custom ? null : shapeRef(fallback.style));
  if (!asset && !custom && node.kind === 'generic' && (!device || fallback.resolvedBy === 'kind-stencil')) {
    warnings.push({ code: 'UNKNOWN_DEVICE_TYPE', message: '设备没有匹配的专用素材，已用通用图形', relatedIds: [node.id], requiresConfirmation: false });
    source = 'fallback';
  }
  const size = custom?.size ?? (asset
    ? { width: asset.defaultWidth, height: asset.defaultHeight }
    : { width: fallback.width, height: fallback.height });
  const iconSize = node.geometry && !options.resize?.includes(node.id)
    ? { width: node.geometry.width, height: node.geometry.height } : size;
  const inside = asset?.labelPosition === 'inside';
  const fontSize = Number(node.style?.fontSize) || localTheme.node.fontSize;
  const lineWidths = node.label.split(/\r?\n/).map((line) => measureLabelWidth(line) * fontSize / 12);
  const labelWidth = Math.min(300, Math.max(iconSize.width, Math.max(...lineWidths) + 20));
  const lines = lineWidths.reduce((sum, width) => sum + Math.max(1, Math.ceil(width / Math.max(12, labelWidth - 16))), 0);
  const labelHeight = Math.max(24, lines * (Math.max(6, Math.min(fontSize, 72)) + 4) + localTheme.node.labelSpacing);
  const outside = !inside || labelWidth > iconSize.width || labelHeight > iconSize.height;
  const labelSize = outside ? { width: labelWidth, height: labelHeight } : { width: 0, height: 0 };
  const overrides = safeStyle(node.style);
  const builtin = node.style?.shape;
  if (typeof builtin === 'string' && ['rectangle', 'ellipse', 'rhombus', 'process', 'cylinder3', 'hexagon', 'cloud'].includes(builtin)) {
    overrides.shape = builtin;
  }
  const base = custom?.style ?? asset?.style ?? fallback.style;
  const style = composeStyle(base, {
    fontSize: localTheme.node.fontSize, fontColor: localTheme.node.fontColor, whiteSpace: 'wrap',
    ...(outside ? { labelWidth, verticalLabelPosition: 'bottom', verticalAlign: 'top', align: 'center' } : {}),
    ...overrides,
    aiKind: node.kind,
    ...(typeof node.properties?.deviceType === 'string' ? { aiDeviceType: sanitizeStyleToken(device || node.properties.deviceType) } : {}),
    ...(role ? { aiNetworkRole: sanitizeStyleToken(role) } : {}),
    ...(shapeId ? { aiShapeId: shapeId } : {}),
  });
  return { nodeId: node.id, shapeId, themeId: localTheme.id, resolvedBy: source, style, iconSize, labelSize,
    layoutSize: { width: Math.max(iconSize.width, labelSize.width), height: iconSize.height + labelSize.height },
    preserveAspectRatio: true };
}

function resolveEdge(edge: GraphEdge, doc: GraphDocument, theme: Theme): ResolvedEdge {
  const routing = doc.appearance?.edgeRouting ??
    (doc.schemaVersion === '1.0' ? (theme.id === 'cisco' ? 'straight' : 'orthogonal') : theme.edge.routing);
  const policy = doc.appearance?.edgeLabelPolicy ?? theme.edge.labelPolicy;
  const label = edge.label ?? '';
  const value = policy === 'hidden' || (policy === 'explicit_only' && edge.style?.labelSource === 'inferred') ? '' : label;
  const style = composeEdgeStyle(edge.kind, edge.direction, { ...theme.edge.style, ...safeStyle(edge.style) }, theme.baseTheme);
  const withoutRoute = style.split(';').filter((part) => !/^(?:edgeStyle|orthogonalLoop|jettySize)=/.test(part)).join(';');
  const arrowStyle = (doc.appearance?.edgeArrowPolicy ?? theme.edge.arrowPolicy) === 'hidden'
    ? 'startArrow=none;startFill=0;endArrow=none;endFill=0;' : '';
  return { routing, value, style: withoutRoute + arrowStyle };
}

export function resolveDrawing(doc: GraphDocument, options: ResolveOptions = {}): ResolvedDrawing {
  const theme = themeOf(doc);
  const warnings: GraphWarning[] = [];
  if (doc.appearance?.themeId && !themes.has(doc.appearance.themeId)) {
    warnings.push({ code: 'INVALID_THEME', message: '主题不存在，已使用图纸默认主题', requiresConfirmation: false });
  }
  return {
    theme, warnings,
    nodes: Object.fromEntries(doc.nodes.map((node) => [node.id, resolveNode(node, theme, options, warnings)])),
    groups: Object.fromEntries(doc.groups.map((group) => [
      group.id, { style: composeStyle(GROUP_STYLE, {
        ...(doc.schemaVersion === '1.1' ? theme.group.style : {}), ...safeStyle(group.style), ...(doc.appearance?.showGroups === false ? {
        fillColor: 'none', strokeColor: 'none', swimlaneFillColor: 'none', opacity: 0,
      } : {}) }) },
    ])),
    edges: Object.fromEntries(doc.edges.map((edge) => [edge.id, resolveEdge(edge, doc, theme)])),
  };
}
