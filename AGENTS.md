# Agent Instructions

This file is the authoritative specification for AI agents extending this Typst notes template.

## Repository philosophy

Keep the project reusable, predictable, and easy to refactor. Separate assembly, layout, notation, content, assets, bibliography data, and maintenance tooling. Preserve a stable tree-shaped include graph at all times.

The repository is optimized for two users:

1. Humans who want a pleasant writing workflow.
2. LLM/coding agents that need deterministic structure, commands, and validation.

## File ownership

- `main.typ`: thin assembly layer only. Imports shared files, reads `notes.toml`/`sys.inputs` metadata, applies the template, includes public top-level content entrypoints, and wires `refs.bib`.
- `notes.toml`: reproducible document metadata defaults (`title`, `author`, `date`). Empty `author`/`date` values are omitted from the title block.
- `template.typ`: all document layout and style logic, including page setup, fonts, heading numbering, title block, table of contents, and spacing.
- `macros.typ`: reusable notation, operators, callouts, theorem environments, and formatting helpers.
- `src/`: document content only.
- `assets/figures/`: figures.
- `assets/images/`: images.
- `refs.bib`: bibliography entries.
- `justfile`: thin command aliases. Keep these aligned with `tools/notes.py`.
- `tools/notes.py`: executable uv script providing the Rich CLI for interactive and direct maintenance workflows.
- `.pi/extensions/typst-axi/`: project-local Pi AXI extension exposing structured Typst/template tools for agents.
- `out/`: compiled output.

Do not move layout logic into `main.typ` or `src/`. Do not put durable notation in content files. Do not put content in `template.typ` or `macros.typ`.

## Tooling contract

Prefer repository tooling for structural changes:

```sh
just                         # interactive Rich menu
just new-dry src 02_topic
just new src 02_topic
just new src 03_probability/
just promote-dry src/foo.typ
just promote src/foo.typ
just renumber-dry src
just renumber src
just map
just doctor
just check
just metadata
just labels
just bib
just assets
```

Direct CLI equivalents are available through `./tools/notes.py`. Running `./tools/notes.py` with no arguments opens the interactive menu. The script uses a uv shebang and inline dependencies; do not convert it to a project package unless explicitly requested.

Agents should prefer direct, non-interactive commands for deterministic edits and validation. `structure`, `map`, `doctor`, `new`, `promote`, `renumber`, `metadata`, `labels`, `bib`, and `assets` support `--json` for machine-readable output; `new`, `promote`, `renumber`, and `metadata` support `--dry-run` previews. Inside Pi after `/reload`, prefer the AXI tools (`typst_query`, `typst_check`, `typst_build`, `typst_notes`) over raw shell commands. `typst_query` exposes `bibliography`/`bib_entries` and `assets`/`asset_references` read-only views; bibliography-entry and asset-reference mutations remain future work until the CLI owns robust JSON plans. The interactive menu is primarily for humans, but it must remain functional.

When changing `tools/notes.py` or `.pi/extensions/typst-axi/`, also update:

1. `justfile`, if commands or arguments change.
2. `.pi/extensions/typst-axi/README.md`, if AXI behavior changes.
3. `README.md`, if user-facing behavior changes.
4. This `AGENTS.md`, if repository conventions or agent workflows change.

## Include graph rules

The include graph must always be a tree rooted at `main.typ`.

`main.typ` may include only:

- `src/*.typ`
- `src/*/index.typ`

The root `src/` directory is special: its public entrypoint is `main.typ`. Every subdirectory under `src/` exposes exactly one public entrypoint named `index.typ`. A directory's `index.typ` is responsible for including that directory's immediate children.

Rules:

1. No file includes a parent.
2. No sibling includes another sibling.
3. No content file under `src/` should contain `#include`.
4. No import or include cycles.
5. Directory `index.typ` files include only immediate child files and immediate child directory entrypoints.
6. Arbitrary nesting depth is allowed if each level follows these rules.

Use `just map` to inspect the actual include graph rooted at `main.typ`.

## Correct arbitrary-depth structure

```text
src/
  01_foundations/
    index.typ
    00_sets.typ
    01_partitions.typ
    02_relations/
      index.typ
      00_equivalence.typ
      01_orders.typ
```

Correct includes:

```typst
// main.typ
#include "src/01_foundations/index.typ"

// src/01_foundations/index.typ
#include "00_sets.typ"
#include "01_partitions.typ"
#include "02_relations/index.typ"

// src/01_foundations/02_relations/index.typ
#include "00_equivalence.typ"
#include "01_orders.typ"
```

## Incorrect structures

Do not include grandchildren directly from `main.typ`:

```typst
#include "src/01_foundations/02_relations/00_equivalence.typ" // incorrect
```

Do not include parents:

```typst
// src/01_foundations/02_relations/00_equivalence.typ
#include "../index.typ" // incorrect
```

Do not include siblings from siblings:

