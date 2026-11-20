/**
 * X-04: absolute <-> relative coordinate roundtrip within 1px for nested
 * groups. Also covers manual-mode layout honoring provided geometry.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { layoutGraph } from '../src/layout/elkLayout.js';
import { serializeDrawio } from '../src/drawio/xmlWriter.js';
import { parseDrawioXml, absoluteGeometry } from '../src/drawio/xmlReader.js';
import { validateGraph } from '../src/validate.js';
import { groupCellId, nodeCellId } from '../src/types.js';
import type { GraphDocument, GraphNode } from '../src/types.js';

const PX_TOLERANCE = 1;

function nestedGraph(): GraphDocument {
  const raw = {
    schemaVersion: '1.0',
    diagramId: 'nested_roundtrip',
    name: '嵌套组往返测试',
    diagramType: 'business_architecture',
    groups: [
      { id: 'outer', label: '外层大区' },
      { id: 'inner', label: '内层子系统', parentId: 'outer' },
      { id: 'standalone', label: '独立区' },
    ],
    nodes: [
      { id: 'deep1', label: '深层节点一', kind: 'service', groupId: 'inner' },
      { id: 'deep2', label: '深层节点二', kind: 'database', groupId: 'inner' },
      { id: 'mid', label: '中层节点', kind: 'service', groupId: 'outer' },
      { id: 'root_node', label: '根节点', kind: 'client' },
      { id: 'free', label: '独立节点', kind: 'server', groupId: 'standalone' },
    ],
    edges: [
      { id: 'r1', source: 'root_node', target: 'deep1', kind: 'dataflow', direction: 'forward', label: '调用' },
      { id: 'r2', source: 'deep1', target: 'deep2', kind: 'dataflow', direction: 'bidirectional', label: '读写' },
      { id: 'r3', source: 'mid', target: 'root_node', kind: 'control', direction: 'forward', label: '控制' },
    ],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  return validateGraph(raw).doc;
}

test('X-04 nested group coordinates roundtrip within 1px (layered mode)', async () => {
  const doc = nestedGraph();
  const layout = await layoutGraph(doc);
  const xml = serializeDrawio(doc, layout);
  const parsed = parseDrawioXml(xml);

  for (const n of doc.nodes) {
    const cell = parsed.cellById.get(nodeCellId(n.id))!;
    const abs = absoluteGeometry(cell, parsed.cellById);
    const expected = layout.geometries.get(nodeCellId(n.id))!;
    assert.ok(Math.abs(abs.x - expected.x) <= PX_TOLERANCE, `node ${n.id} x: ${abs.x} vs ${expected.x}`);
    assert.ok(Math.abs(abs.y - expected.y) <= PX_TOLERANCE, `node ${n.id} y: ${abs.y} vs ${expected.y}`);
    assert.ok(Math.abs(abs.width - expected.width) <= PX_TOLERANCE);
    assert.ok(Math.abs(abs.height - expected.height) <= PX_TOLERANCE);
  }
  for (const g of doc.groups) {
    const cell = parsed.cellById.get(groupCellId(g.id))!;
    const abs = absoluteGeometry(cell, parsed.cellById);
    const expected = layout.geometries.get(groupCellId(g.id))!;
    assert.ok(Math.abs(abs.x - expected.x) <= PX_TOLERANCE, `group ${g.id} x: ${abs.x} vs ${expected.x}`);
    assert.ok(Math.abs(abs.y - expected.y) <= PX_TOLERANCE, `group ${g.id} y: ${abs.y} vs ${expected.y}`);
    assert.ok(Math.abs(abs.width - expected.width) <= PX_TOLERANCE);
    assert.ok(Math.abs(abs.height - expected.height) <= PX_TOLERANCE);
  }
  // Parent-child wiring: deep nodes live in the inner group cell.
  assert.equal(parsed.cellById.get(nodeCellId('deep1'))!.parent, groupCellId('inner'));
  assert.equal(parsed.cellById.get(groupCellId('inner'))!.parent, groupCellId('outer'));
  assert.equal(parsed.cellById.get(groupCellId('outer'))!.parent, '1');
});

test('X-04 manual mode keeps provided absolute geometry within 1px', () => {
  const doc = nestedGraph();
  doc.layout = { algorithm: 'manual', direction: 'DOWN', preserveManualPositions: true };
  doc.nodes.forEach((n, i) => {
    (n as GraphNode).geometry = { x: 100 + i * 40, y: 500 + i * 10, width: 140, height: 60 };
  });
  doc.groups.forEach((g) => {
    g.geometry = undefined;
  });
  const layout = layoutGraph(doc);
  return layout.then((out) => {
    const xml = serializeDrawio(doc, out);
    const parsed = parseDrawioXml(xml);
    for (const n of doc.nodes) {
      const cell = parsed.cellById.get(nodeCellId(n.id))!;
      const abs = absoluteGeometry(cell, parsed.cellById);
      const g = n.geometry!;
      assert.ok(Math.abs(abs.x - g.x) <= PX_TOLERANCE, `manual node ${n.id} x drifted: ${abs.x} vs ${g.x}`);
      assert.ok(Math.abs(abs.y - g.y) <= PX_TOLERANCE, `manual node ${n.id} y drifted: ${abs.y} vs ${g.y}`);
    }
    // Groups without geometry enclose their members.
    for (const g of doc.groups) {
      const cell = parsed.cellById.get(groupCellId(g.id))!;
      const abs = absoluteGeometry(cell, parsed.cellById);
      assert.ok(abs.width > 0 && abs.height > 0, `computed group ${g.id} must have a size`);
    }
  });
});

test('edge waypoints in XML match the layout output within 1px', async () => {
  const doc = nestedGraph();
  const layout = await layoutGraph(doc);
  const xml = serializeDrawio(doc, layout);
  const parsed = parseDrawioXml(xml);
  // Edges with waypoints declared in the graph are honored in manual mode;
  // in layered mode ELK bend points are written to <Array as="points">.
  for (const cell of parsed.cells.filter((c) => c.edge)) {
    const layoutPts = layout.edgeWaypoints.get(cell.id) ?? [];
    const xmlPts = cell.geometry?.points ?? [];
    assert.equal(xmlPts.length, layoutPts.length, `waypoint count for ${cell.id}`);
    xmlPts.forEach((p, i) => {
      const q = layoutPts[i];
      assert.ok(Math.abs(p.x - q.x) <= PX_TOLERANCE && Math.abs(p.y - q.y) <= PX_TOLERANCE);
    });
  }
});
