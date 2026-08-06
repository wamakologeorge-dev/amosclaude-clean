from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORK_WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-fork-pr-fixer.yml"
MAIN_WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-repair-control-plane.yml"
FORK_ROUTE = ROOT / ".github" / "scripts" / "amosclaud_fork_pr_route.py"
CANDIDATE_V2 = ROOT / ".github" / "scripts" / "amosclaud_repair_candidate_v2.py"
POLICY = ROOT / ".amosclaud" / "repair-control-plane.json"


def test_fork_workflow_repairs_without_pushing_to_the_fork() -> None:
    workflow = FORK_WORKFLOW.read_text(encoding="utf-8")

    assert "repository: ${{ steps.route.outputs.head_repository }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "git -C target remote add repair-base" in workflow
    assert "gh pr create" in workflow
    assert "gh pr comment" in workflow
    assert "git -C target push origin" not in workflow
    assert "force push" not in workflow.lower()


def test_fork_route_blocks_only_sensitive_unapproved_content() -> None:
    route = FORK_ROUTE.read_text(encoding="utf-8")

    assert "same-repository PR is handled by the main repair control plane" in route
    assert "environment, secret-bearing, or personal-information content requires approval" in route
    assert "sensitive_approval_state" in route
    assert "fork pull requests are report-only" not in route


def test_candidate_v2_allows_general_repairs_and_gates_sensitive_content() -> None:
    candidate = CANDIDATE_V2.read_text(encoding="utf-8")

    assert "GitHub workflows" in candidate
    assert "infrastructure configuration" in candidate
    assert "AMOSCLAUD_SENSITIVE_APPROVED" in candidate
    assert "requires a recorded human approval" in candidate


def test_policy_enables_all_open_pr_repairs() -> None:
    policy = POLICY.read_text(encoding="utf-8")

    assert '"fork_pull_request": "verified_base_repository_branch"' in policy
    assert '"same_repository_pull_requests_only": false' in policy
    assert '"workflows": false' in policy
    assert '"infrastructure": false' in policy


def test_main_control_plane_is_wired_to_candidate_v2() -> None:
    workflow = MAIN_WORKFLOW.read_text(encoding="utf-8")

    assert "amosclaud_repair_candidate_v2.py" in workflow
    assert "AMOSCLAUD_SENSITIVE_APPROVED" in workflow
    assert "amosclaud_pr_sensitive_approval.py" in workflow
