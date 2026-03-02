import json
import os
import re
import sys
from datetime import datetime, timedelta

import feedparser
import numpy as np
import pandas as pd
import pytz
import requests
import smtplib
import yfinance as yf
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SYDNEY_TZ = pytz.timezone("Australia/Sydney")
US_EASTERN_TZ = pytz.timezone("America/New_York")
SYMBOL = os.getenv("SYMBOL", "NVDA").upper()

SEND_HOUR = int(os.getenv("SEND_HOUR", "7"))
SEND_MINUTE = int(os.getenv("SEND_MINUTE", "30"))
SEND_WINDOW_MINUTES = int(os.getenv("SEND_WINDOW_MINUTES", "10"))
STATE_PATH = os.getenv("STATE_PATH", os.path.join("state", "last_sent.json"))

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.mail.yahoo.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_APP_PASSWORD")
EMAIL_FROM = os.getenv("FROM_EMAIL")
EMAIL_TO = os.getenv("TO_EMAIL")

SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", f"{SYMBOL} 每日简报")
ENTRY_ALERTS_ENABLED = os.getenv("ENABLE_ENTRY_ALERTS", "true").lower() == "true"
ALERT_COOLDOWN_HOURS = int(os.getenv("ALERT_COOLDOWN_HOURS", "12"))
ALERT_SCORE_THRESHOLD = int(os.getenv("ALERT_SCORE_THRESHOLD", "65"))
SOCIAL_SENTIMENT_THRESHOLD = float(os.getenv("SOCIAL_SENTIMENT_THRESHOLD", "0.15"))
INTRADAY_INTERVAL = os.getenv("INTRADAY_INTERVAL", "30m")

POSITIVE_WORDS = {
    "beat", "beats", "bullish", "buy", "breakout", "growth", "surge", "strong",
    "upgrade", "outperform", "record", "momentum", "ai", "lead", "领先", "增长",
    "利好", "强劲", "看多", "突破", "超预期", "增持", "上调", "大涨",
}
NEGATIVE_WORDS = {
    "miss", "misses", "bearish", "sell", "downgrade", "lawsuit", "weak", "drop",
    "risk", "cut", "delay", "ban", "concern", "warning", "bubble", "overvalued",
    "利空", "下调", "回落", "跳水", "风险", "减持", "承压", "疲弱", "过热",
}


def now_sydney():
    return datetime.now(tz=SYDNEY_TZ)


def now_us_eastern():
    return datetime.now(tz=US_EASTERN_TZ)


def within_send_window(now_dt):
    target = now_dt.replace(hour=SEND_HOUR, minute=SEND_MINUTE, second=0, microsecond=0)
    return abs((now_dt - target).total_seconds()) <= SEND_WINDOW_MINUTES * 60


def read_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    except Exception:
        state = {}

    if "alerts" not in state:
        state["alerts"] = {}
    return state


def write_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def already_sent_daily(state, now_dt):
    return state.get("daily", {}).get("date") == now_dt.strftime("%Y-%m-%d")


def mark_daily_sent(state, now_dt):
    state["daily"] = {
        "date": now_dt.strftime("%Y-%m-%d"),
        "sent_at": now_dt.isoformat(),
    }


def alert_in_cooldown(state, alert_key, now_dt):
    alert_state = state.get("alerts", {}).get(alert_key)
    if not alert_state:
        return False
    try:
        sent_at = datetime.fromisoformat(alert_state["sent_at"])
    except Exception:
        return False
    return now_dt - sent_at < timedelta(hours=ALERT_COOLDOWN_HOURS)


def mark_alert_sent(state, alert_key, now_dt, meta):
    state.setdefault("alerts", {})[alert_key] = {
        "sent_at": now_dt.isoformat(),
        "meta": meta,
    }


def fetch_price_history():
    ticker = yf.Ticker(SYMBOL)
    daily = ticker.history(period="1y", interval="1d", auto_adjust=True)
    intraday = ticker.history(period="10d", interval=INTRADAY_INTERVAL, auto_adjust=True)
    if daily is None or daily.empty:
        raise RuntimeError("No daily price history")
    return ticker, daily.dropna(how="all"), intraday.dropna(how="all")


