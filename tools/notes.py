#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "rich>=13.7",
#   "rich-argparse>=1.5",
# ]
# ///
"""Rich CLI for maintaining this Typst notes template."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
import sys
import tempfile
import time
import tomllib
import webbrowser
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.tree import Tree
from rich_argparse import RichHelpFormatter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUT = ROOT / "out"
MAIN = ROOT / "main.typ"
CONFIG = ROOT / "notes.toml"

console = Console()
JSON_MODE = False
INCLUDE_RE = re.compile(r'^\s*#include\s+"([^"]+)"\s*$')
PREFIX_RE = re.compile(r"^(?P<num>[0-9]+)_(?P<name>.+)$")
IMAGE_RE = re.compile(r'\bimage\("([^"]+)"')

PREVIEW_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Typst Notes Preview</title>
<style>
  html, body, iframe { margin: 0; width: 100%; height: 100%; border: 0; }
  body { overflow: hidden; background: #111; }
</style>
</head>
<body>
<iframe id="pdf" src="main.pdf"></iframe>
<script>
let last = null;
async function poll() {
  try {
    const response = await fetch('main.pdf', { method: 'HEAD', cache: 'no-store' });
    const stamp = response.headers.get('last-modified') + response.headers.get('content-length');
    if (last && stamp !== last) {
      document.getElementById('pdf').src = 'main.pdf?t=' + Date.now();
    }
    last = stamp;
  } catch (_) {}
}
setInterval(poll, 1000);
poll();
</script>
</body>
</html>
"""


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def fail(message: str, code: int = 1) -> None:
    if JSON_MODE:
        print(json.dumps({"ok": False, "error": message}, indent=2), file=sys.stderr)
    else:
        console.print(Panel.fit(message, title="[red]Error[/red]", border_style="red"))
    raise SystemExit(code)


def json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return rel(value)
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    return value


def emit_json(args: argparse.Namespace, payload: dict[str, Any]) -> bool:
    destination = getattr(args, "json", None)
    if destination is None:
        return False
    text = json.dumps(json_ready(payload), indent=2, sort_keys=True) + "\n"
    if destination == "-":
        sys.stdout.write(text)
        return True
    path = (ROOT / destination).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        fail("JSON output path must stay inside the repository.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        nargs="?",
        const="-",
        metavar="PATH",
        help="emit structured JSON to stdout, or write it to PATH when provided",
    )


def ensure_repo() -> None:
    for path in (MAIN, ROOT / "template.typ", ROOT / "macros.typ", SRC):
        if not path.exists():
            fail(f"Missing required path: {rel(path) if path.is_absolute() else path}")


def safe_src_dir(value: str) -> Path:
    path = (ROOT / value).resolve()
    try:
        path.relative_to(SRC)
    except ValueError:
        fail("Directory must be under src/.")
    if not path.exists() or not path.is_dir():
        fail(f"Directory does not exist: {rel(path)}")
    return path


def title_from_slug(slug: str) -> str:
    base = slug.rstrip("/")
    base = PREFIX_RE.sub(lambda m: m.group("name"), base)
    return base.replace("_", " ").replace("-", " ").title()


def validate_slug(slug: str, force_section: bool = False) -> tuple[str, bool]:
    is_section = force_section or slug.endswith("/")
    base = slug.strip("/")
    if not base or "/" in base or base == ".":
        fail("Slug must be one path segment, e.g. 02_topic or 03_probability/.")
    if base.endswith(".typ"):
        base = base[:-4]
    if not re.match(r"^[0-9]{2}_[A-Za-z0-9_-]+$", base):
        fail("Slug must start with a two-digit numeric prefix, e.g. 02_topic.")
    return base, is_section


def heading_marker(parent: Path) -> str:
    depth = len(parent.relative_to(SRC).parts)
    return "=" * (depth + 1)


def entrypoint_for(parent: Path) -> Path:
    return MAIN if parent == SRC else parent / "index.typ"


def include_target_for_child(parent: Path, child: Path) -> str:
    # Planned section directories do not exist yet during dry-runs/new/promote
    # planning, so use the path shape as well as filesystem state.
    if child.is_dir() or child.suffix == "":
        suffix = f"{child.name}/index.typ"
    else:
        suffix = child.name
    if parent == SRC:
        return f"src/{suffix}"
    return suffix


def upsert_include(entrypoint: Path, include_target: str) -> bool:
    if not entrypoint.exists():
        fail(f"Parent entrypoint is missing: {rel(entrypoint)}")

    text = entrypoint.read_text(encoding="utf-8")
    lines = text.splitlines()
    matches: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        match = INCLUDE_RE.match(line)
        if match:
            matches.append((i, match.group(1)))

    existing = [target for _, target in matches]
    if include_target in existing:
        return False

    include_paths = sorted(set(existing + [include_target]))
    include_lines = [f'#include "{target}"' for target in include_paths]

    if matches:
        include_indexes = {i for i, _ in matches}
        first = matches[0][0]
        kept = [line for i, line in enumerate(lines) if i not in include_indexes]
        lines = kept[:first] + include_lines + kept[first:]
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(include_lines)

    entrypoint.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True


def replace_include(entrypoint: Path, old_target: str, new_target: str) -> str:
    """Replace one include target, or add the new target if the old one is absent."""
    if not entrypoint.exists():
        fail(f"Parent entrypoint is missing: {rel(entrypoint)}")

    text = entrypoint.read_text(encoding="utf-8")
    old_line = f'#include "{old_target}"'
    new_line = f'#include "{new_target}"'
    if old_line in text:
        entrypoint.write_text(text.replace(old_line, new_line, 1), encoding="utf-8")
        return "replaced"
    updated = upsert_include(entrypoint, new_target)
    return "added" if updated else "already present"


def strip_macro_import(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skip_blank = False
    for line in lines:
        if re.match(r'^\s*#import\s+".*macros\.typ"\s*:\s*\*\s*$', line):
            skip_blank = True
            continue
        if skip_blank and not line.strip():
            skip_blank = False
            continue
        skip_blank = False
        kept.append(line)
    return "\n".join(kept).strip("\n") + "\n"


def split_promoted_content(text: str, fallback_marker: str, fallback_title: str) -> tuple[str, str, str]:
    """Return heading marker, heading title, and body for a promoted file."""
    cleaned = strip_macro_import(text)
    lines = cleaned.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        match = re.match(r"^(=+)\s+(.+?)\s*$", line)
        if match:
            body_lines = lines[:i] + lines[i + 1 :]
            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)
            body = "\n".join(body_lines).strip("\n")
            return match.group(1), match.group(2), body
        break
    return fallback_marker, fallback_title, cleaned.strip("\n")


def macro_import_for(path: Path) -> str:
    macro_path = Path(os.path.relpath(ROOT / "macros.typ", start=path.parent)).as_posix()
    return f'#import "{macro_path}": *\n\n'


