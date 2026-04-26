import numpy as np
import pandas as pd

from veyraquant.config import AppConfig, SmtpConfig
from veyraquant.models import FundamentalsData, MarketContext, NewsBundle, TechSnapshot, TradePlan
from veyraquant.signals import analyze_symbol
from veyraquant.validator import validate_trade_plan


def make_config():
    return AppConfig(
        symbols=["NVDA"],
        market_symbols=["SPY", "QQQ", "SMH", "^VIX"],
        send_hour=7,
        send_minute=30,
        send_window_minutes=30,
        state_path="state/test.json",
        cache_dir=".cache/test",
        subject_prefix="Test",
        entry_alerts_enabled=True,
        alert_cooldown_hours=12,
        alert_score_threshold=65,
        social_sentiment_threshold=0.15,
        intraday_interval="30m",
        account_equity=100_000,
        risk_per_trade_pct=0.5,
        max_position_pct=10,
        portfolio_heat_max_pct=3,
        atr_stop_multiplier=2,
        min_rr=1.5,
        force_daily_report=False,
        dry_run=True,
        smtp=SmtpConfig("smtp.test", 465, None, None, None, None),
    )


def make_plan(
    entry_zone="$100.00 - $101.00",
    stop="$98.00",
    targets="$104.00 / $106.00",
    position_pct=10.0,
    max_loss_pct=0.3,
    rr=1.5,
):
    return TradePlan(
        entry_zone=entry_zone,
        stop=stop,
        targets=targets,
        position_pct=position_pct,
        max_loss_pct=max_loss_pct,
        rr=rr,
        trigger="buy",
        cancel="cancel",
        account_equity=100_000,
        position_value=10_000,
    )


def dummy_daily(rows=100):
    close = 100 + np.arange(rows) * 0.5
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_000_000, rows),
        },
        index=pd.date_range("2026-01-01", periods=rows, freq="B"),
    )


def bullish_market():
    return MarketContext(
        label="风险偏好",
        score=20.0,
        reasons=["market strong"],
        risks=[],
        snapshots={"QQQ": {"perf20": 5.0}, "SMH": {"perf20": 6.0}, "SPY": {"perf20": 4.0}},
    )


def breakout_snapshot():
    return TechSnapshot(
        {
            "last": 104.0,
            "high_20": 104.1,
            "sma5": 100.0,
            "sma10": 99.0,
            "sma20": 98.0,
            "sma50": 96.0,
            "atr14": 2.0,
            "rsi14": 58.0,
            "vol_ratio_5": 2.2,
            "close_position": 0.82,
            "dist_ma5_pct": 4.0,
            "dist_ma10_pct": 5.0,
        }
    )


def pullback_snapshot():
    return TechSnapshot(
        {
            "last": 101.0,
            "high_20": 106.0,
            "sma5": 101.5,
            "sma10": 101.0,
            "sma20": 100.5,
            "sma50": 98.0,
            "atr14": 2.0,
            "rsi14": 54.0,
            "vol_ratio_5": 0.6,
            "close_position": 0.55,
            "dist_ma5_pct": -0.49,
            "dist_ma10_pct": 0.0,
        }
    )


def news_bundle(score=0.3):
    label = "偏多" if score > 0 else "偏空" if score < 0 else "中性"
    return NewsBundle([], [], {"score": score, "label": label, "sample_size": 2})


def score_result(total_score):
    return {"base": float(total_score)}, ["scored"], []


def test_validator_rejects_entry_low_less_or_equal_stop():
    result = validate_trade_plan(make_plan(stop="$100.00"), make_config())

    assert not result.is_valid
    assert any("entry_low" in item for item in result.errors)


def test_validator_rejects_entry_high_less_or_equal_entry_low():
    result = validate_trade_plan(make_plan(entry_zone="$100.00 - $100.00"), make_config())

    assert not result.is_valid
    assert any("entry_high" in item for item in result.errors)


def test_entry_zone_width_below_warning_threshold_passes_cleanly():
    result = validate_trade_plan(make_plan(entry_zone="$100.00 - $102.50"), make_config())

    assert result.is_valid
    assert result.errors == []
    assert result.warnings == []


def test_entry_zone_width_between_warning_and_rejection_threshold_warns_only():
    result = validate_trade_plan(
        make_plan(entry_zone="$100.00 - $104.00", targets="$108.00 / $110.00"), make_config()
    )

    assert result.is_valid
    assert result.errors == []
    assert result.warnings == ["entry zone width 4.00% exceeds warning threshold 3.00%"]


