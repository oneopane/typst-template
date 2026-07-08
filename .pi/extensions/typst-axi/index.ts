import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { withFileMutationQueue } from "@earendil-works/pi-coding-agent";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from "node:path";
import { Type } from "@earendil-works/pi-ai";

type TypstFormat = "pdf" | "png" | "svg" | "html";
type QueryView = "project_info" | "structure" | "include_map" | "doctor" | "labels" | "bibliography" | "bib_entries" | "assets" | "asset_references" | "outline" | "macro_catalog" | "template_settings" | "info" | "fonts" | "deps" | "selector";
type NotesAction = "new" | "promote" | "renumber" | "metadata_update";

type RunResult = {
  argv: string[];
  command: string;
  status: number | null;
  signal: string | null;
  stdout: string;
  stderr: string;
  error?: string;
  captureTruncated: boolean;
};

type Diagnostic = { path: string; line: number; column: number; severity: "error" | "warning"; message: string };

type TypstQueryParams = {
  view?: QueryView;
  input?: string;
  selector?: string;
  field?: string;
  one?: boolean;
  target?: "paged" | "html";
  variants?: boolean;
  limit?: number;
  maxChars?: number;
  full?: boolean;
};

type TypstCheckParams = {
  input?: string;
  inputs?: string[];
  format?: TypstFormat;
  creationTimestamp?: string;
  limit?: number;
  maxChars?: number;
  full?: boolean;
};

type TypstBuildParams = {
  input?: string;
  output?: string;
  inputs?: string[];
  format?: TypstFormat;
  dryRun?: boolean;
  confirm?: boolean;
  creationTimestamp?: string;
  maxChars?: number;
  full?: boolean;
};

type TypstNotesParams = {
  action: NotesAction;
  parent?: string;
  slug?: string;
  title?: string;
  section?: boolean;
  path?: string;
  directory?: string;
  recursive?: boolean;
  includeHigh?: boolean;
  titleValue?: string;
  author?: string;
  date?: string;
  dryRun?: boolean;
  confirm?: boolean;
  maxChars?: number;
  full?: boolean;
};

const MaxChars = Type.Optional(Type.Number());
const Limit = Type.Optional(Type.Number());
const Full = Type.Optional(Type.Boolean());
const DryRun = Type.Optional(Type.Boolean());
const Confirm = Type.Optional(Type.Boolean());
const SafePath = Type.String({ description: "Safe relative project path. Absolute paths, ~, and .. are rejected." });
const OptionalSafePath = Type.Optional(SafePath);
const Format = Type.Optional(Type.Union([Type.Literal("pdf"), Type.Literal("png"), Type.Literal("svg"), Type.Literal("html")]));
const QueryViewSchema = Type.Optional(Type.Union([
  Type.Literal("project_info"),
  Type.Literal("structure"),
  Type.Literal("include_map"),
  Type.Literal("doctor"),
  Type.Literal("labels"),
  Type.Literal("bibliography"),
  Type.Literal("bib_entries"),
  Type.Literal("assets"),
  Type.Literal("asset_references"),
  Type.Literal("outline"),
  Type.Literal("macro_catalog"),
  Type.Literal("template_settings"),
  Type.Literal("info"),
  Type.Literal("fonts"),
  Type.Literal("deps"),
  Type.Literal("selector"),
]));
const NotesActionSchema = Type.Union([
  Type.Literal("new"),
  Type.Literal("promote"),
  Type.Literal("renumber"),
  Type.Literal("metadata_update"),
]);

const DEFAULT_MAX_CHARS = 12_000;
const DEFAULT_LIMIT = 50;
const MAX_CAPTURE_CHARS = 1_000_000;
const INCLUDE_RE = /^\s*#include\s+"([^"]+)"\s*$/;
const HEADING_RE = /^(=+)\s+(.+?)\s*$/;

function okText(text: string, details: Record<string, unknown> = {}) {
  return { content: [{ type: "text" as const, text }], details };
}

function formatNextSteps(lines: string[]): string {
  return lines.length ? `\nnext[${lines.length}]:\n${lines.map((line) => `  ${line}`).join("\n")}` : "";
}

function quoteCell(value: unknown): string {
  return `"${String(value ?? "").replaceAll('"', '\\"')}"`;
}

function jsLiteral(value: string | number | boolean): string {
  return typeof value === "string" ? JSON.stringify(value) : String(value);
}

function toolCall(name: string, params: Record<string, string | number | boolean | undefined>): string {
  const body = Object.entries(params)
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => `${key}:${jsLiteral(value as string | number | boolean)}`)
    .join(",");
  return `${name}({${body}})`;
}

