from datetime import datetime

import numpy as np
import pandas as pd

from veyraquant.config import AppConfig, SmtpConfig
from veyraquant.models import (
    FundamentalsData,
    MarketContext,
    NewsBundle,
    SignalResult,
    TechSnapshot,
    TradePlan,
)
from veyraquant.reporting import compose_alert_email, compose_daily_report
from veyraquant.signals import analyze_symbol, enforce_portfolio_heat
from veyraquant.timeutils import SYDNEY_TZ


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


def watch_snapshot():
    return TechSnapshot(
        {
            "last": 103.0,
            "high_20": 110.0,
            "sma5": 102.0,
            "sma10": 101.0,
            "sma20": 100.0,
            "sma50": 98.0,
            "atr14": 2.0,
            "rsi14": 57.0,
            "vol_ratio_5": 1.0,
            "close_position": 0.55,
            "dist_ma5_pct": 0.98,
            "dist_ma10_pct": 1.98,
        }
    )


def news_bundle(score):
    label = "偏多" if score > 0 else "偏空" if score < 0 else "中性"
    return NewsBundle([], [], {"score": score, "label": label, "sample_size": 3})


def score_result(total_score):
    return {"base": float(total_score)}, ["scored"], []


def assert_result_consistency(result):
    if result.action in {"BUY_TRIGGER", "ADD_TRIGGER"}:
        assert result.is_actionable
        assert result.plan_kind in {"buy", "add"}
        assert result.position_pct > 0
        assert result.max_loss_pct > 0
        assert result.stop != "NA"
        assert result.targets != "NA"
    else:
        assert not result.is_actionable
        assert result.plan_kind in {"watch", "reduce", "wait", "reject"}
        assert result.position_pct == 0.0
        assert result.max_loss_pct == 0.0
        assert result.stop == "NA"
        assert result.targets == "NA"


def test_negative_news_veto_keeps_final_action_and_plan_consistent(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(72))

    result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(-0.35),
        bullish_market(),
        make_config(),
    )

    assert result.setup_type == "breakout_entry"
    assert result.action == "REJECT"
    assert result.signal_type == "禁止交易/等待"
    assert "negative_news_veto" in result.suppressed_by
    assert result.plan_kind == "reject"
    assert_result_consistency(result)


def test_rr_downgrade_removes_buy_plan_fields(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(72))
    monkeypatch.setattr(
        "veyraquant.signals.preview_trade_plan",
        lambda action, tech, config: TradePlan(
            entry_zone="$100.00 - $101.00",
            stop="$98.00",
            targets="$101.00 / $102.00",
            position_pct=5.0,
            max_loss_pct=0.5,
            rr=1.0,
            trigger="preview",
            cancel="preview",
            account_equity=config.account_equity,
            position_value=5_000.0,
        ),
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

    assert result.setup_type == "breakout_entry"
    assert result.action == "WATCH"
    assert result.signal_type == "持有观察"
    assert "rr_below_min" in result.suppressed_by
    assert result.plan_kind == "watch"
    assert_result_consistency(result)


def test_watch_output_is_non_actionable(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: watch_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(58))

    result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.0),
        bullish_market(),
        make_config(),
    )

    assert result.setup_type == "hold_watch"
    assert result.action == "WATCH"
    assert result.signal_type == "持有观察"
    assert_result_consistency(result)


def test_wait_output_does_not_keep_position_or_targets(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: watch_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(45))

    result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.0),
        bullish_market(),
        make_config(),
    )

    assert result.setup_type == "wait"
    assert result.action == "WAIT"
    assert result.signal_type == "禁止交易/等待"
    assert_result_consistency(result)


def test_buy_trigger_still_generates_full_trade_plan(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(72))

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

    assert result.setup_type == "breakout_entry"
    assert result.action == "BUY_TRIGGER"
    assert result.signal_type == "突破入场"
    assert result.plan_kind == "buy"
    assert result.trade_plan.trigger
    assert result.trade_plan.cancel
    assert_result_consistency(result)


