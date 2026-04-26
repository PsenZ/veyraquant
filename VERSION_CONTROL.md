# Version Control

## Current Version

- Version: `2.4.0`
- Date: `2026-04-26`
- Status: Added trade-plan validation and upgraded daily briefs into a trading decision format

## Versioning Rules

- `MAJOR`: signal model, state schema, report contract, or risk model changes that may affect trading decisions.
- `MINOR`: new data source, indicator, report section, backtest metric, or configuration option.
- `PATCH`: bug fix, test improvement, copy update, or operational hardening with no decision-model change.

## Changelog

### 2.4.0

- Fixed signal/result consistency so the final action is decided before a buy-side trade plan is attached.
- Ensured non-actionable results no longer retain executable entry zones, targets, position sizing, or portfolio-heat consumption.
- Added actionable trade-plan validation with explicit rejection reasons for invalid entry, stop, target, RR, sizing, and max-loss combinations.
- Added configurable entry-zone width warning and rejection thresholds with `MAX_ENTRY_ZONE_WIDTH_WARN_PCT` and `MAX_ENTRY_ZONE_WIDTH_REJECT_PCT`.
- Rebuilt the daily brief into a trading decision format with `Today Conclusion`, `Market Filter`, `Action List`, `Hold / Watch`, `Avoid Chase / Risk Reduce`, `Rejected Plans`, and `System Notes`.
- Centralized reporting helper logic so warning extraction and avoid-chase text heuristics are no longer scattered across the report body.

### 2.3.1

- Added `FORCE_DAILY_REPORT` support so manual workflow runs can send a daily brief immediately without waiting for the normal send window.
- Added a `force_send` input to the GitHub Actions `workflow_dispatch` trigger.
- Kept forced manual briefs from overwriting the official daily-send state, so scheduled daily delivery still works later the same day.

### 2.3.0

- Upgraded the scoring engine with stricter trend-following rules inspired by bull-trend, shrink-pullback, and volume-breakout evaluation ideas.
- Added MA5/MA10/MA20 alignment, anti-chase deviation checks, shrink-volume pullback preference, heavy-volume breakout confirmation, sector resonance, and stronger negative-news veto logic.
- Updated the active US watchlist to `NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH`.
- Kept daily brief delivery more reliable by widening the schedule window and allowing same-day catch-up sending.
- Added dual timezone display for Sydney and US Eastern in reports and alerts.

### 2.2.0

- Renamed the project from `ShortReport` to `VeyraQuant`.
- Renamed the Python package from `shortreport` to `veyraquant`.
- Updated public-facing docs, frontend branding, workflow compile paths, and tests.

### 2.1.0

- Added a static public-facing frontend page under `frontend/`.
- Added English-first bilingual language switching for English and Chinese.
- Added a blue-black cyber finance visual style with full-bleed market imagery.
- Added an interactive sample trade plan for `NVDA`, `MSFT`, and `SMH`.
- Updated README with frontend usage and deployment notes.

### 2.0.0

- Refactored the single-file script into modules for config, data, indicators, market regime, signals, risk, reporting, email, state, runner, and backtesting.
- Added `SYMBOLS` stock-pool support while keeping `python report.py` as the compatible entrypoint.
- Added market filters using `SPY`, `QQQ`, `SMH`, and `^VIX`.
- Added component scoring and signal types: breakout entry, pullback add, hold watch, risk reduce, and wait.
- Added trade plans with entry zone, stop, targets, R multiple, position percentage, max-loss percentage, trigger, and cancel conditions.
- Added state schema version `2` with per-symbol alert records and legacy state migration.
- Added cache-aware data fetching and graceful degradation for missing Yahoo/RSS/options data.
- Added unit, reporting, state, data, and backtest test coverage.
