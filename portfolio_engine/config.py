"""Configuration loading. Everything the engine knows about profiles, life stages,
balance tiers and the investment universe comes from the files in config/."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

PROJECT_ROOT = Path(os.environ.get("PORTFOLIO_ENGINE_ROOT", Path(__file__).resolve().parent.parent))


@dataclass
class Settings:
    raw: dict[str, Any]
    root: Path = PROJECT_ROOT

    def path(self, key: str) -> Path:
        p = Path(self.raw["paths"][key])
        return p if p.is_absolute() else self.root / p

    @property
    def market_data(self) -> dict[str, Any]:
        return self.raw["market_data"]

    @property
    def rebalance(self) -> dict[str, Any]:
        return self.raw["rebalance"]


@dataclass
class Profiles:
    """Parsed profiles.yaml with validation."""
    asset_classes: dict[str, dict]
    risk_profiles: dict[str, dict]
    life_stages: dict[str, dict]
    balance_tiers: dict[str, dict]
    tactical: dict[str, Any]
    sma: dict[str, Any] = field(default_factory=dict)
    diversification: dict[str, Any] = field(default_factory=dict)

    @property
    def growth_classes(self) -> list[str]:
        return [c for c, v in self.asset_classes.items() if v["kind"] == "growth"]

    @property
    def defensive_classes(self) -> list[str]:
        return [c for c, v in self.asset_classes.items() if v["kind"] == "defensive"]

    def tier_for_balance(self, balance: float) -> str:
        tiers = sorted(self.balance_tiers.items(), key=lambda kv: kv[1]["order"])
        chosen = tiers[0][0]
        for name, t in tiers:
            if balance >= t["min_balance"]:
                chosen = name
        return chosen

    def tier_order(self, tier: str) -> int:
        return self.balance_tiers[tier]["order"]

    def profile_order(self, profile: str) -> int:
        return self.risk_profiles[profile]["order"]

    def cap_profile(self, profile: str, life_stage: str) -> str:
        """Return the profile actually used once the life stage cap is applied."""
        cap = self.life_stages[life_stage]["max_profile"]
        if self.profile_order(profile) > self.profile_order(cap):
            return cap
        return profile

    def validate(self) -> None:
        for name, rp in self.risk_profiles.items():
            total = sum(rp["saa"].values())
            if abs(total - 100) > 1e-6:
                raise ValueError(f"Risk profile {name} SAA sums to {total}, not 100")
            missing = set(self.asset_classes) - set(rp["saa"])
            if missing:
                raise ValueError(f"Risk profile {name} missing classes {missing}")
        for name, ls in self.life_stages.items():
            if ls["max_profile"] not in self.risk_profiles:
                raise ValueError(f"Life stage {name} max_profile unknown")
            if ls["default_profile"] not in self.risk_profiles:
                raise ValueError(f"Life stage {name} default_profile unknown")
        for cls in self.tactical.get("proxies", {}):
            if cls not in self.asset_classes:
                raise ValueError(f"Tactical proxy for unknown class {cls}")


def load_quality_review(settings: Settings) -> dict[str, dict]:
    """Written verdicts per holding (config/quality_review.csv): verdict, note, reviewed."""
    p = settings.root / "config" / "quality_review.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p, dtype=str).fillna("")
    return {r["ticker"]: {"verdict": r["verdict"], "note": r["note"], "reviewed": r["reviewed"]} for _, r in df.iterrows()}


def load_settings(path: Path | None = None) -> Settings:
    path = path or PROJECT_ROOT / "config" / "settings.yaml"
    with open(path) as f:
        return Settings(yaml.safe_load(f), root=path.resolve().parent.parent)


def load_profiles(settings: Settings) -> Profiles:
    with open(settings.path("profiles")) as f:
        raw = yaml.safe_load(f)
    p = Profiles(
        asset_classes=raw["asset_classes"],
        risk_profiles=raw["risk_profiles"],
        life_stages=raw["life_stages"],
        balance_tiers=raw["balance_tiers"],
        tactical=raw.get("tactical", {"enabled": False}),
        sma=raw.get("sma", {}),
        diversification=raw.get("diversification", {}),
    )
    p.validate()
    return p


KNOWN_ETFS = {"VAS", "VGS", "VAF", "VAP", "IFRA", "GOLD", "NDQ", "VGE", "VGAD", "VGB", "CRED", "AAA", "QUAL", "ASIA", "VSO", "SUBD",
              "IVV", "A200", "IOZ", "VHY", "VDHG", "DHHF", "STW", "IOO", "VEU", "VTS", "HACK", "ETHI", "FAIR", "MVW", "QUS", "VAE",
              "IAF", "BILL", "VIF", "VBND", "HBRD", "BHYB", "PMGOLD", "QAU", "VDGR", "VDBA", "YLDX", "IHVV", "IJP", "IEM"}

SUFFIX_CURRENCY = {".AX": "AUD", ".XA": "AUD", ".NZ": "NZD", ".TO": "CAD", ".V": "CAD", ".L": "GBP", ".PA": "EUR", ".MI": "EUR",
                   ".DE": "EUR", ".AS": "EUR", ".MC": "EUR", ".BR": "EUR", ".SW": "CHF", ".HK": "HKD", ".T": "JPY", ".SI": "SGD"}


SUFFIX_REGION = {".AX": "Australia", ".XA": "Australia", ".NZ": "New Zealand", ".TO": "Canada", ".V": "Canada", ".L": "United Kingdom",
                 ".PA": "Europe", ".MI": "Europe", ".DE": "Europe", ".AS": "Europe", ".MC": "Europe", ".BR": "Europe", ".SW": "Europe",
                 ".HK": "Asia", ".T": "Asia", ".SI": "Asia"}

YAHOO_SECTORS = {"Financial Services": "Financials", "Basic Materials": "Materials", "Technology": "Technology", "Healthcare": "Healthcare",
                 "Communication Services": "Communication", "Consumer Cyclical": "Consumer discretionary", "Consumer Defensive": "Consumer staples",
                 "Industrials": "Industrials", "Utilities": "Utilities", "Real Estate": "Real estate", "Energy": "Energy"}


def guess_region(ticker: str, name: str = "") -> str:
    """Where a holding's exposure sits: a listing suffix for shares, the fund's name for ETFs that invest abroad."""
    t, n = ticker.upper(), (name or "").lower()
    if t.endswith(".AX") or t.endswith(".XA"):
        if "ex-us" in n or "ex us" in n:
            return "Global ex US"
        if "asia" in n:
            return "Asia"
        if "emerging" in n:
            return "Emerging markets"
        if "nasdaq" in n or "s&p 500" in n or " us " in f" {n} " or "u.s." in n:
            return "United States"
        if any(k in n for k in ["international", "global", "world"]):
            return "Global"
        return "Australia"
    for suf, reg in SUFFIX_REGION.items():
        if t.endswith(suf):
            return reg
    return "United States"


def guess_currency(ticker: str) -> str:
    """Trading currency from the Yahoo Finance suffix; bare tickers are United States listings."""
    t = ticker.upper()
    for suf, ccy in SUFFIX_CURRENCY.items():
        if t.endswith(suf):
            return ccy
    return "USD"


UNIVERSE_COLUMNS = [
    "ticker", "name", "asset_class", "vehicle", "role", "currency", "mer", "yield",
    "franking", "weight_hint", "min_tier", "max_weight", "priority", "notes",
]


def load_universe(settings: Settings, profiles: Profiles, *, include_watchlist: bool = False) -> pd.DataFrame:
    df = pd.read_csv(settings.path("universe"), dtype={"notes": str}).fillna({"notes": ""})
    if "status" not in df.columns:
        df["status"] = "active"
    df["status"] = df["status"].fillna("active")
    # Manual additions: data/my_holdings.csv (ticker, asset_class, optional role, min_tier, weight_hint, notes)
    mine = settings.root / "data" / "my_holdings.csv"
    if mine.exists():
        try:
            extra = pd.read_csv(mine, comment="#", dtype=str).dropna(subset=["ticker"])
        except pd.errors.EmptyDataError:
            extra = pd.DataFrame()
        if len(extra):
            extra = extra[~extra["ticker"].isin(df["ticker"])]
            rows = []
            for r in extra.itertuples():
                t = str(r.ticker).strip().upper()
                vehicle = str(getattr(r, "vehicle", None) or "").strip().lower() or ("etf" if t.split(".")[0] in KNOWN_ETFS else "direct")
                rows.append({"ticker": t, "name": t, "asset_class": str(r.asset_class).strip(), "vehicle": vehicle,
                             "role": (str(getattr(r, "role", None) or "satellite").strip().lower()), "currency": guess_currency(t),
                             "mer": 0.0, "yield": 0.0, "franking": 0.0, "weight_hint": float(getattr(r, "weight_hint", None) or 3),
                             "min_tier": (str(getattr(r, "min_tier", None) or "core").strip().lower()), "max_weight": 6,
                             "priority": 2,   # an explicit addition outranks the engine's own satellites
                             "notes": "Manual addition (data/my_holdings.csv). " + str(getattr(r, "notes", "") or ""), "source": "manual_addition",
                             "hub24_code": "", "status": "active", "sector": "", "region": ""})
            df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    if not include_watchlist:
        df = df[df["status"] == "active"].copy()
    missing = set(UNIVERSE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"universe.csv missing columns {missing}")
    for col in ["mer", "yield", "franking", "weight_hint", "max_weight", "priority"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in ["sector", "region"]:
        df[col] = df[col].fillna("") if col in df.columns else ""
    df["region"] = [r if r else guess_region(t, n) for r, t, n in zip(df["region"], df["ticker"], df["name"])]
    unknown = set(df["asset_class"]) - set(profiles.asset_classes)
    if unknown:
        raise ValueError(f"universe.csv has unknown asset classes {unknown}")
    unknown_tiers = set(df["min_tier"]) - set(profiles.balance_tiers)
    if unknown_tiers:
        raise ValueError(f"universe.csv has unknown min_tier values {unknown_tiers}")
    if df["ticker"].duplicated().any():
        dupes = df.loc[df["ticker"].duplicated(), "ticker"].tolist()
        raise ValueError(f"universe.csv has duplicate tickers {dupes}")
    df["min_tier_order"] = df["min_tier"].map(lambda t: profiles.tier_order(t))
    return df


def load_discover_menu(settings: Settings) -> pd.DataFrame:
    """HUB24 Super Discover menu (config/discover_menu.csv): the managed portfolios available to accounts
    under the Discover threshold, with the booklet's underlying fees and transaction costs."""
    p = settings.root / "config" / "discover_menu.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def _pds_default(ticker: str, vehicle: str, name: str = "") -> tuple[str, str]:
    code = ticker.split(".")[0]
    if ticker.endswith(".AX") or ticker.endswith(".XA"):
        if ticker.endswith(".XA"):
            return f"https://www.cboe.com.au/products/{code}", "Cboe Australia product page (PDS under documents)"
        if vehicle in ("etf", "fund", "lit"):
            return f"https://www.asx.com.au/markets/etp/{code.lower()}", "ASX ETP page (issuer PDS not on file; add it to config/pds_links.csv)"
        return f"https://www.asx.com.au/markets/company/{code}", "Annual report and announcements (a listed company has no PDS)"
    if vehicle == "sma":
        return f"https://my.hub24.com.au/Hub24/public/documents/managed-portfolio-documents?mpCode={code}&productType=Super", "HUB24 Managed Portfolio Service PDS"
    if vehicle == "cash":
        return "https://www.hub24.com.au/product-documents/cash-account/", "HUB24 cash account information"
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={code}&type=10-K&dateb=&owner=include&count=10", "Annual report (SEC 10-K filings; a listed company has no PDS)"


