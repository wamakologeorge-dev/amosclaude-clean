from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from src.amosclaud_os.intelligence.generation import (
    LanguageModelHead,
    decode_token_stream,
    evaluate_stop,
    generate_autoregressive,
    top_p_filter,
)


class FakeTokenizer:
    eos_token_id = 2

    def decode(self, token_ids):
        return "".join({0: "a", 1: "b", 2: "<eos>", 3: "`"}.get(i, "?") for i in token_ids)


class FakeModel:
    def __init__(self):
        self.calls = []
        self.step = 0

    def __call__(self, input_ids, *, past_key_values=None, use_cache=True):
        self.calls.append((tuple(input_ids.shape), past_key_values, use_cache))
        logits = torch.full((1, input_ids.shape[1], 4), -1000.0)
        token = 1 if self.step == 0 else 2
        logits[:, -1, token] = 1000.0
        self.step += 1
        return SimpleNamespace(logits=logits, past_key_values=f"cache-{self.step}")


def test_lm_head_projects_to_vocabulary():
    head = LanguageModelHead(d_model=8, vocab_size=32)
    output = head(torch.randn(2, 5, 8))
    assert output.shape == (2, 5, 32)


def test_top_p_keeps_at_least_one_token():
    logits = torch.tensor([[10.0, 1.0, 0.0]])
    filtered = top_p_filter(logits, top_p=0.1)
    assert torch.isfinite(filtered[0, 0])
    assert not torch.isfinite(filtered[0, 1])


def test_decode_and_stop_evaluation():
    tokenizer = FakeTokenizer()
    assert decode_token_stream(tokenizer, [0, 1]) == "ab"
    assert evaluate_stop(token_id=2, generated_text="ab<eos>", eos_token_id=2) == "eos_token"
    assert evaluate_stop(token_id=1, generated_text="abc```", eos_token_id=2, stop_sequences=("```",)) == "stop_sequence:```"


def test_generation_reuses_cache_and_stops_on_eos():
    model = FakeModel()
    tokenizer = FakeTokenizer()
    result = generate_autoregressive(
        model,
        tokenizer,
        torch.tensor([[0, 1]]),
        max_new_tokens=5,
        top_p=1.0,
    )

    assert result.token_ids == (1, 2)
    assert result.stop_reason == "eos_token"
    assert model.calls[0][0] == (1, 2)
    assert model.calls[0][1] is None
    assert model.calls[1][0] == (1, 1)
    assert model.calls[1][1] == "cache-1"