def test_add_trigger_still_generates_full_trade_plan(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: pullback_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(64))

    result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.2),
        bullish_market(),
        make_config(),
    )

    assert result.setup_type == "pullback_add"
    assert result.action == "ADD_TRIGGER"
    assert result.signal_type == "趋势回踩加仓"
    assert result.plan_kind == "add"
    assert result.trade_plan.trigger
    assert result.trade_plan.cancel
    assert_result_consistency(result)


def test_signal_result_new_fields_have_safe_defaults():
    plan = TradePlan(
        entry_zone="NA",
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
        rr=0.0,
        trigger="none",
        cancel="none",
    )

    result = SignalResult(
        rank=1,
        symbol="NVDA",
        signal_type="禁止交易/等待",
        score=0,
        market_regime="中性震荡",
        entry_zone="NA",
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
        reasons=[],
        risks=[],
        contributions={},
        trade_plan=plan,
        alert_kind="wait",
        signal_hash="abc123",
        last_price=None,
    )

    assert result.setup_type == ""
    assert result.action == "WAIT"
    assert result.is_actionable is False
    assert result.suppressed_by == []
    assert result.plan_kind == "wait"


def test_non_actionable_signal_does_not_consume_portfolio_heat():
    watch_plan = TradePlan(
        entry_zone="观察为主，不新增仓位",
        stop="NA",
        targets="NA",
        position_pct=8.0,
        max_loss_pct=0.8,
        rr=0.0,
        trigger="watch",
        cancel="watch",
    )
    buy_plan = TradePlan(
        entry_zone="$100.00 - $101.00",
        stop="$98.00",
        targets="$104.00 / $106.00",
        position_pct=10.0,
        max_loss_pct=0.5,
        rr=2.0,
        trigger="buy",
        cancel="buy",
    )

    watch_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.0),
        bullish_market(),
        make_config(),
    )
    watch_result.action = "WATCH"
    watch_result.is_actionable = False
    watch_result.plan_kind = "watch"
    watch_result.position_pct = 8.0
    watch_result.max_loss_pct = 0.8
    watch_result.trade_plan = watch_plan
    watch_result.entry_zone = watch_plan.entry_zone
    watch_result.stop = watch_plan.stop
    watch_result.targets = watch_plan.targets

    buy_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.3),
        bullish_market(),
        make_config(),
    )
    buy_result.action = "BUY_TRIGGER"
    buy_result.is_actionable = True
    buy_result.plan_kind = "buy"
    buy_result.position_pct = 10.0
    buy_result.max_loss_pct = 0.5
    buy_result.trade_plan = buy_plan
    buy_result.entry_zone = buy_plan.entry_zone
    buy_result.stop = buy_plan.stop
    buy_result.targets = buy_plan.targets

    results = enforce_portfolio_heat([watch_result, buy_result], 0.3)

    assert results[0].position_pct == 8.0
    assert results[0].max_loss_pct == 0.8
    assert results[1].position_pct == 6.0
    assert results[1].max_loss_pct == 0.3


def test_reporting_can_render_non_actionable_signals_without_crashing(monkeypatch):
    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: watch_snapshot())
    monkeypatch.setattr("veyraquant.signals.intraday_snapshot", lambda _intraday: None)
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(58))
    watch_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(0.0),
        bullish_market(),
        make_config(),
    )

    monkeypatch.setattr("veyraquant.signals.tech_summary", lambda _daily: breakout_snapshot())
    monkeypatch.setattr("veyraquant.signals.score_components", lambda *args, **kwargs: score_result(72))
    reject_result = analyze_symbol(
        "NVDA",
        dummy_daily(),
        None,
        FundamentalsData(),
        None,
        news_bundle(-0.35),
        bullish_market(),
        make_config(),
    )

    market = bullish_market()
    subject, daily_body = compose_daily_report(
        [watch_result, reject_result], market, make_config(), datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    )
    _alert_subject, alert_body = compose_alert_email(
        watch_result, datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    )

    assert subject
    assert "[Hold / Watch]" in daily_body
    assert "[Rejected Plans]" in daily_body
    assert "symbol: NVDA | score: 58 | action: WATCH" in daily_body
    assert "No rejected actionable plans." not in daily_body
    assert "position_pct: 0.00%" in alert_body
    assert "targets: NA" in alert_body
    assert "stop: NA" in alert_body