def parse_typst_inputs(args: argparse.Namespace) -> list[str]:
    values: dict[str, str] = {}
    for raw in getattr(args, "inputs", []) or []:
        if "=" not in raw:
            fail("Typst inputs must use KEY=VALUE syntax.")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", key):
            fail(f"Invalid Typst input key: {key or raw}")
        values[key] = value
    for key in ("title", "author", "date"):
        value = getattr(args, key, None)
        if value is not None:
            values[key] = value
    cli_args: list[str] = []
    for key, value in values.items():
        cli_args.extend(["--input", f"{key}={value}"])
    return cli_args


def add_typst_input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", dest="inputs", action="append", default=[], metavar="KEY=VALUE", help="pass a Typst sys.inputs value")
    parser.add_argument("--title", help="override sys.inputs.title for this compile")
    parser.add_argument("--author", help="override sys.inputs.author for this compile")
    parser.add_argument("--date", help="override sys.inputs.date for this compile; use an empty string to omit it")


def load_notes_config() -> dict[str, Any]:
    if not CONFIG.exists():
        return {}
    data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def load_metadata() -> dict[str, str]:
    metadata = load_notes_config().get("metadata", {})
    if not isinstance(metadata, dict):
        return {}
    result: dict[str, str] = {}
    for key in ("title", "author", "date"):
        if key in metadata:
            result[key] = str(metadata[key])
    return result


def toml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_metadata(metadata: dict[str, str]) -> None:
    ordered = {"title": metadata.get("title", "Notes"), "author": metadata.get("author", ""), "date": metadata.get("date", "")}
    lines = [
        "# Document metadata defaults for main.typ.",
        "# Empty author/date values are omitted from the title block.",
        "# Override per compile with: typst compile --input title=... --input date=...",
        "",
        "[metadata]",
    ]
    lines.extend(f"{key} = {toml_quote(value)}" for key, value in ordered.items())
    CONFIG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def metadata_value(value: str | None) -> str | None:
    return None if value is None else value


def command_table(title: str, rows: list[tuple[str, str]]) -> None:
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Item", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    for item, value in rows:
        table.add_row(item, value)
    console.print(table)


def run(cmd: list[str], label: str) -> int:
    console.print(Panel.fit(" ".join(cmd), title=label, border_style="cyan"))
    return subprocess.run(cmd, cwd=ROOT).returncode


def cmd_build(args: argparse.Namespace) -> None:
    ensure_repo()
    OUT.mkdir(exist_ok=True)
    code = run(["typst", "compile", *parse_typst_inputs(args), "main.typ", "out/main.pdf"], "Build")
    if code != 0:
        raise SystemExit(code)
    console.print("[green]Built[/green] out/main.pdf")


def cmd_check(args: argparse.Namespace) -> None:
    ensure_repo()
    with tempfile.TemporaryDirectory(prefix="typst-notes-check-") as temp_dir:
        output = str(Path(temp_dir) / "main.pdf")
        code = run(["typst", "compile", *parse_typst_inputs(args), "main.typ", output], "Check")
    if code != 0:
        raise SystemExit(code)
    console.print("[green]Document compiles.[/green]")


def cmd_watch(_: argparse.Namespace) -> None:
    ensure_repo()
    OUT.mkdir(exist_ok=True)
    console.print(Panel.fit("typst watch main.typ out/main.pdf", title="Watch", border_style="cyan"))
    raise SystemExit(subprocess.run(["typst", "watch", "main.typ", "out/main.pdf"], cwd=ROOT).returncode)


def write_preview_html() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(PREVIEW_HTML, encoding="utf-8")


def terminate(process: subprocess.Popen[object] | None) -> None:
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def cmd_serve(args: argparse.Namespace) -> None:
    ensure_repo()
    OUT.mkdir(exist_ok=True)
    write_preview_html()

    code = subprocess.run(["typst", "compile", "main.typ", "out/main.pdf"], cwd=ROOT).returncode
    if code != 0:
        raise SystemExit(code)

    watch: subprocess.Popen[object] | None = None
    server: subprocess.Popen[object] | None = None
    url = f"http://localhost:{args.port}/"

    try:
        watch = subprocess.Popen(["typst", "watch", "main.typ", "out/main.pdf"], cwd=ROOT)
        server = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(args.port)],
            cwd=OUT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        webbrowser.open(url)
        console.print(
            Panel.fit(
                f"[bold green]Serving[/bold green] {url}\n"
                "Edit Typst files and the browser preview will refresh.\n"
                "Press [bold]Ctrl+C[/bold] to stop.",
                title="Live Preview",
                border_style="green",
            )
        )
        while True:
            if watch.poll() is not None:
                fail("typst watch exited unexpectedly.")
            if server.poll() is not None:
                fail("HTTP server exited unexpectedly.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping preview...[/yellow]")
    finally:
        terminate(watch)
        terminate(server)


def cmd_clean(_: argparse.Namespace) -> None:
    OUT.mkdir(exist_ok=True)
    removed: list[str] = []
    for path in list(OUT.glob("*.pdf")) + [OUT / "index.html"]:
        if path.exists():
            path.unlink()
            removed.append(rel(path))
    if removed:
        for path in removed:
            console.print(f"[green]Removed[/green] {path}")
    else:
        console.print("[yellow]Nothing to clean.[/yellow]")


def plan_new_entry(args: argparse.Namespace) -> dict[str, Any]:
    parent = safe_src_dir(args.directory)
    base, is_section = validate_slug(args.slug, args.section)
    marker = heading_marker(parent)
    raw_title = " ".join(args.title).strip()
    heading = raw_title or title_from_slug(base)

    if is_section:
        target = parent / base
        created = target / "index.typ"
        if target.exists():
            fail(f"Already exists: {rel(target)}")
        content = f"{marker} {heading}\n\n"
        include_child = target
        kind = "section"
    else:
        target = parent / f"{base}.typ"
        created = target
        if target.exists():
            fail(f"Already exists: {rel(target)}")
        content = f"{macro_import_for(target)}{marker} {heading}\n\n"
        include_child = target
        kind = "file"

    entrypoint = entrypoint_for(parent)
    include_target = include_target_for_child(parent, include_child)
    include_updated = include_target not in includes_in(entrypoint)
    return {
        "kind": kind,
        "parent": parent,
        "slug": base,
        "section": is_section,
        "heading": heading,
        "headingMarker": marker,
        "target": target,
        "created": created,
        "content": content,
        "entrypoint": entrypoint,
        "include": include_target,
        "includeUpdated": include_updated,
    }


def apply_new_entry(plan: dict[str, Any]) -> dict[str, Any]:
    target: Path = plan["target"]
    created: Path = plan["created"]
    if plan["section"]:
        target.mkdir()
        created.write_text(plan["content"], encoding="utf-8")
    else:
        target.write_text(plan["content"], encoding="utf-8")
    updated = upsert_include(plan["entrypoint"], plan["include"])
    return {**plan, "includeUpdated": updated}


