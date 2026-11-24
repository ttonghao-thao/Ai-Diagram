import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Appearance, GraphDocument, GraphNode, NodeKind, StyleMap } from '../types.js';

const assets = path.resolve(__dirname, '..', '..', '..', 'assets');

function readAsset<T>(name: string): T {
  return JSON.parse(readFileSync(path.join(assets, name), 'utf8')) as T;
}

export interface ShapeAsset {
  id: string;
  name: string;
  nameZh?: string;
  category: string;
  library: string;
  assetType: 'stencil' | 'svg' | 'cell_template';
  source: string;
  style: string;
  nativeWidth: number;
  nativeHeight: number;
  defaultWidth: number;
  defaultHeight: number;
  preserveAspectRatio: boolean;
  labelPosition: 'bottom' | 'inside';
  deviceTypes?: string[];
  aliases?: string[];
  searchTags?: string;
  verified: boolean;
  svg?: string;
}

export interface Theme {
  id: string;
  name: string;
  version: string;
  iconLibrary: string;
  baseTheme: 'cisco' | 'networks';
  devices: Record<string, string>;
  node: { fontSize: number; fontColor: string; labelSpacing: number };
  edge: {
    routing: NonNullable<Appearance['edgeRouting']>;
    labelPolicy: NonNullable<Appearance['edgeLabelPolicy']>;
    arrowPolicy: NonNullable<Appearance['edgeArrowPolicy']>;
    style: StyleMap;
  };
  group: { style: StyleMap };
  layout: { nodeSpacing: number; layerSpacing: number; groupPadding: number };
}

const aliases = readAsset<Record<string, { kind: NodeKind; role?: string; aliases: string[] }>>('catalogs/device-aliases.json');
const themeIds = ['cisco', 'networks', 'modern', 'telecom', 'business'];
export const themes = new Map(themeIds.map((id) => [id, readAsset<Theme>(`themes/${id}.json`)]));
export const catalogVersion = readAsset<{ version: string }>('catalogs/manifest.json').version;
const curated = readAsset<Array<Partial<ShapeAsset> & { id: string }>>('catalogs/network.json');
const curatedById = new Map(curated.map((entry) => [entry.id, entry]));
let officialCatalog: Map<string, ShapeAsset> | undefined;

export function shapeCatalog(): ReadonlyMap<string, ShapeAsset> {
  officialCatalog ??= new Map(readAsset<ShapeAsset[]>('catalogs/drawio-search-index.json').map((entry) => [
    entry.id, { ...entry, ...curatedById.get(entry.id) },
  ]));
  return officialCatalog;
}

function aliasKey(value: string): string {
  return value.normalize('NFKC').trim().toLowerCase().replace(/[\s-]+/g, '_');
}

const aliasLookup = new Map(Object.entries(aliases).flatMap(([id, entry]) =>
  [id, ...entry.aliases].map((alias) => [aliasKey(alias), id] as const)));

export function deviceTypeOf(node: Pick<GraphNode, 'properties' | 'kind' | 'label'>): string {
  const supplied = node.properties?.deviceType;
  if (typeof supplied === 'string' && supplied.trim()) return aliasLookup.get(aliasKey(supplied)) ?? '';
  const label = aliasKey(node.label).replace(/_?\d+$/, '');
  return aliasLookup.get(label) ?? node.kind;
}

const roleLabels: Array<[RegExp, string]> = [
  [/^(?:公网|外网|internet|wan)(?:\s*\d+)?$/i, 'internet'],
  [/边界防火墙|出口防火墙|perimeter.*firewall/i, 'perimeter_security'],
  [/服务器区防火墙|内部防火墙|internal.*firewall|server.*firewall/i, 'internal_security'],
];

export function networkRoleOf(node: LookUpNode): string | undefined {
  const role = node.properties?.networkRole;
  if (typeof role === 'string' && role.trim()) return aliasKey(role);
  return roleLabels.find(([pattern]) => pattern.test(node.label.trim()))?.[1] ??
    aliases[deviceTypeOf(node)]?.role;
}

type LookUpNode = Pick<GraphNode, 'properties' | 'kind' | 'label'>;

export function themeOf(doc: Pick<GraphDocument, 'diagramType' | 'metadata' | 'appearance' | 'schemaVersion'>): Theme {
  const selected = doc.appearance?.themeId ?? doc.metadata?.iconTheme;
  if (typeof selected === 'string' && themes.has(selected)) return themes.get(selected)!;
  const fallback = doc.diagramType === 'network_topology' ? 'cisco' : (doc.schemaVersion === '1.0' ? 'networks' : 'business');
  return themes.get(fallback)!;
}
