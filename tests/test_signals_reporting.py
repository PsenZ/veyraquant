from datetime import datetime

import numpy as np
import pandas as pd

from veyraquant.config import AppConfig, SmtpConfig
from veyraquant.market import build_market_context
from veyraquant.models import FundamentalsData, MarketContext, NewsBundle, SignalResult, TechSnapshot, TradePlan
from veyraquant.reporting import (
    _contains_any_marker,
    _filter_by_markers,
    compose_alert_email,
    compose_daily_report,
)
from veyraquant.signals import analyze_symbol, choose_signal_type
from veyraquant.timeutils import SYDNEY_TZ


def make_config():
    return AppConfig(
        symbols=["NVDA", "MSFT"],
        market_symbols=["SPY", "QQQ", "SMH", "^VIX"],
        send_hour=7,
        send_minute=30,
        send_window_minutes=10,
        state_path="state/test.json",
        cache_dir=".cache/test",
        subject_prefix="Test Brief",
        entry_alerts_enabled=True,
        alert_cooldown_hours=12,
        alert_score_threshold=65,
        social_sentiment_threshold=0.15,
        intraday_interval="30m",
        account_equity=100_000,
        risk_per_trade_pct=0.5,
        max_position_pct=10,
        portfolio_heat_max_pct=0.6,
        atr_stop_multiplier=2,
        min_rr=1.5,
        force_daily_report=False,
        dry_run=True,
        smtp=SmtpConfig("smtp.test", 465, None, None, None, None),
    )


def price_frame(rows=260, start=100, step=0.4):
    close = start + np.arange(rows) * step
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.5,
            "Low": close - 1.5,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_000_000, rows),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )


def make_result(
    symbol,
    action,
    signal_type,
    score,
    *,
    setup_type="setup",
    is_actionable=False,
    plan_kind="wait",
    entry_zone="NA",
    stop="NA",
    targets="NA",
    position_pct=0.0,
    max_loss_pct=0.0,
    reasons=None,
    risks=None,
    warnings=None,
    rejection_reasons=None,
    suppressed_by=None,
):
    trade_plan = TradePlan(
        entry_zone=entry_zone,
        stop=stop,
        targets=targets,
        position_pct=position_pct,
        max_loss_pct=max_loss_pct,
        rr=1.8 if is_actionable else 0.0,
        trigger="wait for trigger" if not is_actionable else "breakout confirmed",
        cancel="cancel if invalidated",
        account_equity=100_000 if is_actionable else None,
        position_value=8_000 if is_actionable else None,
    )
    return SignalResult(
        rank=1,
        symbol=symbol,
        signal_type=signal_type,
        score=score,
        market_regime="风险偏好",
        entry_zone=entry_zone,
        stop=stop,
        targets=targets,
        position_pct=position_pct,
        max_loss_pct=max_loss_pct,
        reasons=reasons or ["reason a", "reason b"],
        risks=risks or [],
        contributions={"trend": 10.0},
        trade_plan=trade_plan,
        alert_kind="breakout_entry" if action == "BUY_TRIGGER" else "wait",
        signal_hash=f"{symbol}-{action}",
        last_price=100.0,
        warnings=warnings or [],
        rejection_reasons=rejection_reasons or [],
        setup_type=setup_type,
        action=action,
        is_actionable=is_actionable,
        suppressed_by=suppressed_by or [],
        plan_kind=plan_kind,
    )


def section(body: str, name: str) -> str:
    marker = f"[{name}]"
    start = body.index(marker)
    next_start = body.find("\n[", start + len(marker))
    if next_start == -1:
        return body[start:]
    return body[start:next_start]


def test_analyze_symbol_outputs_required_report_fields():
    config = make_config()
    daily = price_frame()
    market = build_market_context({"SPY": daily, "QQQ": daily, "SMH": daily})
    news = NewsBundle([], [], {"score": 0.3, "label": "偏多", "sample_size": 3})
    result = analyze_symbol(
        "NVDA",
        daily,
        None,
        FundamentalsData(recommendation_key="buy", revenue_growth=0.2),
        None,
        news,
        market,
        config,
    )

    assert result.symbol == "NVDA"
    assert result.score > 0
    assert result.market_regime in {"风险偏好", "中性震荡", "风险规避"}
    assert result.entry_zone
    assert result.stop
    assert result.targets
    assert result.position_pct >= 0
    assert result.max_loss_pct >= 0
    assert result.reasons
    assert "trend" in result.contributions


