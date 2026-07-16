from __future__ import annotations

import json
import os
from typing import Any, Sequence

from ..runtime import AgentStep, Tool


class CodexProvider:
    """OpenAI Responses API adapter for the Amosclaud agent loop."""

    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self.model = model or os.getenv("AMOSCLAUD_CODEX_MODEL", "").strip()
        if not self.model:
            raise RuntimeError("Set AMOSCLAUD_CODEX_MODEL to an available OpenAI coding model")

        self.max_output_tokens = int(os.getenv("AMOSCLAUD_CODEX_MAX_OUTPUT_TOKENS", "12000"))
        if self.max_output_tokens < 256:
            raise ValueError("AMOSCLAUD_CODEX_MAX_OUTPUT_TOKENS must be at least 256")

        if client is None:
            api_key = os.getenv("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("Set OPENAI_API_KEY before enabling OpenAI/Codex execution")
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("Install the openai package to use CodexProvider") from exc
            client = OpenAI(api_key=api_key)
        self.client = client

    def next_step(
        self,
        *,
        objective: str,
        history: Sequence[dict[str, Any]],
        tools: Sequence[Tool],
        memory: Sequence[str],
    ) -> AgentStep:
        tool_contract = [
            {
                "name": tool.name,
                "description": tool.description,
                "requires_approval": tool.requires_approval,
            }
            for tool in tools
        ]
        prompt = {
            "objective": objective,
            "memory": list(memory),
            "tools": tool_contract,
            "history": [self._serialize(item) for item in history[-20:]],
            "instruction": (
                "Return one JSON object only. Either return "
                '{"thought":"...","tool":"tool_name","arguments":{...}} or '
                '{"thought":"...","final_answer":"..."}. '
                "Never include secrets in output. Do not claim completion until observations "
                "contain evidence that the objective was verified."
            ),
        }
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                "You are the Amosclaud autonomous engineering planner. Choose exactly one next "
                "action, obey tool permissions, keep changes inside the configured workspace, "
                "and return valid JSON only."
            ),
            input=json.dumps(prompt, ensure_ascii=False),
            max_output_tokens=self.max_output_tokens,
            store=False,
        )
        raw = getattr(response, "output_text", "")
        if not raw:
            raise ValueError("Codex provider returned an empty response")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Codex provider returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("Codex provider must return a JSON object")
        return AgentStep(
            thought=str(data.get("thought", "")),
            tool=data.get("tool"),
            arguments=dict(data.get("arguments") or {}),
            final_answer=data.get("final_answer"),
        )

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, AgentStep):
            return {
                "thought": value.thought,
                "tool": value.tool,
                "arguments": value.arguments,
                "final_answer": value.final_answer,
            }
        if isinstance(value, dict):
            return {key: CodexProvider._serialize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [CodexProvider._serialize(item) for item in value]
        return value
