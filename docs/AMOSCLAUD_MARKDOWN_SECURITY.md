# Amosclaud Markdown Security Guarantees

Amosclaud treats every repository Markdown document and media reference as untrusted input.

The rendering and media APIs enforce all of the following before returning content:

- repository authentication and authorization;
- normalized repository-relative paths;
- resolved-path containment inside the selected repository root;
- rejection of symlinks that resolve outside repository storage;
- Markdown and inline-media type allowlists;
- raw HTML disabled during Markdown parsing;
- final HTML sanitization with explicit tags, attributes, and protocols;
- rejection of JavaScript URLs, data URLs, traversal paths, and inline SVG;
- 2 MB Markdown and 10 MB inline-media limits;
- `nosniff`, private caching, and restrictive media content security headers.

The regression suite creates tracked symlinks to files outside repository storage and verifies that both the Markdown renderer and media service return HTTP 422 rather than reading those files.