def new_json(plan: dict[str, Any], *, dry_run: bool, applied: bool = False) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "new",
        "dryRun": dry_run,
        "applied": applied,
        "kind": plan["kind"],
        "parent": plan["parent"],
        "slug": plan["slug"],
        "section": plan["section"],
        "heading": plan["heading"],
        "target": plan["target"],
        "created": plan["created"],
        "entrypoint": plan["entrypoint"],
        "include": plan["include"],
        "includeUpdated": plan["includeUpdated"],
    }


def cmd_new(args: argparse.Namespace) -> None:
    ensure_repo()
    plan = plan_new_entry(args)

    if args.dry_run:
        if emit_json(args, new_json(plan, dry_run=True)):
            return
        command_table(
            "New entry preview",
            [
                ("Kind", "section directory" if plan["section"] else "content file"),
                ("Create", rel(plan["created"])),
                ("Parent", rel(plan["parent"])),
                ("Entrypoint", rel(plan["entrypoint"])),
                ("Include", f'#include "{plan["include"]}"'),
                ("Heading", plan["heading"]),
            ],
        )
        return

    result = apply_new_entry(plan)
    if emit_json(args, new_json(result, dry_run=False, applied=True)):
        return

    command_table(
        "Created note entry",
        [
            ("Created", rel(result["created"])),
            ("Parent", rel(result["parent"])),
            ("Entrypoint", rel(result["entrypoint"])),
            ("Include", f'#include "{result["include"]}"'),
            ("Include updated", "yes" if result["includeUpdated"] else "already present"),
        ],
    )


def plan_promote_file(path: str) -> dict[str, Any]:
    source = (ROOT / path).resolve()
    try:
        source.relative_to(SRC)
    except ValueError:
        fail("Promoted file must be under src/.")
    if not source.exists() or not source.is_file() or source.suffix != ".typ":
        fail(f"Not a Typst content file: {path}")
    if source.name == "index.typ":
        fail("Cannot promote an index.typ entrypoint.")

    parent = source.parent
    stem = source.stem
    match = PREFIX_RE.match(stem)
    if not match:
        fail("Promoted files must use a numeric prefix, e.g. 03_probability.typ.")

    target_dir = source.with_suffix("")
    if target_dir.exists():
        fail(f"Target directory already exists: {rel(target_dir)}")

    suffix = match.group("name")
    child = target_dir / f"00_{suffix}.typ"
    index = target_dir / "index.typ"
    original = source.read_text(encoding="utf-8")
    marker, title, body = split_promoted_content(original, heading_marker(parent), title_from_slug(stem))
    old_include = include_target_for_child(parent, source)
    new_include = include_target_for_child(parent, target_dir)
    entrypoint = entrypoint_for(parent)
    return {
        "source": source,
        "parent": parent,
        "targetDir": target_dir,
        "index": index,
        "child": child,
        "headingMarker": marker,
        "heading": title,
        "body": body,
        "oldInclude": old_include,
        "newInclude": new_include,
        "entrypoint": entrypoint,
    }


def promote_json(plan: dict[str, Any], *, dry_run: bool, applied: bool = False, include_status: str | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "promote",
        "dryRun": dry_run,
        "applied": applied,
        "source": plan["source"],
        "targetDir": plan["targetDir"],
        "index": plan["index"],
        "child": plan["child"],
        "heading": f'{plan["headingMarker"]} {plan["heading"]}',
        "entrypoint": plan["entrypoint"],
        "oldInclude": plan["oldInclude"],
        "newInclude": plan["newInclude"],
        "includeStatus": include_status,
    }


def apply_promote_file(plan: dict[str, Any]) -> str:
    target_dir: Path = plan["targetDir"]
    if target_dir.exists():
        fail(f"Target directory already exists: {rel(target_dir)}")
    target_dir.mkdir()
    plan["index"].write_text(
        f'{plan["headingMarker"]} {plan["heading"]}\n\n#include "{plan["child"].name}"\n',
        encoding="utf-8",
    )
    child_body = str(plan["body"]).strip("\n")
    plan["child"].write_text(f'{macro_import_for(plan["child"])}{child_body}\n', encoding="utf-8")
    include_status = replace_include(plan["entrypoint"], plan["oldInclude"], plan["newInclude"])
    plan["source"].unlink()
    return include_status


def cmd_promote(args: argparse.Namespace) -> None:
    ensure_repo()
    plan = plan_promote_file(args.path)

    if getattr(args, "dry_run", False):
        if emit_json(args, promote_json(plan, dry_run=True)):
            return
        command_table(
            "Promote preview",
            [
                ("Source", rel(plan["source"])),
                ("Create", rel(plan["index"])),
                ("Move body to", rel(plan["child"])),
                ("Heading", f'{plan["headingMarker"]} {plan["heading"]}'),
                ("Entrypoint", rel(plan["entrypoint"])),
                ("Include", f'#include "{plan["oldInclude"]}" → #include "{plan["newInclude"]}"'),
            ],
        )
        return

    if getattr(args, "confirm", False) is False and getattr(args, "interactive_confirm", False):
        if not Confirm.ask("Promote this file to a section directory?", default=True):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    include_status = apply_promote_file(plan)
    if emit_json(args, promote_json(plan, dry_run=False, applied=True, include_status=include_status)):
        return

    command_table(
        "Promoted section",
        [
            ("Created", rel(plan["index"])),
            ("Created", rel(plan["child"])),
            ("Removed", rel(plan["source"])),
            ("Entrypoint", f'{rel(plan["entrypoint"])} ({include_status})'),
        ],
    )


def numbered_children(directory: Path, include_high: bool = False) -> list[Path]:
    children: list[Path] = []
    for path in directory.iterdir():
        if path.name == "index.typ":
            continue
        stem = path.stem if path.is_file() else path.name
        match = PREFIX_RE.match(stem)
        if not match:
            continue
        if path.is_file() and path.suffix != ".typ":
            continue
        if not (path.is_file() or path.is_dir()):
            continue
        number = int(match.group("num"))
        if include_high or number < 90:
            children.append(path)
    return sorted(children, key=lambda p: p.name)


def renumber_plan(directory: Path, include_high: bool = False) -> list[tuple[Path, Path]]:
    plan: list[tuple[Path, Path]] = []
    for i, path in enumerate(numbered_children(directory, include_high=include_high)):
        stem = path.stem if path.is_file() else path.name
        match = PREFIX_RE.match(stem)
        if not match:
            continue
        suffix = match.group("name")
        new_name = f"{i:02d}_{suffix}{path.suffix if path.is_file() else ''}"
        new_path = path.with_name(new_name)
        if new_path != path:
            plan.append((path, new_path))
    return plan


def update_entrypoint_after_renames(directory: Path, plan: list[tuple[Path, Path]]) -> None:
    entrypoint = entrypoint_for(directory)
    if not entrypoint.exists():
        return
    text = entrypoint.read_text(encoding="utf-8")
    for old, new in plan:
        old_target = include_target_for_child(directory, old)
        new_target = include_target_for_child(directory, new)
        text = text.replace(f'"{old_target}"', f'"{new_target}"')
    entrypoint.write_text(text, encoding="utf-8")


