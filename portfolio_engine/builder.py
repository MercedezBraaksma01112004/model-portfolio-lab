"""Portfolio construction.

A portfolio is defined by (risk profile, life stage, balance). The build runs in this order:

1. Apply the life stage cap to the requested risk profile.
2. Start from the profile's strategic asset allocation and add the tactical tilts.
3. Apply life stage adjustments: home bias (international to Australian equities) and the
   cash floor.
4. Select holdings per asset class for the balance tier (eligibility by vehicle and
   min_tier, number of names scaled to the class weight, fallback ETFs only where needed).
5. Weight holdings within each class from the model's weight hints, scored for income and
   franking according to the life stage, capped at each holding's max_weight.
6. Convert to dollars, enforce minimum holding sizes, round listed holdings to whole units
   and sweep the residual to cash.
7. Compute metrics: fees, income, growth/defensive split, realised volatility from the
   covariance of the holdings' returns (not a weighted average of individual volatilities).
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from .config import Profiles, Settings
from .market_data import MarketData
from .signals import TacticalView

log = logging.getLogger(__name__)

GROWTH_FALLBACK_CLASS = "aus_equity"
DEFENSIVE_FALLBACK_CLASS = "cash"


@dataclass
class Line:
    ticker: str
    name: str
    asset_class: str
    vehicle: str
    role: str
    currency: str
    source: str
    weight_pct: float
    dollars: float
    price_aud: float | None
    units: float | None
    mer_pct: float
    yield_pct: float
    franking_pct: float
    priced_from: str
    consensus_label: str = ""
    consensus_mean: float | None = None
    analysts: int | None = None
    consensus_multiplier: float = 1.0
    yield_source: str = "config"
    weight_hint: float = 0.0
    sector: str = ""
    region: str = ""
    style: str = ""
    fit_score: float = 0.0


@dataclass
class Portfolio:
    id: str
    profile_requested: str
    profile_used: str
    life_stage: str
    tier: str
    balance: float
    saa: dict[str, float]
    tilts: dict[str, float]
    target_class_weights: dict[str, float]
    lines: list[Line]
    metrics: dict[str, float]
    warnings: list[str] = field(default_factory=list)
    as_of: str = ""
    synthetic: bool = False
    implementation: str = "direct"          # "direct" (holdings chosen one by one) or "sma" (one managed portfolio)
    sma: dict = field(default_factory=dict)  # chosen managed portfolio and shortlist when implementation == "sma"
    esg: dict = field(default_factory=dict)  # {"screened": True, "changes": [...]} when built under the ESG screen

    def class_weights(self) -> dict[str, float]:
        if self.implementation == "sma":
            return dict(self.target_class_weights)
        out: dict[str, float] = {}
        for ln in self.lines:
            out[ln.asset_class] = out.get(ln.asset_class, 0.0) + ln.weight_pct
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["class_weights"] = self.class_weights()
        return d


# ---------------------------------------------------------------- allocation steps

def strategic_plus_tactical(profiles: Profiles, profile: str, view: TacticalView | None) -> tuple[dict, dict, dict]:
    saa = {c: float(v) for c, v in profiles.risk_profiles[profile]["saa"].items()}
    tilts = view.tilts_for(saa, profiles) if view is not None else {c: 0.0 for c in saa}
    target = {c: saa[c] + tilts[c] for c in saa}
    return saa, tilts, target


def apply_life_stage(profiles: Profiles, target: dict[str, float], life_stage: str, warnings: list[str]) -> dict[str, float]:
    ls = profiles.life_stages[life_stage]
    t = dict(target)
    # Home bias: shift from international to Australian equities, but never strip more than a set share
    # of the international sleeve, so a conservative pension still holds some overseas shares.
    max_share = float(ls.get("home_bias_max_share_of_intl", 0.6))
    shift = min(float(ls.get("home_bias_pp", 0)), t.get("intl_equity", 0.0) * max_share)
    if shift > 0:
        t["intl_equity"] -= shift
        t["aus_equity"] += shift
    # Cash floor: fund from growth classes pro rata.
    floor = float(ls.get("cash_floor_pp", 0))
    if t.get("cash", 0.0) < floor:
        need = floor - t["cash"]
        growth_total = sum(t[c] for c in profiles.growth_classes)
        if growth_total <= 0:
            warnings.append("Cash floor could not be funded: no growth allocation")
        else:
            for c in profiles.growth_classes:
                t[c] -= need * t[c] / growth_total
            t["cash"] = floor
    total = sum(t.values())
    if abs(total - 100) > 1e-6:
        raise AssertionError(f"Class weights sum to {total}")
    return t


def _eligible(universe: pd.DataFrame, profiles: Profiles, asset_class: str, tier: str, priced: set[str],
              ls: dict | None = None) -> pd.DataFrame:
    tcfg = profiles.balance_tiers[tier]
    df = universe[(universe["asset_class"] == asset_class)
                  & (universe["min_tier_order"] <= tcfg["order"])
                  & (universe["vehicle"].isin(tcfg["allowed_vehicles"]))
                  & (universe["ticker"].isin(priced))].copy()
    # Drawdown stages: skip equity holdings whose grossed-up yield is below the stage minimum,
    # as long as something in the class still qualifies; rank income vehicles first if asked.
    if ls and asset_class in profiles.growth_classes and asset_class != "alternatives":
        min_y = float(ls.get("min_equity_yield_pct", 0) or 0)
        if min_y > 0:
            gy = grossed_up_yield(df["yield"].astype(float), df["franking"].astype(float))
            keep = df[gy >= min_y]
            if len(keep):
                df = keep
        if ls.get("prefer_income_vehicles"):
            df = df.copy()
            df["_income_rank"] = (~df["vehicle"].isin(["lic", "etf", "fund"])).astype(int)
            df["priority"] = df["priority"].astype(float) + 0.5 * df["_income_rank"] * (df["role"] == "satellite").astype(int)
    if "_excluded" in df.columns:
        ok = df[df["_excluded"] == ""]
        if len(ok):
            df = ok
    model = df[df["role"] != "fallback"]
    fallback = df[df["role"] == "fallback"]
    if tier == "starter" or model.empty:
        # Starter balances get the cheapest broad building block first; otherwise the model holdings.
        chosen = pd.concat([fallback, model]) if tier == "starter" else fallback
    else:
        chosen = model
    if "_fit" in chosen.columns:
        # Index cores (priority 1) stay in front; everything else ranks on how well it fits the profile today.
        chosen = chosen.assign(_order=_priority_offset(chosen["priority"]) - chosen["_fit"])
        return chosen.sort_values(["_order", "weight_hint"], ascending=[True, False]).drop(columns="_order")
    return chosen.sort_values(["priority", "weight_hint"], ascending=[True, False])


def fill_sector_region(universe: pd.DataFrame, research: dict | None) -> pd.DataFrame:
    """Fill blank sector and region columns: single companies from the research feed's sector, funds as
    diversified, region from the listing. Values already in universe.csv are kept."""
    from .config import YAHOO_SECTORS, guess_region
    df = universe.copy()
    for col in ("sector", "region"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("")
    research = research or {}
    for i, r in df.iterrows():
        if not r["sector"]:
            if r["vehicle"] == "direct":
                sec = YAHOO_SECTORS.get(getattr(research.get(r["ticker"]), "sector", "") or "", "")
                df.loc[i, "sector"] = sec or "Other"
            elif r["vehicle"] == "hybrid":
                df.loc[i, "sector"] = "Hybrids"
            elif r["vehicle"] == "cash" or r["asset_class"] == "cash":
                df.loc[i, "sector"] = "Cash"
            else:
                df.loc[i, "sector"] = "Diversified fund"
        if not r["region"]:
            df.loc[i, "region"] = guess_region(r["ticker"], r["name"])
    return df


GROWTH_SECTORS = {"Technology", "Healthcare", "Communication", "Small companies", "Covered call income"}
INCOME_SECTORS = {"Dividend income", "Covered call income", "Hybrids", "Bank subordinated debt", "High yield credit", "Private debt", "Securitised credit", "Floating rate", "Bank floating rate", "Resource royalties"}


def derive_style(row: pd.Series, r) -> str:
    """growth, income, quality or defensive: what job the holding does, from its sector, yield and record."""
    if str(row.get("style", "") or "").strip():
        return str(row["style"]).strip().lower()
    cls, sec, veh = row["asset_class"], str(row.get("sector", "") or ""), row["vehicle"]
    if cls in ("fixed_income", "cash"):
        return "defensive"
    if cls == "credit":
        return "income"
    if cls == "alternatives" and veh != "direct":
        return "quality"   # gold, silver, private equity vehicles: diversifiers rather than growth or income bets
    yld = getattr(r, "dividend_yield_pct", None)
    yld = float(row["yield"]) if yld is None else float(yld)
    r5 = getattr(r, "return_5y_pct_pa", None)
    if sec in INCOME_SECTORS or yld >= 4.5:
        return "income"
    if veh != "direct" and sec in ("Diversified fund", "Diversified fund (hedged)", "Quality"):
        return "quality"
    # Growth means the business is growing, not that the share price has run: technology, healthcare,
    # communication, consumer growth and small companies. A rallying bank, refiner or steelmaker is quality.
    if sec in GROWTH_SECTORS and yld < 3.0:
        return "growth"
    if sec == "Consumer discretionary" and yld < 1.5 and (r5 is None or r5 >= 12):
        return "growth"
    return "quality"


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _priority_offset(priority: pd.Series) -> pd.Series:
    """Priority is a prior, fit is the evidence: index cores (1) come first, hand-picked names (2) start 0.4 ahead of
    screened names (3), which start 0.3 ahead of the long tail (4+). A better fit can still overturn it."""
    return priority.astype(float).map(lambda p: 0.0 if p <= 1 else 0.6 if p <= 2 else 1.0 if p <= 3 else 1.3)


def fit_scores(universe: pd.DataFrame, research: dict, profile: str, ls: dict, cfg: dict) -> tuple[pd.Series, pd.Series, pd.Series]:
    """How well each holding fits the risk profile, from its own record: trend, momentum, 3/5/10 year returns,
    volatility, analyst consensus, yield and style. Returns (score, style, excluded-reason) per universe row.
    Weights per profile come from profiles.yaml (`selection.weights`); the rules are deliberately simple so
    any choice can be traced to the numbers on the holding's fact sheet."""
    w = dict((cfg.get("weights") or {}).get(profile) or cfg.get("default_weights") or {})
    inc_pref = float(ls.get("income_preference", 0) or 0)
    w["yield"] = float(w.get("yield", 0)) + 0.3 * inc_pref
    cons_map = {"Strong Buy": 1.0, "Buy": 0.5, "Hold": 0.0, "Underperform": -0.6, "Sell": -1.0}
    scores, styles, excl = [], [], []
    rules = cfg.get("rules") or {}
    for _, row in universe.iterrows():
        r = research.get(row["ticker"])
        style = derive_style(row, r)
        g = lambda k: getattr(r, k, None) if r is not None else None
        mom, r3, r5, r10, vol = g("momentum_12_1_pct"), g("return_3y_pct_pa"), g("return_5y_pct_pa"), g("return_10y_pct_pa"), g("volatility_1y_pct")
        above = g("above_200dma")
        yld = g("dividend_yield_pct")
        yld = float(row["yield"]) if yld is None else float(yld)
        gy = yld * (1 + FRANKING_GROSS_UP * float(row["franking"]) / 100.0)
        parts = {
            "trend": 0.0 if above is None else (1.0 if above else -1.0),
            "momentum": 0.0 if mom is None else _clip(mom / 30.0),
            "r3": 0.0 if r3 is None else _clip(r3 / 20.0),
            "r5": 0.0 if r5 is None else _clip(r5 / 15.0),
            "r10": 0.0 if r10 is None else _clip(r10 / 12.0),
            "low_vol": 0.0 if vol is None else _clip((30.0 - vol) / 20.0),
            "consensus": cons_map.get(g("consensus_label") or "", 0.0),
            "yield": _clip(gy / 5.0, 0.0, 1.2),
        }
        score = sum(float(w.get(k, 0)) * v for k, v in parts.items())
        score += float((w.get("style") or {}).get(style, 0))
        reason = ""
        if row["vehicle"] == "direct":
            if (g("consensus_label") == "Sell") and rules.get("exclude_sell_consensus", True):
                reason = "analyst consensus Sell"
            if profile in (rules.get("derated_excluded_profiles") or []) and r3 is not None and r5 is not None and r3 < 0 and r5 < 0:
                reason = f"down over 3 and 5 years ({r3:+.0f}% and {r5:+.0f}% a year): not a growth holding"
            if profile in (rules.get("volatile_excluded_profiles") or []) and vol is not None and vol > float(rules.get("max_volatility_pct", 45)):
                reason = f"too volatile for this profile (±{vol:.0f}% a year)"
        scores.append(score); styles.append(style); excl.append(reason)
    return pd.Series(scores, index=universe.index), pd.Series(styles, index=universe.index), pd.Series(excl, index=universe.index)


