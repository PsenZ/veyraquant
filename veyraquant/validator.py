from dataclasses import dataclass, field

from .config import AppConfig
from .models import TradePlan


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_trade_plan(plan: TradePlan, config: AppConfig) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    entry_low, entry_high = _parse_entry_zone(plan.entry_zone)
    stop = _parse_money(plan.stop)
    target1 = _parse_first_target(plan.targets)
    rr = _parse_float(plan.rr)
    position_pct = _parse_float(plan.position_pct)
    max_loss_pct = _parse_float(plan.max_loss_pct)

    if entry_low is None or entry_high is None:
        errors.append("缺少有效的 entry zone")
    if stop is None:
        errors.append("缺少有效的 stop")
    if target1 is None:
        errors.append("缺少有效的 target1")
    if rr is None:
        errors.append("缺少有效的 RR")
    if position_pct is None:
        errors.append("缺少有效的 position_pct")
    if max_loss_pct is None:
        errors.append("缺少有效的 max_loss_pct")

    if errors:
        return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

    if entry_low <= stop:
        errors.append("entry_low 不能小于或等于 stop")
    if entry_high <= entry_low:
        errors.append("entry_high 必须大于 entry_low")

    width_pct = (entry_high - entry_low) / entry_low * 100 if entry_low > 0 else None
    if width_pct is None:
        errors.append("无法计算 entry zone width")
    elif width_pct > config.max_entry_zone_width_reject_pct:
        errors.append(
            f"entry zone width {width_pct:.2f}% exceeds rejection threshold "
            f"{config.max_entry_zone_width_reject_pct:.2f}%"
        )
    elif width_pct > config.max_entry_zone_width_warn_pct:
        warnings.append(
            f"entry zone width {width_pct:.2f}% exceeds warning threshold "
            f"{config.max_entry_zone_width_warn_pct:.2f}%"
        )

    if target1 <= entry_high:
        errors.append("target1 必须大于 entry_high")
    if rr < config.min_rr:
        errors.append(f"RR {rr:.2f} 低于配置下限 {config.min_rr:.2f}")
    if position_pct > config.max_position_pct:
        errors.append(
            f"position_pct {position_pct:.2f}% 超过配置上限 {config.max_position_pct:.2f}%"
        )
    if max_loss_pct > config.risk_per_trade_pct:
        errors.append(
            f"max_loss_pct {max_loss_pct:.2f}% 超过单笔风险预算 {config.risk_per_trade_pct:.2f}%"
        )

    return ValidationResult(is_valid=not errors, errors=errors, warnings=warnings)


def _parse_entry_zone(value: str) -> tuple[float | None, float | None]:
    if not value or " - " not in value:
        return None, None
    left, right = value.split(" - ", 1)
    return _parse_money(left), _parse_money(right)


def _parse_first_target(value: str) -> float | None:
    if not value or "/" not in value:
        return _parse_money(value)
    left, _right = value.split("/", 1)
    return _parse_money(left)


def _parse_money(value) -> float | None:
    if value in {None, "", "NA"}:
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def _parse_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None