def show_plan(title: str, plan: list[tuple[Path, Path]]) -> None:
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Old", style="red")
    table.add_column("New", style="green")
    for old, new in plan:
        table.add_row(rel(old), rel(new))
    console.print(table)


def collect_renumber_plans(directory: Path, include_high: bool, recursive: bool) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    if recursive:
        for child in numbered_children(directory, include_high=True):
            if child.is_dir():
                plans.extend(collect_renumber_plans(child, include_high=include_high, recursive=True))
    renames = renumber_plan(directory, include_high=include_high)
    if renames:
        plans.append({"directory": directory, "entrypoint": entrypoint_for(directory), "renames": renames})
    return plans


def renumber_json(plans: list[dict[str, Any]], *, directory: Path, dry_run: bool, recursive: bool, include_high: bool, applied: bool = False) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "renumber",
        "dryRun": dry_run,
        "applied": applied,
        "directory": directory,
        "recursive": recursive,
        "includeHigh": include_high,
        "changes": sum(len(plan["renames"]) for plan in plans),
        "plans": [
            {
                "directory": plan["directory"],
                "entrypoint": plan["entrypoint"],
                "renames": [{"old": old, "new": new} for old, new in plan["renames"]],
            }
            for plan in plans
        ],
    }


def check_renumber_conflicts(plans: list[dict[str, Any]]) -> None:
    old_paths = {old.resolve() for plan in plans for old, _ in plan["renames"]}
    for plan in plans:
        for _, new in plan["renames"]:
            if new.exists() and new.resolve() not in old_paths:
                fail(f"Cannot rename into existing path: {rel(new)}")


def apply_renumber_plan(plan: dict[str, Any]) -> None:
    renames: list[tuple[Path, Path]] = plan["renames"]
    temp_plan: list[tuple[Path, Path]] = []
    for old, _ in renames:
        tmp = old.with_name(f".__renumber_tmp__{old.name}")
        if tmp.exists():
            fail(f"Temporary rename path already exists: {rel(tmp)}")
        old.rename(tmp)
        temp_plan.append((tmp, next(new for candidate_old, new in renames if candidate_old == old)))
    for tmp, new in temp_plan:
        tmp.rename(new)
    update_entrypoint_after_renames(plan["directory"], renames)


def apply_renumber_batch(plans: list[dict[str, Any]]) -> None:
    check_renumber_conflicts(plans)
    for plan in plans:
        apply_renumber_plan(plan)


def show_renumber_plans(plans: list[dict[str, Any]], directory: Path) -> None:
    if not plans:
        console.print(f"[green]Already numbered:[/green] {rel(directory)}")
        return
    for plan in plans:
        show_plan(f"Renumber {rel(plan['directory'])}", plan["renames"])


def cmd_renumber(args: argparse.Namespace) -> None:
    ensure_repo()
    directory = safe_src_dir(args.directory)
    plans = collect_renumber_plans(directory, include_high=args.all, recursive=args.recursive)

    if args.dry_run:
        if emit_json(args, renumber_json(plans, directory=directory, dry_run=True, recursive=args.recursive, include_high=args.all)):
            return
        show_renumber_plans(plans, directory)
        return

    check_renumber_conflicts(plans)
    if getattr(args, "json", None) is not None:
        apply_renumber_batch(plans)
        emit_json(args, renumber_json(plans, directory=directory, dry_run=False, recursive=args.recursive, include_high=args.all, applied=True))
        return

    show_renumber_plans(plans, directory)
    if not plans:
        return
    apply_renumber_batch(plans)
    for plan in plans:
        console.print(f"[green]Updated[/green] {rel(plan['entrypoint'])}")


def includes_in(path: Path) -> list[str]:
    if not path.exists():
        return []
    includes: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = INCLUDE_RE.match(line)
        if match:
            includes.append(match.group(1))
    return includes


def validate_immediate_include(entrypoint: Path, include: str) -> str | None:
    if include.startswith("../") or "/../" in include:
        return "includes a parent path"
    base = SRC if entrypoint == MAIN else entrypoint.parent
    target = (base / include).resolve() if entrypoint != MAIN else (ROOT / include).resolve()
    if not target.exists():
        return "target does not exist"
    try:
        target.relative_to(SRC)
    except ValueError:
        return "target is outside src/"

    if entrypoint == MAIN:
        rel_target = target.relative_to(SRC)
        ok_file = len(rel_target.parts) == 1 and target.suffix == ".typ"
        ok_index = len(rel_target.parts) == 2 and rel_target.parts[1] == "index.typ"
        if not (ok_file or ok_index):
            return "main.typ may include only src/*.typ or src/*/index.typ"
    else:
        rel_target = target.relative_to(entrypoint.parent)
        ok_file = len(rel_target.parts) == 1 and target.suffix == ".typ" and target.name != "index.typ"
        ok_index = len(rel_target.parts) == 2 and rel_target.parts[1] == "index.typ"
        if not (ok_file or ok_index):
            return "index.typ may include only immediate children"
    return None


def resolve_include(entrypoint: Path, include: str) -> Path:
    base = ROOT if entrypoint == MAIN else entrypoint.parent
    return (base / include).resolve()


def all_entrypoints() -> list[Path]:
    return [MAIN] + sorted(SRC.rglob("index.typ"), key=lambda p: rel(p))


def expected_includes_for(directory: Path) -> list[str]:
    expected: list[str] = []
    for child in sorted(directory.iterdir(), key=lambda p: p.name):
        if child.name.startswith(".") or child.name == "index.typ":
            continue
        if child.is_file() and child.suffix == ".typ":
            expected.append(include_target_for_child(directory, child))
        elif child.is_dir() and (child / "index.typ").exists():
            expected.append(include_target_for_child(directory, child))
    return expected


def referenced_images(path: Path) -> list[str]:
    if not path.exists() or path.suffix != ".typ":
        return []
    return IMAGE_RE.findall(path.read_text(encoding="utf-8"))


def issue_table(issues: list[tuple[str, str]]) -> None:
    table = Table(title="Doctor found issues", show_header=True, header_style="bold red")
    table.add_column("Path", style="cyan")
    table.add_column("Issue", style="red")
    for path, issue in issues:
        table.add_row(path, issue)
    console.print(table)


