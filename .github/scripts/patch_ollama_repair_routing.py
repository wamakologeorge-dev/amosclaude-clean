#!/usr/bin/env python3
"""Apply the bounded Ollama repair-routing change on the working branch.

This temporary helper is removed after it commits the real workflow and tests.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-repair-control-plane.yml"
CANDIDATE = ROOT / ".github" / "scripts" / "amosclaud_repair_candidate.py"
TEST = ROOT / "tests" / "test_automatic_ollama_repair_routing.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Unable to locate {label}")
    return text.replace(old, new, 1)


def patch_workflow() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """    workflows:\n      - Amosclaud CI\n""",
        """    workflows:\n      - Fast PR Gate\n      - Repository Behavior Automation\n      - Amosclaud Bot\n      - Amosclaud CI\n""",
        label="failed-check workflow list",
    )
    text = replace_once(
        text,
        """        env:\n          AMOSCLAUD_API_KEY: ${{ secrets.AMOSCLAUD_API_KEY }}\n          AMOSCLAUD_API_URL: ${{ vars.AMOSCLAUD_API_URL || 'https://www.amosclaud.com' }}\n          AMOSCLAUD_FIXER_MODEL: ${{ vars.AMOSCLAUD_FIXER_MODEL || 'amosclaud-agent' }}\n          FAILURE_LOG: ${{ runner.temp }}/amosclaud-repair-failure.log\n""",
        """        env:\n          OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}\n          OLLAMA_URL: ${{ secrets.OLLAMA_URL }}\n          OLLAMA_MODEL: ${{ vars.OLLAMA_MODEL }}\n          AMOSCLAUD_MODEL: ${{ vars.AMOSCLAUD_MODEL }}\n          AMOSCLAUD_GATEWAY_API_KEY: ${{ secrets.AMOSCLAUD_API_KEY }}\n          AMOSCLAUD_GATEWAY_API_URL: ${{ vars.AMOSCLAUD_API_URL }}\n          AMOSCLAUD_GATEWAY_FIXER_MODEL: ${{ vars.AMOSCLAUD_FIXER_MODEL }}\n          FAILURE_LOG: ${{ runner.temp }}/amosclaud-repair-failure.log\n""",
        label="repair candidate model environment",
    )
    text = replace_once(
        text,
        """        run: |\n          set +e\n          mode=regular\n""",
        """        run: |\n          set +e\n          if [ -n \"$OLLAMA_API_KEY\" ]; then\n            export AMOSCLAUD_API_KEY=\"$OLLAMA_API_KEY\"\n            export AMOSCLAUD_API_URL=\"${OLLAMA_URL:-https://ollama.com}\"\n            export AMOSCLAUD_FIXER_MODEL=\"${OLLAMA_MODEL:-${AMOSCLAUD_MODEL:-gpt-oss:120b}}\"\n            export AMOSCLAUD_REPAIR_PROVIDER=\"ollama-cloud\"\n          else\n            export AMOSCLAUD_API_KEY=\"$AMOSCLAUD_GATEWAY_API_KEY\"\n            export AMOSCLAUD_API_URL=\"${AMOSCLAUD_GATEWAY_API_URL:-https://www.amosclaud.com}\"\n            export AMOSCLAUD_FIXER_MODEL=\"${AMOSCLAUD_GATEWAY_FIXER_MODEL:-amosclaud-agent}\"\n            export AMOSCLAUD_REPAIR_PROVIDER=\"amosclaud-gateway\"\n          fi\n          python - <<'PY'\n          import os\n          from urllib.parse import urlsplit\n\n          endpoint = os.environ.get(\"AMOSCLAUD_API_URL\", \"\")\n          host = urlsplit(endpoint).netloc or \"invalid\"\n          print(f\"Repair provider: {os.environ.get('AMOSCLAUD_REPAIR_PROVIDER', 'unknown')}\")\n          print(f\"Repair endpoint host: {host}\")\n          print(f\"Repair model: {os.environ.get('AMOSCLAUD_FIXER_MODEL', 'unknown')}\")\n          PY\n          mode=regular\n""",
        label="repair provider resolution",
    )
    WORKFLOW.write_text(text, encoding="utf-8")


def patch_candidate_report() -> None:
    text = CANDIDATE.read_text(encoding="utf-8")
    text = text.replace(
        '"provider": "amosclaud",',
        '"provider": os.getenv("AMOSCLAUD_REPAIR_PROVIDER", "amosclaud").strip()\n'
        '                or "amosclaud",',
    )
    if "AMOSCLAUD_REPAIR_PROVIDER" not in text:
        raise RuntimeError("Candidate report provider patch was not applied")
    CANDIDATE.write_text(text, encoding="utf-8")


def write_tests() -> None:
    TEST.write_text(
        '''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\nWORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-repair-control-plane.yml"\nCANDIDATE = ROOT / ".github" / "scripts" / "amosclaud_repair_candidate.py"\n\n\ndef test_failed_pr_checks_trigger_the_repair_control_plane() -> None:\n    workflow = WORKFLOW.read_text(encoding="utf-8")\n\n    assert "- Fast PR Gate" in workflow\n    assert "- Repository Behavior Automation" in workflow\n    assert "- Amosclaud Bot" in workflow\n    assert "types: [completed]" in workflow\n\n\ndef test_ollama_secret_is_the_primary_repair_model_route() -> None:\n    workflow = WORKFLOW.read_text(encoding="utf-8")\n\n    assert "OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}" in workflow\n    assert 'if [ -n "$OLLAMA_API_KEY" ]; then' in workflow\n    assert 'export AMOSCLAUD_API_KEY="$OLLAMA_API_KEY"' in workflow\n    assert '${OLLAMA_URL:-https://ollama.com}' in workflow\n    assert '${OLLAMA_MODEL:-${AMOSCLAUD_MODEL:-gpt-oss:120b}}' in workflow\n    assert 'AMOSCLAUD_REPAIR_PROVIDER="ollama-cloud"' in workflow\n\n\ndef test_gateway_remains_a_safe_fallback_when_ollama_is_unavailable() -> None:\n    workflow = WORKFLOW.read_text(encoding="utf-8")\n\n    assert "AMOSCLAUD_GATEWAY_API_KEY: ${{ secrets.AMOSCLAUD_API_KEY }}" in workflow\n    assert '${AMOSCLAUD_GATEWAY_API_URL:-https://www.amosclaud.com}' in workflow\n    assert '${AMOSCLAUD_GATEWAY_FIXER_MODEL:-amosclaud-agent}' in workflow\n    assert 'AMOSCLAUD_REPAIR_PROVIDER="amosclaud-gateway"' in workflow\n\n\ndef test_repair_evidence_records_the_selected_provider_without_printing_secrets() -> None:\n    workflow = WORKFLOW.read_text(encoding="utf-8")\n    candidate = CANDIDATE.read_text(encoding="utf-8")\n\n    assert "Repair provider:" in workflow\n    assert "Repair endpoint host:" in workflow\n    assert "Repair model:" in workflow\n    assert 'echo "$OLLAMA_API_KEY"' not in workflow\n    assert "AMOSCLAUD_REPAIR_PROVIDER" in candidate\n''',
        encoding="utf-8",
    )


def main() -> None:
    patch_workflow()
    patch_candidate_report()
    write_tests()


if __name__ == "__main__":
    main()
