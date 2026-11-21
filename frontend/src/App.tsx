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
  const [tab, setTab] = useState<'generate' | 'parse' | 'validate' | 'versions'>('generate');
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
        {([['generate', '生成图纸'], ['parse', '文本解析'], ['validate', '校验 Graph'], ['versions', '图纸与版本']] as const).map(
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
