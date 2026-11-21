import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from './api';

/**
 * Phase 1 minimal admin console (docs/01 section 6): generate / parse /
 * validate / versions + download. No drawing canvas — editing happens in
 * Windows draw.io Desktop.
 */

const SAMPLE_NETWORK = {
  schemaVersion: '1.0',
  diagramId: 'demo_network',
  name: '示例拓扑（演示）',
  diagramType: 'network_topology',
  nodes: [
    { id: 'sw1', label: '核心交换机', kind: 'switch' },
    { id: 'srv1', label: '业务服务器', kind: 'server' },
  ],
  groups: [],
  edges: [
    { id: 'l1', source: 'sw1', target: 'srv1', kind: 'physical', direction: 'undirected' },
  ],
  layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
};

const SAMPLE_BUSINESS = {
  schemaVersion: '1.0',
  diagramId: 'demo_business',
  name: '示例业务架构（演示）',
  diagramType: 'business_architecture',
  nodes: [
    { id: 'gateway', label: '接口网关', kind: 'service' },
    { id: 'content', label: '内容服务', kind: 'service' },
    { id: 'database', label: '中心内容库', kind: 'database' },
  ],
  groups: [],
  edges: [
    { id: 'e1', source: 'gateway', target: 'content', kind: 'dataflow', direction: 'forward', label: '内容请求' },
    { id: 'e2', source: 'content', target: 'database', kind: 'dataflow', direction: 'bidirectional', label: '内容读写' },
  ],
  layout: { algorithm: 'layered', direction: 'DOWN', preserveManualPositions: true },
};

type Issue = { code: string; message: string; relatedIds?: string[]; severity?: string; requiresConfirmation?: boolean };

function IssueList({ issues }: { issues: Issue[] }) {
  if (!issues.length) return null;
  return (
    <ul className="issues">
      {issues.map((it, i) => (
        <li key={i} className={it.requiresConfirmation ? 'warn-confirm' : 'warn'}>
          <b>{it.code}</b>：{it.message}
          {it.requiresConfirmation ? '（需人工确认）' : ''}
        </li>
      ))}
    </ul>
  );
}

function ErrorBox({ err }: { err: ApiError | null }) {
  if (!err) return null;
  return (
    <div className="error">
      <b>错误 {err.code}</b>：{err.message}
      {err.details ? <pre>{JSON.stringify(err.details, null, 2)}</pre> : null}
    </div>
  );
}

interface DiagramInfo { id: string; name: string; diagramType: string; currentVersion: number; updatedAt: string }

export default function App() {
  const [tab, setTab] = useState<'generate' | 'parse' | 'validate' | 'versions' | 'import' | 'patch'>('generate');
  const [health, setHealth] = useState<{ rendererAvailable: boolean; llm: { enabled: boolean; provider: string | null } } | null>(null);

  const refreshHealth = useCallback(() => {
    api.health().then(({ data }) => setHealth(data as never)).catch(() => setHealth(null));
  }, []);
  useEffect(refreshHealth, [refreshHealth]);

  return (
    <div className="layout">
      <header>
        <h1>AI 图纸工作台</h1>
        <span className="health">
          {health
            ? `渲染器：${health.rendererAvailable ? '可用' : '未构建'} · LLM：${health.llm.enabled ? `启用（${health.llm.provider}）` : '关闭（JSON 生成可用）'}`
            : '服务端未连接'}
          <button className="ghost" onClick={refreshHealth}>刷新</button>
        </span>
      </header>
      <nav>
        {([['generate', '生成图纸'], ['parse', '文本解析'], ['validate', '校验 Graph'], ['versions', '图纸与版本'],
          ['import', '导入回导'], ['patch', 'AI 修改']] as const).map(
          ([key, label]) => (
            <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>
              {label}
            </button>
          ),
        )}
      </nav>
      <main>
        {tab === 'generate' && <GenerateTab />}
        {tab === 'parse' && <ParseTab />}
        {tab === 'validate' && <ValidateTab />}
        {tab === 'versions' && <VersionsTab />}
        {tab === 'import' && <ImportTab />}
        {tab === 'patch' && <PatchTab />}
      </main>
      <footer>Phase 1 · 图形精修请在 Windows draw.io Desktop 中完成；本工作台不含画布。</footer>
    </div>
  );
}

