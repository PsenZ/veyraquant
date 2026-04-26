from datetime import datetime

from .config import AppConfig
from .models import MarketContext, SignalResult
from .timeutils import US_EASTERN_TZ


ACTIONABLE_ACTIONS = {"BUY_TRIGGER", "ADD_TRIGGER"}
WATCH_ACTIONS = {"HOLD", "WATCH", "WAIT"}
RISK_ACTIONS = {"AVOID_CHASE", "RISK_REDUCE"}
VALIDATION_WARNING_MARKERS = ("warning threshold",)
PORTFOLIO_HEAT_WARNING_MARKERS = ("portfolio heat",)
AVOID_CHASE_MARKERS = ("追高", "chase")


def format_money(value) -> str:
    if value is None:
        return "NA"
    try:
        value = float(value)
    except Exception:
        return "NA"
    if abs(value) >= 1e12:
        return f"{value / 1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.2f}M"
    return f"{value:.2f}"


def format_dual_time(now_dt: datetime) -> str:
    eastern_dt = now_dt.astimezone(US_EASTERN_TZ)
    return (
        f"Sydney {now_dt.strftime('%Y-%m-%d %H:%M')} / "
        f"US Eastern {eastern_dt.strftime('%Y-%m-%d %H:%M')}"
    )


def compose_daily_report(
    results: list[SignalResult],
    market: MarketContext,
    config: AppConfig,
    now_dt: datetime,
) -> tuple[str, str]:
    subject = f"{config.subject_prefix} - {now_dt.strftime('%Y-%m-%d')}"
    dual_time = format_dual_time(now_dt)

    actionable = [item for item in results if _action(item) in ACTIONABLE_ACTIONS and _is_actionable(item)]
    actionable = actionable[:3]
    hold_watch = [item for item in results if _action(item) in WATCH_ACTIONS]
    avoid_or_reduce = [
        item for item in results if _action(item) == "RISK_REDUCE" or _is_avoid_chase(item)
    ]
    rejected = [item for item in results if _action(item) == "REJECT"]

    executable_count = len(actionable)
    hold_watch_count = len(hold_watch)
    avoid_chase_count = len(avoid_or_reduce)
    rejected_count = len(rejected)

    lines: list[str] = [
        f"VeyraQuant Trading Decision Brief",
        f"Time: {dual_time}",
        "",
        "[Today Conclusion]",
        f"market_regime: {market.label}",
        f"trading_posture: {_trading_posture(market, executable_count)}",
        (
            f"counts: executable {executable_count} | hold/watch {hold_watch_count} | "
            f"avoid/reduce {avoid_chase_count} | rejected {rejected_count}"
        ),
        _summary_paragraph(
            market, executable_count, hold_watch_count, avoid_chase_count, rejected_count
        ),
        "",
        "[Market Filter]",
        f"market_score: {market.score:+.1f}",
        *[f"- {reason}" for reason in market.reasons[:4]],
    ]

    if market.risks:
        lines.extend([*[f"- risk: {risk}" for risk in market.risks[:4]]])
    lines.extend(_market_snapshot_lines(market))

    lines.extend(["", "[Action List]"])
    if not actionable:
        lines.append("No executable BUY_TRIGGER or ADD_TRIGGER setups today.")
    for result in actionable:
        lines.extend(_action_block(result))

    lines.extend(["", "[Hold / Watch]"])
    if not hold_watch:
        lines.append("No HOLD / WATCH / WAIT items.")
    for result in hold_watch:
        lines.extend(_hold_watch_block(result))

    lines.extend(["", "[Avoid Chase / Risk Reduce]"])
    if not avoid_or_reduce:
        lines.append("No avoid-chase or risk-reduce items.")
    for result in avoid_or_reduce:
        lines.extend(_risk_reduce_block(result))

    lines.extend(["", "[Rejected Plans]"])
    if not rejected:
        lines.append("No rejected actionable plans.")
    for result in rejected:
        lines.extend(_rejected_block(result))

    lines.extend(["", "[System Notes]"])
    system_notes = _system_notes(results)
    if system_notes:
        lines.extend(system_notes)
    else:
        lines.append("- No additional system notes.")
    lines.extend(
        [
            "- No broker API. No automatic orders. Every trade plan requires human review.",
            "- Position sizing follows existing config risk controls and may be reduced by portfolio heat.",
        ]
    )
    return subject, "\n".join(lines)


