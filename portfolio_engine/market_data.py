"""Market data: daily closes for every listed ticker in the universe plus the proxy
tickers used for signals. Sources are tried in order (yfinance, stooq, csv). Unlisted
holdings are priced from data/manual_prices.csv. A synthetic source exists purely so the
pipeline can be tested without network access; anything built on synthetic data is
labelled as such in every output."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Settings

log = logging.getLogger(__name__)


@dataclass
class MarketData:
    prices: pd.DataFrame            # index: date, columns: ticker, values: close in native currency
    fx_aud_per_usd: float           # AUD per 1 USD
    as_of: pd.Timestamp
    source_by_ticker: dict[str, str] = field(default_factory=dict)
    synthetic: bool = False
    fx_aud_per: dict[str, float] = field(default_factory=dict)   # currency code -> AUD per 1 unit (USD, EUR, CAD, ...)
    fx_tickers: dict[str, str] = field(default_factory=dict)     # currency code -> the FX ticker that priced it

    def latest(self, ticker: str) -> float | None:
        if ticker not in self.prices.columns:
            return None
        s = self.prices[ticker].dropna()
        return float(s.iloc[-1]) if len(s) else None

    def latest_aud(self, ticker: str, currency: str) -> float | None:
        p = self.latest(ticker)
        if p is None:
            return None
        c = (currency or "AUD").upper()
        if c == "AUD":
            return p
        rate = self.fx_aud_per.get(c) or (self.fx_aud_per_usd if c == "USD" else None)
        if rate is None:
            log.warning("No FX rate for %s; %s left unconverted", c, ticker)
            return p
        return p * rate

    def fx_series(self, currency: str) -> pd.Series | None:
        """Daily AUD per one unit of `currency`, for converting a price history."""
        c = (currency or "AUD").upper()
        if c == "AUD":
            return None
        t = self.fx_tickers.get(c)
        if t is None or t not in self.prices.columns:
            return None
        s = self.prices[t].ffill()
        return 1.0 / s if _quotes_foreign_per_aud(t) else s

    def missing(self, tickers: list[str]) -> list[str]:
        return [t for t in tickers if self.latest(t) is None]


# ---------------------------------------------------------------- sources

def _fetch_yfinance(tickers: list[str], days: int) -> pd.DataFrame:
    import yfinance as yf  # imported lazily so the package works without it
    end = datetime.now(timezone.utc) + timedelta(days=1)   # yfinance end is exclusive
    start = end - timedelta(days=days + 1)
    frames = {}
    # Batch download; yfinance handles multiple tickers in one request.
    data = yf.download(tickers, start=start.date(), end=end.date(), progress=False,
                       auto_adjust=True, group_by="ticker", threads=True)
    if data.empty:
        return pd.DataFrame()
    for t in tickers:
        try:
            s = data[t]["Close"] if isinstance(data.columns, pd.MultiIndex) else data["Close"]
        except KeyError:
            continue
        s = s.dropna()
        if len(s):
            frames[t] = s / 100.0 if _quotes_in_pence(t) else s
    return pd.DataFrame(frames)


def _quotes_in_pence(ticker: str) -> bool:
    """London listings are quoted in pence (GBp) on Yahoo Finance; the engine keeps them in pounds."""
    return ticker.upper().endswith(".L")


def _quotes_foreign_per_aud(fx_ticker: str) -> bool:
    """AUDUSD=X quotes USD per AUD and must be inverted; EURAUD=X style tickers quote AUD per unit directly."""
    return fx_ticker.upper().startswith("AUD")


def fx_tickers_for(md_cfg: dict) -> dict[str, str]:
    """Currency code -> FX ticker. `fx_tickers` in settings extends the legacy single `fx_ticker` (USD)."""
    out = {"USD": md_cfg.get("fx_ticker", "AUDUSD=X")}
    out.update({str(k).upper(): str(v) for k, v in (md_cfg.get("fx_tickers") or {}).items()})
    return out


def _stooq_symbol(ticker: str) -> str:
    if ticker.endswith(".AX") or ticker.endswith(".XA"):
        return ticker[:-3].lower() + ".au"
    if ticker.endswith("=X"):
        return ticker[:-2].lower()
    if "." not in ticker and "=" not in ticker:
        return ticker.lower() + ".us"
    return ticker.lower()


def _fetch_stooq(tickers: list[str], days: int) -> pd.DataFrame:
    import requests
    frames = {}
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    for t in tickers:
        url = f"https://stooq.com/q/d/l/?s={_stooq_symbol(t)}&i=d"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200 or "Date" not in r.text[:50]:
                continue
            df = pd.read_csv(pd.io.common.StringIO(r.text), parse_dates=["Date"]).set_index("Date")
            s = df["Close"].dropna()
            s = s[s.index >= cutoff]
            if len(s):
                frames[t] = s
            time.sleep(0.2)
        except Exception as e:  # noqa: BLE001
            log.debug("stooq failed for %s: %s", t, e)
    return pd.DataFrame(frames)


def _fetch_csv_dir(tickers: list[str], directory: Path) -> pd.DataFrame:
    frames = {}
    for t in tickers:
        p = directory / f"{t}.csv"
        if p.exists():
            df = pd.read_csv(p)
            date_col = df.columns[0]
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.set_index(date_col)
            close_col = "close" if "close" in df.columns else df.columns[0]
            frames[t] = pd.to_numeric(df[close_col], errors="coerce").dropna()
    return pd.DataFrame(frames)


def _fetch_synthetic(tickers: list[str], days: int) -> pd.DataFrame:
    """Deterministic geometric random walks seeded by ticker, so tests are repeatable.
    Drift and volatility are loosely realistic per instrument type."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=int(days * 5 / 7))
    frames = {}
    for t in tickers:
        seed = sum(ord(c) * (i + 1) for i, c in enumerate(t)) % (2**32)
        rng = np.random.default_rng(seed)
        if t.endswith("=X"):
            mu, sigma, start = 0.0, 0.08, 0.66 if t.startswith("AUD") else 1.6
        elif t in {"AAA.AX"}:
            mu, sigma, start = 0.04, 0.002, 50.0
        elif t in {"VAF.AX", "VGB.AX", "VIF.AX", "CRED.AX", "BHYB.AX", "SUBD.AX"}:
            mu, sigma, start = 0.03, 0.05, 45.0
        elif t == "GOLD.AX":
            mu, sigma, start = 0.10, 0.14, 35.0
        else:
            mu, sigma, start = 0.08, 0.18, 50.0 + (seed % 100)
        dt = 1 / 252
        steps = rng.normal((mu - 0.5 * sigma**2) * dt, sigma * np.sqrt(dt), len(idx))
        frames[t] = pd.Series(start * np.exp(np.cumsum(steps)), index=idx)
    return pd.DataFrame(frames)


