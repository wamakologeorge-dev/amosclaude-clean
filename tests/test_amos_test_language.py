"""Tests for Amosclaud's focused server-test language."""
from __future__ import annotations

import pytest

from amoscloud_ai.amos_test_language import AmosTestSyntaxError, parse_amos_tests


def test_parses_focused_server_case():
    cases = parse_amos_tests(
        '''AMOSCLAUD SERVER-TESTS 1
FOCUS health
CALL GET /health
EXPECT STATUS 200
EXPECT JSON status = "ok"
END
'''
    )
    assert len(cases) == 1
    assert cases[0].name == "health"
    assert cases[0].method == "GET"
    assert cases[0].path == "/health"
    assert len(cases[0].expectations) == 2


def test_rejects_unknown_amosclaud_command():
    with pytest.raises(AmosTestSyntaxError):
        parse_amos_tests(
            '''AMOSCLAUD SERVER-TESTS 1
FOCUS broken
INVENT SOMETHING
END
'''
        )


def test_requires_explicit_expectation():
    with pytest.raises(AmosTestSyntaxError):
        parse_amos_tests(
            '''AMOSCLAUD SERVER-TESTS 1
FOCUS empty
CALL GET /health
END
'''
        )
