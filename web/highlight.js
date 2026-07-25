/*
 * Amosclaud workspace syntax highlighter.
 *
 * Self-contained and dependency-free on purpose: the deployed container is not
 * guaranteed to reach third-party CDNs, so this file is vendored in the repo
 * and served from /static/highlight.js like every other workspace asset.
 *
 * Security contract: this module NEVER returns caller-supplied text unescaped.
 * Source text is split into (type, text) tokens and every token's text is run
 * through escapeHtml before it is placed inside a <span>. The only HTML this
 * module emits is its own <span class="tok-*"> wrappers, so hostile file
 * content cannot inject markup or script into the workspace.
 *
 * Supported: Python, JavaScript/TypeScript, JSON, HTML, CSS, Markdown, shell
 * and YAML. Anything else falls back to a conservative "plain" mode that still
 * escapes correctly and highlights strings, numbers and common comments.
 */
(function (global) {
  'use strict';

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  var words = function (list) {
    var set = Object.create(null);
    list.split(' ').forEach(function (word) { if (word) set[word] = true; });
    return set;
  };

  // --- keyword tables -----------------------------------------------------
  var PY_KEYWORDS = words(
    'and as assert async await break class continue def del elif else except finally for from ' +
    'global if import in is lambda match nonlocal not or pass raise return try while with yield case'
  );
  var PY_BUILTINS = words(
    'abs all any bool bytes callable chr dict dir enumerate filter float format frozenset getattr ' +
    'hasattr hash id int isinstance issubclass iter len list map max min next object open ord print ' +
    'range repr reversed round set setattr sorted staticmethod str sum super tuple type vars zip ' +
    'self cls None True False NotImplemented Ellipsis Exception ValueError TypeError KeyError'
  );
  var JS_KEYWORDS = words(
    'as async await break case catch class const continue debugger default delete do else enum export ' +
    'extends finally for from function get if implements import in instanceof interface let new of ' +
    'package private protected public return satisfies set static super switch this throw try typeof ' +
    'var void while with yield abstract declare namespace readonly type keyof infer is asserts override'
  );
  var JS_BUILTINS = words(
    'Array Boolean Date Error JSON Map Math Number Object Promise Proxy RegExp Set String Symbol ' +
    'WeakMap WeakSet console document window globalThis undefined null true false NaN Infinity ' +
    'string number boolean any unknown never object bigint symbol void'
  );
  var SH_KEYWORDS = words(
    'if then elif else fi for while until do done case esac function in return break continue ' +
    'local export readonly declare set unset shift source trap exit eval exec'
  );
  var SH_BUILTINS = words(
    'echo printf cd pwd ls cat cp mv rm mkdir rmdir touch chmod chown ln find grep sed awk sort uniq ' +
    'head tail wc tar zip unzip curl wget git python python3 pip pip3 node npm npx bun yarn docker ' +
    'kubectl make sudo apt apt-get systemctl service ssh scp rsync test env which sleep kill ps'
  );
  var YAML_LITERALS = words('true false null yes no on off True False Null None ~');

  // --- rule helpers -------------------------------------------------------
  function rule(type, source, flags) {
    return { type: type, re: new RegExp(source, 'y' + (flags || '')) };
  }
  // A word rule: matches an identifier, but only claims it when the word is in
  // `table`. Returning null lets the tokenizer fall through to the next rule.
  function mapped(source, table, type, flags) {
    return {
      re: new RegExp(source, 'y' + (flags || '')),
      map: function (text) { return table[text] ? type : null; },
    };
  }

  var NUMBER = '\\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\\d[\\d_]*(?:\\.[\\d_]+)?(?:[eE][+-]?\\d+)?)\\b';
  var DQ = '"(?:\\\\[\\s\\S]|[^"\\\\\\n])*"?';
  var SQ = "'(?:\\\\[\\s\\S]|[^'\\\\\\n])*'?";
  var OPERATOR = '[+\\-*/%=<>!&|^~?:]+';
  var PUNCT = '[{}()\\[\\];,.]';
  var IDENT = '[A-Za-z_$][A-Za-z0-9_$]*';

  var LANGUAGES = {
    python: [
      rule('comment', '#[^\\n]*'),
      rule('string', '[rRbBuUfF]{0,3}(?:"""[\\s\\S]*?(?:"""|$)|\'\'\'[\\s\\S]*?(?:\'\'\'|$))'),
      rule('string', '[rRbBuUfF]{0,3}(?:' + DQ + '|' + SQ + ')'),
      rule('meta', '@[A-Za-z_][\\w.]*'),
      rule('number', NUMBER),
      rule('func', '[A-Za-z_]\\w*(?=\\s*\\()'),
      mapped('[A-Za-z_]\\w*', PY_KEYWORDS, 'keyword'),
      mapped('[A-Za-z_]\\w*', PY_BUILTINS, 'builtin'),
      rule('operator', OPERATOR),
      rule('punct', PUNCT),
    ],
    javascript: [
      rule('comment', '//[^\\n]*|/\\*[\\s\\S]*?(?:\\*/|$)'),
      rule('string', '`(?:\\\\[\\s\\S]|[^`\\\\])*`?'),
      rule('string', DQ + '|' + SQ),
      rule('number', NUMBER),
      rule('prop', '(?:\\.)\\s*' + IDENT),
      rule('func', IDENT + '(?=\\s*\\()'),
      mapped(IDENT, JS_KEYWORDS, 'keyword'),
      mapped(IDENT, JS_BUILTINS, 'builtin'),
      rule('operator', OPERATOR),
      rule('punct', PUNCT),
    ],
    json: [
      rule('comment', '//[^\\n]*'),
      rule('prop', '"(?:\\\\[\\s\\S]|[^"\\\\])*"(?=\\s*:)'),
      rule('string', '"(?:\\\\[\\s\\S]|[^"\\\\])*"?'),
      rule('number', '-?' + NUMBER),
      rule('keyword', '\\b(?:true|false|null)\\b'),
      rule('punct', '[{}\\[\\],:]'),
    ],
    html: [
      rule('comment', '<!--[\\s\\S]*?(?:-->|$)'),
      rule('meta', '<!DOCTYPE[^>]*>?', 'i'),
      rule('tag', '</?[A-Za-z][\\w:.-]*'),
      rule('string', DQ + '|' + SQ),
      rule('attr', '[A-Za-z_:][\\w:.-]*(?=\\s*=)'),
      rule('meta', '&[#\\w]+;'),
      rule('tag', '/?>'),
    ],
    css: [
      rule('comment', '/\\*[\\s\\S]*?(?:\\*/|$)'),
      rule('string', DQ + '|' + SQ),
      rule('meta', '@[\\w-]+'),
      rule('number', '#[0-9a-fA-F]{3,8}\\b'),
      rule('prop', '[-a-zA-Z][-\\w]*(?=\\s*:)'),
      rule('number', '-?\\d[\\d.]*(?:px|em|rem|ex|ch|%|vh|vw|vmin|vmax|s|ms|deg|fr|pt|cm|mm|in)?\\b'),
      rule('func', '[-\\w]+(?=\\s*\\()'),
      rule('keyword', '[.#][-\\w]+|::?[A-Za-z][-\\w]*'),
      rule('punct', '[{};:,()]'),
    ],
    markdown: [
      rule('comment', '<!--[\\s\\S]*?(?:-->|$)'),
      rule('string', '^```[\\s\\S]*?(?:^```|$)', 'm'),
      rule('heading', '^#{1,6}[^\\n]*', 'm'),
      rule('heading', '^[=-]{3,}$', 'm'),
      rule('string', '`[^`\\n]*`'),
      rule('link', '!?\\[[^\\]\\n]*\\]\\([^)\\n]*\\)'),
      rule('bold', '\\*\\*[^*\\n]+\\*\\*|__[^_\\n]+__'),
      rule('italic', '\\*[^*\\n]+\\*|_[^_\\n]+_'),
      rule('meta', '^\\s{0,3}(?:[-*+]|\\d+\\.)\\s', 'm'),
      rule('comment', '^\\s{0,3}>[^\\n]*', 'm'),
      rule('meta', '^\\s{0,3}(?:---|\\*\\*\\*|___)\\s*$', 'm'),
    ],
    shell: [
      rule('comment', '#[^\\n]*'),
      rule('string', DQ + '|' + SQ),
      rule('var', '\\$\\{[^}\\n]*\\}|\\$[\\w@*#?$!-]+'),
      rule('meta', '(?:^|(?<=\\s))--?[A-Za-z][\\w-]*', 'm'),
      rule('number', NUMBER),
      mapped('[A-Za-z_][\\w-]*', SH_KEYWORDS, 'keyword'),
      mapped('[A-Za-z_][\\w-]*', SH_BUILTINS, 'builtin'),
      rule('operator', '[|&;<>]+'),
    ],
    yaml: [
      rule('comment', '#[^\\n]*'),
      rule('string', DQ + '|' + SQ),
      rule('meta', '^---\\s*$|^\\.\\.\\.\\s*$', 'm'),
      rule('prop', '^[ \\t]*(?:-[ \\t]+)?[\\w.\\/-]+(?=[ \\t]*:(?:[ \\t]|$))', 'm'),
      rule('meta', '[&*][\\w-]+|<<(?=:)|![\\w!/:.-]+'),
      rule('meta', '^[ \\t]*-(?=[ \\t]|$)', 'm'),
      mapped('[A-Za-z_][\\w-]*', YAML_LITERALS, 'keyword'),
      rule('number', '-?' + NUMBER),
      rule('operator', '[|>]-?(?=\\s*$)', 'm'),
    ],
    plain: [
      rule('comment', '#[^\\n]*|//[^\\n]*|/\\*[\\s\\S]*?(?:\\*/|$)'),
      rule('string', DQ + '|' + SQ),
      rule('number', NUMBER),
    ],
  };

  // Aliases keep the table small while covering the extensions we actually see.
  var ALIASES = {
    py: 'python', pyi: 'python', python: 'python',
    js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'javascript',
    ts: 'javascript', tsx: 'javascript', typescript: 'javascript', javascript: 'javascript',
    json: 'json', jsonc: 'json', lock: 'json',
    html: 'html', htm: 'html', xml: 'html', svg: 'html', vue: 'html',
    css: 'css', scss: 'css', sass: 'css', less: 'css',
    md: 'markdown', markdown: 'markdown', mdx: 'markdown',
    sh: 'shell', bash: 'shell', zsh: 'shell', ksh: 'shell', shell: 'shell', env: 'shell',
    yml: 'yaml', yaml: 'yaml',
  };

  // Files that carry no extension but have a well-known syntax.
  var FILENAMES = {
    dockerfile: 'shell',
    makefile: 'shell',
    procfile: 'shell',
    '.gitignore': 'shell',
    '.dockerignore': 'shell',
    '.env': 'shell',
  };

  function languageForPath(path) {
    var name = String(path || '').split('/').pop() || '';
    var lower = name.toLowerCase();
    if (FILENAMES[lower]) return FILENAMES[lower];
    var dot = lower.lastIndexOf('.');
    if (dot < 0) return 'plain';
    return ALIASES[lower.slice(dot + 1)] || 'plain';
  }

  function resolve(language) {
    if (!language) return 'plain';
    var key = String(language).toLowerCase();
    if (LANGUAGES[key]) return key;
    return ALIASES[key] || 'plain';
  }

  /**
   * Split source into [type, text] pairs. `type` is null for unstyled text.
   * Always advances at least one character, so this cannot loop forever.
   */
  function tokenize(code, language) {
    var source = String(code == null ? '' : code);
    var rules = LANGUAGES[resolve(language)];
    var tokens = [];
    var index = 0;
    var plainFrom = 0;

    function flushPlain(end) {
      if (end > plainFrom) tokens.push([null, source.slice(plainFrom, end)]);
    }

    while (index < source.length) {
      var hit = null;
      for (var r = 0; r < rules.length; r += 1) {
        var current = rules[r];
        current.re.lastIndex = index;
        var match = current.re.exec(source);
        if (match && match[0].length > 0) {
          var type = current.map ? current.map(match[0]) : current.type;
          if (type === null && current.map) continue; // word not in this table
          hit = [type, match[0]];
          break;
        }
      }
      if (hit) {
        flushPlain(index);
        tokens.push(hit);
        index += hit[1].length;
        plainFrom = index;
      } else {
        index += 1;
      }
    }
    flushPlain(index);
    return tokens;
  }

  function wrap(type, text) {
    var safe = escapeHtml(text);
    return type ? '<span class="tok-' + type + '">' + safe + '</span>' : safe;
  }

  /** Highlight `code` and return one HTML string. Every character is escaped. */
  function highlight(code, language) {
    return tokenize(code, language)
      .map(function (token) { return wrap(token[0], token[1]); })
      .join('');
  }

  /**
   * Highlight `code` and return an array of HTML strings, one per source line.
   * Tokens that span lines (block comments, docstrings, fenced code) are split
   * across the lines they cover, which per-line highlighting cannot do.
   */
  function highlightLines(code, language) {
    var tokens = tokenize(code, language);
    var lines = [];
    var buffer = '';
    for (var t = 0; t < tokens.length; t += 1) {
      var type = tokens[t][0];
      var parts = tokens[t][1].split('\n');
      for (var p = 0; p < parts.length; p += 1) {
        if (p > 0) { lines.push(buffer); buffer = ''; }
        if (parts[p]) buffer += wrap(type, parts[p]);
      }
    }
    lines.push(buffer);
    return lines;
  }

  var api = {
    escapeHtml: escapeHtml,
    languageForPath: languageForPath,
    languages: Object.keys(LANGUAGES),
    tokenize: tokenize,
    highlight: highlight,
    highlightLines: highlightLines,
  };

  global.AmosclaudHighlight = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
