"""Lexer for the Amosclaud scripting language (Amcl).

Converts raw source text into a flat list of :class:`Token` objects terminated
by a single ``EOF`` token. Comments begin with ``#`` and run to end-of-line.
"""
from __future__ import annotations

from dataclasses import dataclass


class AmclSyntaxError(Exception):
    """Raised by :func:`tokenize` when the source contains invalid syntax."""


@dataclass(frozen=True)
class Token:
    """A single lexical unit produced by :func:`tokenize`.

    Attributes:
        kind: Token category — a keyword name in uppercase (e.g. ``"LET"``),
            ``"IDENT"``, ``"NUMBER"``, ``"STRING"``, a two-character operator
            such as ``"=="`` or ``"||"``, a single-character punctuator, or
            ``"EOF"``.
        value: The literal source text for this token, or ``""`` for ``EOF``.
        line: 1-based source line number at the start of the token.
        column: 1-based column number at the start of the token.
    """

    kind: str
    value: str
    line: int
    column: int


KEYWORDS = {
    "let",
    "own",
    "fn",
    "return",
    "if",
    "else",
    "while",
    "true",
    "false",
    "null",
}

TWO_CHAR = {"==", "!=", "<=", ">=", "&&", "||"}
SINGLE = set("+-*/%(){};,=!<>")


def tokenize(source: str) -> list[Token]:
    """Tokenize ``source`` and return the complete token list including ``EOF``.

    Handles:
    - Integer and floating-point number literals (at most one ``"."``)
    - Double-quoted string literals with ``\\n``, ``\\t``, ``\\"`` and ``\\\\`` escapes
    - Identifiers and keywords (see :data:`KEYWORDS`)
    - Two-character operators: ``==``, ``!=``, ``<=``, ``>=``, ``&&``, ``||``
    - Single-character punctuators: ``+ - * / % ( ) { } ; , = ! < >``
    - Line comments starting with ``#``

    Args:
        source: Complete source code string to lex.

    Returns:
        Ordered list of :class:`Token` objects. The last element is always
        ``Token("EOF", "", line, column)``.

    Raises:
        AmclSyntaxError: On an unterminated string literal, a number with more
            than one decimal point, or an unrecognised character.
    """
    tokens: list[Token] = []
    i = 0
    line = 1
    column = 1

    while i < len(source):
        ch = source[i]

        if ch in " \t\r":
            i += 1
            column += 1
            continue

        if ch == "\n":
            i += 1
            line += 1
            column = 1
            continue

        if ch == "#":
            while i < len(source) and source[i] != "\n":
                i += 1
                column += 1
            continue

        start_line = line
        start_column = column

        if ch.isdigit():
            start = i
            dots = 0
            while i < len(source) and (source[i].isdigit() or source[i] == "."):
                if source[i] == ".":
                    dots += 1
                i += 1
                column += 1
            if dots > 1:
                raise AmclSyntaxError(f"Invalid number at {start_line}:{start_column}")
            tokens.append(Token("NUMBER", source[start:i], start_line, start_column))
            continue

        if ch.isalpha() or ch == "_":
            start = i
            while i < len(source) and (source[i].isalnum() or source[i] == "_"):
                i += 1
                column += 1
            value = source[start:i]
            kind = value.upper() if value in KEYWORDS else "IDENT"
            tokens.append(Token(kind, value, start_line, start_column))
            continue

        if ch == '"':
            i += 1
            column += 1
            chars: list[str] = []
            while i < len(source) and source[i] != '"':
                if source[i] == "\\":
                    i += 1
                    column += 1
                    if i >= len(source):
                        break
                    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
                    chars.append(escapes.get(source[i], source[i]))
                else:
                    chars.append(source[i])
                i += 1
                column += 1
            if i >= len(source):
                raise AmclSyntaxError(f"Unterminated string at {start_line}:{start_column}")
            i += 1
            column += 1
            tokens.append(Token("STRING", "".join(chars), start_line, start_column))
            continue

        pair = source[i : i + 2]
        if pair in TWO_CHAR:
            tokens.append(Token(pair, pair, start_line, start_column))
            i += 2
            column += 2
            continue

        if ch in SINGLE:
            tokens.append(Token(ch, ch, start_line, start_column))
            i += 1
            column += 1
            continue

        raise AmclSyntaxError(f"Unexpected character {ch!r} at {line}:{column}")

    tokens.append(Token("EOF", "", line, column))
    return tokens