def load_pds_links(settings: Settings, universe: pd.DataFrame, sma_menu: pd.DataFrame | None = None) -> dict[str, dict]:
    """Product document links for every holding: explicit overrides from config/pds_links.csv, otherwise the
    exchange's company page (which carries the PDS for ETFs and the annual report for companies)."""
    overrides: dict[str, dict] = {}
    p = settings.root / "config" / "pds_links.csv"
    if p.exists():
        for _, r in pd.read_csv(p, dtype=str).fillna("").iterrows():
            overrides[r["ticker"]] = {"url": r["url"], "label": r.get("label") or "Product disclosure statement"}
    out: dict[str, dict] = {}
    for r in universe.itertuples():
        if r.ticker in overrides:
            out[r.ticker] = overrides[r.ticker]
        else:
            url, label = _pds_default(r.ticker, str(getattr(r, "vehicle", "")), str(r.name))
            out[r.ticker] = {"url": url, "label": label}
    if sma_menu is not None and len(sma_menu):
        for code in sma_menu["code"]:
            url, label = _pds_default(str(code), "sma")
            out[str(code)] = overrides.get(str(code)) or {"url": url, "label": label}
    return out


def load_sma_twins(settings: Settings) -> dict[str, dict]:
    """Listed ETF twins of managed portfolios (config/sma_twins.csv): code -> {ticker, note}."""
    p = settings.root / "config" / "sma_twins.csv"
    if not p.exists():
        return {}
    return {r["code"]: {"ticker": r["ticker"], "note": r.get("note", "")} for _, r in pd.read_csv(p, dtype=str).fillna("").iterrows()}


def load_esg(settings: Settings) -> dict:
    """ESG screen rules (config/esg.yaml) and the written per-holding verdicts (config/esg_review.csv)."""
    p = settings.root / "config" / "esg.yaml"
    if not p.exists():
        return {}
    with open(p) as f:
        cfg = yaml.safe_load(f) or {}
    review = {}
    rp = settings.root / "config" / "esg_review.csv"
    if rp.exists():
        for _, r in pd.read_csv(rp, dtype=str).fillna("").iterrows():
            review[r["ticker"]] = {"band": r["band"], "involvement": r["involvement"], "note": r["note"], "reviewed": r["reviewed"]}
    cfg["review"] = review
    return cfg
