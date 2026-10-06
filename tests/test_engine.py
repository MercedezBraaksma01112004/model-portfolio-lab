"""Run with: python -m pytest tests -q   (uses synthetic prices; no network needed)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portfolio_engine.config import load_profiles, load_settings, load_universe  # noqa: E402
from portfolio_engine.market_data import get_market_data, load_manual_prices  # noqa: E402
from portfolio_engine.signals import compute_signals  # noqa: E402
from portfolio_engine.builder import build_portfolio, platform_fee  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    s = load_settings()
    p = load_profiles(s)
    u = load_universe(s, p)
    manual = load_manual_prices(s)
    tickers = set(u.loc[~u["ticker"].isin(manual), "ticker"])
    for ps in p.tactical["proxies"].values():
        tickers |= set(ps)
    tickers.add(p.tactical["cash_proxy"])
    md = get_market_data(s, sorted(tickers), offline=True)
    view = compute_signals(md, p, s.path("state"))
    return s, p, u, md, manual, view


def all_combos(p):
    for prof in p.risk_profiles:
        for stage in p.life_stages:
            for tier, t in p.balance_tiers.items():
                yield prof, stage, float(t["representative_balance"])


def test_saa_sums_to_100(ctx):
    _, p, *_ = ctx
    for rp in p.risk_profiles.values():
        assert abs(sum(rp["saa"].values()) - 100) < 1e-9


def test_tilts_zero_sum_and_bounded(ctx):
    _, p, _, _, _, view = ctx
    cap = p.tactical["max_tilt_pp"]
    shift_cap = p.tactical.get("max_growth_shift_pp", cap)
    for rp in p.risk_profiles.values():
        saa = {c: float(v) for c, v in rp["saa"].items()}
        t = view.tilts_for(saa, p)
        assert abs(sum(t.values())) < 1e-6
        for c, v in t.items():
            assert saa[c] + v >= -1e-9, "no negative class weight"
            assert abs(v) <= cap + 1e-6 or c in p.defensive_classes
        assert abs(sum(t[c] for c in p.growth_classes)) <= shift_cap + 1e-6


def test_every_portfolio_is_consistent(ctx):
    s, p, u, md, manual, view = ctx
    for prof, stage, bal in all_combos(p):
        pf = build_portfolio(s, p, u, md, manual, view, profile=prof, life_stage=stage, balance=bal)
        weights = sum(l.weight_pct for l in pf.lines)
        dollars = sum(l.dollars for l in pf.lines)
        assert abs(weights - 100) < 1e-6, pf.id
        assert abs(dollars - bal) < 0.01, pf.id
        tcfg = p.balance_tiers[pf.tier]
        assert len(pf.lines) <= tcfg["max_holdings"], pf.id
        for l in pf.lines:
            assert l.vehicle in tcfg["allowed_vehicles"], (pf.id, l.ticker)
            assert l.weight_pct > 0
            # Minimum holding size, except cash which absorbs rounding and single-holding classes.
            if l.asset_class != "cash":
                same = [x for x in pf.lines if x.asset_class == l.asset_class]
                if len(same) > 1:
                    # whole-unit rounding may leave a line one unit short of the minimum
                    assert l.dollars >= tcfg["min_holding_dollars"] - max(1.0, l.price_aud or 0), (pf.id, l.ticker, l.dollars)
        # Life stage cap respected
        assert p.profile_order(pf.profile_used) <= p.profile_order(p.life_stages[stage]["max_profile"])
        # Cash floor respected
        assert pf.class_weights().get("cash", 0) >= p.life_stages[stage]["cash_floor_pp"] - 0.5, pf.id


def test_growth_split_tracks_target(ctx):
    s, p, u, md, manual, view = ctx
    for prof, stage, bal in all_combos(p):
        pf = build_portfolio(s, p, u, md, manual, view, profile=prof, life_stage=stage, balance=bal)
        target_growth = sum(pf.target_class_weights[c] for c in p.growth_classes)
        actual = pf.metrics["growth_pct"]
        # Small balances fold tiny classes into fallbacks; allow a wider band there.
        tol = 6.0 if pf.tier == "starter" else 2.0
        assert abs(actual - target_growth) <= tol, (pf.id, actual, target_growth)


def test_no_tactical_matches_saa(ctx):
    s, p, u, md, manual, _ = ctx
    pf = build_portfolio(s, p, u, md, manual, None, profile="balanced", life_stage="early_accumulation", balance=500000)
    assert all(v == 0 for v in pf.tilts.values())
    target_growth = sum(p.saa_for("balanced", "early_accumulation")[c] for c in p.growth_classes)
    assert abs(pf.metrics["growth_pct"] - target_growth) < 1
    pf = build_portfolio(s, p, u, md, manual, None, profile="growth", life_stage="accumulation", balance=500000)
    assert all(v == 0 for v in pf.tilts.values())
    assert abs(pf.metrics["growth_pct"] - sum(p.saa_for("growth")[c] for c in p.growth_classes)) < 2


def test_platform_fee_bands(ctx):
    s, *_ = ctx
    assert platform_fee(s, 100000) == pytest.approx(350 + 240 + 25)
    assert platform_fee(s, 500000) == pytest.approx(700 + 400 + 240 + 125)
    assert platform_fee(s, 5000000) == pytest.approx(2000 + 240 + 350)


def test_retirement_prefers_income(ctx):
    s, p, u, md, manual, view = ctx
    early = build_portfolio(s, p, u, md, manual, view, profile="balanced", life_stage="early_accumulation", balance=500000)
    ret = build_portfolio(s, p, u, md, manual, view, profile="balanced", life_stage="retirement", balance=500000)
    assert ret.metrics["weighted_yield_pct"] > early.metrics["weighted_yield_pct"]


def test_sma_portfolio(ctx):
    from portfolio_engine.builder import build_sma_portfolio, load_sma_menu
    s, p, u, md, manual, view = ctx
    menu = load_sma_menu(s)
    if menu.empty or not p.sma.get("enabled"):
        pytest.skip("no SMA menu")
    pf = build_sma_portfolio(s, p, u, md, manual, view, menu, profile="high_growth", life_stage="retirement", balance=30000)
    assert pf is not None and pf.implementation == "sma"
    assert pf.profile_used == "balanced"
    assert abs(sum(l.weight_pct for l in pf.lines) - 100) < 1e-6
    assert abs(sum(pf.class_weights().values()) - 100) < 1e-6
    assert pf.class_weights()["cash"] >= p.life_stages["retirement"]["cash_floor_pp"]
    assert pf.sma["chosen"]["category"] == p.sma["category_by_profile"]["balanced"]
    assert len(pf.sma["shortlist"]) <= p.sma["shortlist"]


def test_manual_priced_holdings_are_cash_or_unlisted_funds_with_twins(ctx):
    _, _, u, md, manual, _ = ctx
    for t in [t for t in u["ticker"] if t in manual]:
        row = u[u["ticker"] == t].iloc[0]
        assert t == "CMA" or row["source"] == "unlisted_fund", t
        if row["source"] == "unlisted_fund" and row["asset_class"] != "cash":
            assert row["twin"], f"{t} needs a listed twin for risk and history"


def test_returns_and_review(ctx):
    from portfolio_engine.research import get_research
    from portfolio_engine.review import run_review
    from portfolio_engine.config import load_universe
    s, p, u, md, manual, view = ctx
    ua = load_universe(s, p, include_watchlist=True)
    research = get_research(s, ua, md, offline=True)
    # every priced holding has 1/3/5/10 year figures (synthetic history is long enough) and no proxies
    for t in ua["ticker"]:
        if t in md.prices.columns:
            r = research[t]
            assert r.return_1y_pct is not None and r.return_10y_pct_pa is not None
    items = run_review(s, ua, research, md)
    assert {i.status for i in items} <= {"active", "watchlist"}
    for i in items:
        assert i.action in {"remove candidate", "add candidate", "keep", "watch"}
        if i.action == "remove candidate":
            assert len(i.reasons) >= s.raw["review"]["strikes_to_remove"]
        if i.action == "add candidate":
            assert len(i.positives) >= s.raw["review"]["add_requirements"] and not i.reasons
    pf = build_portfolio(s, p, u, md, manual, view, profile="growth", life_stage="early_accumulation", balance=500000, research=research)
    for k in ("weighted_return_3y_pct", "weighted_return_5y_pct", "weighted_return_10y_pct"):
        assert k in pf.metrics
    assert any(l.yield_source == "live" for l in pf.lines) or md.synthetic


def test_pension_leans_australian_and_franked(ctx):
    s, p, u, md, manual, view = ctx
    early = build_portfolio(s, p, u, md, manual, view, profile="balanced", life_stage="early_accumulation", balance=500000)
    ret = build_portfolio(s, p, u, md, manual, view, profile="balanced", life_stage="retirement", balance=500000)
    assert ret.metrics["aus_equity_pct"] > early.metrics["aus_equity_pct"] + 5
    assert ret.metrics["grossed_up_yield_pct"] > early.metrics["grossed_up_yield_pct"]
    assert ret.metrics["franking_credits_per_year"] > early.metrics["franking_credits_per_year"]
    # no zero-yield equity holdings in a pension portfolio when alternatives exist
    for l in ret.lines:
        if l.asset_class in ("aus_equity", "intl_equity"):
            assert l.yield_pct > 0, l.ticker


def test_platform_menus_and_discover(tmp_path):
    from portfolio_engine.builder import choose_menu, platform_fee, discover_overlay, load_sma_menu
    from portfolio_engine.config import load_settings, load_discover_menu
    s = load_settings()
    assert choose_menu(s, 50_000, "sma", False) == "discover"
    assert choose_menu(s, 150_000, "sma", False) == "core"
    assert choose_menu(s, 50_000, "direct", True) == "choice"
    assert platform_fee(s, 50_000, "discover") == 0
    assert platform_fee(s, 50_000, "core") < platform_fee(s, 50_000, "choice")
    menu, disc = load_sma_menu(s), load_discover_menu(s)
    ov = discover_overlay(menu, disc)
    assert 0 < len(ov) < len(menu) and (ov["discover_code"] != "").all()


def test_risk_and_pds(ctx):
    from portfolio_engine.config import load_pds_links
    from portfolio_engine.builder import build_portfolio, build_sma_portfolio, load_sma_menu
    from portfolio_engine.config import load_discover_menu
    s, p, u, md, manual, view = ctx
    pf = build_portfolio(s, p, u, md, manual, view, profile="balanced", life_stage="accumulation", balance=250_000)
    sp = build_sma_portfolio(s, p, u, md, manual, view, load_sma_menu(s), profile="balanced", life_stage="accumulation", balance=30_000, discover=load_discover_menu(s))
    assert sp.metrics["platform_menu"] == "discover" and sp.metrics["platform_admin_fee_per_year"] == 0
    assert all(c["discover_code"] for c in sp.sma["shortlist"])
    m = pf.metrics
    assert m["platform_menu"] == "choice"
    assert "beta_asx200" in m and "diversification_ratio" in m and m["diversification_ratio"] >= 1.0
    assert -1 <= m["avg_pairwise_correlation"] <= 1
    links = load_pds_links(s, u)
    assert "vanguard" in links["VAS.AX"]["url"] and links["VAS.AX"]["url"].endswith(".pdf") and links["BHP.AX"]["url"].endswith("/BHP")


def test_history_and_backtest(ctx):
    from portfolio_engine.builder import monthly_history, growth_backtest, build_portfolio
    s, p, u, md, manual, view = ctx
    h = monthly_history(md, s, p, u, currency_of=dict(zip(u["ticker"], u["currency"])))
    assert 100 <= len(h["months"]) <= 121 and "VAS.AX" in h["series"]
    pf = build_portfolio(s, p, u, md, manual, view, profile="growth", life_stage="accumulation", balance=100_000)
    bt = growth_backtest(h, pf.lines, pf.balance)
    assert bt["end_value"] > 0 and len(bt["values"]) == len(h["months"]) and -100 < bt["max_drawdown_pct"] <= 0
    assert 0 <= bt["stand_in_share_pct"] <= 100


def test_diversification_rules(ctx):
    """Single companies in one asset class are spread across sectors and countries, and no sector of single
    companies carries more than the configured share of its class."""
    import math
    s, p, u, md, manual, view = ctx
    d = p.diversification
    assert d.get("enabled")
    for prof, stage, bal in all_combos(p):
        pf = build_portfolio(s, p, u, md, manual, view, profile=prof, life_stage=stage, balance=bal)
        if pf.house:
            continue   # a fixed house model keeps its own spread; the engine's sector rules apply to its own selections
        per_sector = int(d["max_direct_per_sector"][pf.tier])
        cw = pf.class_weights()
        relaxed = any("rule relaxed" in w or "sector cap could not" in w for w in pf.warnings)
        for c in set(l.asset_class for l in pf.lines):
            direct = [l for l in pf.lines if l.asset_class == c and l.vehicle == "direct"]
            if not direct:
                continue
            counts: dict[str, int] = {}
            sums: dict[str, float] = {}
            for l in direct:
                assert l.sector, (pf.id, l.ticker, "sector missing")
                assert l.region, (pf.id, l.ticker, "region missing")
                counts[l.sector] = counts.get(l.sector, 0) + 1
                sums[l.sector] = sums.get(l.sector, 0.0) + l.weight_pct
            n_class = len([l for l in pf.lines if l.asset_class == c])
            if not relaxed and n_class > 1:
                assert max(counts.values()) <= per_sector, (pf.id, c, counts)
                # sector weight cap, with a small allowance for whole-unit rounding and minimum-holding drops
                assert max(sums.values()) <= d["max_sector_share_of_class"] * cw[c] + 1.0, (pf.id, c, sums, cw[c])
            if not relaxed and n_class > 1:
                if c in d.get("region_rule_classes", ["intl_equity"]):
                    regions: dict[str, int] = {}
                    for l in direct:
                        regions[l.region] = regions.get(l.region, 0) + 1
                    assert max(regions.values()) <= max(1, math.ceil(d["max_region_share_of_direct"] * len(direct))) + 1, (pf.id, c, regions)
        m = pf.metrics
        assert "sector_weights" in m and abs(sum(m["sector_weights"].values()) - 100) < 0.5, pf.id
        assert abs(sum(m["region_weights"].values()) - 100) < 0.5, pf.id
        assert m["effective_holdings"] is None or 1 <= m["effective_holdings"] <= len(pf.lines) + 0.01
        for l in pf.lines:
            if l.vehicle == "direct":
                assert l.weight_pct <= d["max_single_holding_pct"] + 0.5, (pf.id, l.ticker, l.weight_pct)


def test_multi_currency_pricing(ctx):
    s, p, u, md, manual, view = ctx
    assert "USD" in md.fx_aud_per and md.fx_aud_per["USD"] > 0
    eur = u[u["currency"] == "EUR"]
    if len(eur):
        t = eur["ticker"].iloc[0]
        native = md.latest(t)
        aud = md.latest_aud(t, "EUR")
        assert native is not None and aud is not None
        assert aud == pytest.approx(native * md.fx_aud_per["EUR"])


def test_platform_schedules_are_complete():
    """Every platform menu in config/platforms.yaml has the fields the builder's fee formula reads."""
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "platforms.yaml").read_text())
    assert cfg["default"] in cfg["platforms"]
    for key, p in cfg["platforms"].items():
        assert p.get("label") and p.get("accounts"), key
        for ak, acct in p["accounts"].items():
            assert acct.get("as_of") and acct.get("source_url"), (key, ak)
            for mk, m in acct["menus"].items():
                bands = m["bands"]
                assert bands and bands[-1]["up_to"] is None, (key, mk)      # the last band is open-ended
                ups = [b["up_to"] for b in bands[:-1]]
                assert ups == sorted(ups), (key, mk)
                assert all(0 <= b["rate"] < 0.02 for b in bands), (key, mk)
                assert all(f.get("cap") is None or f["cap"] > 0 for f in m.get("percent_fees", [])), (key, mk)


