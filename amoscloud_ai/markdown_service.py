"""Secure, repository-aware Markdown rendering for Amosclaud.

The service deliberately renders on the backend. Repository Markdown is untrusted
user content, so raw HTML is disabled in the parser and the resulting HTML is
sanitized again before it reaches the browser.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

import bleach
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin


_MARKDOWN_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "del",
    "details",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "input",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}

_MARKDOWN_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel", "data-repository-path"],
    "code": ["class"],
    "div": ["class"],
    "h1": ["id"],
    "h2": ["id"],
    "h3": ["id"],
    "h4": ["id"],
    "h5": ["id"],
    "h6": ["id"],
    "img": ["src", "alt", "title", "width", "height", "loading", "decoding"],
    "input": ["type", "checked", "disabled", "class"],
    "li": ["class"],
    "ol": ["class", "start"],
    "span": ["class"],
    "td": ["align"],
    "th": ["align"],
    "ul": ["class"],
}

_ALLOWED_PROTOCOLS = {"http", "https", "mailto"}
_SLUG_INVALID = re.compile(r"[^\w\- ]+", re.UNICODE)
_SLUG_SPACE = re.compile(r"[-\s]+")


@dataclass(frozen=True)
class MarkdownDocument:
    """Rendered Markdown plus navigation metadata."""

    html: str
    outline: tuple[dict[str, object], ...]
    source_sha256: str


def _markdown_parser() -> MarkdownIt:
    parser = MarkdownIt(
        "commonmark",
        {
            "html": False,
            "linkify": False,
            "typographer": False,
            "breaks": False,
        },
    )
    parser.enable("table")
    parser.enable("strikethrough")
    parser.use(tasklists_plugin, enabled=True, label=True)
    parser.use(footnote_plugin)
    return parser


def _walk_tokens(tokens: list[Token]):
    for token in tokens:
        yield token
        if token.children:
            yield from _walk_tokens(token.children)


def _slugify(value: str, used: set[str]) -> str:
    base = _SLUG_INVALID.sub("", value.casefold()).strip()
    base = _SLUG_SPACE.sub("-", base).strip("-") or "section"
    slug = base
    suffix = 2
    while slug in used:
        slug = f"{base}-{suffix}"
        suffix += 1
    used.add(slug)
    return slug


def _safe_repository_path(source_path: str, target: str) -> tuple[str, str, str] | None:
    """Resolve a relative Markdown URL without permitting repository traversal."""

    split = urlsplit(target)
    if split.scheme or split.netloc:
        return None
    if not split.path:
        return "", split.query, split.fragment

    base = posixpath.dirname(source_path)
    candidate = split.path.lstrip("/") if split.path.startswith("/") else posixpath.join(base, split.path)
    resolved = posixpath.normpath(candidate)
    if resolved in {"", "."}:
        resolved = source_path
    if resolved == ".." or resolved.startswith("../"):
        return None
    return resolved, split.query, split.fragment


def _repository_link(repository_id: int, branch: str, source_path: str, href: str) -> tuple[str, str | None]:
    if href.startswith("#"):
        return href, None
    split = urlsplit(href)
    if split.scheme or split.netloc:
        if split.scheme.casefold() not in _ALLOWED_PROTOCOLS:
            return "#", None
        return href, None

    resolved = _safe_repository_path(source_path, href)
    if resolved is None:
        return "#", None
    path, _query, fragment = resolved
    if not path:
        return f"#{fragment}" if fragment else "#", None
    url = f"/workspace/{repository_id}?path={quote(path, safe='')}&branch={quote(branch, safe='')}"
    if fragment:
        url = urlunsplit(("", "", url, "", fragment))
    return url, path


def _repository_image(repository_id: int, branch: str, source_path: str, src: str) -> str:
    split = urlsplit(src)
    if split.scheme or split.netloc:
        return src if split.scheme.casefold() in {"http", "https"} else ""
    resolved = _safe_repository_path(source_path, src)
    if resolved is None or not resolved[0]:
        return ""
    path, _query, _fragment = resolved
    return (
        f"/api/v1/repositories/{repository_id}/raw"
        f"?path={quote(path, safe='')}&branch={quote(branch, safe='')}"
    )


def _decorate_tokens(
    tokens: list[Token],
    *,
    repository_id: int,
    branch: str,
    source_path: str,
) -> tuple[dict[str, object], ...]:
    used_slugs: set[str] = set()
    outline: list[dict[str, object]] = []

    for index, token in enumerate(tokens):
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline = tokens[index + 1]
            title = inline.content.strip() if inline.type == "inline" else "Section"
            slug = _slugify(title, used_slugs)
            token.attrSet("id", slug)
            outline.append({"level": int(token.tag[1:]), "title": title, "id": slug})

    for token in _walk_tokens(tokens):
        if token.type == "link_open":
            href = token.attrGet("href") or ""
            rewritten, repository_path = _repository_link(
                repository_id, branch, source_path, href
            )
            token.attrSet("href", rewritten)
            if repository_path:
                token.attrSet("data-repository-path", repository_path)
            elif urlsplit(rewritten).scheme in {"http", "https"}:
                token.attrSet("target", "_blank")
                token.attrSet("rel", "noopener noreferrer nofollow")
        elif token.type == "image":
            src = token.attrGet("src") or ""
            token.attrSet(
                "src",
                _repository_image(repository_id, branch, source_path, src),
            )
            token.attrSet("loading", "lazy")
            token.attrSet("decoding", "async")

    return tuple(outline)


def render_markdown_document(
    source: str,
    *,
    repository_id: int,
    branch: str,
    source_path: str,
) -> MarkdownDocument:
    """Render repository Markdown into sanitized, repository-aware HTML."""

    if len(source.encode("utf-8")) > 2_000_000:
        raise ValueError("Markdown source exceeds the 2 MB rendering limit")

    parser = _markdown_parser()
    tokens = parser.parse(source)
    outline = _decorate_tokens(
        tokens,
        repository_id=repository_id,
        branch=branch,
        source_path=source_path,
    )
    rendered = parser.renderer.render(tokens, parser.options, {})
    sanitized = bleach.clean(
        rendered,
        tags=_MARKDOWN_TAGS,
        attributes=_MARKDOWN_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    return MarkdownDocument(
        html=sanitized,
        outline=outline,
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )
