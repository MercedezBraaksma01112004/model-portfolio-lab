"""The Compare page: platform costs at any balance (from config/platforms.yaml) and every super fund's MySuper product
and choice investment options (from APRA's Comprehensive Product Performance Package, scripts/super_funds.py), with
filters, side-by-side comparison and Excel download. The super fund data is loaded from /data/super.json so the page
itself stays small."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import html as dash

TEMPLATE = r"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compare | Model Portfolio Lab</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&display=swap">
<style>
__CSS__
.tabs { display:flex; gap:6px; margin:0 0 4px; flex-wrap:wrap; }
.tabs button { border:1.5px solid var(--line); background:var(--surface); color:var(--text); padding:10px 18px; border-radius:999px; font-weight:600; font-size:14.5px; min-height:44px; }
.tabs button[aria-selected="true"] { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
.form { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-top:10px; }
.form label { display:block; font-size:12.5px; color:var(--muted); margin-bottom:4px; }
.form input, .form select { width:100%; font:inherit; font-size:15px; padding:10px 12px; border:1.5px solid var(--line); border-radius:10px; background:var(--bg); color:var(--text); min-height:44px; }
.form input:focus, .form select:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }
.fchips { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0; align-items:center; }
.fchips button { border:1.5px solid var(--line); background:var(--surface); color:var(--text); padding:6px 12px; border-radius:999px; font-size:13px; min-height:34px; }
.fchips button[aria-pressed="true"] { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
table.cmp td, table.cmp th { font-size:13px; vertical-align:top; }
table.cmp tr.best td { background:var(--good-bg); }
table.cmp tr.sel td { background:var(--accent-soft); }
.chart svg { width:100%; height:auto; }
.legend2 { display:flex; flex-wrap:wrap; gap:6px 14px; font-size:12.5px; margin-top:6px; }
.legend2 i { display:inline-block; width:12px; height:3px; border-radius:2px; margin-right:5px; vertical-align:middle; }
.pick { width:18px; height:18px; accent-color:var(--accent); }
.cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; }
.card2 { border:1px solid var(--line); border-radius:12px; padding:12px 14px; background:var(--surface); position:relative; }
.card2 h4 { margin:0 0 2px; font-size:14.5px; }
.card2 .sub2 { color:var(--muted); font-size:12.5px; margin-bottom:8px; }
.card2 dl { display:grid; grid-template-columns:1fr auto; gap:3px 10px; margin:0; font-size:13px; }
.card2 dt { color:var(--muted); } .card2 dd { margin:0; font-variant-numeric:tabular-nums; text-align:right; }
.card2 dd.win { color:var(--good); font-weight:600; }
.card2.mine { border-color:var(--accent); box-shadow:inset 0 3px 0 var(--accent); }
.card2 .x { position:absolute; top:8px; right:8px; border:0; background:transparent; color:var(--faint); font-size:18px; padding:2px 6px; border-radius:6px; }
.pt-pass { color:var(--good); font-weight:500; } .pt-fail { color:var(--critical); font-weight:600; }
.more { margin-top:10px; }
.toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%); background:var(--text); color:var(--bg); padding:10px 16px; border-radius:10px; font-size:13.5px; display:none; z-index:20; max-width:90vw; }
</style>
</head>
<body>
<header><div class="wrap">
  <nav class="nav no-print"><a href="/">Model portfolios</a><a href="/builder.html">Builder</a><a href="/compare.html" aria-current="page">Compare</a><a href="/brief.html">Daily brief</a><a href="/quality.html">Quality review</a></nav>
  <h1>Compare</h1>
  <p class="lede">Platform costs at any balance, and every MySuper product and investment option side by side with your own portfolio.</p>
  <div class="meta" id="meta"></div>
  <div class="meta">Personal learning project. General information only, not a recommendation of any fund or platform. Check fees and returns in the product's current disclosure documents before relying on them.</div>
</div></header>
<main class="wrap">
<section class="no-print" style="padding-bottom:14px">
  <div class="tabs" role="tablist"><button type="button" role="tab" data-tab="plat" aria-selected="true">Platforms</button><button type="button" role="tab" data-tab="super" aria-selected="false">Super funds</button></div>
</section>

<div id="tab-plat">
<section>
  <div class="eyebrow">Platforms</div>
  <h2>What the platform itself would cost</h2>
  <p class="sub">Administration, fixed and percentage fees for each platform and menu at the balance below, using each platform's published super rate card. Investment manager fees and adviser fees are the same wherever the portfolio sits, so they are left out; brokerage is estimated separately.</p>
  <div class="form">
    <div><label for="p-bal">Account balance ($)</label><input id="p-bal" type="text" inputmode="numeric" value="500,000"></div>
    <div><label for="p-listed">Listed holdings (shares and ETFs)</label><input id="p-listed" type="number" min="0" max="80" value="15"></div>
    <div><label for="p-intl">Held in international listed shares (%)</label><input id="p-intl" type="number" min="0" max="100" value="0"></div>
    <div><label for="p-trades">Trades a year</label><input id="p-trades" type="number" min="0" max="500" value="12"></div>
    <div><label for="p-trade">Average trade size ($)</label><input id="p-trade" type="text" inputmode="numeric" value="15,000"></div>
    <div><label for="p-menus">Show</label><select id="p-menus"><option value="best">The cheapest menu that fits, per platform</option><option value="all">Every menu</option></select></div>
  </div>
  <div class="tscroll" style="margin-top:14px"><table class="cmp"><thead><tr><th>Platform and menu</th><th class="num">Administration</th><th class="num">Other platform fees</th><th class="num">Platform total a year</th><th class="num">% of balance</th><th class="num">Brokerage a year</th><th class="num">Total with brokerage</th><th>Holds listed?</th><th>Rate card</th></tr></thead><tbody id="p-rows"></tbody></table></div>
  <p class="muted" id="p-note" style="font-size:12.5px;margin:8px 0 0"></p>
  <div class="toolbar no-print"><button class="btn" id="p-xlsx" type="button">Download as Excel</button></div>
</section>
<section>
  <div class="eyebrow">By balance</div>
  <h2>How the cost changes as the balance grows</h2>
  <p class="sub">Platform cost as a percentage of the balance, from $50,000 to $3 million, for the cheapest menu on each platform that can hold the portfolio described above. Caps and fee-free tiers make the larger platforms cheaper as balances rise.</p>
  <div class="chart" id="p-chart"></div>
  <div class="legend2" id="p-legend"></div>
</section>
<section>
  <div class="eyebrow">Features</div>
  <h2>What each menu can hold and charges for</h2>
  <div class="tscroll"><table class="cmp"><thead><tr><th>Platform</th><th>Menu</th><th>Tiered fee</th><th>Minimum and cap</th><th>Fixed and other fees</th><th>Brokerage</th><th>Notes</th></tr></thead><tbody id="p-feat"></tbody></table></div>
</section>
</div>

<div id="tab-super" hidden>
<section>
  <div class="eyebrow">Super funds</div>
  <h2 id="s-title">Every MySuper product and investment option</h2>
  <p class="sub" id="s-sub">Loading APRA's product performance data…</p>
  <div class="form">
    <div><label for="s-q">Fund, product or option</label><input id="s-q" type="search" placeholder="for example AustralianSuper, Balanced, Indexed"></div>
    <div><label for="s-bal">Fees for a balance of</label><select id="s-bal"></select></div>
    <div><label for="s-growth">Growth assets</label><select id="s-growth"><option value="">Any mix</option><option value="0%-40%">0% to 40% (conservative)</option><option value="40%-60%">40% to 60% (moderate)</option><option value="60%-75%">60% to 75% (balanced)</option><option value="75%-90%">75% to 90% (growth)</option><option value="90%-100%">90% to 100% (high growth)</option></select></div>
    <div><label for="s-sort">Sort by</label><select id="s-sort"><option value="r10">10 year return</option><option value="r5">5 year return</option><option value="r3">3 year return</option><option value="after">10 year return less administration fees</option><option value="fee">Lowest total fees</option><option value="a">Largest</option><option value="f">Fund name</option></select></div>
  </div>
  <div class="fchips" id="s-kinds"></div>
  <div class="fchips" id="s-flags"></div>
  <div id="s-compare"></div>
  <div class="tscroll"><table class="cmp"><thead><tr><th class="no-print"></th><th>Fund, product and option</th><th>Type</th><th class="num">Growth</th><th>Performance test</th><th class="num">3 years</th><th class="num">5 years</th><th class="num">7 years</th><th class="num">10 years</th><th class="num" id="s-feehead">Total fees</th><th class="num">Assets</th></tr></thead><tbody id="s-rows"></tbody></table></div>
  <div class="more"><button class="btn" id="s-more" type="button">Show more</button> <span class="muted" id="s-count" style="font-size:12.5px"></span></div>
  <div class="toolbar no-print"><button class="btn" id="s-xlsx" type="button">Download the filtered list as Excel</button></div>
  <details style="margin-top:10px"><summary>What the figures mean</summary><p>Returns are APRA's net investment returns a year to 30 June: after investment fees, costs and tax, before administration fees. Platform options report gross investment returns net of investment fees (before tax and administration fees), so they are not directly comparable with the others. "10 year return less administration fees" subtracts the administration fees at the chosen balance as an approximation of what a member kept. Total fees are administration plus investment fees and costs as a percentage of the balance, from APRA's representative member at each balance. The performance test is APRA's annual test against a benchmark portfolio over up to ten years; "short history" means fewer years were available. Fund size is member assets in the option or product.</p><p>Not in this data: insurance cover and premiums, member services, advice offered, ESG approach and other benefits. Those are in each fund's disclosure documents. Data: APRA Comprehensive Product Performance Package, licensed under Creative Commons Attribution 3.0 Australia.</p></details>
</section>
</div>
</main>
<div class="toast" id="toast"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>
const P = __PLATFORMS__;
const sel = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const fmtM = x => (x == null || isNaN(x)) ? "–" : "$" + Math.round(x).toLocaleString("en-AU");
const fmtP = (x, d = 2) => (x == null || isNaN(x)) ? "–" : x.toFixed(d) + "%";
const pct = (x, d = 2) => (x == null || isNaN(x)) ? "–" : (x * 100).toFixed(d) + "%";
const money = v => { const n = parseFloat(String(v).replace(/[^0-9.]/g, "")); return isFinite(n) ? n : null; };
let toastT; function toast(m){ const t = sel("toast"); t.textContent = m; t.style.display = "block"; clearTimeout(toastT); toastT = setTimeout(() => t.style.display = "none", 3200); }
const COLORS = ["#2e5e4e","#3f6f9f","#b9842a","#9a5638","#6b5b8c","#5e8c6a","#c47a5a","#2f4858","#8c8a3e"];

// ---------------- tabs
document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => { document.querySelectorAll(".tabs button").forEach(x => x.setAttribute("aria-selected", String(x === b)));
  sel("tab-plat").hidden = b.dataset.tab !== "plat"; sel("tab-super").hidden = b.dataset.tab !== "super"; history.replaceState(null, "", "#" + b.dataset.tab); if (b.dataset.tab === "super") loadSuper(); });

// ---------------- platforms (the same fee formula as the builder)
function tieredFee(menu, bal){ const bands = menu.bands || []; let fee = 0, lower = 0;
  for (const b of bands) { const upper = b.up_to == null ? Infinity : b.up_to; fee += Math.max(0, Math.min(bal, upper) - lower) * b.rate; lower = upper; if (bal <= upper) break; }
  if (menu.min_admin_fee && !menu.min_includes_fixed) fee = Math.max(fee, +menu.min_admin_fee); if (menu.max_admin_fee != null) fee = Math.min(fee, +menu.max_admin_fee); return fee; }
function menuCost(menu, bal, nListed, intlValue){ let admin = tieredFee(menu, bal); const fixed = (menu.fixed_fees || []).reduce((s, f) => s + (+f.amount || 0), 0);
  if (menu.min_includes_fixed && menu.min_admin_fee) admin += Math.max(0, +menu.min_admin_fee - (admin + fixed));
  const pc = (menu.percent_fees || []).reduce((s, f) => s + Math.min(bal * (+f.rate || 0), f.cap == null ? Infinity : +f.cap), 0);
  const per = (+menu.per_listed_holding_fee || 0) * nListed + (+menu.intl_listed_rate || 0) * (intlValue || 0);
  return { admin, other: fixed + pc + per, total: admin + fixed + pc + per }; }
function brokerage(b, trades, size){ if (!b || b.rate == null) return null; return trades * Math.min(b.max == null ? Infinity : +b.max, Math.max(+b.min || 0, size * b.rate)); }
function inputs(){ return { bal: money(sel("p-bal").value) || 0, n: Math.max(0, +sel("p-listed").value || 0), intl: Math.min(100, Math.max(0, +sel("p-intl").value || 0)) / 100, trades: Math.max(0, +sel("p-trades").value || 0), size: money(sel("p-trade").value) || 0, mode: sel("p-menus").value }; }
function allRows(inp, balOverride){ const bal = balOverride ?? inp.bal; const rows = [];
  for (const [k, p] of Object.entries(P)) { if (p.manual_rate) continue; const acct = (p.accounts || {}).super || Object.values(p.accounts || {})[0]; if (!acct) continue;
    for (const [mk, m] of Object.entries(acct.menus || {})) { const fits = inp.n === 0 || m.allows_listed !== false; const okBal = m.max_balance == null || bal <= m.max_balance;
      const c = menuCost(m, bal, inp.n, bal * inp.intl); const br = inp.n > 0 ? brokerage(m.brokerage, inp.trades, inp.size) : 0;
      rows.push({ key: k, label: p.label, menu: m.label || mk, product: acct.product, as_of: acct.as_of, url: acct.source_url, verified: p.verified !== false && m.verified !== false, fits: fits && okBal, listed: m.allows_listed !== false, notes: m.notes || "", m, ...c, brokerage: br }); } }
  return rows; }
function bestRows(rows){ const by = {}; for (const r of rows) { if (!r.fits) continue; if (!by[r.key] || r.total < by[r.key].total) by[r.key] = r; } return Object.values(by); }
function renderPlat(){ const inp = inputs(); let rows = allRows(inp); rows = inp.mode === "best" ? bestRows(rows) : rows; rows.sort((a, b) => (b.fits - a.fits) || a.total - b.total);
  const cheapest = rows.find(r => r.fits);
  sel("p-rows").innerHTML = rows.map(r => `<tr class="${r === cheapest ? "best" : ""}" style="${r.fits ? "" : "opacity:.55"}"><td><b>${esc(r.label)}</b> ${esc(r.menu)}${r.verified ? "" : ' <span class="chip neutral" title="Read from the fee document through a summary; check before quoting">to confirm</span>'}<br><span class="muted" style="font-size:11.5px">${esc(r.product)}</span></td><td class="num">${fmtM(r.admin)}</td><td class="num">${fmtM(r.other)}</td><td class="num"><b>${fmtM(r.total)}</b></td><td class="num">${fmtP(inp.bal ? r.total / inp.bal * 100 : null)}</td><td class="num">${r.brokerage == null ? '<span class="muted" title="Brokerage depends on the broker used">–</span>' : fmtM(r.brokerage)}</td><td class="num">${fmtM(r.total + (r.brokerage || 0))}</td><td>${r.listed ? "yes" : "no: funds and managed portfolios only"}</td><td style="font-size:12px">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.as_of)}</a>` : esc(r.as_of)}</td></tr>`).join("");
  const fitting = rows.filter(r => r.fits); const dear = fitting[fitting.length - 1];
  sel("p-note").textContent = cheapest && dear && dear !== cheapest ? `At ${fmtM(inp.bal)}, the gap between the cheapest (${cheapest.label}, ${cheapest.menu}) and the dearest option that can hold this portfolio is ${fmtM(dear.total - cheapest.total)} a year. Greyed rows cannot hold listed securities, or are outside the menu's balance limit. Family group discounts and negotiated licensee rates are not included, and Morgans Wealth+ is left out because its fee is not published.` : "";
  renderChart(inp); }
function renderChart(inp){ const steps = []; for (let b = 50000; b <= 3000000; b += 25000) steps.push(b);
  const keys = Object.keys(P).filter(k => !P[k].manual_rate);
  const series = keys.map((k, i) => ({ k, label: P[k].label, color: COLORS[i % COLORS.length], vals: steps.map(b => { const best = bestRows(allRows(inp, b)).find(r => r.key === k); return best ? best.total / b * 100 : null; }) })).filter(s => s.vals.some(v => v != null));
  const W = 900, H = 320, L = 52, R = 14, T = 12, B = 30; const all = series.flatMap(s => s.vals).filter(v => v != null); const hi = Math.max(0.1, ...all) * 1.08;
  const X = i => L + i / (steps.length - 1) * (W - L - R), Y = v => T + (1 - v / hi) * (H - T - B);
  let g = ""; const step = hi > 1.2 ? 0.25 : hi > 0.6 ? 0.1 : 0.05; for (let v = 0; v <= hi; v += step) g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--faint)">${v.toFixed(2)}%</text>`;
  [50000, 500000, 1000000, 1500000, 2000000, 2500000, 3000000].forEach(b => { const i = steps.indexOf(b); if (i >= 0) g += `<text x="${X(i)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--faint)">${b >= 1e6 ? "$" + b / 1e6 + "m" : "$" + b / 1000 + "k"}</text>`; });
  const mark = steps.findIndex(b => b >= inp.bal); if (mark >= 0) g += `<line x1="${X(mark)}" x2="${X(mark)}" y1="${T}" y2="${H - B}" stroke="var(--accent)" stroke-dasharray="3 4" opacity=".6"/>`;
  const paths = series.map(s => { let d = "", pen = false; s.vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1) + " "; pen = true; }); return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2"/>`; }).join("");
  sel("p-chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Platform cost as a percentage of the balance">${g}${paths}</svg>`;
  sel("p-legend").innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join(""); }
function renderFeatures(){ const rows = [];
  for (const [k, p] of Object.entries(P)) { const acct = (p.accounts || {}).super || Object.values(p.accounts || {})[0]; if (!acct) continue;
    for (const [mk, m] of Object.entries(acct.menus || {})) { const bands = (m.bands || []).map((b, i, a) => `${(b.rate * 100).toFixed(2)}% ${b.up_to == null ? (i ? "above " + fmtM(a[i - 1].up_to) : "on the whole balance") : "to " + fmtM(b.up_to)}`).join("; ");
      const fixed = (m.fixed_fees || []).map(f => `${esc(f.label)} ${fmtM(f.amount)}`).concat((m.percent_fees || []).map(f => `${esc(f.label)} ${(f.rate * 100).toFixed(4).replace(/0+$/, "")}%${f.cap != null ? " (cap " + fmtM(f.cap) + ")" : ""}`)).concat(m.intl_listed_rate ? [`${(m.intl_listed_rate * 100).toFixed(2)}% on international listed shares`] : []).join("<br>");
      rows.push(`<tr><td><b>${esc(p.label)}</b></td><td>${esc(m.label || mk)}</td><td style="font-size:12px">${p.manual_rate ? "Not published" : bands}</td><td style="font-size:12px">${m.min_admin_fee ? "Minimum " + fmtM(m.min_admin_fee) + (m.min_includes_fixed ? " (including fixed fees)" : "") : "No minimum"}${m.max_admin_fee != null ? "<br>Cap " + fmtM(m.max_admin_fee) : ""}</td><td style="font-size:12px">${fixed || "–"}</td><td style="font-size:12px">${m.brokerage && m.brokerage.rate != null ? `${(m.brokerage.rate * 100).toFixed(3).replace(/0+$/, "")}%, minimum ${fmtM(m.brokerage.min)}${m.brokerage.max != null ? ", maximum " + fmtM(m.brokerage.max) : ""}` : "Not modelled"}</td><td style="font-size:12px">${esc(m.notes)}</td></tr>`); } }
  sel("p-feat").innerHTML = rows.join(""); }
["p-bal", "p-listed", "p-intl", "p-trades", "p-trade", "p-menus"].forEach(id => sel(id).onchange = () => { if (id === "p-bal" || id === "p-trade") { const v = money(sel(id).value); if (v) sel(id).value = v.toLocaleString("en-AU"); } renderPlat(); });
sel("p-xlsx").onclick = () => { if (typeof XLSX === "undefined") { toast("The spreadsheet library did not load"); return; } const inp = inputs(); const rows = allRows(inp).sort((a, b) => a.total - b.total);
  const wb = XLSX.utils.book_new(); const head = [["Platform cost comparison", ""], ["Balance", inp.bal], ["Listed holdings", inp.n], ["International listed share", inp.intl], ["Trades a year", inp.trades], ["Average trade size", inp.size], [], ["Platform", "Menu", "Product", "Can hold this portfolio", "Administration", "Other platform fees", "Platform total", "% of balance", "Brokerage a year", "Total with brokerage", "Rate card", "Confirmed", "Fee document"]];
  const ws = XLSX.utils.aoa_to_sheet(head.concat(rows.map(r => [r.label, r.menu, r.product, r.fits ? "yes" : "no", r.admin, r.other, r.total, inp.bal ? r.total / inp.bal : null, r.brokerage, r.total + (r.brokerage || 0), r.as_of, r.verified ? "yes" : "to confirm", r.url]))); ws["!cols"] = [18, 20, 40, 10, 12, 14, 12, 10, 12, 14, 24, 10, 60].map(w => ({ wch: w }));
  XLSX.utils.book_append_sheet(wb, ws, "Platforms"); XLSX.writeFile(wb, `platform_comparison_${Math.round(inp.bal)}.xlsx`); };
renderPlat(); renderFeatures();

// ---------------- super funds
let S = null; const SF = { mine: true, q: "", kinds: new Set(["MySuper", "Choice (diversified)"]), growth: "", open: true, test: "", sort: "r10", bal: 2, shown: 60, picked: [], dedupe: true };
const KINDS = ["MySuper", "Choice (diversified)", "Platform (diversified)", "Choice (single sector)"];
async function loadSuper(){ if (S) return; try { const r = await fetch("/data/super.json", { cache: "no-cache" }); if (!r.ok) throw new Error(r.status); S = await r.json(); } catch (e) { sel("s-sub").textContent = "The super fund data could not be loaded (" + e.message + ")."; return; }
  S.rows.forEach((r, i) => r.id = i);
  sel("s-title").textContent = `${S.rows.length.toLocaleString("en-AU")} MySuper products and investment options from ${new Set(S.rows.map(r => r.f)).size} funds`;
  sel("s-sub").innerHTML = `Fees, returns to ${esc(S.as_of)}, the APRA performance test, growth allocation and size, from APRA's Comprehensive Product Performance Package. Tick up to five to compare side by side. <a href="${esc(S.source_page)}" target="_blank" rel="noopener">Source</a>.`;
  sel("s-bal").innerHTML = S.balances.map((b, i) => `<option value="${i}" ${i === SF.bal ? "selected" : ""}>${fmtM(b)}</option>`).join("");
  ["s-q", "s-bal", "s-growth", "s-sort"].forEach(id => sel(id)[id === "s-q" ? "oninput" : "onchange"] = () => { SF.q = sel("s-q").value; SF.bal = +sel("s-bal").value; SF.growth = sel("s-growth").value; SF.sort = sel("s-sort").value; SF.shown = 60; renderSuper(); });
  sel("s-more").onclick = () => { SF.shown += 100; renderSuper(); };
  renderSuper(); }
const adminAt = r => r.fa ? r.fa[SF.bal] : null; const totalAt = r => r.ft ? r.ft[SF.bal] : null;
const after = r => r.r10 != null && adminAt(r) != null && r.basis == null ? r.r10 - adminAt(r) : (r.k === "MySuper" && r.rm10 != null && SF.bal === 2 ? r.rm10 : null);
function filtered(){ const q = SF.q.trim().toLowerCase();
  let rows = S.rows.filter(r => SF.kinds.has(r.k) && (!SF.open || r.open) && (!SF.growth || r.gc === SF.growth) && (!SF.test || (SF.test === "fail" ? /fail/i.test(r.pt) : /pass/i.test(r.pt))) && (!q || (r.f + " " + r.p + " " + r.o + " " + r.m).toLowerCase().includes(q)));
  if (SF.dedupe) {   // the same option offered through many employer plans or product versions: show it once, the largest copy
    const by = new Map(); for (const r of rows) { const k = [r.f, r.o, r.k, r.r10, r.r5, r.r3, (r.ft || [])[SF.bal]].join("|"); const cur = by.get(k);
      if (!cur) by.set(k, { ...r, copies: 1 }); else { cur.copies++; if ((r.a || 0) > (cur.a || 0)) by.set(k, { ...r, copies: cur.copies, id: r.id }); } }
    rows = [...by.values()]; }
  const val = { r10: r => r.r10, r5: r => r.r5, r3: r => r.r3, after: after, fee: r => totalAt(r) == null ? null : -totalAt(r), a: r => r.a ?? r.parent_a }[SF.sort];
  if (SF.sort === "f") rows.sort((a, b) => a.f.localeCompare(b.f) || a.o.localeCompare(b.o)); else rows.sort((a, b) => (val(b) ?? -Infinity) - (val(a) ?? -Infinity));
  return rows; }
function ptCell(r){ if (!r.pt) return '<span class="muted">not tested</span>'; return `<span class="${/fail/i.test(r.pt) ? "pt-fail" : "pt-pass"}">${esc(r.pt)}</span>`; }
const sizeTxt = v => v == null ? "–" : v >= 1e9 ? "$" + (v / 1e9).toFixed(1) + "bn" : v >= 1e6 ? "$" + (v / 1e6).toFixed(0) + "m" : fmtM(v);
function renderSuper(){ if (!S) return; const rows = filtered();
  sel("s-kinds").innerHTML = KINDS.map(k => `<button type="button" data-k="${esc(k)}" aria-pressed="${SF.kinds.has(k)}">${esc(k)} (${S.rows.filter(r => r.k === k).length})</button>`).join("");
  sel("s-kinds").querySelectorAll("button").forEach(b => b.onclick = () => { SF.kinds.has(b.dataset.k) ? SF.kinds.delete(b.dataset.k) : SF.kinds.add(b.dataset.k); SF.shown = 60; renderSuper(); });
  sel("s-flags").innerHTML = `<button type="button" id="f-open" aria-pressed="${SF.open}">Open to new members only</button><button type="button" id="f-dedupe" aria-pressed="${SF.dedupe}" title="The same option, fees and returns offered through several employer plans or product versions">Combine identical options</button><button type="button" data-t="" aria-pressed="${SF.test === ""}">Any test result</button><button type="button" data-t="pass" aria-pressed="${SF.test === "pass"}">Passed the test</button><button type="button" data-t="fail" aria-pressed="${SF.test === "fail"}">Failed the test</button>`;
  sel("f-open").onclick = () => { SF.open = !SF.open; renderSuper(); }; sel("f-dedupe").onclick = () => { SF.dedupe = !SF.dedupe; SF.shown = 60; renderSuper(); }; sel("s-flags").querySelectorAll("button[data-t]").forEach(b => b.onclick = () => { SF.test = b.dataset.t; renderSuper(); });
  sel("s-feehead").textContent = `Total fees at ${fmtM(S.balances[SF.bal])}`;
  const show = rows.slice(0, SF.shown);
  sel("s-rows").innerHTML = show.map(r => { const t = totalAt(r); const on = SF.picked.includes(r.id);
    return `<tr class="${on ? "sel" : ""}"><td class="no-print"><input type="checkbox" class="pick" data-id="${r.id}" ${on ? "checked" : ""} aria-label="Compare ${esc(r.f)} ${esc(r.o)}"></td><td><b>${esc(r.f)}</b><br><span style="font-size:12.5px">${esc(r.o)}</span> <span class="muted" style="font-size:11.5px">${esc(r.p)}${r.open ? "" : ", closed"}${r.copies > 1 ? `, offered in ${r.copies} plans or versions` : ""}</span></td><td style="font-size:12px">${esc(r.k)}${r.basis ? '<br><span class="muted">gross of tax and administration</span>' : ""}</td><td class="num">${pct(r.g, 0)}</td><td>${ptCell(r)}</td><td class="num">${pct(r.r3)}</td><td class="num">${pct(r.r5)}</td><td class="num">${pct(r.r7)}</td><td class="num"><b>${pct(r.r10)}</b></td><td class="num">${t == null ? "–" : pct(t)}<br><span class="muted" style="font-size:11.5px">${t == null ? "" : fmtM(t * S.balances[SF.bal]) + " a year"}</span></td><td class="num">${sizeTxt(r.a ?? r.parent_a)}</td></tr>`; }).join("") || `<tr><td colspan="11" class="muted">Nothing matches these filters.</td></tr>`;
  sel("s-rows").querySelectorAll("input.pick").forEach(c => c.onchange = () => { const id = +c.dataset.id; if (c.checked) { if (SF.picked.length >= 5) { c.checked = false; toast("Compare up to five at a time"); return; } SF.picked.push(id); } else SF.picked = SF.picked.filter(x => x !== id); renderSuper(); });
  sel("s-count").textContent = `Showing ${show.length} of ${rows.length}`; sel("s-more").hidden = show.length >= rows.length;
  renderCompare(); }
// Your portfolio from the builder (saved in this browser), shown as the first card beside the funds.
function mine(){ try { const m = JSON.parse(localStorage.getItem("mpl-portfolio-summary") || "null"); return m && m.balance ? m : null; } catch (e) { return null; } }
function similarFunds(n = 4){ const me = mine(); if (!me || !S) return []; const best = new Map();
  // one option per fund: the MySuper stage or diversified option whose growth mix is closest to the portfolio's
  for (const r of S.rows) { if (!(r.open && (r.k === "MySuper" || r.k === "Choice (diversified)") && r.g != null && r.r10 != null)) continue;
    const gap = Math.abs(r.g - me.growth); if (gap > 0.075) continue; const cur = best.get(r.f);
    if (!cur || gap < cur.gap || (gap === cur.gap && ((r.a ?? r.parent_a) || 0) > ((cur.r.a ?? cur.r.parent_a) || 0))) best.set(r.f, { r, gap }); }
  return [...best.values()].map(x => x.r).sort((a, b) => ((b.a ?? b.parent_a) || 0) - ((a.a ?? a.parent_a) || 0)).slice(0, n).map(r => r.id); }
function compareColumns(){ const bal = S.balances[SF.bal]; const me = SF.mine ? mine() : null; const cols = [];
  if (me) cols.push({ id: "me", title: me.name, sub: `Your portfolio from the builder: ${me.holdings} holdings on ${me.platform_label}`, test: "",
    v: { g: me.growth, r3: me.r3, r5: me.r5, r7: null, r10: me.r10, after: me.r10 == null ? null : me.r10 - me.platform, fee: me.total, feeyr: me.total * bal, admin: me.platform * bal, grow: me.r10 == null ? null : bal * Math.pow(1 + me.r10 - me.platform, 10), size: null, members: null } });
  for (const id of SF.picked) { const r = S.rows[id]; const a = after(r); cols.push({ id: r.id, title: r.f, sub: `${r.o}, ${r.k}${r.open ? "" : ", closed"}`, test: r.pt, row: r,
    v: { g: r.g, r3: r.r3, r5: r.r5, r7: r.r7, r10: r.r10, after: a, fee: totalAt(r), feeyr: totalAt(r) == null ? null : totalAt(r) * bal, admin: adminAt(r) == null ? null : adminAt(r) * bal, grow: a == null ? null : bal * Math.pow(1 + a, 10), size: r.a ?? r.parent_a, members: r.n } }); }
  return cols; }
const CMP_ROWS = () => { const bal = S.balances[SF.bal]; return [["g", "Growth assets", v => pct(v, 0), null], ["r3", "3 year return", v => pct(v), true], ["r5", "5 year return", v => pct(v), true], ["r7", "7 year return", v => pct(v), true], ["r10", "10 year return", v => pct(v), true],
  ["after", "10 year return less administration fees", v => pct(v), true], ["fee", `Total fees (${fmtM(bal)} for funds)`, v => pct(v), false], ["feeyr", `Total fees a year on ${fmtM(bal)}`, v => fmtM(v), false],
  ["admin", `Administration or platform fees on ${fmtM(bal)}`, v => fmtM(v), false], ["grow", `${fmtM(bal)} after 10 years at that return`, v => fmtM(v), true], ["size", "Size", sizeTxt, null], ["members", "Members", v => v == null ? "–" : Math.round(v).toLocaleString("en-AU"), null]]; };
function renderCompare(){ const box = sel("s-compare"); const me = mine(); const cols = compareColumns();
  const intro = me ? `<div class="fchips"><button type="button" id="c-mine" aria-pressed="${SF.mine}" title="${esc(me.name)}">Show my portfolio</button><button type="button" id="c-similar">Suggest similar funds</button>${cols.length ? '<button type="button" id="c-dl">Download this comparison</button><button type="button" id="c-clear">Clear</button>' : ""}</div>`
    : (cols.length ? `<div class="fchips"><button type="button" id="c-dl">Download this comparison</button><button type="button" id="c-clear">Clear</button><span class="muted" style="font-size:12.5px">To compare your own portfolio, build it on the builder page first; it appears here automatically.</span></div>` : "");
  if (!cols.length) { box.innerHTML = intro; wireCompare(); return; }
  const rows = CMP_ROWS(); const best = (k, hi) => { const vs = cols.map(c => c.v[k]).filter(v => v != null); return vs.length > 1 ? (hi ? Math.max(...vs) : Math.min(...vs)) : null; };
  box.innerHTML = intro + `<div class="cards">` + cols.map(c => `<div class="card2 ${c.id === "me" ? "mine" : ""}">${c.id === "me" ? "" : `<button type="button" class="x" data-x="${c.id}" aria-label="Remove">×</button>`}<h4>${esc(c.title)}</h4><div class="sub2">${esc(c.sub)}${c.id === "me" ? "" : `<br>Performance test: ${ptCell(c.row)}`}</div><dl>${rows.map(([k, lbl, fmt, hi]) => { const v = c.v[k]; const b = hi == null ? null : best(k, hi); return `<dt>${lbl}</dt><dd class="${b != null && v === b ? "win" : ""}">${fmt(v)}</dd>`; }).join("")}</dl></div>`).join("") + `</div>` +
    `<p class="muted" style="font-size:12.5px;margin:8px 0 14px">Green marks the best on each line. ${cols[0].id === "me" ? "Your portfolio's returns are the weighted returns of its holdings after their own fund fees, before platform fees and tax; the funds' returns are after investment fees and tax, before administration fees. Super tax of up to 15% on earnings would lower the portfolio's figures for a super account, so treat the return lines as a rough guide and the fee lines as the firmer comparison." : "Past returns are history, not a forecast; a higher growth allocation explains much of a higher return."}</p>`;
  wireCompare(); }
function wireCompare(){ const box = sel("s-compare");
  box.querySelectorAll("button[data-x]").forEach(b => b.onclick = () => { SF.picked = SF.picked.filter(x => x !== +b.dataset.x); renderSuper(); });
  const on = (id, f) => { const e = sel(id); if (e) e.onclick = f; };
  on("c-mine", () => { SF.mine = !SF.mine; renderCompare(); }); on("c-clear", () => { SF.picked = []; renderSuper(); });
  on("c-similar", () => { const ids = similarFunds(); if (!ids.length) { toast("No open options within 7.5 points of your growth mix"); return; } SF.picked = ids; SF.mine = true; renderSuper(); toast("The four largest open options with a similar growth mix"); });
  on("c-dl", downloadCompare); }
function downloadCompare(){ if (typeof XLSX === "undefined") { toast("The spreadsheet library did not load"); return; } const cols = compareColumns(); const rows = CMP_ROWS();
  const aoa = [["Comparison", `as at ${S.as_of}`], [], ["", ...cols.map(c => c.title)], ["Option or portfolio", ...cols.map(c => c.sub)], ["Performance test", ...cols.map(c => c.id === "me" ? "not applicable" : c.test || "not tested")]]
    .concat(rows.map(([k, lbl, , ]) => [lbl, ...cols.map(c => { const v = c.v[k]; return v == null ? null : v; })]))
    .concat([[], ["Notes", "Fund returns: APRA net investment returns (after investment fees and tax, before administration fees). Portfolio returns: weighted returns of the holdings after their fund fees, before platform fees and tax. Percentages are decimals. Past returns are not a forecast."], ["Source", `${S.source}, ${S.source_page}. Licence: ${S.licence}.`]]);
  const ws = XLSX.utils.aoa_to_sheet(aoa); ws["!cols"] = [{ wch: 44 }, ...cols.map(() => ({ wch: 34 }))]; const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, "Comparison");
  XLSX.writeFile(wb, `super_comparison_${new Date().toISOString().slice(0, 10)}.xlsx`); toast("Downloaded"); }
sel("s-xlsx").onclick = () => { if (!S || typeof XLSX === "undefined") { toast("Not ready yet"); return; } const rows = filtered();
  const head = ["Fund", "Product", "Menu", "Option", "Type", "Open", "Growth assets", "Performance test", "3 year return", "5 year return", "7 year return", "10 year return", "Return basis"].concat(S.balances.map(b => `Admin fees at ${fmtM(b)}`)).concat(S.balances.map(b => `Total fees at ${fmtM(b)}`)).concat(["Assets", "Members"]);
  const data = rows.map(r => [r.f, r.p, r.m, r.o, r.k, r.open ? "yes" : "no", r.g, r.pt, r.r3, r.r5, r.r7, r.r10, r.basis || "net of investment fees and tax"].concat(r.fa || []).concat(r.ft || []).concat([r.a ?? r.parent_a, r.n]));
  const wb = XLSX.utils.book_new(); const ws = XLSX.utils.aoa_to_sheet([[`Super funds: ${S.source} (as at ${S.as_of})`], [`Source: ${S.source_page}. Licence: ${S.licence}.`], [], head].concat(data));
  ws["!cols"] = [36, 36, 30, 36, 20, 6, 10, 16, 9, 9, 9, 9, 28].concat(Array(10).fill(12)).concat([14, 10]).map(w => ({ wch: w })); XLSX.utils.book_append_sheet(wb, ws, "Super funds"); XLSX.writeFile(wb, `super_funds_${S.as_of.replace(/\s+/g, "_")}.xlsx`); };
sel("meta").textContent = `Platform fees from each platform's current disclosure document; the date of each is shown in the cost table. Super fund data loads when you open the Super funds tab.`;
if (location.hash === "#super") document.querySelector('.tabs button[data-tab="super"]').click();   // opened from the builder's "Compare with super funds"
</script>
</body>
</html>
"""


def _css() -> str:
    m = re.search(r"<style>(.*?)</style>", dash.TEMPLATE, re.S)
    css = m.group(1) if m else ""
    light = " ".join(f"--series-{i + 1}:{c};" for i, c in enumerate(dash.PALETTE_LIGHT))
    dark = " ".join(f"--series-{i + 1}:{c};" for i, c in enumerate(dash.PALETTE_DARK))
    return css.replace("__LIGHT_VARS__", light).replace("__DARK_VARS__", dark)


def write_compare(path: Path, platforms: dict) -> Path:
    page = TEMPLATE.replace("__CSS__", _css()).replace("__PLATFORMS__", json.dumps((platforms or {}).get("platforms", {})).replace("</", "<\\/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