def _pick_diverse(elig: pd.DataFrame, n: int, tier: str, cfg: dict, warnings: list[str], asset_class: str) -> pd.DataFrame:
    """Take the first `n` eligible holdings in priority order, but skip a single company when its sector already has
    the tier's quota in this class, or when its country would hold more than the allowed share of the class's single
    companies. Caps are relaxed (region first, then sector) only if they would leave the class short."""
    if not cfg.get("enabled", True) or n >= len(elig):
        return elig.head(n).copy()
    per_sector = int((cfg.get("max_direct_per_sector") or {}).get(tier, 99))
    region_share = float(cfg.get("max_region_share_of_direct", 1.0)) if asset_class in (cfg.get("region_rule_classes") or ["intl_equity"]) else 1.0
    # Spread first, then rank: the first name from each sector (for funds, each sector and region) comes before any
    # second name from a sector already represented, so two banks or four overlapping world index funds are not
    # chosen ahead of a healthcare or industrial name the model also holds.
    if cfg.get("spread_sectors_first", True):
        # Spread only among candidates that fit the profile: the top pool (twice the slots wanted) is spread
        # across sectors; the rest queue behind it in fit order, so an unrepresented sector does not pull in a
        # poor fit just to tick a box.
        if "_fit" in elig.columns:
            pool_n = max(n * 2, 4)
            elig = pd.concat([elig.head(pool_n).assign(_pool=0), elig.iloc[pool_n:].assign(_pool=1)])
        seen: dict[tuple, int] = {}
        ranks = []
        for _, r in elig.iterrows():
            key = (str(r.get("sector", "")),) if r["vehicle"] == "direct" else (str(r.get("sector", "")), str(r.get("region", "")))
            ranks.append(seen.get(key, 0))
            seen[key] = seen.get(key, 0) + 1
        if "_fit" in elig.columns:
            elig = elig.assign(_rank=ranks, _order=_priority_offset(elig["priority"]) - elig["_fit"]).sort_values(["_pool", "_rank", "_order", "weight_hint"], ascending=[True, True, True, False]).drop(columns=["_rank", "_order", "_pool"])
        else:
            elig = elig.assign(_rank=ranks).sort_values(["_rank", "priority", "weight_hint"], ascending=[True, True, False]).drop(columns="_rank")

    def attempt(sector_cap: int, region_cap: float) -> list:
        picked, sectors, regions = [], {}, {}
        for idx, r in elig.iterrows():
            direct = r["vehicle"] == "direct"
            sec, reg = str(r.get("sector", "")), str(r.get("region", ""))
            if direct and sectors.get(sec, 0) >= sector_cap:
                continue
            if direct and regions.get(reg, 0) + 1 > max(1, math.ceil(region_cap * n)):
                continue
            picked.append(idx)
            if direct:
                sectors[sec] = sectors.get(sec, 0) + 1
                regions[reg] = regions.get(reg, 0) + 1
            if len(picked) >= n:
                break
        return picked

    picked = attempt(per_sector, region_share)
    if len(picked) < n:
        picked = attempt(per_sector, 1.0)
        if len(picked) < n:
            picked = attempt(99, 1.0)
        else:
            warnings.append(f"{asset_class}: country spread rule relaxed to fill {n} holdings")
    return elig.loc[picked].copy()


