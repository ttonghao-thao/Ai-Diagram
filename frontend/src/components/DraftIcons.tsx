import { useState } from 'react';
import { api, type Material } from '../api';
import { MaterialPreview } from './Materials';

type DraftNode = {
  id: string;
  label: string;
  kind: string;
  properties?: { deviceType?: unknown };
  style?: Record<string, unknown>;
};

type IconGraph = { diagramId: string; nodes: DraftNode[] };
const shapeKeys = new Set(['shapeId', 'shape', 'icon']);

export function editableIconGraph(value: unknown): IconGraph | null {
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch { return null; }
  }
  if (!value || typeof value !== 'object' || !('diagramId' in value) || typeof value.diagramId !== 'string' ||
      !('nodes' in value) || !Array.isArray(value.nodes) || !value.nodes.length) return null;
  const nodes = value.nodes;
  if (nodes.some((node) => !node || typeof node.id !== 'string' || typeof node.label !== 'string' ||
      typeof node.kind !== 'string') || new Set(nodes.map(({ id }) => id)).size !== nodes.length) return null;
  return value as IconGraph;
}

function deviceType(node: DraftNode) {
  const subtype = node.properties?.deviceType;
  return typeof subtype === 'string' && subtype.trim() ? subtype.trim() : node.kind;
}

export function DraftIcons({ graph, disabled, onChange }: {
  graph: IconGraph;
  disabled: boolean;
  onChange: (graph: IconGraph) => void;
}) {
  const [nodeId, setNodeId] = useState('');
  const [sameType, setSameType] = useState(false);
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<Material[] | null>(null);
  const [picked, setPicked] = useState<Material | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const node = graph.nodes.find(({ id }) => id === nodeId) ?? graph.nodes[0];
  const type = deviceType(node);
  const peers = node.kind === 'generic' && type === 'generic' ? [node] : graph.nodes.filter(
    (item) => item.kind === node.kind && deviceType(item) === type);
  const ids = new Set((sameType ? peers : [node]).map(({ id }) => id));

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError('');
    setStatus('');
    try { await action(); } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  };
  const apply = (shapeId?: string) => {
    const nodes = graph.nodes.map((item) => {
      if (!ids.has(item.id)) return item;
      const style = Object.fromEntries(Object.entries(item.style ?? {}).filter(([key]) => !shapeKeys.has(key)));
      if (shapeId) style.shapeId = shapeId;
      return { ...item, style };
    });
    onChange({ ...graph, nodes });
    setStatus(`已更新 ${ids.size} 个设备的图标`);
  };

  return (
    <details className="draft-icons">
      <summary>选择设备图标</summary>
      <fieldset disabled={disabled || busy}>
        <div className="toolbar">
          <label>设备 <select aria-label="选择设备" value={node.id} onChange={(event) => {
            setNodeId(event.target.value);
            setSameType(false);
            setQuery('');
            setMatches(null);
            setPicked(null);
            setStatus('');
            setError('');
          }}>
            {graph.nodes.map(({ id, label }) => <option key={id} value={id}>{label} · {id}</option>)}
          </select></label>
          <span className="hint">{type} · {String(node.style?.shapeId ?? node.style?.shape ?? '默认图标')}</span>
          {peers.length > 1 && <label><input type="checkbox" checked={sameType}
            onChange={(event) => setSameType(event.target.checked)} /> 同类型设备（{peers.length}）</label>}
        </div>
        <form className="toolbar" onSubmit={(event) => {
          event.preventDefault();
          setPicked(null);
          setMatches(null);
          const q = query.trim() || type;
          void run(async () => {
            const { data } = await api.searchShapes(new URLSearchParams({ q, limit: '60' }));
            setMatches(data.items.filter((item) => item.usable !== false && item.assetType !== 'cell_template'));
          });
        }}>
          <input type="search" aria-label="搜索设备图标" value={query} placeholder={type} maxLength={160}
            onChange={(event) => setQuery(event.target.value)} />
          <button type="submit">搜索素材</button>
        </form>
        {matches?.length ? <label>素材 <select aria-label="选择图标素材" value={picked?.id ?? ''} onChange={(event) => {
          const id = event.target.value;
          setPicked(null);
          if (id) void run(async () => { setPicked((await api.shape(id)).data); });
        }}>
          <option value="">选择素材</option>
          {matches.map((item) => <option key={item.id} value={item.id}>{item.nameZh ?? item.name} · {item.id}</option>)}
        </select></label> : matches && <p className="hint">没有匹配的可放置素材。</p>}
        {picked && <MaterialPreview item={picked} />}
        <div className="toolbar">
          <button type="button" disabled={!picked} onClick={() => picked && apply(picked.id)}>应用图标</button>
          <button type="button" disabled={!graph.nodes.some((item) => ids.has(item.id) &&
            Object.keys(item.style ?? {}).some((key) => shapeKeys.has(key)))} onClick={() => apply()}>恢复默认图标</button>
        </div>
      </fieldset>
      {busy && <p role="status" className="hint">正在读取素材</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {status && <p role="status" className="hint">{status}</p>}
    </details>
  );
}