function GenerateTab() {
  const [text, setText] = useState(JSON.stringify(SAMPLE_NETWORK, null, 2));
  const [err, setErr] = useState<ApiError | null>(null);
  const [result, setResult] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(null);
    setResult(null);
    let graph: unknown;
    try {
      graph = JSON.parse(text);
    } catch (e) {
      setErr(new ApiError('LOCAL_JSON', `JSON 解析失败：${String(e)}`));
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.createDiagram(graph);
      setResult(data);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>从 Graph JSON 创建图纸（初始版本）</h2>
      <p className="hint">
        加载示例：
        <button onClick={() => setText(JSON.stringify(SAMPLE_NETWORK, null, 2))}>网络拓扑</button>
        <button onClick={() => setText(JSON.stringify(SAMPLE_BUSINESS, null, 2))}>业务架构</button>
      </p>
      <textarea rows={14} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      <button className="primary" disabled={busy} onClick={submit}>
        {busy ? '生成中…' : '生成 .drawio 并创建 v1'}
      </button>
      <ErrorBox err={err} />
      {result && (
        <div className="ok">
          已创建 <b>{result.diagram.id}</b>（{result.diagram.name}）当前版本 v{result.diagram.currentVersion}
          ，SHA-256 <code>{String(result.version.sha256).slice(0, 16)}…</code>
          {'　'}
          <a href={api.exportUrl(result.diagram.id)} download>
            下载 .drawio
          </a>
          <IssueList issues={result.warnings ?? []} />
        </div>
      )}
    </section>
  );
}

function ParseTab() {
  const [text, setText] = useState('一台核心交换机连接三台服务器');
  const [diagramType, setDiagramType] = useState('network_topology');
  const [err, setErr] = useState<ApiError | null>(null);
  const [result, setResult] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(null);
    setResult(null);
    setBusy(true);
    try {
      const { data } = await api.parseText(text, diagramType);
      setResult(data);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>文本 → Graph 草稿（不写入版本）</h2>
      <p className="hint">需启用 LLM（LLM_ENABLED=true，provider=mock 或 OpenAI-compatible）。</p>
      <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} />
      <p>
        <select value={diagramType} onChange={(e) => setDiagramType(e.target.value)}>
          <option value="network_topology">network_topology（网络拓扑）</option>
          <option value="business_architecture">business_architecture（业务架构）</option>
        </select>
        <button className="primary" disabled={busy} onClick={submit}>
          {busy ? '解析中…' : '解析草稿'}
        </button>
      </p>
      <ErrorBox err={err} />
      {result && (
        <div className="ok">
          <div>
            草稿包含 {result.graph.nodes.length} 个节点、{result.graph.edges.length} 条边；Schema 合法：
            {String(result.schemaValid)}
          </div>
          <IssueList issues={result.documentWarnings ?? []} />
          <details>
            <summary>查看 Graph JSON</summary>
            <pre>{JSON.stringify(result.graph, null, 2)}</pre>
          </details>
        </div>
      )}
    </section>
  );
}

function ValidateTab() {
  const [text, setText] = useState('');
  const [err, setErr] = useState<ApiError | null>(null);
  const [result, setResult] = useState<Record<string, any> | null>(null);

  const submit = async () => {
    setErr(null);
    setResult(null);
    let graph: unknown;
    try {
      graph = JSON.parse(text);
    } catch (e) {
      setErr(new ApiError('LOCAL_JSON', `JSON 解析失败：${String(e)}`));
      return;
    }
    try {
      const { data } = await api.validateGraph(graph);
      setResult(data);
    } catch (e) {
      setErr(e as ApiError);
    }
  };

  return (
    <section>
      <h2>校验 GraphDocument（不创建版本）</h2>
      <textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} placeholder="粘贴 Graph JSON…" spellCheck={false} />
      <button className="primary" onClick={submit}>校验</button>
      <ErrorBox err={err} />
      {result && (
        <div className={result.ok ? 'ok' : 'error'}>
          {result.ok ? '✓ 结构与语义校验通过' : '✗ 校验未通过'}
          <IssueList issues={result.errors ?? []} />
          <IssueList issues={[...(result.warnings ?? []), ...(result.documentWarnings ?? [])]} />
        </div>
      )}
    </section>
  );
}

interface VersionInfo { version: number; parentVersion: number | null; origin: string; sha256: string; createdAt: string }