def collect_doctor_issues() -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []

    if not CONFIG.exists():
        issues.append(("notes.toml", "metadata config file is missing"))
    if not (ROOT / "refs.bib").exists():
        issues.append(("refs.bib", "bibliography file is missing"))

    directories = [SRC] + sorted((p for p in SRC.rglob("*") if p.is_dir()), key=lambda p: rel(p))
    for directory in directories:
        if directory != SRC and not (directory / "index.typ").exists():
            issues.append((rel(directory), "directory is missing index.typ"))
        if directory != SRC:
            stem = directory.name
            if stem != "90_appendix" and not PREFIX_RE.match(stem):
                issues.append((rel(directory), "directory name should start with a two-digit numeric prefix"))
        for child in directory.iterdir():
            if child.name.startswith(".") or child.name == "index.typ":
                continue
            if child.is_file() and child.suffix == ".typ" and not PREFIX_RE.match(child.stem):
                issues.append((rel(child), "content file name should start with a two-digit numeric prefix"))

    include_parents: dict[Path, list[Path]] = {}
    graph: dict[Path, list[Path]] = {}

    for entrypoint in all_entrypoints():
        includes = includes_in(entrypoint)
        graph[entrypoint] = [resolve_include(entrypoint, include) for include in includes]

        counts = Counter(includes)
        for include, count in counts.items():
            if count > 1:
                issues.append((rel(entrypoint), f'duplicate include appears {count} times: #include "{include}"'))

        if includes != sorted(includes):
            issues.append((rel(entrypoint), "include order should match numeric/lexicographic order"))

        for include in includes:
            issue = validate_immediate_include(entrypoint, include)
            if issue:
                issues.append((rel(entrypoint), f'{issue}: #include "{include}"'))
                continue
            target = resolve_include(entrypoint, include)
            include_parents.setdefault(target, []).append(entrypoint)

        directory = SRC if entrypoint == MAIN else entrypoint.parent
        for expected in expected_includes_for(directory):
            if expected not in includes:
                issues.append((rel(entrypoint), f'orphan immediate child is not included: #include "{expected}"'))

    for path, parents in include_parents.items():
        if len(parents) > 1:
            parent_list = ", ".join(rel(parent) for parent in parents)
            issues.append((rel(path), f"included by multiple parents: {parent_list}"))

    for content_file in sorted(SRC.rglob("*.typ"), key=lambda p: rel(p)):
        if content_file.name != "index.typ" and includes_in(content_file):
            issues.append((rel(content_file), "content files must not contain #include directives"))
        for image_path in referenced_images(content_file):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", image_path):
                continue
            target = (content_file.parent / image_path).resolve()
            try:
                target.relative_to(ROOT)
            except ValueError:
                issues.append((rel(content_file), f'image reference escapes repository: image("{image_path}")'))
                continue
            if not target.exists():
                issues.append((rel(content_file), f'missing image asset: image("{image_path}")'))

    visiting: set[Path] = set()
    visited: set[Path] = set()

    def dfs(path: Path, stack: list[Path]) -> None:
        if path in visiting:
            cycle = " -> ".join(rel(p) for p in stack + [path])
            issues.append((rel(path), f"include cycle detected: {cycle}"))
            return
        if path in visited:
            return
        visiting.add(path)
        for target in graph.get(path, []):
            if target.name == "index.typ":
                dfs(target, stack + [path])
        visiting.remove(path)
        visited.add(path)

    dfs(MAIN, [])
    return issues


def doctor_json(issues: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "ok": not issues,
        "issues": [{"path": path, "issue": issue} for path, issue in issues],
    }


def cmd_doctor(args: argparse.Namespace) -> None:
    ensure_repo()
    issues = collect_doctor_issues()
    if emit_json(args, doctor_json(issues)):
        if issues:
            raise SystemExit(1)
        return
    if issues:
        issue_table(issues)
        raise SystemExit(1)

    console.print(Panel.fit("Include graph and section layout look good.", title="Doctor", border_style="green"))


def add_include_tree(node: Tree, entrypoint: Path, seen: set[Path]) -> None:
    if entrypoint in seen:
        node.add(f"[red]{rel(entrypoint)} (cycle)[/red]")
        return
    seen.add(entrypoint)
    for include in includes_in(entrypoint):
        target = resolve_include(entrypoint, include)
        label = rel(target) if target.exists() else f"{include} [red](missing)[/red]"
        branch = node.add(f"[green]{label}[/green]" if target.exists() else label)
        if target.name == "index.typ" and target.exists():
            add_include_tree(branch, target, seen.copy())


def markdown_include_lines(entrypoint: Path, depth: int = 0, seen: set[Path] | None = None) -> list[str]:
    seen = set() if seen is None else seen
    lines = [f"{'  ' * depth}- `{rel(entrypoint)}`"]
    if entrypoint in seen:
        lines[-1] += " **cycle**"
        return lines
    seen.add(entrypoint)
    for include in includes_in(entrypoint):
        target = resolve_include(entrypoint, include)
        if target.exists() and target.name == "index.typ":
            lines.extend(markdown_include_lines(target, depth + 1, seen.copy()))
        else:
            label = rel(target) if target.exists() else f"{include} (missing)"
            lines.append(f"{'  ' * (depth + 1)}- `{label}`")
    return lines


def include_map_data(entrypoint: Path, seen: set[Path] | None = None) -> dict[str, Any]:
    seen = set() if seen is None else seen
    node: dict[str, Any] = {
        "path": rel(entrypoint) if entrypoint.exists() else entrypoint.as_posix(),
        "exists": entrypoint.exists(),
        "entrypoint": entrypoint.name == "index.typ" or entrypoint == MAIN,
        "children": [],
    }
    if entrypoint in seen:
        node["cycle"] = True
        return node
    seen.add(entrypoint)
    for include in includes_in(entrypoint):
        target = resolve_include(entrypoint, include)
        child = {
            "include": include,
            "path": rel(target) if target.exists() else include,
            "exists": target.exists(),
            "entrypoint": target.name == "index.typ",
            "children": [],
        }
        if target.exists() and target.name == "index.typ":
            nested = include_map_data(target, seen.copy())
            child["children"] = nested["children"]
            if nested.get("cycle"):
                child["cycle"] = True
        node["children"].append(child)
    return node


def cmd_map(args: argparse.Namespace) -> None:
    ensure_repo()
    output = getattr(args, "write", None)
    wrote: str | None = None
    if output:
        path = (ROOT / output).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError:
            fail("Map output path must stay inside the repository.")
        content = "# Include Map\n\n" + "\n".join(markdown_include_lines(MAIN)) + "\n"
        path.write_text(content, encoding="utf-8")
        wrote = rel(path)

    if emit_json(args, {"ok": True, "root": MAIN, "wrote": wrote, "tree": include_map_data(MAIN)}):
        return

    tree = Tree(f"[bold cyan]{rel(MAIN)}[/bold cyan]")
    add_include_tree(tree, MAIN, set())
    console.print(tree)
    if wrote:
        console.print(f"[green]Wrote[/green] {wrote}")


def src_directories() -> list[Path]:
    dirs = [SRC]
    dirs.extend(sorted((path for path in SRC.rglob("*") if path.is_dir()), key=lambda p: rel(p)))
    return dirs


