from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .lexer import AmclSyntaxError, tokenize
from .parser import (
    Assign,
    Binary,
    Block,
    Call,
    Declare,
    ExpressionStatement,
    FunctionStatement,
    IfStatement,
    Literal,
    Name,
    Parser,
    ReturnStatement,
    Unary,
    WhileStatement,
)


class AmclError(Exception):
    """Base runtime error for Amosclaud Computer Language."""


@dataclass
class Binding:
    value: Any
    owned: bool = False
    moved: bool = False


class Environment:
    def __init__(self, parent: Environment | None = None):
        self.parent = parent
        self.values: dict[str, Binding] = {}

    def define(self, name: str, value: Any, owned: bool = False) -> None:
        if name in self.values:
            raise AmclError(f"Name '{name}' is already defined in this scope")
        self.values[name] = Binding(value=value, owned=owned)

    def resolve(self, name: str) -> tuple[Environment, Binding]:
        if name in self.values:
            return self, self.values[name]
        if self.parent is not None:
            return self.parent.resolve(name)
        raise AmclError(f"Undefined name '{name}'")

    def get(self, name: str) -> Any:
        _, binding = self.resolve(name)
        if binding.moved:
            raise AmclError(f"Owned value '{name}' was already moved")
        return binding.value

    def assign(self, name: str, value: Any) -> None:
        _, binding = self.resolve(name)
        if binding.moved:
            raise AmclError(f"Cannot assign to moved value '{name}'")
        binding.value = value

    def move(self, name: str) -> Any:
        _, binding = self.resolve(name)
        if not binding.owned:
            return binding.value
        if binding.moved:
            raise AmclError(f"Owned value '{name}' was already moved")
        binding.moved = True
        return binding.value


@dataclass(frozen=True)
class NativeFunction:
    name: str
    function: Callable[..., Any]

    def call(self, arguments: list[Any]) -> Any:
        try:
            return self.function(*arguments)
        except TypeError as exc:
            raise AmclError(f"Invalid arguments for {self.name}: {exc}") from exc


@dataclass(frozen=True)
class UserFunction:
    declaration: FunctionStatement
    closure: Environment


class _ReturnSignal(Exception):
    def __init__(self, value: Any):
        self.value = value


