"""Command line interface.

    python -m portfolio_engine build [--offline] [--refresh] [--no-tactical]
    python -m portfolio_engine single --profile balanced --stage retirement --balance 350000
    python -m portfolio_engine rebalance --holdings my_account.csv --profile balanced --stage retirement
    python -m portfolio_engine refresh
    python -m portfolio_engine signals
    python -m portfolio_engine schedule --every 24h
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from .builder import build_portfolio, build_sma_portfolio, load_sma_menu, price_lookup, Portfolio, monthly_history, growth_backtest
from .config import load_profiles, load_settings, load_universe, load_quality_review, load_pds_links, load_discover_menu, load_sma_twins, load_esg
from .market_data import get_market_data, load_manual_prices
from .rebalance import analyse, load_current_holdings
from .asx_facts import get_asx_facts, apply_asx_facts, compact as asx_compact
from .research import get_research, research_to_records
from .review import run_review, apply_review, review_to_records
from .reports.excel import write_workbook
from .reports.html import write_dashboard
from .reports.builder import write_builder
from .signals import compute_signals, save_state

log = logging.getLogger("portfolio_engine")


class Context:
    def __init__(self, args):
        self.settings = load_settings(Path(args.config) if getattr(args, "config", None) else None)
        self.profiles = load_profiles(self.settings)
        # ASX facts (last dividend's franking, yield, security type and terms) for every ASX listing, applied to the universe.
        self.asx_facts = get_asx_facts(list(load_universe(self.settings, self.profiles, include_watchlist=True)["ticker"]),
                                       self.settings.root / "data" / "cache" / "asx_facts.json", offline=getattr(args, "offline", False))
        self._load_universes()
        self.manual = load_manual_prices(self.settings)
        tickers = set(self.universe_all.loc[~self.universe_all["ticker"].isin(self.manual), "ticker"])
        tickers |= {t for t in self.universe_all["twin"] if t}   # stand-ins for unlisted funds and unpriced listings
        for v in self.settings.raw.get("returns", {}).get("long_history_proxies", {}).values():
            tickers |= set([v] if isinstance(v, str) else v)
        for ps in self.profiles.tactical.get("proxies", {}).values():
            tickers |= set(ps)
        if self.profiles.tactical.get("cash_proxy"):
            tickers.add(self.profiles.tactical["cash_proxy"])
        self.sma_twins = load_sma_twins(self.settings)
        tickers |= {v["ticker"] for v in self.sma_twins.values()}
        self.md = get_market_data(self.settings, sorted(tickers), force_refresh=getattr(args, "refresh", False),
                                  offline=getattr(args, "offline", False))
        if getattr(args, "no_tactical", False):
            self.profiles.tactical["enabled"] = False
        self.view = compute_signals(self.md, self.profiles, self.settings.path("state"))
        self.sma_menu = load_sma_menu(self.settings)
        self.discover_menu = load_discover_menu(self.settings)
        self.quality = load_quality_review(self.settings)
        self.esg = load_esg(self.settings)
        self.sma_mix = self._sma_mix_series()
        cat_to_profile = {v: k for k, v in (self.profiles.sma.get("category_by_profile") or {}).items()}
        code_cat = dict(zip(self.sma_menu["code"], self.sma_menu["category"])) if len(self.sma_menu) else {}
        fills = {tw["ticker"]: f"MIX:{cat_to_profile.get(code_cat.get(code, ''), 'balanced')}" for code, tw in self.sma_twins.items()}
        self.history = monthly_history(self.md, self.settings, self.profiles, self.universe_all, extra=self.sma_mix,
                                       currency_of=dict(zip(self.universe_all["ticker"], self.universe_all["currency"])), fills=fills)
        self.class_corr = self._class_correlations()
        proxy_rows = pd.DataFrame([{"ticker": t, "name": t, "asset_class": c, "vehicle": "etf", "currency": "AUD"}
                                   for c, v in self.settings.raw.get("returns", {}).get("long_history_proxies", {}).items()
                                   for t in ([v] if isinstance(v, str) else v)
                                   if t not in set(self.universe_all["ticker"])])
        research_universe = pd.concat([self.universe_all, proxy_rows], ignore_index=True) if len(proxy_rows) else self.universe_all
        self.research = get_research(self.settings, research_universe, self.md, force=getattr(args, "refresh_research", False),
                                     offline=getattr(args, "offline", False))
        self.review = run_review(self.settings, self.universe_all, self.research, self.md) if not self.md.synthetic or True else []
        if self.settings.raw.get("review", {}).get("auto_apply") and not self.md.synthetic:
            changes = apply_review(self.settings, self.review, self.settings.path("universe"))
            for c in changes:
                log.warning("review applied: %s", c)
            if changes:
                self._load_universes()
        if self.md.synthetic:
            log.warning("OFFLINE MODE: prices are synthetic. Outputs are for testing the pipeline only.")

    def _load_universes(self) -> None:
        self.universe, notes = apply_asx_facts(load_universe(self.settings, self.profiles), self.asx_facts)
        self.universe_all, _ = apply_asx_facts(load_universe(self.settings, self.profiles, include_watchlist=True), self.asx_facts)
        if notes:
            log.info("ASX franking applied to %d holdings: %s", len(notes), "; ".join(notes[:12]))

    def _class_correlations(self) -> dict:
        """One-year correlation matrix between the asset class proxy ETFs."""
        proxies = self.settings.raw.get("returns", {}).get("long_history_proxies", {})
        series = {}
        for c, v in proxies.items():
            for t in ([v] if isinstance(v, str) else v):
                if t in self.md.prices.columns:
                    series[c] = self.md.prices[t]
                    break
        if len(series) < 2:
            return {}
        rets = pd.DataFrame(series).ffill().pct_change().dropna().iloc[-252:]
        corr = rets.corr().round(2)
        return {"classes": list(corr.columns), "matrix": corr.values.tolist(), "proxies": {c: (v if isinstance(v, str) else v[0]) for c, v in proxies.items()}}

    def _sma_mix_series(self) -> dict:
        """Daily index series standing in for a managed portfolio without a listed twin: the profile's strategic
        allocation held in the asset class proxy ETFs."""
        proxies = self.profiles.tactical.get("proxies", {})
        out = {}
        for prof, cfg in self.profiles.risk_profiles.items():
            parts, weights = {}, {}
            for c, w in cfg["saa"].items():
                p = [t for t in proxies.get(c, []) if t in self.md.prices.columns]
                if p and float(w) > 0:
                    parts[c] = self.md.prices[p].ffill().pct_change().mean(axis=1)
                    weights[c] = float(w)
            if not parts:
                continue
            rets = pd.DataFrame(parts).fillna(0.0)
            wv = pd.Series(weights) / sum(weights.values())
            out[f"MIX:{prof}"] = (1 + rets @ wv.reindex(rets.columns)).cumprod() * 100
        return out

    def _with_backtest(self, pf: Portfolio | None) -> Portfolio | None:
        if pf is None:
            return None
        keys = (pf.sma or {}).get("history_key", {}) if pf.implementation == "sma" else {}
        bt = growth_backtest(self.history, pf.lines, pf.balance, key_of=lambda l: keys.get(l.ticker, l.ticker))
        if bt:
            pf.metrics.update({"backtest_years": round(len(bt["months"]) / 12, 1), "backtest_end_value": bt["end_value"], "backtest_cagr_pct": bt["cagr_pct"],
                               "backtest_max_drawdown_pct": bt["max_drawdown_pct"], "backtest_worst_12m_pct": bt["worst_12m_pct"],
                               "backtest_best_12m_pct": bt["best_12m_pct"], "backtest_stand_in_share_pct": bt["stand_in_share_pct"]})
        return pf

    def build(self, profile: str, stage: str, balance: float, esg: bool = False) -> Portfolio:
        return self._with_backtest(build_portfolio(self.settings, self.profiles, self.universe, self.md, self.manual, self.view,
                                                   profile=profile, life_stage=stage, balance=balance, research=self.research,
                                                   esg=(self.esg if esg else None), universe_all=self.universe_all))

    def build_sma(self, profile: str, stage: str, balance: float, esg: bool = False) -> Portfolio | None:
        return self._with_backtest(build_sma_portfolio(self.settings, self.profiles, self.universe, self.md, self.manual, self.view, self.sma_menu,
                                                       profile=profile, life_stage=stage, balance=balance, discover=self.discover_menu,
                                                       twins=self.sma_twins, mix=self.sma_mix, esg=(self.esg if esg else None)))


def load_platforms(settings) -> dict:
    """Platform fee schedules for the builder (config/platforms.yaml). Missing file: the builder falls back to the HUB24 card in settings."""
    import yaml
    path = settings.root / "config" / "platforms.yaml" if hasattr(settings, "root") else Path("config/platforms.yaml")
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def cmd_build(args) -> int:
    ctx = Context(args)
    p = ctx.profiles
    portfolios: list[Portfolio] = []
    for prof in sorted(p.risk_profiles, key=lambda k: p.risk_profiles[k]["order"]):
        for stage in sorted(p.life_stages, key=lambda k: p.life_stages[k]["order"]):
            for tier in sorted(p.balance_tiers, key=lambda k: p.balance_tiers[k]["order"]):
                bal = float(p.balance_tiers[tier]["representative_balance"])
                portfolios.append(ctx.build(prof, stage, bal))
                if ctx.esg:
                    portfolios.append(ctx.build(prof, stage, bal, esg=True))
                if p.sma.get("enabled") and tier in p.sma.get("tiers", []):
                    if ctx.esg:
                        esp = ctx.build_sma(prof, stage, bal, esg=True)
                        if esp is not None:
                            portfolios.append(esp)
                    sp = ctx.build_sma(prof, stage, bal)
                    if sp is not None:
                        portfolios.append(sp)
    unique = {}
    for pf in portfolios:
        unique.setdefault(pf.id, pf)
    out = ctx.settings.path("output_dir")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    suffix = "_SYNTHETIC" if ctx.md.synthetic else ""
    prices, origin = price_lookup(ctx.universe_all, ctx.md, ctx.manual)
    pds = load_pds_links(ctx.settings, ctx.universe_all, ctx.sma_menu)
    xlsx = write_workbook(out / f"model_portfolios_{stamp}{suffix}.xlsx", list(unique.values()), p, ctx.settings, ctx.md,
                          ctx.view, ctx.universe_all, prices, origin, ctx.research, ctx.review, ctx.quality, pds=pds, esg=ctx.esg)
    # The house models' live record since inception; the version log is only written from real prices.
    from .house_track import track_house_models
    try:
        track = track_house_models(p, ctx.universe_all, ctx.md, ctx.settings.root / "data" / "house_track.json", write=not ctx.md.synthetic)
    except Exception as e:  # noqa: BLE001  a failed record must never stop the build
        log.warning("House model record failed: %s", e)
        track = {}
    # Daily returns, history, research and the search index: shared files fetched after each page has drawn.
    from .reports.html import write_shared_data
    lazy = write_shared_data(out, ctx.md, ctx.universe_all, p, ctx.research, ctx.history)
    html = write_dashboard(out / f"dashboard{suffix}.html", portfolios, p, ctx.md, ctx.view, ctx.research, ctx.universe_all, ctx.review,
                           settings_site_url=ctx.settings.raw.get("publish", {}).get("site_url", ""), quality=ctx.quality,
                           platform_cfg=ctx.settings.raw.get("platform", {}), class_corr=ctx.class_corr, pds=pds, history=ctx.history, esg=ctx.esg,
                           supabase=ctx.settings.raw.get("accounts", {}).get("supabase", {}), asx={t: asx_compact(f) for t, f in ctx.asx_facts.items()},
                           house_track=track, lazy=lazy)
    from .reports.compare import write_compare
    write_compare(out / f"compare{suffix}.html", load_platforms(ctx.settings))
    builder = write_builder(out / f"builder{suffix}.html", portfolios, p, ctx.md, ctx.universe_all, ctx.research, prices,
                            settings_site_url=ctx.settings.raw.get("publish", {}).get("site_url", ""), quality=ctx.quality,
                            platform_cfg=ctx.settings.raw.get("platform", {}), pds=pds, history=ctx.history, esg=ctx.esg,
                            supabase=ctx.settings.raw.get("accounts", {}).get("supabase", {}), platforms=load_platforms(ctx.settings),
                            asx={t: asx_compact(f) for t, f in ctx.asx_facts.items()}, lazy=lazy)
    (out / f"portfolios_{stamp}{suffix}.json").write_text(json.dumps(
        {"as_of": str(ctx.md.as_of.date()), "synthetic": ctx.md.synthetic, "tactical": ctx.view.to_dict(),
         "research": research_to_records(ctx.research), "review": review_to_records(ctx.review), "quality": ctx.quality,
         "portfolios": [pf.to_dict() for pf in portfolios]}, indent=1, default=str))
    # Month-end exchange rates (AUD per unit), published for the website's Nasdaq fallback, which has no exchange rate feed.
    from .market_data import _quotes_foreign_per_aud
    fxm = {}
    for ccy, t in (ctx.md.fx_tickers or {}).items():
        if t in ctx.md.prices.columns:
            fs = ctx.md.prices[t].dropna()
            fs = 1.0 / fs if _quotes_foreign_per_aud(t) else fs
            fxm[ccy] = {k: round(float(v), 6) for k, v in fs.groupby(fs.index.strftime("%Y-%m")).last().items()}
    (out / "fx_monthly.json").write_text(json.dumps({"built": str(ctx.md.as_of.date()), "aud_per": fxm}))
    # Is every holding's data up to date? Shown at the top of the Daily brief.
    try:
        from .freshness import data_freshness
        mp = ctx.settings.path("manual_prices")
        mdates = {}
        if mp.exists():
            mdf = pd.read_csv(mp, dtype=str).fillna("")
            mdates = {r["ticker"]: r.get("as_of", "") for _, r in mdf.iterrows()}
        unl = ctx.settings.root / "config" / "unlisted_funds.csv"
        udf = pd.read_csv(unl, dtype=str).fillna("") if unl.exists() else pd.DataFrame(columns=["ticker"])
        in_models = {l["ticker"] for pf in unique.values() for l in pf.to_dict().get("lines", [])}
        house = {h["ticker"] for m in (p.house_models or {}).values() if isinstance(m, dict) for h in (m.get("holdings") or [])}
        fresh = data_freshness(ctx.universe_all, ctx.md, ctx.manual, mdates, udf, ctx.research or {}, ctx.asx_facts or {}, in_models, house)
        (out / "freshness.json").write_text(json.dumps(fresh, default=str))
        print(f"  Data     : {fresh['counts']['ok']} of {fresh['total']} holdings up to date; {fresh['counts']['stale']} stale, {fresh['counts']['notional']} notional unit prices")
    except Exception as e:  # noqa: BLE001  a failed check must never stop the build
        log.warning("Data freshness check failed: %s", e)
    # Latest copies with stable names so a bookmark or a scheduled job always finds them.
    import shutil
    shutil.copy(xlsx, out / f"model_portfolios_latest{suffix}.xlsx")
    save_state(ctx.view, ctx.settings.path("state"))
    warn_count = sum(len(pf.warnings) for pf in unique.values())
    print(f"Built {len(portfolios)} portfolios ({len(unique)} distinct) as of {ctx.md.as_of.date()}"
          f"{' [SYNTHETIC]' if ctx.md.synthetic else ''}. {warn_count} notes.")
    print(f"  Workbook : {xlsx}")
    print(f"  Dashboard: {html}")
    print(f"  Builder  : {builder}")
    return 0


def _print_portfolio(pf: Portfolio, ctx: Context) -> None:
    labels = {c: v["label"] for c, v in ctx.profiles.asset_classes.items()}
    print(f"\n{pf.id}  balance ${pf.balance:,.0f}  as of {pf.as_of}{'  [SYNTHETIC]' if pf.synthetic else ''}")
    for w in pf.warnings:
        print(f"  note: {w}")
    print(f"\n  {'Asset class':28} {'SAA':>7} {'Tilt':>7} {'Target':>7} {'Actual':>7}")
    cw = pf.class_weights()
    for c in ctx.profiles.asset_classes:
        print(f"  {labels[c]:28} {pf.saa[c]:6.1f}% {pf.tilts[c]:+6.2f} {pf.target_class_weights[c]:6.1f}% {cw.get(c, 0):6.1f}%")
    print(f"\n  {'Ticker':12} {'Holding':42} {'Weight':>7} {'Dollars':>12} {'Units':>10}")
    for ln in pf.lines:
        print(f"  {ln.ticker:12} {ln.name[:42]:42} {ln.weight_pct:6.2f}% {ln.dollars:12,.0f} {ln.units:10,.1f}")
    m = {k: (float('nan') if v is None else v) for k, v in pf.metrics.items()}
    if pf.implementation == "sma":
        print(f"\n  Managed portfolio {pf.sma['chosen']['code']} ({pf.sma['chosen']['manager']}); shortlist: "
              + ", ".join(f"{c['code']} {c['total_fee'] * 100:.2f}%" for c in pf.sma["shortlist"]))
    print(f"\n  growth {m['growth_pct']:.1f}%  MER {m['weighted_mer_pct']:.2f}%  yield {m.get('weighted_yield_pct', float('nan')):.2f}%  "
          f"platform ${m['platform_admin_fee_per_year']:,.0f}  total cost {m['total_ongoing_cost_pct']:.2f}%  "
          f"realised vol {m.get('realised_volatility_pct', float('nan')):.1f}%")


def cmd_single(args) -> int:
    ctx = Context(args)
    esg = getattr(args, "esg", False)
    pf = ctx.build_sma(args.profile, args.stage, args.balance, esg=esg) if getattr(args, "sma", False) else ctx.build(args.profile, args.stage, args.balance, esg=esg)
    if pf is None:
        print("No managed portfolio available for that profile; check config/sma_menu.csv and the sma section of profiles.yaml")
        return 1
    _print_portfolio(pf, ctx)
    if args.out:
        Path(args.out).write_text(json.dumps(pf.to_dict(), indent=1, default=str))
        print(f"\nWritten to {args.out}")
    return 0


def cmd_rebalance(args) -> int:
    ctx = Context(args)
    current = load_current_holdings(args.holdings, ctx.universe, ctx.md, ctx.manual)
    balance = float(current["value"].sum())
    target = ctx.build(args.profile, args.stage, balance)
    rep = analyse(ctx.settings, ctx.profiles, current, target)
    pd.set_option("display.width", 160)
    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    print(f"\nAccount value ${rep.balance:,.0f}; target {target.id}")
    print("\nAsset class drift:")
    print(rep.class_drift.to_string())
    print("\nHolding drift:")
    print(rep.holding_drift.to_string())
    print("\nTrades (above minimum size):")
    print(rep.trades.to_string() if len(rep.trades) else "  none")
    if rep.flags:
        print("\nFlags:")
        for f in rep.flags:
            print("  " + f)
    else:
        print("\nAll asset classes within tolerance bands.")
    if args.out:
        with pd.ExcelWriter(args.out) as xw:
            rep.class_drift.to_excel(xw, sheet_name="Class drift")
            rep.holding_drift.to_excel(xw, sheet_name="Holding drift")
            rep.trades.to_excel(xw, sheet_name="Trades")
        print(f"\nWritten to {args.out}")
    return 0


def cmd_refresh(args) -> int:
    args.refresh = True
    ctx = Context(args)
    print(f"Prices refreshed as of {ctx.md.as_of.date()}; {ctx.md.prices.shape[1]} tickers.")
    missing = ctx.md.missing(sorted(set(ctx.universe["ticker"]) - set(ctx.manual)))
    if missing:
        print(f"No data for: {', '.join(missing)}")
    return 0


def cmd_signals(args) -> int:
    ctx = Context(args)
    v = ctx.view
    print(f"Signals as of {v.as_of}{'  [SYNTHETIC]' if v.synthetic else ''}; tactical {'enabled' if v.enabled else 'disabled'}")
    print(f"{'class':16} {'trend':>8} {'mom':>8} {'volr':>8} {'score':>6} {'raw':>6} {'used':>6}  note")
    for c, s in v.signals.items():
        f = lambda x: "   -" if x is None else f"{x * 100:7.1f}%"
        print(f"{c:16} {f(s.trend):>8} {f(s.momentum):>8} {f(s.volatility):>8} {s.score:6.2f} {s.raw_tilt_pp:6.2f} {s.tilt_pp:6.2f}  {s.note}")
    return 0


def cmd_research(args) -> int:
    ctx = Context(args)
    print(f"{'ticker':12} {'consensus':13} {'n':>3} {'mean':>5} {'target':>8} {'1y':>7} {'3y pa':>7} {'5y pa':>7} {'yield':>6}  sector")
    for t, r in ctx.research.items():
        f = lambda x, d=1: "     -" if x is None else f"{x:.{d}f}"
        print(f"{t:12} {r.consensus_label:13} {r.analysts or 0:3d} {f(r.consensus_mean):>5} {f(r.target_upside_pct):>7}% {f(r.return_1y_pct):>6}% {f(r.return_3y_pct_pa):>6}% {f(r.return_5y_pct_pa):>6}% {f(r.dividend_yield_pct):>5}%  {r.sector}")
    return 0


def cmd_review(args) -> int:
    ctx = Context(args)
    items = ctx.review
    print(f"Holding review as of {ctx.md.as_of.date()}{'  [SYNTHETIC]' if ctx.md.synthetic else ''}")
    for it in items:
        if it.action in ("remove candidate", "add candidate") or getattr(args, "all", False):
            print(f"\n{it.action.upper():18} {it.ticker:10} {it.name}  [{it.asset_class}]")
            for r in it.reasons:
                print(f"    - {r}")
            for m in it.positives:
                print(f"    + {m}")
    cands = [i for i in items if i.action.endswith("candidate")]
    if not cands:
        print("\nNo changes proposed: every active holding has fewer strikes than the removal threshold and no watchlist name clears the bar.")
    if getattr(args, "apply", False) and cands:
        if ctx.md.synthetic:
            print("\nNot applying: synthetic data.")
            return 1
        changes = apply_review(ctx.settings, items, ctx.settings.path("universe"))
        print("\nApplied:" if changes else "\nNothing applied.")
        for c in changes:
            print("  " + c)
    elif cands:
        print(f"\n{len(cands)} proposal(s). Run `python -m portfolio_engine review --apply` to make up to "
              f"{ctx.settings.raw.get('review', {}).get('max_changes_per_run', 2)} of them, or edit config/universe.csv by hand.")
    return 0


def cmd_add(args) -> int:
    import csv as _csv
    settings = load_settings(Path(args.config) if getattr(args, "config", None) else None)
    profiles = load_profiles(settings)
    t = args.ticker.strip().upper()
    if args.asset_class not in profiles.asset_classes:
        print(f"asset class must be one of {list(profiles.asset_classes)}")
        return 1
    uni = load_universe(settings, profiles, include_watchlist=True)
    if t in set(uni["ticker"]):
        print(f"{t} is already in the universe (status {uni.loc[uni['ticker'] == t, 'status'].iloc[0]}); set its status to active in config/universe.csv if needed")
        return 1
    md = get_market_data(settings, [t], offline=getattr(args, "offline", False))
    if md.latest(t) is None:
        print(f"No price data for {t}. Check the ticker (ASX codes end in .AX, Cboe in .XA, US tickers are bare).")
        return 1
    path = settings.root / "data" / "my_holdings.csv"
    with open(path, "a", newline="") as f:
        _csv.writer(f).writerow([t, args.asset_class, args.vehicle or "", args.role, args.tier, args.hint, args.note or ""])
    print(f"Added {t} to data/my_holdings.csv at {md.latest(t):.2f}; it will be researched and become eligible on the next build.")
    return 0


def cmd_remove(args) -> int:
    settings = load_settings(Path(args.config) if getattr(args, "config", None) else None)
    t = args.ticker.strip().upper()
    path = settings.path("universe")
    df = pd.read_csv(path, dtype={"notes": str}).fillna({"notes": ""})
    if t in set(df["ticker"]):
        df.loc[df["ticker"] == t, "status"] = "watchlist"
        df.to_csv(path, index=False)
        print(f"{t} moved to the watchlist in config/universe.csv (set status back to active to restore it).")
        return 0
    mine = settings.root / "data" / "my_holdings.csv"
    if mine.exists():
        lines = mine.read_text().splitlines()
        keep = [l for l in lines if not l.upper().startswith(t + ",")]
        if len(keep) != len(lines):
            mine.write_text("\n".join(keep) + "\n")
            print(f"{t} removed from data/my_holdings.csv")
            return 0
    print(f"{t} not found")
    return 1


def cmd_schedule(args) -> int:
    """Simple in-process scheduler. For production use cron or launchd (see README)."""
    unit = args.every[-1]
    n = float(args.every[:-1])
    seconds = n * {"m": 60, "h": 3600, "d": 86400}[unit]
    print(f"Rebuilding every {args.every}. Ctrl+C to stop.")
    while True:
        try:
            args.refresh = True
            cmd_build(args)
        except Exception as e:  # noqa: BLE001
            log.exception("Build failed: %s", e)
        time.sleep(seconds)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="portfolio_engine", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="path to settings.yaml (default config/settings.yaml)")
    ap.add_argument("--offline", action="store_true", help="use synthetic prices (testing only)")
    ap.add_argument("--refresh", action="store_true", help="ignore the price cache")
    ap.add_argument("--no-tactical", action="store_true", help="disable tactical tilts for this run")
    ap.add_argument("--refresh-research", action="store_true", help="refetch fundamentals and analyst consensus now")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    parent = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS so a subcommand's copy of a flag never overwrites the global one
    parent.add_argument("--offline", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parent.add_argument("--refresh", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parent.add_argument("--no-tactical", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parent.add_argument("--refresh-research", action="store_true", default=argparse.SUPPRESS, help="refetch fundamentals and analyst consensus now")
    sub.add_parser("build", parents=[parent], help="build every portfolio in the matrix and write outputs").set_defaults(fn=cmd_build)
    s = sub.add_parser("single", parents=[parent], help="build one portfolio")
    s.add_argument("--profile", required=True)
    s.add_argument("--stage", required=True)
    s.add_argument("--balance", type=float, required=True)
    s.add_argument("--sma", action="store_true", help="use one managed portfolio from the HUB24 menu instead of individual holdings")
    s.add_argument("--esg", action="store_true", help="apply the ESG screen (config/esg.yaml)")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_single)
    r = sub.add_parser("rebalance", parents=[parent], help="compare an account to its target and list trades")
    r.add_argument("--holdings", required=True, help="CSV with ticker and units (or value)")
    r.add_argument("--profile", required=True)
    r.add_argument("--stage", required=True)
    r.add_argument("--out")
    r.set_defaults(fn=cmd_rebalance)
    sub.add_parser("refresh", parents=[parent], help="refresh the price cache").set_defaults(fn=cmd_refresh)
    sub.add_parser("signals", parents=[parent], help="print tactical signals").set_defaults(fn=cmd_signals)
    sub.add_parser("research", parents=[parent], help="print holding research and analyst consensus").set_defaults(fn=cmd_research)
    rv = sub.add_parser("review", parents=[parent], help="screen holdings and the watchlist; propose additions and removals")
    rv.add_argument("--apply", action="store_true", help="make the proposed changes (up to review.max_changes_per_run)")
    rv.add_argument("--all", action="store_true", help="show every holding, not only the candidates")
    rv.set_defaults(fn=cmd_review)
    ad = sub.add_parser("add", parents=[parent], help="add a holding by ticker (written to data/my_holdings.csv)")
    ad.add_argument("ticker")
    ad.add_argument("--class", dest="asset_class", required=True, help="aus_equity, intl_equity, infrastructure, alternatives, fixed_income, credit, cash")
    ad.add_argument("--vehicle", default="", help="direct or etf (guessed if omitted)")
    ad.add_argument("--role", default="satellite")
    ad.add_argument("--tier", default="core", help="smallest balance tier it is eligible for")
    ad.add_argument("--hint", type=float, default=3, help="relative size within its class")
    ad.add_argument("--note", default="")
    ad.set_defaults(fn=cmd_add)
    rm = sub.add_parser("remove", parents=[parent], help="move a holding to the watchlist")
    rm.add_argument("ticker")
    rm.set_defaults(fn=cmd_remove)
    sc = sub.add_parser("schedule", parents=[parent], help="rebuild on an interval (for example 24h)")
    sc.add_argument("--every", default="24h")
    sc.set_defaults(fn=cmd_schedule)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
