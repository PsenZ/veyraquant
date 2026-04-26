import json
import os
from datetime import datetime, timedelta
from typing import Any


STATE_VERSION = 2


def read_state(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raw = {}
    except Exception:
        raw = {}
    return migrate_state(raw)


def migrate_state(raw: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {"version": STATE_VERSION, "daily": {}, "alerts": {}}

    if not isinstance(raw, dict):
        return state

    if raw.get("version") == STATE_VERSION:
        state["daily"] = raw.get("daily", {}) if isinstance(raw.get("daily"), dict) else {}
        state["alerts"] = raw.get("alerts", {}) if isinstance(raw.get("alerts"), dict) else {}
        return state

    if isinstance(raw.get("daily"), dict):
        state["daily"] = raw["daily"]
    elif raw.get("date"):
        state["daily"] = {"date": raw.get("date"), "sent_at": raw.get("sent_at")}

    old_alerts = raw.get("alerts", {})
    if isinstance(old_alerts, dict):
        for key, value in old_alerts.items():
            if not isinstance(value, dict):
                continue
            symbol = value.get("symbol", "NVDA")
            state["alerts"].setdefault(symbol, {})[key] = value

    return state


def write_state(path: str, state: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def already_sent_daily(state: dict[str, Any], now_dt: datetime) -> bool:
    return state.get("daily", {}).get("date") == now_dt.strftime("%Y-%m-%d")


def mark_daily_sent(state: dict[str, Any], now_dt: datetime) -> None:
    state["version"] = STATE_VERSION
    state["daily"] = {
        "date": now_dt.strftime("%Y-%m-%d"),
        "sent_at": now_dt.isoformat(),
    }


def alert_in_cooldown(
    state: dict[str, Any], symbol: str, alert_kind: str, now_dt: datetime, cooldown_hours: int
) -> bool:
    alert_state = state.get("alerts", {}).get(symbol, {}).get(alert_kind)
    if not alert_state:
        return False
    try:
        sent_at = datetime.fromisoformat(alert_state["sent_at"])
    except Exception:
        return False
    return now_dt - sent_at < timedelta(hours=cooldown_hours)


def should_send_alert(
    state: dict[str, Any],
    symbol: str,
    alert_kind: str,
    now_dt: datetime,
    cooldown_hours: int,
    signal_hash: str | None = None,
) -> tuple[bool, str]:
    alert_state = state.get("alerts", {}).get(symbol, {}).get(alert_kind)
    if not alert_state:
        return True, "new_alert"

    previous_hash = alert_state.get("signal_hash")
    if signal_hash and previous_hash and signal_hash != previous_hash:
        return True, "signal_changed"

    try:
        sent_at = datetime.fromisoformat(alert_state["sent_at"])
    except Exception:
        return True, "invalid_history"

    if now_dt - sent_at >= timedelta(hours=cooldown_hours):
        return True, "cooldown_elapsed"
    return False, "cooldown_active"


def mark_alert_sent(
    state: dict[str, Any],
    symbol: str,
    alert_kind: str,
    now_dt: datetime,
    meta: dict[str, Any],
) -> None:
    state["version"] = STATE_VERSION
    state.setdefault("alerts", {}).setdefault(symbol, {})[alert_kind] = {
        "sent_at": now_dt.isoformat(),
        **meta,
    }
