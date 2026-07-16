from __future__ import annotations

import pytest

torch = pytest.importorskip(
    "torch",
    reason="model-server tests require the optional PyTorch dependency",
)

from amoscloud_ai.model_server import (  # noqa: E402
    ByteTokenizer,
    ContextWindow,
    KVCache,
    MultiHeadAttention,
    SamplingConfig,
    StopEvaluator,
    TransformerConfig,
    TransformerStack,
    apply_kv_cache,
    sample_next_token,
)


def test_byte_tokenizer_round_trip() -> None:
    tokenizer = ByteTokenizer()
    text = "def hello():\n    return 'world'"
    assert tokenizer.decode(tokenizer.encode(text)) == text


def test_context_window_preserves_prefix_and_tail() -> None:
    window = ContextWindow(max_tokens=10, reserve_output_tokens=2)
    trimmed = window.trim_token_ids(list(range(12)), keep_prefix=2)
    assert trimmed == [0, 1, 6, 7, 8, 9, 10, 11]


def test_kv_cache_appends_sequence_dimension() -> None:
    first = torch.randn(1, 2, 3, 4)
    second = torch.randn(1, 2, 1, 4)
    cache = KVCache()
    cache.append(first, first)
    key, value = cache.append(second, second)
    assert key.shape == value.shape == (1, 2, 4, 4)
    key2, value2 = apply_kv_cache(
        second,
        second,
        (first, first),
    )
    assert key2.shape == value2.shape == (1, 2, 4, 4)


def test_sampling_returns_valid_token() -> None:
    torch.manual_seed(3)
    logits = torch.tensor([[9.0, 2.0, 1.0, -2.0]])
    token = sample_next_token(
        logits,
        SamplingConfig(
            temperature=1.0,
            top_p=0.9,
            do_sample=False,
        ),
    )
    assert token.shape == (1, 1)
    assert token.item() == 0


def test_stop_evaluator_detects_eos_and_sequence() -> None:
    evaluator = StopEvaluator({7}, ("```",))
    assert evaluator.should_stop(7, "hello") == (True, "eos_token")
    stopped, reason = evaluator.should_stop(2, "hello```")
    assert stopped
    assert reason == "stop_sequence:```"


def test_multi_head_attention_shapes_and_cache() -> None:
    layer = MultiHeadAttention(d_model=16, num_heads=4)
    output, cache = layer(torch.randn(2, 3, 16), use_cache=True)
    assert output.shape == (2, 3, 16)
    assert cache is not None
    assert cache.length == 3

    output2, cache2 = layer(
        torch.randn(2, 1, 16),
        cache=cache,
        use_cache=True,
    )
    assert output2.shape == (2, 1, 16)
    assert cache2 is not None
    assert cache2.length == 4


def test_transformer_stack_forward() -> None:
    model = TransformerStack(
        TransformerConfig(
            vocab_size=257,
            d_model=32,
            num_heads=4,
            num_layers=2,
            max_length=64,
        )
    )
    hidden, caches = model(
        torch.randint(0, 257, (2, 5)),
        use_cache=True,
    )
    assert hidden.shape == (2, 5, 32)
    assert len(caches) == 2
    assert all(
        cache is not None and cache.length == 5
        for cache in caches
    )
