import { json } from "./_yahoo.mjs";
// GET /.netlify/functions/asx?code=CBA -> the company's latest ASX announcements and price snapshot, for the Daily brief's lookup box.
// Uses the same public endpoints as the ASX website; responses are cached for five minutes.
const API = "https://asx.api.markitdigital.com/asx-research/1.0";
const HEADERS = { "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36", "Accept": "application/json" };

export default async (req) => {
  const code = (new URL(req.url).searchParams.get("code") || "").trim().toUpperCase().replace(/\.AX$/, "");
  if (!/^[A-Z0-9]{2,6}$/.test(code)) return json({ error: "an ASX code such as CBA is required" }, 400);
  try {
    const [a, h, ks, ab] = await Promise.all([
      fetch(`${API}/companies/${code.toLowerCase()}/announcements`, { headers: HEADERS }),
      fetch(`${API}/companies/${code.toLowerCase()}/header`, { headers: HEADERS }),
      fetch(`${API}/companies/${code.toLowerCase()}/key-statistics`, { headers: HEADERS }).catch(() => null),
      fetch(`${API}/companies/${code.toLowerCase()}/about`, { headers: HEADERS }).catch(() => null),
    ]);
    const data = async r => (r && r.ok ? ((await r.json().catch(() => ({}))).data || {}) : {});
    const [k, about] = await Promise.all([data(ks), data(ab)]);
    const header = h.ok ? ((await h.json().catch(() => ({}))).data || {}) : {};
    // Listed notes, hybrids and bonds sometimes have a price but no announcements feed: the price is enough for the builder.
    if (!a.ok && header.priceLast == null) return json({ error: a.status === 404 ? `no ASX listing found for ${code}` : `the ASX returned ${a.status}` }, a.status === 404 ? 404 : 502);
    const d = a.ok ? ((await a.json().catch(() => ({}))).data || {}) : { displayName: header.displayName || header.name || code, items: [] };
    const items = (d.items || []).map(it => ({
      code, name: d.displayName || "", headline: it.headline || "", date: it.date, price_sensitive: !!it.isPriceSensitive,
      type: (it.announcementType || "").replace(/\b\w+/g, w => w[0] + w.slice(1).toLowerCase()),
      url: it.documentKey ? `${API}/file/${it.documentKey}` : "",
    }));
    // The same facts the daily build keeps for every ASX holding (portfolio_engine/asx_facts.py): last dividend and its franking,
    // dates, yield, P/E, 52 week range, security type and terms, issuer description, sector and listing date.
    const n = v => (v == null || v === -32768 ? null : v);
    const KIND = { CS: "share", ETF: "ETF", PR: "hybrid or preference security", FLC: "listed note", FRG: "government bond", UT: "unit trust", SP: "stapled security" };
    const facts = Object.fromEntries(Object.entries({
      issue_type: about.issueType || "", kind: KIND[about.issueType] || "", security: (k.shareDescription || "").trim(), description: (about.description || "").trim().slice(0, 600),
      sector: header.sector || "", industry: header.industryGroup || "", listed: header.dateListed || "", isin: k.isin || "",
      market_cap: n(header.marketCap) || null, price: n(header.priceLast), last_dividend: k.dividend ?? null, dividend_currency: k.dividendCurrency || "",
      dividend_type: k.dividendType || "", franking_pct: k.frankingPercent ?? null, ex_date: k.dateExDate || "", pay_date: k.datePayDate || "",
      yield_pct: typeof k.yieldAnnual === "number" ? +k.yieldAnnual.toFixed(2) : null, pe: typeof k.priceEarningsRatio === "number" ? +k.priceEarningsRatio.toFixed(1) : null,
      high_52w: n(k.priceFiftyTwoWeekHigh), low_52w: n(k.priceFiftyTwoWeekLow), fetched: new Date().toISOString().slice(0, 10),
    }).filter(([, v]) => v !== "" && v != null));
    return json({ code, name: d.displayName || header.displayName || code, header: { priceLast: header.priceLast ?? null, priceChangePercent: header.priceChangePercent ?? null, marketCap: header.marketCap ?? null }, facts, items }, 200, 300);
  } catch (e) {
    return json({ error: String(e.message || e) }, 502);
  }
};
