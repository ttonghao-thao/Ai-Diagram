import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { parseDrawioXml } from '../src/drawio/xmlReader.js';
import { serializeDrawio } from '../src/drawio/xmlWriter.js';
import { layoutGraph } from '../src/layout/elkLayout.js';
import { checkQuality } from '../src/quality/check.js';
import { resolveDrawing } from '../src/shapes/resolve.js';
import type { GraphDocument, GraphNode } from '../src/types.js';
import { validateGraph } from '../src/validate.js';

function fixture(): GraphDocument {
  return validateGraph(JSON.parse(readFileSync(path.resolve(__dirname, '../../../fixtures/v1_2_network.graph.json'), 'utf8'))).doc;
}

test('T01–T06: native network layers, two firewalls and explicit order in a nested group', async () => {
  const doc = fixture();
  const layout = await layoutGraph(doc);
  const x = (id: string) => layout.geometries.get('n_' + id)!.x;
  const y = (id: string) => layout.geometries.get('n_' + id)!.y;
  assert.ok(y('wan') < y('perimeter') && y('perimeter') < y('core'));
  assert.ok(y('core') < y('aggregation') && y('aggregation') < y('access'));
  assert.ok(y('core') < y('internal_fw') && y('internal_fw') < y('srv1'));
  assert.equal(y('srv1'), y('srv2'));
  assert.equal(y('srv2'), y('srv3'));
  assert.ok(x('srv1') < x('srv2') && x('srv2') < x('srv3'));
  const parsed = parseDrawioXml(serializeDrawio(doc, layout));
  assert.match(parsed.cellById.get('n_core')!.style!, /shape=mxgraph\.cisco\.misc\.route_switch_processor;/);
  assert.equal(parsed.cellById.get('n_srv1')?.parent, 'g_servers');
  assert.equal(parsed.cellById.get('e_backbone')?.value, '');
  assert.equal(doc.edges[1].label, '万兆主干');
  assert.equal(parsed.cellById.get('e_backbone')?.source, 'n_core');
  assert.equal(parsed.cellById.get('e_backbone')?.target, 'n_perimeter');
  assert.equal(checkQuality(doc, layout.drawing!, parsed).ok, true);
});

test('T03: nested default numeric order stays independent of document order', async () => {
  const doc = fixture();
  delete doc.layout.constraints;
  const layout = await layoutGraph(doc);
  const x = (id: string) => layout.geometries.get('n_' + id)!.x;
  assert.ok(x('srv1') < x('srv2') && x('srv2') < x('srv3'));
});

test('T07–T09: label footprint is separate, aliases match, and unknown shapes warn', () => {
  const doc = fixture();
  doc.nodes = [
    { id: 'cn', label: '服务器', kind: 'server' },
    { id: 'long', label: '服务器—跨园区超长业务应用'.repeat(15), kind: 'server' },
    { id: 'apcn', label: 'AP 中文', kind: 'generic', properties: { deviceType: '无线接入点' } },
    { id: 'apen', label: 'AP English', kind: 'generic', properties: { deviceType: 'Access Point' } },
    { id: 'other', label: '非标设备', kind: 'generic', style: { shapeId: 'fabricated.native.asset' } },
  ];
  const { nodes, warnings } = resolveDrawing(doc);
  assert.deepEqual(nodes.cn.iconSize, nodes.long.iconSize);
  assert.ok(nodes.long.labelSize.width > nodes.long.iconSize.width);
  assert.ok(nodes.long.labelSize.height > nodes.cn.labelSize.height);
  assert.equal(nodes.apcn.shapeId, nodes.apen.shapeId);
  assert.ok(warnings.some((issue) => issue.code === 'INVALID_SHAPE'));
  assert.ok(warnings.some((issue) => issue.code === 'UNKNOWN_DEVICE_TYPE'));
  assert.doesNotMatch(nodes.other.style, /fabricated/);
});

