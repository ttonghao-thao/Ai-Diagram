/**
 * X-05: 100 nodes / 150 edges layout performance. Records the measured time;
 * the number is reported in IMPLEMENTATION_REPORT.md (no invented figures).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { layoutGraph } from '../src/layout/elkLayout.js';
import { serializeDrawio } from '../src/drawio/xmlWriter.js';
import { parseDrawioXml } from '../src/drawio/xmlReader.js';
import type { GraphDocument } from '../src/types.js';

/** Deterministic synthetic graph: 5 groups x 20 nodes, 150 edges. */
function syntheticGraph(nodesPerGroup = 20, groupCount = 5): GraphDocument {
  const groups = Array.from({ length: groupCount }, (_, gi) => ({
    id: `zone_${gi}`,
    label: `分区${gi}（含${nodesPerGroup}节点）`,
  }));
  const nodes: Array<{ id: string; label: string; kind: 'server' | 'vm' | 'switch' | 'client' | 'database'; groupId: string }> = [];
  for (let gi = 0; gi < groupCount; gi += 1) {
    for (let ni = 0; ni < nodesPerGroup; ni += 1) {
      nodes.push({
        id: `host_${gi}_${ni}`,
        label: `主机${gi}-${ni}`,
        kind: (['server', 'vm', 'switch', 'client', 'database'] as const)[ni % 5],
        groupId: `zone_${gi}`,
      });
    }
  }
  const edges: Array<{ id: string; source: string; target: string; kind: 'physical' | 'dataflow'; direction: 'undirected' | 'forward'; label: string }> = [];
  let edgeSeq = 0;
  const pushEdge = (source: string, target: string, kind: 'physical' | 'dataflow'): void => {
    edges.push({
      id: `link_${edgeSeq}`,
      source,
      target,
      kind,
      direction: kind === 'physical' ? 'undirected' : 'forward',
      label: '',
    });
    edgeSeq += 1;
  };
  // Chains inside each group: (n-1) per group = 95 edges.
  for (let gi = 0; gi < groupCount; gi += 1) {
    for (let ni = 0; ni < nodesPerGroup - 1; ni += 1) {
      pushEdge(`host_${gi}_${ni}`, `host_${gi}_${ni + 1}`, 'physical');
    }
  }
  // Spokes from each group's first node to other groups' first nodes: 20.
  for (let gi = 0; gi < groupCount; gi += 1) {
    for (let gj = 0; gj < groupCount; gj += 1) {
      if (gi !== gj) pushEdge(`host_${gi}_0`, `host_${gj}_0`, 'dataflow');
    }
  }
  // Ring between group heads: 5.
  for (let gi = 0; gi < groupCount; gi += 1) {
    pushEdge(`host_${gi}_0`, `host_${(gi + 1) % groupCount}_0`, 'dataflow');
  }
  // Extra spokes from nodes 1..6 of each group to group 0's head: 30.
  for (let gi = 0; gi < groupCount; gi += 1) {
    for (let ni = 1; ni <= 6; ni += 1) {
      pushEdge(`host_${gi}_${ni}`, 'host_0_0', 'dataflow');
    }
  }
  return {
    schemaVersion: '1.0',
    diagramId: 'perf_test',
    name: `性能测试 ${groupCount * nodesPerGroup} 节点`,
    diagramType: 'network_topology',
    nodes,
    groups,
    edges,
    layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
  } as GraphDocument;
}

test('X-05: 100 nodes / 150 edges layout and serialization performance', async () => {
  const doc = syntheticGraph(20, 5);
  assert.equal(doc.nodes.length, 100);
  assert.equal(doc.edges.length, 150);

  const startedLayout = performance.now();
  const layout = await layoutGraph(doc);
  const layoutMs = performance.now() - startedLayout;

  const startedSerialize = performance.now();
  const xml = serializeDrawio(doc, layout);
  const serializeMs = performance.now() - startedSerialize;

  const parsed = parseDrawioXml(xml);
  assert.deepEqual(parsed.cells.filter((c) => c.vertex).length, 100 + 5);
  assert.deepEqual(parsed.cells.filter((c) => c.edge).length, 150);

  const total = Math.round(layoutMs + serializeMs);
  // Generous CI bound; the measured value (not this bound) goes into the report.
  assert.ok(total < 30000, `layout+serialize took ${total}ms, exceeds 30s bound`);
  console.log(`PERF X-05: layout=${layoutMs.toFixed(1)}ms serialize=${serializeMs.toFixed(1)}ms total=${total}ms (100 nodes / 150 edges, page ${layout.pageWidth}x${layout.pageHeight})`);
});
