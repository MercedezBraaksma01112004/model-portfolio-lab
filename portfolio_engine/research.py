"""Holding research: fundamentals and analyst consensus from Yahoo Finance, plus trailing
total returns computed from dividend-adjusted prices. Cached in data/cache/research.json
and refreshed when older than research.max_age_days (default 7); prices-based returns are
recomputed on every build.

Analyst consensus is Yahoo's aggregate of the covering brokers: recommendationMean runs
from 1 (Strong Buy) to 5 (Sell), with the number of analysts and mean target price. It is
an input to a bounded weighting rule and a review flag, never an automatic trade."""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Settings
from .market_data import MarketData

log = logging.getLogger(__name__)

FIELDS = ["sector", "industry", "longName", "longBusinessSummary", "marketCap", "trailingPE", "forwardPE",
          "dividendYield", "trailingAnnualDividendYield", "trailingAnnualDividendRate", "currentPrice", "regularMarketPrice", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "beta",
          "recommendationMean", "recommendationKey", "numberOfAnalystOpinions", "targetMeanPrice",
          "currency", "quoteType", "totalAssets", "category", "fundFamily"]


@dataclass
class HoldingResearch:
    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    summary: str = ""
    quote_type: str = ""
    market_cap: float | None = None
    pe_trailing: float | None = None
    pe_forward: float | None = None
    dividend_yield_pct: float | None = None
    beta: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    consensus_mean: float | None = None      # 1 strong buy .. 5 sell
    consensus_label: str = ""
    analysts: int | None = None
    target_mean: float | None = None
    target_upside_pct: float | None = None
    return_1y_pct: float | None = None
    return_3y_pct_pa: float | None = None
    return_5y_pct_pa: float | None = None
    return_10y_pct_pa: float | None = None
    return_proxy: dict = field(default_factory=dict)   # period -> proxy ticker used when the holding's history is too short
    history_years: float | None = None
    above_200dma: bool | None = None
    momentum_12_1_pct: float | None = None
    max_drawdown_1y_pct: float | None = None
    volatility_1y_pct: float | None = None
    price: float | None = None
    price_currency: str = ""
    sparkline: list[float] = field(default_factory=list)   # last ~250 closes, normalised to 100
    yield_basis: str = ""
    data_flags: list[str] = field(default_factory=list)
    fetched: str = ""
    source: str = ""


def consensus_label(mean: float | None) -> str:
    if mean is None:
        return "no coverage"
    if mean < 1.75:
        return "Strong Buy"
    if mean < 2.5:
        return "Buy"
    if mean < 3.5:
        return "Hold"
    if mean < 4.25:
        return "Underperform"
    return "Sell"


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    return v


