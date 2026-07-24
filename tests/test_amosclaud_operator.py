from amoscloud_ai.operator import OperatorRequest, infer_mode, normalize_operator_request


def test_operator_infers_specialized_internal_work() -> None:
    assert infer_mode("Fix the failing repository tests") == "fix"
    assert infer_mode("Deploy the verified release") == "deploy"
    assert infer_mode("Explain this repository") == "ask"


def test_operator_routes_repository_work_to_one_github_task() -> None:
    payload = normalize_operator_request(
        OperatorRequest(
            objective="Fix the CI error and prepare a pull request",
            repository="wamakologeorge-dev/amosclaude-clean",
            conversation_id="conversation-123",
        )
    )

    assert payload["mode"] == "fix"
    assert payload["execution_target"] == "github"
    assert payload["delivery"] == "pull_request"
    assert payload["metadata"]["operator"] == "Amosclaud-bot"
    assert payload["metadata"]["single_brain"] is True
    assert payload["metadata"]["conversation_id"] == "conversation-123"


def test_operator_routes_general_questions_to_cloud_report() -> None:
    payload = normalize_operator_request(
        OperatorRequest(objective="Explain how branches work", require_approval=False)
    )

    assert payload["mode"] == "ask"
    assert payload["execution_target"] == "cloud"
    assert payload["delivery"] == "report"
    assert payload["require_approval"] is False
