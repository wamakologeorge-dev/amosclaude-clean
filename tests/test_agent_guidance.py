from amoscloud_ai.api.routes.agent import _is_guidance_request


def test_website_guidance_does_not_start_engineering_job():
    assert _is_guidance_request("I want to create a website can you guide me", "autonomous-check") is True


def test_direct_fix_instruction_remains_an_engineering_job():
    assert _is_guidance_request("Fix the login error and apply the fix", "fix") is False


def test_question_is_guidance_in_inspect_mode():
    assert _is_guidance_request("What can go wrong with this deployment?", "autonomous-check") is True


def test_explicit_execution_is_not_treated_as_guidance():
    assert _is_guidance_request("Proceed and start building the website", "autonomous-check") is False
