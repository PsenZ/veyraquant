from datetime import datetime
from types import SimpleNamespace

from veyraquant.runner import maybe_send_daily_report, maybe_send_entry_alerts
from veyraquant.state import mark_daily_sent, migrate_state
from veyraquant.timeutils import SYDNEY_TZ


def test_force_daily_report_sends_without_updating_daily_state(monkeypatch):
    sent = []
    monkeypatch.setattr("veyraquant.runner.compose_daily_report", lambda *args: ("subject", "body"))
    monkeypatch.setattr("veyraquant.runner.send_email", lambda smtp, subject, body: sent.append(subject))

    now_dt = datetime(2026, 4, 22, 2, 15, tzinfo=SYDNEY_TZ)
    state = migrate_state({})
    config = SimpleNamespace(
        force_daily_report=True,
        dry_run=False,
        send_hour=7,
        send_minute=30,
        send_window_minutes=30,
        smtp=object(),
    )

    did_send, changed_state = maybe_send_daily_report(state, now_dt, [], None, config)

    assert did_send
    assert not changed_state
    assert sent == ["subject"]
    assert state["daily"] == {}


def test_force_daily_report_ignores_already_sent_today(monkeypatch):
    monkeypatch.setattr("veyraquant.runner.compose_daily_report", lambda *args: ("subject", "body"))
    monkeypatch.setattr("veyraquant.runner.send_email", lambda *args: None)

    now_dt = datetime(2026, 4, 22, 8, 0, tzinfo=SYDNEY_TZ)
    state = migrate_state({})
    mark_daily_sent(state, now_dt)
    config = SimpleNamespace(
        force_daily_report=True,
        dry_run=False,
        send_hour=7,
        send_minute=30,
        send_window_minutes=30,
        smtp=object(),
    )

    did_send, changed_state = maybe_send_daily_report(state, now_dt, [], None, config)

    assert did_send
    assert not changed_state
    assert state["daily"]["date"] == "2026-04-22"


def test_non_actionable_signal_does_not_trigger_entry_alert(monkeypatch):
    sent = []
    monkeypatch.setattr("veyraquant.runner.is_regular_us_market_hours", lambda _dt: True)
    monkeypatch.setattr("veyraquant.runner.send_email", lambda *args: sent.append(args))

    result = SimpleNamespace(
        symbol="NVDA",
        alert_kind="hold_watch",
        score=90,
        is_actionable=False,
        action="WATCH",
        signal_hash="watch-1",
    )
    config = SimpleNamespace(
        entry_alerts_enabled=True,
        risk_alerts_enabled=False,
        alert_score_threshold=65,
        alert_cooldown_hours=12,
        dry_run=False,
        smtp=object(),
    )

    sent_any = maybe_send_entry_alerts(
        migrate_state({}),
        datetime(2026, 4, 22, 10, 0, tzinfo=SYDNEY_TZ),
        [result],
        config,
    )

    assert not sent_any
    assert sent == []


def test_same_signal_hash_does_not_resend_within_cooldown(monkeypatch):
    sent = []
    monkeypatch.setattr("veyraquant.runner.is_regular_us_market_hours", lambda _dt: True)
    monkeypatch.setattr("veyraquant.runner.compose_alert_email", lambda *args: ("subject", "body"))
    monkeypatch.setattr("veyraquant.runner.send_email", lambda *args: sent.append(args))

    now_dt = datetime(2026, 4, 22, 10, 0, tzinfo=SYDNEY_TZ)
    state = migrate_state({})
    state["alerts"] = {
        "NVDA": {
            "breakout_entry": {
                "sent_at": datetime(2026, 4, 22, 9, 0, tzinfo=SYDNEY_TZ).isoformat(),
                "signal_hash": "same-hash",
            }
        }
    }
    result = SimpleNamespace(
        symbol="NVDA",
        alert_kind="breakout_entry",
        score=90,
        is_actionable=True,
        action="BUY_TRIGGER",
        signal_hash="same-hash",
    )
    config = SimpleNamespace(
        entry_alerts_enabled=True,
        risk_alerts_enabled=False,
        alert_score_threshold=65,
        alert_cooldown_hours=12,
        dry_run=False,
        smtp=object(),
    )

    sent_any = maybe_send_entry_alerts(state, now_dt, [result], config)

    assert not sent_any
    assert sent == []


def test_changed_signal_hash_resends_within_cooldown(monkeypatch):
    sent = []
    monkeypatch.setattr("veyraquant.runner.is_regular_us_market_hours", lambda _dt: True)
    monkeypatch.setattr("veyraquant.runner.compose_alert_email", lambda *args: ("subject", "body"))
    monkeypatch.setattr("veyraquant.runner.send_email", lambda *args: sent.append(args))

    now_dt = datetime(2026, 4, 22, 10, 0, tzinfo=SYDNEY_TZ)
    state = migrate_state({})
    state["alerts"] = {
        "NVDA": {
            "breakout_entry": {
                "sent_at": datetime(2026, 4, 22, 9, 0, tzinfo=SYDNEY_TZ).isoformat(),
                "signal_hash": "old-hash",
            }
        }
    }
    result = SimpleNamespace(
        symbol="NVDA",
        alert_kind="breakout_entry",
        score=90,
        is_actionable=True,
        action="BUY_TRIGGER",
        signal_hash="new-hash",
        entry_zone="$100 - $101",
        stop="$98",
        targets="$104 / $106",
        position_pct=8.0,
        max_loss_pct=0.5,
    )
    config = SimpleNamespace(
        entry_alerts_enabled=True,
        risk_alerts_enabled=False,
        alert_score_threshold=65,
        alert_cooldown_hours=12,
        dry_run=False,
        smtp=object(),
    )

    sent_any = maybe_send_entry_alerts(state, now_dt, [result], config)

    assert sent_any
    assert len(sent) == 1
    assert state["alerts"]["NVDA"]["breakout_entry"]["signal_hash"] == "new-hash"
    assert state["alerts"]["NVDA"]["breakout_entry"]["reason"] == "signal_changed"