def test_validator_rejects_entry_zone_width_over_rejection_threshold():
    result = validate_trade_plan(
        make_plan(entry_zone="$100.00 - $107.00", targets="$111.00 / $113.00"), make_config()
    )

    assert not result.is_valid
    assert result.errors == ["entry zone width 7.00% exceeds rejection threshold 6.00%"]


def test_validator_rejects_target1_not_above_entry_high():
    result = validate_trade_plan(make_plan(targets="$100.50 / $104.00"), make_config())

    assert not result.is_valid
    assert any("target1" in item for item in result.errors)


def test_validator_rejects_rr_below_min_rr():
    result = validate_trade_plan(make_plan(rr=1.2), make_config())

    assert not result.is_valid
    assert any("RR" in item for item in result.errors)


def test_validator_rejects_position_pct_above_config_max():
    result = validate_trade_plan(make_plan(position_pct=10.5), make_config())

    assert not result.is_valid
    assert any("position_pct" in item for item in result.errors)


def test_validator_rejects_max_loss_pct_above_risk_budget():
    result = validate_trade_plan(make_plan(max_loss_pct=0.6), make_config())

    assert not result.is_valid
    assert any("max_loss_pct" in item for item in result.errors)


def test_validator_rejects_missing_critical_fields():
    result = validate_trade_plan(make_plan(entry_zone="NA", stop="NA", targets="NA"), make_config())

    assert not result.is_valid
    assert any("entry zone" in item for item in result.errors)
    assert any("stop" in item for item in result.errors)
    assert any("target1" in item for item in result.errors)


def test_analyze_symbol_rejects_invalid_actionable_plan(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(72))
    monkeypatch.setattr(
        "veyraquant.signals.build_trade_plan",
        lambda action, tech, config: make_plan(stop="$100.00"),
    )

    result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.3),
        bullish_market(),
        make_config(),
    )

    assert result.action == "REJECT"
    assert result.is_actionable is False
    assert result.plan_kind == "reject"
    assert result.position_pct == 0.0
    assert result.max_loss_pct == 0.0
    assert result.targets == "NA"
    assert result.rejection_reasons


def test_valid_buy_trigger_plan_passes_validator():
    result = validate_trade_plan(make_plan(), make_config())

    assert result.is_valid
    assert result.errors == []


def test_valid_add_trigger_plan_passes_validator():
    result = validate_trade_plan(
        make_plan(entry_zone="$100.00 - $100.80", stop="$98.50", targets="$103.00 / $105.00", rr=1.5),
        make_config(),
    )

    assert result.is_valid
    assert result.errors == []


def test_validator_uses_configured_entry_zone_thresholds():
    config = make_config()
    config = AppConfig(
        symbols=config.symbols,
        market_symbols=config.market_symbols,
        send_hour=config.send_hour,
        send_minute=config.send_minute,
        send_window_minutes=config.send_window_minutes,
        state_path=config.state_path,
        cache_dir=config.cache_dir,
        subject_prefix=config.subject_prefix,
        entry_alerts_enabled=config.entry_alerts_enabled,
        alert_cooldown_hours=config.alert_cooldown_hours,
        alert_score_threshold=config.alert_score_threshold,
        social_sentiment_threshold=config.social_sentiment_threshold,
        intraday_interval=config.intraday_interval,
        account_equity=config.account_equity,
        risk_per_trade_pct=config.risk_per_trade_pct,
        max_position_pct=config.max_position_pct,
        portfolio_heat_max_pct=config.portfolio_heat_max_pct,
        atr_stop_multiplier=config.atr_stop_multiplier,
        min_rr=config.min_rr,
        force_daily_report=config.force_daily_report,
        dry_run=config.dry_run,
        smtp=config.smtp,
        max_entry_zone_width_warn_pct=2.0,
        max_entry_zone_width_reject_pct=5.0,
    )

    warning_result = validate_trade_plan(
        make_plan(entry_zone="$100.00 - $104.00", targets="$108.00 / $110.00"), config
    )
    reject_result = validate_trade_plan(
        make_plan(entry_zone="$100.00 - $106.00", targets="$110.00 / $112.00"), config
    )

    assert warning_result.is_valid
    assert warning_result.warnings == ["entry zone width 4.00% exceeds warning threshold 2.00%"]
    assert not reject_result.is_valid
    assert reject_result.errors == ["entry zone width 6.00% exceeds rejection threshold 5.00%"]
