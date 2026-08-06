from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-repair-control-plane.yml"
CANDIDATE = ROOT / ".github" / "scripts" / "amosclaud_repair_candidate.py"


def test_failed_pr_checks_trigger_the_repair_control_plane() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "- Fast PR Gate" in workflow
    assert "- Repository Behavior Automation" in workflow
    assert "- Amosclaud Bot" in workflow
    assert "types: [completed]" in workflow


def test_ollama_secret_is_the_primary_repair_model_route() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}" in workflow
    assert 'if [ -n "$OLLAMA_API_KEY" ]; then' in workflow
    assert 'export AMOSCLAUD_API_KEY="$OLLAMA_API_KEY"' in workflow
    assert "${OLLAMA_URL:-https://ollama.com}" in workflow
    assert "${OLLAMA_MODEL:-${AMOSCLAUD_MODEL:-gpt-oss:120b}}" in workflow
    assert 'AMOSCLAUD_REPAIR_PROVIDER="ollama-cloud"' in workflow


def test_gateway_remains_a_safe_fallback_when_ollama_is_unavailable() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "AMOSCLAUD_GATEWAY_API_KEY: ${{ secrets.AMOSCLAUD_API_KEY }}" in workflow
    assert "${AMOSCLAUD_GATEWAY_API_URL:-https://www.amosclaud.com}" in workflow
    assert "${AMOSCLAUD_GATEWAY_FIXER_MODEL:-amosclaud-agent}" in workflow
    assert 'AMOSCLAUD_REPAIR_PROVIDER="amosclaud-gateway"' in workflow


def test_repair_evidence_records_the_selected_provider_without_printing_secrets() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    candidate = CANDIDATE.read_text(encoding="utf-8")

    assert "Repair provider:" in workflow
    assert "Repair endpoint host:" in workflow
    assert "Repair model:" in workflow
    assert 'echo "$OLLAMA_API_KEY"' not in workflow
    assert "AMOSCLAUD_REPAIR_PROVIDER" in candidate