def test_daily_report_groups_results_into_new_sections():
    config = make_config()
    market = MarketContext(
        label="风险偏好",
        score=18.0,
        reasons=["QQQ above SMA20", "SMH strong"],
        risks=[],
        snapshots={"SPY": {"last": 500, "sma20": 490, "sma50": 480, "perf20": 3.2}},
    )
    buy_result = make_result(
        "NVDA",
        "BUY_TRIGGER",
        "突破入场",
        88,
        setup_type="breakout_entry",
        is_actionable=True,
        plan_kind="buy",
        entry_zone="$100.00 - $101.00",
        stop="$98.00",
        targets="$104.00 / $106.00",
        position_pct=8.0,
        max_loss_pct=0.4,
        risks=["entry zone width 4.00% exceeds warning threshold 3.00%", "portfolio heat trimmed"],
    )
    add_result = make_result(
        "AMD",
        "ADD_TRIGGER",
        "趋势回踩加仓",
        77,
        setup_type="pullback_add",
        is_actionable=True,
        plan_kind="add",
        entry_zone="$50.00 - $50.50",
        stop="$48.00",
        targets="$54.00 / $56.00",
        position_pct=6.0,
        max_loss_pct=0.5,
    )
    watch_result = make_result(
        "MSFT",
        "WATCH",
        "持有观察",
        58,
        plan_kind="watch",
        reasons=["need cleaner pullback"],
    )
    reject_result = make_result(
        "QQQ",
        "REJECT",
        "禁止交易/等待",
        72,
        plan_kind="reject",
        entry_zone="交易计划校验失败，不执行买入计划",
        rejection_reasons=["target1 must exceed entry_high"],
        suppressed_by=["trade_plan_validation_failed"],
    )

    subject, body = compose_daily_report(
        [buy_result, add_result, watch_result, reject_result],
        market,
        config,
        datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ),
    )

    assert "Test Brief" in subject
    assert "[Today Conclusion]" in body
    assert "[Market Filter]" in body
    assert "[Action List]" in body
    assert "[Hold / Watch]" in body
    assert "[Rejected Plans]" in body
    assert "Sydney 2026-04-20 07:30 / US Eastern 2026-04-19 17:30" in body

    action_section = section(body, "Action List")
    assert "NVDA" in action_section
    assert "BUY_TRIGGER" in action_section
    assert "AMD" in action_section
    assert "ADD_TRIGGER" in action_section
    assert "validation_warnings:" in action_section
    assert "entry zone width 4.00% exceeds warning threshold 3.00%" in action_section
    assert "plan:" in action_section
    assert "risk: position 8.00% | max_loss 0.40%" in action_section
    assert action_section.count("\n## ") <= 3

    hold_section = section(body, "Hold / Watch")
    assert "MSFT" in hold_section
    assert "WATCH" in hold_section
    assert "next:" in hold_section
    assert "summary:" in hold_section
    assert "position_pct:" not in hold_section
    assert "entry_zone:" not in hold_section

    rejected_section = section(body, "Rejected Plans")
    assert "QQQ" in rejected_section
    assert "rejection:" in rejected_section
    assert "trade_plan_validation_failed" in rejected_section

    system_notes = section(body, "System Notes")
    assert "portfolio heat warnings:" in system_notes


def test_non_actionable_does_not_display_buy_plan_in_hold_watch_section():
    config = make_config()
    market = MarketContext("中性震荡", 0.0, ["neutral"], [], {})
    wait_result = make_result(
        "AAPL",
        "WAIT",
        "禁止交易/等待",
        40,
        plan_kind="wait",
        entry_zone="等待更清晰的趋势或市场确认",
    )

    _subject, body = compose_daily_report(
        [wait_result], market, config, datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    )

    hold_section = section(body, "Hold / Watch")
    assert "AAPL" in hold_section
    assert "WAIT" in hold_section
    assert "entry_zone:" not in hold_section
    assert "position_pct:" not in hold_section


