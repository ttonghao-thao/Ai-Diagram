import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type LlmOptions, type LlmSettings, type LlmSettingsChanges } from '../api';

export function LlmSettingsPanel({ onSaved }: { onSaved: () => void }) {
  const [config, setConfig] = useState<LlmSettings | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState<LlmOptions['provider']>('mock');
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  const applyConfig = useCallback((data: LlmSettings) => {
    setConfig(data);
    setEnabled(data.enabled);
    setProvider(data.provider);
    setClearKey(false);
  }, []);

  const load = useCallback(async () => {
    setBusy(true);
    setConfig(null);
    setError('');
    setSaved(false);
    try {
      const { data } = await api.llmSettings();
      applyConfig(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [applyConfig]);

  useEffect(() => { void load(); }, [load]);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!config || busy) return;
    const form = new FormData(event.currentTarget);
    const field = (name: string) => String(form.get(name) ?? '').trim();
    const changes: LlmSettingsChanges = { baseVersion: config.version, enabled, provider };
    if (provider === 'openai') {
      const key = field('apiKey');
      Object.assign(changes, {
        baseUrl: field('baseUrl'),
        model: field('model'),
        timeoutSeconds: Number(form.get('timeoutSeconds')),
        maxRetries: Number(form.get('maxRetries')),
        reasoningEffort: field('reasoningEffort'),
        privateEndpoint: form.has('privateEndpoint'),
        ...(clearKey ? { apiKey: null } : key ? { apiKey: key } : {}),
      });
    }
    setBusy(true);
    setError('');
    setSaved(false);
    try {
      const { data } = await api.updateLlmSettings(changes);
      applyConfig(data);
      setSaved(true);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>LLM 配置</h2>
      {error && <p className="error" role="alert">{error}</p>}
      {saved && <p className="ok" role="status">配置已保存，后续请求使用新设置。</p>}
      {config ? (
        <form key={config.version} className="llm-settings" autoComplete="off" onSubmit={save}
          onChange={() => setSaved(false)}>
          <fieldset disabled={busy} className="llm-fields">
            <div className="option-grid">
              <label>模型服务
                <select value={provider} onChange={(event) => setProvider(event.target.value as LlmOptions['provider'])}>
                  <option value="mock">Mock</option>
                  <option value="openai">OpenAI-compatible</option>
                </select>
              </label>
              <label className="check">
                <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> 启用 LLM
              </label>
            </div>
            <fieldset className="llm-fields" hidden={provider !== 'openai'} disabled={provider !== 'openai'}>
              <div className="option-grid">
                <label>服务地址
                  <input type="url" name="baseUrl" defaultValue={config.baseUrl} maxLength={2048}
                    placeholder="https://example.com/v1" required={enabled && provider === 'openai'} />
                </label>
                <label>模型名称
                  <input name="model" defaultValue={config.model} maxLength={300} required={enabled && provider === 'openai'} />
                </label>
                <label>API key
                  <input type="password" name="apiKey" placeholder={config.apiKey} autoComplete="new-password"
                    aria-describedby="llm-key-help" maxLength={4096} disabled={clearKey} />
                </label>
                {config.apiKey && (
                  <label className="check">
                    <input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} /> 清除已保存的 API key
                  </label>
                )}
              </div>
              <p id="llm-key-help" className="hint">留空保留当前服务地址的密钥。更换地址时可填写新地址的密钥。</p>
              <details>
                <summary>调用参数</summary>
                <div className="option-grid">
                  <label>超时（秒）
                    <input type="number" name="timeoutSeconds" min={1} max={86400} defaultValue={config.timeoutSeconds} required />
                  </label>
                  <label>最大修复重试次数
                    <input type="number" name="maxRetries" min={0} max={10} defaultValue={config.maxRetries} required />
                  </label>
                  <label>推理力度
                    <input name="reasoningEffort" placeholder="由服务决定" defaultValue={config.reasoningEffort} maxLength={40} />
                  </label>
                  <label className="check">
                    <input type="checkbox" name="privateEndpoint" defaultChecked={config.privateEndpoint} /> 可信私有端点
                  </label>
                </div>
              </details>
            </fieldset>
          </fieldset>
          <div className="toolbar">
            <button className="primary" type="submit" disabled={busy}>{busy ? '正在保存…' : '保存并生效'}</button>
            <button type="button" disabled={busy} onClick={() => void load()}>重新加载</button>
          </div>
        </form>
      ) : busy ? <p role="status">正在加载…</p> : <button onClick={() => void load()}>重新加载</button>}
    </section>
  );
}