def test_legacy_state_without_signal_hash_does_not_crash(monkeypatch):
    sent = []
    monkeypatch.setattr("veyraquant.runner.is_regular_us_market_hours", lambda _dt: True)
    monkeypatch.setattr("veyraquant.runner.compose_alert_email", lambda *args: ("subject", "body"))
    monkeypatch.setattr("veyraquant.runner.send_email", lambda *args: sent.append(args))

    now_dt = datetime(2026, 4, 22, 10, 0, tzinfo=SYDNEY_TZ)
    state = migrate_state({})
    state["alerts"] = {
        "NVDA": {
            "breakout_entry": {
                "sent_at": datetime(2026, 4, 22, 9, 0, tzinfo=SYDNEY_TZ).isoformat(),
            }
        }
    }
    result = SimpleNamespace(
        symbol="NVDA",
        alert_kind="breakout_entry",
        score=90,
        is_actionable=True,
        action="BUY_TRIGGER",
        signal_hash="new-hash",
    )
    config = SimpleNamespace(
        entry_alerts_enabled=True,
        risk_alerts_enabled=False,
        alert_score_threshold=65,
        alert_cooldown_hours=12,
        dry_run=False,
        smtp=object(),
    )

    sent_any = maybe_send_entry_alerts(state, now_dt, [result], config)

    assert not sent_any
    assert sent == []


def test_risk_reduce_does_not_send_when_risk_alerts_disabled(monkeypatch):
    sent = []
    monkeypatch.setattr("veyraquant.runner.is_regular_us_market_hours", lambda _dt: True)
    monkeypatch.setattr("veyraquant.runner.send_email", lambda *args: sent.append(args))

    result = SimpleNamespace(
        rank=3,
        symbol="TSLA",
        alert_kind="risk_reduce",
        signal_type="减仓/风险升高",
        score=38,
        market_regime="风险偏好",
        reasons=["趋势转弱"],
        risks=["跌破 SMA20"],
        is_actionable=False,
        action="RISK_REDUCE",
        signal_hash="risk-1",
    )
    config = SimpleNamespace(
        entry_alerts_enabled=True,
        risk_alerts_enabled=False,
        alert_score_threshold=65,
        alert_cooldown_hours=12,
        dry_run=False,
        smtp=object(),
    )

    sent_any = maybe_send_entry_alerts(
        migrate_state({}),
        datetime(2026, 4, 22, 10, 0, tzinfo=SYDNEY_TZ),
        [result],
        config,
    )

    assert not sent_any
    assert sent == []


def test_risk_reduce_sends_when_risk_alerts_enabled(monkeypatch):
    sent = []
    monkeypatch.setattr("veyraquant.runner.is_regular_us_market_hours", lambda _dt: True)
    monkeypatch.setattr("veyraquant.runner.send_email", lambda smtp, subject, body: sent.append((subject, body)))

    result = SimpleNamespace(
        rank=3,
        symbol="TSLA",
        alert_kind="risk_reduce",
        signal_type="减仓/风险升高",
        score=38,
        market_regime="风险偏好",
        reasons=["趋势转弱"],
        risks=["跌破 SMA20"],
        is_actionable=False,
        action="RISK_REDUCE",
        signal_hash="risk-1",
        entry_zone="不适用",
        stop="NA",
        targets="NA",
        position_pct=0.0,
        max_loss_pct=0.0,
    )
    config = SimpleNamespace(
        entry_alerts_enabled=True,
        risk_alerts_enabled=True,
        alert_score_threshold=65,
        alert_cooldown_hours=12,
        dry_run=False,
        smtp=object(),
    )

    sent_any = maybe_send_entry_alerts(
        migrate_state({}),
        datetime(2026, 4, 22, 10, 0, tzinfo=SYDNEY_TZ),
        [result],
        config,
    )

    assert sent_any
    assert len(sent) == 1
    subject, body = sent[0]
    assert "风险提醒" in subject
    assert "No buy/add trade plan is attached to this risk alert." in body
    assert "entry_zone:" not in body


def test_watch_wait_reject_still_do_not_send_entry_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr("veyraquant.runner.is_regular_us_market_hours", lambda _dt: True)
    monkeypatch.setattr("veyraquant.runner.send_email", lambda *args: sent.append(args))

    results = [
        SimpleNamespace(symbol="AAPL", alert_kind="wait", score=80, is_actionable=False, action="WATCH", signal_hash="w1"),
        SimpleNamespace(symbol="MU", alert_kind="wait", score=72, is_actionable=False, action="WAIT", signal_hash="w2"),
        SimpleNamespace(symbol="SMH", alert_kind="wait", score=74, is_actionable=False, action="REJECT", signal_hash="w3"),
    ]
    config = SimpleNamespace(
        entry_alerts_enabled=True,
        risk_alerts_enabled=False,
        alert_score_threshold=65,
        alert_cooldown_hours=12,
        dry_run=False,
        smtp=object(),
    )

    sent_any = maybe_send_entry_alerts(
        migrate_state({}),
        datetime(2026, 4, 22, 10, 0, tzinfo=SYDNEY_TZ),
        results,
        config,
    )

    assert not sent_any
    assert sent == []
