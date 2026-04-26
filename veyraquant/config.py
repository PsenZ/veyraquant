import os
from dataclasses import dataclass
from typing import Optional


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _symbols_from_env() -> list[str]:
    raw = os.getenv("SYMBOLS") or os.getenv("SYMBOL") or "NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH"
    symbols = [part.strip().upper() for part in raw.split(",") if part.strip()]
    return symbols or ["NVDA"]


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: Optional[str]
    password: Optional[str]
    from_email: Optional[str]
    to_email: Optional[str]


@dataclass(frozen=True)
class AppConfig:
    symbols: list[str]
    market_symbols: list[str]
    send_hour: int
    send_minute: int
    send_window_minutes: int
    state_path: str
    cache_dir: str
    subject_prefix: str
    entry_alerts_enabled: bool
    alert_cooldown_hours: int
    alert_score_threshold: int
    social_sentiment_threshold: float
    intraday_interval: str
    account_equity: Optional[float]
    risk_per_trade_pct: float
    max_position_pct: float
    portfolio_heat_max_pct: float
    atr_stop_multiplier: float
    min_rr: float
    force_daily_report: bool
    dry_run: bool
    smtp: SmtpConfig
    risk_alerts_enabled: bool = False
    max_entry_zone_width_warn_pct: float = 3.0
    max_entry_zone_width_reject_pct: float = 6.0

    @classmethod
    def from_env(cls) -> "AppConfig":
        symbols = _symbols_from_env()
        market_symbols = [
            part.strip().upper()
            for part in os.getenv("MARKET_SYMBOLS", "SPY,QQQ,SMH,^VIX").split(",")
            if part.strip()
        ]
        account_equity_raw = os.getenv("ACCOUNT_EQUITY")
        account_equity = float(account_equity_raw) if account_equity_raw else None
        subject_default = (
            f"{symbols[0]} 每日简报" if len(symbols) == 1 else "VeyraQuant 量化简报"
        )

        return cls(
            symbols=symbols,
            market_symbols=market_symbols,
            send_hour=_int_env("SEND_HOUR", 7),
            send_minute=_int_env("SEND_MINUTE", 30),
            send_window_minutes=_int_env("SEND_WINDOW_MINUTES", 30),
            state_path=os.getenv("STATE_PATH", os.path.join("state", "last_sent.json")),
            cache_dir=os.getenv("CACHE_DIR", os.path.join(".cache", "veyraquant")),
            subject_prefix=os.getenv("SUBJECT_PREFIX", subject_default),
            entry_alerts_enabled=_bool_env("ENABLE_ENTRY_ALERTS", True),
            risk_alerts_enabled=_bool_env("ENABLE_RISK_ALERTS", False),
            alert_cooldown_hours=_int_env("ALERT_COOLDOWN_HOURS", 12),
            alert_score_threshold=_int_env("ALERT_SCORE_THRESHOLD", 65),
            social_sentiment_threshold=_float_env("SOCIAL_SENTIMENT_THRESHOLD", 0.15),
            intraday_interval=os.getenv("INTRADAY_INTERVAL", "30m"),
            account_equity=account_equity,
            risk_per_trade_pct=_float_env("RISK_PER_TRADE_PCT", 0.5),
            max_position_pct=_float_env("MAX_POSITION_PCT", 10.0),
            portfolio_heat_max_pct=_float_env("PORTFOLIO_HEAT_MAX_PCT", 3.0),
            atr_stop_multiplier=_float_env("ATR_STOP_MULTIPLIER", 2.0),
            min_rr=_float_env("MIN_RR", 1.5),
            force_daily_report=_bool_env("FORCE_DAILY_REPORT", False),
            dry_run=_bool_env("DRY_RUN", False),
            smtp=SmtpConfig(
                host=os.getenv("SMTP_HOST", "smtp.mail.yahoo.com"),
                port=_int_env("SMTP_PORT", 465),
                user=os.getenv("SMTP_USER"),
                password=os.getenv("SMTP_APP_PASSWORD"),
                from_email=os.getenv("FROM_EMAIL"),
                to_email=os.getenv("TO_EMAIL"),
            ),
            max_entry_zone_width_warn_pct=_float_env("MAX_ENTRY_ZONE_WIDTH_WARN_PCT", 3.0),
            max_entry_zone_width_reject_pct=_float_env("MAX_ENTRY_ZONE_WIDTH_REJECT_PCT", 6.0),
        )
