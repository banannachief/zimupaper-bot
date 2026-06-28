from src.agent.sentiment import analyze, apply_tilt


def test_no_sentiment_leaves_weights_unchanged():
    w = {"SPY": 0.4, "QQQ": 0.4, "BIL": 0.2}
    assert apply_tilt(w, {}, strength=0.3) == w
    assert apply_tilt(w, {"SPY": 0.5}, strength=0.0) == w


def test_tilt_preserves_gross_exposure():
    w = {"SPY": 0.3, "QQQ": 0.3, "BIL": 0.4}
    out = apply_tilt(w, {"SPY": 1.0, "QQQ": -0.2}, strength=0.3)
    risk_before = w["SPY"] + w["QQQ"]
    risk_after = sum(v for s, v in out.items() if s != "BIL")
    assert abs(risk_after - risk_before) < 1e-9        # no added leverage
    assert out["SPY"] > out["QQQ"]                      # bullish name tilted up


def test_strong_bearish_drops_name_to_cash():
    w = {"SPY": 0.5, "QQQ": 0.5}
    out = apply_tilt(w, {"QQQ": -0.8}, strength=0.3, cash_asset="BIL")
    assert "QQQ" not in out                              # bailed out of bearish name
    assert abs(out.get("SPY", 0) - 0.5) < 1e-9 or out.get("SPY", 0) > 0


def test_analyze_safe_without_key_or_news():
    # no API key + no news -> empty (never raises, never trades on noise)
    assert analyze([], ["SPY"], api_key="") == {}
    assert analyze([{"symbols": ["SPY"], "headline": "x"}], ["SPY"], api_key="") == {}