def rsi(series, period=14):
    delta = series.diff()
    gain = pd.Series(np.where(delta > 0, delta, 0.0), index=series.index)
    loss = pd.Series(np.where(delta < 0, -delta, 0.0), index=series.index)
    gain_ema = gain.ewm(alpha=1 / period, adjust=False).mean()
    loss_ema = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = gain_ema / (loss_ema + 1e-9)
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger_bands(series, window=20, num_std=2):
    sma = series.rolling(window).mean()
    std = series.rolling(window).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    return sma, upper, lower


def atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(high, low, close, period=14):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
    )
    tr = pd.concat(
        [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr_series = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr_series + 1e-9)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr_series + 1e-9)
    dx = ((plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-9)) * 100
    adx_series = dx.ewm(alpha=1 / period, adjust=False).mean()
    return plus_di, minus_di, adx_series


def volume_ratio(volume, lookback=20):
    baseline = volume.rolling(lookback).mean()
    return volume / (baseline + 1e-9)


def safe_float(value):
    if value is None:
        return np.nan
    try:
        return float(value)
    except Exception:
        return np.nan


def tech_summary(hist):
    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    last = close.iloc[-1]
    prev = close.iloc[-2]
    chg = last - prev
    chg_pct = chg / prev * 100

    sma20_series = close.rolling(20).mean()
    sma50_series = close.rolling(50).mean()
    sma200_series = close.rolling(200).mean()
    sma20 = sma20_series.iloc[-1]
    sma50 = sma50_series.iloc[-1]
    sma200 = sma200_series.iloc[-1] if len(close) >= 200 else np.nan

    rsi_series = rsi(close)
    macd_line, signal_line, hist_line = macd(close)
    bb_sma, bb_upper, bb_lower = bollinger_bands(close)
    atr14_series = atr(high, low, close)
    plus_di, minus_di, adx_series = adx(high, low, close)
    vol_ratio_series = volume_ratio(volume)

    return {
        "last": last,
        "prev": prev,
        "chg": chg,
        "chg_pct": chg_pct,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "sma20_prev": sma20_series.iloc[-2],
        "sma50_prev": sma50_series.iloc[-2],
        "rsi14": rsi_series.iloc[-1],
        "rsi14_prev": rsi_series.iloc[-2],
        "macd": macd_line.iloc[-1],
        "signal": signal_line.iloc[-1],
        "macd_hist": hist_line.iloc[-1],
        "macd_hist_prev": hist_line.iloc[-2],
        "high_20": close.rolling(20).max().iloc[-1],
        "low_20": close.rolling(20).min().iloc[-1],
        "high_55": close.rolling(55).max().iloc[-1],
        "low_55": close.rolling(55).min().iloc[-1],
        "bb_upper": bb_upper.iloc[-1],
        "bb_lower": bb_lower.iloc[-1],
        "bb_sma": bb_sma.iloc[-1],
        "bb_width": (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / (bb_sma.iloc[-1] + 1e-9),
        "atr14": atr14_series.iloc[-1],
        "plus_di": plus_di.iloc[-1],
        "minus_di": minus_di.iloc[-1],
        "adx14": adx_series.iloc[-1],
        "vol_ratio": vol_ratio_series.iloc[-1],
    }


def fundamentals(ticker):
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    def g(key):
        return info.get(key)

    return {
        "market_cap": g("marketCap"),
        "trailing_pe": g("trailingPE"),
        "forward_pe": g("forwardPE"),
        "ps": g("priceToSalesTrailing12Months"),
        "profit_margin": g("profitMargins"),
        "roe": g("returnOnEquity"),
        "revenue_growth": g("revenueGrowth"),
        "earnings_growth": g("earningsGrowth"),
        "fifty_two_week_high": g("fiftyTwoWeekHigh"),
        "fifty_two_week_low": g("fiftyTwoWeekLow"),
        "target_mean_price": g("targetMeanPrice"),
        "recommendation_key": g("recommendationKey"),
        "current_price": g("currentPrice"),
    }


def options_summary(ticker):
    try:
        exps = ticker.options
    except Exception:
        return None
    if not exps:
        return None

    exp = exps[0]
    try:
        chain = ticker.option_chain(exp)
    except Exception:
        return None

    calls = chain.calls
    puts = chain.puts
    if calls.empty or puts.empty:
        return None

    total_call_oi = calls["openInterest"].fillna(0).sum()
    total_put_oi = puts["openInterest"].fillna(0).sum()
    total_call_vol = calls["volume"].fillna(0).sum()
    total_put_vol = puts["volume"].fillna(0).sum()
    iv_call = calls["impliedVolatility"].dropna().median()
    iv_put = puts["impliedVolatility"].dropna().median()

    return {
        "expiration": exp,
        "put_call_oi": total_put_oi / total_call_oi if total_call_oi > 0 else None,
        "put_call_vol": total_put_vol / total_call_vol if total_call_vol > 0 else None,
        "iv_mid": np.nanmean([iv_call, iv_put]),
    }


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def headline_sentiment_score(text):
    text_norm = normalize_text(text)
    score = 0
    for word in POSITIVE_WORDS:
        if word in text_norm:
            score += 1
    for word in NEGATIVE_WORDS:
        if word in text_norm:
            score -= 1
    return score


def fetch_feed_entries(url, limit):
    feed = feedparser.parse(url)
    entries = []
    for entry in feed.entries[:limit]:
        entries.append(
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "source": entry.get("source", {}).get("title")
                if isinstance(entry.get("source"), dict)
                else None,
            }
        )
    return entries