def compose_alert_email(result: SignalResult, now_dt: datetime) -> tuple[str, str]:
    subject = f"{result.symbol} {result.signal_type} - score {result.score}"
    dual_time = format_dual_time(now_dt)
    lines = [
        f"{result.symbol} 机会/风险提醒 ({dual_time})",
        "",
        f"rank: {result.rank}",
        f"symbol: {result.symbol}",
        f"signal_type: {result.signal_type}",
        f"score: {result.score}",
        f"market_regime: {result.market_regime}",
        f"entry_zone: {result.entry_zone}",
        f"stop: {result.stop}",
        f"targets: {result.targets}",
        f"position_pct: {result.position_pct:.2f}%",
        f"max_loss_pct: {result.max_loss_pct:.2f}%",
        f"trigger: {result.trade_plan.trigger}",
        f"cancel: {result.trade_plan.cancel}",
    ]
    if result.trade_plan.position_value is not None:
        lines.append(f"position_value: ${result.trade_plan.position_value:,.2f}")

    lines.extend(["", "[score breakdown]"])
    lines.extend(f"- {key}: {value:+.1f}" for key, value in result.contributions.items())
    lines.extend(["", "[reasons]", *[f"- {line}" for line in result.reasons]])
    lines.extend(["", "[risks]", *[f"- {line}" for line in result.risks or ["No major risk note."]]])
    return subject, "\n".join(lines)


def _action(result: SignalResult) -> str:
    if getattr(result, "action", ""):
        return result.action
    mapping = {
        "突破入场": "BUY_TRIGGER",
        "趋势回踩加仓": "ADD_TRIGGER",
        "持有观察": "WATCH",
        "减仓/风险升高": "RISK_REDUCE",
        "禁止交易/等待": "WAIT",
    }
    return mapping.get(result.signal_type, "WAIT")


def _setup_type(result: SignalResult) -> str:
    if getattr(result, "setup_type", ""):
        return result.setup_type
    return result.alert_kind or "unknown"


def _is_actionable(result: SignalResult) -> bool:
    return bool(getattr(result, "is_actionable", False))


def _is_avoid_chase(result: SignalResult) -> bool:
    return _contains_any_marker(result.risks, AVOID_CHASE_MARKERS)


def _validation_warnings(result: SignalResult) -> list[str]:
    return _filter_by_markers(result.risks, VALIDATION_WARNING_MARKERS)


def _portfolio_heat_warnings(result: SignalResult) -> list[str]:
    return _filter_by_markers(result.risks, PORTFOLIO_HEAT_WARNING_MARKERS)


def _trading_posture(market: MarketContext, executable_count: int) -> str:
    if market.label == "风险规避":
        return "Defense first"
    if executable_count > 0:
        return "Selective execution"
    if market.label == "风险偏好":
        return "Wait for cleaner entries"
    return "Neutral and patient"


def _summary_paragraph(
    market: MarketContext,
    executable_count: int,
    hold_watch_count: int,
    avoid_chase_count: int,
    rejected_count: int,
) -> str:
    if executable_count:
        lead = f"{executable_count} executable setup(s) survived filters."
    else:
        lead = "No executable setup cleared the final filter."
    return (
        f"{lead} {hold_watch_count} name(s) stay on watch, "
        f"{avoid_chase_count} sit in risk-control, and {rejected_count} were rejected."
    )


def _market_snapshot_lines(market: MarketContext) -> list[str]:
    lines: list[str] = []
    for symbol in ["SPY", "QQQ", "SMH", "^VIX"]:
        snapshot = market.snapshots.get(symbol)
        if not snapshot:
            continue
        if snapshot.get("status") == "missing":
            lines.append(f"- {symbol}: data missing")
            continue
        if symbol == "^VIX":
            last = snapshot.get("last")
            if last is not None:
                lines.append(f"- ^VIX: last {float(last):.2f}")
            continue
        pieces = []
        for key in ["last", "sma20", "sma50", "perf20"]:
            value = snapshot.get(key)
            if value is None:
                continue
            if key == "perf20":
                pieces.append(f"{key} {float(value):+.2f}%")
            else:
                pieces.append(f"{key} {float(value):.2f}")
        if pieces:
            lines.append(f"- {symbol}: " + ", ".join(pieces))
    return lines


