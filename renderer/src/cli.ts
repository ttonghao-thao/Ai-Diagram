#!/usr/bin/env node
/**
 * Phase 0 renderer CLI (docs/03 section 8):
 *   ai-diagram-renderer generate --input <graph.json> --output <file.drawio>
 *   ai-diagram-renderer validate  --input <file.drawio>
 *
 * Exit codes: 0 = success, 1 = validation/content errors, 2 = usage/IO/internal errors.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import path from 'node:path';
import { GraphValidationError, RenderError, type ValidationIssue } from './errors.js';
import { layoutGraph } from './layout/elkLayout.js';
import { serializeDrawio } from './drawio/xmlWriter.js';
import { parseDrawioXml, validateStructure } from './drawio/xmlReader.js';
import { loadCustomIcons } from './shapes/iconRegistry.js';
import { validateGraph } from './validate.js';

function printIssues(issues: ValidationIssue[]): void {
  for (const i of issues) {
    const ids = i.relatedIds.length ? ` [ids: ${i.relatedIds.join(', ')}]` : '';
    console.error(`ERROR ${i.code}: ${i.message}${ids}`);
  }
}

function readJsonFile(file: string): unknown {
  const text = readFileSync(file, 'utf8');
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new RenderError('SCHEMA_INVALID', `${file} is not valid JSON: ${err instanceof Error ? err.message : String(err)}`);
  }
}

function argValue(args: string[], flag: string, command: string): string {
  const idx = args.indexOf(flag);
  if (idx < 0 || idx + 1 >= args.length) {
    throw new RenderError('USAGE', `${command} requires ${flag} <path>`);
  }
  return args[idx + 1];
}

function optionalArgValue(args: string[], flag: string): string | undefined {
  const idx = args.indexOf(flag);
  if (idx < 0) return undefined;
  if (idx + 1 >= args.length) {
    throw new RenderError('USAGE', `${flag} requires a directory path`);
  }
  return args[idx + 1];
}

async function cmdGenerate(args: string[]): Promise<number> {
  const input = argValue(args, '--input', 'generate');
  const output = argValue(args, '--output', 'generate');
  const iconsDir = optionalArgValue(args, '--icons-dir') ??
    path.resolve(__dirname, '..', '..', 'assets', 'icons');
  const customIcons = existsSync(iconsDir) ? loadCustomIcons(iconsDir) : new Map();
  const started = Date.now();
  const raw = readJsonFile(input);
  const { doc, warnings } = validateGraph(raw);
  const layout = await layoutGraph(doc);
  const xml = serializeDrawio(doc, layout, { customIcons });
  mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
  writeFileSync(output, xml, 'utf8');
  const vertexCount = layout.geometries.size;
  const edges = doc.edges.length;
  const ms = Date.now() - started;
  for (const w of warnings) {
    console.error(`WARNING ${w.code}: ${w.message}`);
  }
  const iconNote = customIcons.size ? `, ${customIcons.size} custom icon(s)` : '';
  console.log(
    `OK generated ${output} (diagram "${doc.name}"): ${vertexCount} cells, ${edges} edges, page ${layout.pageWidth}x${layout.pageHeight}, ${ms}ms${iconNote}`,
  );
  return 0;
}

function cmdValidate(args: string[]): number {
  const input = argValue(args, '--input', 'validate');
  const xml = readFileSync(input, 'utf8');
  const parsed = parseDrawioXml(xml);
  const issues = validateStructure(parsed);
  if (issues.length) {
    printIssues(issues);
    return 1;
  }
  const vertices = parsed.cells.filter((c) => c.vertex).length;
  const edges = parsed.cells.filter((c) => c.edge).length;
  const groups = parsed.cells.filter((c) => c.vertex && c.id.startsWith('g_')).length;
  console.log(
    `OK ${input}: ${parsed.cells.length} cells (${vertices} vertices incl. ${groups} groups, ${edges} edges), page ${parsed.pageWidth}x${parsed.pageHeight}, name "${parsed.pageName ?? ''}"`,
  );
  return 0;
}

function printUsage(): void {
  console.log(`Usage: node dist/src/cli.js <command> [options]

Commands:
  generate --input <graph.json> --output <file.drawio> [--icons-dir <dir>]   Validate graph, run ELK layout, write draw.io XML
  validate  --input <file.drawio>                                            Structural validation of an uncompressed draw.io file

Options:
  --icons-dir <dir>   Local directory of custom SVG icons (<kind>.svg / <deviceType>.svg),
                      embedded as base64 data URIs (no online loading). Default: assets/icons.

Exit codes: 0 success, 1 validation/content errors, 2 usage/IO errors.`);
}

async function main(argv: string[]): Promise<number> {
  const [command, ...rest] = argv;
  if (command === 'generate') {
    return await cmdGenerate(rest);
  }
  if (command === 'validate') {
    return cmdValidate(rest);
  }
  printUsage();
  return command === undefined ? 0 : 2;
}

main(process.argv.slice(2)).then(
  (code) => process.exit(code),
  (err: unknown) => {
    if (err instanceof GraphValidationError) {
      printIssues(err.issues);
      process.exit(1);
      return;
    }
    if (err instanceof RenderError) {
      console.error(`ERROR ${err.code}: ${err.message}`);
      process.exit(err.code === 'USAGE' ? 2 : 1);
      return;
    }
    console.error('ERROR INTERNAL:', err instanceof Error ? err.stack : String(err));
    process.exit(2);
  },
);