def _fetch_info(ticker: str) -> dict:
    import yfinance as yf
    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception as e:  # noqa: BLE001
        log.warning("info failed for %s: %s", ticker, e)
        return {}
    out = {k: _clean(info.get(k)) for k in FIELDS}
    # Actual cash dividends paid in the last 12 months: the only reliable basis for a trailing yield.
    try:
        divs = tk.dividends
        if divs is not None and len(divs):
            cutoff = pd.Timestamp.now(tz=divs.index.tz) - pd.Timedelta(days=365)
            recent = divs[divs.index >= cutoff]
            out["_dividends_12m"] = float(recent.sum())
            out["_dividend_count_12m"] = int(len(recent))
    except Exception as e:  # noqa: BLE001
        log.debug("dividends failed for %s: %s", ticker, e)
    return out


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _returns_from_prices(s: pd.Series) -> dict:
    s = s.dropna()
    out: dict = {}
    if len(s) < 40:
        return out
    last = s.index[-1]
    def ret(years: float):
        start = last - pd.DateOffset(years=years)
        window = s[s.index <= start]
        if window.empty or (start - window.index[-1]).days > 20:
            return None
        base = float(window.iloc[-1])
        total = float(s.iloc[-1]) / base - 1
        return total if years == 1 else (1 + total) ** (1 / years) - 1
    r1, r3, r5, r10 = ret(1), ret(3), ret(5), ret(10)
    out["return_1y_pct"] = None if r1 is None else round(r1 * 100, 2)
    out["return_3y_pct_pa"] = None if r3 is None else round(r3 * 100, 2)
    out["return_5y_pct_pa"] = None if r5 is None else round(r5 * 100, 2)
    out["return_10y_pct_pa"] = None if r10 is None else round(r10 * 100, 2)
    out["history_years"] = round((last - s.index[0]).days / 365.25, 1)
    if len(s) >= 253:
        out["momentum_12_1_pct"] = round(float(s.iloc[-22] / s.iloc[-253] - 1) * 100, 2)
    if len(s) >= 200:
        out["above_200dma"] = bool(s.iloc[-1] > s.rolling(200).mean().iloc[-1])
    last_year = s[s.index > last - pd.DateOffset(years=1)]
    if len(last_year) > 40:
        dd = (last_year / last_year.cummax() - 1).min()
        out["max_drawdown_1y_pct"] = round(float(dd) * 100, 2)
        out["volatility_1y_pct"] = round(float(np.log(last_year).diff().std() * math.sqrt(252)) * 100, 2)
        step = max(1, len(last_year) // 120)
        spark = last_year.iloc[::step]
        out["sparkline"] = [round(float(v) / float(spark.iloc[0]) * 100, 2) for v in spark]
    return out


def _unlisted_research(r, u, md: MarketData) -> HoldingResearch:
    """A research record for an unlisted fund: the manager's published returns and price, with day-to-day risk,
    momentum and the sparkline taken from its listed twin and labelled as such."""
    def num(k):
        v = str(u.get(k, "") or "").strip()
        return float(v) if v else None
    twin = str(u.get("twin", "") or "").strip()
    hr = HoldingResearch(ticker=r.ticker, name=str(u.get("name") or r.name), sector=str(u.get("sector") or ""), industry=str(u.get("liquidity") or ""),
                         summary=str(u.get("notes") or ""), quote_type="UNLISTED", price=num("unit_price"), price_currency="AUD",
                         dividend_yield_pct=num("yield"), yield_basis="manager's distribution figure", consensus_label="no coverage",
                         return_1y_pct=num("return_1y"), return_3y_pct_pa=num("return_3y"), return_5y_pct_pa=num("return_5y"), return_10y_pct_pa=num("return_10y"),
                         fetched=str(u.get("returns_as_at") or u.get("price_date") or ""), source=f"manager published; risk from listed twin {twin}" if twin else "manager published")
    if twin and twin in md.prices.columns:
        tw = _returns_from_prices(md.prices[twin])
        for k in ("momentum_12_1_pct", "above_200dma", "max_drawdown_1y_pct", "volatility_1y_pct", "sparkline", "history_years"):
            if k in tw:
                setattr(hr, k, tw[k])
        for period, key in [("1y", "return_1y_pct"), ("3y", "return_3y_pct_pa"), ("5y", "return_5y_pct_pa"), ("10y", "return_10y_pct_pa")]:
            if getattr(hr, key) is None and tw.get(key) is not None:
                setattr(hr, key, tw[key]); hr.return_proxy[period] = twin
        hr.data_flags.append(f"unlisted: volatility, drawdown and chart are the listed twin {twin}")
    return hr


def get_research(settings: Settings, universe: pd.DataFrame, md: MarketData, *, force: bool = False,
                 offline: bool = False) -> dict[str, HoldingResearch]:
    cfg = settings.raw.get("research", {})
    max_age_days = float(cfg.get("max_age_days", 7))
    cache_path = settings.path("research_cache") if "research_cache" in settings.raw["paths"] else settings.root / "data/cache/research.json"
    cache = _load_cache(cache_path)
    now = time.time()
    result: dict[str, HoldingResearch] = {}
    listed = [r for r in universe.itertuples() if r.ticker in md.prices.columns and not md.synthetic]
    changed = False
    from .config import load_unlisted_funds
    unlisted = load_unlisted_funds(settings)
    for r in universe.itertuples():
        if r.ticker in unlisted.index and r.ticker not in md.prices.columns:
            result[r.ticker] = _unlisted_research(r, unlisted.loc[r.ticker], md)
            continue
        entry = cache.get(r.ticker, {})
        fresh = entry and (now - entry.get("_ts", 0)) < max_age_days * 86400
        stale_format = entry and "_dividends_12m" not in entry.get("info", {}) and entry.get("info")   # cached before dividend history was collected
        if r.ticker in md.prices.columns and not offline and not md.synthetic and (force or not fresh or stale_format):
            info = _fetch_info(r.ticker)
            entry = {"_ts": time.time(), "info": info}
            cache[r.ticker] = entry
            changed = True
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache))   # save as we go so an interrupted refresh keeps its progress
            time.sleep(0.15)
        info = entry.get("info", {}) if entry else {}
        if str(info.get("currency", "")) == "GBp":   # London quotes in pence: express everything in pounds, as the price feed does
            info = {**info, "currency": "GBP", **{k: info[k] / 100.0 for k in ("currentPrice", "regularMarketPrice", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "targetMeanPrice", "_dividends_12m") if info.get(k) is not None}}   # trailingAnnualDividendRate is already in pounds
        hr = HoldingResearch(ticker=r.ticker, name=info.get("longName") or r.name, sector=info.get("sector") or info.get("category") or "",
                             industry=info.get("industry") or info.get("fundFamily") or "", summary=info.get("longBusinessSummary") or "",
                             quote_type=info.get("quoteType") or "", market_cap=info.get("marketCap") or info.get("totalAssets"),
                             pe_trailing=info.get("trailingPE"), pe_forward=info.get("forwardPE"), beta=info.get("beta"),
                             week52_high=info.get("fiftyTwoWeekHigh"), week52_low=info.get("fiftyTwoWeekLow"),
                             consensus_mean=info.get("recommendationMean"), analysts=(int(info["numberOfAnalystOpinions"]) if info.get("numberOfAnalystOpinions") else None),
                             target_mean=info.get("targetMeanPrice"), price_currency=info.get("currency") or r.currency,
                             fetched=(pd.Timestamp(entry["_ts"], unit="s").strftime("%Y-%m-%d") if entry.get("_ts") else ""),
                             source=("yfinance" if info else ("manual" if r.ticker not in md.prices.columns else "prices only")))
        # Yahoo's dividendYield changed units between yfinance versions (fraction vs percent), so derive the
        # yield from the trailing dividend rate and price where possible, then fall back to the fraction field.
        # Trailing yield = cash dividends actually paid in the last 12 months / price. Yahoo's summary
        # fields double count specials and change units between versions, so they are the fallback only.
        px = md.latest(r.ticker) if r.ticker in md.prices.columns else None
        paid = info.get("_dividends_12m")
        paid_y = round(paid / px * 100, 2) if (paid is not None and px) else None
        rate, px2 = info.get("trailingAnnualDividendRate"), info.get("currentPrice") or info.get("regularMarketPrice")
        rate_y = round(rate / px2 * 100, 2) if (rate and px2) else (round(info["trailingAnnualDividendYield"] * 100, 2) if info.get("trailingAnnualDividendYield") else None)
        # Two independent estimates. Errors in either source inflate rather than deflate (double counted
        # specials, currency mix-ups), so when they disagree badly the lower one is used and it is flagged.
        if paid_y is not None and rate_y is not None and max(paid_y, rate_y) > 1.4 * max(min(paid_y, rate_y), 0.1):
            hr.dividend_yield_pct = min(paid_y, rate_y)
            hr.yield_basis = "lower of two conflicting sources"
            hr.data_flags.append(f"dividend sources disagree ({paid_y:.1f}% paid vs {rate_y:.1f}% Yahoo rate); lower used")
        elif paid_y is not None:
            hr.dividend_yield_pct = paid_y
            hr.yield_basis = f"{info.get('_dividend_count_12m', 0)} payments in the last 12 months"
        elif rate_y is not None:
            hr.dividend_yield_pct = rate_y
            hr.yield_basis = "Yahoo trailing rate"
        if hr.dividend_yield_pct is not None and hr.dividend_yield_pct > 15:
            hr.data_flags.append(f"yield {hr.dividend_yield_pct:.1f}% looks wrong; ignored")
            hr.dividend_yield_pct = None
        if hr.analysts and hr.analysts >= 3 and hr.consensus_mean:
            hr.consensus_label = consensus_label(hr.consensus_mean)
        else:
            hr.consensus_label = "no coverage" if not hr.consensus_mean else "thin coverage"
        if hr.pe_forward is not None and hr.pe_forward < 0:
            hr.data_flags.append(f"forward PE {hr.pe_forward:.0f} is a data error; ignored")
            hr.pe_forward = None
        if r.ticker in md.prices.columns:
            s = md.prices[r.ticker]
            hr.price = md.latest(r.ticker)
            for k, v in _returns_from_prices(s).items():
                setattr(hr, k, v)
            # Fill missing long-period returns from the asset class index ETF and say so.
            chain = settings.raw.get("returns", {}).get("long_history_proxies", {}).get(r.asset_class) or []
            chain = [chain] if isinstance(chain, str) else list(chain)
            for period, key in [("3y", "return_3y_pct_pa"), ("5y", "return_5y_pct_pa"), ("10y", "return_10y_pct_pa")]:
                if getattr(hr, key) is not None:
                    continue
                for proxy_t in chain:
                    if proxy_t in md.prices.columns and proxy_t != r.ticker:
                        pr = _returns_from_prices(md.prices[proxy_t])
                        if pr.get(key) is not None:
                            setattr(hr, key, pr[key])
                            hr.return_proxy[period] = proxy_t
                            break
            if hr.target_mean and hr.price:
                hr.target_upside_pct = round((hr.target_mean / hr.price - 1) * 100, 1)
        result[r.ticker] = hr
    if changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    return result


def research_to_records(research: dict[str, HoldingResearch]) -> list[dict]:
    return [asdict(v) for v in research.values()]
