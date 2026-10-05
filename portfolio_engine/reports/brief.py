"""The "Daily brief" page: key numbers, announcements for the universe's holdings and the market, regulatory, legal
and policy updates, market wrap headlines and the day's moves, from scripts/daily_brief.py's JSON. Shares the
dashboard's styles; every list can be filtered on the page and the whole brief downloads as an Excel workbook."""
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
<title>Daily brief | Model Portfolio Lab</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&display=swap">
<style>
__CSS__
.groups { display:grid; gap:18px; }
.numtiles { display:grid; grid-template-columns:repeat(auto-fill, minmax(190px, 1fr)); gap:12px; }
.numtiles .tile .v { font-size:24px; }
.chg { font-variant-numeric:tabular-nums; font-size:13px; }
.chg.up { color:var(--good); } .chg.down { color:var(--critical); }
.coming { display:flex; flex-wrap:wrap; gap:8px 18px; font-size:13.5px; margin-top:10px; color:var(--muted); }
.coming b { color:var(--text); font-weight:600; }
.fchips { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 10px; align-items:center; }
.fchips button { border:1.5px solid var(--line); background:var(--surface); color:var(--text); padding:6px 12px; border-radius:999px; font-size:13px; min-height:34px; }
.fchips button[aria-pressed="true"] { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
.fchips input { font:inherit; font-size:14px; padding:7px 10px; border:1.5px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); min-width:200px; }
.alist { display:grid; gap:0; border-top:1px solid var(--line); }
.arow { display:grid; grid-template-columns:118px 76px 1fr auto; gap:6px 14px; padding:9px 2px; border-bottom:1px solid var(--line); align-items:baseline; font-size:14px; }
.arow .when { color:var(--faint); font-size:12.5px; font-variant-numeric:tabular-nums; }
.arow .code { font-variant-numeric:tabular-nums; font-weight:500; }
.arow .co { color:var(--muted); font-size:12.5px; }
.arow a { color:var(--text); text-decoration:none; } .arow a:hover { text-decoration:underline; color:var(--accent); }
.arow.held { background:var(--accent-soft); }
.rrow { display:grid; grid-template-columns:118px 1fr; gap:4px 14px; padding:10px 2px; border-bottom:1px solid var(--line); font-size:14px; }
.rrow .when { color:var(--faint); font-size:12.5px; font-variant-numeric:tabular-nums; }
.rrow .t a { color:var(--text); font-weight:500; text-decoration:none; } .rrow .t a:hover { text-decoration:underline; color:var(--accent); }
.rrow .sum { color:var(--muted); font-size:13px; margin-top:2px; }
.src { display:inline-block; font-size:11.5px; font-weight:600; letter-spacing:.02em; padding:2px 8px; border-radius:6px; background:var(--surface-2); color:var(--muted); margin-right:6px; }
.newdot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--accent); margin-right:6px; vertical-align:middle; }
.movers { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
@media (max-width:760px) { .movers { grid-template-columns:1fr; } .arow { grid-template-columns:1fr; gap:2px; } .rrow { grid-template-columns:1fr; } }
.mrow { display:flex; justify-content:space-between; gap:10px; padding:6px 0; border-bottom:1px solid var(--line); font-size:13.5px; }
.empty { padding:16px; text-align:center; color:var(--faint); border:1px dashed var(--line); border-radius:10px; }
.srcs { display:grid; gap:4px; font-size:13px; }
.srcs .bad { color:var(--critical); }
.lookup-out { margin-top:10px; }
@media print { .fchips, .toolbar, #lookup { display:none !important; } .arow, .rrow { break-inside:avoid; } }
</style>
</head>
<body>
<header><div class="wrap">
  <nav class="nav no-print"><a href="/">Model portfolios</a><a href="/builder.html">Builder</a><a href="/compare.html">Compare</a><a href="/brief.html" aria-current="page">Daily brief</a><a href="/quality.html">Quality review</a></nav>
  <h1 id="h1">Daily brief</h1>
  <p class="lede">Today's key numbers, what the holdings told the market, and what changed for financial advice.</p>
  <div class="meta" id="meta"></div>
  <div class="meta">Personal learning project. Headlines link to their publishers; nothing here is financial advice. Check anything you rely on at its source.</div>
</div></header>
<main class="wrap">

<section class="no-print">
  <div class="toolbar" style="margin:0">
    <button class="btn primary" id="btn-xlsx" type="button">Download the brief as Excel</button>
    <button class="btn" id="btn-print" type="button">Print or save as PDF</button>
    <a class="btn" href="/data/brief.json" download>Raw data (JSON)</a>
  </div>
</section>

<section id="numbers">
  <div class="eyebrow">Key numbers</div>
  <h2>Where things closed</h2>
  <div class="groups" id="groups"></div>
  <div class="coming" id="coming"></div>
</section>

<section id="moves">
  <div class="eyebrow">The model portfolios' holdings</div>
  <h2 id="moves-title">Biggest moves today</h2>
  <div class="movers" id="movers"></div>
  <p class="muted" id="breadth" style="font-size:12.5px;margin:8px 0 0"></p>
</section>

<section id="anns">
  <div class="eyebrow">Company announcements</div>
  <h2>What the holdings told the market this week</h2>
  <p class="sub">Every ASX announcement in the last seven days from the companies, ETFs and listed investment companies in the model portfolios' universe. Price-sensitive announcements are the ones the ASX flags as likely to move the share price.</p>
  <div class="fchips" id="afilters"></div>
  <div class="alist" id="alist"></div>
  <div id="lookup" style="margin-top:18px">
    <div class="eyebrow">Look up any ASX code</div>
    <div class="fchips"><input id="lcode" type="search" placeholder="ASX code, for example CBA" maxlength="6" autocomplete="off"><button type="button" id="btn-look" class="btn small primary">Show announcements</button></div>
    <div class="lookup-out" id="lout"></div>
  </div>
</section>

<section id="market">
  <div class="eyebrow">Whole market</div>
  <h2 id="mkt-title">Price-sensitive announcements</h2>
  <p class="sub">Every price-sensitive announcement on the ASX on the latest trading day. Companies in the model portfolios' universe are shaded.</p>
  <div class="fchips" id="mfilters"></div>
  <div class="alist" id="mlist"></div>
</section>

<section id="reg">
  <div class="eyebrow">Regulation, law and policy</div>
  <h2>What changed for financial advice</h2>
  <p class="sub">The last 30 days from ASIC (media releases, and financial advice enforcement and bannings), APRA, the Treasurer and the Financial Services minister, open Treasury consultations, new legislative instruments, Federal Court judgments involving ASIC, the Commissioner of Taxation or superannuation, the RBA, the FAAA, and ATO and AFCA news. A dot marks the last two days.</p>
  <div class="fchips" id="rfilters"></div>
  <div class="alist" id="rlist"></div>
</section>

<section id="wrapsec">
  <div class="eyebrow">Market wrap</div>
  <h2>How the day was reported</h2>
  <div class="alist" id="wlist"></div>
</section>

<section id="sources" class="no-print">
  <div class="eyebrow">Sources</div>
  <h2>Where this came from</h2>
  <p class="sub">Each source is fetched separately; one that fails or blocks the request is listed here and the rest of the brief still builds. Yahoo Finance and the ASX announcement feed are unofficial; the RBA, ABS, ASIC, APRA, Treasury, the Federal Court and the Federal Register of Legislation are official. ATO and AFCA refuse automated requests, so their items come from Google News.</p>
  <div class="srcs" id="srcs"></div>
</section>

</main>
<div class="toast" id="toast" style="position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--text);color:var(--bg);padding:10px 16px;border-radius:10px;font-size:13.5px;display:none;z-index:20"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>
const B = __DATA__;
const sel = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const FN = (() => { const h = location.hostname; return (h.endsWith("netlify.app") || h.endsWith(".app") || h.includes(".")) && !location.protocol.startsWith("file") ? "/.netlify/functions" : null; })();
let toastT; function toast(m){ const t = sel("toast"); t.textContent = m; t.style.display = "block"; clearTimeout(toastT); toastT = setTimeout(() => t.style.display = "none", 3200); }
const D = s => s ? new Date(s) : null;
const fmtWhen = s => { const d = D(s); if (!d || isNaN(d)) return ""; return d.toLocaleDateString("en-AU", { day: "numeric", month: "short", timeZone: "Australia/Brisbane" }) + (s.length > 10 ? " " + d.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit", timeZone: "Australia/Brisbane" }) : ""); };
const fmtDay = s => { const d = D(s); return d && !isNaN(d) ? d.toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Australia/Brisbane" }) : ""; };
const num = (v, d) => v == null || isNaN(v) ? "–" : v.toLocaleString("en-AU", { minimumFractionDigits: d, maximumFractionDigits: d });
const isRecent = (s, days) => { const d = D(s); return d && (Date.now() - d.getTime()) < days * 86400000; };

// ---- header
sel("h1").textContent = "Daily brief: " + fmtDay(B.generated_at);
const okN = B.sources.filter(s => s.ok).length;
sel("meta").textContent = `Built ${fmtWhen(B.generated_at)} Brisbane time from ${okN} of ${B.sources.length} sources.`;

// ---- key numbers
function valueText(n){ if (n.value == null) return "–"; if (n.unit === "%") return num(n.value, n.decimals ?? 2) + "%"; const pre = (n.unit === "USD" || n.unit === "AUD") && !/AUD\/USD/.test(n.label) ? "$" : ""; return pre + num(n.value, n.decimals ?? 2); }
function changeText(n){ if (n.change == null) return ""; const up = n.change > 0, dn = n.change < 0; const arrow = up ? "▲" : dn ? "▼" : "■";
  const body = n.unit === "%" ? `${n.change > 0 ? "+" : ""}${num(n.change * 100, 0)} basis points` : `${n.change > 0 ? "+" : ""}${num(n.change, n.decimals ?? 2)}${n.change_pct != null ? ` (${n.change_pct > 0 ? "+" : ""}${num(n.change_pct, 2)}%)` : ""}`;
  const cls = n.unit === "%" ? "" : up ? "up" : dn ? "down" : "";   // a rise in a rate or in unemployment is not "good", so rates stay neutral
  return `<span class="chg ${cls}">${arrow} ${body}</span>`; }
const GROUPS = ["Markets", "Commodities and rates", "Australian economy"];
sel("groups").innerHTML = GROUPS.map(g => { const ns = B.numbers.filter(n => n.group === g); if (!ns.length) return "";
  return `<div><div class="eyebrow" style="margin-bottom:6px">${g}</div><div class="numtiles">${ns.map(n => `<div class="tile"><div class="k">${esc(n.label)}</div><div class="v">${valueText(n)}</div><div class="s">${changeText(n)}${n.note ? "<br>" + esc(n.note) : ""}${n.as_of ? `<br><span style="color:var(--faint)">${fmtWhen(n.as_of)}</span>` : ""}</div></div>`).join("")}</div></div>`; }).join("") || `<div class="empty">No market numbers could be fetched today.</div>`;
const ex = B.extra || {}; const coming = [];
if (ex.next_rba_decision) coming.push(`<span>Next RBA decision: <b>${fmtDay(ex.next_rba_decision)}</b></span>`);
(ex.abs_upcoming || []).slice(0, 5).forEach(x => coming.push(`<span>${esc(x.name)}: <b>${D(x.date).toLocaleDateString("en-AU", { day: "numeric", month: "short" })}</b></span>`));
sel("coming").innerHTML = coming.length ? "<b>Coming up</b> " + coming.join("") : "";

// ---- movers
const M = B.movers || {};
if (M.up && M.up.length) { sel("moves-title").textContent = `Biggest moves on ${fmtDay(M.as_of)}`;
  const col = (title, rows, cls) => `<div><div class="eyebrow">${title}</div>${rows.map(r => `<div class="mrow"><span><b class="mono">${esc(r.ticker.replace(/\.AX$/, ""))}</b> ${esc(r.name)}</span><span class="chg ${cls}">${r.change_pct > 0 ? "+" : ""}${num(r.change_pct, 2)}%</span></div>`).join("")}</div>`;
  sel("movers").innerHTML = col("Up the most", M.up, "up") + col("Down the most", M.down, "down");
  sel("breadth").textContent = `${M.breadth.up} holdings rose, ${M.breadth.down} fell${M.breadth.flat ? ", " + M.breadth.flat + " were unchanged" : ""}. Last close against the one before, in each holding's own currency.`;
} else sel("moves").hidden = true;

// ---- announcements
const ROUTINE = /^(Distribution Announcement|Issued Capital|Security Holder Details|Dividend Announcement)$/i;   // distributions, buy-back tallies, substantial holder notices
const AF = { ps: false, today: false, q: "", routine: false };
function annRow(a, heldShade){ return `<div class="arow ${heldShade && a.held ? "held" : ""}"><span class="when">${fmtWhen(a.date)}</span><span class="code">${esc(a.code)}</span><span><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.headline)}</a> <span class="co">${esc(a.name)}${a.type ? ", " + esc(a.type) : ""}</span></span><span>${a.price_sensitive ? '<span class="chip serious">price sensitive</span>' : ""}</span></div>`; }
function renderAnns(){ const latestDay = (B.announcements[0] || {}).date ? D(B.announcements[0].date).toLocaleDateString("en-AU", { timeZone: "Australia/Brisbane" }) : "";
  const q = AF.q.trim().toUpperCase();
  const rows = B.announcements.filter(a => (AF.routine || !ROUTINE.test(a.type || "")) && (!AF.ps || a.price_sensitive) && (!AF.today || D(a.date).toLocaleDateString("en-AU", { timeZone: "Australia/Brisbane" }) === latestDay) && (!q || a.code.includes(q) || (a.name || "").toUpperCase().includes(q) || a.headline.toUpperCase().includes(q)));
  sel("alist").innerHTML = rows.length ? rows.map(a => annRow(a, false)).join("") : `<div class="empty">No announcements match.</div>`;
  const nps = B.announcements.filter(a => a.price_sensitive).length;
  sel("afilters").innerHTML = `<button type="button" data-f="ps" aria-pressed="${AF.ps}">Price sensitive only (${nps})</button><button type="button" data-f="today" aria-pressed="${AF.today}">Latest day only</button><button type="button" data-f="routine" aria-pressed="${AF.routine}" title="Fund distributions, issued capital and buy-back notices, substantial holder notices">Show routine notices (${B.announcements.filter(a => ROUTINE.test(a.type || "")).length})</button><input id="aq" type="search" placeholder="Filter by code, company or words" value="${esc(AF.q)}"><span class="muted" style="font-size:12.5px">${rows.length} of ${B.announcements.length}</span>`;
  sel("afilters").querySelectorAll("button[data-f]").forEach(b => b.onclick = () => { AF[b.dataset.f] = !AF[b.dataset.f]; renderAnns(); });
  const aq = sel("aq"); aq.oninput = () => { AF.q = aq.value; const pos = aq.selectionStart; renderAnns(); const n = sel("aq"); n.focus(); n.setSelectionRange(pos, pos); }; }
renderAnns();
sel("btn-look").onclick = async () => { const code = sel("lcode").value.trim().toUpperCase().replace(/\.AX$/, ""); if (!/^[A-Z0-9]{2,6}$/.test(code)) { toast("Enter an ASX code such as CBA"); return; }
  if (!FN) { toast("Live lookups work on the published site"); return; } sel("lout").innerHTML = `<div class="muted">Fetching ${code}…</div>`;
  try { const r = await fetch(FN + "/asx?code=" + encodeURIComponent(code)); const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText);
    const h = j.header || {}; sel("lout").innerHTML = `<div style="margin-bottom:6px"><b>${esc(j.name || code)}</b>${h.priceLast != null ? `, last $${num(h.priceLast, 3)} ${h.priceChangePercent != null ? `<span class="chg ${h.priceChangePercent > 0 ? "up" : h.priceChangePercent < 0 ? "down" : ""}">${h.priceChangePercent > 0 ? "+" : ""}${num(h.priceChangePercent, 2)}%</span>` : ""}` : ""}</div><div class="alist">${(j.items || []).map(a => annRow(a, false)).join("") || '<div class="empty">No recent announcements.</div>'}</div>`;
  } catch (e) { sel("lout").innerHTML = `<div class="empty">Could not fetch ${esc(code)}: ${esc(e.message)}</div>`; } };
sel("lcode").onkeydown = e => { if (e.key === "Enter") sel("btn-look").click(); };

// ---- whole market
const MF = { held: false };
function renderMkt(){ const all = B.market_price_sensitive || []; if (!all.length) { sel("market").hidden = true; return; }
  sel("mkt-title").textContent = `Price-sensitive announcements on ${fmtDay(all[0].date)}`;
  const rows = all.filter(a => !MF.held || a.held);
  sel("mfilters").innerHTML = `<button type="button" aria-pressed="${MF.held}" id="mheld">Only companies in the universe (${all.filter(a => a.held).length})</button><span class="muted" style="font-size:12.5px">${rows.length} of ${all.length}</span>`;
  sel("mheld").onclick = () => { MF.held = !MF.held; renderMkt(); };
  sel("mlist").innerHTML = rows.map(a => annRow(a, true)).join("") || `<div class="empty">None.</div>`; }
renderMkt();

// ---- regulatory
const RF = { src: "", relevant: true, all: false };
function renderReg(){ const all = B.regulatory || []; const srcs = [...new Set(all.map(r => r.source))];
  const match = all.filter(r => (!RF.src || r.source === RF.src) && (!RF.relevant || r.relevant)); const rows = RF.all ? match : match.slice(0, 40);
  sel("rfilters").innerHTML = `<button type="button" data-s="" aria-pressed="${RF.src === ""}">All (${all.length})</button>` + srcs.map(s => `<button type="button" data-s="${esc(s)}" aria-pressed="${RF.src === s}">${esc(s)} (${all.filter(r => r.source === s).length})</button>`).join("") + `<button type="button" id="rrel" aria-pressed="${RF.relevant}">Advice-related only</button>` + (match.length > rows.length || RF.all ? `<button type="button" id="rall" aria-pressed="${RF.all}">${RF.all ? "Show the latest 40" : "Show all " + match.length}</button>` : "");
  sel("rfilters").querySelectorAll("button[data-s]").forEach(b => b.onclick = () => { RF.src = b.dataset.s; renderReg(); }); sel("rrel").onclick = () => { RF.relevant = !RF.relevant; renderReg(); }; if (sel("rall")) sel("rall").onclick = () => { RF.all = !RF.all; renderReg(); };
  sel("rlist").innerHTML = rows.length ? rows.map(r => `<div class="rrow"><span class="when">${r.date ? fmtWhen(r.date.slice(0, 10)) : ""}</span><span><span class="t">${isRecent(r.date, 2) ? '<span class="newdot" title="Last two days"></span>' : ""}<span class="src">${esc(r.source)}</span>${r.tag ? `<span class="src" style="font-weight:500">${esc(r.tag)}</span>` : ""}<a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.title)}</a></span>${r.summary ? `<div class="sum">${esc(r.summary)}</div>` : ""}</span></div>`).join("") : `<div class="empty">Nothing matches.</div>`; }
renderReg();

// ---- wrap
sel("wlist").innerHTML = (B.wrap || []).map(w => `<div class="rrow"><span class="when">${fmtWhen(w.date)}</span><span class="t"><span class="src">${esc(w.source)}</span><a href="${esc(w.link)}" target="_blank" rel="noopener">${esc(w.title)}</a></span></div>`).join("") || `<div class="empty">No market wrap headlines today.</div>`;

// ---- sources
sel("srcs").innerHTML = B.sources.map(s => `<div class="${s.ok ? "" : "bad"}">${s.ok ? "✓" : "✗"} ${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>` : esc(s.name)}${s.ok ? `, ${s.items} item${s.items === 1 ? "" : "s"}` : ""}${s.note ? ", " + esc(s.note) : ""}</div>`).join("");

// ---- downloads
sel("btn-print").onclick = () => window.print();
sel("btn-xlsx").onclick = () => { if (typeof XLSX === "undefined") { toast("The spreadsheet library did not load"); return; } const wb = XLSX.utils.book_new();
  const add = (rows, name, cols) => { const ws = XLSX.utils.aoa_to_sheet(rows); if (cols) ws["!cols"] = cols.map(w => ({ wch: w })); XLSX.utils.book_append_sheet(wb, ws, name); };
  add([["Daily brief", fmtDay(B.generated_at)], ["Built", B.generated_at], [], ["Measure", "Latest", "Previous", "Change", "Change %", "Unit", "As at", "Note", "Source"]].concat(B.numbers.map(n => [n.label, n.value, n.prev, n.change, n.change_pct == null ? null : n.change_pct / 100, n.unit, n.as_of || "", n.note || "", n.source])).concat([[], ["Next RBA decision", ex.next_rba_decision || ""]]).concat((ex.abs_upcoming || []).map(x => ["ABS release: " + x.name, x.date])), "Key numbers", [40, 14, 14, 12, 10, 8, 22, 60, 40]);
  add([["Date", "Code", "Company", "Headline", "Type", "Price sensitive", "Link"]].concat(B.announcements.map(a => [a.date, a.code, a.name, a.headline, a.type, a.price_sensitive ? "yes" : "", a.url])), "Holdings announcements", [18, 8, 30, 70, 22, 12, 60]);
  add([["Date", "Code", "Company", "Headline", "In universe", "Link"]].concat((B.market_price_sensitive || []).map(a => [a.date, a.code, a.name, a.headline, a.held ? "yes" : "", a.url])), "Market price sensitive", [18, 8, 30, 70, 10, 60]);
  add([["Date", "Source", "Type", "Title", "Summary", "Advice related", "Link"]].concat((B.regulatory || []).map(r => [r.date, r.source, r.tag, r.title, r.summary, r.relevant ? "yes" : "", r.link])), "Regulation and law", [18, 16, 18, 70, 70, 10, 60]);
  add([["Date", "Source", "Headline", "Link"]].concat((B.wrap || []).map(w => [w.date, w.source, w.title, w.link])), "Market wrap", [18, 16, 80, 60]);
  if (M.up) add([["Ticker", "Holding", "Change %", "Last price"]].concat(M.up.concat(M.down).map(r => [r.ticker, r.name, r.change_pct / 100, r.price])), "Moves", [12, 36, 10, 12]);
  add([["Source", "Status", "Items", "Note", "Link"]].concat(B.sources.map(s => [s.name, s.ok ? "ok" : "unavailable", s.items, s.note, s.url])), "Sources", [50, 12, 8, 60, 60]);
  XLSX.writeFile(wb, `daily_brief_${B.date}.xlsx`); toast("Downloaded"); };
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


def write_brief(path: Path, data: dict) -> Path:
    page = TEMPLATE.replace("__CSS__", _css()).replace("__DATA__", json.dumps(data, default=str).replace("</", "<\\/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
