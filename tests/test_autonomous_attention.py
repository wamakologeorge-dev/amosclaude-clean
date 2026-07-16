import pytest

torch = pytest.importorskip("torch")

from src.amosclaud_os.intelligence.attention import ScaledDotProductAttention


def test_attention_preserves_shape_and_normalizes_weights():
    layer = ScaledDotProductAttention(d_model=8)
    inputs = torch.randn(2, 4, 8)

    output, weights = layer(inputs, return_weights=True)

    assert output.shape == inputs.shape
    assert weights.shape == (2, 4, 4)
    assert torch.allclose(weights.sum(dim=-1), torch.ones(2, 4), atol=1e-5)


def test_attention_mask_blocks_disallowed_positions():
    layer = ScaledDotProductAttention(d_model=4)
    inputs = torch.randn(1, 3, 4)
    mask = torch.tensor([[[True, False, False], [True, True, False], [True, True, True]]])

    _, weights = layer(inputs, mask=mask, return_weights=True)

    assert weights[0, 0, 1].item() == pytest.approx(0.0, abs=1e-7)
    assert weights[0, 0, 2].item() == pytest.approx(0.0, abs=1e-7)


def test_attention_rejects_wrong_embedding_width():
    layer = ScaledDotProductAttention(d_model=8)
    with pytest.raises(ValueError, match="expected final dimension"):
        layer(torch.randn(1, 2, 7))