def choose_src_directory(title: str, default: Path | None = None) -> Path:
    directories = src_directories()
    default_index = directories.index(default) if default in directories else 0

    while True:
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("#", justify="right", style="cyan", no_wrap=True)
        table.add_column("Directory", style="white")
        table.add_column("Entrypoint", style="dim")
        table.add_column("Children", justify="right", style="magenta")
        for i, directory in enumerate(directories):
            table.add_row(
                str(i),
                rel(directory),
                rel(entrypoint_for(directory)),
                str(len(numbered_children(directory, include_high=True))),
            )
        console.print(table)

        answer = Prompt.ask("Directory number or path", default=str(default_index)).strip()
        if answer.isdigit() and int(answer) < len(directories):
            return directories[int(answer)]

        candidate = (ROOT / answer).resolve()
        try:
            candidate.relative_to(SRC)
        except ValueError:
            console.print("[red]Directory must be under src/.[/red]")
            continue
        if not candidate.exists() or not candidate.is_dir():
            console.print(f"[red]Directory does not exist:[/red] {answer}")
            continue
        return candidate


def src_content_files() -> list[Path]:
    return sorted(
        (path for path in SRC.rglob("*.typ") if path.name != "index.typ"),
        key=lambda p: rel(p),
    )


def choose_src_file(title: str) -> Path:
    files = src_content_files()
    if not files:
        fail("No content files found under src/.")
    while True:
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("#", justify="right", style="cyan", no_wrap=True)
        table.add_column("File", style="white")
        for i, path in enumerate(files):
            table.add_row(str(i), rel(path))
        console.print(table)

        answer = Prompt.ask("File number or path", default="0").strip()
        if answer.isdigit() and int(answer) < len(files):
            return files[int(answer)]

        candidate = (ROOT / answer).resolve()
        try:
            candidate.relative_to(SRC)
        except ValueError:
            console.print("[red]File must be under src/.[/red]")
            continue
        if not candidate.exists() or not candidate.is_file() or candidate.suffix != ".typ" or candidate.name == "index.typ":
            console.print(f"[red]Not a promotable content file:[/red] {answer}")
            continue
        return candidate


