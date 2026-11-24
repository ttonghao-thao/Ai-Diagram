import { XMLParser, XMLValidator } from 'fast-xml-parser';
import { RenderError } from '../errors.js';

const parser = new XMLParser({ ignoreAttributes: false, processEntities: false });
const svgElements = new Set([
  'svg', 'g', 'defs', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
  'text', 'tspan', 'title', 'desc', 'clipPath', 'mask', 'linearGradient', 'radialGradient',
  'stop', 'pattern', 'symbol', 'use', 'marker',
]);

export function inspectSvg(raw: string): { width: number; height: number } {
  function reject(message: string): never {
    throw new RenderError('DRAWIO_UNSUPPORTED_CONTENT', message);
  }
  if (Buffer.byteLength(raw) > 64 * 1024) reject('SVG exceeds the 65536-byte limit');
  if (/<!DOCTYPE|<!ENTITY|<\?|<script\b|javascript:/i.test(raw.replace(/^\s*<\?xml[^>]*\?>/i, ''))) {
    reject('SVG contains executable content or an XML directive');
  }
  if (XMLValidator.validate(raw) !== true) reject('custom icon is not an SVG document');
  const parsed = parser.parse(raw) as Record<string, unknown>;
  if (!Object.hasOwn(parsed, 'svg')) reject('custom icon is not an SVG document');
  function walk(element: unknown, depth: number): void {
    if (depth > 64) reject('SVG nesting exceeds the limit');
    if (Array.isArray(element)) {
      element.forEach((item) => walk(item, depth + 1));
      return;
    }
    if (typeof element !== 'object' || element === null) return;
    for (const [key, value] of Object.entries(element)) {
      if (key === '#text') continue;
      if (!key.startsWith('@_')) {
        if (!svgElements.has(key)) reject('SVG contains an unsupported element');
        walk(value, depth + 1);
        continue;
      }
      const attr = key.slice(2).toLowerCase();
      const text = String(value);
      if (attr === 'xmlns' || attr === 'xmlns:xlink') continue;
      if (attr.startsWith('on') || attr === 'style' || attr === 'xml:base' || attr === 'src' ||
          (attr.endsWith('href') && !/^#[\w.-]+$/.test(text)) ||
          /(?:https?:|data:|file:|javascript:|&[#a-z]|url\s*\((?!#[\w.-]+\s*\)))/i.test(text)) {
        reject('SVG contains executable content or an external reference');
      }
    }
  }
  walk(parsed.svg, 0);
  const root = parsed.svg as Record<string, unknown>;
  const viewBox = String(root?.['@_viewBox'] ?? '').trim().split(/[\s,]+/).map(Number);
  const dimension = (value: unknown) => /^(?:\d+(?:\.\d+)?|\.\d+)(?:px)?$/.test(String(value)) ? parseFloat(String(value)) : 0;
  const width = viewBox.length === 4 ? viewBox[2] : dimension(root?.['@_width']);
  const height = viewBox.length === 4 ? viewBox[3] : dimension(root?.['@_height']);
  return width > 0 && height > 0 && Number.isFinite(width / height) ? { width, height } : { width: 100, height: 80 };
}
