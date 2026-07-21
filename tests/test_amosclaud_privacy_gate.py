from amosclaud_bot.privacy_gate import requires_private_work


def test_serious_work_is_private_by_default() -> None:
    assert requires_private_work("fix production deployment workflow")
    assert requires_private_work("investigate security vulnerability")
    assert requires_private_work("rotate authentication credential")
    assert requires_private_work("handle confidential customer data incident")


def test_safe_process_work_can_remain_public() -> None:
    assert not requires_private_work("fix typo in README")
    assert not requires_private_work("add unit test for parser")
    assert not requires_private_work("inspect code quality")