class Interpreter:
    def __init__(self, output: Callable[[str], None] | None = None):
        self.output = output or print
        self.globals = Environment()
        self.environment = self.globals
        self.globals.define("print", NativeFunction("print", self._print))
        self.globals.define("len", NativeFunction("len", len))
        self.globals.define("text", NativeFunction("text", self._text))
        self.globals.define("number", NativeFunction("number", self._number))
        self.globals.define("type", NativeFunction("type", self._type_name))

    def execute(self, statements: list[Any]) -> Any:
        result = None
        for statement in statements:
            result = self._execute(statement)
        return result

    def _execute(self, statement: Any) -> Any:
        if isinstance(statement, Declare):
            value = self._evaluate(statement.expression)
            self.environment.define(statement.name, value, owned=statement.owned)
            return value

        if isinstance(statement, Assign):
            value = self._evaluate(statement.expression)
            self.environment.assign(statement.name, value)
            return value

        if isinstance(statement, ExpressionStatement):
            return self._evaluate(statement.expression)

        if isinstance(statement, Block):
            return self._execute_block(statement.statements, Environment(self.environment))

        if isinstance(statement, IfStatement):
            if self._truthy(self._evaluate(statement.condition)):
                return self._execute_block(statement.then_branch.statements, Environment(self.environment))
            if statement.else_branch is not None:
                return self._execute_block(statement.else_branch.statements, Environment(self.environment))
            return None

        if isinstance(statement, WhileStatement):
            result = None
            iterations = 0
            while self._truthy(self._evaluate(statement.condition)):
                result = self._execute_block(statement.body.statements, Environment(self.environment))
                iterations += 1
                if iterations > 1_000_000:
                    raise AmclError("Loop exceeded the runtime safety limit")
            return result

        if isinstance(statement, FunctionStatement):
            self.environment.define(statement.name, UserFunction(statement, self.environment))
            return None

        if isinstance(statement, ReturnStatement):
            value = None if statement.expression is None else self._evaluate(statement.expression)
            raise _ReturnSignal(value)

        raise AmclError(f"Unsupported statement: {type(statement).__name__}")

    def _execute_block(self, statements: list[Any], environment: Environment) -> Any:
        previous = self.environment
        self.environment = environment
        try:
            result = None
            for statement in statements:
                result = self._execute(statement)
            return result
        finally:
            self.environment = previous

    def _evaluate(self, expression: Any) -> Any:
        if isinstance(expression, Literal):
            return expression.value

        if isinstance(expression, Name):
            return self.environment.get(expression.value)

        if isinstance(expression, Unary):
            operand = self._evaluate(expression.operand)
            if expression.operator == "-":
                return -operand
            if expression.operator == "!":
                return not self._truthy(operand)
            raise AmclError(f"Unknown unary operator {expression.operator}")

        if isinstance(expression, Binary):
            if expression.operator == "&&":
                left = self._evaluate(expression.left)
                return self._evaluate(expression.right) if self._truthy(left) else left
            if expression.operator == "||":
                left = self._evaluate(expression.left)
                return left if self._truthy(left) else self._evaluate(expression.right)

            left = self._evaluate(expression.left)
            right = self._evaluate(expression.right)
            return self._binary(expression.operator, left, right)

        if isinstance(expression, Call):
            function = self._evaluate(expression.callee)
            arguments = [self._evaluate(argument) for argument in expression.arguments]
            return self._call(function, arguments)

        raise AmclError(f"Unsupported expression: {type(expression).__name__}")

    def _call(self, function: Any, arguments: list[Any]) -> Any:
        if isinstance(function, NativeFunction):
            return function.call(arguments)

        if isinstance(function, UserFunction):
            declaration = function.declaration
            if len(arguments) != len(declaration.parameters):
                raise AmclError(
                    f"Function '{declaration.name}' expected {len(declaration.parameters)} "
                    f"arguments but received {len(arguments)}"
                )
            call_environment = Environment(function.closure)
            for name, value in zip(declaration.parameters, arguments):
                call_environment.define(name, value)
            try:
                self._execute_block(declaration.body.statements, call_environment)
            except _ReturnSignal as signal:
                return signal.value
            return None

        raise AmclError("Attempted to call a non-function value")

    @staticmethod
    def _binary(operator: str, left: Any, right: Any) -> Any:
        operations: dict[str, Callable[[Any, Any], Any]] = {
            "+": lambda a, b: a + b,
            "-": lambda a, b: a - b,
            "*": lambda a, b: a * b,
            "/": lambda a, b: a / b,
            "%": lambda a, b: a % b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
        }
        try:
            return operations[operator](left, right)
        except KeyError as exc:
            raise AmclError(f"Unknown binary operator {operator}") from exc
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise AmclError(f"Operator {operator} failed: {exc}") from exc

    def _print(self, *values: Any) -> None:
        self.output(" ".join(self._text(value) for value in values))

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        return str(value)

    @staticmethod
    def _number(value: Any) -> int | float:
        text = str(value)
        try:
            return float(text) if "." in text else int(text)
        except ValueError as exc:
            raise AmclError(f"Cannot convert {value!r} to number") from exc

    @staticmethod
    def _type_name(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return "text"
        if isinstance(value, (NativeFunction, UserFunction)):
            return "function"
        return type(value).__name__

    @staticmethod
    def _truthy(value: Any) -> bool:
        return bool(value)


def run_source(
    source: str,
    *,
    interpreter: Interpreter | None = None,
    output: Callable[[str], None] | None = None,
) -> Any:
    """Tokenize, parse, and execute AMCL source code."""
    try:
        statements = Parser(tokenize(source)).parse()
        runtime = interpreter or Interpreter(output=output)
        return runtime.execute(statements)
    except AmclSyntaxError:
        raise
    except AmclError:
        raise
    except Exception as exc:
        raise AmclError(str(exc)) from exc
