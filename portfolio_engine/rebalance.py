"""Drift analysis and rebalance trade lists.

Given a current holdings file (ticker plus units, or ticker plus value) and a target
portfolio built for the same balance, this module reports asset class drift against the
profile's tolerance band, holding-level drift against a relative tolerance, and a trade list
that moves the account back to target while ignoring trades below the minimum size."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .builder import Portfolio
from .config import Profiles, Settings
from .market_data import MarketData


@dataclass
class RebalanceReport:
    balance: float
    class_drift: pd.DataFrame
    holding_drift: pd.DataFrame
    trades: pd.DataFrame
    flags: list[str]


def load_current_holdings(path: str, universe: pd.DataFrame, md: MarketData, manual: dict[str, float]) -> pd.DataFrame:
    """Accepts columns: ticker, and either units or value. Returns ticker, units, value, price_aud."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "ticker" not in df.columns:
        raise ValueError("holdings file needs a 'ticker' column")
    uni = universe.set_index("ticker")
    rows = []
    for r in df.itertuples():
        t = str(r.ticker).strip()
        ccy = uni.loc[t, "currency"] if t in uni.index else "AUD"
        price = md.latest_aud(t, ccy)
        if price is None:
            price = manual.get(t)
        units = getattr(r, "units", None)
        value = getattr(r, "value", None)
        if pd.notna(units) if units is not None else False:
            if price is None:
                raise ValueError(f"No price for {t}; supply 'value' instead of 'units'")
            value = float(units) * price
        elif value is not None and pd.notna(value):
            value = float(value)
            units = value / price if price else None
        else:
            raise ValueError(f"Row for {t} needs units or value")
        rows.append({"ticker": t, "units": units, "value": value, "price_aud": price,
                     "asset_class": uni.loc[t, "asset_class"] if t in uni.index else "unclassified",
                     "name": uni.loc[t, "name"] if t in uni.index else t})
    return pd.DataFrame(rows)


def analyse(settings: Settings, profiles: Profiles, current: pd.DataFrame, target: Portfolio) -> RebalanceReport:
    balance = float(current["value"].sum())
    flags: list[str] = []
    tol_class = float(profiles.risk_profiles[target.profile_used]["tolerance_pp"])
    tol_rel = float(settings.rebalance["holding_tolerance_relative"])
    min_trade = float(settings.rebalance["min_trade_dollars"])

    cur_cls = current.groupby("asset_class")["value"].sum() / balance * 100
    tgt_cls = pd.Series(target.class_weights())
    classes = sorted(set(cur_cls.index) | set(tgt_cls.index))
    class_drift = pd.DataFrame({
        "current_pct": [cur_cls.get(c, 0.0) for c in classes],
        "target_pct": [tgt_cls.get(c, 0.0) for c in classes],
    }, index=classes)
    class_drift["drift_pp"] = class_drift["current_pct"] - class_drift["target_pct"]
    class_drift["outside_band"] = class_drift["drift_pp"].abs() > tol_class
    for c, r in class_drift.iterrows():
        if r["outside_band"]:
            flags.append(f"{c}: {r['current_pct']:.1f}% vs target {r['target_pct']:.1f}% (band ±{tol_class}pp)")

    tgt_h = pd.DataFrame([{"ticker": l.ticker, "name": l.name, "asset_class": l.asset_class,
                           "target_pct": l.weight_pct, "price_aud": l.price_aud} for l in target.lines]).set_index("ticker")
    cur_h = current.set_index("ticker")
    tickers = sorted(set(tgt_h.index) | set(cur_h.index))
    hd = pd.DataFrame(index=tickers)
    hd["name"] = [tgt_h["name"].get(t, cur_h["name"].get(t, t)) for t in tickers]
    hd["asset_class"] = [tgt_h["asset_class"].get(t, cur_h["asset_class"].get(t, "")) for t in tickers]
    hd["current_value"] = [float(cur_h["value"].get(t, 0.0)) for t in tickers]
    hd["current_pct"] = hd["current_value"] / balance * 100
    hd["target_pct"] = [float(tgt_h["target_pct"].get(t, 0.0)) for t in tickers]
    hd["target_value"] = hd["target_pct"] / 100 * balance
    hd["drift_pp"] = hd["current_pct"] - hd["target_pct"]
    hd["flag"] = ""
    for t, r in hd.iterrows():
        if r["target_pct"] == 0 and r["current_value"] > 0:
            hd.loc[t, "flag"] = "not in target: sell"
        elif r["current_pct"] == 0 and r["target_pct"] > 0:
            hd.loc[t, "flag"] = "missing: buy"
        elif r["target_pct"] > 0 and abs(r["drift_pp"]) / r["target_pct"] > tol_rel:
            hd.loc[t, "flag"] = "outside relative band"

    trades = hd.copy()
    trades["trade_value"] = trades["target_value"] - trades["current_value"]
    price = pd.Series({t: (tgt_h["price_aud"].get(t) if t in tgt_h.index else cur_h["price_aud"].get(t)) for t in tickers})
    trades["price_aud"] = price
    trades["units"] = (trades["trade_value"] / trades["price_aud"]).where(trades["price_aud"] > 0)
    trades["action"] = trades["trade_value"].apply(lambda v: "BUY" if v > 0 else "SELL" if v < 0 else "")
    trades = trades[trades["trade_value"].abs() >= min_trade]
    trades = trades[["name", "asset_class", "action", "trade_value", "units", "price_aud", "current_pct", "target_pct"]]
    trades = trades.sort_values("trade_value")
    return RebalanceReport(balance=balance, class_drift=class_drift, holding_drift=hd, trades=trades, flags=flags)
