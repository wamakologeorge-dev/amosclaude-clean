from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .lexer import AmclSyntaxError, Token


@dataclass(frozen=True)
class Literal:
    value: Any


@dataclass(frozen=True)
class Name:
    value: str


@dataclass(frozen=True)
class Unary:
    operator: str
    operand: Any


@dataclass(frozen=True)
class Binary:
    left: Any
    operator: str
    right: Any


@dataclass(frozen=True)
class Call:
    callee: Any
    arguments: list[Any]


@dataclass(frozen=True)
class Declare:
    name: str
    expression: Any
    owned: bool


@dataclass(frozen=True)
class Assign:
    name: str
    expression: Any


@dataclass(frozen=True)
class ExpressionStatement:
    expression: Any


@dataclass(frozen=True)
class Block:
    statements: list[Any]


@dataclass(frozen=True)
class IfStatement:
    condition: Any
    then_branch: Block
    else_branch: Block | None


@dataclass(frozen=True)
class WhileStatement:
    condition: Any
    body: Block


@dataclass(frozen=True)
class FunctionStatement:
    name: str
    parameters: list[str]
    body: Block


@dataclass(frozen=True)
class ReturnStatement:
    expression: Any | None


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.current = 0

    def parse(self) -> list[Any]:
        statements: list[Any] = []
        while not self._check("EOF"):
            statements.append(self._statement())
        return statements

    def _statement(self) -> Any:
        if self._match("LET", "OWN"):
            owned = self._previous().kind == "OWN"
            name = self._consume("IDENT", "Expected variable name").value
            self._consume("=", "Expected '=' after variable name")
            expression = self._expression()
            self._consume(";", "Expected ';' after declaration")
            return Declare(name, expression, owned)
        if self._match("FN"):
            return self._function()
        if self._match("IF"):
            return self._if_statement()
        if self._match("WHILE"):
            return self._while_statement()
        if self._match("RETURN"):
            expression = None if self._check(";") else self._expression()
            self._consume(";", "Expected ';' after return")
            return ReturnStatement(expression)
        if self._check("IDENT") and self._peek_next().kind == "=":
            name = self._advance().value
            self._advance()
            expression = self._expression()
            self._consume(";", "Expected ';' after assignment")
            return Assign(name, expression)
        if self._match("{"):
            return self._block_after_open()
        expression = self._expression()
        self._consume(";", "Expected ';' after expression")
        return ExpressionStatement(expression)

    def _function(self) -> FunctionStatement:
        name = self._consume("IDENT", "Expected function name").value
        self._consume("(", "Expected '(' after function name")
        parameters: list[str] = []
        if not self._check(")"):
            while True:
                parameters.append(self._consume("IDENT", "Expected parameter name").value)
                if not self._match(","):
                    break
        self._consume(")", "Expected ')' after parameters")
        self._consume("{", "Expected function body")
        return FunctionStatement(name, parameters, self._block_after_open())

    def _if_statement(self) -> IfStatement:
        self._consume("(", "Expected '(' after if")
        condition = self._expression()
        self._consume(")", "Expected ')' after condition")
        self._consume("{", "Expected if block")
        then_branch = self._block_after_open()
        else_branch = None
        if self._match("ELSE"):
            self._consume("{", "Expected else block")
            else_branch = self._block_after_open()
        return IfStatement(condition, then_branch, else_branch)

    def _while_statement(self) -> WhileStatement:
        self._consume("(", "Expected '(' after while")
        condition = self._expression()
        self._consume(")", "Expected ')' after condition")
        self._consume("{", "Expected while block")
        return WhileStatement(condition, self._block_after_open())

    def _block_after_open(self) -> Block:
        statements: list[Any] = []
        while not self._check("}") and not self._check("EOF"):
            statements.append(self._statement())
        self._consume("}", "Expected '}' after block")
        return Block(statements)

    def _expression(self) -> Any:
        return self._or()

    def _or(self) -> Any:
        expression = self._and()
        while self._match("||"):
            expression = Binary(expression, self._previous().kind, self._and())
        return expression

    def _and(self) -> Any:
        expression = self._equality()
        while self._match("&&"):
            expression = Binary(expression, self._previous().kind, self._equality())
        return expression

    def _equality(self) -> Any:
        expression = self._comparison()
        while self._match("==", "!="):
            expression = Binary(expression, self._previous().kind, self._comparison())
        return expression

    def _comparison(self) -> Any:
        expression = self._term()
        while self._match("<", "<=", ">", ">="):
            expression = Binary(expression, self._previous().kind, self._term())
        return expression

    def _term(self) -> Any:
        expression = self._factor()
        while self._match("+", "-"):
            expression = Binary(expression, self._previous().kind, self._factor())
        return expression

    def _factor(self) -> Any:
        expression = self._unary()
        while self._match("*", "/", "%"):
            expression = Binary(expression, self._previous().kind, self._unary())
        return expression

    def _unary(self) -> Any:
        if self._match("!", "-"):
            return Unary(self._previous().kind, self._unary())
        return self._call()

    def _call(self) -> Any:
        expression = self._primary()
        while self._match("("):
            arguments: list[Any] = []
            if not self._check(")"):
                while True:
                    arguments.append(self._expression())
                    if not self._match(","):
                        break
            self._consume(")", "Expected ')' after arguments")
            expression = Call(expression, arguments)
        return expression

    def _primary(self) -> Any:
        if self._match("NUMBER"):
            value = self._previous().value
            return Literal(float(value) if "." in value else int(value))
        if self._match("STRING"):
            return Literal(self._previous().value)
        if self._match("TRUE"):
            return Literal(True)
        if self._match("FALSE"):
            return Literal(False)
        if self._match("NULL"):
            return Literal(None)
        if self._match("IDENT"):
            return Name(self._previous().value)
        if self._match("("):
            expression = self._expression()
            self._consume(")", "Expected ')' after expression")
            return expression
        token = self._peek()
        raise AmclSyntaxError(f"Expected expression at {token.line}:{token.column}")

    def _match(self, *kinds: str) -> bool:
        for kind in kinds:
            if self._check(kind):
                self._advance()
                return True
        return False

    def _consume(self, kind: str, message: str) -> Token:
        if self._check(kind):
            return self._advance()
        token = self._peek()
        raise AmclSyntaxError(f"{message} at {token.line}:{token.column}")

    def _check(self, kind: str) -> bool:
        return self._peek().kind == kind

    def _advance(self) -> Token:
        token = self.tokens[self.current]
        if token.kind != "EOF":
            self.current += 1
        return token

    def _peek(self) -> Token:
        return self.tokens[self.current]

    def _peek_next(self) -> Token:
        return self.tokens[min(self.current + 1, len(self.tokens) - 1)]

    def _previous(self) -> Token:
        return self.tokens[self.current - 1]
