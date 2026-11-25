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

export interface Quality {
  ok: boolean;
  counts: { nodes: number; edges: number; matchedShapes: number; warnings: number; errors: number };
  issues: { code: string; message: string; relatedIds: string[]; severity: string }[];
  truncated: boolean;
}
export interface Theme {
  id: string;
  name: string;
  iconLibrary: string;
  edge: { routing: string; labelPolicy: string; arrowPolicy: string };
  layout: { nodeSpacing: number; layerSpacing: number };
}
export interface Material {
  id: string; name: string; nameZh?: string; library: string; category: string;
  assetType: 'svg' | 'stencil' | 'cell_template';
  defaultWidth: number; defaultHeight: number; favorite: boolean; usable?: boolean;
  verified: boolean; style?: string; thumbnail?: boolean;
}
export interface ShapePreferences {
  mappings: Record<string, string>;
  favorites: string[];
  deviceTypes: string[];
}

export interface LlmOptions {
  enabled: boolean;
  provider: 'mock' | 'openai';
  baseUrl: string;
  model: string;
  timeoutSeconds: number;
  maxRetries: number;
  reasoningEffort: string;
  privateEndpoint: boolean;
}

export interface LlmSettings extends LlmOptions {
  version: number;
  apiKey: '' | '****';
}

export type LlmSettingsChanges = Partial<LlmOptions> & { baseVersion: number; apiKey?: string | null };

function jsonRequest<T = any>(path: string, method: string, payload: unknown) {
  return request<T>(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
}

export const api = {
  health: () => request('/api/v1/health'),
  llmSettings: () => request<LlmSettings>('/api/v1/settings/llm', { cache: 'no-store' }),
  updateLlmSettings: (changes: LlmSettingsChanges) =>
    jsonRequest<LlmSettings>('/api/v1/settings/llm', 'PATCH', changes),
  listDiagrams: () => request('/api/v1/diagrams'),
  getDiagram: (id: string) => request(`/api/v1/diagrams/${encodeURIComponent(id)}`),
  listVersions: (id: string) => request(`/api/v1/diagrams/${encodeURIComponent(id)}/versions`),
  createDiagram: (graph: unknown) =>
    request('/api/v1/diagrams', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(graph),
    }),
  parseText: (text: string, diagramType: string, options: Record<string, unknown> = {}) =>
    request('/api/v1/diagrams/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, diagramType, ...options }),
    }),
  validateGraph: (graph: unknown) =>
    request('/api/v1/diagrams/-/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ graph }),
    }),
  layoutDiagram: (id: string, baseVersion: number, options: Record<string, unknown> = {}) =>
    request(`/api/v1/diagrams/${encodeURIComponent(id)}/layout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ baseVersion, ...options }),
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
  quality: (id: string, version?: number) =>
    jsonRequest<{ version: number; quality: Quality }>(`/api/v1/diagrams/${encodeURIComponent(id)}/quality`, 'POST', { version }),
  themes: () => request<{ themes: Theme[] }>('/api/v1/themes'),
  searchShapes: (parameters: URLSearchParams) =>
    request<{ items: Material[]; total: number; catalogVersion: string }>(`/api/v1/shapes/search?${parameters}`),
  shape: (id: string) => request<Material>(`/api/v1/shapes/${encodeURIComponent(id)}`),
  shapeThumbnail: (id: string) => `/api/v1/shapes/${encodeURIComponent(id)}/thumbnail`,
  shapePreview: (id: string) => `/api/v1/shapes/${encodeURIComponent(id)}/preview`,
  preferences: () => request<ShapePreferences>('/api/v1/preferences/shapes'),
  updatePreferences: (changes: Partial<ShapePreferences>) =>
    jsonRequest<ShapePreferences>('/api/v1/preferences/shapes', 'PUT', changes),
  importMaterial: (form: FormData) => request<{ items: Material[] }>('/api/v1/shapes/import', { method: 'POST', body: form }),
  async exportMaterials(ids: string[]) {
    const response = await fetch('/api/v1/shapes/export', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
    });
    if (!response.ok) {
      const { error } = await response.json();
      throw new ApiError(error.code, error.message, error.details, response.status);
    }
    return response.blob();
  },
  exportUrl: (id: string, version?: number) =>
    `/api/v1/diagrams/${encodeURIComponent(id)}/export/drawio${version ? `?version=${version}` : ''}`,
};
