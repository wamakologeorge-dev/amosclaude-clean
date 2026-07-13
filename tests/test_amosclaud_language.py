from pathlib import Path

import pytest

from amosclaud_language.cli import main
from amosclaud_language.lexer import AmclSyntaxError, tokenize
from amosclaud_language.runtime import AmclError, Interpreter, run_source


def capture(source: str) -> list[str]:
    output: list[str] = []
    run_source(source, output=output.append)
    return output


def test_lexer_recognizes_amcl_program():
    tokens = tokenize('let answer = 42; print("ready", answer);')
    assert [token.kind for token in tokens[:6]] == ["LET", "IDENT", "=", "NUMBER", ";", "IDENT"]


def test_functions_conditionals_and_loops_execute():
    source = '''
    fn double(value) {
        return value * 2;
    }

    let current = 1;
    while (current < 4) {
        if (current == 2) {
            print("middle", double(current));
        } else {
            print("value", current);
        }
        current = current + 1;
    }
    '''
    assert capture(source) == ["value 1", "middle 4", "value 3"]


def test_scoped_variables_do_not_escape_blocks():
    with pytest.raises(AmclError, match="Undefined name 'inside'"):
        run_source('if (true) { let inside = 1; } print(inside);')


def test_invalid_syntax_has_source_position():
    with pytest.raises(AmclSyntaxError, match=r"\d+:\d+"):
        run_source("let value = ;")


def test_runtime_reports_division_by_zero():
    with pytest.raises(AmclError, match="division by zero"):
        run_source("print(10 / 0);")


def test_cli_executes_amcl_file(tmp_path: Path, capsys):
    program = tmp_path / "program.amcl"
    program.write_text('print("AMCL online");', encoding="utf-8")

    assert main([str(program)]) == 0
    assert capsys.readouterr().out.strip() == "AMCL online"


def test_cli_rejects_wrong_extension(tmp_path: Path, capsys):
    program = tmp_path / "program.txt"
    program.write_text('print("wrong");', encoding="utf-8")

    assert main([str(program)]) == 2
    assert ".amcl extension" in capsys.readouterr().out


def test_interpreter_can_preserve_state_between_runs():
    output: list[str] = []
    interpreter = Interpreter(output=output.append)
    run_source("let value = 4;", interpreter=interpreter)
    run_source("print(value + 1);", interpreter=interpreter)
    assert output == ["5"]
