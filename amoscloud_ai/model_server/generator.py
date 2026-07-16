"""Autoregressive generation engine with cache, sampling, stop rules, and metrics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import torch

from .context import ContextWindow
from .kv_cache import KVCache
from .metrics import GenerationMetrics, Timer
from .sampling import SamplingConfig, sample_next_token
from .stop_tokens import StopEvaluator


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    max_new_tokens: int = 256
    sampling: SamplingConfig = SamplingConfig()
    stop_sequences: tuple[str, ...] = ()


class AutoregressiveGenerator:
    """Drive compatible causal models one token at a time.

    Compatible models return an object with ``logits`` and optionally
    ``past_key_values``. When the model accepts ``past_key_values`` and
    ``use_cache``, only the newest token is sent after the first step.
    """

    def __init__(self, model, tokenizer, *, context_window: ContextWindow, metrics: GenerationMetrics | None = None) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.context_window = context_window
        self.metrics = metrics or GenerationMetrics()

    def _device(self):
        try:
            return next(self.model.parameters()).device
        except (StopIteration, AttributeError):
            return torch.device("cpu")

    @torch.inference_mode()
    def stream(self, request: GenerationRequest) -> Iterator[str]:
        if request.max_new_tokens <= 0:
            raise ValueError("max_new_tokens must be greater than zero")
        prompt_ids = self.tokenizer.encode(request.prompt)
        prompt_ids = self.context_window.trim_token_ids(prompt_ids)
        input_ids = torch.tensor([prompt_ids], dtype=torch.long, device=self._device())
        eos = getattr(self.tokenizer, "eos_token_id", None)
        stop = StopEvaluator({eos} if eos is not None else set(), request.stop_sequences)
        generated_ids: list[int] = []
        past = None
        emitted_text = ""
        failed = False
        timer = Timer()
        timer.__enter__()
        try:
            for _ in range(min(request.max_new_tokens, self.context_window.reserve_output_tokens)):
                model_input = input_ids if past is None else input_ids[:, -1:]
                kwargs = {"input_ids": model_input}
                if past is not None:
                    kwargs["past_key_values"] = past
                try:
                    output = self.model(**kwargs, use_cache=True)
                except TypeError:
                    output = self.model(**kwargs)
                logits = output.logits[:, -1, :]
                token = sample_next_token(logits, request.sampling)
                token_id = int(token.item())
                generated_ids.append(token_id)
                input_ids = torch.cat((input_ids, token.to(input_ids.device)), dim=-1)
                past = getattr(output, "past_key_values", None)
                full_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
                delta = full_text[len(emitted_text):]
                emitted_text = full_text
                should_stop, _reason = stop.should_stop(token_id, full_text)
                if delta:
                    yield delta
                if should_stop:
                    break
        except Exception:
            failed = True
            raise
        finally:
            timer.__exit__(None, None, None)
            self.metrics.record(
                input_tokens=len(prompt_ids),
                output_tokens=len(generated_ids),
                latency_seconds=timer.elapsed,
                cache_tokens_reused=max(0, len(generated_ids) - 1) if past is not None else 0,
                failed=failed,
            )

    def generate(self, request: GenerationRequest) -> str:
        text = "".join(self.stream(request))
        return StopEvaluator(stop_sequences=request.stop_sequences).trim(text)
