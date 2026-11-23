/** Thin API client for the requestId/data envelope (docs/04 section 1). */

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: unknown,
    public status?: number,
  ) {
    super(message);
  }
}

interface Envelope<T = Record<string, unknown>> {
  requestId: string;
  data?: T;
  error?: { code: string; message: string; details?: unknown };
}

async function request<T = any>(path: string, init?: RequestInit): Promise<{ data: T; requestId: string }> {
  let resp: Response;
  try {
    resp = await fetch(path, init);
  } catch (err) {
    throw new ApiError('NETWORK_ERROR', `无法连接服务端：${String(err)}`);
  }
  let body: Envelope;
  try {
    body = await resp.json();
  } catch {
    throw new ApiError('BAD_RESPONSE', `HTTP ${resp.status}（响应不是 JSON）`, undefined, resp.status);
  }
  if (!resp.ok || body.error) {
    const err = body.error ?? { code: 'HTTP_ERROR', message: `HTTP ${resp.status}` };
    throw new ApiError(err.code, err.message, err.details, resp.status);
  }
  return { data: body.data as T, requestId: body.requestId };
}

export const api = {
  health: () => request('/api/v1/health'),
  listDiagrams: () => request('/api/v1/diagrams'),
  getDiagram: (id: string) => request(`/api/v1/diagrams/${encodeURIComponent(id)}`),
  listVersions: (id: string) => request(`/api/v1/diagrams/${encodeURIComponent(id)}/versions`),
  createDiagram: (graph: unknown) =>
    request('/api/v1/diagrams', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(graph),
    }),
  parseText: (text: string, diagramType: string) =>
    request('/api/v1/diagrams/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, diagramType }),
    }),
  validateGraph: (graph: unknown) =>
    request('/api/v1/diagrams/-/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ graph }),
    }),
  layoutDiagram: (id: string, baseVersion: number) =>
    request(`/api/v1/diagrams/${encodeURIComponent(id)}/layout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ baseVersion }),
    }),
  importPreview: (id: string, file: File, baseVersion: number) => {
    const form = new FormData();
    form.append('file', file);
    form.append('baseVersion', String(baseVersion));
    return request(`/api/v1/diagrams/${encodeURIComponent(id)}/import/drawio`, { method: 'POST', body: form });
  },
  importCommit: (id: string, token: string, baseVersion: number) =>
    request(`/api/v1/diagrams/${encodeURIComponent(id)}/import/commit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmationToken: token, baseVersion }),
    }),
  patchPreview: (id: string, body: { instruction?: string; patch?: unknown }) =>
    request(`/api/v1/diagrams/${encodeURIComponent(id)}/patch/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  patchApply: (id: string, token: string, baseVersion: number) =>
    request(`/api/v1/diagrams/${encodeURIComponent(id)}/patch/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmationToken: token, baseVersion }),
    }),
  rollback: (id: string, targetVersion: number, baseVersion: number) =>
    request(`/api/v1/diagrams/${encodeURIComponent(id)}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ targetVersion, baseVersion }),
    }),
  exportUrl: (id: string, version?: number) =>
    `/api/v1/diagrams/${encodeURIComponent(id)}/export/drawio${version ? `?version=${version}` : ''}`,
};