# ---------------------------------------------------------------- cache and load

def load_manual_prices(settings: Settings) -> dict[str, float]:
    p = settings.path("manual_prices")
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    return {str(r.ticker): float(r.price) for r in df.itertuples()}


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df


def _cache_is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < max_age_hours * 3600


def get_market_data(settings: Settings, tickers: list[str], *, force_refresh: bool = False,
                    offline: bool = False) -> MarketData:
    """Return a MarketData object covering `tickers` (listed only; manual-priced holdings are
    handled by the caller). Uses the cache when it is fresh and complete."""
    md_cfg = settings.market_data
    fx_ticker = md_cfg.get("fx_ticker", "AUDUSD=X")
    fx_map = fx_tickers_for(md_cfg)
    wanted = sorted(set(tickers) | {fx_ticker} | set(fx_map.values()))
    cache_path = settings.path("price_cache")
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if offline:
        prices = _fetch_synthetic(wanted, md_cfg["history_days"])
        return _finish(prices, fx_ticker, {t: "synthetic" for t in wanted}, synthetic=True, fx_map=fx_map)

    cached = _read_cache(cache_path)
    if cached is not None and not force_refresh and _cache_is_fresh(cache_path, md_cfg["max_cache_age_hours"]):
        if all(t in cached.columns for t in wanted):
            log.info("Using cached prices from %s", cache_path)
            return _finish(cached[wanted], fx_ticker, {t: "cache" for t in wanted}, fx_map=fx_map)

    prices = pd.DataFrame()
    source_by_ticker: dict[str, str] = {}
    remaining = list(wanted)
    for source in md_cfg["sources"]:
        if not remaining:
            break
        try:
            if source == "yfinance":
                got = _fetch_yfinance(remaining, md_cfg["history_days"])
            elif source == "stooq":
                got = _fetch_stooq(remaining, md_cfg["history_days"])
            elif source == "csv":
                got = _fetch_csv_dir(remaining, settings.path("csv_price_dir"))
            elif source == "synthetic":
                got = _fetch_synthetic(remaining, md_cfg["history_days"])
            else:
                log.warning("Unknown market data source %s", source)
                continue
        except Exception as e:  # noqa: BLE001
            log.warning("Source %s failed: %s", source, e)
            continue
        got = got.loc[:, [c for c in got.columns if got[c].dropna().shape[0] >= 30]]
        if not got.empty:
            prices = got if prices.empty else prices.join(got, how="outer")
            for t in got.columns:
                source_by_ticker[t] = source
            remaining = [t for t in remaining if t not in prices.columns]
            log.info("%s supplied %d tickers; %d remaining", source, got.shape[1], len(remaining))

    if remaining and cached is not None:
        # Fall back to stale cache for anything that could not be refreshed.
        stale = [t for t in remaining if t in cached.columns]
        if stale:
            prices = prices.join(cached[stale], how="outer") if not prices.empty else cached[stale]
            for t in stale:
                source_by_ticker[t] = "stale-cache"
            remaining = [t for t in remaining if t not in stale]
            log.warning("Using stale cache for %s", stale)
    if remaining:
        log.warning("No price data for %s", remaining)

    if prices.empty:
        raise RuntimeError("No market data could be obtained from any source. Run with --offline "
                           "to use synthetic data for testing, or place CSVs in data/prices/.")

    prices = prices.sort_index()
    # Merge into the cache so partial refreshes do not lose older columns.
    merged = prices if cached is None else cached.drop(columns=[c for c in prices.columns if c in cached.columns]).join(prices, how="outer")
    merged.sort_index().to_csv(cache_path)
    return _finish(prices, fx_ticker, source_by_ticker, fx_map=fx_map)


