import { useCallback, useEffect, useState } from 'react';
import { api, type Material, type ShapePreferences, type Theme } from '../api';

const PAGE_SIZE = 20;
const EMPTY_PREFS: ShapePreferences = { mappings: {}, favorites: [], deviceTypes: [] };
const TYPE_LABELS = { stencil: '原生图形', svg: 'SVG', cell_template: '组合模板' };

export function MaterialPreview({ item }: { item: Material }) {
  const label = item.nameZh ?? item.name;
  if (item.assetType === 'svg') {
    return <img src={api.shapePreview(item.id)} alt={label} width={140} height={100} />;
  }
  return <>
    {item.thumbnail && <img src={api.shapeThumbnail(item.id)} alt={label} width={140} height={100} />}
    <p><a href={api.shapePreview(item.id)} download>下载原生图形预览</a></p>
  </>;
}

export function Themes({ themes }: { themes: Theme[] }) {
  const kind = { auto: '自动避障', straight: '直线', orthogonal: '正交线' };
  return (
    <section>
      <h2>绘图主题</h2>
      <div className="theme-grid">
        {themes.map((theme) => (
          <article key={theme.id}>
            <h3>{theme.name}</h3>
            <dl>
              <dt>图形库</dt><dd>{theme.iconLibrary}</dd>
              <dt>默认连线</dt><dd>{kind[theme.edge.routing as keyof typeof kind]}</dd>
              <dt>设备间距</dt><dd>{theme.layout.nodeSpacing} px</dd>
              <dt>层级间距</dt><dd>{theme.layout.layerSpacing} px</dd>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

export function Materials() {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState({ query: '', library: '', favorite: false });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{ items: Material[]; total: number }>({ items: [], total: 0 });
  const [selected, setSelected] = useState<Material | null>(null);
  const [prefs, setPrefs] = useState(EMPTY_PREFS);
  const [device, setDevice] = useState('');
  const [importType, setImportType] = useState<'svg' | 'library' | 'drawio'>('svg');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let current = true;
    const criteria = new URLSearchParams({
      q: filter.query, library: filter.library, favorite: String(filter.favorite),
      offset: String(offset), limit: String(PAGE_SIZE),
    });
    Promise.all([api.searchShapes(criteria), api.preferences()]).then(([shapes, preferences]) => {
      if (!current) return;
      setPage(shapes.data); setPrefs(preferences.data);
    }).catch((err: Error) => { if (current) setError(err.message); });
    return () => { current = false; };
  }, [filter, offset, refresh]);

  const action = useCallback(async (work: () => Promise<void>) => {
    setError(''); setStatus(''); setBusy(true);
    try { await work(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }, []);

  const show = (id: string) => action(async () => {
    const { data } = await api.shape(id);
    setSelected(data);
  });
  const update = (changes: Partial<ShapePreferences>, status: string) => action(async () => {
    const { data } = await api.updatePreferences(changes);
    setPrefs(data); setStatus(status); setRefresh((i) => i + 1);
  });
  const exportItems = (ids: string[]) => action(async () => {
    const url = URL.createObjectURL(await api.exportMaterials(ids));
    const link = document.createElement('a');
    link.href = url; link.download = 'materials.xml'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  return (
    <section>
      <h2>图形素材库</h2>
      <form className="toolbar" onSubmit={(event) => {
        event.preventDefault(); setOffset(0); setFilter({ ...filter, query });
      }}>
        <input type="search" aria-label="素材搜索" placeholder="设备名称、分类或 Shape ID" value={query}
          onChange={(e) => setQuery(e.target.value)} />
        <select aria-label="图形库" value={filter.library} onChange={(e) => { setOffset(0); setFilter({ ...filter, library: e.target.value }); }}>
          <option value="">全部素材</option><option value="cisco">Cisco Classic</option>
          <option value="cisco19">Cisco Modern</option><option value="networks">Networks</option>
          <option value="rack">Rack</option><option value="cloud">Cloud</option><option value="personal">个人库</option>
        </select>
        <label><input type="checkbox" checked={filter.favorite} onChange={(e) => { setOffset(0); setFilter({ ...filter, favorite: e.target.checked }); }} /> 只看收藏</label>
        <button className="primary" type="submit">搜索</button>
      </form>
      <details className="material-import">
        <summary>导入素材</summary>
        <form className="toolbar" onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void action(async () => {
            const { data } = await api.importMaterial(form);
            setStatus(`已导入 ${data.items.length} 项素材`); setQuery(''); setOffset(0);
            setFilter({ query: '', library: 'personal', favorite: false }); setRefresh((i) => i + 1);
          });
        }}>
          <label>格式 <select name="kind" value={importType} onChange={(e) => setImportType(e.target.value as typeof importType)}>
            <option value="svg">SVG</option><option value="library">draw.io 素材库</option><option value="drawio">从 .drawio 提取</option>
          </select></label>
          <input aria-label="素材文件" name="file" type="file" required accept={importType === 'svg' ? '.svg' : '.xml,.drawio'} />
          {importType === 'drawio' && <input name="cellId" required maxLength={120} aria-label="节点 cell ID" placeholder="节点 cell ID" />}
          <input name="name" maxLength={200} aria-label="素材名称" placeholder="素材名称（可选）" />
          <button type="submit" disabled={busy}>导入</button>
        </form>
      </details>
      {error && <p className="error" role="alert">{error}</p>}
      {status && <p className="ok" role="status">{status}</p>}
      <div className="material-grid">
        <div className="table-scroll">
          <table>
            <thead><tr><th>素材</th><th>类型</th><th>尺寸</th></tr></thead>
            <tbody>{page.items.map((row) => (
              <tr key={row.id} className={selected?.id === row.id ? 'selected' : ''}>
                <td><button className="text-button" onClick={() => show(row.id)}>{row.nameZh ?? row.name}</button><small>{row.id}</small></td>
                <td>{TYPE_LABELS[row.assetType]}</td><td>{Math.round(row.defaultWidth)} × {Math.round(row.defaultHeight)}</td>
              </tr>
            ))}</tbody>
          </table>
          {!page.items.length && <p>没有匹配的素材。</p>}
          <div className="toolbar pagination">
            <button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</button>
            <span>共 {page.total} 项</span>
            <button disabled={offset + PAGE_SIZE >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button>
          </div>
        </div>
        {selected && (
          <aside className="material-details">
            <h3>{selected.nameZh ?? selected.name}</h3>
            <code>{selected.id}</code>
            <MaterialPreview item={selected} />
            {selected.assetType === 'cell_template' && <p>组合模板可导出到 draw.io 素材库。</p>}
            <div className="toolbar">
              <button disabled={busy} onClick={() => update({ favorites: prefs.favorites.includes(selected.id)
                ? prefs.favorites.filter((id) => id !== selected.id) : [...prefs.favorites, selected.id] }, '已保存收藏')}>
                {prefs.favorites.includes(selected.id) ? '取消收藏' : '收藏'}
              </button>
              <button disabled={busy} onClick={() => exportItems([selected.id])}>导出素材</button>
            </div>
            {selected.usable !== false && (
              <form className="toolbar" onSubmit={(e) => {
                e.preventDefault(); void update({ mappings: { ...prefs.mappings, [device]: selected.id } }, '已保存默认映射');
              }}>
                <label>设备类型 <select value={device} onChange={(e) => setDevice(e.target.value)} required>
                  <option value="">选择设备</option>{prefs.deviceTypes.map((id) => <option key={id}>{id}</option>)}
                </select></label>
                <button disabled={busy || !device}>设为默认素材</button>
              </form>
            )}
          </aside>
        )}
      </div>
      {Object.keys(prefs.mappings).length > 0 && (
        <details className="material-import"><summary>默认设备映射</summary>
          <dl>{Object.entries(prefs.mappings).map(([key, value]) => (
            <div key={key} className="toolbar"><dt>{key}</dt><dd>{value}</dd>
              <button disabled={busy} onClick={() => update({
                mappings: Object.fromEntries(Object.entries(prefs.mappings).filter(([k]) => k !== key)),
              }, '已移除默认映射')}>移除</button></div>
          ))}</dl>
        </details>
      )}
    </section>
  );
}
