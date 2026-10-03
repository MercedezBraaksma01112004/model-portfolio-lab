"""Holding review: a transparent screen over the active universe and the watchlist.

Every active holding collects "strikes" and every watchlist name collects "merits", each with
a written reason. A holding with at least `strikes_to_remove` strikes becomes a removal
candidate; a watchlist name with at least `add_requirements` merits becomes an add candidate.
Nothing changes unless `apply` is called (or review.auto_apply is true), and even then at
most `max_changes_per_run` changes are made, respecting the cooling-off window.

Strikes (removal): price below its 200 day average; 12-1 month momentum more than
`momentum_lag_pp` behind the asset class index ETF; worst one-year drawdown beyond
`drawdown_limit_pct`; analyst consensus Underperform or Sell; market cap below the minimum.
Merits (addition): above 200 day average; momentum ahead of the class index; consensus Buy or
Strong Buy with at least three analysts; market cap above the minimum; one-year volatility at
or below the median of active holdings in the class.

This is a discipline, not a forecast. Price-based screens are late by construction."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .config import Settings
from .market_data import MarketData
from .research import HoldingResearch


@dataclass
class ReviewItem:
    ticker: str
    name: str
    asset_class: str
    status: str                  # active or watchlist
    action: str                  # "remove candidate", "add candidate", "keep", "watch"
    score: int
    reasons: list[str] = field(default_factory=list)
    positives: list[str] = field(default_factory=list)
    blocked_until: str = ""      # cooling-off


def _class_index_momentum(settings: Settings, research: dict[str, HoldingResearch], asset_class: str) -> float | None:
    chain = settings.raw.get("returns", {}).get("long_history_proxies", {}).get(asset_class) or []
    chain = [chain] if isinstance(chain, str) else chain
    for proxy in chain:
        hr = research.get(proxy)
        if hr and getattr(hr, "momentum_12_1_pct", None) is not None:
            return hr.momentum_12_1_pct
    return None


def _log_path(settings: Settings) -> Path:
    return settings.root / "data" / "review_log.csv"


def _recent_changes(settings: Settings, days: int) -> dict[str, tuple[str, date]]:
    p = _log_path(settings)
    out: dict[str, tuple[str, date]] = {}
    if not p.exists():
        return out
    cutoff = date.today() - timedelta(days=days)
    with open(p) as f:
        for row in csv.DictReader(f):
            d = date.fromisoformat(row["date"])
            if d >= cutoff:
                out[row["ticker"]] = (row["action"], d)
    return out


def run_review(settings: Settings, universe_all: pd.DataFrame, research: dict[str, HoldingResearch], md: MarketData) -> list[ReviewItem]:
    cfg = settings.raw.get("review", {})
    min_cap = float(cfg.get("min_market_cap_aud", 0))
    lag = float(cfg.get("momentum_lag_pp", 15))
    dd_limit = float(cfg.get("drawdown_limit_pct", -35))
    strikes_needed = int(cfg.get("strikes_to_remove", 3))
    merits_needed = int(cfg.get("add_requirements", 3))
    recent = _recent_changes(settings, int(cfg.get("cooling_off_days", 90)))
    fx = md.fx_aud_per_usd
    # Median volatility of active holdings per class, for the "not unusually volatile" merit.
    vol_by_class: dict[str, float] = {}
    for c, grp in universe_all[universe_all["status"] == "active"].groupby("asset_class"):
        vols = [research[t].volatility_1y_pct for t in grp["ticker"] if t in research and research[t].volatility_1y_pct is not None]
        if vols:
            vol_by_class[c] = float(pd.Series(vols).median())
    items: list[ReviewItem] = []
    for r in universe_all.itertuples():
        if r.vehicle in {"cash", "td"} or r.ticker not in research:
            continue
        hr = research[r.ticker]
        if hr.price is None:
            continue
        idx_mom = _class_index_momentum(settings, research, r.asset_class)
        cap_aud = (hr.market_cap or 0) * (md.fx_aud_per.get(str(hr.price_currency).upper(), fx if hr.price_currency == "USD" else 1.0))
        is_fund = r.vehicle in {"etf", "lic", "lit", "fund", "hybrid"}
        strikes, merits = [], []
        # Trend
        if hr.above_200dma is False:
            strikes.append("below its 200 day average")
        elif hr.above_200dma:
            merits.append("above its 200 day average")
        # Momentum against the class index
        if hr.momentum_12_1_pct is not None and idx_mom is not None:
            gap = hr.momentum_12_1_pct - idx_mom
            if gap < -lag:
                strikes.append(f"12-1 month momentum {abs(gap):.0f} points behind its asset class index")
            elif gap > 0:
                merits.append(f"12-1 month momentum {gap:.0f} points ahead of its asset class index")
        # Drawdown
        if hr.max_drawdown_1y_pct is not None and hr.max_drawdown_1y_pct < dd_limit:
            strikes.append(f"fell {abs(hr.max_drawdown_1y_pct):.0f}% from its one-year high")
        # Consensus (direct shares only; funds have none)
        if not is_fund and hr.analysts and hr.analysts >= 3 and hr.consensus_mean is not None:
            if hr.consensus_mean >= 3.5:
                strikes.append(f"analyst consensus {hr.consensus_label} ({hr.consensus_mean:.1f}, {hr.analysts} analysts)")
            elif hr.consensus_mean < 2.5:
                merits.append(f"analyst consensus {hr.consensus_label} ({hr.analysts} analysts)")
        # Size and liquidity
        if not is_fund and cap_aud:
            if cap_aud < min_cap:
                strikes.append(f"market cap A${cap_aud / 1e9:.1f} bn below the A${min_cap / 1e9:.0f} bn minimum")
            else:
                merits.append(f"market cap A${cap_aud / 1e9:.1f} bn")
        # Volatility relative to class
        med = vol_by_class.get(r.asset_class)
        if hr.volatility_1y_pct is not None and med is not None and hr.volatility_1y_pct <= med:
            merits.append(f"volatility {hr.volatility_1y_pct:.0f}% at or below the class median {med:.0f}%")
        blocked = ""
        if r.ticker in recent:
            act, d = recent[r.ticker]
            blocked = (d + timedelta(days=int(cfg.get("cooling_off_days", 90)))).isoformat()
        if r.status == "active":
            action = "remove candidate" if len(strikes) >= strikes_needed else "keep"
            if action == "remove candidate" and blocked and recent[r.ticker][0] == "add":
                action = "keep"
                strikes.append(f"(removal blocked until {blocked}: added recently)")
            items.append(ReviewItem(r.ticker, r.name, r.asset_class, r.status, action, len(strikes), strikes, merits, blocked))
        else:
            action = "add candidate" if len(merits) >= merits_needed and not strikes else "watch"
            if action == "add candidate" and blocked and recent[r.ticker][0] == "remove":
                action = "watch"
                strikes.append(f"(addition blocked until {blocked}: removed recently)")
            items.append(ReviewItem(r.ticker, r.name, r.asset_class, r.status, action, len(merits), strikes, merits, blocked))
    order = {"remove candidate": 0, "add candidate": 1, "keep": 2, "watch": 3}
    items.sort(key=lambda i: (order[i.action], -i.score, i.ticker))
    return items


def apply_review(settings: Settings, items: list[ReviewItem], universe_path: Path) -> list[str]:
    """Write up to max_changes_per_run changes to universe.csv and append to the review log."""
    cfg = settings.raw.get("review", {})
    limit = int(cfg.get("max_changes_per_run", 2))
    df = pd.read_csv(universe_path, dtype={"notes": str}).fillna({"notes": ""})
    if "status" not in df.columns:
        df["status"] = "active"
    changes: list[str] = []
    today = date.today().isoformat()
    log_rows = []
    for it in items:
        if len(changes) >= limit:
            break
        if it.action == "remove candidate":
            df.loc[df["ticker"] == it.ticker, "status"] = "watchlist"
            df.loc[df["ticker"] == it.ticker, "notes"] = f"Moved to watchlist {today} by review: " + "; ".join(it.reasons)
            changes.append(f"removed {it.ticker} ({it.name}): " + "; ".join(it.reasons))
            log_rows.append({"date": today, "ticker": it.ticker, "action": "remove", "reasons": "; ".join(it.reasons)})
        elif it.action == "add candidate":
            df.loc[df["ticker"] == it.ticker, "status"] = "active"
            df.loc[df["ticker"] == it.ticker, "notes"] = f"Added {today} by review: " + "; ".join(it.positives)
            changes.append(f"added {it.ticker} ({it.name}): " + "; ".join(it.positives))
            log_rows.append({"date": today, "ticker": it.ticker, "action": "add", "reasons": "; ".join(it.positives)})
    if changes:
        df.to_csv(universe_path, index=False)
        p = _log_path(settings)
        new = not p.exists()
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "ticker", "action", "reasons"])
            if new:
                w.writeheader()
            w.writerows(log_rows)
    return changes


def review_to_records(items: list[ReviewItem]) -> list[dict]:
    return [asdict(i) for i in items]