def news_and_social_items(symbol):
    news_queries = [
        f"{symbol} earnings",
        f"{symbol} stock",
        "NVIDIA AI chip",
    ]
    social_queries = [
        f"site:reddit.com {symbol} stock",
        f"site:stocktwits.com {symbol}",
        f"site:x.com {symbol} stock",
    ]

    news_urls = [
        "https://nvidianews.nvidia.com/releases.xml",
        "https://feeds.feedburner.com/nvidiablog",
        "https://developer.nvidia.com/blog/feed",
    ] + [
        "https://news.google.com/rss/search?q=" + requests.utils.quote(query)
        for query in news_queries
    ]
    social_urls = [
        "https://news.google.com/rss/search?q=" + requests.utils.quote(query)
        for query in social_queries
    ]

    news_items = []
    social_items = []
    for url in news_urls:
        news_items.extend(fetch_feed_entries(url, 4))
    for url in social_urls:
        social_items.extend(fetch_feed_entries(url, 4))

    def dedupe(items, limit):
        seen = set()
        unique = []
        for item in items:
            title = item.get("title")
            if not title:
                continue
            key = normalize_text(title)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique[:limit]

    news_items = dedupe(news_items, 8)
    social_items = dedupe(social_items, 8)

    social_scores = [headline_sentiment_score(item["title"]) for item in social_items]
    avg_raw = float(np.mean(social_scores)) if social_scores else 0.0
    normalized = max(-1.0, min(1.0, avg_raw / 3.0))
    sentiment_label = "中性"
    if normalized >= 0.2:
        sentiment_label = "偏多"
    elif normalized <= -0.2:
        sentiment_label = "偏空"

    return {
        "news": news_items,
        "social": social_items,
        "social_sentiment": {
            "score": normalized,
            "label": sentiment_label,
            "sample_size": len(social_items),
        },
    }


def is_regular_us_market_hours(now_dt_et):
    if now_dt_et.weekday() >= 5:
        return False
    minutes = now_dt_et.hour * 60 + now_dt_et.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def intraday_snapshot(intraday):
    if intraday is None or intraday.empty:
        return None

    intraday = intraday.copy()
    close = intraday["Close"]
    volume = intraday["Volume"]
    latest = intraday.iloc[-1]
    prev = intraday.iloc[-2] if len(intraday) >= 2 else latest
    rolling_high = close.rolling(13).max().iloc[-1]
    rolling_low = close.rolling(13).min().iloc[-1]
    intraday_vol_ratio = volume.iloc[-1] / (volume.tail(20).mean() + 1e-9)

    return {
        "last_ts": intraday.index[-1],
        "price": latest["Close"],
        "open": latest["Open"],
        "high": latest["High"],
        "low": latest["Low"],
        "prev_close": prev["Close"],
        "chg_pct": (latest["Close"] - prev["Close"]) / (prev["Close"] + 1e-9) * 100,
        "high_13": rolling_high,
        "low_13": rolling_low,
        "vol_ratio": intraday_vol_ratio,
    }


