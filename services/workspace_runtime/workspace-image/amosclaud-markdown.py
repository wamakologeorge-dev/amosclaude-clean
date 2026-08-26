#!/usr/bin/env python3
"""Safe Markdown checks and rendering for an Amosclaud workspace.

The command intentionally works only on files below the current workspace. It
is useful in a terminal or CI check, while the web application remains the
source of repository-aware links and authenticated media URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import posixpath
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import bleach
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin


MAX_SOURCE_BYTES = 2_000_000
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
ALLOWED_PROTOCOLS = {"http", "https", "mailto"}
ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "details", "div", "em", "h1",
    "h2", "h3", "h4", "h5", "h6", "hr", "img", "input", "li", "ol", "p",
    "pre", "span", "strong", "sub", "summary", "sup", "table", "tbody", "td",
    "th", "thead", "tr", "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "code": ["class"],
    "div": ["class"],
    "h1": ["id"], "h2": ["id"], "h3": ["id"], "h4": ["id"], "h5": ["id"],
    "h6": ["id"],
    "img": ["src", "alt", "title", "width", "height", "loading", "decoding"],
    "input": ["type", "checked", "disabled", "class"],
    "li": ["class"], "ol": ["class", "start"], "span": ["class"],
    "td": ["align"], "th": ["align"], "ul": ["class"],
}
SLUG_INVALID = re.compile(r"[^\w\- ]+", re.UNICODE)
SLUG_SPACE = re.compile(r"[-\s]+")


def workspace_root() -> Path:
    return Path(".").resolve()


def safe_path(value: str, *, markdown_input: bool = True) -> Path:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        raise ValueError("path must be relative to the workspace")
    cleaned = raw.strip("/")
    parts = cleaned.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path cannot contain '.', '..', or empty components")
    if any(part.casefold() == ".git" for part in parts):
        raise ValueError(".git paths are not Markdown inputs")
    root = workspace_root()
    target = (root / Path(*parts)).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("path resolves outside the workspace") from exc
    if markdown_input and target.suffix.casefold() not in MARKDOWN_SUFFIXES:
        raise ValueError("path must end in .md, .markdown, .mdown, or .mkd")
    return target


def safe_output_path(value: str) -> Path:
    """Allow workspace output plus ephemeral files below the container /tmp."""

    raw = str(value or "").strip().replace("\\", "/")
    if raw == "/tmp" or raw.startswith("/tmp/"):
        target = Path(raw).resolve()
        tmp_root = Path("/tmp").resolve()
        try:
            target.relative_to(tmp_root)
        except ValueError as exc:
            raise ValueError("output path must stay inside /tmp") from exc
        if target == tmp_root:
            raise ValueError("output path must name a file below /tmp")
        return target
    return safe_path(raw, markdown_input=False)


def read_source(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Markdown file not found: {path}")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Markdown source exceeds the 2 MB limit")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Markdown source must be valid UTF-8 text") from exc


def parser() -> MarkdownIt:
    instance = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": False, "typographer": False, "breaks": False},
    )
    instance.enable("table")
    instance.enable("strikethrough")
    instance.use(tasklists_plugin, enabled=True, label=True)
    instance.use(footnote_plugin)
    return instance


def walk(tokens: list[Token]):
    for token in tokens:
        yield token
        if token.children:
            yield from walk(token.children)


def slugify(value: str, used: set[str]) -> str:
    base = SLUG_INVALID.sub("", value.casefold()).strip()
    base = SLUG_SPACE.sub("-", base).strip("-") or "section"
    slug = base
    suffix = 2
    while slug in used:
        slug = f"{base}-{suffix}"
        suffix += 1
    used.add(slug)
    return slug


def local_link(target: str) -> bool:
    split = urlsplit(target)
    if split.scheme or split.netloc:
        return split.scheme.casefold() in ALLOWED_PROTOCOLS
    resolved = posixpath.normpath(split.path)
    return resolved not in {".."} and not resolved.startswith("../")


def decorate(tokens: list[Token]) -> list[dict[str, object]]:
    used: set[str] = set()
    outline: list[dict[str, object]] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline = tokens[index + 1]
            title = inline.content.strip() if inline.type == "inline" else "Section"
            identifier = slugify(title, used)
            token.attrSet("id", identifier)
            outline.append({"level": int(token.tag[1:]), "title": title, "id": identifier})

    for token in walk(tokens):
        if token.type == "link_open":
            href = token.attrGet("href") or ""
            if not local_link(href):
                token.attrSet("href", "#")
            elif urlsplit(href).scheme.casefold() in {"http", "https"}:
                token.attrSet("target", "_blank")
                token.attrSet("rel", "noopener noreferrer nofollow")
        elif token.type == "image":
            src = token.attrGet("src") or ""
            if not local_link(src) or urlsplit(src).scheme.casefold() not in {"http", "https"}:
                token.attrSet("src", "")
            token.attrSet("loading", "lazy")
            token.attrSet("decoding", "async")
    return outline


def render(source: str) -> tuple[str, list[dict[str, object]]]:
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("Markdown source exceeds the 2 MB limit")
    instance = parser()
    tokens = instance.parse(source)
    outline = decorate(tokens)
    html = instance.renderer.render(tokens, instance.options, {})
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    ), outline


def build_parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        prog="amosclaud-markdown",
        description="Check, inspect, and safely render Markdown in the current workspace.",
    )
    command.add_argument("--version", action="version", version="Amosclaud Markdown 1.0")
    subcommands = command.add_subparsers(dest="action", required=True)
    for name, help_text in (
        ("check", "Validate one Markdown document"),
        ("toc", "Print the document heading outline"),
        ("render", "Render sanitized HTML to stdout or a workspace file"),
    ):
        subcommand = subcommands.add_parser(name, help=help_text)
        subcommand.add_argument("path", nargs="?", default="README.md")
        if name == "render":
            subcommand.add_argument("-o", "--output", default="-", help="Output path or - for stdout")
    return command


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = safe_path(args.path)
        source = read_source(path)
        html, outline = render(source)
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if args.action == "check":
            print(f"OK: {path.relative_to(workspace_root())} ({len(outline)} headings, sha256:{digest[:16]})")
        elif args.action == "toc":
            for item in outline:
                indent = "  " * max(0, int(item["level"]) - 1)
                print(f"{indent}- [{item['title']}](#{item['id']})")
        elif args.output == "-":
            sys.stdout.write(html)
        else:
            output = safe_output_path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(html, encoding="utf-8")
            print(f"Rendered {path.relative_to(workspace_root())} -> {output.relative_to(workspace_root())}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Amosclaud Markdown error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