def _action_block(result: SignalResult) -> list[str]:
    validation_warnings = _validation_warnings(result)
    risk_summary = _compact_summary(result.risks, limit=2, exclude=validation_warnings)
    lines = [
        "",
        f"## {result.symbol}",
        f"action: {_action(result)} | score: {result.score} | setup: {_setup_type(result)}",
        f"plan: {result.entry_zone} | stop {result.stop} | targets {result.targets}",
        f"risk: position {result.position_pct:.2f}% | max_loss {result.max_loss_pct:.2f}%",
        f"trigger: {result.trade_plan.trigger}",
        f"cancel: {result.trade_plan.cancel}",
        f"reasons: {_compact_summary(result.reasons, limit=3)}",
        f"risks: {risk_summary}",
    ]
    if validation_warnings:
        lines.append(f"validation_warnings: {_compact_summary(validation_warnings, limit=2)}")
    return lines


def _hold_watch_block(result: SignalResult) -> list[str]:
    return [
        "",
        f"symbol: {result.symbol} | score: {result.score} | action: {_action(result)} | next: {result.trade_plan.trigger}",
        f"summary: {_reason_summary(result)}",
    ]


def _risk_reduce_block(result: SignalResult) -> list[str]:
    action = "AVOID_CHASE" if _is_avoid_chase(result) and _action(result) != "RISK_REDUCE" else _action(result)
    lines = [
        "",
        f"symbol: {result.symbol} | score: {result.score} | action: {action}",
        f"summary: {_reason_summary(result)}",
    ]
    risk_lines = result.risks[:2] or ["No additional risk note."]
    lines.append(f"risks: {_compact_summary(risk_lines, limit=2)}")
    return lines


def _rejected_block(result: SignalResult) -> list[str]:
    reasons = getattr(result, "rejection_reasons", []) or ["No explicit rejection reason."]
    suppressed_by = getattr(result, "suppressed_by", []) or ["No suppression metadata."]
    return [
        "",
        f"symbol: {result.symbol} | score: {result.score}",
        f"rejection: {_compact_summary(reasons, limit=2)}",
        f"suppressed_by: {_compact_summary(suppressed_by, limit=2)}",
    ]


def _reason_summary(result: SignalResult) -> str:
    items = result.reasons[:2] or result.risks[:2]
    if not items:
        return "No summary available."
    return " ; ".join(items)


def _system_notes(results: list[SignalResult]) -> list[str]:
    lines: list[str] = []
    data_warnings = [warning for result in results for warning in result.warnings]
    validation_warnings = [item for result in results for item in _validation_warnings(result)]
    heat_warnings = [item for result in results for item in _portfolio_heat_warnings(result)]

    if data_warnings:
        lines.extend(["- data warnings:"] + [f"  - {item}" for item in data_warnings[:8]])
    if validation_warnings:
        lines.extend(["- validation warnings:"] + [f"  - {item}" for item in validation_warnings[:8]])
    if heat_warnings:
        lines.extend(["- portfolio heat warnings:"] + [f"  - {item}" for item in heat_warnings[:8]])
    return lines


def _filter_by_markers(items: list[str], markers: tuple[str, ...]) -> list[str]:
    return [item for item in items if _contains_any_marker([item], markers)]


def _contains_any_marker(items: list[str], markers: tuple[str, ...]) -> bool:
    lowered_markers = tuple(marker.lower() for marker in markers)
    for item in items:
        text = item.lower()
        if any(marker in text for marker in lowered_markers):
            return True
    return False


def _compact_summary(items: list[str], limit: int = 2, exclude: list[str] | None = None) -> str:
    exclude = exclude or []
    filtered = [item for item in items if item not in exclude]
    if not filtered:
        return "None."
    return " ; ".join(filtered[:limit])
