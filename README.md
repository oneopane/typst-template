# Typst Notes Template

Reusable Typst notes template with a stable, tree-shaped include graph, shared layout/template code, shared notation macros, and a maintenance CLI designed for both humans and coding agents.

## Requirements

- [`typst`](https://typst.app/) for compilation
- [`just`](https://just.systems/) for convenient project commands
- [`uv`](https://docs.astral.sh/uv/) for running the Rich Python CLI in `tools/notes.py`

`tools/notes.py` is an executable uv script with inline dependencies, so uv installs its Python dependencies automatically on first run.

## Layout

```text
.
├── main.typ              # thin document assembly layer
├── notes.toml            # reproducible document metadata defaults
├── template.typ          # reusable page/layout template
├── macros.typ            # notation, helpers, callouts, theorem environments
├── refs.bib              # bibliography entries
├── justfile              # command aliases
├── tools/init-template.py # copy/init helper for new notes projects
├── tools/notes.py        # uv-backed Rich maintenance CLI
├── .pi/extensions/typst-axi/ # project-local Pi AXI extension
├── src/                  # document content only
│   ├── 00_intro.typ
│   ├── 01_notes.typ
│   └── 90_appendix/
│       ├── index.typ
│       └── 00_appendix_intro.typ
├── assets/figures/       # generated or source figures
├── assets/images/        # raster/vector images
└── out/                  # compiled outputs
```

## Quick start

Create a new notes project from this template with the interactive initializer:

```sh
just init
```

Or pass arguments to run it non-interactively:

```sh
just init ../my-notes "My Notes"
```

Optional metadata and VCS initialization can be passed through:

```sh
just init ../my-notes "My Notes" --author "Ada" --date "2026-01-01" --vcs jj
```

Open the interactive CLI:

```sh
just
```

Build the PDF:

```sh
just build
```

Serve a localhost preview with browser refresh while editing:

```sh
just serve
```

Validate the include graph and compile:

```sh
just doctor
just check
```

## Commands

```sh
just                       # open the interactive notes CLI
just ui                    # same interactive menu explicitly
just help                  # show CLI help
just init [DIR TITLE]      # copy this template into a new notes project; interactive with no args
just tree                  # show the physical src/ tree
just map                   # show the include graph rooted at main.typ
just map-write CONTENTS.md # write a Markdown include map
just build                 # compile main.typ to out/main.pdf
just watch                 # rebuild automatically when Typst files change
just serve                 # localhost preview with browser auto-refresh
just check                 # verify compilation to a temporary output
just doctor                # validate include graph conventions
just metadata              # show or update notes.toml metadata defaults
just labels                # summarize labels and Typst references
just bib                   # summarize refs.bib entries and citations
just assets                # summarize image asset references
just clean                 # remove generated preview outputs
```

The underlying CLI can also be called directly:

```sh
./tools/notes.py
./tools/notes.py --help
./tools/notes.py map
./tools/notes.py map --json
./tools/notes.py map --write CONTENTS.md
./tools/notes.py new src 02_topic --dry-run --json
./tools/notes.py renumber src --dry-run
./tools/notes.py metadata --title "My Notes" --dry-run
```

## Pi / AXI extension

This repository includes a project-local Pi extension at `.pi/extensions/typst-axi/`.

After project trust and `/reload`, it provides a structured Typst tool surface for agents:

- `typst_query` — project info, structure, include map, doctor, labels, bibliography (`bib_entries`), assets (`asset_references`), outline, macros, settings, Typst info/fonts/deps/selectors
- `typst_check` — read-only compile validation to a temporary output, with optional Typst `sys.inputs`
- `typst_build` — dry-run/confirm generated output writes under `out/`, with optional Typst `sys.inputs`
- `typst_notes` — dry-run/confirm structural operations for new/promote/renumber/metadata updates

The extension mirrors the safety style of other AXI tools: safe relative paths, bounded output, and `dryRun` / `confirm` semantics for writes. It intentionally keeps asset-reference insertion and bibliography-entry mutation as future work until `tools/notes.py` owns robust JSON plans for those edits. See `.pi/extensions/typst-axi/README.md` for details.

## Metadata and reproducible dates

Document metadata defaults live in `notes.toml`:

```toml
[metadata]
title = "Notes"
author = "Author Name"
date = ""
```

`main.typ` reads those defaults and then applies Typst `sys.inputs` overrides. The default `date` is empty, so the visible title-block date is omitted instead of using the current day. This keeps builds reproducible. To set persistent defaults:

```sh
./tools/notes.py metadata --title "My Notes" --author "Ada" --date "2026-01-01"
```

To override for one compile:

```sh
./tools/notes.py check --input title="Draft Notes" --input date="2026-01-01"
./tools/notes.py build --title "Published Notes" --date ""
```

## Interactive CLI

Run `just` or `./tools/notes.py` with no arguments for a guided Rich menu. It can:

- create a new content file or section directory
- promote a file into a section directory
- preview and apply renumbering
- show the physical `src/` tree
- show the actual include graph rooted at `main.typ`
- run `doctor`, `build`, `serve`, `watch`, and `clean`

Direct commands also support structured JSON for scripting and agents:

```sh
./tools/notes.py structure --json
./tools/notes.py map --json
./tools/notes.py doctor --json
./tools/notes.py new src 02_topic --dry-run --json
./tools/notes.py promote src/02_topic.typ --dry-run --json
./tools/notes.py renumber src --recursive --dry-run --json
./tools/notes.py doctor --json out/doctor.json
```

`--json` emits to stdout by default; pass a repository-relative path to write the JSON instead.

The interactive flow is optimized for humans. Direct commands are better for scripts and coding agents.

## Creating notes

Use the interactive flow when you want guided prompts:

```sh
just
```

Use direct commands when you already know the parent directory and slug:

```sh
just new-dry src 02_topic
just new src 02_topic
just new src 03_probability/
```

- `just new-dry src 02_topic` previews the created file and include update.
- `just new src 02_topic` creates `src/02_topic.typ`.
- `just new src 03_probability/` creates `src/03_probability/index.typ`.
- The CLI infers the title from the slug and updates the parent include entrypoint automatically.
- The interactive menu can infer the next numeric prefix from a plain title.

## Promoting files to sections

Start small with a single file:

```text
src/03_probability.typ
```

When it grows, promote it:

```sh
just promote-dry src/03_probability.typ
just promote src/03_probability.typ
```

Promotion converts the file into:

```text
src/03_probability/
  index.typ
  00_probability.typ
```

The CLI moves the original body into the child file, creates the section `index.typ`, and updates the parent include from `03_probability.typ` to `03_probability/index.typ`.

## Section organization

Small sections can be single files:

```text
src/03_probability.typ
```

Large sections should be directories:

```text
src/03_probability/
  index.typ
  00_axioms.typ
  01_random_variables.typ
  02_expectation.typ
```

Then include only `src/03_probability/index.typ` from `main.typ`.

## Nested sections and include graph

`main.typ` is the root. It may include only:

- `src/*.typ`
- `src/*/index.typ`

Subdirectories under `src/` expose exactly one public entrypoint: `index.typ`. A directory's `index.typ` includes only that directory's immediate children.

This supports arbitrary depth:

```text
src/01_foundations/
  index.typ
  00_sets.typ
  01_partitions.typ
  02_relations/
    index.typ
    00_equivalence.typ
    01_orders.typ
```

No file should include a parent, and siblings should not include siblings.

Use `just map` to inspect the actual include graph:

```text
main.typ
├── src/00_intro.typ
├── src/01_notes.typ
└── src/90_appendix/index.typ
    └── src/90_appendix/00_appendix_intro.typ
```

## Doctor checks

`just doctor` validates conventions that are easy for humans or agents to accidentally break:

- invalid include targets
- duplicate includes
- include order drift
- orphan immediate children not included by their parent entrypoint
- content files containing `#include`
- directories under `src/` missing `index.typ`
- non-numeric content names
- files included by multiple parents
- include cycles through `index.typ` files
- missing `notes.toml`
- missing `refs.bib`
- missing local image assets referenced with `image("...")`

Run it before committing structural changes.

Additional read-only helpers are useful before larger edits:

```sh
./tools/notes.py labels --json
./tools/notes.py bib --json
./tools/notes.py assets --json
```

They summarize Typst labels/references, bibliography citations, and local `image("...")` asset references.

## Renumbering

Preview local renumbering before applying it:

```sh
just renumber-dry src
just renumber src
```

By default, high-numbered sections such as `90_appendix` are preserved. To include them intentionally:

```sh
./tools/notes.py renumber src --all
```

For nested renumbering:

```sh
./tools/notes.py renumber src --recursive --dry-run
```

## Images and figures

Place images in `assets/images/` and figures in `assets/figures/`, then reference them from content files:

```typst
#figure(image("../assets/images/example.png", width: 80%), caption: [Example image])
```

Adjust relative paths from the file doing the referencing.

## Macros

`macros.typ` is the default compatibility bundle. It re-exports common helpers from `macros/` such as `bbR`, `cA`, `norm(x)`, `EE`, `Var`, `Cov`, `definition`, `theorem`, `lemma`, `proposition`, `corollary`, `example`, `remark`, `proof`, `note`, and `todo`.

Domain-specific modules live under `macros/` and can be imported directly when needed. `macros/diagrams.typ` is opt-in and imports Fletcher for category-theory diagrams.

Content files that use the default bundle should import it with the correct relative path, for example:

```typst
#import "../macros.typ": *
```

Probability helpers support optional conditioning and measure arguments:

```typst
#EE[$X$]
#EE($X$, given: $Y$)
#EE($X$, given: $Y$, measure: $P$)
#Var($X$, given: $Y$)
#Cov($X$, $Y$, given: $Z$)
```

Specialized modules can be imported directly or with a namespace:

```typst
#import "../../macros/category.typ" as cat
#import "../../macros/diagrams.typ": commdiag, edge

#commdiag($
  A edge("r", f, "->") edge("d", g, "->") & B edge("d", h, "->") \\
  C edge("r", k, "->") & D
$)
```

Theorem-like environments preserve bare block syntax and accept optional `title:` arguments:

```typst
#definition(title: [Reusable template])[
A notes template separates assembly, layout, notation, content, assets, and bibliography data.
] <def:reusable-template>

#theorem(title: [Stable includes])[
Each content file has exactly one path from `main.typ`.
] <thm:stable-includes>

See @def:reusable-template and @thm:stable-includes.
```

Labels are normal Typst labels appended after the macro call. They are not passed as a `label:` argument. Theorem, lemma, proposition, and corollary share a counter; definitions, examples, and remarks use separate counters. `proof` accepts optional `title:` and `qed:` arguments while preserving bare `#proof[...]` usage.

Typst reserves `set` as a keyword, so this template names the set-builder helper `setof(x)`.

## Bibliography

Add BibTeX entries to `refs.bib`, cite them with Typst citation syntax such as `@knuth1984texbook`, and keep the bibliography call in `main.typ`.
