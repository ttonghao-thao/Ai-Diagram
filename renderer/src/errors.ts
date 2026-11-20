import type { Point } from './types.js';

export type IssueSeverity = 'error' | 'warning';

export interface ValidationIssue {
  code: string;
  message: string;
  relatedIds: string[];
  severity: IssueSeverity;
}

/** Error codes aligned with docs/04 section 3; additional Phase 0 codes are documented. */
export const ErrorCodes = {
  SCHEMA_INVALID: 'SCHEMA_INVALID',
  GRAPH_DUPLICATE_ID: 'GRAPH_DUPLICATE_ID',
  GRAPH_INVALID_REFERENCE: 'GRAPH_INVALID_REFERENCE',
  GRAPH_GROUP_CYCLE: 'GRAPH_GROUP_CYCLE',
  GRAPH_LAYOUT_FAILED: 'GRAPH_LAYOUT_FAILED',
  DRAWIO_PARSE_FAILED: 'DRAWIO_PARSE_FAILED',
  DRAWIO_UNSUPPORTED_CONTENT: 'DRAWIO_UNSUPPORTED_CONTENT',
  /** Phase 0 addition: physical edges must not imply a data direction (docs/02, docs/05 0.2). */
  GRAPH_PHYSICAL_EDGE_DIRECTION: 'GRAPH_PHYSICAL_EDGE_DIRECTION',
} as const;

export function issue(
  code: string,
  message: string,
  relatedIds: string[] = [],
  severity: IssueSeverity = 'error',
): ValidationIssue {
  return { code, message, relatedIds, severity };
}

export class GraphValidationError extends Error {
  public readonly issues: ValidationIssue[];

  constructor(issues: ValidationIssue[]) {
    super(
      'Graph validation failed:\n' +
        issues.map((i) => `  [${i.code}] ${i.message}${i.relatedIds.length ? ` (ids: ${i.relatedIds.join(', ')})` : ''}`).join('\n'),
    );
    this.name = 'GraphValidationError';
    this.issues = issues;
  }
}

export class RenderError extends Error {
  public readonly code: string;

  constructor(code: string, message: string) {
    super(`${code}: ${message}`);
    this.name = 'RenderError';
    this.code = code;
  }
}

export function isPoint(value: unknown): value is Point {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Point).x === 'number' &&
    typeof (value as Point).y === 'number'
  );
}
