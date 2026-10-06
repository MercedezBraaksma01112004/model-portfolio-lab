"""A live record for each house model.

A notional $100,000 is invested at the model's weights at the close on the day the model was loaded into the site (its
inception, set in config/house_models.yaml), then held without rebalancing and valued at every close in Australian
dollars, with dividends reinvested (the price feed's adjusted closes are total-return prices). It is the record the
model would have produced if it had been bought that day and left alone: no fees, brokerage or tax, and no forecasting.

When the model's holdings or weights change, the record carries on rather than restarting: on that day the portfolio
is sold at its value and bought again at the new weights, and the change is marked. The versions (date and weights)
are kept in data/house_track.json, which the daily build commits, so a change to the model starts a new segment and
never rewrites what the old model did.

Holdings without a daily price of their own follow a stand-in: an unlisted fund or an unpriced listing follows its
listed twin (the universe's twin column, config/stand_ins.csv), and a term deposit or the cash account earns its
configured yield each day. Anything with neither is held flat and named on the page.

The benchmark (`benchmark` in the model, ticker -> weight) is bought on the same day and held the same way."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
START = 100_000.0


def _weights(model: dict) -> dict[str, float]:
    w = {str(h["ticker"]): float(h["weight"]) for h in model.get("holdings") or []}
    tot = sum(w.values()) or 1.0
    return {t: v / tot for t, v in w.items()}


def _hash(w: dict[str, float]) -> str:
    return hashlib.sha1(json.dumps(sorted((t, round(v, 6)) for t, v in w.items())).encode()).hexdigest()[:12]


def _daily_returns(tickers: list[str], md, universe: pd.DataFrame, index: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, str]]:
    """Daily AUD total returns on `index` for each ticker, and how each one was priced."""
    u = universe.drop_duplicates("ticker").set_index("ticker")
    out, how = {}, {}

    full = md.prices.index

    def aud_series(t: str, ccy: str) -> pd.Series | None:
        # Returns are taken on the whole price history and then cut to the record's dates, so a record only a day old
        # still knows which holdings have prices of their own.
        if t not in md.prices.columns:
            return None
        p = md.prices[t].ffill()
        if p.notna().sum() < 2:
            return None
        fx = md.fx_series(ccy)
        if fx is not None:
            p = p * fx.reindex(full).ffill()
        return p.pct_change().reindex(index)

    for t in tickers:
        r = u.loc[t] if t in u.index else None
        ccy = str(r["currency"]) if r is not None else "AUD"
        s = aud_series(t, ccy)
        if s is not None:
            out[t], how[t] = s, "own price"
            continue
        twin = str(r["twin"]) if r is not None and "twin" in u.columns and r["twin"] else ""
        if twin:
            tc = str(u.loc[twin, "currency"]) if twin in u.index else "AUD"
            s = aud_series(twin, tc)
            if s is not None:
                out[t], how[t] = s, f"follows {twin}"
                continue
        if r is not None and str(r["vehicle"]) in ("cash", "td"):
            y = float(r["yield"] or 0) / 100
            days = pd.Series(index.to_series().diff().dt.days.fillna(0).values, index=index)
            out[t], how[t] = (1 + y) ** (days / 365.0) - 1, f"accrues {y * 100:.2f}% a year"
            continue
        out[t], how[t] = pd.Series(0.0, index=index), "no price: held flat"
    return pd.DataFrame(out, index=index).fillna(0.0), how


def _run(segments: list[tuple[pd.Timestamp, dict[str, float]]], rets: pd.DataFrame) -> tuple[pd.Series, dict[str, float]]:
    """Value of a buy-and-hold portfolio, re-bought at each segment's weights on its start date, and each holding's
    dollar contribution."""
    idx = rets.index
    value = pd.Series(index=idx, dtype=float)
    contrib: dict[str, float] = {}
    total = START
    for i, (start, w) in enumerate(segments):
        end = segments[i + 1][0] if i + 1 < len(segments) else None
        days = idx[(idx >= start) & ((idx <= end) if end is not None else True)]
        if not len(days):
            continue
        pos = {t: total * x for t, x in w.items()}
        value.loc[days[0]] = total
        for d in days[1:]:
            for t in pos:
                r = float(rets.at[d, t]) if t in rets.columns else 0.0
                contrib[t] = contrib.get(t, 0.0) + pos[t] * r
                pos[t] *= 1 + r
            total = sum(pos.values())
            value.loc[d] = total
    return value.dropna(), contrib


def track_house_models(profiles, universe: pd.DataFrame, md, state_path: Path, *, today: date | None = None, write: bool = True) -> dict:
    """The record for every house model, for the dashboard. Updates the version log in `state_path` (when `write`)."""
    models = {k: m for k, m in (profiles.house_models or {}).items() if isinstance(m, dict) and m.get("holdings")}
    if not models or md.prices.empty:
        return {}
    today = today or md.as_of.date()
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
    except (OSError, ValueError):
        state = {}
    state.setdefault("models", {})
    out: dict[str, dict] = {}
    idx_all = md.prices.index
    for key, m in models.items():
        w = _weights(m)
        st = state["models"].setdefault(key, {"inception": str(m.get("inception") or today), "versions": []})
        if not st["versions"] or st["versions"][-1]["hash"] != _hash(w):
            st["versions"].append({"from": st["inception"] if not st["versions"] else str(today), "hash": _hash(w),
                                   "weights": {t: round(v * 100, 4) for t, v in w.items()}})
        incep = pd.Timestamp(st["inception"])
        # The record starts at the last close on or before inception.
        start = idx_all[idx_all <= incep].max() if (idx_all <= incep).any() else idx_all[0]
        index = idx_all[idx_all >= start]
        segs = []
        for v in st["versions"]:
            f = pd.Timestamp(v["from"])
            d = index[index <= f].max() if (index <= f).any() else index[0]
            segs.append((d, {t: x / 100 for t, x in v["weights"].items()}))
        tickers = sorted({t for _, ws in segs for t in ws})
        bench = {str(t): float(x) for t, x in (m.get("benchmark") or {}).items()}
        rets, how = _daily_returns(sorted(set(tickers) | set(bench)), md, universe, index)
        value, contrib = _run(segs, rets)
        bvalue = None
        if bench:
            bt = sum(bench.values()) or 1.0
            bvalue, _ = _run([(index[0], {t: x / bt for t, x in bench.items()})], rets)
            if any(not how.get(t, "").startswith("own") for t in bench):
                bvalue = None   # a benchmark without its own prices is not a benchmark
        n = len(value)

        def period(days: int | None, s: pd.Series | None) -> float | None:
            if s is None or len(s) < 2:
                return None
            if days is None:
                return round(float(s.iloc[-1] / s.iloc[0] - 1) * 100, 2)
            cut = s.index[-1] - pd.Timedelta(days=days)
            if s.index[0] > cut:
                return None
            base = s[s.index <= cut].iloc[-1]
            return round(float(s.iloc[-1] / base - 1) * 100, 2)

        periods = [("Since inception", None), ("1 week", 7), ("1 month", 31), ("3 months", 92), ("1 year", 365)]
        peak = value.cummax()
        mdd = float(((value / peak) - 1).min() * 100) if n else 0.0
        names = universe.drop_duplicates("ticker").set_index("ticker")["name"].to_dict()
        cur = st["versions"][-1]["weights"]
        contrib_rows = sorted(({"ticker": t, "name": str(names.get(t, t)), "pts": round(float(c) / START * 100, 3), "weight": cur.get(t),
                                "priced": how.get(t, "")} for t, c in contrib.items()), key=lambda r: -r["pts"])
        out[key] = {
            "label": m.get("label", key), "inception": st["inception"], "start": str(index[0].date()), "as_of": str(value.index[-1].date()) if n else str(start.date()),
            "days": max(0, n - 1), "dates": [d.strftime("%Y-%m-%d") for d in value.index],
            "model": [round(float(v) / START * 100, 3) for v in value.values],
            "bench": [round(float(v) / START * 100, 3) for v in bvalue.reindex(value.index).ffill().values] if bvalue is not None else None,
            "bench_label": m.get("benchmark_label") or " and ".join(bench) if bench else "",
            "periods": [{"label": lbl, "model": period(dd, value), "bench": period(dd, bvalue) if bvalue is not None else None} for lbl, dd in periods],
            "max_drawdown_pct": round(mdd, 2),
            "changes": [v["from"] for v in st["versions"][1:]],
            "contrib": contrib_rows,
            "stand_ins": {t: h for t, h in how.items() if not h.startswith("own") and t in tickers},
        }
    if write:
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, indent=1))
        except OSError as e:
            log.warning("Could not save the house model record: %s", e)
    return out