function useDiagrams(errFn: (e: ApiError) => void) {
  const [diagrams, setDiagrams] = useState<DiagramInfo[]>([]);
  const refresh = useCallback(() => {
    api.listDiagrams().then(({ data }) => setDiagrams((data as any).diagrams)).catch(errFn);
  }, [errFn]);
  useEffect(refresh, [refresh]);
  return { diagrams, refresh };
}

function DiagramPicker({ diagrams, value, onChange }: { diagrams: DiagramInfo[]; value: string | null; onChange: (id: string) => void }) {
  return (
    <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
      <option value="" disabled>选择图纸…</option>
      {diagrams.map((d) => (
        <option key={d.id} value={d.id}>{d.id}（v{d.currentVersion}）</option>
      ))}
    </select>
  );
}

function DiffSummary({ diff }: { diff: any }) {
  const s = diff?.summary ?? {};
  const entries = Object.entries(s).filter(([k]) => k !== 'total');
  return (
    <table>
      <tbody>
        <tr><th colSpan={2}>差异摘要（共 {s.total ?? 0} 项）</th></tr>
        {entries.map(([k, v]) => (
          <tr key={k}><td>{k}</td><td>{String(v)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function ImportTab() {
  const setErrSafe = useCallback((e: ApiError) => setErr(e), []);
  const { diagrams, refresh } = useDiagrams(setErrSafe);
  const [selected, setSelected] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Record<string, any> | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const current = diagrams.find((d) => d.id === selected);

  const upload = async () => {
    setErr(null); setMsg(null); setPreview(null);
    if (!selected || !file || !current) {
      setErr(new ApiError('LOCAL_INPUT', '请选择图纸和 .drawio 文件'));
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.importPreview(selected, file, current.currentVersion);
      setPreview(data);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!selected || !preview) return;
    setBusy(true);
    try {
      const { data } = await api.importCommit(selected, preview.confirmationToken, current!.currentVersion);
      setMsg(`已提交为 v${(data as any).version.version}（保留未知对象 ${data.preservedUnknownCells} 个）`);
      setPreview(null);
      refresh();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>导入 Desktop 修改后的 .drawio（先预览差异，再确认提交）</h2>
      <p className="hint">
        在 Windows draw.io Desktop 中编辑保存后，把文件上传到这里。多页文件会被拒绝且不改动现有版本。
      </p>
      <p>
        <DiagramPicker diagrams={diagrams} value={selected} onChange={(id) => { setSelected(id); setPreview(null); setMsg(null); }} />
        <input type="file" accept=".drawio,application/xml,text/xml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button className="primary" disabled={busy || !selected || !file} onClick={upload}>
          {busy ? '解析中…' : '上传并预览差异'}
        </button>
      </p>
      <ErrorBox err={err} />
      {msg && <div className="ok">{msg}</div>}
      {preview && (
        <div>
          <DiffSummary diff={preview.diff} />
          <IssueList issues={preview.warnings ?? []} />
          {preview.requiresConfirmation ? (
            <p className="hint">包含删除/重接线等高风险变更，请核对差异后再提交。</p>
          ) : null}
          <button className="primary" disabled={busy} onClick={commit}>
            确认导入为新版本 v{preview.candidateVersion}
          </button>
        </div>
      )}
    </section>
  );
}

function PatchTab() {
  const setErrSafe = useCallback((e: ApiError) => setErr(e), []);
  const { diagrams, refresh } = useDiagrams(setErrSafe);
  const [selected, setSelected] = useState<string | null>(null);
  const [instruction, setInstruction] = useState('新增两台服务器并连接核心交换机');
  const [preview, setPreview] = useState<Record<string, any> | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const current = diagrams.find((d) => d.id === selected);

  const runPreview = async () => {
    setErr(null); setMsg(null); setPreview(null);
    if (!selected || !current) return;
    setBusy(true);
    try {
      const { data } = await api.patchPreview(selected, { instruction });
      setPreview(data);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!selected || !preview || !current) return;
    setBusy(true);
    try {
      const { data } = await api.patchApply(selected, preview.confirmationToken, current.currentVersion);
      setMsg(`已应用并生成 v${(data as any).version.version}；受影响对象：${(data as any).impactedIds.join(', ')}`);
      setPreview(null);
      refresh();
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>AI 增量修改（指令 → Patch 预览 → 确认应用）</h2>
      <p className="hint">
        示例指令：新增两台服务器并连接核心交换机 / 删除服务器 02 / 重命名外部网络为互联网出口。手工移动过的对象不会被自动挪动。
      </p>
      <p>
        <DiagramPicker diagrams={diagrams} value={selected} onChange={(id) => { setSelected(id); setPreview(null); setMsg(null); }} />
      </p>
      <textarea rows={2} value={instruction} onChange={(e) => setInstruction(e.target.value)} />
      <button className="primary" disabled={busy || !selected} onClick={runPreview}>
        {busy ? '分析中…' : '预览 Patch'}
      </button>
      <ErrorBox err={err} />
      {msg && <div className="ok">{msg}{'　'}<a href={api.exportUrl(selected!)} download>下载新版本</a></div>}
      {preview && (
        <div className={preview.requiresConfirmation ? 'error' : 'ok'}>
          <div>
            需要确认：<b>{String(preview.requiresConfirmation)}</b>
            {preview.confirmationReasons?.length ? `（${preview.confirmationReasons.join('；')}）` : ''}
          </div>
          <div>受影响对象：{preview.impactedIds?.join(', ')}</div>
          <IssueList issues={preview.warnings ?? []} />
          <details>
            <summary>布局计划与差异</summary>
            <pre>{JSON.stringify({ layoutPlan: preview.layoutPlan, diff: preview.diff?.summary }, null, 2)}</pre>
          </details>
          <button className="primary" disabled={busy} onClick={apply}>确认应用</button>
        </div>
      )}
    </section>
  );
}

function VersionsTab() {
  const [diagrams, setDiagrams] = useState<DiagramInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, any> | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busyVersion, setBusyVersion] = useState(false);
  const [layoutMsg, setLayoutMsg] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.listDiagrams().then(({ data }) => {
      setDiagrams((data as any).diagrams);
    }).catch((e) => setErr(e as ApiError));
  }, []);
  useEffect(refresh, [refresh]);

  const openVersions = useCallback((id: string) => {
    setSelected(id);
    setLayoutMsg(null);
    api.listVersions(id).then(({ data }) => setVersions(data as never)).catch((e) => setErr(e as ApiError));
  }, []);
  useEffect(() => {
    if (selected) openVersions(selected);
  }, [selected, openVersions]);

  const relayout = async () => {
    if (!selected || !versions) return;
    setBusyVersion(true);
    setLayoutMsg(null);
    try {
      const { data } = await api.layoutDiagram(selected, versions.currentVersion);
      setLayoutMsg(`已生成新版本 v${(data as any).version.version}（ELK 重排）`);
      await openVersions(selected);
    } catch (e) {
      setLayoutMsg(`重排失败：${(e as ApiError).code} ${(e as ApiError).message}`);
    } finally {
      setBusyVersion(false);
    }
  };

  return (
    <section>
      <h2>图纸与版本</h2>
      <button className="ghost" onClick={refresh}>刷新列表</button>
      <ErrorBox err={err} />
      <table>
        <thead>
          <tr><th>ID</th><th>名称</th><th>类型</th><th>当前版本</th><th></th></tr>
        </thead>
        <tbody>
          {diagrams.map((d) => (
            <tr key={d.id} className={selected === d.id ? 'selected' : ''}>
              <td>{d.id}</td>
              <td>{d.name}</td>
              <td>{d.diagramType}</td>
              <td>v{d.currentVersion}</td>
              <td><button onClick={() => openVersions(d.id)}>查看版本</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && versions && (
        <div>
          <h3>
            {selected} 的版本列表（当前 v{versions.currentVersion}）
            <button className="primary" disabled={busyVersion} onClick={relayout}>
              {busyVersion ? '重排中…' : '基于当前版本重新布局（新版本）'}
            </button>
          </h3>
          {layoutMsg && <p className="hint">{layoutMsg}</p>}
          <table>
            <thead>
              <tr><th>版本</th><th>来源</th><th>父版本</th><th>SHA-256</th><th>时间</th><th>下载</th></tr>
            </thead>
            <tbody>
              {versions.versions.map((v: any) => (
                <tr key={v.version}>
                  <td>v{v.version}</td>
                  <td>{v.origin}</td>
                  <td>{v.parentVersion ?? '—'}</td>
                  <td><code>{String(v.sha256).slice(0, 16)}…</code></td>
                  <td>{v.createdAt}</td>
                  <td><a href={api.exportUrl(selected, v.version)} download={`v${v.version}.drawio`}>.drawio</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
