from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github/workflows/amosclaud-bot.yml",
    ROOT / ".github/workflows/amosclaud-model-agent.yml",
)


def test_groq_secret_is_wired_without_storing_its_value() -> None:
    for workflow in WORKFLOWS:
        source = workflow.read_text(encoding="utf-8")
        assert "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}" in source
        assert "GROQ_MODEL: ${{ vars.GROQ_MODEL || 'openai/gpt-oss-20b' }}" in source
        assert "secrets.GROQ_API_KEY && 'https://api.groq.com/openai'" in source
        assert "|| secrets.GROQ_API_KEY }}" in source
        assert "secrets.GROQ_API_KEY && 'openai/gpt-oss-20b'" in source
        assert "gsk_" not in source


def test_first_party_and_ollama_routes_still_precede_groq() -> None:
    for workflow in WORKFLOWS:
        source = workflow.read_text(encoding="utf-8")
        expression = next(
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith("AMOSCLAUD_MODEL_URL:")
        )
        assert expression.index("secrets.AMOSCLAUD_MODEL_URL") < expression.index(
            "secrets.GROQ_API_KEY"
        )
        assert expression.index("secrets.OLLAMA_URL") < expression.index(
            "secrets.GROQ_API_KEY"
        )
