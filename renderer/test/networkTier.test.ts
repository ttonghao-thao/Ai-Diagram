/**
 * Network hierarchy layout (docs/03 section 1 position template):
 * undirected edges are oriented by device tier FOR LAYOUT ONLY, so
 * "公网 → 防火墙 → 核心交换机 → 服务器" comes out top-down no matter which
 * way round the sentence listed them. The semantic graph is never modified.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { layoutGraph } from '../src/layout/elkLayout.js';
import { networkTierOf, orientEdgesForLayout } from '../src/layout/networkTier.js';
import { serializeDrawio } from '../src/drawio/xmlWriter.js';
import { parseDrawioXml } from '../src/drawio/xmlReader.js';
import type { GraphDocument } from '../src/types.js';

/** "一台核心交换机连接三台服务器，上联防火墙，防火墙连公网" in sentence order. */
function sentenceGraph(direction: 'DOWN' | 'UP' = 'DOWN'): GraphDocument {
  return {
    schemaVersion: '1.0',
    diagramId: 'tier',
    name: '层级布局',
    diagramType: 'network_topology',
    nodes: [
      { id: 'core', label: '核心交换机', kind: 'switch' },
      { id: 's1', label: '服务器 1', kind: 'server' },
      { id: 's2', label: '服务器 2', kind: 'server' },
      { id: 's3', label: '服务器 3', kind: 'server' },
      { id: 'fw', label: '防火墙', kind: 'firewall' },
      { id: 'net', label: '公网', kind: 'cloud' },
    ],
    groups: [],
    edges: [
      { id: 'l1', source: 'core', target: 's1', kind: 'physical', direction: 'undirected' },
      { id: 'l2', source: 'core', target: 's2', kind: 'physical', direction: 'undirected' },
      { id: 'l3', source: 'core', target: 's3', kind: 'physical', direction: 'undirected' },
      { id: 'l4', source: 'core', target: 'fw', kind: 'physical', direction: 'undirected' },
      { id: 'l5', source: 'fw', target: 'net', kind: 'physical', direction: 'undirected' },
    ],
    layout: { algorithm: 'layered', direction, preserveManualPositions: true },
  };
}

function baseDoc(diagramType: 'network_topology' | 'business_architecture'): GraphDocument {
  return {
    schemaVersion: '1.0', diagramId: 'd', name: 'd', diagramType,
    nodes: [], groups: [], edges: [],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
}

test('tiers follow the network hierarchy', () => {
  assert.equal(networkTierOf({ kind: 'cloud' }), 0);
  assert.equal(networkTierOf({ kind: 'router' }), 1);
  assert.equal(networkTierOf({ kind: 'firewall' }), 2);
  assert.equal(networkTierOf({ kind: 'switch' }), 3);
  assert.equal(networkTierOf({ kind: 'server' }), 4);
  // aliases on generic nodes
  assert.equal(networkTierOf({ kind: 'generic', properties: { deviceType: 'VPN_Gateway' } }), 2);
  assert.equal(networkTierOf({ kind: 'generic', properties: { deviceType: 'access_point' } }), 4);
  // unknown types have no tier
  assert.equal(networkTierOf({ kind: 'generic' }), undefined);
  assert.equal(networkTierOf({ kind: 'service' }), undefined);
});

test('undirected edges are handed to the layout engine high-tier first', () => {
  const oriented = orientEdgesForLayout(sentenceGraph());
  const byId = Object.fromEntries(oriented.map((o) => [o.edge.id, o]));
  assert.deepEqual([byId.l4.source, byId.l4.target], ['fw', 'core']);   // was core -> fw
  assert.deepEqual([byId.l5.source, byId.l5.target], ['net', 'fw']);   // was fw -> net
  assert.deepEqual([byId.l1.source, byId.l1.target], ['core', 's1']);  // already high -> low
  // the edge objects themselves are untouched
  assert.deepEqual([byId.l4.edge.source, byId.l4.edge.target], ['core', 'fw']);
});

test('layout puts 公网 → 防火墙 → 核心交换机 → 服务器 top-down', async () => {
  const layout = await layoutGraph(sentenceGraph());
  const y = (id: string) => layout.geometries.get(`n_${id}`)!.y;
  assert.ok(y('net') < y('fw'), `公网 (${y('net')}) must be above 防火墙 (${y('fw')})`);
  assert.ok(y('fw') < y('core'), `防火墙 (${y('fw')}) must be above 核心交换机 (${y('core')})`);
  assert.ok(y('core') < y('s1') && y('core') < y('s2') && y('core') < y('s3'));
  // the three servers share one row
  assert.equal(y('s1'), y('s2'));
  assert.equal(y('s2'), y('s3'));
});

test('same-layer devices keep the input order left to right', async () => {
  const layout = await layoutGraph(sentenceGraph());
  const x = (id: string) => layout.geometries.get(`n_${id}`)!.x;
  assert.ok(x('s1') < x('s2') && x('s2') < x('s3'), `got ${x('s1')}, ${x('s2')}, ${x('s3')}`);
});

test('layout never changes the semantic edges or the XML source/target', async () => {
  const doc = sentenceGraph();
  const before = JSON.stringify(doc.edges);
  const layout = await layoutGraph(doc);
  assert.equal(JSON.stringify(doc.edges), before);
  const parsed = parseDrawioXml(serializeDrawio(doc, layout));
  const l4 = parsed.cellById.get('e_l4')!;
  assert.equal(l4.source, 'n_core');   // declared order preserved in the file
  assert.equal(l4.target, 'n_fw');
});

test('directed edges keep their declared direction (meaningful flow)', async () => {
  const doc = baseDoc('network_topology');
  doc.nodes = [
    { id: 'srv', label: '服务器', kind: 'server' },
    { id: 'net', label: '公网', kind: 'cloud' },
  ];
  // a forward dataflow edge says server -> internet: keep that orientation
  doc.edges = [{ id: 'd1', source: 'srv', target: 'net', kind: 'dataflow', direction: 'forward' }];
  const oriented = orientEdgesForLayout(doc);
  assert.deepEqual([oriented[0].source, oriented[0].target], ['srv', 'net']);
});

test('unknown-tier endpoints keep the declared order', () => {
  const doc = baseDoc('network_topology');
  doc.nodes = [
    { id: 'box', label: '未知设备', kind: 'generic' },
    { id: 'sw', label: '交换机', kind: 'switch' },
  ];
  doc.edges = [{ id: 'u1', source: 'box', target: 'sw', kind: 'physical', direction: 'undirected' }];
  const oriented = orientEdgesForLayout(doc);
  assert.deepEqual([oriented[0].source, oriented[0].target], ['box', 'sw']);
});

test('UP/LEFT layouts still place the higher tier on top', async () => {
  const layout = await layoutGraph(sentenceGraph('UP'));
  const y = (id: string) => layout.geometries.get(`n_${id}`)!.y;
  assert.ok(y('net') < y('fw') && y('fw') < y('core') && y('core') < y('s1'));
});

test('tier orientation only applies to network topologies', () => {
  const doc = baseDoc('business_architecture');
  doc.nodes = [
    { id: 'db', label: '数据库', kind: 'database' },
    { id: 'svc', label: '服务', kind: 'service' },
  ];
  doc.edges = [{ id: 'b1', source: 'db', target: 'svc', kind: 'logical', direction: 'undirected' }];
  const oriented = orientEdgesForLayout(doc);
  assert.deepEqual([oriented[0].source, oriented[0].target], ['db', 'svc']);
});
