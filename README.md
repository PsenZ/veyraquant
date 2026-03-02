# NVDA Daily Brief

Automated NVDA email system with two outputs:

1. A daily morning brief at 07:30 Sydney time.
2. Opportunistic entry or add-position alerts when the signal score reaches the configured threshold.

## Setup

1. Create a Yahoo App Password for your account.
2. Add GitHub Actions repository secrets:
   - `SMTP_USER` = your Yahoo email
   - `SMTP_APP_PASSWORD` = Yahoo App Password
   - `FROM_EMAIL` = sender email
   - `TO_EMAIL` = recipient email

## What The Report Includes

- Technical snapshot: moving averages, RSI, MACD, ADX, DI, ATR, Bollinger reference, volume ratio.
- Technical reasoning: why the model classifies the current setup as strong, neutral, or weak.
- Fundamentals: valuation, profitability, growth, analyst consensus.
- News catalysts: company and market headlines.
- Social sentiment: headline-based sentiment proxy from public RSS results related to Reddit, Stocktwits, and X.
- Options: put/call volume, open interest, implied volatility.
- Trading assist: signal score for entry or add-position opportunities.

## Alert Logic

- The workflow still runs every 20 minutes.
- Morning report only sends inside the configured Sydney-time window.
- Opportunity alerts can send outside the morning window.
- Each alert type uses cooldown control to avoid repeated emails from the same signal.

## Configurable Environment Variables

- `SYMBOL`: ticker symbol, default `NVDA`
- `SEND_HOUR`, `SEND_MINUTE`, `SEND_WINDOW_MINUTES`
- `ENABLE_ENTRY_ALERTS`: `true` or `false`
- `ALERT_COOLDOWN_HOURS`: default `12`
- `ALERT_SCORE_THRESHOLD`: default `65`
- `SOCIAL_SENTIMENT_THRESHOLD`: default `0.15`
- `INTRADAY_INTERVAL`: default `30m`
- `SUBJECT_PREFIX`

## Notes

- Data sources: Yahoo Finance, NVIDIA RSS, Google News RSS.
- Social sentiment is an auxiliary proxy, not a direct order-flow signal.
- This brief is for information only and not investment advice.

## Manual Run

Use GitHub Actions `workflow_dispatch` to run on demand.