```typst
// src/01_foundations/00_sets.typ
#include "01_partitions.typ" // incorrect
```

Do not create multiple public entrypoints in one directory.

## Naming conventions

Use two-digit numeric prefixes for stable ordering:

```text
00_intro.typ
01_sets.typ
02_partitions.typ
05_measure/
06_learning_theory/
90_appendix/
```

Preserve numeric ordering when adding, renaming, or promoting sections. High-numbered sections such as `90_appendix` are reserved for appendices/back matter and are ignored by default by `just renumber`; include them only with `./tools/notes.py renumber src --all` when intentional.

## Creating content

Preferred direct commands:

```sh
just new-dry src 02_topic
just new src 02_topic
just new src 03_probability/
```

`just new-dry` previews without mutating. `just new` requires a parent directory and slug. A trailing slash creates a section directory with `index.typ`; otherwise it creates a `.typ` file. The CLI infers a heading title from the slug and updates the parent include entrypoint automatically.

For guided creation, use:

```sh
just
```

The interactive flow can infer the next numeric prefix from a plain title.

## Promoting a file to a directory

Promote a file when it becomes large enough to split.

Before:

```text
src/03_probability.typ
```

Preview and apply:

```sh
just promote-dry src/03_probability.typ
just promote src/03_probability.typ
```

After:

```text
src/03_probability/
  index.typ
  00_probability.typ
```

The promote command:

1. Reads the existing file.
2. Uses the first heading as the new section heading when present.
3. Moves the body into `00_<name>.typ`.
4. Creates `index.typ` with the section heading and child include.
5. Updates the parent include from `<name>.typ` to `<name>/index.typ`.
6. Rewrites the child file's `macros.typ` import to the correct relative path.

After promotion, split `00_<name>.typ` into more children as needed.

## Renumbering

Always preview renumbering first:

```sh
just renumber-dry src
```

Then apply:

```sh
just renumber src
```

For nested directories:

```sh
./tools/notes.py renumber src --recursive --dry-run
./tools/notes.py renumber src --recursive
```

Do not manually rename numbered files/directories unless you also update the parent include entrypoint. Prefer the CLI because it rewrites includes.

## Doctor expectations

`just doctor` is the structural gate. It checks for:

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

If `doctor` fails, fix the structure before continuing with content changes.

## Metadata conventions

Do not reintroduce daily nondeterminism in `main.typ`. Visible document metadata comes from `notes.toml` and can be overridden per compile with Typst `sys.inputs` (`--input title=...`, `--input author=...`, `--input date=...`). The empty string means “omit this field” for `author` and `date`.

Use the CLI for persistent metadata changes:

```sh
./tools/notes.py metadata --title "My Notes" --author "Ada" --date "2026-01-01" --dry-run
./tools/notes.py metadata --title "My Notes" --author "Ada" --date "2026-01-01"
```

## Macros and imports

Keep reusable notation and environments in `macros.typ`. Content files that use macros may import `macros.typ` with a relative `#import`, but must not redefine durable notation locally.

`EE` is a function with optional arguments:

```typst
#EE[$X$]
#EE[$X$, given: $Y$]
#EE[$X$, given: $Y$, measure: $P$]
```

The theorem-like environments (`definition`, `theorem`, `lemma`, `proposition`, `corollary`, `example`, `remark`) preserve bare block syntax and accept optional `title:` arguments. Add references with normal Typst labels after the macro call, not a `label:` argument:

```typst
#theorem(title: [Stable includes])[
Each content file has exactly one path from `main.typ`.
] <thm:stable-includes>

See @thm:stable-includes.
```

The theorem family (`theorem`, `lemma`, `proposition`, `corollary`) shares a counter; definitions, examples, and remarks use separate counters. `proof` accepts optional `title:` and `qed:` while preserving `#proof[...]`.

Typst reserves `set`; the set-builder helper is named `setof`.

## Agent checklist

Before finishing changes:

1. Confirm `main.typ` remains thin and does not call `datetime.today()` for visible metadata.
2. Confirm persistent metadata defaults remain in `notes.toml`.
3. Confirm layout changes are only in `template.typ`.
4. Confirm notation/environment changes are only in `macros.typ`.
5. Confirm content changes are only in `src/`.
6. Confirm assets are under `assets/figures/` or `assets/images/`.
7. Confirm every subdirectory under `src/` has exactly one `index.typ` entrypoint.
8. Confirm no parent, sibling, or cyclic includes were introduced.
9. Confirm numeric ordering is preserved.
10. If tooling changed, confirm `justfile`, `.pi/extensions/typst-axi/README.md`, `README.md`, and `AGENTS.md` remain aligned.
11. If the AXI extension changed, reload Pi and smoke-test `typst_query({view:"project_info"})`, `typst_query({view:"doctor"})`, and `typst_check({})` when possible.
12. Run `just map` if include structure changed and inspect the graph.
13. Run `just doctor`.
14. Run `just check`.