def test_house_models(ctx):
    """Balanced at the Core tier and above is the house model: the model's holdings at the model's weights (to whole
    units, rounding in cash), no tilts. Below Core, and under the ESG screen, the engine builds to the same allocation."""
    s, p, u, md, manual, view = ctx
    from portfolio_engine.config import load_universe
    ua = load_universe(s, p, include_watchlist=True)
    assert p.house_models, "house models not loaded"
    for key, model in ((k, m) for k, m in p.house_models.items() if isinstance(m, dict) and "holdings" in m):
        want = {h["ticker"]: float(h["weight"]) for h in model["holdings"]}
        assert abs(sum(want.values()) - 100) < 1e-9
        for stage in model["stages"]:
            for tier, t in p.balance_tiers.items():
                bal = float(t["representative_balance"])
                pf = build_portfolio(s, p, u, md, manual, view, profile=model["profile"], life_stage=stage, balance=bal, universe_all=ua)
                if p.tier_order(tier) < p.tier_order(model["min_tier"]):
                    assert not pf.house, (key, tier)
                    continue
                assert pf.house and pf.house["key"] == key, (key, stage, tier)
                got = {l.ticker: l.weight_pct for l in pf.lines}
                assert set(got) == set(want), (key, set(want) ^ set(got))
                rounding = sum(100 * (l.price_aud or 0) / bal for l in pf.lines if l.priced_from != "manual")   # whole units: at most one unit short per line
                for tk, w in want.items():
                    tol = rounding + 0.01 if tk == "CMA" else max(0.25, 100 * (next(l for l in pf.lines if l.ticker == tk).price_aud or 0) / bal + 1e-9)
                    assert abs(got[tk] - w) <= tol, (key, tier, tk, got[tk], w)
                assert abs(sum(got.values()) - 100) < 1e-6 and abs(sum(l.dollars for l in pf.lines) - bal) < 0.01
                assert all(v == 0 for v in pf.tilts.values())
        # the ESG variant is the engine's own, to the same allocation
        stage = model["stages"][0]
        from portfolio_engine.config import load_esg
        esg = build_portfolio(s, p, u, md, manual, view, profile=model["profile"], life_stage=stage, balance=500000, esg=load_esg(s), universe_all=ua)
        assert not esg.house
    # pension-phase SAA replaces the home bias: the engine's own retirement portfolios start from saa_by_stage
    for prof in ("conservative", "moderate"):
        pf = build_portfolio(s, p, u, md, manual, None, profile=prof, life_stage="retirement", balance=500000)
        saa = p.saa_for(prof, "retirement")
        assert pf.saa == saa
        assert abs(pf.target_class_weights["aus_equity"] - saa["aus_equity"]) < 1e-9


