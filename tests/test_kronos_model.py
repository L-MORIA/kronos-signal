"""Тесты исправлений kronos-source/model/kronos.py:

- sample_from_logits: top_k=None больше не падает TypeError
- top_k_top_p_filtering: top-k и top-p применяются последовательно, а не либо/или
- top_k_top_p_filtering: входной тензор не мутирует
- KronosPredictor.predict: валидация длин x_timestamp / y_timestamp
- sample_from_logits: temperature <= 0 → явная ошибка вместо NaN
"""
import numpy as np
import pandas as pd
import pytest
import torch

import conftest  # noqa: F401  (кладёт kronos-source в sys.path)
from model.kronos import sample_from_logits, top_k_top_p_filtering, KronosPredictor


# ── sample_from_logits ────────────────────────────────────────────────

def test_sample_from_logits_none_top_k_with_top_p():
    """top_k=None + top_p<1 раньше падал TypeError: None > 0."""
    logits = torch.tensor([[5.0, 4.0, 1.0, 0.5]])
    out = sample_from_logits(logits, temperature=1.0, top_k=None, top_p=0.9)
    assert out.shape == (1, 1)
    assert 0 <= out.item() <= 3


def test_sample_from_logits_none_both():
    logits = torch.tensor([[1.0, 2.0]])
    out = sample_from_logits(logits, temperature=1.0, top_k=None, top_p=None)
    assert 0 <= out.item() <= 1


def test_sample_from_logits_zero_temperature_raises():
    logits = torch.tensor([[1.0, 2.0]])
    with pytest.raises(ValueError):
        sample_from_logits(logits, temperature=0.0)


def test_sample_from_logits_greedy():
    logits = torch.tensor([[0.0, 10.0, 1.0]])
    out = sample_from_logits(logits, sample_logits=False)
    assert out.item() == 1


# ── top_k_top_p_filtering ─────────────────────────────────────────────

def test_filter_combines_top_k_and_top_p():
    """top_k=3, top_p≈0.7: третий по вероятности токен должен вырезаться
    nucleus'ом — то есть оба фильтра применяются последовательно
    (раньше top_k>0 делал early return и top_p игнорировался)."""
    logits = torch.tensor([[10.0, 9.0, 8.0, 1.0]])
    out = top_k_top_p_filtering(logits.clone(), top_k=3, top_p=0.7)
    assert out[0, 0] > -float("inf")
    assert out[0, 1] > -float("inf")
    assert out[0, 2] == -float("inf")   # вырезан nucleus'ом из top-3
    assert out[0, 3] == -float("inf")   # вырезан top-k


def test_filter_top_k_only():
    logits = torch.tensor([[10.0, 5.0, 1.0, 0.0]])
    out = top_k_top_p_filtering(logits.clone(), top_k=2, top_p=1.0)
    assert out[0, 0] > -float("inf")
    assert out[0, 1] > -float("inf")
    assert out[0, 2] == -float("inf")
    assert out[0, 3] == -float("inf")


def test_filter_top_p_only():
    logits = torch.tensor([[10.0, 5.0, 1.0, 0.0]])
    # softmax ≈ [0.9931, 0.0067, 0.00012, 0.00005]: nucleus 0.999 держит первые два
    out = top_k_top_p_filtering(logits.clone(), top_k=0, top_p=0.999)
    assert out[0, 0] > -float("inf")
    assert out[0, 1] > -float("inf")
    assert out[0, 2] == -float("inf")
    assert out[0, 3] == -float("inf")


def test_filter_top_p_keeps_top_token_when_it_exceeds_nucleus():
    logits = torch.tensor([[10.0, 5.0, 1.0]])
    # p0 ≈ 0.993 > 0.99: остаётся только лучший токен
    out = top_k_top_p_filtering(logits.clone(), top_k=0, top_p=0.99)
    assert out[0, 0] > -float("inf")
    assert out[0, 1] == -float("inf")
    assert out[0, 2] == -float("inf")


def test_filter_does_not_mutate_input():
    logits = torch.tensor([[3.0, 2.0, 1.0]])
    snapshot = logits.clone()
    top_k_top_p_filtering(logits, top_k=1, top_p=1.0)
    assert torch.equal(logits, snapshot)


def test_filter_accepts_none():
    logits = torch.tensor([[3.0, 2.0, 1.0]])
    out = top_k_top_p_filtering(logits.clone(), top_k=None, top_p=None)
    assert torch.isfinite(out).all()


# ── KronosPredictor.predict: валидация ────────────────────────────────

class _DummyPredictor(KronosPredictor):
    """predict() без модели: валидация срабатывает раньше generate()."""

    def __init__(self):
        self.price_cols = ['open', 'high', 'low', 'close']
        self.vol_col = 'volume'
        self.amt_vol = 'amount'
        self.device = 'cpu'
        self.clip = 5
        self.max_context = 512

    def generate(self, *a, **kw):
        raise AssertionError("generate() не должен вызываться при невалидном входе")


@pytest.fixture()
def predictor():
    return _DummyPredictor()


@pytest.fixture()
def ohlcv_df():
    n = 30
    idx = pd.date_range("2026-01-05 10:00", periods=n, freq="5min")
    rng = np.random.RandomState(0)
    close = 300 + rng.randn(n).cumsum()
    return pd.DataFrame({
        "open": close - 0.3, "high": close + 0.7, "low": close - 0.8,
        "close": close, "volume": rng.randint(100, 1000, n).astype(float),
    }, index=range(n)), idx


def test_predict_rejects_x_timestamp_length_mismatch(predictor, ohlcv_df):
    df, idx = ohlcv_df
    future = pd.date_range(idx[-1], periods=6, freq="5min")[1:]
    with pytest.raises(ValueError, match="x_timestamp"):
        predictor.predict(df=df, x_timestamp=pd.Series(idx[:-1]),
                          y_timestamp=pd.Series(future), pred_len=5)


def test_predict_rejects_y_timestamp_length_mismatch(predictor, ohlcv_df):
    df, idx = ohlcv_df
    future = pd.date_range(idx[-1], periods=6, freq="5min")[1:]
    with pytest.raises(ValueError, match="pred_len"):
        predictor.predict(df=df, x_timestamp=pd.Series(idx),
                          y_timestamp=pd.Series(future), pred_len=3)


def test_predict_accepts_valid_lengths_and_runs(predictor, ohlcv_df):
    df, idx = ohlcv_df
    future = pd.date_range(idx[-1], periods=6, freq="5min")[1:]
    # подменяем generate, чтобы проверить, что валидный вход доходит до него
    called = {}

    def fake_generate(x, x_stamp, y_stamp, pred_len, *a, **kw):
        called["shapes"] = (x.shape, x_stamp.shape, y_stamp.shape, pred_len)
        return np.zeros((1, pred_len, 6), dtype=np.float32)

    predictor.generate = fake_generate
    out = predictor.predict(df=df, x_timestamp=pd.Series(idx),
                            y_timestamp=pd.Series(future), pred_len=5, verbose=False)
    assert out.shape == (5, 6)
    assert called["shapes"][3] == 5