def test_action_list_and_rejected_sections_do_not_depend_on_risk_text_keywords():
    config = make_config()
    market = MarketContext("风险偏好", 10.0, ["strong"], [], {})
    buy_result = make_result(
        "TSLA",
        "BUY_TRIGGER",
        "突破入场",
        81,
        setup_type="breakout_entry",
        is_actionable=True,
        plan_kind="buy",
        entry_zone="$200.00 - $201.00",
        stop="$196.00",
        targets="$208.00 / $212.00",
        position_pct=7.0,
        max_loss_pct=0.5,
        risks=["this text says wait but should not change section"],
    )
    reject_result = make_result(
        "SMH",
        "REJECT",
        "禁止交易/等待",
        67,
        plan_kind="reject",
        entry_zone="交易计划校验失败，不执行买入计划",
        risks=["contains breakout wording but still rejected"],
        rejection_reasons=["RR below threshold"],
        suppressed_by=["trade_plan_validation_failed"],
    )

    _subject, body = compose_daily_report(
        [buy_result, reject_result], market, config, datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    )

    action_section = section(body, "Action List")
    rejected_section = section(body, "Rejected Plans")
    assert "TSLA" in action_section
    assert "SMH" not in action_section
    assert "SMH" in rejected_section


def test_reporting_helpers_match_keyword_markers():
    risks = [
        "entry zone width 4.00% exceeds warning threshold 3.00%",
        "portfolio heat trimmed position",
        "avoid chase after sharp extension",
    ]

    assert _contains_any_marker(risks, ("chase",))
    assert _filter_by_markers(risks, ("warning threshold",)) == [
        "entry zone width 4.00% exceeds warning threshold 3.00%"
    ]
    assert _filter_by_markers(risks, ("portfolio heat",)) == [
        "portfolio heat trimmed position"
    ]


def test_alert_email_contains_dual_timezone_header():
    result = make_result(
        "NVDA",
        "BUY_TRIGGER",
        "突破入场",
        88,
        setup_type="breakout_entry",
        is_actionable=True,
        plan_kind="buy",
        entry_zone="$100.00 - $101.00",
        stop="$98.00",
        targets="$104.00 / $106.00",
        position_pct=8.0,
        max_loss_pct=0.4,
    )

    _subject, body = compose_alert_email(
        result, datetime(2026, 4, 20, 7, 30, tzinfo=SYDNEY_TZ)
    )

    assert "Sydney 2026-04-20 07:30 / US Eastern 2026-04-19 17:30" in body


def test_breakout_requires_volume_and_negative_news_can_veto():
    config = make_config()
    tech = TechSnapshot(
        {
            "last": 104.0,
            "high_20": 104.1,
            "sma5": 100.0,
            "sma10": 99.0,
            "sma20": 98.0,
            "atr14": 2.0,
            "rsi14": 58.0,
            "vol_ratio_5": 2.2,
            "close_position": 0.82,
            "dist_ma5_pct": 4.0,
            "dist_ma10_pct": 5.0,
        }
    )
    market = MarketContext("风险偏好", 20.0, [], [], {"QQQ": {"perf20": 5.0}, "SMH": {"perf20": 6.0}})
    positive_news = NewsBundle([], [], {"score": 0.25, "label": "偏多", "sample_size": 3})
    negative_news = NewsBundle([], [], {"score": -0.35, "label": "偏空", "sample_size": 3})

    signal_type, alert_kind = choose_signal_type(tech, None, 72, market, positive_news, config)
    veto_signal_type, veto_alert_kind = choose_signal_type(
        tech, None, 72, market, negative_news, config
    )

    assert signal_type == "突破入场"
    assert alert_kind == "breakout_entry"
    assert veto_signal_type == "禁止交易/等待"
    assert veto_alert_kind == "wait"