def test_sizing_follows_house_model(ctx):
    """Engine-built portfolios size positions like the house model: an index ETF core or a fund larger than a single
    company in the same class."""
    s, p, u, md, manual, view = ctx
    pf = build_portfolio(s, p, u, md, manual, None, profile="growth", life_stage="accumulation", balance=500000)
    intl = [l for l in pf.lines if l.asset_class == "intl_equity"]
    direct = [l.weight_pct for l in intl if l.vehicle == "direct"]
    pooled = [l.weight_pct for l in intl if l.vehicle in ("etf", "lic", "fund") and l.role in ("core", "fallback")]
    if direct and pooled:
        assert max(pooled) > max(direct)
    assert len(pf.lines) <= p.balance_tiers[pf.tier]["max_holdings"]


def test_house_model_record(ctx, tmp_path):
    """The live record: contributions add up to the return, a change of weights carries the value on, and the
    benchmark is bought on the same day."""
    import copy
    import json
    from portfolio_engine.house_track import track_house_models, _hash, _weights
    s, p, *_ = ctx
    u = load_universe(s, p, include_watchlist=True)
    md = get_market_data(s, sorted(set(u["ticker"]) | {"VDGR.AX", "VDBA.AX"}), offline=True)
    p2 = copy.deepcopy(p)
    for m in p2.house_models.values():
        if isinstance(m, dict) and m.get("holdings"):
            m["inception"] = str(md.prices.index[-120].date())
    state = tmp_path / "track.json"
    first = track_house_models(p2, u, md, state)
    acc = first["balanced_accumulation"]
    assert acc["days"] >= 100 and acc["model"][0] == 100 and acc["bench"] and acc["bench"][0] == 100
    assert abs(sum(c["pts"] for c in acc["contrib"]) - (acc["model"][-1] - 100)) < 0.05
    # a new version of the model starts a new segment on its date; the value carries on
    m = p2.house_models["balanced_accumulation"]
    m["holdings"][0]["weight"] += 1
    m["holdings"][1]["weight"] -= 1
    st = json.loads(state.read_text())
    v = st["models"]["balanced_accumulation"]["versions"]
    v.append({"from": str(md.prices.index[-40].date()), "hash": _hash(_weights(m)), "weights": {t: x * 100 for t, x in _weights(m).items()}})
    state.write_text(json.dumps(st))
    second = track_house_models(p2, u, md, state)["balanced_accumulation"]
    assert second["changes"] == [str(md.prices.index[-40].date())]
    assert second["model"][:80] == acc["model"][:80], "history before the change is unchanged"
    assert len(json.loads(state.read_text())["models"]["balanced_accumulation"]["versions"]) == 2
    # a record one close old still knows which holdings have prices of their own, and has its benchmark
    for m in p2.house_models.values():
        if isinstance(m, dict) and m.get("holdings"):
            m["inception"] = str(md.prices.index[-1].date())
    day1 = track_house_models(p2, u, md, tmp_path / "day1.json")["balanced_accumulation"]
    assert day1["days"] == 0 and day1["bench"] is not None
    assert "VEU.AX" not in day1["stand_ins"] and set(day1["stand_ins"]) <= {"CMA", "TD12", "BNT0101AU", "ETL1293AU", "GSF0874AU", "WHT1465AU"}