function obstacleFixture(): GraphDocument {
  const n = (id: string, x: number, y: number): GraphNode => ({
    id, label: id, kind: 'server', geometry: { x, y, width: 48, height: 68 },
  });
  return {
    schemaVersion: '1.1', diagramId: 'obstacle', name: '路由测试', diagramType: 'network_topology',
    appearance: { themeId: 'cisco', edgeRouting: 'auto', edgeArrowPolicy: 'hidden' },
    nodes: [n('source', 70, 140), n('target', 610, 140), n('other', 320, 140)],
    groups: [], edges: [{ id: 'line', source: 'source', target: 'target', kind: 'dataflow', direction: 'forward' }],
    layout: { algorithm: 'manual', direction: 'DOWN', preserveManualPositions: true },
  };
}

test('T13–T15: straight warns, auto uses bends, manual points and semantic direction survive', async () => {
  const doc = obstacleFixture();
  const analyze = async () => {
    const layout = await layoutGraph(doc);
    const xml = parseDrawioXml(serializeDrawio(doc, layout));
    return { layout, edge: xml.cellById.get('e_line')!, quality: checkQuality(doc, layout.drawing!, xml) };
  };
  let result = await analyze();
  assert.ok((result.edge.geometry?.points.length ?? 0) >= 2);
  assert.ok(!result.quality.issues.some((item) => item.code === 'EDGE_NODE_COLLISION'));
  assert.match(result.edge.style!, /endArrow=none;/);
  assert.match(result.edge.style!, /aiDirection=forward;/);
  doc.appearance!.edgeRouting = 'straight';
  result = await analyze();
  assert.equal(result.edge.geometry?.points.length, 0);
  assert.ok(result.quality.issues.some((item) => item.code === 'EDGE_NODE_COLLISION'));
  doc.edges[0].waypoints = [{ x: 120, y: 70 }, { x: 590, y: 70 }];
  result = await analyze();
  assert.deepEqual(result.edge.geometry?.points, doc.edges[0].waypoints);
});

test('constraints honor locks and report cycles rather than modifying topology', async () => {
  const doc = fixture();
  doc.layout.constraints = [
    { type: 'order', axis: 'x', nodes: ['srv1', 'srv2'] },
    { type: 'order', axis: 'x', nodes: ['srv2', 'srv1'] },
  ];
  await assert.rejects(layoutGraph(doc), /LAYOUT_CONFLICT/);
  assert.equal(doc.edges.length, 8);
  const graph = obstacleFixture();
  graph.layout.constraints = [{ type: 'relativePosition', source: 'target', target: 'source', position: 'left' }];
  await assert.rejects(layoutGraph(graph), /LAYOUT_CONFLICT/);
});

test('rank, relative positions and alignment produce a deterministic star layout', async () => {
  const doc = obstacleFixture();
  for (const node of doc.nodes) delete node.geometry;
  doc.layout.algorithm = 'star';
  doc.layout.centerNodeId = 'source';
  doc.layout.constraints = [
    { type: 'rank', rank: 0, nodes: ['source'] },
    { type: 'rank', rank: 2, nodes: ['other', 'target'] },
    { type: 'align', axis: 'x', mode: 'center', nodes: ['source', 'target'] },
    { type: 'relativePosition', source: 'other', target: 'target', position: 'left' },
  ];
  const first = await layoutGraph(doc);
  const second = await layoutGraph(doc);
  assert.deepEqual(first.geometries, second.geometries);
  assert.equal(first.geometries.get('n_source')!.x, first.geometries.get('n_target')!.x);
  assert.ok(first.geometries.get('n_source')!.y < first.geometries.get('n_other')!.y);
  assert.equal(first.geometries.get('n_other')!.y, first.geometries.get('n_target')!.y);
});

test('quality rejects missing or moved protected objects and broken topology', async () => {
  const doc = obstacleFixture();
  const layout = await layoutGraph(doc);
  const parsed = parseDrawioXml(serializeDrawio(doc, layout));
  parsed.cellById.get('e_line')!.target = 'n_missing';
  const report = checkQuality(doc, layout.drawing!, parsed, {
    unknownIds: ['editor_custom'], protectedGeometry: { source: { x: 8, y: 0, width: 48, height: 68 } },
  });
  assert.equal(report.ok, false);
  assert.deepEqual(new Set(report.issues.filter((item) => item.severity === 'error').map(({ code }) => code)),
    new Set(['TOPOLOGY_MISMATCH', 'UNKNOWN_CELL_LOSS', 'LOCKED_POSITION_CHANGED']));
});
