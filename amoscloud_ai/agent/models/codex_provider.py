from __future__ import annotations

import json
import os
from typing import Any, Sequence

from src.agent.model import AutonomousModelGateway, load_model_config

from ..runtime import AgentStep, Tool


class CodexProvider:
    """Autonomous planner using first-party runtime or opt-in Codex Cloud."""

    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self.config = load_model_config()
        self.model = model or os.getenv("AMOSCLAUD_CODEX_MODEL", "").strip() or self.config.model
        if not self.model:
            raise RuntimeError("Configure an Amosclaud model or AMOSCLAUD_CODEX_MODEL")

        self.max_output_tokens = int(os.getenv("AMOSCLAUD_CODEX_MAX_OUTPUT_TOKENS", "12000"))
        if self.max_output_tokens < 256:
            raise ValueError("AMOSCLAUD_CODEX_MAX_OUTPUT_TOKENS must be at least 256")

        self.client = client
        self.gateway: AutonomousModelGateway | None = None
        if client is None and self.config.provider == "openai":
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("Install the openai package to use Codex Cloud") from exc
            self.client = OpenAI(api_key=self.config.api_key, base_url=self.config.endpoint)
        elif client is None:
            self.gateway = AutonomousModelGateway(self.config)
            if not self.gateway.available():
                raise RuntimeError("Configure an Amosclaud runtime or enable the OpenAI adapter for Codex Cloud")

    def next_step(
        self,
        *,
        objective: str,
        history: Sequence[dict[str, Any]],
        tools: Sequence[Tool],
        memory: Sequence[str],
    ) -> AgentStep:
        tool_contract = [
            {"name": tool.name, "description": tool.description, "requires_approval": tool.requires_approval}
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
        raw = self._complete(json.dumps(prompt, ensure_ascii=False))
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

    def _complete(self, prompt: str) -> str:
        if self.client is not None:
            response = self.client.responses.create(
                model=self.model,
                instructions=(
                    "You are the Amosclaud autonomous engineering planner. Choose exactly one next "
                    "action, obey tool permissions, keep changes inside the configured workspace, "
                    "and return valid JSON only."
                ),
                input=prompt,
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
            raw = getattr(response, "output_text", "")
        else:
            assert self.gateway is not None
            raw = self.gateway.complete("Choose the next autonomous engineering action.", [prompt])
        if not raw:
            raise ValueError("Codex provider returned an empty response")
        return str(raw)

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, AgentStep):
            return {"thought": value.thought, "tool": value.tool, "arguments": value.arguments, "final_answer": value.final_answer}
        if isinstance(value, dict):
            return {key: CodexProvider._serialize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [CodexProvider._serialize(item) for item in value]
        return value