def test_data_freshness_flags(ctx):
    import pandas as pd
    from portfolio_engine.freshness import data_freshness
    s, p, u, md, manual, _ = ctx
    unl = pd.read_csv(s.root / "config" / "unlisted_funds.csv", dtype=str).fillna("")
    f = data_freshness(u, md, manual, {}, unl, {}, {}, set(), set())
    by = {r["ticker"]: r for r in f["rows"]}
    assert by["CMA"]["status"] == "ok"
    eq = unl[(unl["unit_price"] == "1.0") & (unl["asset_class"].isin(["aus_equity", "intl_equity"]))]["ticker"]
    for t in eq:
        if t in by:
            assert by[t]["status"] == "notional", t
    assert f["counts"]["ok"] + f["counts"]["stale"] + f["counts"]["notional"] == f["total"]


def test_page_lines_factor_losslessly(ctx):
    import copy
    import json
    from portfolio_engine.reports.html import _compact_portfolios, _factor_lines, _clean
    s, p, u, md, manual, view = ctx
    pfs = [build_portfolio(s, p, u, md, manual, view, profile="balanced", life_stage=st, balance=b) for st in ("accumulation", "retirement") for b in (60_000, 400_000)]
    orig = _clean(_compact_portfolios(pfs))
    fact, base = _factor_lines(copy.deepcopy(orig))
    back = [{**x, "lines": [{**base[l["ticker"]], **l} for l in x["lines"]]} for x in fact]
    assert json.dumps(orig, sort_keys=True, default=str) == json.dumps(back, sort_keys=True, default=str)