def select_holdings(universe: pd.DataFrame, profiles: Profiles, target: dict[str, float], tier: str,
                    priced: set[str], warnings: list[str], ls: dict | None = None) -> dict[str, pd.DataFrame]:
    tcfg = profiles.balance_tiers[tier]
    max_holdings = int(tcfg["max_holdings"])
    max_per_class = int(tcfg["max_per_class"])
    dcfg = getattr(profiles, "diversification", {}) or {}
    active = {c: w for c, w in target.items() if w > 0}
    # Number of names per class scales with class weight, at least one, capped per class.
    caps = {c: max(1, min(max_per_class, round(max_holdings * w / 100))) for c, w in active.items()}
    # Trim if the total exceeds max_holdings.
    while sum(caps.values()) > max_holdings:
        c = max(caps, key=lambda k: (caps[k], active[k]))
        if caps[c] <= 1:
            break
        caps[c] -= 1
    selection: dict[str, pd.DataFrame] = {}
    for c in active:
        elig = _eligible(universe, profiles, c, tier, priced, ls)
        if elig.empty:
            warnings.append(f"No eligible holding for {c} at tier {tier}; weight moved to fallback class")
            continue
        n = caps[c]
        chosen = _pick_diverse(elig, n, tier, dcfg, warnings, c)
        # Add names until the selected holdings' max_weight caps can carry the class weight.
        while n < len(elig) and chosen["max_weight"].sum() < active[c] and sum(len(v) for v in selection.values()) + n < max_holdings:
            n += 1
            chosen = _pick_diverse(elig, n, tier, dcfg, warnings, c)
        selection[c] = chosen
    return selection


def consensus_multiplier(mean: float | None, analysts: int | None, cfg: dict) -> float:
    """Bounded scaling: Strong Buy (1) -> 1 + k, neutral (3) -> 1, Sell (5) -> 1 - k."""
    k = float(cfg.get("consensus_weighting", 0.0))
    if not k or mean is None or not analysts or analysts < int(cfg.get("min_analysts", 3)):
        return 1.0
    return float(1 + k * (3.0 - mean) / 2.0)


FRANKING_GROSS_UP = 30.0 / 70.0   # $1 of fully franked dividend carries $0.4286 of franking credit at the 30% company rate


def grossed_up_yield(yield_pct, franking_pct):
    return yield_pct * (1 + FRANKING_GROSS_UP * franking_pct / 100.0)


def weight_within_class(sel: pd.DataFrame, class_weight: float, ls: dict, warnings: list[str],
                        multipliers: pd.Series | None = None, dcfg: dict | None = None) -> pd.Series:
    """Weights in percent of the whole portfolio for the holdings in one class. Income scoring uses
    the grossed-up yield so a franked dividend counts for more than an unfranked one. Single companies
    are then held to the diversification rules: a cap per holding and a cap per sector."""
    dcfg = dcfg or {}
    inc = float(ls.get("income_preference", 0))
    frk = float(ls.get("franking_preference", 0))
    hint = sel["weight_hint"].astype(float).clip(lower=0)
    if hint.sum() <= 0:
        hint = pd.Series(1.0, index=sel.index)
    gy = grossed_up_yield(sel["yield"].astype(float), sel["franking"].astype(float))
    mean_gy = float(gy.mean()) if len(sel) else 0.0
    score = hint * (1 + inc * (gy - mean_gy) / max(mean_gy, 1.0)) \
                 * (1 + frk * 0.5 * sel["franking"] / 100.0)
    if multipliers is not None:
        score = score * multipliers.reindex(sel.index).fillna(1.0)
    score = score.clip(lower=0.05 * hint.max())
    w = score / score.sum() * class_weight
    # Cap at max_weight and redistribute iteratively. A class with one holding carries its whole weight.
    cap = sel["max_weight"].astype(float)
    if dcfg.get("enabled", True) and dcfg.get("max_single_holding_pct"):
        direct = (sel["vehicle"] == "direct")
        cap = cap.where(~direct, cap.clip(upper=float(dcfg["max_single_holding_pct"])))
    if len(sel) == 1:
        return w
    if cap.sum() < class_weight:
        warnings.append(f"{sel['asset_class'].iloc[0]}: max_weight caps total {cap.sum():.0f}pp but class needs {class_weight:.1f}pp; caps scaled up")
        cap = cap * class_weight / cap.sum()
    for _ in range(20):
        over = w > cap
        if not over.any():
            break
        excess = float((w[over] - cap[over]).sum())
        w[over] = cap[over]
        room = ~over
        if not room.any():
            warnings.append(f"All holdings in {sel['asset_class'].iloc[0]} at max_weight; {excess:.2f}pp unallocated")
            break
        w[room] += excess * w[room] / w[room].sum()
    return _apply_sector_cap(sel, w, cap, class_weight, dcfg, warnings)


def _apply_sector_cap(sel: pd.DataFrame, w: pd.Series, cap: pd.Series, class_weight: float, dcfg: dict, warnings: list[str]) -> pd.Series:
    """No sector of single companies above `max_sector_share_of_class` of the class weight. Excess goes to the other
    holdings in the class (funds and other sectors) that still have room under their own caps."""
    share = float(dcfg.get("max_sector_share_of_class", 0) or 0)
    if not dcfg.get("enabled", True) or share <= 0 or "sector" not in sel.columns or len(sel) < 2:
        return w
    limit = share * class_weight
    direct = sel["vehicle"] == "direct"
    for _ in range(10):
        sums = w[direct].groupby(sel.loc[direct, "sector"]).sum()
        over = sums[sums > limit + 1e-9]
        if over.empty:
            break
        excess = 0.0
        capped = pd.Series(False, index=w.index)
        for sec, tot in over.items():
            rows = direct & (sel["sector"] == sec)
            excess += tot - limit
            w[rows] = w[rows] * limit / tot
            capped |= rows
        room = (~capped) & (w < cap - 1e-9)
        if not room.any():
            warnings.append(f"{sel['asset_class'].iloc[0]}: sector cap could not be fully applied; {excess:.2f}pp stays in the capped sectors")
            w[capped] += excess * w[capped] / w[capped].sum()
            break
        w[room] += excess * w[room] / w[room].sum()
        # a receiving holding may now breach its own cap; the loop re-checks sectors and the cap loop below trims it
        over_cap = w > cap
        if over_cap.any():
            spill = float((w[over_cap] - cap[over_cap]).sum())
            w[over_cap] = cap[over_cap]
            room2 = (~over_cap) & (~capped)
            if room2.any():
                w[room2] += spill * w[room2] / w[room2].sum()
            else:
                w[capped] += spill * w[capped] / w[capped].sum()
    return w


# ---------------------------------------------------------------- pricing helpers

def price_lookup(universe: pd.DataFrame, md: MarketData, manual: dict[str, float]) -> tuple[dict[str, float], dict[str, str]]:
    prices: dict[str, float] = {}
    origin: dict[str, str] = {}
    for r in universe.itertuples():
        p = md.latest_aud(r.ticker, r.currency)
        if p is not None:
            prices[r.ticker] = p
            origin[r.ticker] = md.source_by_ticker.get(r.ticker, "market")
        elif r.ticker in manual:
            prices[r.ticker] = manual[r.ticker]
            origin[r.ticker] = "manual"
    return prices, origin


def choose_menu(settings: Settings, balance: float, implementation: str, has_listed: bool) -> str:
    """Choice for anything holding listed securities; managed-portfolio-only accounts use Core, or
    Discover under the threshold."""
    cfg = settings.raw.get("platform", {})
    if "menus" not in cfg:
        return "choice"
    if implementation == "sma" or not has_listed:
        return "discover" if balance < float(cfg.get("discover_max_balance", 0)) and "discover" in cfg["menus"] else "core"
    return "choice"


