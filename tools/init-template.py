#!/usr/bin/env python3
"""Initialize a new notes project from this template."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".jj",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "out",
}
EXCLUDED_FILES = {".DS_Store"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy this Typst notes template into a new project directory.",
    )
    parser.add_argument("target", nargs="?", help="Directory to create for the new notes project")
    parser.add_argument("title", nargs="?", help="Document title to write to notes.toml")
    parser.add_argument("--author", default="", help="Document author; empty omits it from the title block")
    parser.add_argument("--date", default="", help="Document date; empty omits it from the title block")
    parser.add_argument(
        "--vcs",
        choices=("none", "jj", "git"),
        default="none",
        help="Optionally initialize a fresh VCS repository in the new project",
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="Skip post-copy `just doctor` and `just check` validation",
    )
    return parser.parse_args()


def should_ignore(_dir: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in EXCLUDED_DIRS or name in EXCLUDED_FILES:
            ignored.add(name)
    return ignored


def toml_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def write_metadata(project: Path, title: str, author: str, date: str) -> None:
    notes = project / "notes.toml"
    notes.write_text(
        "# Document metadata defaults for main.typ.\n"
        "# Empty author/date values are omitted from the title block.\n"
        "# Override per compile with: typst compile --input title=... --input date=...\n\n"
        "[metadata]\n"
        f"title = {toml_string(title)}\n"
        f"author = {toml_string(author)}\n"
        f"date = {toml_string(date)}\n",
        encoding="utf-8",
    )


def run(cmd: list[str], cwd: Path, optional: bool = False) -> None:
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except FileNotFoundError:
        if optional:
            print(f"warning: skipped missing command: {cmd[0]}", file=sys.stderr)
            return
        raise


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_choice(prompt: str, choices: tuple[str, ...], default: str) -> str:
    while True:
        value = ask(f"{prompt} ({'/'.join(choices)})", default)
        if value in choices:
            return value
        print(f"Please choose one of: {', '.join(choices)}")


def fill_interactive(args: argparse.Namespace) -> argparse.Namespace:
    if args.target and args.title:
        return args

    print("Initialize a new Typst notes project")
    if not args.target:
        args.target = ask("Target directory")
    if not args.title:
        default_title = Path(args.target).expanduser().name.replace("-", " ").replace("_", " ").title()
        args.title = ask("Document title", default_title)
    args.author = ask("Author (empty to omit)", args.author)
    args.date = ask("Date (empty to omit)", args.date)
    args.vcs = ask_choice("Initialize VCS", ("none", "jj", "git"), args.vcs)
    check_choice = ask_choice("Run doctor and check", ("yes", "no"), "no" if args.no_check else "yes")
    args.no_check = check_choice == "no"
    return args


def main() -> int:
    args = fill_interactive(parse_args())
    template_root = Path(__file__).resolve().parents[1]
    target = Path(args.target).expanduser().resolve()

    if target.exists() and any(target.iterdir()):
        print(f"error: target exists and is not empty: {target}", file=sys.stderr)
        return 2
    if target == template_root or template_root in target.parents:
        print("error: target must not be inside the template repository", file=sys.stderr)
        return 2

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_root, target, ignore=should_ignore, dirs_exist_ok=target.exists())
    write_metadata(target, args.title, args.author, args.date)

    if args.vcs == "jj":
        run(["jj", "git", "init", "--colocate"], cwd=target, optional=True)
    elif args.vcs == "git":
        run(["git", "init"], cwd=target, optional=True)

    if not args.no_check:
        run(["just", "doctor"], cwd=target)
        run(["just", "check"], cwd=target)

    print(f"initialized notes project: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
