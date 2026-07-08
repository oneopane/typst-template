# Typst AXI

Project-local Pi extension for this Typst notes template.

This extension intentionally behaves like the other AXI tools in `pi-extensions`: small intent-focused tools, safe relative paths, bounded output, structured `details`, and `dryRun` / `confirm` semantics for writes. Template-specific views and mutations consume `tools/notes.py --json` instead of parsing Rich output.

## Tools

### `typst_query`

Read-only Typst/template inspection.

Views:

- `project_info`
- `structure`
- `include_map`
- `doctor`
- `labels`
- `bibliography` (alias: `bib_entries`)
- `assets` (alias: `asset_references`)
- `outline`
- `macro_catalog`
- `template_settings`
- `info`
- `fonts`
- `deps`
- `selector`

Examples:

```ts
typst_query({ view: "project_info" })
typst_query({ view: "include_map" })
typst_query({ view: "doctor" })
typst_query({ view: "labels" })
typst_query({ view: "bibliography" })
typst_query({ view: "bib_entries" })
typst_query({ view: "assets" })
typst_query({ view: "asset_references" })
typst_query({ view: "outline" })
typst_query({ view: "selector", selector: "heading" })
```

### `typst_check`

Read-only Typst compile validation.

```ts
typst_check({ input: "main.typ" })
typst_check({ inputs: ["title=Draft Notes", "date=2026-01-01"] })
```

This compiles to a temporary output and removes it. It does **not** write `out/main.pdf`. `inputs` are passed to Typst as `--input KEY=VALUE` and are available through `sys.inputs`.

### `typst_build`

Controlled generated-output writes.

```ts
typst_build({ dryRun: true })
typst_build({ output: "out/main.pdf", inputs: ["title=Published Notes"], confirm: true })
```

Rules:

- no `confirm:true` and no `dryRun:true` returns a plan only
- `dryRun:true` compiles to a temporary output
- `confirm:true` writes only under `out/`

### `typst_notes`

Template-aware structural operations.

Actions:

- `new`
- `promote`
- `renumber`
- `metadata_update`

Examples:

```ts
typst_notes({ action: "new", parent: "src", slug: "02_topic", dryRun: true })
typst_notes({ action: "new", parent: "src", slug: "02_topic", confirm: true })

typst_notes({ action: "promote", path: "src/02_topic.typ", dryRun: true })
typst_notes({ action: "promote", path: "src/02_topic.typ", confirm: true })

typst_notes({ action: "renumber", directory: "src", dryRun: true })
typst_notes({ action: "renumber", directory: "src", confirm: true })

typst_notes({ action: "metadata_update", titleValue: "My Notes", dryRun: true })
typst_notes({ action: "metadata_update", titleValue: "My Notes", author: "Ada", date: "", confirm: true })
```

`metadata_update` is backed by `tools/notes.py metadata --json` and updates `notes.toml`; `main.typ` reads those defaults and allows per-compile `sys.inputs` overrides.

## Safety model

- Project-local extension; intended only for this template.
- Validates required template root files before running, while allowing `doctor` to report a missing `refs.bib`.
- Rejects absolute paths, `~`, NUL bytes, Windows drives, UNC paths, and `..` segments.
- Restricts note-structure operations to `src/`.
- Restricts generated build output to `out/`.
- Uses argv arrays, never shell strings.
- Bounds stdout/stderr in tool output.
- Mutating operations require `dryRun:true` or `confirm:true`.
- `dryRun:true` wins over `confirm:true`.
- Confirmed writes are serialized with Pi's file mutation queue.

## Bash guidance

The extension conservatively blocks common raw shell equivalents and points agents to structured tools:

- `just map`, `just doctor`, `just labels`, `just bib`, `just assets`, `tools/notes.py map` → `typst_query`
- `typst query`, `typst fonts`, `typst info` → `typst_query`
- `just check` → `typst_check`
- `just build`, `typst compile ...` → `typst_build`
- `just new`, `just new-dry`, `just promote`, `just renumber`, `just metadata` → `typst_notes`
- `just serve`, `just watch`, `typst watch` → `process_job`

## Intentionally not included

`asset_reference` planning/apply and `bib_entry_add` planning/apply are intentionally left as future work. They should first be implemented in `tools/notes.py` with robust JSON dry-run/apply plans, duplicate detection, path validation, and formatting guarantees; the AXI layer should not half-implement direct edits to Typst content, `assets/`, or `refs.bib`.

Long-running preview/watch management is not part of this extension. Use this repository's human command:

```sh
just serve
```

or Pi's managed process tools for agent-managed jobs.

## Recommended agent workflow

After structural changes:

```ts
typst_query({ view: "include_map" })
typst_query({ view: "doctor" })
typst_check({})
```

For generated outputs:

```ts
typst_build({ dryRun: true })
typst_build({ confirm: true })
```
