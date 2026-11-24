/**
 * Network hierarchy tiers — the POSITION template from docs/03 section 1
 * ("云/出口 → 防火墙 → 核心/接入 → 服务器"). A position template decides
 * where devices are drawn; it is never used to invent or alter edges.
 */
import { networkRoleOf } from '../shapes/catalog.js';
import type { GraphDocument, GraphEdge, GraphNode } from '../types.js';

const KIND_TIER: Partial<Record<string, number>> = {
  cloud: 0,
  router: 1,
  firewall: 2,
  switch: 3,
  server: 4,
  vm: 4,
  database: 4,
  client: 4,
};

/** Tiers for extended deviceType aliases on kind="generic" nodes. */
const ALIAS_TIER: Record<string, number> = {
  modem: 1,
  vpn_gateway: 2,
  load_balancer: 3,
  proxy: 3,
  hub: 3,
  access_point: 4,
  mainframe: 4,
  rack: 4,
};

/** Lower tier = closer to the internet = drawn higher. undefined = unknown. */
export function networkTierOf(node: Pick<GraphNode, 'kind' | 'properties'>): number | undefined {
  if (node.kind === 'generic') {
    const deviceType = node.properties?.deviceType;
    if (typeof deviceType === 'string') {
      return ALIAS_TIER[deviceType.toLowerCase()];
    }
    return undefined;
  }
  return KIND_TIER[node.kind];
}

const ROLE_TIERS = new Map([
  ['internet', 0], ['edge_router', 1], ['perimeter_security', 2], ['core', 3],
  ['aggregation', 4], ['internal_security', 5], ['access', 5], ['endpoint', 6],
]);

function networkRanks(doc: GraphDocument): Map<string, number | undefined> {
  const ranks = new Map(doc.nodes.map((node) => {
    const role = networkRoleOf(node);
    const tier = node.properties?.tier;
    const fallback = doc.schemaVersion === '1.1' && node.kind === 'cloud' && node.groupId ? 6 :
      node.kind === 'cloud' && /内部|私有|private|internal/i.test(node.label) ? 6 :
      networkTierOf(node);
    return [node.id, typeof tier === 'number' && Number.isInteger(tier) && tier >= 0 && tier <= 999
      ? tier : (role ? ROLE_TIERS.get(role) : undefined) ?? (fallback === 4 ? 6 : fallback)];
  }));
  for (const constraint of doc.layout.constraints ?? []) {
    if (constraint.type === 'rank') for (const id of constraint.nodes) ranks.set(id, constraint.rank);
  }
  return ranks;
}

export interface OrientedEdge {
  edge: GraphEdge;
  source: string;
  target: string;
}

/**
 * Layout-only orientation of undirected edges in network topologies.
 *
 * LLM/user output follows sentence order ("核心交换机 上联 防火墙" becomes
 * switch -> firewall), but ELK places a source above its target in a DOWN
 * layout, which put servers and firewalls on one row below the switch. For
 * `undirected` edges the source/target order carries no meaning, so the
 * higher-tier device is handed to ELK as the "flow origin". The semantic
 * graph and the stored XML keep the declared source/target untouched.
 */
export function orientEdgesForLayout(doc: GraphDocument): OrientedEdge[] {
  const isNetwork = doc.diagramType === 'network_topology';
  const ranks = isNetwork ? networkRanks(doc) : new Map();
  const sourceFirst = doc.layout.direction === 'DOWN' || doc.layout.direction === 'RIGHT';
  const legacyOrder = doc.schemaVersion === '1.0';
  const explicitOrder = new Map<string, string>();
  for (const rule of doc.layout.constraints ?? []) {
    if (rule.type !== 'relativePosition') continue;
    const vertical = doc.layout.direction === 'UP' || doc.layout.direction === 'DOWN';
    if (vertical !== ['above', 'below'].includes(rule.position)) continue;
    const sourceIsFirst = ['above', 'left'].includes(rule.position) === sourceFirst;
    const key = [rule.source, rule.target].sort().join('/');
    explicitOrder.set(key, sourceIsFirst ? rule.source : rule.target);
  }
  return doc.edges.map((edge) => {
    let source = edge.source;
    let target = edge.target;
    if (isNetwork && edge.direction === 'undirected') {
      const sourceTier = ranks.get(edge.source);
      const targetTier = ranks.get(edge.target);
      const first = explicitOrder.get([edge.source, edge.target].sort().join('/'));
      if (first) {
        source = first;
        target = first === edge.source ? edge.target : edge.source;
      } else if (sourceTier !== undefined && targetTier !== undefined && sourceTier !== targetTier) {
        const higher = sourceTier < targetTier ? edge.source : edge.target;
        const lower = higher === edge.source ? edge.target : edge.source;
        const preferHigher = !legacyOrder || sourceFirst;
        source = preferHigher ? higher : lower;
        target = preferHigher ? lower : higher;
      }
    }
    return { edge, source, target };
  });
}