function shellQuote(value: string): string {
  if (/^[A-Za-z0-9_./:@%+=,-]+$/.test(value)) return value;
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

function commandString(argv: string[], root: string): string {
  return argv.map((part, index) => {
    const display = index === 0 && part.startsWith(root) ? `.${part.slice(root.length)}` : part;
    return shellQuote(display);
  }).join(" ");
}

function truncateText(text: string, maxChars = DEFAULT_MAX_CHARS, full?: boolean): { text: string; truncated: boolean } {
  if (full || text.length <= maxChars) return { text, truncated: false };
  return {
    text: `${text.slice(0, maxChars)}\n... (truncated, ${text.length} chars total; request full=true or larger maxChars)`,
    truncated: true,
  };
}

function normalizeLimit(value: number | undefined, fallback = DEFAULT_LIMIT): number {
  if (value === undefined) return fallback;
  if (!Number.isFinite(value) || value < 0) throw new Error("limit must be a non-negative finite number.");
  return Math.min(Math.floor(value), 500);
}

function normalizeMaxChars(value: number | undefined, fallback = DEFAULT_MAX_CHARS): number {
  if (value === undefined) return fallback;
  if (!Number.isFinite(value) || value <= 0) throw new Error("maxChars must be a positive finite number.");
  return Math.min(Math.floor(value), 100_000);
}

function indentBlock(text: string): string {
  const value = text.trimEnd() || "(empty)";
  return value.split("\n").map((line) => `  ${line}`).join("\n");
}

function formatRows(name: string, headers: string[], rows: string[]): string {
  return `${name}[${rows.length}]{${headers.join(",")}}:\n${rows.length ? rows.map((row) => `  ${row}`).join("\n") : "  0 results"}`;
}

function formatCommandResult(kind: string, result: RunResult, opts: { maxChars?: number; full?: boolean; next?: string[]; extra?: string[] } = {}) {
  const maxChars = normalizeMaxChars(opts.maxChars);
  const stdout = truncateText(result.stdout, maxChars, opts.full);
  const stderr = truncateText(result.stderr, maxChars, opts.full);
  const truncated = stdout.truncated || stderr.truncated || result.captureTruncated;
  const status = result.error ? "error" : result.status === 0 ? "ok" : "failed";
  const text = [
    `${kind}:`,
    `  status: ${status}`,
    `  command: ${result.command}`,
    `  exit_code: ${result.status ?? "null"}`,
    `  signal: ${result.signal ?? "none"}`,
    `  truncated: ${truncated}`,
    ...(opts.extra ?? []),
    `stdout: |-`,
    indentBlock(stdout.text),
    `stderr: |-`,
    indentBlock(stderr.text),
  ].join("\n") + formatNextSteps(opts.next ?? []);

  return okText(text, {
    kind,
    status,
    command: result.argv,
    exitCode: result.status,
    signal: result.signal,
    stdout: stdout.text,
    stderr: stderr.text,
    truncated,
    error: result.error,
  });
}

function rootFrom(ctx: ExtensionContext | undefined): string {
  return resolve(ctx?.cwd ?? process.cwd());
}

function ensureTemplateRoot(ctx: ExtensionContext | undefined): string {
  const root = rootFrom(ctx);
  const required = ["main.typ", "template.typ", "macros.typ", "src", join("tools", "notes.py")];
  for (const relPath of required) {
    if (!existsSync(join(root, relPath))) throw new Error(`Not a Typst notes template root: missing ${relPath}`);
  }
  return root;
}

function isInside(root: string, target: string): boolean {
  const rel = relative(root, target);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

function safeRelPath(root: string, input: string | undefined, label = "path"): string {
  const raw = input ?? ".";
  if (!raw || raw.includes("\0")) throw new Error(`${label} is empty or invalid.`);
  if (raw.startsWith("~")) throw new Error(`${label} must not start with ~.`);
  if (isAbsolute(raw)) throw new Error(`${label} must be relative.`);
  if (/^[A-Za-z]:[\\/]/.test(raw) || raw.startsWith("\\\\")) throw new Error(`${label} must be a safe relative path.`);
  if (raw.split(/[\\/]+/).some((part) => part === "..")) throw new Error(`${label} must not contain .. segments.`);
  const abs = resolve(root, raw);
  if (!isInside(root, abs)) throw new Error(`${label} escapes the project root.`);
  const rel = relative(root, abs).split("\\").join("/");
  return rel || ".";
}

function requireExistingTypstInput(root: string, input: string | undefined): string {
  const rel = safeRelPath(root, input ?? "main.typ", "input");
  if (!rel.endsWith(".typ")) throw new Error("input must be a .typ file.");
  const abs = join(root, rel);
  if (!existsSync(abs) || !statSync(abs).isFile()) throw new Error(`input does not exist: ${rel}`);
  return rel;
}

function requireOutPath(root: string, output: string | undefined, format: TypstFormat): string {
  const fallback = format === "pdf" ? "out/main.pdf" : `out/main.${format}`;
  const rel = safeRelPath(root, output ?? fallback, "output");
  if (rel === "out" || !rel.startsWith("out/")) throw new Error("output must be under out/.");
  return rel;
}

function requireSrcPath(root: string, input: string | undefined, label = "path"): string {
  const rel = safeRelPath(root, input, label);
  if (rel !== "src" && !rel.startsWith("src/")) throw new Error(`${label} must be under src/.`);
  return rel;
}

function requireDryRunOrConfirm(tool: string, p: { dryRun?: boolean; confirm?: boolean }) {
  if (!p.dryRun && !p.confirm) throw new Error(`${tool} requires confirm:true unless dryRun:true.`);
}

function validateSlug(raw: string | undefined, section?: boolean): { slug: string; isSection: boolean } {
  if (!raw) throw new Error("slug is required.");
  const isSection = Boolean(section) || raw.endsWith("/");
  const slug = raw.replace(/\.typ$/, "").replace(/\/+$/, "");
  if (!slug || slug.includes("/") || slug.includes("\\") || slug === ".") throw new Error("slug must be one path segment.");
  if (!/^[0-9]{2}_[A-Za-z0-9][A-Za-z0-9_-]*$/.test(slug)) throw new Error("slug must start with a two-digit numeric prefix, e.g. 02_topic.");
  return { slug, isSection };
}

function typstInputArgs(rawInputs: string[] | undefined): string[] {
  const values = new Map<string, string>();
  for (const raw of rawInputs ?? []) {
    const index = raw.indexOf("=");
    if (index <= 0) throw new Error("inputs must use KEY=VALUE syntax.");
    const key = raw.slice(0, index).trim();
    const value = raw.slice(index + 1);
    if (!/^[A-Za-z_][A-Za-z0-9_-]*$/.test(key)) throw new Error(`Invalid Typst input key: ${key}`);
    values.set(key, value);
  }
  return [...values.entries()].flatMap(([key, value]) => ["--input", `${key}=${value}`]);
}

function typstArgsBase(format: TypstFormat, creationTimestamp?: string, inputs?: string[]): string[] {
  const args = ["--color", "never", "compile", "--diagnostic-format", "short", "-f", format, ...typstInputArgs(inputs)];
  if (format === "html") args.push("--features", "html");
  if (creationTimestamp) args.push("--creation-timestamp", creationTimestamp);
  return args;
}

function tempOutputFor(format: TypstFormat): { dir: string; output: string } {
  const dir = mkdtempSync(join(tmpdir(), "typst-axi-"));
  const ext = format === "html" ? "html" : format;
  const name = format === "png" || format === "svg" ? `main-{p}.${ext}` : `main.${ext}`;
  return { dir, output: join(dir, name) };
}

function parseDiagnostics(text: string): Diagnostic[] {
  const rows: Diagnostic[] = [];
  for (const line of text.split("\n")) {
    const match = /^(.+?):(\d+):(\d+):\s+(error|warning):\s+(.+)$/.exec(line.trim());
    if (!match) continue;
    rows.push({ path: match[1], line: Number(match[2]), column: Number(match[3]), severity: match[4] as "error" | "warning", message: match[5] });
  }
  return rows;
}

async function runCommand(root: string, argv: string[], signal?: AbortSignal, timeoutMs = 120_000): Promise<RunResult> {
  return await new Promise((resolvePromise) => {
    const child = spawn(argv[0], argv.slice(1), { cwd: root, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, NO_COLOR: "1" } });
    let stdout = "";
    let stderr = "";
    let captureTruncated = false;
    const append = (kind: "stdout" | "stderr", chunk: unknown) => {
      const text = String(chunk);
      if (kind === "stdout") {
        if (stdout.length < MAX_CAPTURE_CHARS) stdout += text.slice(0, MAX_CAPTURE_CHARS - stdout.length);
      } else if (stderr.length < MAX_CAPTURE_CHARS) {
        stderr += text.slice(0, MAX_CAPTURE_CHARS - stderr.length);
      }
      if (stdout.length >= MAX_CAPTURE_CHARS || stderr.length >= MAX_CAPTURE_CHARS) captureTruncated = true;
    };
    const timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs);
    const abort = () => child.kill("SIGTERM");
    signal?.addEventListener("abort", abort, { once: true });
    child.stdout?.on("data", (chunk) => append("stdout", chunk));
    child.stderr?.on("data", (chunk) => append("stderr", chunk));
    child.on("error", (error) => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      resolvePromise({ argv, command: commandString(argv, root), status: null, signal: null, stdout, stderr, error: error.message, captureTruncated });
    });
    child.on("close", (code, sig) => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      const error = signal?.aborted ? "Operation aborted." : undefined;
      resolvePromise({ argv, command: commandString(argv, root), status: code, signal: sig, stdout, stderr, error, captureTruncated });
    });
  });
}

