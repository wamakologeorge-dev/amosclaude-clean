from amosclaud_bot.autonomous_planning import is_continue_request


def test_proceed_phrases_resume_the_latest_plan() -> None:
    assert is_continue_request("proceed")
    assert is_continue_request("@amosclaud proceed")
    assert is_continue_request("@amosclaud proceed with the repair")
    assert is_continue_request("@amosclaud-bot go ahead")


def test_unrelated_objectives_are_not_continuations() -> None:
    assert not is_continue_request("@amosclaud inspect the repository")
    assert not is_continue_request("@amosclaud create a new file")
