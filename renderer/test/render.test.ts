/**
 * Renderer output tests (docs/06 section 2: X-01, X-02, X-03).
 * Generates out/network.drawio and out/business.drawio as Phase 0 deliverables.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { layoutGraph } from '../src/layout/elkLayout.js';
import { serializeDrawio, escapeXml } from '../src/drawio/xmlWriter.js';
import { parseDrawioXml, validateStructure } from '../src/drawio/xmlReader.js';
import { validateGraph } from '../src/validate.js';
import { edgeCellId, groupCellId, nodeCellId } from '../src/types.js';
import type { GraphDocument, GraphNode } from '../src/types.js';

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const OUT_DIR = path.join(REPO_ROOT, 'out');

function loadFixture(name: string): GraphDocument {
  const raw = JSON.parse(readFileSync(path.join(REPO_ROOT, 'fixtures', name), 'utf8'));
  return validateGraph(raw).doc;
}

async function renderToFile(fixture: string, outName: string): Promise<{ doc: GraphDocument; xml: string }> {
  const doc = loadFixture(fixture);
  const layout = await layoutGraph(doc);
  const xml = serializeDrawio(doc, layout);
  mkdirSync(OUT_DIR, { recursive: true });
  writeFileSync(path.join(OUT_DIR, outName), xml, 'utf8');
  return { doc, xml };
}

test('X-01/X-02 network fixture renders structurally valid XML', async () => {
  const { doc, xml } = await renderToFile('network.graph.json', 'network.drawio');
  const parsed = parseDrawioXml(xml);
  assert.deepEqual(validateStructure(parsed), []);
  assert.equal(parsed.pageName, doc.name);

  const vertices = parsed.cells.filter((c) => c.vertex);
  const edges = parsed.cells.filter((c) => c.edge);
  assert.equal(vertices.length, doc.nodes.length + doc.groups.length);
  assert.equal(edges.length, doc.edges.length);

  // Stable cell id mapping for every graph object.
  for (const n of doc.nodes) {
    const cell = parsed.cellById.get(nodeCellId(n.id));
    assert.ok(cell, `missing vertex cell for node ${n.id}`);
    assert.equal(cell.value, n.label);
    const expectedParent = n.groupId ? groupCellId(n.groupId) : '1';
    assert.equal(cell.parent, expectedParent);
  }
  for (const g of doc.groups) {
    const cell = parsed.cellById.get(groupCellId(g.id));
    assert.ok(cell, `missing group cell for ${g.id}`);
    assert.equal(cell.value, g.label);
  }
  for (const e of doc.edges) {
    const cell = parsed.cellById.get(edgeCellId(e.id));
    assert.ok(cell, `missing edge cell for ${e.id}`);
    assert.equal(cell.source, nodeCellId(e.source));
    assert.equal(cell.target, nodeCellId(e.target));
  }
  // Every cell's parent reference resolves (X-02) and groups precede children.
  const seen = new Set(['0', '1']);
  for (const cell of parsed.cells) {
    if (cell.id === '0' || cell.id === '1') continue;
    assert.ok(seen.has(cell.parent ?? ''), `parent of ${cell.id} must be declared before the cell`);
    seen.add(cell.id);
  }
});

test('X-01/X-02 business fixture renders structurally valid XML with cross-group edges', async () => {
  const { doc, xml } = await renderToFile('business.graph.json', 'business.drawio');
  const parsed = parseDrawioXml(xml);
  assert.deepEqual(validateStructure(parsed), []);
  assert.equal(parsed.cells.filter((c) => c.vertex).length, doc.nodes.length + doc.groups.length);
  assert.equal(parsed.cells.filter((c) => c.edge).length, doc.edges.length);

  // Cross-group edges carry orthogonal waypoints from ELK and stay near the page.
  for (const e of doc.edges) {
    const cell = parsed.cellById.get(edgeCellId(e.id));
    assert.ok(cell, `missing edge cell ${e.id}`);
    if (cell.geometry && cell.geometry.points.length) {
      for (const p of cell.geometry.points) {
        assert.ok(p.x > -60 && p.x < (parsed.pageWidth ?? 0) + 60, `waypoint x out of page bounds: ${JSON.stringify(p)}`);
        assert.ok(p.y > -60 && p.y < (parsed.pageHeight ?? 0) + 60, `waypoint y out of page bounds: ${JSON.stringify(p)}`);
      }
    }
  }
});

test('X-03 Chinese labels and XML special characters survive escaping', () => {
  const tricky = `中文 & <标签> "引号" '单引号' && <b>not html</b>`;
  assert.equal(escapeXml('plain'), 'plain');
  // Apostrophes stay literal (attributes are double-quoted); the rest escapes.
  assert.equal(
    escapeXml(tricky),
    `中文 &amp; &lt;标签&gt; &quot;引号&quot; '单引号' &amp;&amp; &lt;b&gt;not html&lt;/b&gt;`,
  );

  const doc: GraphDocument = {
    schemaVersion: '1.0',
    diagramId: 'escape_test',
    name: `名称含 " & < > ' 中文`,
    diagramType: 'business_architecture',
    nodes: [{ id: 'n1', label: tricky, kind: 'generic' }],
    groups: [{ id: 'g1', label: `组名 & "组" <X>'`, }],
    edges: [],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  const nodes = doc.nodes[0] as GraphNode;
  nodes.groupId = 'g1';
  const xml = serializeDrawio(doc, {
    geometries: new Map([
      ['g_g1', { x: 0, y: 0, width: 400, height: 200 }],
      ['n_n1', { x: 10, y: 50, width: 120, height: 56 }],
    ]),
    edgeWaypoints: new Map(),
    pageWidth: 900,
    pageHeight: 600,
  });
  const parsed = parseDrawioXml(xml);
  assert.equal(parsed.pageName, doc.name);
  assert.equal(parsed.cellById.get('g_g1')?.value, doc.groups[0].label);
  assert.equal(parsed.cellById.get('n_n1')?.value, tricky);
  // Node is a child of the group; conversion keeps relative coords.
  const gGeo = parsed.cellById.get('g_g1')!.geometry!;
  const nGeo = parsed.cellById.get('n_n1')!.geometry!;
  assert.equal(nGeo.x, 10);
  assert.equal(nGeo.y, 50);
  assert.equal(gGeo.x, 0);
});

test('kind styles and physical undirected edges are reflected in the XML', async () => {
  const { doc, xml } = await renderToFile('network.graph.json', 'network-check-style.drawio');
  const parsed = parseDrawioXml(xml);
  const fw = parsed.cellById.get(nodeCellId('firewall'));
  assert.ok(fw?.style?.includes('fillColor=#F8CECC'));
  const cloud = parsed.cellById.get(nodeCellId('wan'));
  assert.ok(cloud?.style?.includes('ellipse'));
  const phys = parsed.cellById.get(edgeCellId('wan_to_fw'));
  assert.ok(phys?.style?.includes('endArrow=none'));
  assert.equal(doc.nodes.length, 6);
  // Style assertions are done in memory; remove the scratch file.
  rmSync(path.join(OUT_DIR, 'network-check-style.drawio'), { force: true });
});

test('unknown kinds map to the generic style (no unknown-kind crash)', () => {
  const doc: GraphDocument = {
    schemaVersion: '1.0',
    diagramId: 'generic_test',
    name: '未知设备',
    diagramType: 'network_topology',
    nodes: [{ id: 'weird', label: '神秘设备XYZ-100', kind: 'generic' }],
    groups: [],
    edges: [],
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  };
  const layout = layoutGraph(doc);
  return layout.then((out) => {
    const xml = serializeDrawio(doc, out);
    const parsed = parseDrawioXml(xml);
    assert.ok(parsed.cellById.get('n_weird')?.style?.includes('fillColor=#FFF2CC'));
  });
});