def format_money(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "NA"
    if abs(value) >= 1e12:
        return f"{value / 1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.2f}M"
    return f"{value:.2f}"


def pct(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "NA"
    return f"{value * 100:.2f}%"


def classify_trend(tech):
    score = 0
    reasons = []

    if tech["last"] > tech["sma20"] > tech["sma50"]:
        score += 25
        reasons.append("价格站上 SMA20 与 SMA50，短中期趋势保持多头结构")
    elif tech["last"] > tech["sma20"]:
        score += 10
        reasons.append("价格高于 SMA20，但趋势强度仍需继续确认")
    else:
        reasons.append("价格跌回 SMA20 下方，趋势延续性转弱")

    if not np.isnan(tech["sma200"]) and tech["last"] > tech["sma200"]:
        score += 10
        reasons.append("价格位于 SMA200 上方，长期趋势仍偏强")

    if tech["macd"] > tech["signal"] and tech["macd_hist"] > tech["macd_hist_prev"]:
        score += 15
        reasons.append("MACD 位于信号线之上且柱体扩张，动能正在增强")
    elif tech["macd"] > tech["signal"]:
        score += 8
        reasons.append("MACD 维持金叉，但动能扩张有限")
    else:
        reasons.append("MACD 位于信号线下方，动能偏弱")

    if 45 <= tech["rsi14"] <= 68:
        score += 15
        reasons.append("RSI 位于健康强势区间，趋势上涨但未明显过热")
    elif tech["rsi14"] > 70:
        score -= 5
        reasons.append("RSI 进入过热区，追涨性价比下降")
    elif tech["rsi14"] < 40:
        score -= 10
        reasons.append("RSI 偏弱，说明多头承接不足")

    if tech["adx14"] >= 25 and tech["plus_di"] > tech["minus_di"]:
        score += 20
        reasons.append("ADX 超过 25 且 +DI 领先，趋势具备持续性")
    elif tech["adx14"] >= 20:
        score += 8
        reasons.append("ADX 超过 20，市场开始出现趋势化")
    else:
        reasons.append("ADX 偏低，价格更可能处于震荡而非单边")

    if tech["vol_ratio"] >= 1.2:
        score += 10
        reasons.append("量能高于 20 日均量，趋势信号可信度更高")

    return max(0, min(100, score)), reasons


def build_entry_alerts(tech, intraday, social, fundamentals_data):
    alerts = []
    sentiment = social["social_sentiment"]["score"]
    trend_score, trend_reasons = classify_trend(tech)
    add_on_bias = trend_score >= 70 and sentiment >= -0.1

    breakout_score = trend_score
    breakout_reasons = list(trend_reasons)
    if tech["last"] >= tech["high_20"] * 0.995:
        breakout_score += 12
        breakout_reasons.append("日线价格逼近或突破 20 日高点，存在动能延续机会")
    if intraday and intraday["price"] >= intraday["high_13"] * 0.998 and intraday["vol_ratio"] >= 1.2:
        breakout_score += 15
        breakout_reasons.append("盘中价格逼近 13 根 K 线高点且量能放大，属于短线突破确认")
    if sentiment >= SOCIAL_SENTIMENT_THRESHOLD:
        breakout_score += 8
        breakout_reasons.append("社媒情绪偏多，对突破信号形成辅助确认")

    if breakout_score >= ALERT_SCORE_THRESHOLD:
        alerts.append(
            {
                "key": "breakout_entry",
                "kind": "入场提醒",
                "score": min(100, breakout_score),
                "headline": f"{SYMBOL} 突破型入场信号",
                "summary": "趋势、动能、量能与情绪出现共振，可作为分批试探性建仓窗口。",
                "details": breakout_reasons,
            }
        )

    pullback_score = trend_score
    pullback_reasons = list(trend_reasons)
    pullback_distance = abs(tech["last"] - tech["sma20"]) / (tech["atr14"] + 1e-9)
    if tech["last"] > tech["sma20"] and pullback_distance <= 0.8:
        pullback_score += 15
        pullback_reasons.append("价格回踩 SMA20 附近且仍未破位，符合强趋势中的低吸结构")
    if tech["rsi14"] >= 45 and tech["rsi14"] <= 58:
        pullback_score += 10
        pullback_reasons.append("RSI 回落到更舒适的再介入区间，追高风险低于突破追价")
    if sentiment >= -0.05:
        pullback_score += 5
        pullback_reasons.append("社媒情绪未明显转空，回踩后继续上行的阻力较小")

    if pullback_score >= ALERT_SCORE_THRESHOLD:
        alerts.append(
            {
                "key": "pullback_add",
                "kind": "加仓提醒",
                "score": min(100, pullback_score),
                "headline": f"{SYMBOL} 趋势回踩加仓信号",
                "summary": "强趋势中回踩支撑位，若采用分批加仓，这类位置通常优于追高。",
                "details": pullback_reasons,
            }
        )

    risk_score = 0
    risk_reasons = []
    if tech["rsi14"] > 74:
        risk_score += 20
        risk_reasons.append("RSI 过热，短线回撤风险升高")
    if social["social_sentiment"]["score"] <= -0.25:
        risk_score += 15
        risk_reasons.append("社媒情绪显著偏空，说明一致性预期在恶化")
    if fundamentals_data["recommendation_key"] in {"sell", "underperform"}:
        risk_score += 10
        risk_reasons.append("分析师一致预期偏弱，不支持激进加仓")
    if risk_score >= 25 and add_on_bias:
        alerts = [alert for alert in alerts if alert["key"] != "pullback_add"]

    return alerts, trend_score


def compose_daily_report(ticker, daily_hist, intraday_hist):
    tech = tech_summary(daily_hist)
    fundamentals_data = fundamentals(ticker)
    options_data = options_summary(ticker)
    info_bundle = news_and_social_items(SYMBOL)
    social = info_bundle["social_sentiment"]
    alerts, trend_score = build_entry_alerts(
        tech,
        intraday_snapshot(intraday_hist),
        info_bundle,
        fundamentals_data,
    )

    last_date = daily_hist.index[-1].strftime("%Y-%m-%d")
    now_dt = now_sydney()
    subject = f"{SUBJECT_PREFIX} - {now_dt.strftime('%Y-%m-%d')}"

    trend_label = "强势多头" if trend_score >= 75 else "偏多震荡" if trend_score >= 55 else "中性偏弱"

    tech_lines = [
        f"最新价: ${tech['last']:.2f} (日变动 {tech['chg']:+.2f}, {tech['chg_pct']:+.2f}%)  数据日期: {last_date}",
        f"均线结构: SMA20 {tech['sma20']:.2f}, SMA50 {tech['sma50']:.2f}, SMA200 {tech['sma200']:.2f}" if not np.isnan(tech["sma200"]) else f"均线结构: SMA20 {tech['sma20']:.2f}, SMA50 {tech['sma50']:.2f}",
        f"动量指标: RSI14 {tech['rsi14']:.1f}, MACD {tech['macd']:.2f}, Signal {tech['signal']:.2f}, Hist {tech['macd_hist']:.2f}",
        f"趋势强度: ADX14 {tech['adx14']:.1f}, +DI {tech['plus_di']:.1f}, -DI {tech['minus_di']:.1f}, 量比 {tech['vol_ratio']:.2f}",
        f"波动区间: 20日高 {tech['high_20']:.2f} / 20日低 {tech['low_20']:.2f}, 布林中轨 {tech['bb_sma']:.2f}, ATR14 {tech['atr14']:.2f}",
    ]

    process_lines = [f"- {line}" for line in classify_trend(tech)[1]]

    fund_lines = [
        f"市值: {format_money(fundamentals_data['market_cap'])}",
        f"估值: trailing PE {fundamentals_data['trailing_pe'] if fundamentals_data['trailing_pe'] is not None else 'NA'}, forward PE {fundamentals_data['forward_pe'] if fundamentals_data['forward_pe'] is not None else 'NA'}, P/S {fundamentals_data['ps'] if fundamentals_data['ps'] is not None else 'NA'}",
        f"盈利与增长: 净利率 {pct(fundamentals_data['profit_margin'])}, ROE {pct(fundamentals_data['roe'])}, 收入增速 {pct(fundamentals_data['revenue_growth'])}, 利润增速 {pct(fundamentals_data['earnings_growth'])}",
        f"52周区间: {fundamentals_data['fifty_two_week_low']} - {fundamentals_data['fifty_two_week_high']}, 一致预期 {fundamentals_data['recommendation_key'] or 'NA'}, 目标均价 {fundamentals_data['target_mean_price'] or 'NA'}",
    ]

    if options_data:
        options_lines = [
            f"最近到期: {options_data['expiration']}",
            f"Put/Call 成交量比: {options_data['put_call_vol']:.2f}" if options_data["put_call_vol"] is not None else "Put/Call 成交量比: NA",
            f"Put/Call 持仓量比: {options_data['put_call_oi']:.2f}" if options_data["put_call_oi"] is not None else "Put/Call 持仓量比: NA",
            f"隐含波动率中位: {options_data['iv_mid']:.2%}" if options_data["iv_mid"] is not None else "隐含波动率中位: NA",
        ]
    else:
        options_lines = ["期权数据: 暂不可用"]

    news_lines = [
        "- " + item["title"] + (f" ({item['source']})" if item.get("source") else "")
        for item in info_bundle["news"]
    ] or ["- 暂无可用新闻"]

    social_lines = [
        f"社媒情绪结论: {social['label']} (分数 {social['score']:+.2f}, 样本 {social['sample_size']})",
    ]
    social_lines.extend(
        "- " + item["title"] + (f" ({item['source']})" if item.get("source") else "")
        for item in info_bundle["social"][:5]
    )

    action_lines = [
        f"趋势评分: {trend_score}/100 ({trend_label})",
    ]
    if alerts:
        for alert in alerts:
            action_lines.append(f"{alert['kind']}: {alert['headline']}，评分 {alert['score']}/100")
            action_lines.append(f"理由: {alert['summary']}")
    else:
        action_lines.append("当前未出现达到阈值的分批入场/加仓提醒，继续等待更清晰信号。")

    risk_lines = []
    if tech["rsi14"] >= 70:
        risk_lines.append("RSI 已偏热，若加速上冲需防止高位震荡。")
    if options_data and options_data["iv_mid"] is not None and options_data["iv_mid"] >= 0.6:
        risk_lines.append("隐含波动率偏高，说明市场对事件风险定价较高。")
    if social["score"] <= -0.2:
        risk_lines.append("社媒情绪偏空，说明市场讨论热度可能正在转弱。")
    if not risk_lines:
        risk_lines.append("当前主要风险来自宏观数据、行业轮动与财报预期变化。")

    body = "\n".join(
        [
            f"{SYMBOL} 每日简报 ({now_dt.strftime('%Y-%m-%d')} Sydney)",
            "",
            "[技术面概览]",
            *tech_lines,
            "",
            "[技术面分析过程]",
            *process_lines,
            "",
            "[基本面]",
            *fund_lines,
            "",
            "[新闻催化]",
            *news_lines,
            "",
            "[社交媒体情绪]",
            *social_lines,
            "",
            "[期权]",
            *options_lines,
            "",
            "[交易辅助判断]",
            *action_lines,
            "",
            "[风险提示]",
            *risk_lines,
            "",
            "提示: 本简报仅供信息参考，不构成投资建议。",
            "说明: 社媒情绪基于公开 RSS/新闻中与 Reddit、Stocktwits、X 相关条目的标题情绪打分，属于辅助信号。",
            "来源: Yahoo Finance, NVIDIA RSS, Google News RSS",
        ]
    )
    return subject, body


def compose_alert_email(alert, tech, intraday, social):
    now_dt = now_sydney()
    subject = f"{SYMBOL} {alert['kind']} - {alert['headline']}"
    intraday_lines = ["盘中数据: 暂不可用"]
    if intraday:
        intraday_lines = [
            f"最新时间: {intraday['last_ts']}",
            f"盘中价格: ${intraday['price']:.2f} (相对上一根K线 {intraday['chg_pct']:+.2f}%)",
            f"13根K线高低区间: {intraday['low_13']:.2f} - {intraday['high_13']:.2f}, 盘中量比 {intraday['vol_ratio']:.2f}",
        ]

    body = "\n".join(
        [
            f"{SYMBOL} 机会提醒 ({now_dt.strftime('%Y-%m-%d %H:%M')} Sydney)",
            "",
            f"提醒类型: {alert['kind']}",
            f"信号名称: {alert['headline']}",
            f"综合评分: {alert['score']}/100",
            f"结论: {alert['summary']}",
            "",
            "[技术面快照]",
            f"最新价: ${tech['last']:.2f}, SMA20 {tech['sma20']:.2f}, SMA50 {tech['sma50']:.2f}, RSI14 {tech['rsi14']:.1f}",
            f"MACD: {tech['macd']:.2f} / Signal {tech['signal']:.2f} / Hist {tech['macd_hist']:.2f}",
            f"ADX14: {tech['adx14']:.1f}, +DI {tech['plus_di']:.1f}, -DI {tech['minus_di']:.1f}",
            "",
            "[盘中确认]",
            *intraday_lines,
            "",
            "[社媒情绪]",
            f"情绪结论: {social['label']} (分数 {social['score']:+.2f}, 样本 {social['sample_size']})",
            "",
            "[详细理由]",
            *[f"- {reason}" for reason in alert["details"]],
            "",
            "提示: 该提醒用于辅助分批入场或加仓，不代表必须立即执行。",
        ]
    )
    return subject, body


def send_email(subject, body):
    if not all([SMTP_USER, SMTP_PASS, EMAIL_FROM, EMAIL_TO]):
        raise RuntimeError("Missing SMTP_USER/SMTP_APP_PASSWORD/FROM_EMAIL/TO_EMAIL")

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def maybe_send_daily_report(state, now_dt, ticker, daily_hist, intraday_hist, dry_run):
    if not within_send_window(now_dt):
        print("Daily report skipped: not in send window.")
        return False
    if already_sent_daily(state, now_dt):
        print("Daily report skipped: already sent today.")
        return False

    subject, body = compose_daily_report(ticker, daily_hist, intraday_hist)
    if dry_run:
        print(subject)
        print(body)
    else:
        send_email(subject, body)

    mark_daily_sent(state, now_dt)
    print("Daily report sent.")
    return True


def maybe_send_entry_alerts(state, now_dt, ticker, daily_hist, intraday_hist, dry_run):
    if not ENTRY_ALERTS_ENABLED:
        print("Entry alerts disabled.")
        return False
    if not is_regular_us_market_hours(now_us_eastern()):
        print("Entry alerts skipped: outside regular US market hours.")
        return False

    tech = tech_summary(daily_hist)
    social_bundle = news_and_social_items(SYMBOL)
    intraday = intraday_snapshot(intraday_hist)
    alerts, _ = build_entry_alerts(tech, intraday, social_bundle, fundamentals(ticker))

    sent_any = False
    for alert in alerts:
        if alert_in_cooldown(state, alert["key"], now_dt):
            print(f"Alert skipped due to cooldown: {alert['key']}")
            continue

        subject, body = compose_alert_email(alert, tech, intraday, social_bundle["social_sentiment"])
        if dry_run:
            print(subject)
            print(body)
        else:
            send_email(subject, body)
        mark_alert_sent(state, alert["key"], now_dt, {"score": alert["score"], "headline": alert["headline"]})
        sent_any = True
        print(f"Alert sent: {alert['key']}")

    if not sent_any:
        print("No alert sent.")
    return sent_any


def main():
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    now_dt = now_sydney()
    state = read_state()
    ticker, daily_hist, intraday_hist = fetch_price_history()

    daily_sent = maybe_send_daily_report(state, now_dt, ticker, daily_hist, intraday_hist, dry_run)
    alerts_sent = maybe_send_entry_alerts(state, now_dt, ticker, daily_hist, intraday_hist, dry_run)

    if daily_sent or alerts_sent:
        write_state(state)
        print("State updated.")
    else:
        print("Nothing sent; state unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
