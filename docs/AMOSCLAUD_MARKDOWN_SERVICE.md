# Amosclaud Markdown Service

## Purpose

Amosclaud Markdown is the repository documentation rendering service for native Amosclaud repositories. It makes `README.md` and other Markdown documents behave like first-class repository pages instead of plain text files.

The service is designed around one rule: repository content is untrusted. Markdown is parsed on the backend with raw HTML disabled, rewritten into repository-aware links, sanitized with an explicit allowlist, and only then returned to the browser.

## User experience

On the repository Code page, Amosclaud automatically:

- discovers the root README on the selected branch;
- renders headings, links, images, tables, task lists, blockquotes, fenced code, strikethrough, and footnotes;
- shows repository description, policy files, commits, branches, tags, files, issues, pull requests, storage size, and language distribution;
- opens relative document links inside the same Amosclaud repository;
- serves safe repository images through an authenticated media endpoint;
- re-renders Markdown files through the backend when a user selects them in the file browser.

## Architecture

```text
Repository working tree
        |
        | authenticated read
        v
/api/v1/repositories/{id}/markdown
        |
        | Markdown-it parser
        | - CommonMark
        | - tables
        | - task lists
        | - strikethrough
        | - footnotes
        | - raw HTML disabled
        v
Repository link and image rewriter
        |
        | Bleach allowlist sanitizer
        v
Sanitized HTML + heading outline + source SHA-256
        |
        v
web/markdown-service.js
        |
        +--> automatic README card
        +--> selected Markdown file viewer
        +--> repository details sidebar
```

## Backend components

### `amoscloud_ai/markdown_service.py`

This module owns parsing, repository-relative URL resolution, heading IDs, document outlines, sanitization, and source hashing. It has no database or HTTP dependency and can be tested independently.

### Repository API

`GET /api/v1/repositories/{repository_id}/markdown`

Required query parameters:

- `path`: repository-relative Markdown path;
- `branch`: branch to render, defaulting to `main`.

Response fields:

- `path` and `branch`;
- sanitized `html`;
- heading `outline`;
- `source_sha256` for cache and integrity decisions.

`GET /api/v1/repositories/{repository_id}/raw`

Serves only allowlisted inline image formats. SVG, HTML, scripts, arbitrary downloads, traversal paths, and files larger than 10 MB are rejected.

`GET /api/v1/repositories/{repository_id}/overview`

Returns facts calculated from the actual branch working tree and Git repository: branches, tags, commits, files, stored bytes, detected languages, and policy-file paths.

## Security boundaries

- Existing repository authorization is applied to every endpoint.
- Raw Markdown HTML is disabled before parsing.
- Rendered output is sanitized with explicit tags, attributes, and protocols.
- JavaScript, data URLs, repository traversal, inline event handlers, and unsafe SVG are rejected.
- External links receive `noopener`, `noreferrer`, and `nofollow`.
- Repository media responses use `nosniff`, a restrictive content security policy, and private caching.
- Markdown source is limited to 2 MB; inline media is limited to 10 MB.
- The browser never receives unsanitized repository Markdown.

## Frontend components

### `web/markdown-service.js`

The client discovers README files, requests rendered HTML, builds the details sidebar from real APIs, intercepts repository-relative links, and upgrades the existing file viewer for every supported Markdown file.

### `web/markdown-service.css`

The stylesheet provides GitHub-style readable typography and responsive repository cards without copying GitHub code or assets.

## Dependencies

- `markdown-it-py` for CommonMark parsing;
- `mdit-py-plugins` for task lists and footnotes;
- `bleach` for final HTML sanitization.

The production Docker image installs the same dependencies as local development and CI.

## Validation

`tests/test_amosclaud_markdown_service.py` verifies:

- supported Markdown features;
- safe repository link and image rewriting;
- script, JavaScript URL, data URL, SVG, and traversal rejection;
- authenticated rendering of real repository files;
- real repository overview counts and language detection;
- frontend service integration.
