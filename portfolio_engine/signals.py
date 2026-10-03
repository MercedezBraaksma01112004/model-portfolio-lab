"""Tactical signals and tilts.

For each asset class with a proxy ticker we compute three signals from daily closes:

  trend      price relative to its 200 day moving average, as a fraction
  momentum   12 month return excluding the most recent month (the classic 12-1 measure),
             less the same return on the cash proxy
  volatility ratio of 20 day realised volatility to 1 year realised volatility, minus 1;
             a spike in short term volatility is treated as a risk-off signal

Each signal is clipped to [-1, 1] using the scale in profiles.yaml, then combined with the
signal weights into a score in [-1, 1]. The raw tilt is score * max_tilt_pp. Hysteresis
compares the raw tilt to the previously stored tilt and keeps the old value when the change
is smaller than hysteresis_pp. Finally the tilts are made to sum to zero: the net of the
growth-class tilts is offset against the defensive classes in proportion to their SAA
weights, and every class is clipped so it never goes below zero.

None of this is a forecast. It is a transparent, bounded rule so that the effect of "market
information" on a portfolio is explicit and auditable."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Profiles
from .market_data import MarketData

log = logging.getLogger(__name__)


@dataclass
class ClassSignal:
    asset_class: str
    proxies: list[str]
    trend: float | None
    momentum: float | None
    volatility: float | None
    score: float
    raw_tilt_pp: float
    previous_tilt_pp: float | None
    tilt_pp: float                 # after hysteresis, before rebalancing to zero-sum
    note: str = ""


@dataclass
class TacticalView:
    as_of: str
    signals: dict[str, ClassSignal]
    enabled: bool
    synthetic: bool

    def tilts_for(self, saa: dict[str, float], profiles: Profiles) -> dict[str, float]:
        """Return a zero-sum tilt vector (pp) for a given SAA, clipped so no class goes negative."""
        if not self.enabled:
            return {c: 0.0 for c in saa}
        raw = {c: (self.signals[c].tilt_pp if c in self.signals else 0.0) for c in saa}
        # A class with zero strategic weight is not tilted (no position to scale from).
        raw = {c: (v if saa[c] > 0 else 0.0) for c, v in raw.items()}
        growth = [c for c in profiles.growth_classes if c in saa]
        defensive = [c for c in profiles.defensive_classes if c in saa]
        net_growth = sum(raw[c] for c in growth)
        cap = float(profiles.tactical.get("max_growth_shift_pp", profiles.tactical.get("max_tilt_pp", 5)))
        if abs(net_growth) > cap and net_growth != 0:
            scale = cap / abs(net_growth)
            for c in growth:
                raw[c] *= scale
            net_growth = sum(raw[c] for c in growth)
        # The defensive classes must in total offset the growth shift exactly. Their own
        # signals only move weight between defensive classes; the adjustment that makes the
        # defensive total equal -net_growth is spread in proportion to SAA weight.
        def_total = sum(saa[c] for c in defensive) or 1.0
        tilts = dict(raw)
        def_adjust = -net_growth - sum(raw[c] for c in defensive)
        for c in defensive:
            tilts[c] = raw[c] + def_adjust * saa[c] / def_total
        # Enforce non-negative final weights, then repair any residual within the same kind.
        for _ in range(3):
            for c in tilts:
                tilts[c] = max(tilts[c], -saa[c])
            residual = sum(tilts.values())
            if abs(residual) < 1e-9:
                break
            candidates = [c for c in defensive if saa[c] + tilts[c] - residual >= 0] or \
                         [c for c in saa if saa[c] + tilts[c] - residual >= 0]
            target = max(candidates, key=lambda c: saa[c]) if candidates else max(saa, key=saa.get)
            tilts[target] -= residual
        assert abs(sum(tilts.values())) < 1e-6, tilts
        return {c: round(v, 4) for c, v in tilts.items()}

    def to_dict(self) -> dict:
        return {"as_of": self.as_of, "enabled": self.enabled, "synthetic": self.synthetic,
                "signals": {c: asdict(s) for c, s in self.signals.items()}}


def _clip(x: float | None, scale: float) -> float:
    if x is None or np.isnan(x):
        return 0.0
    return float(np.clip(x / scale, -1.0, 1.0))


def _series(md: MarketData, tickers: list[str]) -> pd.Series | None:
    cols = [t for t in tickers if t in md.prices.columns]
    if not cols:
        return None
    # Equal-weight index of normalised proxies
    px = md.prices[cols].dropna(how="all").ffill()
    norm = px / px.iloc[0]
    return norm.mean(axis=1)


def compute_signals(md: MarketData, profiles: Profiles, state_path: Path) -> TacticalView:
    cfg = profiles.tactical
    enabled = bool(cfg.get("enabled", False))
    previous = _load_state(state_path)
    cash = _series(md, [cfg.get("cash_proxy", "")])
    signals: dict[str, ClassSignal] = {}
    for cls, proxies in cfg.get("proxies", {}).items():
        if not proxies:
            signals[cls] = ClassSignal(cls, [], None, None, None, 0.0, 0.0, previous.get(cls), 0.0, "no proxy: not tilted")
            continue
        s = _series(md, proxies)
        if s is None or len(s) < 260:
            signals[cls] = ClassSignal(cls, proxies, None, None, None, 0.0, 0.0, previous.get(cls), 0.0,
                                       "insufficient price history: not tilted")
            continue
        trend = float(s.iloc[-1] / s.rolling(200).mean().iloc[-1] - 1)
        mom_12_1 = float(s.iloc[-22] / s.iloc[-253] - 1)
        cash_ret = float(cash.iloc[-22] / cash.iloc[-253] - 1) if cash is not None and len(cash) >= 253 else 0.0
        momentum = mom_12_1 - cash_ret
        rets = np.log(s).diff().dropna()
        vol_20 = float(rets.iloc[-20:].std() * np.sqrt(252))
        vol_1y = float(rets.iloc[-252:].std() * np.sqrt(252))
        volatility = (vol_20 / vol_1y - 1) if vol_1y > 0 else 0.0
        w = cfg["signal_weights"]
        score = (w["trend"] * _clip(trend, cfg["trend_scale"])
                 + w["momentum"] * _clip(momentum, cfg["momentum_scale"])
                 - w["volatility"] * max(0.0, _clip(volatility, cfg["volatility_scale"])))
        score = float(np.clip(score, -1, 1))
        raw_tilt = score * cfg["max_tilt_pp"]
        prev = previous.get(cls)
        if prev is not None and abs(raw_tilt - prev) < cfg["hysteresis_pp"]:
            tilt, note = prev, f"held at previous tilt (change {raw_tilt - prev:+.2f}pp under hysteresis)"
        else:
            tilt, note = raw_tilt, "updated"
        signals[cls] = ClassSignal(cls, proxies, trend, momentum, volatility, score, round(raw_tilt, 3), prev,
                                   round(tilt, 3), note)
    view = TacticalView(as_of=str(md.as_of.date()), signals=signals, enabled=enabled, synthetic=md.synthetic)
    return view


def _load_state(path: Path) -> dict[str, float]:
    if path.exists():
        try:
            return json.loads(path.read_text()).get("tilts", {})
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(view: TacticalView, path: Path) -> None:
    if view.synthetic:
        log.info("Not saving tactical state: synthetic data")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"as_of": view.as_of,
                                "tilts": {c: s.tilt_pp for c, s in view.signals.items()}}, indent=2))