def _finish(prices: pd.DataFrame, fx_ticker: str, sources: dict[str, str], synthetic: bool = False,
            fx_map: dict[str, str] | None = None) -> MarketData:
    prices = prices.sort_index().ffill()
    fx = float(prices[fx_ticker].dropna().iloc[-1]) if fx_ticker in prices.columns and prices[fx_ticker].dropna().shape[0] else None
    # AUDUSD=X quotes USD per AUD; we want AUD per USD.
    aud_per_usd = 1.0 / fx if fx else 1.5
    if fx is None:
        log.warning("No FX rate available; assuming 1 USD = 1.50 AUD")
    as_of = prices.index.max()
    fx_map = dict(fx_map or {"USD": fx_ticker})
    aud_per: dict[str, float] = {"USD": aud_per_usd}
    for ccy, t in fx_map.items():
        if t in prices.columns and prices[t].dropna().shape[0]:
            last = float(prices[t].dropna().iloc[-1])
            aud_per[ccy] = 1.0 / last if _quotes_foreign_per_aud(t) else last
        elif ccy != "USD":
            log.warning("No FX rate for %s (%s); holdings in that currency will be left unconverted", ccy, t)
    return MarketData(prices=prices, fx_aud_per_usd=aud_per_usd, as_of=as_of,
                      source_by_ticker=sources, synthetic=synthetic, fx_aud_per=aud_per, fx_tickers=fx_map)