def platform_fee(settings: Settings, balance: float, menu: str = "choice") -> float:
    cfg = settings.raw.get("platform")
    if not cfg:
        return 0.0
    if "menus" in cfg:
        cfg = cfg["menus"].get(menu) or cfg["menus"].get("choice") or {}
    fee, lower = 0.0, 0.0
    for band in cfg["bands"]:
        upper = band["up_to"] if band["up_to"] is not None else float("inf")
        slice_ = max(0.0, min(balance, upper) - lower)
        fee += slice_ * band["rate"]
        lower = upper
        if balance <= upper:
            break
    fee = min(max(fee, cfg.get("min_admin_fee", 0)), cfg.get("max_admin_fee", float("inf")) or float("inf"))
    fee += cfg.get("account_keeping_fee", 0)
    fee += min(balance * cfg.get("expense_recovery_rate", 0), cfg.get("expense_recovery_cap", 0))
    return fee


# ---------------------------------------------------------------- ESG screen

def apply_esg_screen(universe: pd.DataFrame, universe_all: pd.DataFrame, esg: dict, research: dict | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Remove holdings that fail the exclusion screens and swap unscreened index funds for screened ones.
    Written verdicts win; a holding without one is judged on its sector and industry from the research feed."""
    review = esg.get("review", {})
    subs = esg.get("substitutions", {})
    patterns = [(k, v["label"], [p.lower() for p in v.get("patterns", [])]) for k, v in esg.get("exclusions", {}).items()]
    research = research or {}
    changes: list[dict] = []
    keep, add = [], {}
    for _, r in universe.iterrows():
        t = r["ticker"]
        v = review.get(t)
        band = v["band"] if v else ""
        if not v:
            text = " ".join(str(getattr(research.get(t), k, "") or "") for k in ("sector", "industry")).lower()
            hit = next(((k, lbl) for k, lbl, pats in patterns if any(p in text for p in pats)), None)
            if hit:
                band = "excluded"
                v = {"involvement": hit[0], "note": f"Industry '{text.strip()}' matches the {hit[1].lower()} screen (no written verdict yet)."}
        if band == "excluded":
            changes.append({"ticker": t, "name": r["name"], "action": "excluded", "replacement": "", "reason": v.get("note", ""), "involvement": v.get("involvement", "")})
            continue
        if band == "substituted" and subs.get(t):
            rep_t = subs[t]
            src = universe_all[universe_all["ticker"] == rep_t]
            if len(src):
                row = src.iloc[0].to_dict()
                for k in ("role", "weight_hint", "min_tier", "max_weight", "priority", "min_tier_order"):
                    if k in r:
                        row[k] = r[k]
                row["status"] = "active"
                if rep_t in add:   # two holdings map to the same fund: pool their hints
                    add[rep_t]["weight_hint"] = float(add[rep_t]["weight_hint"]) + float(row["weight_hint"])
                    add[rep_t]["priority"] = min(add[rep_t]["priority"], row["priority"])
                else:
                    add[rep_t] = row
                changes.append({"ticker": t, "name": r["name"], "action": "substituted", "replacement": rep_t, "reason": v.get("note", ""), "involvement": v.get("involvement", "")})
                continue
            changes.append({"ticker": t, "name": r["name"], "action": "excluded", "replacement": "", "reason": v.get("note", "") + " (substitute not available in the price feed)", "involvement": v.get("involvement", "")})
            continue
        keep.append(r)
    out = pd.DataFrame(keep + [pd.Series(v) for v in add.values() if v["ticker"] not in {k["ticker"] for k in keep}])
    return out.reset_index(drop=True), changes


# ---------------------------------------------------------------- main build

def build_portfolio(settings: Settings, profiles: Profiles, universe: pd.DataFrame, md: MarketData,
                    manual: dict[str, float], view: TacticalView | None, *, profile: str, life_stage: str,
                    balance: float, research: dict | None = None, esg: dict | None = None,
                    universe_all: pd.DataFrame | None = None) -> Portfolio:
    warnings: list[str] = []
    rcfg = settings.raw.get("research", {})
    research = research or {}
    universe = fill_sector_region(universe, research)
    scfg = getattr(profiles, "selection", {}) or {}
    esg_info: dict = {}
    if esg:
        universe, changes = apply_esg_screen(universe, universe_all if universe_all is not None else universe, esg, research)
        esg_info = {"screened": True, "changes": changes}
        warnings.append(f"ESG screen on: {sum(c['action'] == 'excluded' for c in changes)} holdings excluded, "
                        f"{sum(c['action'] == 'substituted' for c in changes)} unscreened funds swapped for screened equivalents")
    profile_used = profiles.cap_profile(profile, life_stage)
    if profile_used != profile:
        warnings.append(f"Requested {profile} capped to {profile_used} for life stage {life_stage}")
    tier = profiles.tier_for_balance(balance)
    tcfg = profiles.balance_tiers[tier]
    ls = profiles.life_stages[life_stage]

    saa, tilts, target = strategic_plus_tactical(profiles, profile_used, view)
    target = apply_life_stage(profiles, target, life_stage, warnings)
    if scfg.get("enabled", True):
        fit, style, excluded = fit_scores(universe, research, profile_used, ls, scfg)
        universe = universe.assign(_fit=fit, style=style, _excluded=excluded)
        # Hand-picked lists lead the profiles they were written for: the income list in Conservative and Moderate
        # (and every pension-phase portfolio), the growth list in Growth and High Growth, both in Balanced.
        if "lists" in universe.columns:
            want = set()
            if profile_used in ("conservative", "moderate", "balanced") or life_stage == "retirement":
                want.add("income")
            if profile_used in ("growth", "high_growth", "balanced") and life_stage not in ("retirement",):
                want.add("growth")
            tags = universe["lists"].fillna("").astype(str)
            lead = tags.apply(lambda x: any(w in x.split() for w in want))
            other = (tags != "") & ~lead & (universe["vehicle"] == "direct")
            universe.loc[lead & (universe["priority"].astype(float) > 1), "priority"] = 2
            universe.loc[other, "priority"] = 3
        dropped = universe[(universe["_excluded"] != "") & (universe["vehicle"] == "direct")]
        if len(dropped):
            warnings.append("Left out for this profile: " + "; ".join(f"{r['ticker']} ({r['_excluded']})" for _, r in dropped.head(8).iterrows()) + (f"; and {len(dropped) - 8} more" if len(dropped) > 8 else ""))

    prices, origin = price_lookup(universe, md, manual)
    unpriced = sorted(set(universe["ticker"]) - set(prices))
    if unpriced:
        warnings.append(f"Unpriced holdings excluded: {', '.join(unpriced)}")

    # Fold classes too small to hold into a fallback class.
    min_hold = float(tcfg["min_holding_dollars"])
    working = dict(target)
    for c in list(working):
        if working[c] > 0 and working[c] / 100 * balance < min_hold:
            fb = GROWTH_FALLBACK_CLASS if c in profiles.growth_classes else DEFENSIVE_FALLBACK_CLASS
            if fb != c:
                warnings.append(f"{c} ({working[c]:.1f}% = ${working[c] / 100 * balance:,.0f}) below minimum holding; merged into {fb}")
                working[fb] = working.get(fb, 0.0) + working[c]
                working[c] = 0.0

    selection = select_holdings(universe, profiles, working, tier, set(prices), warnings, ls)
    # Classes with no eligible holdings: move weight to fallback class.
    for c in list(working):
        if working[c] > 0 and c not in selection:
            fb = GROWTH_FALLBACK_CLASS if c in profiles.growth_classes else DEFENSIVE_FALLBACK_CLASS
            working[fb] = working.get(fb, 0.0) + working[c]
            working[c] = 0.0
            if fb not in selection:
                selection = select_holdings(universe, profiles, working, tier, set(prices), warnings, ls)

    rows: list[dict] = []
    review_threshold = float(rcfg.get("review_threshold", 3.5))
    for c, sel in selection.items():
        mult = pd.Series({idx: consensus_multiplier(getattr(research.get(r.ticker), "consensus_mean", None),
                                                    getattr(research.get(r.ticker), "analysts", None), rcfg)
                          for idx, r in sel.iterrows()})
        dcfg = getattr(profiles, "diversification", {}) or {}
        w = weight_within_class(sel, working[c], ls, warnings, mult, dcfg)
        # Drop the smallest line while any line in a shared class falls under the tier's minimum holding.
        while len(sel) > 1 and float(w.min()) / 100 * balance < min_hold - 1:
            drop = w.idxmin()
            warnings.append(f"{sel.loc[drop, 'ticker']} left out: {w[drop]:.2f}% of ${balance:,.0f} is under the ${min_hold:,.0f} minimum holding")
            sel = sel.drop(index=drop)
            mult = mult.drop(index=drop)
            w = weight_within_class(sel, working[c], ls, warnings, mult, dcfg)
        for idx, r in sel.iterrows():
            hr = research.get(r.ticker)
            live_yield = getattr(hr, "dividend_yield_pct", None)
            cm = getattr(hr, "consensus_mean", None)
            if cm is not None and (getattr(hr, "analysts", 0) or 0) >= int(rcfg.get("min_analysts", 3)) and cm >= review_threshold:
                warnings.append(f"{r.ticker}: analyst consensus {getattr(hr, 'consensus_label', '')} ({cm:.1f}); review this holding")
            rows.append({"ticker": r.ticker, "name": r["name"], "asset_class": c, "vehicle": r.vehicle,
                         "role": r.role, "currency": r.currency, "source": r.get("source", ""),
                         "weight_pct": float(w[idx]), "mer_pct": float(r.mer),
                         "yield_pct": float(live_yield) if live_yield is not None else float(r["yield"]),
                         "yield_source": "live" if live_yield is not None else "config",
                         "franking_pct": float(r.franking), "price_aud": prices[r.ticker], "priced_from": origin[r.ticker],
                         "weight_hint": float(r.weight_hint), "sector": str(r.get("sector", "") or ""), "region": str(r.get("region", "") or ""),
                         "style": str(r.get("style", "") or ""), "fit_score": round(float(r.get("_fit", 0) or 0), 2),
                         "consensus_label": getattr(hr, "consensus_label", "") or "", "consensus_mean": cm,
                         "analysts": getattr(hr, "analysts", None), "consensus_multiplier": float(mult[idx])})
    df = pd.DataFrame(rows)

    # Minimum holding size: drop the smallest offenders and renormalise within class, keeping at least one per class.
    for _ in range(50):
        df["dollars"] = df["weight_pct"] / 100 * balance
        small = df[(df["dollars"] < min_hold)]
        if small.empty:
            break
        # Only drop if the class has more than one holding; otherwise leave it (class already passed the size test).
        counts = df.groupby("asset_class")["ticker"].transform("count")
        droppable = small[counts.loc[small.index] > 1]
        if droppable.empty:
            break
        victim = droppable.sort_values("dollars").index[0]
        c = df.loc[victim, "asset_class"]
        lost = df.loc[victim, "weight_pct"]
        df = df.drop(index=victim)
        mask = df["asset_class"] == c
        df.loc[mask, "weight_pct"] += lost * df.loc[mask, "weight_pct"] / df.loc[mask, "weight_pct"].sum()
    df["dollars"] = df["weight_pct"] / 100 * balance

    # Whole units for listed holdings; residual to cash.
    listed = df["priced_from"] != "manual"
    df["units"] = np.where(listed, np.floor(df["dollars"] / df["price_aud"]), df["dollars"] / df["price_aud"])
    df["dollars"] = df["units"] * df["price_aud"]
    residual = balance - df["dollars"].sum()
    cash_rows = df[df["asset_class"] == "cash"]
    if not cash_rows.empty:
        i = cash_rows.index[0]
        df.loc[i, "dollars"] += residual
        df.loc[i, "units"] = df.loc[i, "dollars"] / df.loc[i, "price_aud"]
    else:
        warnings.append(f"No cash line to absorb rounding residual of ${residual:,.2f}")
    df["weight_pct"] = df["dollars"] / balance * 100
    df = df.sort_values(["asset_class", "weight_pct"], ascending=[True, False])

    lines = [Line(**{k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in r.items()})
             for r in df[[f.name for f in Line.__dataclass_fields__.values()]].to_dict("records")]
    metrics = compute_metrics(settings, profiles, df, md, balance, tier, universe)
    metrics.update(weighted_returns(df, research))
    pid = f"{profile_used}__{life_stage}__{tier}" + ("__esg" if esg_info else "")
    return Portfolio(id=pid, profile_requested=profile, profile_used=profile_used, life_stage=life_stage, tier=tier,
                     balance=balance, saa=saa, tilts=tilts, target_class_weights=target, lines=lines,
                     metrics=metrics, warnings=warnings, as_of=str(md.as_of.date()), synthetic=md.synthetic, esg=esg_info)


# ---------------------------------------------------------------- metrics

def weighted_returns(df: pd.DataFrame, research: dict) -> dict:
    """Weighted average of the holdings' annualised trailing returns (the spreadsheet method).
    Cash and anything without a figure is counted at its yield; proxy-filled figures are counted
    and the share of the portfolio relying on proxies is reported."""
    out: dict = {}
    w = df["weight_pct"].values / 100
    for period, key in [("3y", "return_3y_pct_pa"), ("5y", "return_5y_pct_pa"), ("10y", "return_10y_pct_pa")]:
        vals, proxy_w, missing_w = [], 0.0, 0.0
        for wi, r in zip(w, df.itertuples()):
            hr = research.get(r.ticker)
            v = getattr(hr, key, None) if hr else None
            if v is None:
                v = float(r.yield_pct)          # cash and unresearched lines: assume they return their yield
                missing_w += wi
            elif hr.return_proxy.get(period):
                proxy_w += wi
            vals.append(wi * v)
        out[f"weighted_return_{period}_pct"] = round(float(sum(vals)), 2)
        out[f"weighted_return_{period}_proxy_share_pct"] = round(proxy_w * 100, 1)
        out[f"weighted_return_{period}_missing_share_pct"] = round(missing_w * 100, 1)
        # Same figure using only holdings with their own record for the period, re-weighted to 100.
        own = [(wi, getattr(research.get(r.ticker), key, None)) for wi, r in zip(w, df.itertuples())
               if research.get(r.ticker) and getattr(research[r.ticker], key, None) is not None and not research[r.ticker].return_proxy.get(period)]
        tot = sum(wi for wi, _ in own)
        out[f"weighted_return_{period}_own_pct"] = round(float(sum(wi * v for wi, v in own) / tot), 2) if tot > 0 else None
        out[f"weighted_return_{period}_own_share_pct"] = round(tot * 100, 1)
    return out


def diversification_metrics(df: pd.DataFrame, profiles: Profiles) -> dict:
    """How spread out the portfolio is: weight by sector and by region, the largest holdings, the effective number of
    holdings (1 / sum of squared weights), and plain-English flags against the diversification rules."""
    if df.empty:
        return {}
    w = df["weight_pct"].astype(float)
    sec = df["sector"].fillna("").replace("", "Other") if "sector" in df.columns else pd.Series("Other", index=df.index)
    reg = df["region"].fillna("").replace("", "Other") if "region" in df.columns else pd.Series("Other", index=df.index)
    direct = df["vehicle"] == "direct"
    by_sector = w.groupby(sec).sum().sort_values(ascending=False)
    by_region = w.groupby(reg).sum().sort_values(ascending=False)
    direct_by_sector = w[direct].groupby(sec[direct]).sum().sort_values(ascending=False)
    top = df.assign(w=w).sort_values("w", ascending=False)
    hhi = float(((w / 100) ** 2).sum())
    flags: list[str] = []
    dcfg = getattr(profiles, "diversification", {}) or {}
    dshare = float(w[direct].sum())
    if len(direct_by_sector) and dshare > 0 and int(direct.sum()) >= 4:
        s0 = direct_by_sector.index[0]
        if direct_by_sector.iloc[0] / dshare > 0.4 and direct_by_sector.iloc[0] > 5:
            flags.append(f"{s0} is {direct_by_sector.iloc[0] / dshare * 100:.0f}% of the single-company holdings")
    if len(by_region) and by_region.iloc[0] > 70 and by_region.index[0] != "Australia":
        flags.append(f"{by_region.iloc[0]:.0f}% of the portfolio is exposed to {by_region.index[0]}")
    biggest = top.iloc[0]
    if biggest["vehicle"] == "direct" and biggest["w"] > float(dcfg.get("max_single_holding_pct", 10) or 10):
        flags.append(f"{biggest['name']} is {biggest['w']:.1f}% of the portfolio")
    n_direct_sectors = int(sec[direct].nunique())
    if direct.sum() >= 3 and n_direct_sectors < int(dcfg.get("min_sectors_direct", 3) or 3):
        flags.append(f"the single companies span only {n_direct_sectors} sector(s)")
    return {
        "sector_weights": {k: round(float(v), 2) for k, v in by_sector.items()},
        "region_weights": {k: round(float(v), 2) for k, v in by_region.items()},
        "direct_share_pct": round(dshare, 2),
        "direct_count": int(direct.sum()),
        "direct_sectors": n_direct_sectors,
        "top_holding_pct": round(float(top["w"].iloc[0]), 2),
        "top_holding": str(top["name"].iloc[0]),
        "top5_pct": round(float(top["w"].head(5).sum()), 2),
        "effective_holdings": round(1 / hhi, 1) if hhi > 0 else None,
        "diversification_flags": flags,
    }


def compute_metrics(settings: Settings, profiles: Profiles, df: pd.DataFrame, md: MarketData, balance: float,
                    tier: str, universe: pd.DataFrame) -> dict[str, float]:
    w = df["weight_pct"] / 100
    growth = float(w[df["asset_class"].isin(profiles.growth_classes)].sum() * 100)
    mer = float((w * df["mer_pct"]).sum())
    yld = float((w * df["yield_pct"]).sum())
    listed_count = int((df["priced_from"] != "manual").sum())
    brokerage = listed_count * float(profiles.balance_tiers[tier]["brokerage_dollars"])
    menu = choose_menu(settings, balance, "direct", listed_count > 0)
    admin = platform_fee(settings, balance, menu)
    credits = float((w * df["yield_pct"] * df["franking_pct"] / 100 * FRANKING_GROSS_UP).sum())
    metrics = {
        "growth_pct": round(growth, 2),
        "defensive_pct": round(100 - growth, 2),
        "holdings": int(len(df)),
        **diversification_metrics(df, profiles),
        "weighted_mer_pct": round(mer, 3),
        "weighted_yield_pct": round(yld, 2),
        "grossed_up_yield_pct": round(yld + credits, 2),
        "franking_credits_per_year": round(credits / 100 * balance, 0),
        "income_per_year": round(yld / 100 * balance, 0),
        "aus_equity_pct": round(float(w[df["asset_class"] == "aus_equity"].sum() * 100), 2),
        "investment_fees_per_year": round(mer / 100 * balance, 0),
        "platform_admin_fee_per_year": round(admin, 0),
        "platform_menu": menu,
        "initial_brokerage": round(brokerage, 0),
        "total_ongoing_cost_pct": round(mer + admin / balance * 100, 3),
    }
    # Realised volatility and trailing return from the covariance of daily returns.
    proxies = profiles.tactical.get("proxies", {})
    twins = dict(zip(universe["ticker"], universe["twin"])) if universe is not None and "twin" in universe.columns else {}
    series = {}
    for r in df.itertuples():
        if r.ticker in md.prices.columns:
            series[r.ticker] = md.prices[r.ticker]
        elif twins.get(r.ticker) and twins[r.ticker] in md.prices.columns:
            series[r.ticker] = md.prices[twins[r.ticker]]       # unlisted fund: its listed twin stands in
        elif r.asset_class in proxies and proxies[r.asset_class]:
            p = [t for t in proxies[r.asset_class] if t in md.prices.columns]
            if p:
                series[r.ticker] = md.prices[p].mean(axis=1)
        # cash, term deposits and notes without a proxy are treated as zero volatility
    if series:
        px = pd.DataFrame(series).ffill().dropna(how="all")
        rets = px.pct_change().dropna(how="all").fillna(0.0).iloc[-252:]   # last year, as the page states
        if len(rets) >= 60:
            wv = df.set_index("ticker").loc[rets.columns, "weight_pct"].values / 100
            cov = rets.cov().values * 252
            port_var = float(wv @ cov @ wv)
            metrics["realised_volatility_pct"] = round(math.sqrt(max(port_var, 0)) * 100, 2)
            avg_vol = float((wv * rets.std().values * math.sqrt(252)).sum() * 100)
            metrics["weighted_avg_holding_vol_pct"] = round(avg_vol, 2)
            _risk_metrics(rets, wv, md, metrics, avg_vol, port_var)
    return metrics

def _risk_metrics(rets: pd.DataFrame, wv: np.ndarray, md: MarketData, metrics: dict, avg_vol: float, port_var: float) -> None:
    """Trailing one-year return, beta and correlation to the Australian (VAS) and world (VGS) share markets,
    average pairwise correlation between the holdings, diversification ratio and each holding's beta to the ASX 200.
    Daily returns in each holding's own currency; the beta of a USD holding therefore excludes the currency move."""
    last_year = rets.iloc[-252:]
    if len(last_year) >= 200:
        metrics["trailing_1y_return_pct"] = round(float(((1 + last_year @ wv).prod() - 1) * 100), 2)
    port = last_year @ wv
    bench = {"asx200": "VAS.AX", "world": "VGS.AX"}
    for k, t in bench.items():
        if t in md.prices.columns:
            b = md.prices[t].pct_change().reindex(port.index).fillna(0.0)
            if b.std() > 0:
                metrics[f"beta_{k}"] = round(float(port.cov(b) / b.var()), 2)
                metrics[f"correlation_{k}"] = round(float(port.corr(b)), 2)
    corr = last_year.corr()
    n = len(corr)
    if n > 1:
        metrics["avg_pairwise_correlation"] = round(float((corr.values.sum() - n) / (n * (n - 1))), 2)
    metrics["diversification_ratio"] = round(float(avg_vol / max(math.sqrt(max(port_var, 0)) * 100, 1e-9)), 2)
    metrics["holding_beta_asx200"] = {}
    if "VAS.AX" in md.prices.columns:
        b = md.prices["VAS.AX"].pct_change().reindex(last_year.index).fillna(0.0)
        if b.var() > 0:
            for t in last_year.columns:
                metrics["holding_beta_asx200"][t] = round(float(last_year[t].cov(b) / b.var()), 2)


# ---------------------------------------------------------------- history and backtest

def monthly_history(md: MarketData, settings: Settings, profiles: Profiles, universe: pd.DataFrame, years: int = 10,
                    extra: dict[str, pd.Series] | None = None, currency_of: dict[str, str] | None = None,
                    fills: dict[str, str] | None = None) -> dict:
    """Month-end total-return series (dividends reinvested, AUD) for every priced ticker over the last `years`
    years. A holding younger than the window is filled with its asset class index ETF for the months before it
    listed, and the fill is recorded so the page and the workbook can say how much of a result rests on stand-ins.
    `extra` adds synthetic series (for example an asset class mix standing in for a managed portfolio)."""
    px = md.prices.copy()
    fx_t = settings.raw.get("market_data", {}).get("fx_ticker", "AUDUSD=X")
    fx_cols = set(md.fx_tickers.values()) | {fx_t}
    cur = currency_of or {}
    for t in px.columns:
        c = str(cur.get(t, "AUD")).upper()
        if c == "AUD" or t in fx_cols:
            continue
        fs = md.fx_series(c)
        if fs is None and c == "USD" and fx_t in px.columns:
            fs = 1.0 / px[fx_t].ffill()
        if fs is not None:
            px[t] = px[t] * fs.reindex(px.index).ffill()
    if extra:
        for k, v in extra.items():
            px[k] = v.reindex(px.index)
    try:
        m = px.resample("ME").last()
    except ValueError:   # pandas before 2.2
        m = px.resample("M").last()
    m = m.iloc[-(years * 12 + 1):]
    rets = m.pct_change().iloc[1:]
    months = [d.strftime("%Y-%m") for d in rets.index]
    chains = settings.raw.get("returns", {}).get("long_history_proxies", {})
    cls = dict(zip(universe["ticker"], universe["asset_class"])) if universe is not None else {}
    series, stand_in, stand_months = {}, {}, {}
    for t in rets.columns:
        if t in fx_cols:
            continue
        r = rets[t]
        if r.notna().sum() < 3:
            continue
        if r.isna().any():
            chain = chains.get(cls.get(t, ""), [])
            chain = [chain] if isinstance(chain, str) else list(chain)
            if fills and fills.get(t):
                chain = [fills[t]] + chain
            for pt in chain:
                if pt in rets.columns and pt != t and rets[pt].notna().sum() > r.notna().sum():
                    filled = r.fillna(rets[pt])
                    stand_months[t] = int(r.isna().sum() - filled.isna().sum())
                    stand_in[t] = pt
                    r = filled
                    break
        series[t] = [None if pd.isna(v) else round(float(v), 5) for v in r]
    # Unlisted funds: the listed twin's whole history stands in, and is recorded as a stand-in for every month.
    if universe is not None and "twin" in universe.columns:
        for t, tw in zip(universe["ticker"], universe["twin"]):
            if tw and t not in series and tw in series:
                series[t] = list(series[tw]); stand_in[t] = tw; stand_months[t] = len(months)
    return {"months": months, "series": series, "stand_in": stand_in, "stand_in_months": stand_months,
            "class_proxy": {c: next((t for t in ps if t in series), None) for c, ps in profiles.tactical.get("proxies", {}).items()}}


def growth_backtest(history: dict, lines: list[Line], balance: float, key_of=None) -> dict:
    """Constant-mix backtest: the current weights held for the whole window and rebalanced monthly, starting
    with `balance`. Cash and unpriced lines earn nothing; a holding without any history uses its asset class
    proxy. Returns end value, annualised return, worst peak-to-trough fall and the stand-in share."""
    months = history.get("months", [])
    if not months:
        return {}
    S, cp = history["series"], history.get("class_proxy", {})
    n = len(months)
    rows = []
    for l in lines:
        k = key_of(l) if key_of else l.ticker
        sr = S.get(k) or (S.get(cp.get(l.asset_class)) if l.vehicle != "cash" else None)
        if sr is None:
            sr = [0.0] * n
        rows.append((l.weight_pct / 100, sr, k if k in S else cp.get(l.asset_class), k not in S and l.vehicle != "cash"))
    values, v, peak, mdd = [], float(balance), float(balance), 0.0
    fallback = {l.ticker: S.get(cp.get(l.asset_class)) for l in lines}
    for i in range(n):
        r = 0.0
        for (w, sr, k, _), l in zip(rows, lines):
            x = sr[i]
            if x is None:
                fb = fallback.get(l.ticker)
                x = fb[i] if fb and fb[i] is not None else 0.0
            r += w * x
        v *= 1 + r
        values.append(round(v, 2))
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    yrs = n / 12
    cagr = (v / balance) ** (1 / yrs) - 1 if balance > 0 and yrs > 0 else 0.0
    twelve = [values[i] / values[i - 12] - 1 for i in range(12, n)] if n > 12 else []
    stand_share = sum(w * (history.get("stand_in_months", {}).get(k, 0) if not whole else n) for w, _, k, whole in rows) / n * 100
    return {"months": months, "values": values, "end_value": round(v, 0), "cagr_pct": round(cagr * 100, 2),
            "max_drawdown_pct": round(mdd * 100, 2), "best_12m_pct": round(max(twelve) * 100, 2) if twelve else None,
            "worst_12m_pct": round(min(twelve) * 100, 2) if twelve else None, "stand_in_share_pct": round(stand_share, 1),
            "stand_ins": {k: history["stand_in"][k] for _, _, k, _ in rows if k in history.get("stand_in", {})}}


# ---------------------------------------------------------------- managed portfolio (SMA) implementation

def load_sma_menu(settings: Settings) -> pd.DataFrame:
    path = settings.root / "config" / "sma_menu.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["inception"] = pd.to_datetime(df["inception"], errors="coerce")
    return df


def _norm_name(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x).lower().replace(" (d)", ""))