def next_number(directory: Path) -> int:
    numbers: list[int] = []
    for child in numbered_children(directory, include_high=False):
        stem = child.stem if child.is_file() else child.name
        match = PREFIX_RE.match(stem)
        if match:
            numbers.append(int(match.group("num")))
    return max(numbers, default=-1) + 1


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = PREFIX_RE.sub(lambda m: m.group("name"), value)
    value = re.sub(r"\.typ$", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    if not value:
        fail("Slug/title cannot be empty.")
    return value


def target_exists(parent: Path, base: str, is_section: bool) -> bool:
    return (parent / base).exists() if is_section else (parent / f"{base}.typ").exists()


def interactive_slug(parent: Path, raw: str, is_section: bool) -> str:
    raw = raw.strip().strip("/")
    if raw.endswith(".typ"):
        raw = raw[:-4]
    if re.match(r"^[0-9]{2}_", raw):
        base, _ = validate_slug(raw, force_section=is_section)
        return base

    name = slugify(raw)
    number = next_number(parent)
    while True:
        base = f"{number:02d}_{name}"
        if not target_exists(parent, base, is_section):
            return base
        number += 1


def pause() -> None:
    Prompt.ask("[dim]Press Enter to continue[/dim]", default="")


def structure_data(directory: Path) -> dict[str, Any]:
    children: list[dict[str, Any]] = []
    for child in sorted(directory.iterdir(), key=lambda p: p.name):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            children.append(structure_data(child))
        elif child.suffix == ".typ":
            children.append({"name": child.name, "path": child, "type": "file"})
    return {"name": directory.name, "path": directory, "type": "directory", "children": children}


def cmd_structure(args: argparse.Namespace) -> None:
    ensure_repo()

    def add_children(node: Tree, directory: Path) -> None:
        children = sorted(directory.iterdir(), key=lambda p: p.name)
        for child in children:
            if child.name.startswith("."):
                continue
            if child.is_dir():
                branch = node.add(f"[bold cyan]{child.name}/[/bold cyan]")
                add_children(branch, child)
            elif child.suffix == ".typ":
                node.add(f"[green]{child.name}[/green]")

    if emit_json(args, {"ok": True, "root": SRC, "tree": structure_data(SRC)}):
        return

    tree = Tree(f"[bold cyan]{rel(SRC)}/[/bold cyan]")
    add_children(tree, SRC)
    console.print(tree)


def typst_project_files() -> list[Path]:
    files = [MAIN, ROOT / "template.typ", ROOT / "macros.typ"]
    files.extend(sorted(SRC.rglob("*.typ"), key=lambda p: rel(p)))
    return [path for path in files if path.exists()]


def strip_line_comment(line: str) -> str:
    return line.split("//", 1)[0]


def collect_labels() -> dict[str, Any]:
    labels: dict[str, list[dict[str, Any]]] = {}
    references: list[dict[str, Any]] = []
    label_re = re.compile(r"<([A-Za-z0-9_:-][A-Za-z0-9_:.:-]*)>")
    ref_re = re.compile(r"@([A-Za-z0-9_:-][A-Za-z0-9_:.:-]*)")
    bib_keys = {entry["key"] for entry in collect_bib_entries()["entries"]}
    for path in typst_project_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            text = strip_line_comment(line)
            for match in label_re.finditer(text):
                labels.setdefault(match.group(1), []).append({"path": path, "line": line_number})
            for match in ref_re.finditer(text):
                key = match.group(1)
                if key not in bib_keys:
                    references.append({"key": key, "path": path, "line": line_number})
    defined = set(labels)
    unresolved = [ref for ref in references if ref["key"] not in defined]
    duplicates = [{"key": key, "definitions": locs} for key, locs in labels.items() if len(locs) > 1]
    return {"labels": labels, "references": references, "unresolved": unresolved, "duplicates": duplicates}


def collect_bib_entries() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if (ROOT / "refs.bib").exists():
        text = (ROOT / "refs.bib").read_text(encoding="utf-8")
        for match in re.finditer(r"@([A-Za-z]+)\s*\{\s*([^,\s]+)", text):
            line = text.count("\n", 0, match.start()) + 1
            entries.append({"type": match.group(1), "key": match.group(2), "path": ROOT / "refs.bib", "line": line})
    return {"entries": entries}


def collect_bib() -> dict[str, Any]:
    bib = collect_bib_entries()
    keys = {entry["key"] for entry in bib["entries"]}
    labels = set(collect_labels()["labels"])
    all_refs: list[dict[str, Any]] = []
    for path in typst_project_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in re.finditer(r"@([A-Za-z0-9_:-][A-Za-z0-9_:.:-]*)", strip_line_comment(line)):
                all_refs.append({"key": match.group(1), "path": path, "line": line_number})
    citations = [ref for ref in all_refs if ref["key"] in keys]
    cited_keys = {ref["key"] for ref in citations}
    unknown = [ref for ref in all_refs if ref["key"] not in keys and ref["key"] not in labels]
    uncited = [entry for entry in bib["entries"] if entry["key"] not in cited_keys]
    return {**bib, "citations": citations, "unknownCitations": unknown, "uncitedEntries": uncited}


def collect_assets() -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    for path in typst_project_files():
        if path.suffix != ".typ":
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for image_path in IMAGE_RE.findall(strip_line_comment(line)):
                external = bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", image_path))
                target = None if external else (path.parent / image_path).resolve()
                references.append(
                    {
                        "path": path,
                        "line": line_number,
                        "reference": image_path,
                        "external": external,
                        "target": target,
                        "exists": external or (target.exists() if target else False),
                    }
                )
    asset_files: list[Path] = []
    for directory in (ROOT / "assets" / "figures", ROOT / "assets" / "images"):
        if directory.exists():
            asset_files.extend(sorted((path for path in directory.rglob("*") if path.is_file()), key=lambda p: rel(p)))
    referenced_targets = {ref["target"].resolve() for ref in references if ref.get("target") and ref.get("exists")}
    unreferenced = [path for path in asset_files if path.resolve() not in referenced_targets]
    missing = [ref for ref in references if not ref["external"] and not ref["exists"]]
    return {"references": references, "assetFiles": asset_files, "missing": missing, "unreferenced": unreferenced}


def cmd_metadata(args: argparse.Namespace) -> None:
    ensure_repo()
    before = load_metadata()
    changes = {key: getattr(args, key) for key in ("title", "author", "date") if getattr(args, key) is not None}
    after = {**before, **changes}
    if not changes:
        payload = {"ok": True, "action": "metadata", "dryRun": True, "applied": False, "metadata": before, "config": CONFIG}
        if emit_json(args, payload):
            return
        command_table("Document metadata", [(key, before.get(key, "")) for key in ("title", "author", "date")])
        return

    payload = {
        "ok": True,
        "action": "metadata_update",
        "dryRun": args.dry_run,
        "applied": not args.dry_run,
        "config": CONFIG,
        "before": before,
        "after": after,
        "changes": changes,
    }
    if args.dry_run:
        if emit_json(args, payload):
            return
        command_table("Metadata update preview", [(key, value) for key, value in changes.items()])
        return

    write_metadata(after)
    if emit_json(args, payload):
        return
    command_table("Updated metadata", [(key, after.get(key, "")) for key in ("title", "author", "date")])


def cmd_labels(args: argparse.Namespace) -> None:
    ensure_repo()
    data = collect_labels()
    payload = {"ok": True, **data}
    if emit_json(args, payload):
        return
    table = Table(title="Typst labels", show_header=True, header_style="bold cyan")
    table.add_column("Label", style="cyan")
    table.add_column("Definitions", style="white")
    table.add_column("References", justify="right", style="magenta")
    refs = Counter(ref["key"] for ref in data["references"])
    for key, locs in sorted(data["labels"].items()):
        table.add_row(key, ", ".join(f"{rel(loc['path'])}:{loc['line']}" for loc in locs), str(refs[key]))
    console.print(table)
    if data["unresolved"]:
        issue_table([(f"{rel(ref['path'])}:{ref['line']}", f"unresolved label reference @{ref['key']}") for ref in data["unresolved"]])


def cmd_bib(args: argparse.Namespace) -> None:
    ensure_repo()
    data = collect_bib()
    payload = {"ok": True, **data}
    if emit_json(args, payload):
        return
    table = Table(title="Bibliography", show_header=True, header_style="bold cyan")
    table.add_column("Key", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("Citations", justify="right", style="magenta")
    citations = Counter(ref["key"] for ref in data["citations"])
    for entry in data["entries"]:
        table.add_row(entry["key"], entry["type"], str(citations[entry["key"]]))
    console.print(table)
    if data["unknownCitations"]:
        issue_table([(f"{rel(ref['path'])}:{ref['line']}", f"unknown citation @{ref['key']}") for ref in data["unknownCitations"]])


def cmd_assets(args: argparse.Namespace) -> None:
    ensure_repo()
    data = collect_assets()
    payload = {"ok": True, **data}
    if emit_json(args, payload):
        return
    table = Table(title="Image assets", show_header=True, header_style="bold cyan")
    table.add_column("Reference", style="cyan")
    table.add_column("Source", style="white")
    table.add_column("Target", style="white")
    table.add_column("Status", style="magenta")
    for ref_data in data["references"]:
        target = "external" if ref_data["external"] else rel(ref_data["target"])
        table.add_row(ref_data["reference"], f"{rel(ref_data['path'])}:{ref_data['line']}", target, "ok" if ref_data["exists"] else "missing")
    console.print(table)
    if data["missing"]:
        issue_table([(f"{rel(ref['path'])}:{ref['line']}", f"missing image asset: image(\"{ref['reference']}\")") for ref in data["missing"]])


def interactive_new() -> None:
    parent = choose_src_directory("Choose where the new entry should live")
    kind = Prompt.ask("Create a file or section directory?", choices=["file", "section"], default="file")
    is_section = kind == "section"
    raw = Prompt.ask("Slug or title (numeric prefix optional)", default=f"{next_number(parent):02d}_new_topic")
    base = interactive_slug(parent, raw, is_section)
    default_title = title_from_slug(base)
    title = Prompt.ask("Heading title", default=default_title).strip()
    slug_arg = f"{base}/" if is_section else base
    target = parent / base / "index.typ" if is_section else parent / f"{base}.typ"
    include_target = include_target_for_child(parent, target.parent if is_section else target)

    command_table(
        "New entry preview",
        [
            ("Kind", "section directory" if is_section else "content file"),
            ("Create", rel(target)),
            ("Heading", title),
            ("Entrypoint", rel(entrypoint_for(parent))),
            ("Include", f'#include "{include_target}"'),
        ],
    )
    if not Confirm.ask("Create this entry and update the include?", default=True):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    cmd_new(argparse.Namespace(directory=rel(parent), slug=slug_arg, title=[title], section=False, dry_run=False, json=None))


def interactive_promote() -> None:
    source = choose_src_file("Choose a content file to promote")
    cmd_promote(
        argparse.Namespace(path=rel(source), dry_run=True, confirm=False, interactive_confirm=False, skip_preview=False, json=None)
    )
    if Confirm.ask("Promote this file to a section directory?", default=True):
        cmd_promote(
            argparse.Namespace(path=rel(source), dry_run=False, confirm=False, interactive_confirm=False, skip_preview=True, json=None)
        )
    else:
        console.print("[yellow]No files changed.[/yellow]")


def renumber_has_changes(directory: Path, include_high: bool, recursive: bool) -> bool:
    return bool(collect_renumber_plans(directory, include_high=include_high, recursive=recursive))


def interactive_renumber() -> None:
    directory = choose_src_directory("Choose directory to renumber")
    recursive = Confirm.ask("Renumber nested section directories too?", default=False)
    include_high = Confirm.ask("Include high-numbered sections such as 90_appendix?", default=False)

    console.rule("Dry run")
    cmd_renumber(
        argparse.Namespace(directory=rel(directory), recursive=recursive, all=include_high, dry_run=True, json=None)
    )
    if not renumber_has_changes(directory, include_high=include_high, recursive=recursive):
        return
    if Confirm.ask("Apply this renumber plan?", default=False):
        cmd_renumber(
            argparse.Namespace(directory=rel(directory), recursive=recursive, all=include_high, dry_run=False, json=None)
        )
    else:
        console.print("[yellow]No files changed.[/yellow]")


def interactive_serve() -> None:
    port = IntPrompt.ask("Localhost port", default=8000)
    cmd_serve(argparse.Namespace(port=port))


def interactive_clean() -> None:
    if Confirm.ask("Remove generated preview outputs from out/?", default=True):
        cmd_clean(argparse.Namespace())
    else:
        console.print("[yellow]Cancelled.[/yellow]")


def interactive_menu() -> str:
    console.print(
        Panel.fit(
            "[bold]Typst Notes Template[/bold]\n"
            "Create sections, maintain numbering, validate the include graph, and preview the PDF.",
            title="Notes CLI",
            border_style="cyan",
        )
    )
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Choice", style="bold cyan", no_wrap=True)
    table.add_column("Action", style="white")
    table.add_row("1", "Create a new note file or section")
    table.add_row("2", "Promote a file to a section directory")
    table.add_row("3", "Renumber a directory")
    table.add_row("4", "Show include map")
    table.add_row("5", "Show src/ structure")
    table.add_row("6", "Validate include graph")
    table.add_row("7", "Build PDF")
    table.add_row("8", "Serve live browser preview")
    table.add_row("9", "Watch and rebuild")
    table.add_row("10", "Clean generated output")
    table.add_row("q", "Quit")
    console.print(table)
    return Prompt.ask("Choose an action", choices=["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "q"], default="1")


def cmd_interactive(_: argparse.Namespace) -> None:
    ensure_repo()
    try:
        while True:
            choice = interactive_menu()
            try:
                if choice == "1":
                    interactive_new()
                    pause()
                elif choice == "2":
                    interactive_promote()
                    pause()
                elif choice == "3":
                    interactive_renumber()
                    pause()
                elif choice == "4":
                    cmd_map(argparse.Namespace(write=None, json=None))
                    pause()
                elif choice == "5":
                    cmd_structure(argparse.Namespace(json=None))
                    pause()
                elif choice == "6":
                    cmd_doctor(argparse.Namespace(json=None))
                    pause()
                elif choice == "7":
                    cmd_build(argparse.Namespace(inputs=[], title=None, author=None, date=None))
                    pause()
                elif choice == "8":
                    interactive_serve()
                    pause()
                elif choice == "9":
                    cmd_watch(argparse.Namespace())
                    pause()
                elif choice == "10":
                    interactive_clean()
                    pause()
                elif choice == "q":
                    console.print("[green]Goodbye.[/green]")
                    return
            except SystemExit as exc:
                if exc.code not in (0, None):
                    console.print(f"[red]Action failed with exit code {exc.code}.[/red]")
                pause()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Goodbye.[/yellow]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notes",
        description="Rich CLI for this Typst notes template.",
        formatter_class=RichHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    interactive = sub.add_parser("interactive", aliases=["ui", "menu"], help="open the fully interactive menu")
    interactive.set_defaults(func=cmd_interactive)

    structure = sub.add_parser("structure", aliases=["tree"], help="show the src/ content tree")
    add_json_argument(structure)
    structure.set_defaults(func=cmd_structure)

    map_cmd = sub.add_parser("map", help="show the include graph rooted at main.typ")
    map_cmd.add_argument("--write", metavar="PATH", help="also write the include map as Markdown")
    add_json_argument(map_cmd)
    map_cmd.set_defaults(func=cmd_map)

    build = sub.add_parser("build", help="compile main.typ to out/main.pdf")
    add_typst_input_arguments(build)
    build.set_defaults(func=cmd_build)

    check = sub.add_parser("check", help="compile once to a temporary output and report success/failure")
    add_typst_input_arguments(check)
    check.set_defaults(func=cmd_check)

    watch = sub.add_parser("watch", help="rebuild automatically when Typst files change")
    watch.set_defaults(func=cmd_watch)

    serve = sub.add_parser("serve", help="serve localhost preview with browser auto-refresh")
    serve.add_argument("--port", type=int, default=8000, help="localhost port to serve")
    serve.set_defaults(func=cmd_serve)

    clean = sub.add_parser("clean", help="remove generated preview outputs")
    clean.set_defaults(func=cmd_clean)

    new = sub.add_parser("new", help="create a content file or section and update includes")
    new.add_argument("directory", help="parent directory under src/, e.g. src or src/03_probability")
    new.add_argument("slug", help="02_topic for a file, 03_topic/ for a section")
    new.add_argument("title", nargs="*", help="optional heading title; inferred from slug by default")
    new.add_argument("--section", action="store_true", help="create a section directory even without trailing slash")
    new.add_argument("--dry-run", action="store_true", help="preview without changing files")
    add_json_argument(new)
    new.set_defaults(func=cmd_new)

    promote = sub.add_parser("promote", help="promote a content file to a section directory")
    promote.add_argument("path", help="content file under src/ to promote, e.g. src/03_probability.typ")
    promote.add_argument("--dry-run", action="store_true", help="preview without changing files")
    add_json_argument(promote)
    promote.set_defaults(func=cmd_promote)

    renumber = sub.add_parser("renumber", help="renumber immediate numbered children and update includes")
    renumber.add_argument("directory", nargs="?", default="src", help="directory under src/ to renumber")
    renumber.add_argument("--dry-run", action="store_true", help="show the rename plan without changing files")
    renumber.add_argument("--recursive", action="store_true", help="also renumber child section directories")
    renumber.add_argument("--all", action="store_true", help="include high-numbered sections such as 90_appendix")
    add_json_argument(renumber)
    renumber.set_defaults(func=cmd_renumber)

    metadata = sub.add_parser("metadata", aliases=["metadata-update"], help="show or update notes.toml document metadata")
    metadata.add_argument("--title", help="set the default document title")
    metadata.add_argument("--author", help="set the default author; use an empty string to omit")
    metadata.add_argument("--date", help="set the default visible date; use an empty string to omit")
    metadata.add_argument("--dry-run", action="store_true", help="preview without changing notes.toml")
    add_json_argument(metadata)
    metadata.set_defaults(func=cmd_metadata)

    labels = sub.add_parser("labels", help="summarize Typst labels and non-bibliography references")
    add_json_argument(labels)
    labels.set_defaults(func=cmd_labels)

    bib = sub.add_parser("bib", aliases=["bibliography"], help="summarize refs.bib entries and citations")
    add_json_argument(bib)
    bib.set_defaults(func=cmd_bib)

    assets = sub.add_parser("assets", help="summarize image asset references")
    add_json_argument(assets)
    assets.set_defaults(func=cmd_assets)

    doctor = sub.add_parser("doctor", help="validate include graph conventions")
    add_json_argument(doctor)
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main() -> None:
    global JSON_MODE
    parser = build_parser()
    args = parser.parse_args()
    JSON_MODE = getattr(args, "json", None) is not None
    if not hasattr(args, "func"):
        cmd_interactive(argparse.Namespace())
        return
    args.func(args)


if __name__ == "__main__":
    main()