async function runNotes(root: string, args: string[], signal?: AbortSignal, timeoutMs = 120_000): Promise<RunResult> {
  return await runCommand(root, [join(root, "tools", "notes.py"), ...args], signal, timeoutMs);
}

function parseJsonOutput(result: RunResult): unknown {
  const text = result.stdout.trim();
  if (!text) throw new Error(`Expected JSON from ${result.command}, but stdout was empty.`);
  try {
    return JSON.parse(text) as unknown;
  } catch (error) {
    throw new Error(`Could not parse JSON from ${result.command}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

async function runNotesJson(root: string, args: string[], signal?: AbortSignal, timeoutMs = 120_000): Promise<{ result: RunResult; data: unknown }> {
  const result = await runNotes(root, [...args, "--json"], signal, timeoutMs);
  const data = parseJsonOutput(result);
  return { result, data };
}

function formatJsonCommandResult(kind: string, result: RunResult, data: unknown, opts: { maxChars?: number; full?: boolean; next?: string[]; extra?: string[] } = {}) {
  const maxChars = normalizeMaxChars(opts.maxChars);
  const pretty = JSON.stringify(data, null, 2) ?? "null";
  const jsonText = truncateText(pretty, maxChars, opts.full);
  const stderr = truncateText(result.stderr, maxChars, opts.full);
  const status = result.error ? "error" : result.status === 0 ? "ok" : "failed";
  const text = [
    `${kind}:`,
    `  status: ${status}`,
    `  command: ${result.command}`,
    `  exit_code: ${result.status ?? "null"}`,
    `  truncated: ${jsonText.truncated || stderr.truncated || result.captureTruncated}`,
    ...(opts.extra ?? []),
    `json: |-`,
    indentBlock(jsonText.text),
    ...(stderr.text.trim() ? [`stderr: |-`, indentBlock(stderr.text)] : []),
  ].join("\n") + formatNextSteps(opts.next ?? []);
  return okText(text, { kind, status, command: result.argv, exitCode: result.status, data, stderr: stderr.text, truncated: jsonText.truncated || stderr.truncated || result.captureTruncated, error: result.error });
}

function includesIn(path: string): string[] {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8").split("\n").flatMap((line) => {
    const match = INCLUDE_RE.exec(line);
    return match ? [match[1]] : [];
  });
}

function resolveInclude(root: string, entrypoint: string, include: string): string {
  return resolve(entrypoint === join(root, "main.typ") ? root : dirname(entrypoint), include);
}

function includedTypstFiles(root: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  function walk(entrypoint: string) {
    if (seen.has(entrypoint)) return;
    seen.add(entrypoint);
    for (const include of includesIn(entrypoint)) {
      const target = resolveInclude(root, entrypoint, include);
      out.push(target);
      if (basename(target) === "index.typ") walk(target);
    }
  }
  walk(join(root, "main.typ"));
  return out.filter((path) => existsSync(path) && statSync(path).isFile());
}

function rel(root: string, abs: string): string {
  return relative(root, abs).split("\\").join("/") || ".";
}

function formatDiagnostics(kind: string, result: RunResult, diagnostics: Diagnostic[], p: { limit?: number; maxChars?: number; full?: boolean }, next: string[]) {
  const limit = normalizeLimit(p.limit);
  const maxChars = normalizeMaxChars(p.maxChars);
  const stdout = truncateText(result.stdout, maxChars, p.full);
  const stderr = truncateText(result.stderr, maxChars, p.full);
  const rows = diagnostics.slice(0, limit).map((d) => `${d.severity},${d.path},${d.line},${d.column},${quoteCell(d.message)}`);
  const truncated = stdout.truncated || stderr.truncated || result.captureTruncated || diagnostics.length > rows.length;
  const status = result.error ? "error" : result.status === 0 ? "ok" : "failed";
  const text = [
    `${kind}:`,
    `  status: ${status}`,
    `  command: ${result.command}`,
    `  exit_code: ${result.status ?? "null"}`,
    `  diagnostics: ${diagnostics.length}`,
    `  truncated: ${truncated}`,
    formatRows("diagnostics", ["severity", "path", "line", "column", "message"], rows),
    ...(stdout.text.trim() ? [`stdout: |-`, indentBlock(stdout.text)] : []),
    ...(stderr.text.trim() ? [`stderr: |-`, indentBlock(stderr.text)] : []),
  ].join("\n") + formatNextSteps(next);
  return okText(text, { kind, status, command: result.argv, exitCode: result.status, diagnostics, stdout: stdout.text, stderr: stderr.text, truncated, error: result.error });
}

async function typstCompileTo(root: string, input: string, output: string, format: TypstFormat, creationTimestamp: string | undefined, inputs: string[] | undefined, signal?: AbortSignal): Promise<RunResult> {
  const argv = ["typst", ...typstArgsBase(format, creationTimestamp, inputs), "--root", root, input, output];
  return await runCommand(root, argv, signal);
}

async function runTypstCheck(root: string, p: TypstCheckParams, signal?: AbortSignal) {
  const input = requireExistingTypstInput(root, p.input);
  const format = p.format ?? "pdf";
  const temp = tempOutputFor(format);
  try {
    const result = await typstCompileTo(root, input, temp.output, format, p.creationTimestamp, p.inputs, signal);
    const diagnostics = parseDiagnostics(`${result.stdout}\n${result.stderr}`);
    return formatDiagnostics("typst_check", result, diagnostics, p, [`typst_query({view:"outline"})`, `typst_build({dryRun:true})`]);
  } finally {
    rmSync(temp.dir, { recursive: true, force: true });
  }
}

function formatPlan(kind: string, rows: Array<[string, string]>, next: string[], details: Record<string, unknown>) {
  const textRows = rows.map(([item, value]) => `${item},${quoteCell(value)}`);
  const text = [`${kind}:`, `  status: planned`, formatRows("plan", ["item", "value"], textRows)].join("\n") + formatNextSteps(next);
  return okText(text, { kind, status: "planned", ...details });
}

async function runTypstBuild(root: string, p: TypstBuildParams, signal?: AbortSignal) {
  const input = requireExistingTypstInput(root, p.input);
  const format = p.format ?? (p.output ? (extname(p.output).replace(/^\./, "") as TypstFormat || "pdf") : "pdf");
  if (!["pdf", "png", "svg", "html"].includes(format)) throw new Error("format must be pdf, png, svg, or html.");
  const output = requireOutPath(root, p.output, format);

  if (!p.dryRun && !p.confirm) {
    return formatPlan("typst_build", [["input", input], ["output", output], ["format", format], ["requires", "confirm:true or dryRun:true"]], [`typst_build({input:"${input}",output:"${output}",dryRun:true})`, `typst_build({input:"${input}",output:"${output}",confirm:true})`], { input, output, format, wouldWrite: output });
  }

  if (p.dryRun) {
    const temp = tempOutputFor(format);
    try {
      const result = await typstCompileTo(root, input, temp.output, format, p.creationTimestamp, p.inputs, signal);
      const diagnostics = parseDiagnostics(`${result.stdout}\n${result.stderr}`);
      return formatDiagnostics("typst_build", result, diagnostics, p, [`typst_build({input:"${input}",output:"${output}",confirm:true})`]);
    } finally {
      rmSync(temp.dir, { recursive: true, force: true });
    }
  }

  const outputAbs = join(root, output);
  return await withFileMutationQueue(outputAbs, async () => {
    mkdirSync(dirname(outputAbs), { recursive: true });
    const result = await typstCompileTo(root, input, output, format, p.creationTimestamp, p.inputs, signal);
    const diagnostics = parseDiagnostics(`${result.stdout}\n${result.stderr}`);
    return formatDiagnostics("typst_build", result, diagnostics, p, [`typst_query({view:"doctor"})`, `typst_query({view:"deps"})`]);
  });
}

function formatProjectInfo(root: string) {
  const paths = ["main.typ", "notes.toml", "template.typ", "macros.typ", "refs.bib", "justfile", "tools/notes.py", "src", "assets/figures", "assets/images", "out"];
  const rows = paths.map((path) => {
    const abs = join(root, path);
    const exists = existsSync(abs);
    const type = exists ? (statSync(abs).isDirectory() ? "dir" : "file") : "missing";
    return `${path},${type}`;
  });
  const version = spawnVersion(root);
  const text = [
    `typst_query:`,
    `  view: project_info`,
    `  root: ${root}`,
    `  typst: ${version}`,
    formatRows("paths", ["path", "type"], rows),
  ].join("\n") + formatNextSteps([`typst_query({view:"include_map"})`, `typst_query({view:"doctor"})`, `typst_check({})`]);
  return okText(text, { kind: "typst_query", view: "project_info", root, typst: version, paths: rows });
}

function spawnVersion(root: string): string {
  try {
    const run = spawnSyncCompat(root, ["typst", "--version"]);
    return (run.stdout || run.stderr).trim() || "unknown";
  } catch {
    return "unknown";
  }
}

function spawnSyncCompat(root: string, argv: string[]): { stdout: string; stderr: string } {
  const proc = spawnSync(argv[0], argv.slice(1), { cwd: root, encoding: "utf8", timeout: 10_000 });
  return { stdout: String(proc.stdout ?? ""), stderr: String(proc.stderr ?? "") };
}

function formatOutline(root: string, p: TypstQueryParams) {
  const limit = normalizeLimit(p.limit);
  const files = includedTypstFiles(root);
  const headings: Array<{ path: string; line: number; level: number; title: string }> = [];
  for (const file of files) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, index) => {
      const match = HEADING_RE.exec(line);
      if (match) headings.push({ path: rel(root, file), line: index + 1, level: match[1].length, title: match[2] });
    });
  }
  const rows = headings.slice(0, limit).map((h) => `${h.path},${h.line},${h.level},${quoteCell(h.title)}`);
  const text = [`typst_query:`, `  view: outline`, `  headings: ${headings.length}`, `  truncated: ${headings.length > rows.length}`, formatRows("headings", ["path", "line", "level", "title"], rows)].join("\n") + formatNextSteps([`typst_query({view:"selector",selector:"heading"})`, `typst_query({view:"macro_catalog"})`]);
  return okText(text, { kind: "typst_query", view: "outline", headings, truncated: headings.length > rows.length });
}

function formatMacroCatalog(root: string, p: TypstQueryParams) {
  const limit = normalizeLimit(p.limit);
  const macrosPath = join(root, "macros.typ");
  const macros: Array<{ name: string; signature: string; line: number }> = [];
  const lines = readFileSync(macrosPath, "utf8").split("\n");
  lines.forEach((line, index) => {
    const match = /^#let\s+([A-Za-z_][A-Za-z0-9_-]*)\s*(\([^=]*\))?\s*=/.exec(line.trim());
    if (match) macros.push({ name: match[1], signature: `${match[1]}${match[2] ?? ""}`, line: index + 1 });
  });
  const rows = macros.slice(0, limit).map((m) => `${m.name},${m.line},${quoteCell(m.signature)}`);
  const text = [`typst_query:`, `  view: macro_catalog`, `  macros: ${macros.length}`, `  truncated: ${macros.length > rows.length}`, formatRows("macros", ["name", "line", "signature"], rows)].join("\n") + formatNextSteps([`typst_query({view:"outline"})`]);
  return okText(text, { kind: "typst_query", view: "macro_catalog", macros, truncated: macros.length > rows.length });
}

function formatTemplateSettings(root: string) {
  const main = readFileSync(join(root, "main.typ"), "utf8");
  const template = readFileSync(join(root, "template.typ"), "utf8");
  const configPath = join(root, "notes.toml");
  const configMetadata = existsSync(configPath)
    ? readFileSync(configPath, "utf8").split("\n").map((line, index) => ({ line: index + 1, text: line.trim() })).filter((line) => line.text && !line.text.startsWith("#"))
    : [];
  const metadataBlock = /#show:\s*notes-template\.with\(([\s\S]*?)\)\s*\n/.exec(main)?.[1] ?? "";
  const metadata = metadataBlock.split("\n").map((line) => line.trim()).filter(Boolean);
  const settings = template.split("\n").map((line, index) => ({ line: index + 1, text: line.trim() })).filter((line) => line.text.startsWith("set ") || line.text.startsWith("show heading") || line.text.startsWith("outline("));
  const rows = [
    ...configMetadata.map((line) => `notes.toml,line ${line.line},${quoteCell(line.text)}`),
    ...metadata.map((line) => `main.typ,metadata,${quoteCell(line)}`),
    ...settings.map((line) => `template.typ,line ${line.line},${quoteCell(line.text)}`),
  ];
  const text = [`typst_query:`, `  view: template_settings`, formatRows("settings", ["path", "kind", "value"], rows)].join("\n") + formatNextSteps([`typst_notes({action:"metadata_update",titleValue:"<title>",dryRun:true})`]);
  return okText(text, { kind: "typst_query", view: "template_settings", configMetadata, metadata, settings });
}

async function runTypstQuery(root: string, p: TypstQueryParams, signal?: AbortSignal) {
  const view = p.view ?? "project_info";
  if (view === "project_info") return formatProjectInfo(root);
  if (view === "outline") return formatOutline(root, p);
  if (view === "macro_catalog") return formatMacroCatalog(root, p);
  if (view === "template_settings") return formatTemplateSettings(root);

  if (view === "structure" || view === "include_map" || view === "doctor" || view === "labels" || view === "bibliography" || view === "bib_entries" || view === "assets" || view === "asset_references") {
    const command = view === "structure" ? "structure" : view === "include_map" ? "map" : view === "bibliography" || view === "bib_entries" ? "bib" : view === "asset_references" ? "assets" : view;
    const { result, data } = await runNotesJson(root, [command], signal);
    return formatJsonCommandResult("typst_query", result, data, { maxChars: p.maxChars, full: p.full, extra: [`  view: ${view}`], next: view === "doctor" ? [`typst_check({})`] : [`typst_query({view:"doctor"})`] });
  }

  if (view === "info") {
    const result = await runCommand(root, ["typst", "--color", "never", "info", "--format", "json", "--pretty"], signal);
    return formatCommandResult("typst_query", result, { maxChars: p.maxChars, full: p.full, extra: [`  view: info`], next: [`typst_query({view:"fonts"})`] });
  }

  if (view === "fonts") {
    const args = ["typst", "--color", "never", "fonts"];
    if (p.variants) args.push("--variants");
    const result = await runCommand(root, args, signal);
    return formatCommandResult("typst_query", result, { maxChars: p.maxChars, full: p.full, extra: [`  view: fonts`], next: [`typst_query({view:"info"})`] });
  }

  if (view === "deps") {
    const input = requireExistingTypstInput(root, p.input);
    const temp = tempOutputFor("pdf");
    const deps = join(temp.dir, "deps.json");
    try {
      const result = await runCommand(root, ["typst", "--color", "never", "compile", "--diagnostic-format", "short", "--root", root, "--deps", deps, "--deps-format", "json", input, temp.output], signal);
      const depsText = existsSync(deps) ? readFileSync(deps, "utf8") : "";
      const augmented: RunResult = { ...result, stdout: depsText || result.stdout };
      return formatCommandResult("typst_query", augmented, { maxChars: p.maxChars, full: p.full, extra: [`  view: deps`, `  input: ${input}`], next: [`typst_query({view:"outline"})`] });
    } finally {
      rmSync(temp.dir, { recursive: true, force: true });
    }
  }

  if (view === "selector") {
    const input = requireExistingTypstInput(root, p.input);
    const selector = (p.selector ?? "").trim();
    if (!selector) throw new Error('selector is required when view is "selector".');
    if (selector.length > 200 || selector.includes("\0")) throw new Error("selector is too long or invalid.");
    const args = ["typst", "--color", "never", "query", "--root", root, "--format", "json", "--pretty"];
    if (p.target) args.push("--target", p.target);
    if (p.field) args.push("--field", p.field);
    if (p.one) args.push("--one");
    args.push(input, selector);
    const result = await runCommand(root, args, signal);
    return formatCommandResult("typst_query", result, { maxChars: p.maxChars, full: p.full, extra: [`  view: selector`, `  selector: ${selector}`], next: [`typst_query({view:"outline"})`] });
  }

  throw new Error(`Unsupported typst_query view: ${view}`);
}

async function runTypstNotes(root: string, p: TypstNotesParams, signal?: AbortSignal) {
  requireDryRunOrConfirm("typst_notes", p);
  const dryRun = Boolean(p.dryRun);
  const action = p.action;
  let args: string[];
  let queuePath = join(root, "main.typ");
  let next = dryRun ? [toolCall("typst_notes", { action, confirm: true })] : [`typst_query({view:"include_map"})`, `typst_query({view:"doctor"})`];

  if (action === "new") {
    const parent = requireSrcPath(root, p.parent ?? "src", "parent");
    const { slug, isSection } = validateSlug(p.slug, p.section);
    args = ["new", parent, isSection ? `${slug}/` : slug];
    if (p.title) args.push(p.title);
    if (dryRun) args.push("--dry-run");
    queuePath = join(root, parent === "src" ? "main.typ" : `${parent}/index.typ`);
    next = dryRun ? [toolCall("typst_notes", { action: "new", parent, slug: `${slug}${isSection ? "/" : ""}`, title: p.title, confirm: true })] : [`typst_query({view:"include_map"})`, `typst_query({view:"doctor"})`];
  } else if (action === "promote") {
    const path = requireSrcPath(root, p.path, "path");
    if (!path.endsWith(".typ") || basename(path) === "index.typ") throw new Error("promote path must be a non-index .typ content file.");
    args = ["promote", path];
    if (dryRun) args.push("--dry-run");
    next = dryRun ? [toolCall("typst_notes", { action: "promote", path, confirm: true })] : [`typst_query({view:"include_map"})`, `typst_query({view:"doctor"})`];
  } else if (action === "renumber") {
    const directory = requireSrcPath(root, p.directory ?? "src", "directory");
    args = ["renumber", directory];
    if (p.recursive) args.push("--recursive");
    if (p.includeHigh) args.push("--all");
    if (dryRun) args.push("--dry-run");
    next = dryRun ? [toolCall("typst_notes", { action: "renumber", directory, recursive: p.recursive || undefined, includeHigh: p.includeHigh || undefined, confirm: true })] : [`typst_query({view:"include_map"})`, `typst_query({view:"doctor"})`];
  } else if (action === "metadata_update") {
    const changes = [p.titleValue, p.author, p.date].filter((value) => value !== undefined);
    if (!changes.length) throw new Error("metadata_update requires titleValue, author, or date.");
    args = ["metadata"];
    if (p.titleValue !== undefined) args.push("--title", p.titleValue);
    if (p.author !== undefined) args.push("--author", p.author);
    if (p.date !== undefined) args.push("--date", p.date);
    if (dryRun) args.push("--dry-run");
    queuePath = join(root, "notes.toml");
    next = dryRun ? [toolCall("typst_notes", { action: "metadata_update", titleValue: p.titleValue, author: p.author, date: p.date, confirm: true })] : [`typst_query({view:"template_settings"})`, `typst_check({})`];
  } else {
    throw new Error(`Unsupported typst_notes action: ${action}`);
  }

  const run = async () => {
    const { result, data } = await runNotesJson(root, args, signal);
    return formatJsonCommandResult("typst_notes", result, data, { maxChars: p.maxChars, full: p.full, extra: [`  action: ${action}`, `  dry_run: ${dryRun}`], next });
  };
  return dryRun ? await run() : await withFileMutationQueue(queuePath, run);
}

function classifyTypstShellCommand(command: string): { tool: string; reason: string } | undefined {
  const compact = command.replace(/\s+/g, " ").trim();
  if (!compact) return undefined;
  if (/\btypst\s+watch\b/.test(compact) || /\bjust\s+serve\b/.test(compact) || /\bjust\s+watch\b/.test(compact)) {
    return { tool: "process_job", reason: "Long-running Typst preview/watch commands should be managed as process jobs." };
  }
  if (/\b(just\s+(tree|map|doctor|labels|bib|assets)|tools\/notes\.py\s+(structure|map|doctor|labels|bib|bibliography|assets))\b/.test(compact)) return { tool: "typst_query", reason: "Typst template inspection has a bounded structured tool." };
  if (/\btypst\s+(query|fonts|info)\b/.test(compact)) return { tool: "typst_query", reason: "Typst query/info/font inspection has a bounded structured tool." };
  if (/\b(just\s+check|tools\/notes\.py\s+check)\b/.test(compact)) return { tool: "typst_check", reason: "Typst compile validation should use the bounded read-only check tool." };
  if (/\b(just\s+build|tools\/notes\.py\s+build|typst\s+(--color\s+never\s+)?compile\b)/.test(compact)) return { tool: "typst_build", reason: "Typst builds should use the dry-run/confirm build tool." };
  if (/\b(just\s+(new|new-dry|promote|renumber|metadata)|tools\/notes\.py\s+(new|promote|renumber|metadata|metadata-update))\b/.test(compact)) return { tool: "typst_notes", reason: "Typst notes/config mutations should use the dry-run/confirm notes tool." };
  return undefined;
}

export default function registerTypstAxi(pi: ExtensionAPI) {
  pi.on("tool_call", (event, ctx) => {
    if (event.toolName !== "bash") return undefined;
    const command = typeof event.input?.command === "string" ? event.input.command : "";
    const classified = classifyTypstShellCommand(command);
    if (!classified) return undefined;
    ctx?.ui?.notify?.(`Blocked raw Typst maintenance bash; use ${classified.tool}.`, "warning");
    return { block: true, reason: `${classified.reason} Use ${classified.tool} instead.` };
  });

  pi.registerTool({
    name: "typst_query",
    label: "Typst AXI: Query",
    description: "Read-only Typst/template queries: project info, structure, include map, doctor, labels, bibliography/bib_entries, assets/asset_references, outline, macros, settings, fonts, deps, and selectors.",
    promptSnippet: "Use typst_query for bounded Typst/template inspection instead of raw just map/doctor, typst query, typst fonts, or ad-hoc file parsing.",
    promptGuidelines: [
      "Read-only Typst/template inspection tool.",
      "Use typst_query({view:\"doctor\"}) after structural changes.",
      "Use typst_query({view:\"include_map\"}) to inspect the stable include tree rooted at main.typ.",
      "Use typst_query({view:\"selector\", selector:\"heading\"}) for raw Typst query selectors; keep selector strings short and focused.",
    ],
    parameters: Type.Object({
      view: QueryViewSchema,
      input: OptionalSafePath,
      selector: Type.Optional(Type.String()),
      field: Type.Optional(Type.String()),
      one: Type.Optional(Type.Boolean()),
      target: Type.Optional(Type.Union([Type.Literal("paged"), Type.Literal("html")])),
      variants: Type.Optional(Type.Boolean()),
      limit: Limit,
      maxChars: MaxChars,
      full: Full,
    }),
    execute: async (_id: string, p: TypstQueryParams, signal, _onUpdate, ctx) => {
      const root = ensureTemplateRoot(ctx);
      return await runTypstQuery(root, p, signal);
    },
  });

  pi.registerTool({
    name: "typst_check",
    label: "Typst AXI: Check",
    description: "Read-only Typst compile validation. Compiles to a temporary output and returns bounded diagnostics without writing out/main.pdf.",
    promptSnippet: "Use typst_check instead of raw typst compile or just check when you need read-only Typst validation.",
    promptGuidelines: [
      "Read-only compile validation tool; output is temporary and removed.",
      "Use safe relative .typ inputs only; defaults to main.typ.",
      "Use typst_build when you explicitly need to write generated output under out/.",
    ],
    parameters: Type.Object({
      input: OptionalSafePath,
      inputs: Type.Optional(Type.Array(Type.String({ description: "Typst sys.inputs entries as KEY=VALUE strings." }))),
      format: Format,
      creationTimestamp: Type.Optional(Type.String()),
      limit: Limit,
      maxChars: MaxChars,
      full: Full,
    }),
    execute: async (_id: string, p: TypstCheckParams, signal, _onUpdate, ctx) => {
      const root = ensureTemplateRoot(ctx);
      return await runTypstCheck(root, p, signal);
    },
  });

  pi.registerTool({
    name: "typst_build",
    label: "Typst AXI: Build",
    description: "Controlled Typst output generation. Plans by default; dryRun compiles to temp output; confirmed writes are restricted to out/.",
    promptSnippet: "Use typst_build for generated Typst outputs. Omit confirm for a plan, use dryRun:true to validate without writing, and confirm:true to write under out/.",
    promptGuidelines: [
      "Generated-output mutation tool; confirmed writes are restricted to out/.",
      "Omitting confirm returns a plan. Use dryRun:true before confirm:true for non-trivial builds.",
      "Use typst_check for read-only validation when no output file is needed.",
    ],
    parameters: Type.Object({
      input: OptionalSafePath,
      output: OptionalSafePath,
      inputs: Type.Optional(Type.Array(Type.String({ description: "Typst sys.inputs entries as KEY=VALUE strings." }))),
      format: Format,
      dryRun: DryRun,
      confirm: Confirm,
      creationTimestamp: Type.Optional(Type.String()),
      maxChars: MaxChars,
      full: Full,
    }),
    execute: async (_id: string, p: TypstBuildParams, signal, _onUpdate, ctx) => {
      const root = ensureTemplateRoot(ctx);
      return await runTypstBuild(root, p, signal);
    },
  });

  pi.registerTool({
    name: "typst_notes",
    label: "Typst AXI: Notes",
    description: "Template-aware structural notes operations: create entries, promote files, renumber sections, and update main metadata with dry-run/confirm safety.",
    promptSnippet: "Use typst_notes for Typst notes structure changes instead of raw tools/notes.py, just new/promote/renumber, or manual include edits.",
    promptGuidelines: [
      "Template-aware mutation tool; requires dryRun:true or confirm:true.",
      "Structural note operations are restricted to src/ and keep the include graph stable.",
      "Run typst_query({view:\"include_map\"}), typst_query({view:\"doctor\"}), and typst_check({}) after confirmed structural changes.",
    ],
    parameters: Type.Object({
      action: NotesActionSchema,
      parent: OptionalSafePath,
      slug: Type.Optional(Type.String({ description: "One segment with a two-digit prefix, e.g. 02_topic. A trailing / creates a section." })),
      title: Type.Optional(Type.String()),
      section: Type.Optional(Type.Boolean()),
      path: OptionalSafePath,
      directory: OptionalSafePath,
      recursive: Type.Optional(Type.Boolean()),
      includeHigh: Type.Optional(Type.Boolean()),
      titleValue: Type.Optional(Type.String({ description: "New document title for action=metadata_update." })),
      author: Type.Optional(Type.String()),
      date: Type.Optional(Type.String()),
      dryRun: DryRun,
      confirm: Confirm,
      maxChars: MaxChars,
      full: Full,
    }),
    execute: async (_id: string, p: TypstNotesParams, signal, _onUpdate, ctx) => {
      const root = ensureTemplateRoot(ctx);
      return await runTypstNotes(root, p, signal);
    },
  });

  pi.registerCommand("typst", {
    description: "Show Typst AXI extension status",
    handler: async (_args, ctx) => ctx.ui.notify("Typst AXI loaded. Use typst_query, typst_check, typst_build, and typst_notes.", "info"),
  });
}

export const __testing = { classifyTypstShellCommand, parseDiagnostics };