def discover_overlay(menu: pd.DataFrame, discover: pd.DataFrame) -> pd.DataFrame:
    """Restrict the managed portfolio menu to those also offered on the Discover menu, and take the Discover
    booklet's underlying fees and transaction costs. The booklet discloses the manager fee only as "tiered",
    so the Core menu manager fee is kept as the stand-in and the total fee is recomputed."""
    if menu.empty or discover is None or discover.empty:
        return menu
    dmap = {_norm_name(n): r for n, r in zip(discover["name"], discover.to_dict("records"))}
    keep, under, trans, dcode = [], [], [], []
    for _, r in menu.iterrows():
        d = dmap.get(_norm_name(r["name"]))
        keep.append(d is not None)
        under.append(float(d["underlying_fees"]) if d else r["underlying_fees"])
        trans.append(float(d["transaction_costs"]) if d else r["transaction_costs"])
        dcode.append(d["code"] if d else "")
    out = menu.copy()
    out["underlying_fees"], out["transaction_costs"], out["discover_code"] = under, trans, dcode
    out = out[pd.Series(keep, index=out.index)]
    out["total_fee"] = out["mgmt_fee"] + out["perf_fee"].fillna(0) + out["underlying_fees"] + out["underlying_perf_fees"].fillna(0) + out["transaction_costs"]
    out["fee_basis"] = "Discover menu underlying fees and costs; manager fee is the Core menu figure (booklet shows it only as tiered)"
    return out


def sma_shortlist(profiles: Profiles, menu: pd.DataFrame, profile: str) -> pd.DataFrame:
    cfg = getattr(profiles, "sma", {}) or {}
    cat = cfg.get("category_by_profile", {}).get(profile)
    if menu.empty or not cat:
        return pd.DataFrame()
    df = menu[menu["category"] == cat].copy()
    years = (pd.Timestamp.today() - df["inception"]).dt.days / 365.25
    df["track_record_years"] = years.round(1)
    df = df[df["track_record_years"] >= float(cfg.get("min_track_record_years", 0))]
    prefer = [m.lower() for m in cfg.get("prefer_managers", [])]
    df["preferred"] = df["manager"].str.lower().apply(lambda m: any(pm in m for pm in prefer)) if prefer else False
    df = df.sort_values(["preferred", "total_fee", "track_record_years"], ascending=[False, True, False])
    return df.head(int(cfg.get("shortlist", 3)))


def build_sma_portfolio(settings: Settings, profiles: Profiles, universe: pd.DataFrame, md: MarketData,
                        manual: dict[str, float], view: TacticalView | None, menu: pd.DataFrame, *, profile: str,
                        life_stage: str, balance: float, discover: pd.DataFrame | None = None,
                        twins: dict | None = None, mix: dict | None = None, esg: dict | None = None) -> Portfolio | None:
    """One diversified managed portfolio matched to the risk profile, plus the life stage cash floor."""
    warnings: list[str] = []
    esg_info: dict = {}
    if esg:
        pat = esg.get("sma_name_pattern", "ethical|sustainab|esg")
        before = len(menu)
        menu = menu[menu["name"].str.contains(pat, case=False, regex=True)]
        esg_info = {"screened": True, "changes": [{"ticker": "", "name": "Managed portfolio menu", "action": "filtered", "replacement": "",
                                                   "reason": f"Only ethical, sustainable or ESG-labelled managed portfolios are eligible ({len(menu)} of {before} on the menu)", "involvement": ""}]}
        warnings.append("ESG screen on: only ethical, sustainable or ESG-labelled managed portfolios are eligible; the manager applies the screens inside the portfolio")
    profile_used = profiles.cap_profile(profile, life_stage)
    if profile_used != profile:
        warnings.append(f"Requested {profile} capped to {profile_used} for life stage {life_stage}")
    tier = profiles.tier_for_balance(balance)
    ls = profiles.life_stages[life_stage]
    platform_menu = choose_menu(settings, balance, "sma", False)
    if platform_menu == "discover":
        overlay = discover_overlay(menu, discover)
        if not overlay.empty:
            menu = overlay
            warnings.append("Discover menu: no administration or account keeping fee; underlying fees and transaction costs from the Discover investment booklet; "
                            "the manager fee is the Core menu figure because the booklet discloses it only as tiered")
        else:
            warnings.append("Discover menu applies at this balance but config/discover_menu.csv is missing; Core menu figures shown")
    short = sma_shortlist(profiles, menu, profile_used)
    if short.empty:
        return None
    n = int((getattr(profiles, "sma", {}).get("count_by_tier") or {}).get(tier, 1))
    # Pick n from the shortlist, preferring different managers so one manager's process is not the whole account.
    picks, managers = [], set()
    for _, row in short.iterrows():
        m = str(row["manager"]).split(" (")[0]
        if m in managers:
            continue
        picks.append(row)
        managers.add(m)
        if len(picks) >= n:
            break
    if len(picks) < n:
        for _, row in short.iterrows():
            if not any(row["code"] == pr["code"] for pr in picks):
                picks.append(row)
            if len(picks) >= n:
                break
    chosen = picks[0]
    saa = {c: float(v) for c, v in profiles.risk_profiles[profile_used]["saa"].items()}
    cash_floor = float(ls.get("cash_floor_pp", 0))
    sma_pct = 100.0 - cash_floor
    cash_row = universe[universe["asset_class"] == "cash"].sort_values("priority").head(1)
    cash_ticker = cash_row["ticker"].iloc[0] if len(cash_row) else "CMA"
    cash_price = manual.get(cash_ticker, 1.0)
    each = sma_pct / len(picks)
    lines = [
        Line(ticker=str(pk["code"]), name=str(pk["name"]), asset_class="__sma__", vehicle="sma", role="core", currency="AUD",
             source="hub24_sma_menu", weight_pct=each, dollars=each / 100 * balance, price_aud=1.0, units=each / 100 * balance,
             mer_pct=float(pk["total_fee"]) * 100, yield_pct=0.0, franking_pct=0.0, priced_from="platform")
        for pk in picks
    ] + [
        Line(ticker=cash_ticker, name=str(cash_row["name"].iloc[0]) if len(cash_row) else "Cash account", asset_class="cash", vehicle="cash",
             role="core", currency="AUD", source="hub24_model", weight_pct=cash_floor, dollars=cash_floor / 100 * balance, price_aud=cash_price,
             units=cash_floor / 100 * balance / cash_price, mer_pct=0.0, yield_pct=float(cash_row["yield"].iloc[0]) if len(cash_row) else 4.0,
             franking_pct=0.0, priced_from="manual"),
    ]
    # Class weights: the SMA's category implies the profile SAA; scale it into the non-cash portion.
    target = {c: saa[c] * sma_pct / 100 for c in saa}
    target["cash"] = target.get("cash", 0.0) + cash_floor
    growth = sum(target[c] for c in profiles.growth_classes)
    menu = platform_menu
    admin = platform_fee(settings, balance, menu)
    mer = sum(float(pk["total_fee"]) * 100 * each / 100 for pk in picks)
    metrics = {
        "growth_pct": round(growth, 2), "defensive_pct": round(100 - growth, 2), "holdings": len(picks) + 1,
        "weighted_mer_pct": round(mer, 3), "weighted_yield_pct": None, "income_per_year": None,
        "investment_fees_per_year": round(mer / 100 * balance, 0), "platform_admin_fee_per_year": round(admin, 0),
        "platform_menu": menu, "initial_brokerage": 0.0, "total_ongoing_cost_pct": round(mer + admin / balance * 100, 3),
    }
    # Risk from a proxy: the profile SAA implemented with the class proxy ETFs.
    proxies = profiles.tactical.get("proxies", {})
    series, weights = {}, {}
    for c, w in target.items():
        p = [t for t in proxies.get(c, []) if t in md.prices.columns]
        if p and w > 0:
            series[c] = md.prices[p].mean(axis=1)
            weights[c] = w / 100
    if series:
        px = pd.DataFrame(series).ffill().dropna(how="all")
        rets = px.pct_change().dropna(how="all").fillna(0.0).iloc[-252:]   # last year, as the page states
        if len(rets) >= 60:
            wv = np.array([weights[c] for c in rets.columns])
            wv = wv / wv.sum() * sum(weights.values())
            cov = rets.cov().values * 252
            port_var = float(wv @ cov @ wv)
            avg_vol = float((wv * rets.std().values * math.sqrt(252)).sum() * 100)
            metrics["realised_volatility_pct"] = round(math.sqrt(max(port_var, 0)) * 100, 2)
            metrics["weighted_avg_holding_vol_pct"] = round(avg_vol, 2)
            _risk_metrics(rets, wv, md, metrics, avg_vol, port_var)
            metrics["holding_beta_asx200"] = {}   # proxies, not the managed portfolio's own holdings
    clean = lambda row: {k: (None if (isinstance(v, float) and math.isnan(v)) else (v.isoformat() if hasattr(v, "isoformat") else v)) for k, v in row.to_dict().items()}
    # Live estimate from the underlying ETFs: the listed twin of the model where one exists, otherwise the
    # profile's strategic mix held in the asset class ETFs. Shown beside the manager's reported (stale) figures.
    from .research import _returns_from_prices
    underlying, history_key = {}, {}
    for pk in picks:
        code = str(pk["code"])
        tw = (twins or {}).get(code)
        if tw and tw["ticker"] in md.prices.columns:
            src, key, sr = f"listed twin {tw['ticker']}", tw["ticker"], md.prices[tw["ticker"]]
        elif mix and f"MIX:{profile_used}" in mix:
            src, key, sr = "asset class ETF mix for this risk profile", f"MIX:{profile_used}", mix[f"MIX:{profile_used}"]
        else:
            continue
        history_key[code] = key
        u = {k: v for k, v in _returns_from_prices(sr).items() if k.startswith("return_") or k == "history_years"}
        u["source"] = src
        underlying[code] = u
    sma_info = {
        "underlying": underlying, "history_key": history_key,
        "chosen": clean(chosen),
        "picks": [clean(pk) for pk in picks],
        "shortlist": [{k: (None if (isinstance(v, float) and math.isnan(v)) else (v.isoformat() if hasattr(v, "isoformat") else v))
                       for k, v in r.to_dict().items()} for _, r in short.iterrows()],
        "category": getattr(profiles, "sma", {}).get("category_by_profile", {}).get(profile_used, ""),
        "as_of": str(chosen.get("as_of", "")),
    }
    warnings.append("Managed portfolio performance and fees are from the HUB24 menu dated " + sma_info["as_of"] + "; risk figures use the profile's ETF proxies")
    return Portfolio(id=f"{profile_used}__{life_stage}__{tier}__sma" + ("__esg" if esg_info else ""), profile_requested=profile, profile_used=profile_used, life_stage=life_stage,
                     tier=tier, balance=balance, saa=saa, tilts={c: 0.0 for c in saa}, target_class_weights=target, lines=lines,
                     metrics=metrics, warnings=warnings, as_of=str(md.as_of.date()), synthetic=md.synthetic, implementation="sma", sma=sma_info, esg=esg_info)
